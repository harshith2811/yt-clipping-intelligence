# Native Multi-Channel Publishing — Blueprint

What we learned from reading the Postiz engine (`automation/postiz-app-main/
libraries/nestjs-libraries/src/integrations/`), and how to run the same
patterns from our own backend on a 512 MB Render instance.

**Licensing:** Postiz is AGPL-3.0. Everything below is *how the platform APIs
behave* plus architectural decisions — facts and ideas, not copyrightable
expression. No Postiz code is copied into our stack. Endpoint details live in
[`SOCIAL_API_REFERENCE.md`](./SOCIAL_API_REFERENCE.md).

---

## 1. The finding that makes a small server viable

Meta (Instagram/Facebook) and Pinterest **do not accept raw bytes from your
server**. You hand them a *public URL* and they fetch the media themselves:

```
POST /{ig-user-id}/media?video_url=https://.../clip.mp4   -> container id
GET  /{container-id}?fields=status_code                    -> IN_PROGRESS | FINISHED | ERROR
POST /{ig-user-id}/media_publish?creation_id={container}   -> live post
```

Consequences for us:

- Publishing a 200 MB reel costs our server **no upload bandwidth and no RAM**.
  We only pass a URL and poll a tiny JSON status.
- The media must be publicly reachable for the duration of the fetch. Our Drive
  vault already holds it — a Drive file shared "anyone with the link" serves
  this directly, so nothing extra needs hosting.
- YouTube is the exception: it needs a real resumable upload, which is why the
  YouTube publisher streams from Drive through n8n rather than passing a URL.

This is the single reason a free-tier box can run the whole practice's social
publishing.

## 2. Error taxonomy — the part worth copying outright

Postiz classifies every provider failure into three kinds, and this is what
separates a reliable publisher from one that silently rots:

| Kind | Meaning | Correct response |
|---|---|---|
| `refresh_token` | Token expired but the channel is fine | Refresh, retry the same post |
| `disconnect` | Platform will keep rejecting this channel regardless of token (revoked app, TikTok DAU cap, account restriction) | Stop retrying. Mark the channel dead and **tell the operator to reconnect** |
| `bad_body` | This specific post will never succeed (aspect ratio, duration, caption length) | Fail this post only, leave the channel healthy |

Our current pipeline collapses all three into "retry" plus a Gmail alert. That
is precisely how our Threads and YouTube tokens went stale while the dashboard
still reported four channels connected: a `disconnect` was being retried forever
instead of surfacing as "reconnect this channel".

**Implemented** in [`automation/web/publishing/classify.js`](../web/publishing/classify.js)
as `AUTH_EXPIRED` / `TRANSIENT_NETWORK` / `FATAL_PAYLOAD`, reading Meta's
structured error codes (190 + subcodes 458–492 → auth; the 2207xxx media family
→ payload; 4/17/32/613 → throttle) and Google's `reason` field in preference to
the HTTP status, which is too coarse to separate "quota exhausted" from
"permission revoked". `nextAction()` returns `retry` with jittered exponential
backoff or `halt`; an `AUTH_EXPIRED` channel is marked **Needs Reconnect**
rather than retried.

## 3. Resumability — what actually matters on Render

Render free tier sleeps after ~15 minutes and can be recycled mid-request. An
Instagram video container can take 30–60 s to transcode. A naive
"create → sleep → publish" loop inside one request will therefore sometimes die
between *container created* and *media_publish* — and the retry posts a second
copy to the client's feed.

Postiz avoids this with a resumable state machine rather than a blocking loop:

```
{ status: 'pending',   pendingData }  -> come back later, nothing to do yet
{ status: 'ready',     pendingData }  -> container finished, safe to publish
{ status: 'completed', postId, releaseURL }
```

Crucially, before republishing it re-checks the container and treats
`PUBLISHED` as **already done** — so a crash between publish and bookkeeping
never double-posts.

**Action — our design, no Temporal required:**

1. `POST /api/publish` creates the container(s), writes
   `platform_statuses.instagram = { state: 'pending', containerId }` to Supabase,
   and returns immediately.
2. A cheap poller (n8n schedule, or an external cron ping) picks up rows in
   `state: 'pending'`, checks the container, and advances to `ready` →
   `completed`.
3. The publish step is keyed on `containerId`; if the container already reports
   `PUBLISHED`, record it as completed instead of publishing again.

Because state lives in Supabase, the container going to sleep between steps is
harmless — which is exactly the "wake 2–4 times a day, then sleep" model we want.

**Implemented** in [`automation/web/publishing/state.js`](../web/publishing/state.js)
(`queued → pending → ready → completed | failed`), persisted via
`db.getPublishState` / `db.savePublishState` into
`content_calendar.platform_statuses`, `publish_state`, `last_attempt_at` and
`failure_kind`. Both the `pending` and `ready` transitions re-check the
container and treat `PUBLISHED` as already done.

`node automation/web/publishing/publishing.test.mjs` — 27 tests, including
"CRASH AFTER PUBLISH: does not post twice", which asserts `publishContainer` is
called **zero** times when a stale `ready` state meets an already-published
container.

## 4. Provider shape to implement

Postiz's `ISocialMediaIntegration` is a clean contract; ours can be narrower:

```js
// automation/web/publishers/<platform>.js
export default {
  name: 'instagram',
  generateAuthUrl(),                       // OAuth consent URL
  authenticate({ code }),                  // -> { accessToken, refreshToken, expiresIn, id, name }
  refreshToken(refreshToken),              // -> same shape
  createPost({ auth, media, caption }),    // -> { state:'pending', containerId } | { state:'completed', postId }
  checkPending({ auth, pendingData }),     // -> pending | ready | completed
  finalize({ auth, pendingData })          // -> { state:'completed', postId, releaseURL }
};
```

Four methods carry all six platforms. Facebook and Instagram share the Graph
container flow, so one module covers both with a different node id.

## 5. Media sizing

Postiz normalises images with `sharp` before upload. We should **not** add
`sharp` — it is a large native dependency and would eat both the Render image
size and RAM budget. Our media originates in Drive and is produced by the
practice, so the cheaper control is validation: reject at submission time
anything outside each platform's documented aspect-ratio/duration limits and
tell the operator, rather than transcoding on the server.

## 6. Ordering against current status

| Platform | State | Next step |
|---|---|---|
| YouTube | **Live in production**, verified end to end | Nothing |
| Facebook / Instagram | Graph app blocked pending 2FA + business documents | Ready to build the moment the app clears review; the container flow above is the whole implementation |
| LinkedIn | On hold — needs a company profile | — |
| Threads | Token dead | Re-auth; treat as `disconnect`, not a retry |
| Pinterest | Dropped — trial denied (app 1607736) | — |

The highest-value work available right now is **§2 (error taxonomy)** and
**§3 (resumable publish state)**. Both are platform-independent, both fix
defects we have already hit in production, and both are prerequisites for
Meta going live rather than extra work alongside it.
