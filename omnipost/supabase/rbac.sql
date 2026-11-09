-- =============================================================================
-- VBL Law Chambers — role separation via Supabase Auth + Row Level Security
--
-- Run in the Supabase dashboard -> SQL Editor, AFTER schema.sql.
--
-- WHAT THIS CHANGES
-- -----------------
-- Access was two shared passkeys held in environment variables. That works,
-- but it cannot do three things a law practice needs:
--
--   * revoke ONE person (a departing assistant) without re-keying everyone,
--   * say WHO opened a client's file, and
--   * keep a credential out of CI — the publishing heartbeat needs one, and a
--     shared key in CI is a shared key with a wider blast radius.
--
-- So each person gets a Supabase Auth account carrying a role, and the same
-- separation is enforced a second time in the database itself.
--
-- THE TWO ROLES (chambers is a superset, deliberately — the principal advocate
-- owns both surfaces)
--
--   chambers    wills, testator PII, documents, Drive lockers, AND publishing
--   automation  the content calendar and publishing engine, NOTHING ELSE.
--               A social media assistant must never reach a partition deed.
--
-- WHERE THE ROLE LIVES — and why it is not user_metadata
-- -----------------------------------------------------
-- The role is stored in app_metadata. That field is writable only with the
-- service-role key. user_metadata is writable by the user themselves via
-- supabase.auth.updateUser(), so a role kept there could be self-granted by
-- any account holder. Reading the role from user_metadata would hand every
-- signed-up user the keys to the client vault.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Role accessor
-- ---------------------------------------------------------------------------
-- STABLE, not VOLATILE, so the planner may cache it per statement.
-- SECURITY INVOKER (the default) is correct: it must see the CALLER's JWT.
CREATE OR REPLACE FUNCTION public.vbl_role()
RETURNS text
LANGUAGE sql
STABLE
SET search_path = public, pg_catalog
AS $fn$
  SELECT coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb
      -> 'app_metadata' ->> 'vbl_role',
    ''
  );
$fn$;

COMMENT ON FUNCTION public.vbl_role() IS
  'Caller chambers role from JWT app_metadata: chambers | automation | empty. app_metadata is service-role-writable only; never read a role from user_metadata.';

-- chambers is a superset of automation.
CREATE OR REPLACE FUNCTION public.vbl_has_role(required text)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public, pg_catalog
AS $fn$
  SELECT CASE public.vbl_role()
           WHEN 'chambers'   THEN required IN ('chambers', 'automation')
           WHEN 'automation' THEN required =  'automation'
           ELSE false
         END;
$fn$;

REVOKE ALL ON FUNCTION public.vbl_role()            FROM public;
REVOKE ALL ON FUNCTION public.vbl_has_role(text)    FROM public;
GRANT EXECUTE ON FUNCTION public.vbl_role()         TO authenticated;
GRANT EXECUTE ON FUNCTION public.vbl_has_role(text) TO authenticated;

-- ---------------------------------------------------------------------------
-- 2. Privileges
--
-- RLS filters ROWS; it does not grant the privilege to touch the table at all.
-- Both are required, so the grant is the outer gate and the policy the inner
-- one. `anon` is granted nothing anywhere: an unauthenticated caller holding
-- only the publishable key reads nothing, which is the current behaviour and
-- must not regress.
-- ---------------------------------------------------------------------------
REVOKE ALL ON public.will_submissions     FROM anon, authenticated;
REVOKE ALL ON public.submission_documents FROM anon, authenticated;
REVOKE ALL ON public.content_calendar     FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.will_submissions     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.submission_documents TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.content_calendar     TO authenticated;

-- ---------------------------------------------------------------------------
-- 3. Policies
-- ---------------------------------------------------------------------------
ALTER TABLE public.will_submissions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.submission_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.content_calendar     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "chambers_all_submissions" ON public.will_submissions;
DROP POLICY IF EXISTS "chambers_all_documents"   ON public.submission_documents;
DROP POLICY IF EXISTS "publishing_all_calendar"  ON public.content_calendar;

-- The client legal vault. chambers ONLY.
-- There is deliberately no automation policy here: a missing policy is a deny,
-- and that is precisely the intent.
CREATE POLICY "chambers_all_submissions" ON public.will_submissions
  FOR ALL TO authenticated
  USING      (public.vbl_has_role('chambers'))
  WITH CHECK (public.vbl_has_role('chambers'));

CREATE POLICY "chambers_all_documents" ON public.submission_documents
  FOR ALL TO authenticated
  USING      (public.vbl_has_role('chambers'))
  WITH CHECK (public.vbl_has_role('chambers'));

-- The content calendar. Both roles — chambers because it is a superset.
CREATE POLICY "publishing_all_calendar" ON public.content_calendar
  FOR ALL TO authenticated
  USING      (public.vbl_has_role('automation'))
  WITH CHECK (public.vbl_has_role('automation'));

-- ---------------------------------------------------------------------------
-- 4. Granting a role to a person
--
-- Create the user first (Authentication -> Users -> Add user), then:
--
--   UPDATE auth.users
--      SET raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb)
--                              || '{"vbl_role":"chambers"}'::jsonb
--    WHERE email = 'advocate@vbllawchambers.com';
--
--   UPDATE auth.users
--      SET raw_app_meta_data = coalesce(raw_app_meta_data, '{}'::jsonb)
--                              || '{"vbl_role":"automation"}'::jsonb
--    WHERE email = 'assistant@vbllawchambers.com';
--
-- To revoke one person, delete or ban that user. No re-keying, and the other
-- accounts are untouched.
--
-- The role is read from the JWT, so it takes effect on that user's NEXT token,
-- not immediately on an already-issued one. Tokens are short-lived (1h by
-- default); for an urgent revocation, ban the user in the dashboard.
--
-- >> DISABLE PUBLIC SIGN-UPS <<
-- Authentication -> Providers -> Email -> turn OFF "Enable sign ups".
-- Otherwise anyone can create an account. They would hold no vbl_role and the
-- policies above would deny them everything — but an unbounded supply of
-- authenticated identities against a legal vault is not a thing to leave on.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 5. Self-test — proves the separation rather than assuming it.
--
-- Run this whole block in the SQL Editor. It impersonates each role by setting
-- the JWT claims the way PostgREST does, and RAISES if any expectation fails.
-- ---------------------------------------------------------------------------
DO $test$
DECLARE
  chambers_jwt   text := '{"role":"authenticated","app_metadata":{"vbl_role":"chambers"}}';
  automation_jwt text := '{"role":"authenticated","app_metadata":{"vbl_role":"automation"}}';
  stranger_jwt   text := '{"role":"authenticated","app_metadata":{}}';
BEGIN
  PERFORM set_config('request.jwt.claims', chambers_jwt, true);
  IF NOT public.vbl_has_role('chambers')   THEN RAISE EXCEPTION 'chambers must hold chambers';   END IF;
  IF NOT public.vbl_has_role('automation') THEN RAISE EXCEPTION 'chambers must be a superset';   END IF;

  PERFORM set_config('request.jwt.claims', automation_jwt, true);
  IF     public.vbl_has_role('chambers')   THEN RAISE EXCEPTION 'automation must NOT reach the client vault'; END IF;
  IF NOT public.vbl_has_role('automation') THEN RAISE EXCEPTION 'automation must hold automation'; END IF;

  PERFORM set_config('request.jwt.claims', stranger_jwt, true);
  IF public.vbl_has_role('chambers')   THEN RAISE EXCEPTION 'a roleless account must hold nothing'; END IF;
  IF public.vbl_has_role('automation') THEN RAISE EXCEPTION 'a roleless account must hold nothing'; END IF;

  PERFORM set_config('request.jwt.claims', '', true);
  IF public.vbl_has_role('automation') THEN RAISE EXCEPTION 'an anonymous caller must hold nothing'; END IF;

  RAISE NOTICE 'RBAC self-test passed: chambers superset, automation confined, strangers denied.';
END
$test$;
