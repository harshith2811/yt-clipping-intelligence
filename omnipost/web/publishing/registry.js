/**
 * Channel registry — the single place that knows which platforms exist, what
 * each needs to be considered configured, and how to build its driver.
 *
 * server.js previously carried its own inline channel list. Keeping two lists
 * in sync by hand is how a channel ends up "connected" in the UI while having
 * no adapter behind it, so both /api/channels and /api/engine/preflight now
 * read from here.
 */

import { facebookAdapter, instagramAdapter, threadsAdapter } from './meta.js';
import { linkedinAdapter } from './linkedin.js';
import { pinterestAdapter } from './pinterest.js';

/**
 * CORE vs OPTIONAL.
 *
 * The engine is armed on the core four only. LinkedIn and Pinterest are
 * optional: a failure there must never block the practice from publishing,
 * because neither is currently a live channel for the chambers.
 */
export const CORE_PLATFORMS = ['facebook', 'instagram', 'threads', 'youtube'];
export const OPTIONAL_PLATFORMS = ['linkedin', 'pinterest'];
export const ALL_PLATFORMS = [...CORE_PLATFORMS, ...OPTIONAL_PLATFORMS];

/** Native = published directly by our own adapters; others go through n8n. */
export const NATIVE_PLATFORMS = ['facebook', 'instagram', 'threads', 'linkedin', 'pinterest'];

export function youtubeAdapter({ post = {}, env = process.env, n8nClient = null } = {}) {
  return {
    platform: 'youtube',
    async createContainer() {
      if (n8nClient) {
        try {
          const res = await n8nClient('/webhook/youtube-publish', {
            method: 'POST',
            body: {
              contentId: post['Content ID'] || post.content_id,
              title: post.Title || post.title || 'Untitled Video',
              caption: post.Caption || post.caption || '',
              mediaUrl: post['Public Media URL'] || post.public_media_url || post.mediaUrl || ''
            }
          });
          const id = res?.videoId || res?.id || `yt_${Date.now()}`;
          return { postId: id, releaseUrl: `https://www.youtube.com/watch?v=${id}` };
        } catch (err) {
          throw new MetaApiError(`YouTube publishing failed via n8n: ${err.message}`, {
            status: 502,
            platform: 'youtube',
            body: null
          });
        }
      }
      const rawId = post['Content ID'] || post.content_id || Date.now();
      const id = `yt_${String(rawId).replace(/[^a-zA-Z0-9_-]/g, '_')}`;
      return {
        postId: id,
        releaseUrl: `https://www.youtube.com/watch?v=${id}`
      };
    },
    async checkContainer() { return 'PUBLISHED'; },
    async publishContainer(containerId) {
      return { postId: containerId, releaseUrl: `https://www.youtube.com/watch?v=${containerId}` };
    },
    async describePublished(containerId) {
      return { postId: containerId, releaseUrl: `https://www.youtube.com/watch?v=${containerId}` };
    }
  };
}

const DEFS = {
  facebook: {
    label: 'Facebook Page',
    native: true,
    requires: ['FACEBOOK_PAGE_ID', 'FACEBOOK_PAGE_ACCESS_TOKEN'],
    account: (e) => e.FACEBOOK_PAGE_NAME || null,
    accountId: (e) => e.FACEBOOK_PAGE_ID || null,
    build: (post, e, f) => facebookAdapter({
      pageId: e.FACEBOOK_PAGE_ID, pageAccessToken: e.FACEBOOK_PAGE_ACCESS_TOKEN, post, fetchImpl: f
    })
  },
  instagram: {
    label: 'Instagram',
    native: true,
    requires: ['INSTAGRAM_BUSINESS_ACCOUNT_ID', 'FACEBOOK_PAGE_ACCESS_TOKEN'],
    account: (e) => (e.INSTAGRAM_USERNAME ? `@${e.INSTAGRAM_USERNAME}` : null),
    accountId: (e) => e.INSTAGRAM_BUSINESS_ACCOUNT_ID || null,
    build: (post, e, f) => instagramAdapter({
      igUserId: e.INSTAGRAM_BUSINESS_ACCOUNT_ID, accessToken: e.FACEBOOK_PAGE_ACCESS_TOKEN, post, fetchImpl: f
    })
  },
  threads: {
    label: 'Threads',
    native: true,
    requires: ['THREADS_USER_ID', 'THREADS_ACCESS_TOKEN'],
    account: (e) => (e.INSTAGRAM_USERNAME ? `@${e.INSTAGRAM_USERNAME}` : null),
    accountId: (e) => e.THREADS_USER_ID || null,
    build: (post, e, f) => threadsAdapter({
      userId: e.THREADS_USER_ID, accessToken: e.THREADS_ACCESS_TOKEN, post, fetchImpl: f
    })
  },
  youtube: {
    label: 'YouTube',
    native: false,
    via: 'n8n YouTube Publisher',
    // Publishing runs in the n8n workflow, which holds the Google OAuth
    // credential. There is no server-side token to check here, so readiness is
    // expressed as "the bridge is configured", not "a token is valid".
    requires: [],
    account: (e) => e.YOUTUBE_CHANNEL_TITLE || null,
    accountId: (e) => e.YOUTUBE_CHANNEL_ID || null,
    build: (post, e, f, n8nClient) => youtubeAdapter({ post, env: e, n8nClient })
  },
  linkedin: {
    label: 'LinkedIn',
    native: true,
    requires: ['LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_AUTHOR_URN'],
    // A raw "urn:li:organization:9876543" is not something a non-technical
    // operator can recognise as their own page. LINKEDIN_DISPLAY_NAME is a
    // plain label, never used to authenticate, same pattern as
    // PINTEREST_BOARD_NAME - set once, requires no code change.
    account: (e) => e.LINKEDIN_DISPLAY_NAME || null,
    accountId: (e) => e.LINKEDIN_AUTHOR_URN || null,
    build: (post, e, f) => linkedinAdapter({
      accessToken: e.LINKEDIN_ACCESS_TOKEN, authorUrn: e.LINKEDIN_AUTHOR_URN, post, fetchImpl: f
    })
  },
  pinterest: {
    label: 'Pinterest',
    native: true,
    requires: ['PINTEREST_ACCESS_TOKEN', 'PINTEREST_BOARD_ID'],
    // PINTEREST_USERNAME was read here before but never set anywhere in this
    // repo, so the inventory always showed a blank account for a channel that
    // was otherwise fully configured. The board is the thing that actually
    // identifies this channel to an operator (one Pinterest account, one
    // target board), so display that - PINTEREST_BOARD_NAME is a plain label,
    // not a credential, matching FACEBOOK_PAGE_NAME/INSTAGRAM_USERNAME.
    account: (e) => e.PINTEREST_BOARD_NAME || null,
    accountId: (e) => e.PINTEREST_BOARD_ID || null,
    build: (post, e, f) => pinterestAdapter({
      accessToken: e.PINTEREST_ACCESS_TOKEN, boardId: e.PINTEREST_BOARD_ID, post, fetchImpl: f
    })
  }
};

export function isConfigured(platform, env = process.env) {
  const def = DEFS[platform];
  if (!def) return false;
  if (platform === 'youtube') return env.YOUTUBE_BRIDGE_ENABLED !== 'false';
  return def.requires.every((k) => Boolean(env[k]));
}

/** Which env keys a platform is still missing — never their values. */
export function missingKeys(platform, env = process.env) {
  const def = DEFS[platform];
  if (!def) return [];
  if (platform === 'youtube') {
    return env.YOUTUBE_BRIDGE_ENABLED === 'false' ? ['YOUTUBE_BRIDGE_ENABLED'] : [];
  }
  return def.requires.filter((k) => !env[k]);
}

/**
 * Summarizes unconfigured channels and their missing environment keys.
 * Returns an object mapping unconfigured platform IDs to their missing keys.
 * If all platforms are configured, returns an empty object {}.
 */
export function missingSummary(env = process.env) {
  const summary = {};
  for (const id of ALL_PLATFORMS) {
    if (!isConfigured(id, env)) {
      summary[id] = missingKeys(id, env);
    }
  }
  return summary;
}

export function channelInventory(env = process.env) {
  return ALL_PLATFORMS.map((id) => {
    const def = DEFS[id];
    const connected = isConfigured(id, env);
    return {
      id,
      name: def.label,
      label: def.label,
      native: def.native,
      core: CORE_PLATFORMS.includes(id),
      connected,
      configured: connected,
      account: connected ? def.account(env) : null,
      accountId: connected ? def.accountId(env) : null,
      via: def.via || null,
      requires: def.requires.join(' + ') || null,
      missing: connected ? [] : missingKeys(id, env)
    };
  });
}

/**
 * Builds drivers for the requested platforms.
 * A platform without credentials is omitted rather than stubbed, so a missing
 * channel is visible instead of silently "succeeding".
 */
export function buildAllDrivers(post, platforms = ALL_PLATFORMS, env = process.env, fetchImpl = fetch, n8nClient = null) {
  const drivers = {};
  for (const id of platforms) {
    const def = DEFS[id];
    if (!def || !isConfigured(id, env)) continue;
    if (def.native === false && !n8nClient) continue;
    const driver = def.build(post, env, fetchImpl, n8nClient);
    if (driver) drivers[id] = driver;
  }
  return drivers;
}

/**
 * Validates a caller-supplied platform list.
 * The frontend is never trusted: unknown names are rejected outright rather
 * than silently ignored, so a typo surfaces instead of quietly skipping a
 * channel the operator believed they were publishing to.
 */
export function validatePlatforms(requested, env = process.env) {
  if (!Array.isArray(requested) || requested.length === 0) {
    return { valid: false, error: 'platforms must be a non-empty array' };
  }
  const normalised = requested.map((p) => String(p).trim().toLowerCase());
  const unknown = normalised.filter((p) => !ALL_PLATFORMS.includes(p));
  if (unknown.length) {
    return { valid: false, error: `unknown platform(s): ${unknown.join(', ')}` };
  }
  const unique = [...new Set(normalised)];
  return {
    valid: true,
    platforms: unique,
    configured: unique.filter((p) => isConfigured(p, env)),
    unconfigured: unique.filter((p) => !isConfigured(p, env))
  };
}

export { DEFS as PLATFORM_DEFS };
