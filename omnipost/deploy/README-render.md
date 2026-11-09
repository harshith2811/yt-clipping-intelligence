# Render Blueprint

The blueprint lives at the **repository root**: [`render.yaml`](../../render.yaml).

Render only discovers `render.yaml` at the root of the repo, so that copy is
canonical. A second copy used to sit in this directory; the two were identical
by luck rather than by any mechanism, and would have drifted the first time
only one was edited. Edit the root file.

Also in this directory:

| File | Applies to |
|---|---|
| `DNS_AND_DOMAINS.md` | The CNAME records for `admin.` and `n8n.vbllawchambers.com` (the free tier allows two per workspace), the dangling `automation.` record to delete, and how they map to the two services above. |
| `Caddyfile` | A server you control (e.g. Oracle Cloud Always Free). Not needed on Render — Render terminates TLS itself. |
| `nginx.conf` | Same, if you prefer nginx to Caddy. |
| `PII_HISTORY_PURGE.md` | Runbook for the client data still in git history. |
| `purge-pii-history.sh` | Automated version of that runbook. |
