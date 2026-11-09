# Social Publishing API Reference

Implementation notes for publishing directly from n8n, without Postiz.

This documents **API facts** — endpoints, required parameters, call ordering, status
values, and real-world timing quirks. Everything here is behaviour of the platforms'
own public APIs. Write fresh implementations from this; do not copy Postiz source
(it is AGPL-3.0, and copying it into the portal would make the portal AGPL too).

---

## Coverage summary

| Platform | n8n native node | Work required |
|---|---|---|
| Facebook Page | ✅ Facebook Graph API | Configure node |
| Instagram | ⚠️ Use Facebook Graph API node | 2-step container flow (below) |
| YouTube | ✅ Google → YouTube | Configure node |
| LinkedIn | ✅ LinkedIn | Configure node |
| Telegram | ✅ Telegram | Configure node |
| **Threads** | ❌ None | HTTP Request — 3 calls |
| **Pinterest** | ❌ None | HTTP Request — 2 calls (image) / 4 (video) |
| X / Twitter | ✅ Twitter | API is paid — see note at end |

---

## The single most important fact

**Meta and Pinterest fetch media from a public URL — you do not upload bytes.**

You pass `video_url` / `image_url` pointing at a publicly reachable file, and their
servers download it themselves. This means Instagram, Threads, Facebook and Pinterest
(images) cost your server **zero bandwidth and zero RAM**, which is what makes a
512 MB free-tier instance viable.

The exceptions that *do* stream real bytes through your server:
- **YouTube** (resumable upload)
- **Pinterest video** (upload to a pre-signed URL)

The media must be reachable by *their* servers — a Google Drive file must be shared
"anyone with the link", or use a Cloudflare R2 / S3 public object.

---

## Threads

Base: `https://graph.threads.net/v1.0`
Auth: `access_token` query parameter. You already have `THREADS_USER_ID` and
`THREADS_ACCESS_TOKEN` in `automation/.env`.

### Publishing is 3 calls

**1. Create a media container**

```
POST /{THREADS_USER_ID}/threads
```
| Param | Value |
|---|---|
| `media_type` | `TEXT` \| `IMAGE` \| `VIDEO` \| `CAROUSEL` |
| `text` | caption |
| `image_url` | public URL (when `IMAGE`) |
| `video_url` | public URL (when `VIDEO`) |
| `children` | comma-separated container IDs (when `CAROUSEL`) |
| `is_carousel_item` | `true` on each child container |
| `reply_to_id` | container/post id, for threaded replies |
| `access_token` | token |

Returns `{ id }` — the **container id**, not a published post.

**2. Poll until the container is processed**

```
GET /{containerId}?fields=status,error_message
```

| `status` | Meaning |
|---|---|
| `IN_PROGRESS` | keep polling |
| `FINISHED` | ready to publish |
| `PUBLISHED` | already live |
| `ERROR` / `EXPIRED` | fail — surface `error_message` |

Practical timing: poll about every **2.2 s**, and cap it — roughly **150 attempts
(~5.5 min)** before giving up, otherwise a stuck video hangs the job forever.

> ⚠️ **Non-obvious quirk:** after `status` becomes `FINISHED`, wait ~**2 more seconds**
> before publishing. Publishing the instant it reports FINISHED can still fail — the
> status flips slightly before the media is genuinely publishable.

**3. Publish**

```
POST /{THREADS_USER_ID}/threads_publish?creation_id={containerId}&access_token=...
```
Returns the published thread id.

**Optional — get the permalink:**
```
GET /{threadId}?fields=id,permalink&access_token=...
```

### Token lifetime
Threads long-lived tokens expire (~60 days) and are refreshed with:
```
GET /refresh_access_token?grant_type=th_refresh_token&access_token={token}
```
Refresh well before expiry, or posting silently starts failing.

---

## Instagram

Base: `https://graph.facebook.com/v20.0`
Requires an Instagram **Professional** (Business/Creator) account linked to a
Facebook Page. Uses the IG Business Account ID, not the Page ID.

Same container → poll → publish shape as Threads.

**1. Create container**
```
POST /{ig-user-id}/media
```
| Post type | Parameters |
|---|---|
| Image (feed) | `image_url`, `caption` |
| Reel | `video_url`, `media_type=REELS`, `thumb_offset`, `caption` |
| Video (feed) | `video_url`, `media_type=VIDEO`, `thumb_offset` |
| Story (image) | `image_url`, `media_type=STORIES` |
| Story (video) | `video_url`, `media_type=STORIES` |
| Carousel | `media_type=CAROUSEL`, `children={ids}` |

`thumb_offset` is the millisecond position used for the video thumbnail.

**2. Poll container status** — same `status` field and same ~2.2 s cadence as Threads.
Video containers routinely take 30 s–several minutes.

**3. Publish**
```
POST /{ig-user-id}/media_publish?creation_id={containerId}
```

### Known limits
- Instagram does **not** expose Story link stickers via the API.
- Personal (non-professional) accounts cannot use the Graph API at all.

---

## Pinterest

Base: `https://api.pinterest.com/v5`
Auth: `Authorization: Bearer {token}`. Requires a Pinterest **business** account.
Every pin needs a target `board_id`.

**List boards:** `GET /boards?page_size=250`

### Image pin — 1 call
```
POST /pins
{
  "board_id": "...",
  "title": "...",
  "description": "...",
  "link": "https://optional-destination",
  "media_source": { "source_type": "image_url", "url": "https://..." }
}
```

### Video pin — 3 calls
1. **Register the upload**
   ```
   POST /media   { "media_type": "video" }
   ```
   Returns `{ media_id, upload_url, upload_parameters }`.

2. **Upload to the pre-signed URL** — POST multipart form to `upload_url`, appending
   every key/value in `upload_parameters` as form fields **first**, then the file.
   (This is an S3-style pre-signed post; field order matters.)

3. **Poll** `GET /media/{media_id}` until status is registered/succeeded, then
   **create the pin** referencing it:
   ```
   POST /pins
   { "board_id": "...", "media_source": { "source_type": "video_id", "media_id": "..." } }
   ```

> If Pinterest replies that it could not reach your URL, the media is not publicly
> accessible — that is the usual cause, not a malformed request.

---

## Facebook Page — use the n8n Facebook Graph API node

Base: `https://graph.facebook.com/v20.0`. Post to `/{page-id}/photos`, `/{page-id}/videos`,
or `/{page-id}/feed`. Requires a **Page access token**, obtained from
`GET /me/accounts` (each entry carries its own `access_token`) — a user token will not work.

## YouTube — use the n8n Google → YouTube node

The native node handles the resumable upload. This is the one platform where the video
bytes genuinely flow through n8n, so keep `N8N_DEFAULT_BINARY_DATA_MODE=filesystem`
so n8n buffers to disk rather than RAM.

---

## X / Twitter

n8n has a native Twitter node, but write access is heavily restricted on the free API
tier and paid tiers are expensive. **Verify current pricing before promising this channel.**

---

## Failure handling to preserve

Whatever replaces the Postiz scheduler must keep the behaviour already built into the
Google Sheet, or failures become invisible:

- Per-platform status columns (`Instagram Status`, `YouTube Status`, …)
- `Status` lifecycle: `Draft → Pending Review → Approved → Posted / Retry Pending / Failed`
- `Retry Count` with a cap, and an `Error` column
- Gmail alert to the admin when a row exhausts its retries

A post failing silently is worse than a post going out late.
