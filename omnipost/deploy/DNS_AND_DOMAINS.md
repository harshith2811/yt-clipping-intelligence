# DNS & Custom Domain Mapping

How the public hostnames reach the services, and the exact records at the
registrar for `vbllawchambers.com`. DNS and the Render/Vercel dashboards
cannot be changed from this repository; this is the runbook for doing it by
hand.

## Current shape (verified 2026-09-23)

```
vbllawchambers.com / www ───► Vercel (website/)        public site
admin.vbllawchambers.com ───► advocate-content-portal   Render ──► Supabase (public schema)
n8n.vbllawchambers.com   ───► n8n-automation            Render ──► Supabase (n8n schema)
```

**Two custom domains on Render, and that is the ceiling.** The free tier
allows two custom domains per *workspace*, across all services. A third
(`automation.vbllawchambers.com`, on the portal) made Render ask for payment
and was removed from `render.yaml`.

> An earlier version of this file said "2 custom domains per service". That
> was wrong: Render's payment prompt showed the limit is per workspace.

The portal still recognises `automation.` in code (`HOST_SCOPES` in
`automation/web/server.js`, `detectHostScope()` in
`automation/web/src/App.jsx`), which costs nothing and reactivates if that
domain is ever added back on a paid plan. Nothing serves it today.

## Records at the registrar

| Type | Host | Value (target) | Status on 2026-09-23 |
|---|---|---|---|
| CNAME | `admin` | `advocate-content-portal.onrender.com` | resolves, HTTPS 200 |
| CNAME | `n8n` | `n8n-automation-p7cc.onrender.com` | resolves; service had no live deploy (see render.yaml) |
| CNAME | `automation` | `advocate-content-portal.onrender.com` | **DELETE** — dangling |
| CNAME | `www` | Vercel (`*.vercel-dns-017.com`) | managed by Vercel |

Notes:

- **Delete the `automation` record.** It still points at the portal, but
  Render no longer has that domain attached: the TLS handshake fails and
  nothing is served. A record pointing at a platform that has not claimed it
  is the classic setup for a subdomain takeover. The portal no longer trusts
  `*.vbllawchambers.com` wholesale in CORS (exact origins only), so a
  takeover would not reach the API, but the record should still go.
- **The `.onrender.com` targets are assigned by Render, not derived from
  `name:`.** The n8n service got `n8n-automation-p7cc` because
  `n8n-automation` was taken. Always copy the hostname from the service's page
  in the Render dashboard.
- **CNAME, not A record.** Render custom domains point at the service's
  `onrender.com` hostname.
- TLS certificates are issued by Render automatically once the CNAME
  resolves. Do not add anything TLS-related at the registrar.

## Verify

```bash
curl -sI https://admin.vbllawchambers.com/api/health?shallow=1   # 200
curl -sI https://n8n.vbllawchambers.com/healthz                  # 200 once n8n is live
# The admin shell should carry its host scope:
curl -s https://admin.vbllawchambers.com/ | grep -o '__VBL_HOST_SCOPE__=[^;]*'
# After deleting the dangling record this should fail to resolve:
nslookup automation.vbllawchambers.com
```

A response header of `x-render-routing: no-deploy` with HTTP 502 means the
DNS and domain are fine and the *service* has no successful deploy. Check its
deploy logs rather than DNS.

## OAuth redirect URIs

`N8N_EDITOR_BASE_URL` and `N8N_WEBHOOK_URL` in `render.yaml` are
`https://n8n-automation-p7cc.onrender.com` today. n8n builds OAuth callbacks
from them (`{N8N_EDITOR_BASE_URL}/rest/oauth2-credential/callback`), so the
Google Cloud / Meta / Pinterest / LinkedIn apps must list exactly that
address. Switching n8n to `https://n8n.vbllawchambers.com` means changing
both values and every registered redirect URI together; changing one side
alone fails at the consent screen with no useful error.

## If a portal domain name ever changes

The portal hostnames are spelled out in four places that must agree:

1. `render.yaml` → the service's `domains:` list
2. `automation/web/server.js` → `HOST_SCOPES` and `ALLOWED_ORIGINS` (CORS)
3. `automation/web/src/App.jsx` → `detectHostScope()`
4. `website` on Vercel → the `VITE_API_BASE_URL` build variable (the public
   site calls the portal API cross-origin)
