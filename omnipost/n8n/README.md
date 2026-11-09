# n8n Workflows — Activation & Credentials Runbook

Exported workflow definitions live in [`claude_mcp/`](./claude_mcp). These files are
**exports, not the live instance.** Editing a file here does not change a running
workflow — import it in the n8n UI, or edit the node there directly.

| Environment | URL |
|---|---|
| Local (docker compose) | <http://localhost:5678> |
| Production | <https://n8n.vbllawchambers.com> |

---

## What n8n is still responsible for

Publishing used to run through Postiz, and this runbook used to describe that.
It no longer does. Facebook, Instagram, Threads, LinkedIn and Pinterest are
published **directly** by the chambers portal's own adapters in
[`automation/web/publishing/`](../web/publishing) — no Postiz, no Temporal, no
`Header Auth` credential, no `POSTIZ_API_KEY`. The `Postiz Social Scheduler`
workflow has been deleted; if you still have it imported in a live n8n, **delete
it there too**. Left running it polls every five minutes, calls a host that no
longer exists, writes failure statuses back over the calendar the native engine
is managing, and emails an admin alert every time.

Three things genuinely still belong here, because each needs a Google OAuth
credential that the portal deliberately does not hold:

All four were imported into production on 2026-09-23 through the n8n MCP
server, into the owner's personal project, **unpublished and with no
credentials attached** — the production instance had none. The JSON files
here are exports of exactly those workflows.

| Workflow | n8n id | Trigger | Credentials to attach |
|---|---|---|---|
| **Will Document Ingestion & Chambers Alert** | `zdWT46w4UbV2NGPV` | `POST /webhook/will-submission` | Google Drive, VBL Portal Webhook Key |
| **Content Ingestion Webhook** | `f5mDlezsdqUQVEpE` | `POST /webhook/content-upload`, `GET /webhook/content-list` | Google Drive, Google Sheets, VBL Portal Webhook Key |
| **YouTube Publisher** | `mvAa3hiDPutYTHkj` | Schedule (5 min) + manual | Google Sheets, Google Drive, YouTube, Gmail |
| **Content Approval Requests** | `xn33388wF39RsQVr` | Schedule (15 min) | Google Sheets, Gmail |

Every webhook requires the `X-VBL-Webhook-Key` header (Header Auth). The
portal sends it from `N8N_WEBHOOK_SECRET`. Without that check, anyone who
found the n8n host (it is in public certificate-transparency logs) could file
a video into the calendar marked `Approved`, and the YouTube Publisher would
post it within five minutes.

---

## Where n8n keeps its data

Workflows, executions and **encrypted credentials** live in the chambers
Supabase Postgres, in a dedicated `n8n` schema — not in `public`, where the
legal tables are and where PostgREST is exposed. There is no separate Neon
project any more, and no SQLite file.

Before n8n boots for the first time, run
[`automation/supabase/n8n-schema.sql`](../supabase/n8n-schema.sql) once in the
Supabase SQL editor. n8n expects to FIND the schema and fails its first
migration if it is absent.

Connect through the **session pooler**, from Supabase → Connect → Session pooler:

| | |
|---|---|
| host | `aws-0-<region>.pooler.supabase.com` — **not** `db.<ref>.supabase.co`, which is IPv6-only on the free tier and unreachable from a container |
| port | `5432` (session mode). **Not** `6543`, which is transaction mode and breaks n8n's migrations |
| user | `postgres.<project-ref>` — the suffix is required by the pooler |
| password | the **database** password (Settings → Database), *not* the service-role key |
| schema | `n8n` |

Two consequences worth holding onto:

* `N8N_ENCRYPTION_KEY` is now the only thing not backed up along with the
  database. Lose it and every credential in Supabase becomes unreadable.
* Execution history shares the 500 MB free tier with the client legal tables,
  so `EXECUTIONS_DATA_PRUNE` is a capacity control. An unpruned history can
  fill the database the will registry depends on.

Verify after the first boot:

```sql
SELECT table_schema, count(*) FROM information_schema.tables
 WHERE table_schema IN ('public','n8n') AND table_type='BASE TABLE'
 GROUP BY table_schema;
-- expect: n8n ~31, public 3
```

---

## ⚠️ Step 0 — Activate "Will Document Ingestion" before taking any client work

This is the highest-consequence step in this file.

That workflow serves `/webhook/will-submission`, which is what creates a client's
`[RefId] - [Client Name]` folder in the Drive vault and uploads their title deeds,
pattadar passbooks and draft wills into it. **It ships inactive.** While it is
inactive, here is what happens on every new submission:

1. The client uploads their documents and receives a reference number.
2. The portal stores the files under `automation/web/uploads/`.
3. The provisioning call fails; the record is marked `driveProvisionState: pending`.
   The submission still succeeds — by design, a client's documents are never
   rejected because a downstream service is down.
4. **On Render's free tier there is no persistent disk.** The next sleep, restart
   or redeploy erases `uploads/`. The Supabase record survives; the documents do not.

So: activate it, then confirm the backlog is empty.

```bash
# How many submissions still hold documents only on ephemeral disk?
curl -s -H "x-admin-key: $AUTOMATION_SECRET_KEY" \
     https://admin.vbllawchambers.com/api/engine/preflight \
  | grep -o '"awaitingVault":[0-9]*'
```

Anything above `0` is a backlog. Drain it with the chambers key:

```bash
curl -X POST -H "x-admin-key: $CHAMBERS_ADMIN_SECRET_KEY" \
     https://admin.vbllawchambers.com/api/drive/provision-pending
```

Provisioning re-reads the files from disk, so this works long after the original
request ended — **but only while those files still exist.** Drain the backlog
before the instance is left to idle.

---

## Step 1 — Complete owner setup (first boot only)

n8n 1.x removed `N8N_BASIC_AUTH_*`; 1.x and 2.x protect the editor with
built-in user management, and on a fresh schema n8n presents an owner-setup
screen: **whoever reaches it first becomes the owner.** The editor holds live
Google Drive, YouTube and Meta credentials, so complete this immediately after
the first deploy — before the `n8n.vbllawchambers.com` DNS record is published.

*Status 2026-09-23:* the owner in the production `n8n` schema was claimed on
2026-09-15, so this step is done unless that schema is ever recreated. The
schema holds no workflows or credentials yet: the JSON files in `claude_mcp/`
still have to be imported and their Google credentials connected.

## Step 2 — Create the credentials

The production instance has none (the ids in older exports belonged to a
previous instance). Create these under **Credentials → Add credential**, then
select them on every node that shows a credential warning:

| Name to use | Type | Notes |
|---|---|---|
| Google Drive account | Google Drive OAuth2 API | Account that owns the private client vault `1SHI8YHrgHZEmVU30Jlr-FVDhqo-XZkSm` and the marketing media folder `1Q171pLkFgucgHO0bJ1lRWlxC3en-tHZz` |
| Google Sheets account | Google Sheets OAuth2 API | Account that owns the Content Calendar sheet (tab `Untitled`) |

> **Do not rename the `Untitled` tab.** All nine Sheets nodes (Content
> Ingestion, Content Approval, YouTube Publisher) find it by name, so a rename
> breaks every one of them at once. To make them rename-proof, switch each
> node's Sheet field to "By ID" with the tab's `gid` (the number after
> `#gid=` in the Sheet's address), then republish all three workflows.
| YouTube account | YouTube OAuth2 API | The chambers channel |
| Gmail account | Gmail OAuth2 | Sends from / to vbllawchambers@gmail.com |
| VBL Portal Webhook Key | Header Auth | Name `X-VBL-Webhook-Key`; Value = a new random secret (`openssl rand -hex 32`) |

Then put the **same** Header Auth value into `N8N_WEBHOOK_SECRET` on the
Render `advocate-content-portal` service. Until both sides match, n8n answers
the portal with 403 and submissions simply stay `pending` (safe, retryable).

Verify — this must return JSON with a `posts` array:

```bash
curl -H "X-VBL-Webhook-Key: $N8N_WEBHOOK_SECRET" https://n8n.vbllawchambers.com/webhook/content-list
```

> **OAuth callbacks.** n8n builds its redirect URI from `N8N_EDITOR_BASE_URL`, as
> `{N8N_EDITOR_BASE_URL}/rest/oauth2-credential/callback`. It must be a real
> https URL. Setting it from Render's `fromService: { property: hostport }`
> yields `n8n-automation:5678` — no scheme, wrong port — and every Google
> consent screen then fails at the redirect with no useful error. `render.yaml`
> sets it literally for exactly this reason.

## Step 3 — Publish the workflows

n8n 2.x keeps edits as a draft until you press **Publish** (top right) —
attaching credentials is an edit, so publish *after* Step 2:

1. **Will Document Ingestion** — Step 0 above. Do this one first.
2. **Content Ingestion Webhook** — the composer and calendar depend on it.
3. **Content Approval Requests** — emails the advocate when a row reaches `Status = Pending Review`.
4. **YouTube Publisher** — last, and only when you want real, **public** uploads
   to the chambers channel (switch `privacyStatus` to `private` first if testing).

## Step 4 — Smoke-test end to end

1. Submit a will through the public site with one small PDF attached.
2. Confirm a `[RefId] - [Client Name]` folder appears in the Drive vault with that PDF in it.
3. Confirm `awaitingVault` is still `0` in the pre-flight.

---

## Webhook contract

The portal calls exactly these three paths, resolved through `n8nCandidates()`
in [`server.js`](../web/server.js) — internal address first, then localhost,
then the public URL:

| Path | Called by | Purpose |
|---|---|---|
| `/webhook/will-submission` | `provisionDriveFolder()` | Create the client's Drive locker and upload documents |
| `/webhook/content-list` | `GET /api/posts` | Read the Content Calendar |
| `/webhook/content-upload` | `POST /api/upload` | File media into Drive and schedule a row |

Renaming a webhook path in n8n breaks the portal silently — the call fails, the
portal falls back to its local cache, and nothing surfaces except a warning in
the log. If you rename one, rename it in `server.js` in the same commit.

`will-submission` receives `refId`, `fullName`, `phone`, `email`,
`serviceType`, `folderName`, `documentNames` (JSON: field → the testator's
original filename, since disk names are ASCII-sanitised) and files
`document_0 … document_N`. It must answer with `driveFolderId` /
`driveFolderUrl`; anything else leaves the record `pending`.

When a client uploads supplementary documents against a deficiency checklist,
the portal also sends `existingFolderId` (the client's own folder) and only
the new files. The workflow's **Existing Folder?** branch then uploads into
that folder instead of creating a second one. A workflow older than that
branch ignores the field and creates a duplicate folder; the portal logs
`n8n created a new folder instead of reusing the client's own` when it sees
that. Import `claude_mcp/Will_Document_Ingestion.json` before deploying a
portal that sends supplementary uploads.

---

## Connected channels

Publishing credentials live in the **portal's** environment, not in n8n — see
`automation/.env.example`. n8n only needs Google's.

| Platform | Published by | Status |
|---|---|---|
| Facebook, Instagram, Threads | portal — `publishing/meta.js` | connected |
| YouTube | **n8n** — `YouTube_Publisher` workflow | needs the YouTube credential reconnected |
| LinkedIn | portal — `publishing/linkedin.js` | no access token configured |
| Pinterest | portal — `publishing/pinterest.js` | token returns HTTP 401 — reconnect required |

YouTube stays in n8n deliberately: it is the one channel that needs a genuine
resumable upload of the media bytes, and doing that inside a 512 MB portal
container is exactly the memory profile the rest of the design avoids. Every
other platform fetches media from a public URL, so no bytes pass through Node.
