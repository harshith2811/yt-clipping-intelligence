/**
 * Pinterest publishing adapter.
 *
 * Implements the same driver contract as meta.js so state.js drives it
 * unchanged.
 *
 * Base: https://api.pinterest.com/v5
 * Auth: Authorization: Bearer {token}. Requires a Pinterest BUSINESS account,
 * and every pin needs a target board_id.
 *
 * ZERO-RAM: an image pin is a single POST carrying
 *   media_source: { source_type: 'image_url', url: '<public url>' }
 * so Pinterest fetches the file itself and no bytes pass through this process.
 *
 * Video is deliberately NOT implemented here. Pinterest video needs a
 * three-step pre-signed S3-style upload where the order of the
 * upload_parameters form fields matters, and getting it subtly wrong fails in
 * ways that are hard to diagnose. Until the practice actually needs video pins,
 * a clear "not supported" beats a half-working path that silently drops posts.
 */

import { MetaApiError } from './meta.js';

const API = 'https://api.pinterest.com/v5';

async function pinFetch(url, { method = 'GET', token, body } = {}, fetchImpl = fetch) {
  let res;
  try {
    res = await fetchImpl(url, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { 'Content-Type': 'application/json' } : {})
      },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
  } catch (err) {
    throw new MetaApiError(err.message, { platform: 'pinterest', endpoint: url });
  }

  let parsed = null;
  try { parsed = await res.json(); } catch { parsed = null; }

  if (!res.ok) {
    throw new MetaApiError(parsed?.message || `HTTP ${res.status}`, {
      status: res.status, body: parsed, platform: 'pinterest', endpoint: url
    });
  }
  return parsed;
}

/**
 * @param {object} opts
 * @param {string} opts.accessToken
 * @param {string} opts.boardId
 * @param {object} opts.post  { caption, title, mediaUrl, mediaType, link }
 */
export function pinterestAdapter({ accessToken, boardId, post, fetchImpl = fetch }) {
  if (!accessToken) throw new Error('pinterestAdapter: accessToken is required');
  if (!boardId) throw new Error('pinterestAdapter: boardId is required');

  return {
    platform: 'pinterest',

    async createContainer() {
      const { caption = '', title = '', mediaUrl = '', mediaType = 'image', link = '' } = post;

      if (!mediaUrl) {
        throw new MetaApiError('Pinterest requires an image URL', {
          status: 400,
          body: { message: 'media required', code: 'CONFIGURATION_ERROR' },
          platform: 'pinterest'
        });
      }
      if (mediaType === 'video') {
        throw new MetaApiError('Pinterest video pins are not implemented', {
          status: 400,
          body: { message: 'video unsupported', code: 'CONFIGURATION_ERROR' },
          platform: 'pinterest'
        });
      }

      const created = await pinFetch(`${API}/pins`, {
        method: 'POST',
        token: accessToken,
        body: {
          board_id: boardId,
          title: (title || caption).slice(0, 100),
          description: caption.slice(0, 800),
          ...(link ? { link } : {}),
          media_source: { source_type: 'image_url', url: mediaUrl }
        }
      }, fetchImpl);

      return {
        postId: created.id,
        releaseUrl: `https://www.pinterest.com/pin/${created.id}/`
      };
    },

    async checkContainer() { return 'PUBLISHED'; },
    async publishContainer(containerId) {
      return { postId: containerId, releaseUrl: `https://www.pinterest.com/pin/${containerId}/` };
    },
    async describePublished(containerId) {
      return { postId: containerId, releaseUrl: `https://www.pinterest.com/pin/${containerId}/` };
    }
  };
}

/** Board discovery — used by diagnostics and to configure PINTEREST_BOARD_ID. */
export async function listBoards(accessToken, fetchImpl = fetch) {
  const data = await pinFetch(`${API}/boards?page_size=250`, { token: accessToken }, fetchImpl);
  return (data?.items || []).map(b => ({ id: b.id, name: b.name, privacy: b.privacy }));
}

/**
 * Lightweight probe for the pre-flight endpoint.
 * Verifies the token AND that the configured board actually exists - a valid
 * token pointing at a deleted board fails only at publish time otherwise.
 */
export async function pinterestProbe(env = process.env, fetchImpl = fetch) {
  const token = env.PINTEREST_ACCESS_TOKEN;
  const boardId = env.PINTEREST_BOARD_ID;

  if (!token) {
    return { ready: false, status: 'NEEDS_CONFIGURATION', detail: 'PINTEREST_ACCESS_TOKEN not set' };
  }

  try {
    const res = await fetchImpl(`${API}/user_account`, {
      headers: { Authorization: `Bearer ${token}` }
    });

    if (res.status === 401) {
      return { ready: false, status: 'AUTH_EXPIRED', detail: 'Pinterest rejected the token (HTTP 401)' };
    }
    if (res.status === 403) {
      return { ready: false, status: 'PERMISSION_DENIED', detail: 'Token lacks the required scope (HTTP 403)' };
    }
    if (!res.ok) {
      return { ready: false, status: 'ERROR', detail: `user_account returned HTTP ${res.status}` };
    }

    const account = await res.json().catch(() => ({}));

    if (!boardId) {
      let boards = [];
      try { boards = await listBoards(token, fetchImpl); } catch { /* non-fatal */ }
      return {
        ready: false,
        status: 'NEEDS_CONFIGURATION',
        detail: 'PINTEREST_BOARD_ID not set',
        account: account?.username || null,
        availableBoards: boards.slice(0, 10)
      };
    }

    let boards = [];
    try { boards = await listBoards(token, fetchImpl); } catch { /* non-fatal */ }
    const match = boards.find(b => b.id === boardId);
    if (boards.length && !match) {
      return {
        ready: false,
        status: 'CONFIGURATION_ERROR',
        detail: `PINTEREST_BOARD_ID ${boardId} is not among this account's boards`,
        account: account?.username || null
      };
    }

    return {
      ready: true,
      status: 'READY',
      account: account?.username || null,
      board: match?.name || boardId
    };
  } catch (err) {
    return { ready: false, status: 'NETWORK_ERROR', detail: err.message };
  }
}

export const PINTEREST_API = API;
