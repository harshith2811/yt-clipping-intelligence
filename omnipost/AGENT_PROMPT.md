# 🤖 AGENT DIRECTIVE: OmniPost Universal Social Automation & Multi-Platform Publishing Suite

> **Instructions for the AI Assistant / Coding Agent taking over this project:**  
> You are acting as the **Lead Systems Architect & Full-Stack Platform Engineer** for this standalone repository.  
> Read this directive carefully before inspecting files or writing code.

---

## 🎯 1. Project Mission & Identity

This repository is **OmniPost Social Automation** — a high-performance, 100% standalone, generic, white-label multi-platform publishing and video automation engine.

It is completely decoupled from any single website or brand, designed to be wired directly to:
1. **Any External Website or Frontend**: E-commerce, marketing sites, blogs, portfolios, SaaS applications, or corporate sites.
2. **Any Headless CMS or Backend**: WordPress, Ghost, Webflow, Strapi, Sanity, Shopify, or custom Next.js/Express/Laravel backends.
3. **Stand-Alone Web Dashboard**: Includes a sleek, modern React + Vite dashboard (`/`) for direct manual uploading, content scheduling, and live preflight health monitoring.

---

## 🚀 2. Core Capabilities

1. **Direct Video & Media Uploading**:
   - Accepts large high-resolution video files (`.mp4`, `.mov`, `.webm`, up to 500 MB) and images (`.png`, `.jpg`, `.webp`, `.gif`).
   - Streams uploads directly to temporary disk staging before uploading to public CDN storage (Supabase Storage bucket `social-media-assets`). Never buffers entire files into container RAM.
2. **Native Multi-Platform Publishing**:
   - **YouTube**: Resumable chunked video uploads with tags, privacy status, and custom descriptions via n8n workflow.
   - **Facebook Pages**: Feed videos, reels, photos, and long-form status updates via Meta Graph API v21.0.
   - **Instagram Business**: Reels and single-media containers via Meta Graph API v21.0.
   - **Threads**: Direct media and text threads via Meta Threads API.
   - **LinkedIn**: Organization and Personal UGC posts, articles, and media updates.
   - **Pinterest**: Image pins and board publishing via Pinterest API v5.
3. **Automated Scheduling Engine**:
   - Timezone-aware scheduling with cron execution (`Asia/Kolkata` / UTC / configurable via `.env`).
   - Idempotent state machine (`web/publishing/state.js`): Never duplicates posts on network drops or container restarts.
   - Automatic failure classification: distinguishes transient rate limits (`TRANSIENT_NETWORK`), expired tokens (`AUTH_EXPIRED`), and permanent bad payloads (`FATAL_PAYLOAD`).
4. **Universal Inbound REST API (v1)**:
   - Dedicated endpoints (`/api/v1/publish`, `/api/v1/schedule`, `/api/v1/posts`, `/api/v1/channels`) protected by API key or Bearer token for wiring into ANY external website or service.

---

## 🏗️ 3. Repository Architecture & Layout

```text
automation-and-uploading/
├── .env                           # Configured environment variables (API keys & credentials)
├── .env.example                   # Annotated configuration reference & schema
├── docker-compose.yml             # Local Docker Compose setup (Web Portal + n8n)
├── docker-compose.prod.yml        # Production Docker Compose configuration
├── render.yaml                    # One-click Render Blueprint ($0/mo free tier compatible)
├── service-manager.ps1            # Windows PowerShell service manager CLI
├── start-all.bat / stop-all.bat   # 1-Click launcher scripts
├── AGENT_PROMPT.md                # This agent briefing directive
├── README.md                      # Comprehensive user & developer guide
├── QUICKSTART.md                  # 5-minute setup guide
│
├── web/                           # 🌐 THE PUBLISHING PORTAL & EXPRESS API (Port 3300)
│   ├── Dockerfile                 # Multi-stage production container build (Node 24 Alpine)
│   ├── package.json               # Backend & frontend dependencies
│   ├── server.js                  # Express API server + static React frontend host
│   ├── auth.js                    # Dual-passkey RBAC security (Admin vs Automation)
│   ├── db.js                      # Supabase PostgreSQL database client + local cache fallback
│   ├── n8n-client.js              # Resilient webhook integration with n8n
│   ├── verify-imports.mjs         # Build-time import resolution validator
│   ├── src/                       # React 18 + Vite frontend source
│   │   ├── App.jsx                # Main application component
│   │   ├── components/            # UI components (UploaderModule, ContentFeed, EnginePanel, etc.)
│   │   └── index.css              # Modern dark-mode styled CSS
│   └── publishing/                # ⚡ NATIVE CHANNEL ADAPTERS & STATE ENGINE
│       ├── registry.js            # Channel registry & credential validator
│       ├── state.js               # Idempotent state machine & rollup calculator
│       ├── schedule.js            # Timezone-aware due calendar post selector
│       ├── preflight.js           # Comprehensive pre-flight system diagnostics
│       ├── meta.js                # Facebook, Instagram & Threads Graph API drivers
│       ├── linkedin.js            # LinkedIn UGC & Article driver
│       ├── pinterest.js           # Pinterest Pins & Boards driver
│       └── *.test.mjs             # Node native test runner test suite (100% pass)
│
├── n8n/                           # 🔄 N8N ORCHESTRATION & WORKFLOWS (Port 5678)
│   └── claude_mcp/                # Production workflow JSON templates
│       ├── Content_Approval_Requests.json
│       ├── YouTube_Publisher.json
│       └── System_Health_Watchdog.json
│
└── supabase/                      # 🗄️ PERSISTENCE & RELATIONAL SCHEMAS
    └── schema.sql                 # PostgreSQL tables for content calendar & publishing states
```

---

## 🔌 4. Wiring OmniPost to ANY External Website or CMS

### Method A: Direct Inbound REST API (Recommended)

Call OmniPost from your backend, webhook handler, or serverless function:

```javascript
// Example: Posting from an external Next.js / Express backend
async function publishToOmniPost({ title, caption, mediaUrl, platforms }) {
  const response = await fetch('http://localhost:3300/api/v1/publish', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-admin-key': process.env.OMNIPOST_SECRET_KEY // Match AUTOMATION_SECRET_KEY in .env
    },
    body: JSON.stringify({
      title,
      caption,
      mediaUrl, // Direct public CDN link to image or video
      mediaType: 'video', // 'video' | 'image' | 'text'
      platforms: platforms || ['youtube', 'instagram', 'facebook', 'linkedin', 'threads', 'pinterest']
    })
  });

  return await response.json();
}
```

### Method B: cURL / Webhook

```bash
curl -X POST http://localhost:3300/api/v1/publish \
  -H "Content-Type: application/json" \
  -H "x-admin-key: your_automation_secret_key" \
  -d '{
    "title": "Exciting New Product Update",
    "caption": "Check out our latest breakthrough! Read more: https://example.com #Innovation #Tech",
    "mediaUrl": "https://cdn.example.com/videos/product-demo.mp4",
    "mediaType": "video",
    "platforms": ["youtube", "instagram", "facebook", "linkedin"]
  }'
```

---

## 🛡️ 5. Key Design Principles & Guardrails

1. **Maintain Zero-SaaS Dependency**: Native publishing to Meta, LinkedIn, and Pinterest runs directly inside Node.js; YouTube publishes run through n8n. Do NOT introduce paid aggregators (Buffer, Hootsuite, Make.com).
2. **Never Buffer Heavy Media into Memory**: Always use disk streaming (`multer.diskStorage` into temporary staging, streaming to CDN, and cleaning up staged files on `res.on('finish')`).
3. **Preserve Idempotency**: Never alter `state.js` in a way that allows re-publishing an already completed post (`state === 'completed'`).
4. **All Tests Must Pass**: Run `npm run verify` inside `web/` before finalizing any changes. All 57 tests must pass cleanly.
5. **Brand Neutrality**: Do not hardcode specific business or firm names into the codebase. All branding (app name, subtitle, colors, placeholders, quick tags) must be dynamic via `.env` and `/api/config`.

---

## 🛠️ 6. Quick Start Commands

```powershell
# Navigate to web directory
cd web

# Verify module imports
npm run verify

# Run test suite
npm test

# Build frontend for production
npm run build

# Start local server
npm start
```
