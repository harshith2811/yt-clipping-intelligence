/**
 * LinkedIn publishing adapter.
 *
 * Implements the same driver contract as meta.js (createContainer /
 * checkContainer / publishContainer / describePublished) so state.js can drive
 * it without special-casing.
 *
 * API family: https://api.linkedin.com/rest/posts (the versioned REST API, not
 * the legacy /v2/ugcPosts). Every versioned call needs BOTH headers:
 *
 *   LinkedIn-Version: YYYYMM
 *   X-Restli-Protocol-Version: 2.0.0
 *
 * Omitting either returns a confusing 426 / 400 rather than a clear error,
 * which is the usual reason a "correct-looking" LinkedIn integration fails.
 *
 * MEDIA AND MEMORY
 * ----------------
 * LinkedIn is the one platform here with no public-URL handoff: it requires the
 * image bytes to be PUT to an upload URL it issues. To keep this viable on a
 * 512MB instance the bytes are STREAMED from the source URL straight into the
 * upload request (response.body piped into the PUT) - they are never collected
 * into a Buffer. Peak memory is therefore a socket buffer, not the file size.
 */

import { MetaApiError } from './meta.js';

const API = 'https://api.linkedin.com';
// LinkedIn requires a concrete version stamp; it is an API contract date, not
// a value to invent at runtime.
const VERSION = process.env.LINKEDIN_API_VERSION || '202601';

function headers(token, extra = {}) {
  return {
    Authorization: `Bearer ${token}`,
    'X-Restli-Protocol-Version': '2.0.0',
    'LinkedIn-Version': VERSION,
    ...extra
  };
}

/**
 * LinkedIn returns errors as JSON with `status`/`message`, but also uses plain
 * 401/403. Throwing MetaApiError keeps one error shape across every adapter so
 * classify.js needs no per-platform branch.
 */
async function ljson(res, url) {
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) {
    throw new MetaApiError(body?.message || `HTTP ${res.status}`, {
      status: res.status, body, platform: 'linkedin', endpoint: url
    });
  }
  return body;
}

/**
 * Streams media from a public URL into LinkedIn's upload URL.
 * Never buffers the file: response.body is piped directly into the PUT.
 */
async function streamUpload(uploadUrl, mediaUrl, token, fetchImpl) {
  const source = await fetchImpl(mediaUrl);
  if (!source.ok) {
    throw new MetaApiError(`Could not fetch media (${source.status})`, {
      status: source.status, body: null, platform: 'linkedin', endpoint: mediaUrl
    });
  }

  const res = await fetchImpl(uploadUrl, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}` },
    body: source.body,
    // Node's fetch requires this when the body is a stream.
    duplex: 'half'
  });

  if (!res.ok) {
    throw new MetaApiError(`Upload failed (HTTP ${res.status})`, {
      status: res.status, body: null, platform: 'linkedin', endpoint: uploadUrl
    });
  }
}

/**
 * @param {object} opts
 * @param {string} opts.accessToken
 * @param {string} opts.authorUrn  urn:li:person:xxx or urn:li:organization:xxx
 * @param {object} opts.post       { caption, mediaUrl, mediaType, link }
 */
export function linkedinAdapter({ accessToken, authorUrn, post, fetchImpl = fetch }) {
  if (!accessToken) throw new Error('linkedinAdapter: accessToken is required');
  if (!authorUrn) throw new Error('linkedinAdapter: authorUrn is required');
  if (!/^urn:li:(person|organization):/.test(authorUrn)) {
    throw new Error(`linkedinAdapter: authorUrn must be urn:li:person:<id> or urn:li:organization:<id>, got "${authorUrn}"`);
  }

  return {
    platform: 'linkedin',

    async createContainer() {
      const { caption = '', mediaUrl = '', mediaType = 'text', link = '' } = post;

      const body = {
        author: authorUrn,
        commentary: caption,
        visibility: 'PUBLIC',
        distribution: {
          feedDistribution: 'MAIN_FEED',
          targetEntities: [],
          thirdPartyDistributionChannels: []
        },
        lifecycleState: 'PUBLISHED',
        isReshareDisabledByAuthor: false
      };

      if (mediaType === 'video' && !mediaUrl) {
        throw new MetaApiError('LinkedIn video post requires a media URL', {
          status: 400, body: null, platform: 'linkedin'
        });
      }

      if (mediaUrl && (mediaType === 'image' || mediaType === 'video')) {
        const isVideo = mediaType === 'video' || /\.(mp4|mov|webm)(\?|$)/i.test(mediaUrl);
        const endpoint = isVideo ? `${API}/rest/videos?action=initializeUpload` : `${API}/rest/images?action=initializeUpload`;

        // 1. Ask LinkedIn where to put the bytes.
        const init = await ljson(
          await fetchImpl(endpoint, {
            method: 'POST',
            headers: headers(accessToken, { 'Content-Type': 'application/json' }),
            body: JSON.stringify({ initializeUploadRequest: { owner: authorUrn } })
          }),
          endpoint
        );

        const uploadUrl = init?.value?.uploadUrl || init?.value?.uploadInstructions?.[0]?.uploadUrl;
        const assetUrn = init?.value?.image || init?.value?.video;
        if (!uploadUrl || !assetUrn) {
          throw new MetaApiError(`initializeUpload returned no uploadUrl/${isVideo ? 'video' : 'image'}`, {
            status: 502, body: init, platform: 'linkedin'
          });
        }

        // 2. Stream the bytes through without buffering them.
        await streamUpload(uploadUrl, mediaUrl, accessToken, fetchImpl);

        body.content = { media: { id: assetUrn, ...(caption ? { title: caption.slice(0, 400) } : {}) } };
      } else if (link) {
        // Article/link share.
        body.content = { article: { source: link, title: (caption || link).slice(0, 400) } };
      }

      const res = await fetchImpl(`${API}/rest/posts`, {
        method: 'POST',
        headers: headers(accessToken, { 'Content-Type': 'application/json' }),
        body: JSON.stringify(body)
      });

      if (!res.ok) {
        let errBody = null;
        try { errBody = await res.json(); } catch { /* LinkedIn sometimes returns empty */ }
        throw new MetaApiError(errBody?.message || `HTTP ${res.status}`, {
          status: res.status, body: errBody, platform: 'linkedin', endpoint: `${API}/rest/posts`
        });
      }

      // The post URN comes back in a header, not the body - the body is empty
      // on success, which makes this easy to get wrong.
      const postUrn =
        res.headers?.get?.('x-restli-id') ||
        res.headers?.get?.('x-linkedin-id') ||
        null;

      if (!postUrn) {
        throw new MetaApiError('LinkedIn accepted the post but returned no id header', {
          status: res.status, body: null, platform: 'linkedin'
        });
      }

      return {
        postId: postUrn,
        releaseUrl: `https://www.linkedin.com/feed/update/${postUrn}`
      };
    },

    // LinkedIn publishes synchronously; these exist for contract completeness.
    async checkContainer() { return 'PUBLISHED'; },
    async publishContainer(containerId) {
      return { postId: containerId, releaseUrl: `https://www.linkedin.com/feed/update/${containerId}` };
    },
    async describePublished(containerId) {
      return { postId: containerId, releaseUrl: `https://www.linkedin.com/feed/update/${containerId}` };
    }
  };
}

/**
 * Lightweight credential probe for the pre-flight endpoint.
 * Never returns or logs the token.
 */
export async function linkedinProbe(env = process.env, fetchImpl = fetch) {
  const token = env.LINKEDIN_ACCESS_TOKEN;
  const author = env.LINKEDIN_AUTHOR_URN;

  if (!token || !author) {
    return {
      ready: false,
      status: 'NEEDS_CONFIGURATION',
      detail: !token && !author
        ? 'LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_URN not set'
        : !token ? 'LINKEDIN_ACCESS_TOKEN not set' : 'LINKEDIN_AUTHOR_URN not set'
    };
  }

  try {
    const res = await fetchImpl(`${API}/v2/userinfo`, { headers: headers(token) });
    if (res.ok) {
      const me = await res.json().catch(() => ({}));
      // /v2/userinfo is OpenID Connect's PERSON endpoint. For an
      // organization-scoped token (posting as a Company Page, which is the
      // practice's actual use case - urn:li:organization:...) me.name is the
      // ADMIN who authorized the app, not the page. LINKEDIN_DISPLAY_NAME is
      // set explicitly for exactly this reason and wins when present; me.name
      // is still a reasonable fallback for a person-scoped token with no
      // display name configured, and the raw URN is the last resort.
      const account = env.LINKEDIN_DISPLAY_NAME || me?.name || author;
      return { ready: true, status: 'READY', account, authorUrn: author };
    }
    return {
      ready: false,
      status: res.status === 401 ? 'AUTH_EXPIRED' : 'ERROR',
      detail: `userinfo returned HTTP ${res.status}`
    };
  } catch (err) {
    return { ready: false, status: 'NETWORK_ERROR', detail: err.message };
  }
}

export const LINKEDIN_API = API;
export const LINKEDIN_VERSION = VERSION;
