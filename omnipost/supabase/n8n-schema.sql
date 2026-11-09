-- =============================================================================
-- VBL Law Chambers — isolated n8n schema inside the chambers Supabase project
--
-- Run this ONCE, in the Supabase dashboard -> SQL Editor, BEFORE starting n8n
-- against this project.
--
-- WHY A SEPARATE SCHEMA
-- ---------------------
-- n8n creates ~30 tables of its own (execution_entity, workflow_entity,
-- credentials_entity, migrations, insights_*, …). Left in `public` they sit
-- beside will_submissions and content_calendar, where:
--
--   * `credentials_entity` — which holds the ENCRYPTED Google Drive, YouTube
--     and Meta credentials — would live in the same schema PostgREST exposes.
--   * A future `schema.sql` re-run, or any "drop everything in public and
--     recreate" recovery step, would take n8n's workflow history with it.
--   * `SELECT * FROM information_schema.tables WHERE table_schema='public'`
--     stops being a meaningful description of the legal application.
--
-- n8n does NOT create the schema itself — it expects to find it and fails its
-- first migration if it is absent. Hence this file.
--
-- WHY NOT NEON
-- ------------
-- n8n was previously pointed at a separate Neon project. That meant two
-- databases, two backup stories and two things to keep alive, for a workflow
-- engine that already has to reach this project anyway. One Postgres is fewer
-- moving parts and stays inside the free tier.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS n8n;

COMMENT ON SCHEMA n8n IS
  'n8n workflow engine internal tables. Not part of the legal application. '
  'Never expose this schema through PostgREST - credentials_entity lives here.';

-- The pooler user (postgres.<project-ref>) resolves to the `postgres` role.
GRANT ALL ON SCHEMA n8n TO postgres;
ALTER SCHEMA n8n OWNER TO postgres;

-- ---------------------------------------------------------------------------
-- Keep it off the public API surface.
--
-- Supabase exposes only `public` (and graphql_public) through PostgREST by
-- default, so this is belt and braces — but the cost of being wrong here is
-- every stored OAuth credential being one API call away, so it is stated
-- explicitly rather than assumed.
--
-- Do NOT add "n8n" to Settings -> API -> Exposed schemas.
-- ---------------------------------------------------------------------------
REVOKE ALL ON SCHEMA n8n FROM anon, authenticated, public;
ALTER DEFAULT PRIVILEGES IN SCHEMA n8n REVOKE ALL ON TABLES    FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA n8n REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA n8n REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- Verification — run after n8n has booted once and completed its migrations.
-- ---------------------------------------------------------------------------
-- Expect ~30 tables here, and ZERO n8n tables in public:
--
--   SELECT table_schema, count(*)
--     FROM information_schema.tables
--    WHERE table_schema IN ('public','n8n')
--    GROUP BY table_schema;
--
--   SELECT table_name FROM information_schema.tables
--    WHERE table_schema='public' AND table_name LIKE '%entity%';   -- expect 0 rows
--
-- Size check — the free tier is 500 MB shared with the legal tables:
--
--   SELECT pg_size_pretty(sum(pg_total_relation_size(c.oid))) AS n8n_size
--     FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
--    WHERE n.nspname = 'n8n';
