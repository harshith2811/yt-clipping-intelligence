# Hybrid Storage — Supabase + Google Drive

## The contract

| Lives in | What | Why |
|---|---|---|
| **Supabase PostgreSQL** | Testator particulars, `VBL-XXXXXX` references, legal service types, scrutiny stages, document *descriptors* (name, size, MIME), and the Google Drive folder/file IDs | Relational, queryable, tiny. Stays inside the free tier indefinitely. |
| **Google Drive vault** | Every heavy binary — will PDFs, title deeds, pattadar passbooks, social video | A single registered sale deed scan can be 5 MB. A few hundred of those would exhaust Supabase storage; Drive holds them for free and Meta/Pinterest can fetch media straight from a public URL. |

Nothing large is ever written to Supabase. The tables carry *pointers* into Drive.

- Vault root: `1Q171pLkFgucgHO0bJ1lRWlxC3en-tHZz` (override with `GOOGLE_DRIVE_FOLDER_ID`)
- Per-client subfolder: `[RefId] - [ClientFullName]`, created by the n8n
  `Will Document Ingestion` workflow, which calls back with the real folder id/url.

Until that callback lands, a submission carries the **vault root as a pending
placeholder**, not as the client's own folder. `db.patchSubmission()` is what
replaces it — in both stores. (It previously wrote only to the local JSON cache,
so Supabase kept the placeholder forever.)

## Access model

The browser never talks to Supabase. Both front ends call the Express API, which
holds `SUPABASE_SERVICE_ROLE_KEY`, and `service_role` bypasses RLS by design.

That is the *transport*. Authorisation is enforced in two independent places, so
neither is load-bearing on its own:

| Layer | File | Enforces |
|---|---|---|
| API | [`web/auth.js`](../web/auth.js) | route guards — `requireChambers` / `requireAutomation` |
| Database | [`rbac.sql`](./rbac.sql) | RLS policies keyed on the caller's JWT role |

Roles, with `chambers` deliberately a superset (the principal advocate owns both
surfaces):

| Role | `will_submissions` / `submission_documents` | `content_calendar` |
|---|---|---|
| `chambers` | full | full |
| `automation` | **nothing** | full |
| any other authenticated user | nothing | nothing |
| `anon` (the publishable key) | nothing | nothing |

The role lives in **`app_metadata.vbl_role`** and is read from nowhere else.
`user_metadata` is writable by the user through `supabase.auth.updateUser()`, so
a role kept there could be self-granted by anyone holding an account — which is
the entire client vault, one API call away. `app_metadata` is service-role
writable only.

> ⚠️ Do not add a `TO public USING (true)` policy. The publishable/anon key is
> meant to be embedded in browsers; such a policy hands every client's
> particulars and privileged instructions to anyone who asks. The first draft of
> `schema.sql` carried exactly that on `will_submissions` and
> `submission_documents`, under policy names that read as if they were scoped
> ("Public track own will").

> ⚠️ Turn **off** Authentication → Providers → Email → "Enable sign ups". A
> self-registered account holds no `vbl_role` and the policies deny it
> everything, but an unbounded supply of authenticated identities pointed at a
> legal vault is not a thing to leave switched on.

## n8n shares this database

n8n's workflows, executions and **encrypted credentials** live here too, in a
dedicated `n8n` schema — never in `public`, which is what PostgREST exposes.
See [`n8n-schema.sql`](./n8n-schema.sql).

Connect n8n through the **session pooler**, not the direct host:

| Endpoint | Result from inside a container |
|---|---|
| `db.<ref>.supabase.co:5432` | IPv6-only on the free tier → **unreachable** |
| `aws-0-<region>.pooler.supabase.com:5432` | IPv4, session mode → works |
| same host, port `6543` | transaction mode → breaks n8n's migrations |

The pooler username carries the project ref: `postgres.<project-ref>`. The
password is the **database** password (Settings → Database), which is a
different credential from `SUPABASE_SERVICE_ROLE_KEY` — the service-role key is
a PostgREST API key and will not authenticate a Postgres connection.

Execution history now shares the 500 MB free tier with the legal tables, so
`EXECUTIONS_DATA_PRUNE` is a capacity control, not housekeeping.

## Applying the schema

DDL cannot be executed through the REST API, so this is the one manual step.

1. Open <https://supabase.com/dashboard/project/cmjhgvhtlpayjcrsqgox/sql/new>
2. Run these three, **in order**:

   | # | File | What it does |
   |---|---|---|
   | 1 | [`schema.sql`](./schema.sql) | the legal tables |
   | 2 | [`rbac.sql`](./rbac.sql) | roles + RLS. Ends in a self-test that RAISES if the separation is wrong. |
   | 3 | [`n8n-schema.sql`](./n8n-schema.sql) | the `n8n` schema, **before** n8n first boots — it expects to find it and fails its first migration otherwise. |

3. Verify:

```bash
node automation/supabase/verify-schema.mjs
```

The verifier confirms the tables exist **and** that the anon key can read
nothing from them. It exits non-zero on failure, so it is safe to wire into a
deploy check.

Re-running `schema.sql` is safe: it is idempotent (`IF NOT EXISTS`,
`ON CONFLICT DO NOTHING`) and its `DROP POLICY IF EXISTS` lines actively remove
the earlier permissive policies from an already-provisioned project.

## Until the schema is applied

The system runs on the local JSON cache and says so. `GET /api/health` reports:

```json
"storage": { "backend": "local-cache", "supabaseReachable": true, "schemaReady": false }
```

Once the tables exist, the first read reconciles every cached submission into
Supabase (`reconcileLocalIntoSupabase`), so no existing record is lost when the
source of truth moves.

## Notes

- Timestamps are stored as UTC `timestamptz` and rendered in `Asia/Kolkata` by
  `db.js`. Do **not** reintroduce `DEFAULT timezone('Asia/Kolkata', now())`: that
  yields a naive timestamp which Postgres re-reads in the server zone, skewing
  every record by +5:30.
- `submission_documents` is uniquely keyed on `(submission_ref_id, file_name)`
  so re-syncing a submission updates rows instead of duplicating the whole list.
- Supabase errors are logged, never swallowed. `supabase-js` *resolves* with an
  `{ error }` object rather than throwing, so a bare `try/catch` silently loses
  failed writes — which is how a submission can look saved while never reaching
  the database.
