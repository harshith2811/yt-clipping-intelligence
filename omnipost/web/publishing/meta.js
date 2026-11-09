/**
 * Native Meta publishing adapters — Facebook Page, Instagram, Threads.
 *
 * These implement the driver contract consumed by state.js:
 *
 *   createContainer()             -> { containerId } | { postId, releaseUrl }
 *   checkContainer(containerId)   -> 'IN_PROGRESS' | 'FINISHED' | 'PUBLISHED' | 'ERROR'
 *   publishContainer(containerId) -> { postId, releaseUrl }
 *   describePublished(containerId)-> { postId, releaseUrl }
 *
 * ZERO-RAM MEDIA HANDOFF
 * ----------------------
 * None of these adapters ever reads media bytes. Meta is handed a PUBLIC URL
 * (image_url / video_url / file_url) and fetches the file itself, so publishing
 * a 200MB reel costs this process no upload bandwidth and no heap - which is
 * what makes the 512MB instance viable. The corollary is that the URL must be
 * publicly reachable for the duration of Meta's fetch: a Drive file shared
 * "anyone with the link" satisfies this, a signed URL that expires in 60s does not.
 *
 * ERRORS
 * ------
 * Every failure is thrown as a structured MetaApiError carrying { status, body }
 * so classify.js can sort it into AUTH_EXPIRED / TRANSIENT_NETWORK /
 * FATAL_PAYLOAD. Never swallow one: an unclassified failure is retried blindly,
 * which is how a dead channel stays "connected" on the dashboard forever.
 */

const GRAPH_VERSION = process.env.META_GRAPH_VERSION || 'v21.0';
const GRAPH = `https://graph.facebook.com/${GRAPH_VERSION}`;
const THREADS = 'https://graph.threads.net/v1.0';

/**
 * Redacts secret query parameters (access_token, client_secret, appsecret_proof, token)
 * from URLs to prevent credentials from being leaked in errors, logs, or API responses.
 */
export function redactUrlSecrets(url) {
  if (typeof url !== 'string') return url;
  return url.replace(/([?&](?:access_token|client_secret|appsecret_proof|token)=)[^&#\s"']*/gi, '$1[REDACTED]');
}

export class MetaApiError extends Error {
  constructor(message, { status, body, platform, endpoint } = {}) {
    super(message);
    this.name = 'MetaApiError';
    this.status = status;
    this.body = body;
    this.platform = platform;
    this.endpoint = redactUrlSecrets(endpoint);
  }
}

/**
 * One HTTP call against a Meta surface.
 *
 * Meta returns 200 with an `error` object in some paths, so success is decided
 * by the body as well as the status.
 */
async function call(url, { method = 'GET', platform, form } = {}, fetchImpl = fetch) {
  let res;
  try {
    res = await fetchImpl(url, {
      method,
      ...(form ? { body: form } : {})
    });
  } catch (networkErr) {
    // Never reached Meta: surface the errno so classify.js sees TRANSIENT_NETWORK.
    throw new MetaApiError(networkErr.message, {
      status: undefined,
      body: undefined,
      platform,
      endpoint: redactUrlSecrets(url)
    });
  }

  let body;
  try { body = await res.json(); } catch { body = null; }

  if (!res.ok || body?.error) {
    const msg = body?.error?.message || `HTTP ${res.status}`;
    throw new MetaApiError(msg, { status: res.status, body, platform, endpoint: redactUrlSecrets(url) });
  }
  return body;
}

const enc = encodeURIComponent;

// ===========================================================================
// Facebook Page
// ===========================================================================
/**
 * Publishing to a Page is single-step: the Graph API returns the post id
 * immediately, so createContainer resolves straight to 'completed'.
 *
 * Endpoint depends on the media:
 *   none  -> POST /{page-id}/feed    { message, link }
 *   image -> POST /{page-id}/photos  { url, caption }
 *   video -> POST /{page-id}/videos  { file_url, description }
 *
 * `url` / `file_url` are the zero-RAM handoff: Meta fetches them.
 */
export function facebookAdapter({ pageId, pageAccessToken, post, fetchImpl = fetch }) {
  if (!pageId) throw new Error('facebookAdapter: pageId is required');
  if (!pageAccessToken) throw new Error('facebookAdapter: pageAccessToken is required');

  const token = enc(pageAccessToken);

  return {
    platform: 'facebook',

    async createContainer() {
      const { caption = '', mediaUrl = '', mediaType = 'text', link = '' } = post;
      let url;

      if (mediaType === 'image' && mediaUrl) {
        url = `${GRAPH}/${pageId}/photos?url=${enc(mediaUrl)}&caption=${enc(caption)}&access_token=${token}`;
      } else if (mediaType === 'video' && mediaUrl) {
        url = `${GRAPH}/${pageId}/videos?file_url=${enc(mediaUrl)}&description=${enc(caption)}&access_token=${token}`;
      } else {
        url = `${GRAPH}/${pageId}/feed?message=${enc(caption)}${link ? `&link=${enc(link)}` : ''}&access_token=${token}`;
      }

      const body = await call(url, { method: 'POST', platform: 'facebook' }, fetchImpl);
      // /photos returns { id, post_id }; /feed and /videos return { id }.
      const postId = body.post_id || body.id;
      return {
        postId,
        releaseUrl: `https://www.facebook.com/${postId}`
      };
    },

    // Present for contract completeness; the Page flow never reaches these.
    async checkContainer() { return 'PUBLISHED'; },
    async publishContainer(containerId) {
      return { postId: containerId, releaseUrl: `https://www.facebook.com/${containerId}` };
    },
    async describePublished(containerId) {
      return { postId: containerId, releaseUrl: `https://www.facebook.com/${containerId}` };
    }
  };
}

// ===========================================================================
// Instagram (two-step container flow)
// ===========================================================================
/**
 * IG never accepts bytes. The flow is:
 *   1. POST /{ig-user-id}/media          -> container id
 *   2. GET  /{container-id}?fields=status_code  until FINISHED
 *   3. POST /{ig-user-id}/media_publish  -> post id
 *
 * Step 2 is why this is a state machine rather than a loop: transcoding a reel
 * takes 30-60s, and blocking on it is what lets a sleeping container die
 * mid-publish and duplicate the post on retry.
 */
export function instagramAdapter({ igUserId, accessToken, post, fetchImpl = fetch }) {
  if (!igUserId) throw new Error('instagramAdapter: igUserId is required');
  if (!accessToken) throw new Error('instagramAdapter: accessToken is required');

  const token = enc(accessToken);

  return {
    platform: 'instagram',

    async createContainer() {
      const { caption = '', mediaUrl, mediaType = 'image', isReel = false, thumbOffset } = post;
      if (!mediaUrl) {
        // Instagram has no text-only post. Failing here rather than at Meta
        // keeps the error precise instead of a generic 400.
        throw new MetaApiError('Instagram requires an image or video URL', {
          status: 400,
          body: { error: { message: 'media required', code: 100, error_subcode: 2207009 } },
          platform: 'instagram'
        });
      }

      let media;
      if (mediaType === 'video') {
        media = `video_url=${enc(mediaUrl)}&media_type=${isReel ? 'REELS' : 'VIDEO'}` +
                (thumbOffset ? `&thumb_offset=${thumbOffset}` : '');
      } else {
        media = `image_url=${enc(mediaUrl)}`;
      }

      const body = await call(
        `${GRAPH}/${igUserId}/media?${media}&caption=${enc(caption)}&access_token=${token}`,
        { method: 'POST', platform: 'instagram' },
        fetchImpl
      );
      return { containerId: body.id };
    },

    async checkContainer(containerId) {
      const body = await call(
        `${GRAPH}/${containerId}?fields=status_code,status&access_token=${token}`,
        { platform: 'instagram' },
        fetchImpl
      );
      // status_code: IN_PROGRESS | FINISHED | PUBLISHED | ERROR | EXPIRED
      return body.status_code;
    },

    async publishContainer(containerId) {
      const body = await call(
        `${GRAPH}/${igUserId}/media_publish?creation_id=${enc(containerId)}&access_token=${token}`,
        { method: 'POST', platform: 'instagram' },
        fetchImpl
      );
      const postId = body.id;
      let permalink = null;
      try {
        const detail = await call(
          `${GRAPH}/${postId}?fields=id,permalink,shortcode&access_token=${token}`,
          { platform: 'instagram' },
          fetchImpl
        );
        permalink = detail.permalink || (detail.shortcode ? `https://www.instagram.com/p/${detail.shortcode}/` : null);
      } catch {
        // Permalink lookup is best-effort: post is live even if lookup fails
      }
      return {
        postId,
        releaseUrl: permalink || null
      };
    },

    async describePublished(containerId) {
      // A container that already published exposes the live media id here, which
      // is what lets a crashed run record the ORIGINAL post instead of making a
      // second one.
      const body = await call(
        `${GRAPH}/${containerId}?fields=id,permalink,shortcode&access_token=${token}`,
        { platform: 'instagram' },
        fetchImpl
      );
      const permalink = body.permalink || (body.shortcode ? `https://www.instagram.com/p/${body.shortcode}/` : null);
      return { postId: body.id, releaseUrl: permalink };
    }
  };
}

// ===========================================================================
// Threads (two-step, different host)
// ===========================================================================
/**
 * Threads is NOT on graph.facebook.com - it has its own host and its own app
 * credentials. Text-only posts are supported (unlike Instagram).
 *
 *   1. POST /{user-id}/threads          -> creation id
 *   2. GET  /{creation-id}?fields=status  until FINISHED   (media posts)
 *   3. POST /{user-id}/threads_publish  -> thread id
 */
export function threadsAdapter({ userId, accessToken, post, fetchImpl = fetch }) {
  if (!userId) throw new Error('threadsAdapter: userId is required');
  if (!accessToken) throw new Error('threadsAdapter: accessToken is required');

  const token = enc(accessToken);

  return {
    platform: 'threads',

    async createContainer() {
      const { caption = '', mediaUrl = '', mediaType = 'text' } = post;
      const params = new URLSearchParams();

      if (mediaUrl && mediaType === 'image') {
        params.set('media_type', 'IMAGE');
        params.set('image_url', mediaUrl);
      } else if (mediaUrl && mediaType === 'video') {
        params.set('media_type', 'VIDEO');
        params.set('video_url', mediaUrl);
      } else {
        params.set('media_type', 'TEXT');
      }
      params.set('text', caption);
      params.set('access_token', accessToken);

      const body = await call(
        `${THREADS}/${userId}/threads?${params.toString()}`,
        { method: 'POST', platform: 'threads' },
        fetchImpl
      );
      return { containerId: body.id };
    },

    async checkContainer(containerId) {
      const body = await call(
        `${THREADS}/${containerId}?fields=status,error_message&access_token=${token}`,
        { platform: 'threads' },
        fetchImpl
      );
      // Threads reports FINISHED / IN_PROGRESS / ERROR / PUBLISHED via `status`.
      return body.status;
    },

    async publishContainer(containerId) {
      const body = await call(
        `${THREADS}/${userId}/threads_publish?creation_id=${enc(containerId)}&access_token=${token}`,
        { method: 'POST', platform: 'threads' },
        fetchImpl
      );
      const threadId = body.id;
      let permalink = null;
      try {
        const detail = await call(
          `${THREADS}/${threadId}?fields=id,permalink&access_token=${token}`,
          { platform: 'threads' },
          fetchImpl
        );
        permalink = detail.permalink || null;
      } catch {
        // The post is live; only the permalink lookup failed. Losing the link
        // must not turn a successful publish into a failure.
      }
      return { postId: threadId, releaseUrl: permalink };
    },

    async describePublished(containerId) {
      const body = await call(
        `${THREADS}/${containerId}?fields=id,permalink&access_token=${token}`,
        { platform: 'threads' },
        fetchImpl
      );
      return { postId: body.id, releaseUrl: body.permalink || null };
    }
  };
}

/**
 * Builds the driver map for one calendar entry from environment configuration.
 * Platforms without credentials are omitted rather than stubbed, so a missing
 * channel is visible instead of silently "succeeding".
 */
export function buildDrivers(post, env = process.env, fetchImpl = fetch) {
  const drivers = {};

  if (env.FACEBOOK_PAGE_ID && env.FACEBOOK_PAGE_ACCESS_TOKEN) {
    drivers.facebook = facebookAdapter({
      pageId: env.FACEBOOK_PAGE_ID,
      pageAccessToken: env.FACEBOOK_PAGE_ACCESS_TOKEN,
      post,
      fetchImpl
    });
  }
  if (env.INSTAGRAM_BUSINESS_ACCOUNT_ID && env.FACEBOOK_PAGE_ACCESS_TOKEN) {
    drivers.instagram = instagramAdapter({
      igUserId: env.INSTAGRAM_BUSINESS_ACCOUNT_ID,
      accessToken: env.FACEBOOK_PAGE_ACCESS_TOKEN,
      post,
      fetchImpl
    });
  }
  if (env.THREADS_USER_ID && env.THREADS_ACCESS_TOKEN) {
    drivers.threads = threadsAdapter({
      userId: env.THREADS_USER_ID,
      accessToken: env.THREADS_ACCESS_TOKEN,
      post,
      fetchImpl
    });
  }

  return drivers;
}

export const GRAPH_BASE = GRAPH;
export const THREADS_BASE = THREADS;
