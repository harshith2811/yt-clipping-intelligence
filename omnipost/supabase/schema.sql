-- ==============================================================================
-- OMNIPOST SOCIAL AUTOMATION - SUPABASE RELATIONAL SCHEMA (metadata only)
-- OmniPost Universal Multi-Platform Social Automation Engine
-- Project: cmjhgvhtlpayjcrsqgox
--
-- HYBRID STORAGE CONTRACT
--   Supabase     -> relational metadata ONLY (testator particulars, ref ids,
--                   scrutiny stages, document *descriptors*, Drive ids/urls).
--   Google Drive -> every heavy binary (will PDFs, title deeds, pattadar
--                   passbooks, social video). Nothing large is stored here,
--                   which is what keeps the Supabase tier viable.
--
-- ACCESS MODEL (read this before adding any policy)
--   The browser NEVER talks to Supabase. Both front ends call the Express API
--   (automation/web/server.js), which holds SUPABASE_SERVICE_ROLE_KEY and is
--   itself guarded by requireAdminAuth. service_role bypasses RLS by design,
--   so these tables need NO permissive policy in order to function.
--   RLS is therefore enabled default-deny: anon / authenticated read nothing.
--   Adding a "TO public USING (true)" policy here would publish every client's
--   privileged instructions to anyone holding the publishable key.
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- 1. Client Will Drafting Submissions (testator particulars + scrutiny state)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS public.will_submissions (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ref_id               VARCHAR(32) UNIQUE NOT NULL,       -- 'VBL-475868'
    -- Stored as absolute UTC instants; rendered in Asia/Kolkata at the app
    -- layer (db.js formats with timeZone:'Asia/Kolkata').
    -- Do NOT wrap now() in timezone('Asia/Kolkata', ...) here: that returns a
    -- naive timestamp which postgres re-reads in the server zone, skewing
    -- every record by +5:30.
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    full_name            TEXT NOT NULL,
    parent_spouse_name   TEXT DEFAULT '',
    age                  VARCHAR(10) DEFAULT 'N/A',
    phone                VARCHAR(32) NOT NULL,
    email                TEXT DEFAULT '',
    city                 TEXT DEFAULT 'Kavali',
    address              TEXT DEFAULT '',
    service_type         VARCHAR(64) NOT NULL,              -- draft_new | review_existing | codicil | family_settlement
    service_label        TEXT NOT NULL,
    asset_types          JSONB DEFAULT '[]'::jsonb,
    executor_name        TEXT DEFAULT '',
    special_instructions TEXT DEFAULT '',
    folder_name          TEXT NOT NULL,                     -- '[RefId] - [ClientFullName]'
    drive_folder_id      TEXT DEFAULT '',                   -- per-client Drive subfolder id
    drive_folder_url     TEXT DEFAULT '',                   -- per-client Drive subfolder url
    -- 'pending' until the client's own "[RefId] - [Name]" folder exists. While
    -- pending the record carries the vault ROOT as a placeholder, which is why
    -- the tracker must not hand driveFolderUrl to the testator - the root holds
    -- every client's locker.
    drive_provision_state VARCHAR(32) DEFAULT 'pending',
    status               VARCHAR(64) NOT NULL DEFAULT 'New Submission'
);

ALTER TABLE public.will_submissions
    ADD COLUMN IF NOT EXISTS drive_provision_state VARCHAR(32) DEFAULT 'pending';

-- Intake v2: WhatsApp contact, family members (collected on the form so no
-- ration card is needed), and per-asset detail (account/folio numbers,
-- nominees, survey numbers) keyed by the asset ids in asset_types.
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS whatsapp       VARCHAR(32) DEFAULT '';
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS family_members JSONB DEFAULT '[]'::jsonb;
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS asset_details  JSONB DEFAULT '{}'::jsonb;

-- Document deficiency checklist. The advocate records what is missing; the
-- client sees it on the tracker (after confirming their mobile number) and
-- uploads the missing papers there. Replaces informal WhatsApp requests.
--   deficiency_status: 'none' | 'pending_client' | 'resolved'
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS deficiencies              JSONB DEFAULT '[]'::jsonb;
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS deficiency_status         VARCHAR(32) DEFAULT 'none';
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS deficiency_updated_at     TIMESTAMPTZ;
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS supplementary_received_at TIMESTAMPTZ;

-- Online payment (Razorpay), unused until ENABLE_ONLINE_PAYMENTS is on.
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS payment_status   VARCHAR(32) DEFAULT 'unpaid';
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS payment_order_id TEXT DEFAULT '';
ALTER TABLE public.will_submissions ADD COLUMN IF NOT EXISTS payment_id       TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_will_submissions_ref     ON public.will_submissions (ref_id);
CREATE INDEX IF NOT EXISTS idx_will_submissions_status  ON public.will_submissions (status);
CREATE INDEX IF NOT EXISTS idx_will_submissions_created ON public.will_submissions (created_at DESC);

-- ==============================================================================
-- 2. Submission Document Descriptors (pointers into the Drive vault)
--    No bytes live here - only name/size/mime plus the Drive id and url.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS public.submission_documents (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submission_ref_id VARCHAR(32) NOT NULL
                      REFERENCES public.will_submissions(ref_id) ON DELETE CASCADE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    file_name         TEXT NOT NULL,
    file_size         TEXT NOT NULL DEFAULT '',             -- display string e.g. '2.1 MB'
    file_size_bytes   BIGINT NOT NULL DEFAULT 0,            -- numeric truth for sorting / quota
    mime_type         TEXT DEFAULT 'application/pdf',
    url               TEXT DEFAULT '',                      -- locally served path
    drive_file_id     TEXT DEFAULT '',
    drive_url         TEXT DEFAULT '',
    folder_name       TEXT DEFAULT '',
    -- A submission is re-synced when n8n returns the real Drive ids. Without
    -- this constraint every re-save duplicated the entire document list.
    CONSTRAINT uq_submission_document UNIQUE (submission_ref_id, file_name)
);

CREATE INDEX IF NOT EXISTS idx_submission_documents_ref ON public.submission_documents (submission_ref_id);

-- True for documents the client uploaded in answer to a deficiency checklist.
ALTER TABLE public.submission_documents ADD COLUMN IF NOT EXISTS is_supplementary BOOLEAN DEFAULT false;

-- ==============================================================================
-- 3. Social Content Calendar
-- ==============================================================================
CREATE TABLE IF NOT EXISTS public.content_calendar (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_id         VARCHAR(32) UNIQUE NOT NULL,         -- 'W-001'
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    scheduled_datetime TIMESTAMPTZ NOT NULL,
    title              TEXT NOT NULL,
    caption            TEXT DEFAULT '',
    platforms          TEXT NOT NULL,                       -- 'instagram,facebook,youtube'
    status             VARCHAR(32) NOT NULL DEFAULT 'Draft',
    drive_file_id      TEXT DEFAULT '',
    retry_count        INT DEFAULT 0,
    posted_at          TIMESTAMPTZ,
    error_log          TEXT DEFAULT '',
    -- Resumable publish state, one entry per channel:
    --   { "instagram": { "state": "pending", "containerId": "...",
    --                    "retryCount": 0, "lastAttemptAt": "...",
    --                    "failureKind": null, "postId": null } }
    -- See automation/web/publishing/state.js. Persisting the container id is
    -- what stops a container that sleeps mid-publish from posting twice.
    platform_statuses  JSONB DEFAULT '{}'::jsonb,
    publish_state      VARCHAR(32) DEFAULT 'queued',        -- rollup across channels
    last_attempt_at    TIMESTAMPTZ,
    failure_kind       VARCHAR(32),                         -- AUTH_EXPIRED | TRANSIENT_NETWORK | FATAL_PAYLOAD
    public_media_url   TEXT DEFAULT '',
    media_type         TEXT DEFAULT '',
    link               TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_content_calendar_sched  ON public.content_calendar (scheduled_datetime DESC);
CREATE INDEX IF NOT EXISTS idx_content_calendar_status ON public.content_calendar (status);

-- Lets the dispatcher find work without scanning the table.
CREATE INDEX IF NOT EXISTS idx_content_calendar_publish_state
    ON public.content_calendar (publish_state)
    WHERE publish_state NOT IN ('completed', 'failed');

-- Idempotent upgrade for projects provisioned before these columns existed.
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS publish_state   VARCHAR(32) DEFAULT 'queued';
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMPTZ;
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS failure_kind    VARCHAR(32);
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS public_media_url TEXT DEFAULT '';
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS media_type       TEXT DEFAULT '';
ALTER TABLE public.content_calendar ADD COLUMN IF NOT EXISTS link             TEXT DEFAULT '';

-- ==============================================================================
-- 4. Row Level Security - DEFAULT DENY
--    Advocate-client privilege + DPDP Act 2023.
--    Enabling RLS with no permissive policy means anon/authenticated read
--    nothing; the Express backend reaches these tables with service_role,
--    which bypasses RLS. The DROP POLICY statements below exist so that
--    re-running this file on an already-provisioned project actually closes
--    the earlier "USING (true)" holes rather than leaving them in place.
-- ==============================================================================
ALTER TABLE public.will_submissions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.submission_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.content_calendar     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public submit wills"                          ON public.will_submissions;
DROP POLICY IF EXISTS "Public track own will"                        ON public.will_submissions;
DROP POLICY IF EXISTS "Chambers staff all operations on submissions" ON public.will_submissions;
DROP POLICY IF EXISTS "Public insert documents"                      ON public.submission_documents;
DROP POLICY IF EXISTS "Public read documents"                        ON public.submission_documents;
DROP POLICY IF EXISTS "Chambers staff all operations on documents"   ON public.submission_documents;
DROP POLICY IF EXISTS "Chambers staff all operations on calendar"    ON public.content_calendar;

-- Belt and braces: revoke the default PostgREST grants so that a mis-added
-- policy later cannot silently expose these tables to the publishable key.
REVOKE ALL ON public.will_submissions     FROM anon, authenticated;
REVOKE ALL ON public.submission_documents FROM anon, authenticated;
REVOKE ALL ON public.content_calendar     FROM anon, authenticated;

-- ==============================================================================
-- 5. updated_at maintenance
-- ==============================================================================
-- search_path is pinned empty (Supabase security advisor lint 0011, "function
-- search path mutable"): otherwise the function resolves names through the
-- CALLER's search_path. now() lives in pg_catalog, which is always searched,
-- so behaviour is unchanged. For an existing database:
--   ALTER FUNCTION public.update_updated_at_column() SET search_path = '';
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER
SET search_path = ''
AS $fn$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_will_submissions_updated_at ON public.will_submissions;
CREATE TRIGGER set_will_submissions_updated_at
BEFORE UPDATE ON public.will_submissions
FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

-- ==============================================================================
-- 6. Baseline content calendar rows (no client PII - safe to keep in git)
-- ==============================================================================
INSERT INTO public.content_calendar
    (content_id, scheduled_datetime, title, caption, platforms, status, drive_file_id, posted_at)
VALUES
    ('W-004', '2026-09-10T09:00:00Z', 'Major Announcement & Product Launch',
     'Excited to unveil our newest feature release! Built to streamline workflows, eliminate friction, and accelerate results. Check it out today! #ProductLaunch #Innovation #Growth',
     'instagram,facebook,youtube,linkedin,threads', 'Posted', '', '2026-09-10T09:02:11Z'),
    ('W-003', '2026-09-11T18:00:00Z', 'Top 5 Actionable Industry Insights',
     'Here are 5 battle-tested strategies to boost engagement, scale your operations, and drive real community growth. #IndustryInsights #Strategy #ProTips',
     'instagram,facebook,linkedin,threads', 'Approved', '', NULL),
    ('W-002', '2026-09-12T14:30:00Z', 'Behind The Scenes: Engineering Our Automation Pipeline',
     'A look inside how we process media, maintain resilience, and automate multi-channel publishing at zero SaaS cost. #Engineering #DevCommunity #BuildInPublic',
     'instagram,facebook,youtube', 'Pending Review', '', NULL),
    ('W-001', '2026-09-14T10:00:00Z', 'Quick Video Tutorial & Walkthrough',
     'Follow this quick step-by-step walkthrough to get started with the new platform workflow in under 3 minutes. #Tutorial #QuickTips #HowTo',
     'instagram,facebook,youtube,linkedin', 'Draft', '', NULL)
ON CONFLICT (content_id) DO NOTHING;
