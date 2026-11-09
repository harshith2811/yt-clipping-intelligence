/**
 * Publishing failure taxonomy.
 *
 * Adapted from the three-way split used by the Postiz engine (refresh_token /
 * disconnect / bad_body), which is the single most important thing that
 * separates a publisher that stays healthy from one that silently rots.
 *
 * Our pipeline previously treated every failure as "retry, then email an
 * alert". That is precisely how the Threads and YouTube tokens went stale
 * while the dashboard still reported four channels connected: a dead channel
 * was being retried forever instead of surfacing as "reconnect this channel".
 *
 * The three kinds:
 *
 *   AUTH_EXPIRED      The credential is the problem, not the post. Refresh if we
 *                     hold a refresh token; otherwise the channel needs a human
 *                     to reconnect it. NEVER loop on this.
 *   TRANSIENT_NETWORK The platform was momentarily unable to serve us (5xx,
 *                     rate limit, socket error). Retry with backoff.
 *   FATAL_PAYLOAD     This specific post will never succeed (aspect ratio,
 *                     duration, caption length, unsupported media). Fail the
 *                     post, leave the channel healthy.
 */

export const AUTH_EXPIRED = 'AUTH_EXPIRED';
export const TRANSIENT_NETWORK = 'TRANSIENT_NETWORK';
export const FATAL_PAYLOAD = 'FATAL_PAYLOAD';

export const CHANNEL_STATUS = {
  [AUTH_EXPIRED]: 'Needs Reconnect',
  [TRANSIENT_NETWORK]: 'Retrying',
  [FATAL_PAYLOAD]: 'Failed - Revision Needed'
};

// Socket-level failures never reached the platform, so they are always safe to
// retry and never indicate anything about the post or the credential.
const NETWORK_ERRNOS = new Set([
  'ECONNRESET', 'ETIMEDOUT', 'ECONNREFUSED', 'ENOTFOUND',
  'EAI_AGAIN', 'EPIPE', 'ERR_SOCKET_CONNECTION_TIMEOUT'
]);

// Meta Graph API. code 190 is the OAuthException family; the subcode narrows it.
// 458 app-unauthorised, 459 checkpointed, 460 password changed, 463 expired,
// 464 unconfirmed user, 467 invalid access token - all require a human or a
// refresh, none are retryable as-is.
const META_AUTH_SUBCODES = new Set([458, 459, 460, 463, 464, 467, 492]);

// Meta media errors (the 2207xxx family) describe the *file*: wrong aspect
// ratio, too long, unsupported codec, fetch failed. Retrying is pointless.
const META_MEDIA_CODE_PREFIX = '2207';

function text(value) {
  if (value === null || value === undefined) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

/**
 * @param {object} failure
 * @param {number} [failure.status]    HTTP status code
 * @param {string} [failure.code]      Node errno, e.g. 'ECONNRESET'
 * @param {object} [failure.body]      Parsed platform response body
 * @param {string} [failure.platform]  'instagram' | 'facebook' | 'youtube' | ...
 * @returns {{kind: string, retryable: boolean, channelStatus: string, reason: string}}
 */
export function classifyFailure(failure = {}) {
  const { status, code, body, platform } = failure;
  const blob = text(body).toLowerCase();

  const decide = (kind, reason) => ({
    kind,
    retryable: kind === TRANSIENT_NETWORK,
    channelStatus: CHANNEL_STATUS[kind],
    reason
  });

  // 1. Never reached the platform.
  if (code && NETWORK_ERRNOS.has(code)) {
    return decide(TRANSIENT_NETWORK, `socket error ${code}`);
  }

  // 2. Meta's structured errors are more precise than the HTTP status, so they
  //    are read before falling back to status-code heuristics.
  const metaError = body?.error;
  if (metaError) {
    const metaCode = Number(metaError.code);
    const subCode = Number(metaError.error_subcode);

    if (metaCode === 190 || META_AUTH_SUBCODES.has(subCode)) {
      return decide(AUTH_EXPIRED, `Meta OAuthException code=${metaCode} subcode=${subCode || 'none'}`);
    }
    if (String(metaError.error_subcode || '').startsWith(META_MEDIA_CODE_PREFIX)) {
      return decide(FATAL_PAYLOAD, `Meta media error subcode=${subCode}`);
    }
    // code 4 / 17 / 32 / 613 are throttles: the app is over its call budget.
    if ([4, 17, 32, 613].includes(metaCode)) {
      return decide(TRANSIENT_NETWORK, `Meta rate limit code=${metaCode}`);
    }
    // code 10 / 200-299 are permission problems - a scope was never granted or
    // was revoked. Retrying cannot grant a scope.
    if (metaCode === 10 || (metaCode >= 200 && metaCode <= 299)) {
      return decide(AUTH_EXPIRED, `Meta permission error code=${metaCode}`);
    }
  }

  // 3. Google/YouTube structured errors.
  const googleReason = body?.error?.errors?.[0]?.reason || body?.error?.status;
  if (googleReason) {
    const reason = String(googleReason);
    if (['authError', 'invalid_grant', 'UNAUTHENTICATED', 'invalidCredentials'].includes(reason)) {
      return decide(AUTH_EXPIRED, `Google ${reason}`);
    }
    // Quotas reset; this is a wait, not a defect.
    if (['quotaExceeded', 'rateLimitExceeded', 'userRateLimitExceeded',
         'uploadLimitExceeded', 'backendError'].includes(reason)) {
      return decide(TRANSIENT_NETWORK, `Google ${reason}`);
    }
    if (['invalidVideoMetadata', 'invalidTitle', 'invalidDescription',
         'mediaBodyRequired', 'failedPrecondition'].includes(reason)) {
      return decide(FATAL_PAYLOAD, `Google ${reason}`);
    }
  }

  // 4. OAuth 2.0 standard error field (token endpoints).
  if (body?.error === 'invalid_grant' || body?.error === 'invalid_token') {
    return decide(AUTH_EXPIRED, `OAuth ${body.error}`);
  }
  // invalid_client means OUR app credentials are wrong - no amount of user
  // reconnection fixes that, but it is still an auth problem for an operator.
  if (body?.error === 'invalid_client') {
    return decide(AUTH_EXPIRED, 'OAuth invalid_client - check app credentials');
  }

  // 5. Status-code fallback.
  if (status === 401) return decide(AUTH_EXPIRED, 'HTTP 401');
  if (status === 429) return decide(TRANSIENT_NETWORK, 'HTTP 429 rate limited');
  if (status >= 500) return decide(TRANSIENT_NETWORK, `HTTP ${status}`);

  if (status === 403) {
    // 403 is ambiguous: a quota exhaustion or a revoked permission. The body
    // decides; default to auth, because retrying a revoked permission forever
    // is the failure mode we are trying to eliminate.
    if (/quota|rate|limit/.test(blob)) return decide(TRANSIENT_NETWORK, 'HTTP 403 quota');
    return decide(AUTH_EXPIRED, 'HTTP 403');
  }

  if (status === 400 || status === 422) {
    if (/token|credential|oauth|session/.test(blob)) return decide(AUTH_EXPIRED, `HTTP ${status} token error`);
    return decide(FATAL_PAYLOAD, `HTTP ${status}`);
  }

  // 6. Unknown. Treated as transient so a one-off oddity is retried, but the
  //    backoff cap in the state machine stops it looping indefinitely.
  return decide(TRANSIENT_NETWORK, `unclassified${status ? ` HTTP ${status}` : ''}${platform ? ` (${platform})` : ''}`);
}

/**
 * Exponential backoff with jitter, capped.
 *
 * Jitter matters because all channels for one post fail together when a token
 * dies; without it they would retry in lockstep and hammer the platform.
 */
export function backoffMs(retryCount, { base = 60_000, cap = 6 * 60 * 60 * 1000 } = {}) {
  const exponential = Math.min(cap, base * Math.pow(2, Math.max(0, retryCount)));
  return Math.round(exponential * (0.5 + Math.random() * 0.5));
}

export const MAX_RETRIES = 6;

/**
 * Decides what the dispatcher should do next.
 * Returns { action: 'retry'|'halt', ... } - 'halt' means stop and surface it.
 */
export function nextAction(failure, retryCount = 0) {
  const verdict = classifyFailure(failure);

  if (!verdict.retryable) {
    return { action: 'halt', ...verdict, retryCount };
  }
  if (retryCount >= MAX_RETRIES) {
    return {
      action: 'halt',
      ...verdict,
      channelStatus: 'Failed - Revision Needed',
      reason: `${verdict.reason} (gave up after ${retryCount} retries)`,
      retryCount
    };
  }
  return { action: 'retry', ...verdict, retryCount: retryCount + 1, retryInMs: backoffMs(retryCount) };
}
