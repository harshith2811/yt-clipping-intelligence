/**
 * Who is calling, and what are they allowed to reach.
 *
 * This is the single source of truth for role resolution. It used to live
 * inline in server.js, with publishing/rbac.test.mjs keeping a hand-written
 * *copy* of the same logic to test against — which meant the tests could stay
 * green while the server drifted away from them. The tests now import this.
 *
 * THREE CREDENTIAL FORMS, one answer
 * ----------------------------------
 *   1. x-admin-key: <key>            the shared chambers/automation passkeys
 *   2. Authorization: Bearer <key>   the same, raw or base64
 *   3. Authorization: Bearer <JWT>   a Supabase Auth session
 *   4. Authorization: Bearer vbls1.… a portal session from /api/auth/login
 *                                    (signed, expiring; see mintSessionToken)
 *
 * Forms 1 and 2 are kept because the deployed portal and the publishing
 * heartbeat use them today; removing them would lock the practice out of its
 * own suite on the next deploy. Form 3 is the direction of travel: a shared
 * passkey cannot be revoked for one person, says nothing about WHO opened a
 * client's file, and has to be handed to CI.
 *
 * THE ROLES (chambers is a superset — the principal advocate owns both)
 *   chambers    wills, testator PII, documents, Drive lockers, AND publishing
 *   automation  the content calendar and publishing engine. Nothing else.
 *
 * WHERE A JWT'S ROLE COMES FROM
 * -----------------------------
 * `app_metadata.vbl_role`, and nowhere else. `user_metadata` is writable by
 * the user themselves through supabase.auth.updateUser(), so a role read from
 * there could be self-granted by anyone holding an account — which is the
 * whole client vault, one API call away. app_metadata is service-role-writable
 * only. The same rule is enforced again in the database by
 * automation/supabase/rbac.sql, so neither layer is load-bearing alone.
 */

import crypto from 'crypto';

export const ROLE_GRANTS = {
  chambers: ['chambers', 'automation'],
  automation: ['automation'],
  editor: ['editor', 'viewer'],
  viewer: ['viewer']
};

/**
 * Resolves an entered passkey into granted roles based on configured passkeys.
 * Supports flexible configuration key names (chambersKey / chambersPasskey / adminKey / adminPasskey,
 * automationKey / automationPasskey, editorKey / editorPasskey, viewerKey / viewerPasskey).
 *
 * @param {string} passkey - The passkey entered by the user
 * @param {object} config - Configured secret keys/passkeys
 * @returns {string[]} Granted roles array, or [] if no match
 */
export function rolesForPasskey(passkey, config = {}) {
  if (!passkey || typeof passkey !== 'string') return [];
  const entered = passkey.trim();
  if (!entered) return [];

  const chambers = config.chambersKey || config.chambersPasskey || config.adminKey || config.adminPasskey;
  if (chambers && keyMatches(entered, chambers)) {
    return ROLE_GRANTS.chambers;
  }

  const automation = config.automationKey || config.automationPasskey;
  if (automation && keyMatches(entered, automation)) {
    return ROLE_GRANTS.automation;
  }

  const editor = config.editorKey || config.editorPasskey;
  if (editor && keyMatches(entered, editor)) {
    return ROLE_GRANTS.editor || ['editor', 'viewer'];
  }

  const viewer = config.viewerKey || config.viewerPasskey;
  if (viewer && keyMatches(entered, viewer)) {
    return ROLE_GRANTS.viewer || ['viewer'];
  }

  return [];
}

/** Timing-safe compare so a wrong key cannot be recovered byte by byte. */
export function keyMatches(provided, expected) {
  if (!provided || !expected) return false;
  const a = Buffer.from(String(provided));
  const b = Buffer.from(String(expected));
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

/**
 * Does this look like a JWT rather than a passkey?
 *
 * Three base64url segments with a JSON header. Deliberately a shape test only
 * — nothing is trusted until the token is verified. Its job is to decide which
 * verification path to take, not whether the caller is genuine.
 */
export function looksLikeJwt(token) {
  if (typeof token !== 'string') return false;
  const parts = token.split('.');
  if (parts.length !== 3) return false;
  if (!parts.every((p) => p.length > 0 && /^[A-Za-z0-9_-]+$/.test(p))) return false;
  try {
    const header = JSON.parse(Buffer.from(parts[0], 'base64url').toString('utf8'));
    return typeof header === 'object' && header !== null && 'alg' in header;
  } catch {
    return false;
  }
}

/**
 * Credentials the caller presented, as raw strings.
 *
 * Returns BOTH the base64-decoded bearer and the raw one, because
 * Buffer.from(x, 'base64') does not throw on invalid base64 — it silently
 * decodes whatever it can. A try/catch around it therefore never fires, and a
 * caller sending a raw (un-encoded) bearer would be rejected even though that
 * form is documented as supported.
 */
export function presentedKeys(req) {
  const custom = req?.headers?.['x-admin-key'] || req?.headers?.['x-api-key'];
  if (custom) return [String(custom).trim()];

  const queryKey = req?.query?.apiKey || req?.query?.key;
  if (queryKey) return [String(queryKey).trim()];

  const auth = req?.headers?.['authorization'];
  if (auth && auth.startsWith('Bearer ')) {
    const raw = auth.substring(7).trim();
    const candidates = [raw];
    try {
      const decoded = Buffer.from(raw, 'base64').toString('utf-8').trim();
      if (decoded && decoded !== raw) candidates.unshift(decoded);
    } catch {
      // Unreachable in practice; kept so a future Node change cannot break auth.
    }
    return candidates;
  }
  return [];
}

/** The bearer token, when one was sent. */
export function bearerToken(req) {
  const auth = req?.headers?.['authorization'];
  if (auth && auth.startsWith('Bearer ')) return auth.substring(7).trim();
  const custom = req?.headers?.['x-admin-key'];
  return custom ? String(custom).trim() : '';
}

/**
 * Portal session tokens.
 *
 * POST /api/auth/login used to return the passkey itself, base64'd, and both
 * front ends keep that token in sessionStorage - where any script running on
 * the page can read it. One script (an uploaded "document" opened from the
 * vault, say) therefore walked off with the permanent master key.
 *
 * The login now returns `vbls1.<payload>.<hmac>`: the role and an expiry,
 * signed with a key derived from both passkeys. It holds nothing that
 * unlocks anything once it expires, and rotating either passkey voids every
 * session. The front ends need no change - they already treat the token as
 * an opaque bearer.
 */
const SESSION_PREFIX = 'vbls1';
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000;

export function sessionSigningKey(chambersKey, automationKey = '') {
  return crypto.createHash('sha256')
    .update(`portal-session-v1\n${chambersKey || ''}\n${automationKey || ''}`)
    .digest();
}

function sessionSignature(signingKey, body) {
  return crypto.createHmac('sha256', signingKey).update(body).digest('base64url');
}

export function mintSessionToken(roleOrOpts, signingKey, { ttlMs = SESSION_TTL_MS, now = Date.now() } = {}) {
  const role = typeof roleOrOpts === 'object' && roleOrOpts !== null ? roleOrOpts.role : roleOrOpts;
  if (!role || !ROLE_GRANTS[role]) throw new Error(`Unknown role: ${role}`);
  const payload = Buffer.from(JSON.stringify({
    r: role,
    exp: now + ttlMs,
    n: crypto.randomBytes(9).toString('base64url')
  })).toString('base64url');
  const body = `${SESSION_PREFIX}.${payload}`;
  return `${body}.${sessionSignature(signingKey, body)}`;
}

/** The session's role, or null when the token is not ours, altered or expired. */
export function readSessionToken(token, signingKey, now = Date.now()) {
  if (typeof token !== 'string' || !signingKey) return null;
  const parts = token.split('.');
  if (parts.length !== 3 || parts[0] !== SESSION_PREFIX) return null;
  const expected = Buffer.from(sessionSignature(signingKey, `${parts[0]}.${parts[1]}`));
  const given = Buffer.from(parts[2]);
  if (given.length !== expected.length || !crypto.timingSafeEqual(given, expected)) return null;
  let payload;
  try {
    payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'));
  } catch {
    return null;
  }
  if (!payload || !ROLE_GRANTS[payload.r] || !(Number(payload.exp) > now)) return null;
  return { role: payload.r, expiresAt: Number(payload.exp) };
}

/**
 * Mints a time-limited signed URL for private vault documents or media assets.
 */
export function mintVaultSignedUrl(filePath, signingKey, { ttlSeconds = 3600, now = Date.now() } = {}) {
  if (!signingKey) throw new Error('signingKey is required to mint signed vault URLs');
  const exp = Math.floor(now / 1000) + ttlSeconds;
  const rawPath = filePath.startsWith('/') ? filePath : `/${filePath}`;
  const canonicalPath = encodeURI(rawPath);
  const payload = `${canonicalPath}:${exp}`;
  const sig = crypto.createHmac('sha256', signingKey).update(payload).digest('base64url');
  return `${canonicalPath}?sig=${sig}&exp=${exp}`;
}

/**
 * Verifies a time-limited signed URL.
 */
export function verifyVaultSignedUrl(reqPath, sig, exp, signingKey, now = Date.now()) {
  if (!sig || !exp || !signingKey) return false;
  const expNum = Number(exp);
  if (!Number.isFinite(expNum) || expNum * 1000 < now) return false;

  const rawPath = reqPath.startsWith('/') ? reqPath : `/${reqPath}`;
  const candidates = [rawPath];
  try {
    const decoded = decodeURI(rawPath);
    if (decoded !== rawPath) candidates.push(decoded);
    const encoded = encodeURI(rawPath);
    if (encoded !== rawPath && !candidates.includes(encoded)) candidates.push(encoded);
  } catch {
    // Malformed URI sequence ignored
  }

  const sigBuf = Buffer.from(String(sig));

  for (const candidate of candidates) {
    const payload = `${candidate}:${expNum}`;
    const expectedSig = crypto.createHmac('sha256', signingKey).update(payload).digest('base64url');
    const expectedBuf = Buffer.from(expectedSig);
    if (sigBuf.length === expectedBuf.length && crypto.timingSafeEqual(sigBuf, expectedBuf)) {
      return true;
    }
  }
  return false;
}

/**
 * Builds the role resolver.
 *
 * @param {object}   opts
 * @param {string}   opts.chambersKey
 * @param {string}   opts.automationKey
 * @param {Function} [opts.verifySupabaseJwt]  async (token) => { role, userId, email } | null
 * @param {number}   [opts.cacheTtlMs]         how long a verified JWT is trusted
 * @param {Function} [opts.now]
 */
export function createResolver({
  chambersKey,
  automationKey,
  sessionKey = null,
  verifySupabaseJwt = null,
  supabaseVerifier = null,
  cacheTtlMs = 60_000,
  now = () => Date.now()
} = {}) {
  const jwtVerifier = verifySupabaseJwt || supabaseVerifier;
  // Verified JWTs are cached briefly so that a burst of requests does not turn
  // into a burst of round-trips to Supabase Auth. Keyed by a HASH of the token:
  // a Map keyed by the token itself is a bearer credential sitting in heap for
  // anyone who can read a memory dump.
  const verified = new Map();

  const fingerprint = (token) =>
    crypto.createHash('sha256').update(token).digest('base64url');

  function cacheGet(token) {
    const hit = verified.get(fingerprint(token));
    if (!hit) return null;
    if (now() > hit.expiresAt) {
      verified.delete(fingerprint(token));
      return null;
    }
    return hit.identity;
  }

  function cachePut(token, identity) {
    // Bounded: this runs in a 512MB container and the map is keyed by token.
    if (verified.size > 500) {
      for (const [k, v] of verified) if (now() > v.expiresAt) verified.delete(k);
      if (verified.size > 500) verified.clear();
    }
    verified.set(fingerprint(token), { identity, expiresAt: now() + cacheTtlMs });
  }

  /** Roles granted by the shared passkeys. Synchronous, no network. */
  function rolesFromKeys(req) {
    for (const key of presentedKeys(req)) {
      if (!key) continue;
      if (keyMatches(key, chambersKey)) return { roles: ROLE_GRANTS.chambers, via: 'chambers-key' };
      if (automationKey && keyMatches(key, automationKey)) {
        return { roles: ROLE_GRANTS.automation, via: 'automation-key' };
      }
    }
    return null;
  }

  /**
   * Full resolution: passkeys first (free), then Supabase Auth.
   * Returns { roles, via, userId?, email? }; roles is [] when unauthenticated.
   */
  async function resolve(req) {
    const byKey = rolesFromKeys(req);
    if (byKey) return byKey;

    const token = bearerToken(req);
    const session = readSessionToken(token, sessionKey, now());
    if (session) return { roles: ROLE_GRANTS[session.role], via: 'session' };
    if (!token || !jwtVerifier || !looksLikeJwt(token)) {
      return { roles: [], via: null };
    }

    const cached = cacheGet(token);
    if (cached) return { ...cached, via: 'supabase-jwt (cached)' };

    let identity;
    try {
      identity = await jwtVerifier(token);
    } catch {
      // A Supabase outage must not silently promote or demote anyone; it
      // simply means this credential could not be established.
      return { roles: [], via: null };
    }
    if (!identity || !identity.role) return { roles: [], via: null };

    const grants = ROLE_GRANTS[identity.role];
    if (!grants) return { roles: [], via: null };

    const resolved = { roles: grants, userId: identity.userId, email: identity.email };
    cachePut(token, resolved);
    return { ...resolved, via: 'supabase-jwt' };
  }

  /** Roles only — the shape server.js's guards consume. */
  async function rolesFor(req) {
    return (await resolve(req)).roles;
  }

  const instance = async function (req) {
    return resolve(req);
  };
  instance.resolve = resolve;
  instance.rolesFor = rolesFor;
  instance.rolesForPasskey = rolesForPasskey;
  instance.rolesFromKeys = rolesFromKeys;
  instance._cacheSize = () => verified.size;
  return instance;
}

/**
 * Turns a Supabase client into the verifier createResolver expects.
 *
 * getUser(token) is a real verification: Supabase checks the signature and
 * expiry server-side. Decoding the JWT locally and trusting its claims would
 * accept anything a caller cared to forge.
 */
export function supabaseJwtVerifier(supabase) {
  if (!supabase?.auth?.getUser) return null;
  return async function verify(token) {
    const { data, error } = await supabase.auth.getUser(token);
    if (error || !data?.user) return null;
    // app_metadata ONLY. See the header note on user_metadata.
    const role = data.user.app_metadata?.vbl_role;
    if (role !== 'chambers' && role !== 'automation') return null;
    return { role, userId: data.user.id, email: data.user.email };
  };
}

/**
 * Verifies any authenticated Supabase user (including clients without staff roles).
 */
export function supabaseClientVerifier(supabase) {
  if (!supabase?.auth?.getUser) return null;
  return async function verifyClient(token) {
    if (!token || !looksLikeJwt(token)) return null;
    const { data, error } = await supabase.auth.getUser(token);
    if (error || !data?.user) return null;
    return {
      userId: data.user.id,
      email: data.user.email,
      role: data.user.app_metadata?.vbl_role || 'client',
      userMetadata: data.user.user_metadata || {}
    };
  };
}

