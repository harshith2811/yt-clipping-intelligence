# OmniPost Universal Integration Guide

Welcome to the **OmniPost Universal Integration Guide**. This document outlines how anyone—whether a marketer, creator, no-code automator, or software engineer—can integrate, configure, and publish content through OmniPost with ease.

---

## 1. 60-Second Quickstart Setup Wizard

OmniPost includes an interactive terminal setup wizard that eliminates manual `.env` file editing and automates passkey generation.

To run the wizard:

```bash
npm run setup
```

The wizard will:
1. **Generate Cryptographically Secure Passkeys** for your dashboard (`CHAMBERS_ADMIN_SECRET_KEY`) and webhook triggers (`AUTOMATION_SECRET_KEY`).
2. **Configure Database Mode:**
   - **Local Mode (Zero Setup):** Runs instantly using local JSON calendar files (`posts.json`) and local media staging.
   - **Supabase Cloud Mode:** Prompts for your Supabase URL and Service Role Key to enable managed PostgreSQL storage.
3. **Step-by-Step Social Channel Guided Setup:** Configure tokens for LinkedIn, Meta (Facebook & Instagram), and Pinterest, or press Enter to skip and configure later.
4. **Automated Safety Backup:** Creates a timestamped `.env.backup.<timestamp>` before writing changes.
5. **Self-Check Diagnostic:** Tests your configuration and displays active channels.

To verify your configuration status at any time:
```bash
npm run setup -- --check
```

---

## 2. Flexible Selective Publishing

You **do not need all social media platforms configured** to start publishing.

- If you only want to publish to **LinkedIn**, connect LinkedIn and publish immediately.
- If you only want to publish to **YouTube**, connect YouTube and post immediately.
- If you select multiple platforms for a post (e.g. LinkedIn and Instagram), OmniPost will publish to whichever channels have valid credentials and cleanly report which channels require configuration without crashing or blocking the successful ones.

---

## 3. Social Media Channel Setup Instructions

### 📸 Instagram Business
1. Go to the [Meta Developer Console](https://developers.facebook.com/apps/) and create an app (App Type: **Business**).
2. Connect your Professional Instagram account to a Facebook Page.
3. Under **Graph API Explorer**, generate a User Access Token with the following permissions:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
4. Find your `INSTAGRAM_ACCOUNT_ID` by querying:
   ```http
   GET /me/accounts -> select Page ID -> GET /{page-id}?fields=instagram_business_account
   ```
5. Exchange the token for a long-lived 60-day token and add to `.env`:
   ```env
   INSTAGRAM_ACCESS_TOKEN=EAAG...
   INSTAGRAM_ACCOUNT_ID=17841400...
   ```

### 📘 Facebook Pages
1. In Meta Developer Console, generate a Page Access Token with:
   - `pages_manage_posts`
   - `pages_read_engagement`
2. Add to `.env`:
   ```env
   FACEBOOK_PAGE_ACCESS_TOKEN=EAAG...
   FACEBOOK_PAGE_ID=1000...
   ```

### 🧵 Threads
1. Add the **Threads API** use case in Meta Developer Console.
2. Generate an access token with `threads_basic` and `threads_content_publish`.
3. Add to `.env`:
   ```env
   THREADS_ACCESS_TOKEN=THQ...
   THREADS_USER_ID=12345678...
   ```

### 💼 LinkedIn
1. Go to the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps) and create an app.
2. Under **Products**, add **Share on LinkedIn** and **Sign In with LinkedIn using OpenID Connect**.
3. Under Auth -> OAuth 2.0 Tools, generate an access token with scope: `w_member_social`.
4. Your Author URN is formatted as: `urn:li:person:<your_member_id>` (found via `GET /v2/userinfo`).
5. Add to `.env`:
   ```env
   LINKEDIN_ACCESS_TOKEN=AQV...
   LINKEDIN_AUTHOR_URN=urn:li:person:abcdef1234
   ```

### 🎬 YouTube
1. In Google Cloud Console, enable **YouTube Data API v3** and create OAuth credentials.
2. Connect YouTube inside your n8n workflow hub (`http://localhost:5678`).
3. OmniPost will automatically dispatch video uploads through n8n.

### 📌 Pinterest
1. In the [Pinterest Developer Portal](https://developers.pinterest.com/apps/), generate an access token with scopes `boards:read`, `pins:read`, `pins:write`.
2. Add to `.env`:
   ```env
   PINTEREST_ACCESS_TOKEN=pina_...
   PINTEREST_BOARD_ID=123456789...
   ```

---

## 4. Universal Incoming Webhook (`/api/webhook/publish`)

Any external service (Zapier, Make.com, Airtable, Notion, cURL, Python) can trigger immediate or scheduled social posts by sending a standard HTTP POST request.

### Endpoint
```http
POST /api/webhook/publish
```

### Supported Authentication Headers
OmniPost accepts authentication via any of the following:
- `x-api-key: YOUR_AUTOMATION_SECRET_KEY`
- `x-admin-key: YOUR_CHAMBERS_ADMIN_SECRET_KEY`
- `Authorization: Bearer YOUR_AUTOMATION_SECRET_KEY`
- URL Query parameter: `?apiKey=YOUR_AUTOMATION_SECRET_KEY`

### Request Body (JSON)
```json
{
  "title": "Product Launch Announcement",
  "caption": "Excited to share our newest release! 🚀 #tech #innovation",
  "mediaUrl": "https://example.com/video.mp4",
  "mediaType": "video",
  "platforms": ["youtube", "linkedin", "instagram"],
  "link": "https://mysite.com",
  "publishNow": true
}
```

### Response (Immediate Publish)
```json
{
  "success": true,
  "contentId": "P-48291048",
  "published": true,
  "status": "Published",
  "settled": true,
  "results": [
    {
      "platform": "linkedin",
      "status": "published",
      "result": "PUBLISHED",
      "permalink": "https://www.linkedin.com/feed/update/urn:li:share:123456",
      "error": null
    },
    {
      "platform": "instagram",
      "status": "published",
      "result": "PUBLISHED",
      "permalink": "https://www.instagram.com/p/Cxyz123/",
      "error": null
    }
  ],
  "summary": {
    "published": 2,
    "failed": 0,
    "skipped": 0,
    "requested": 2,
    "text": "2/2 published"
  }
}
```

---

## 5. No-Code Integration: Zapier & Make.com

You can trigger social media posts directly from Google Sheets, Airtable, Typeform, or Notion using Zapier or Make.com:

### Zapier Setup
1. **Trigger:** Choose your trigger (e.g., *New Row in Google Sheets* or *New Record in Airtable*).
2. **Action:** Select **Webhooks by Zapier** -> **Custom Request**.
3. **Method:** `POST`
4. **URL:** `https://your-omnipost-domain.com/api/webhook/publish`
5. **Headers:**
   - `x-api-key`: `your_automation_secret_key`
   - `Content-Type`: `application/json`
6. **Data:**
   ```json
   {
     "title": "{{Step 1. Title}}",
     "caption": "{{Step 1. Caption}}",
     "mediaUrl": "{{Step 1. Video_URL}}",
     "platforms": ["linkedin", "instagram", "facebook"],
     "publishNow": true
   }
   ```
7. Click **Test Step** — your post will publish live across all selected networks!

### Make.com Setup
1. Add an **HTTP** module -> **Make a request**.
2. **URL:** `https://your-omnipost-domain.com/api/webhook/publish`
3. **Method:** `POST`
4. **Headers:**
   - Name: `x-api-key`, Value: `your_automation_secret_key`
   - Name: `Content-Type`, Value: `application/json`
5. **Body type:** Raw -> JSON. Map your fields and run!

---

## 6. JavaScript & TypeScript SDK

OmniPost provides a zero-dependency universal SDK compatible with Node.js 18+, Bun, Deno, and modern browser environments.

### Installation / Import
The SDK is located at `sdk/omnipost.js`:

```javascript
import { OmniPost } from './sdk/omnipost.js';

const client = new OmniPost({
  baseUrl: 'http://localhost:3300',
  apiKey: process.env.AUTOMATION_SECRET_KEY
});

// 1. Check channel readiness
const status = await client.preflight();
console.log('Ready platforms:', status.readyToPublish);

// 2. Publish immediately
const publishResult = await client.publish({
  title: 'Weekly Roundup',
  caption: 'Here is what we shipped this week! #buildinpublic',
  mediaUrl: 'https://example.com/demo.mp4',
  platforms: ['linkedin', 'instagram']
});
console.log('Published IDs:', publishResult.results);

// 3. Schedule for later
const scheduled = await client.schedule({
  title: 'Future Post',
  caption: 'Scheduled for tomorrow morning!',
  scheduledDateTime: '2026-11-01T09:00:00Z',
  platforms: ['youtube']
});

// 4. Check post status
const postStatus = await client.getStatus(scheduled.contentId);
console.log('Post status:', postStatus.status);
```

---

## 7. Python SDK

Located at `sdk/omnipost.py`, the Python SDK has zero external dependencies and runs on Python 3.8+.

```python
from sdk.omnipost import OmniPost

client = OmniPost(
    base_url="http://localhost:3300",
    api_key="your_automation_secret_key"
)

# 1. Check readiness
preflight = client.preflight()
print("Armed channels:", preflight.get("readyToPublish"))

# 2. Publish post
result = client.publish(
    title="Python Milestone",
    caption="Publishing from Python backend seamlessly! #python #automation",
    media_url="https://example.com/video.mp4",
    platforms=["linkedin", "threads"]
)
print("Result:", result)

# 3. Schedule post
scheduled = client.schedule(
    title="Tomorrow's Video",
    caption="Dropping tomorrow at noon!",
    scheduled_date_time="2026-11-02T12:00:00Z",
    platforms=["youtube", "instagram"]
)

# 4. Check status
status = client.get_status(scheduled["contentId"])
print("Status:", status["status"])
```

---

## 8. In-Studio "Integrations & API" Panel

Inside the OmniPost Web Studio (`http://localhost:3300`), click the **⚡ Integrations & API** button in the header bar.

From this panel, you can:
- View live status badges for every social channel (🟢 Connected / 🟡 Needs Setup).
- Click any channel to open its step-by-step setup walkthrough and developer portal link.
- Use the **Interactive Playground** to customize post copy and instantly generate ready-to-run cURL commands, Python scripts, JavaScript SDK snippets, or Zapier/Make JSON payloads.
- Copy your passkeys with a single click.

---

**OmniPost Integration Suite** — *Universal, Reliable, and Easy for Everyone.*
