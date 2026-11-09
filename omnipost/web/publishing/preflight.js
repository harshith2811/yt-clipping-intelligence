/**
 * Start Engine pre-flight diagnostics.
 *
 * Answers one question: can this system publish right now?
 *
 * Design rules:
 *   - Every probe is LIGHTWEIGHT. No dataset is retrieved, no media downloaded.
 *     A pre-flight that costs real work is a pre-flight nobody runs.
 *   - Every probe is INDIVIDUALLY guarded. One dead channel must never take
 *     down the endpoint; an auth failure is a RESULT, not an exception.
 *   - No probe returns a credential. Only presence, validity and account
 *     labels cross this boundary.
 *   - Probes run in PARALLEL with a hard timeout. On a sleeping Render
 *     container six serial network calls would blow past any sensible request
 *     budget.
 */

import { CORE_PLATFORMS, channelInventory, isConfigured, missingKeys } from './registry.js';
import { linkedinProbe } from './linkedin.js';
import { pinterestProbe } from './pinterest.js';

const DEFAULT_TIMEOUT_MS = 12000;

/** Resolves to a NOT-VERIFIED result rather than rejecting. */
async function guarded(label, fn, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const started = Date.now();
  try {
    const result = await Promise.race([
      fn(),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error(`timed out after ${timeoutMs}ms`)), timeoutMs)
      )
    ]);
    return { ...result, ms: Date.now() - started };
  } catch (err) {
    return {
      ready: false,
      status: /timed out/.test(err.message) ? 'TIMEOUT' : 'ERROR',
      detail: err.message,
      ms: Date.now() - started
    };
  }
}

const GRAPH = () => `https://graph.facebook.com/${process.env.META_GRAPH_VERSION || 'v21.0'}`;
const THREADS_API = 'https://graph.threads.net/v1.0';

// ---------------------------------------------------------------------------
// Supabase
// ---------------------------------------------------------------------------
/**
 * Confirms both tables answer. Uses HEAD-style selects limited to one column
 * and one row: the point is reachability, not data.
 */
async function probeSupabase(db, env, fetchImpl) {
  const url = env.SUPABASE_URL;
  const key = env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) {
    return { ready: false, status: 'NEEDS_CONFIGURATION', detail: 'SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set' };
  }

  const tables = ['content_calendar'];
  const seen = {};
  for (const t of tables) {
    const res = await fetchImpl(`${url}/rest/v1/${t}?select=id&limit=1`, {
      headers: { apikey: key, Authorization: `Bearer ${key}` }
    });
    seen[t] = res.status;
    if (!res.ok) {
      return {
        ready: false,
        status: res.status === 404 ? 'CONFIGURATION_ERROR' : 'ERROR',
        detail: `${t} returned HTTP ${res.status}`,
        tables: seen
      };
    }
  }

  const backend = db?.getBackendStatus ? db.getBackendStatus().backend : 'unknown';
  return { ready: true, status: 'READY', backend, tables: seen };
}

// ---------------------------------------------------------------------------
// Google Drive vault
// ---------------------------------------------------------------------------
/**
 * The Drive credential lives in n8n, not here, so this cannot validate a
 * token. It reports what IS knowable server-side: the vault root is
 * configured, whether n8n (which performs the Drive calls) is reachable, and
 * HOW MANY client submissions are still waiting for their Drive folder.
 *
 * That backlog count matters more than it looks. A submission whose
 * provisioning failed keeps its documents only in the portal's uploads/
 * directory, and on a free Render instance that directory is EPHEMERAL — there
 * is no disk, so a sleep or a redeploy erases it. If the will-submission
 * workflow is not active in n8n (it ships inactive), every new submission lands
 * in that state silently: the client gets a reference number, the chambers get
 * a record, and the title deeds quietly cease to exist on the next restart.
 * Reporting the number is what turns that into something someone can notice.
 */
async function probeDrive(env, n8nReachable) {
  const root = env.GOOGLE_DRIVE_FOLDER_ID;
  if (!root) {
    return { ready: false, status: 'NEEDS_CONFIGURATION', detail: 'GOOGLE_DRIVE_FOLDER_ID not set' };
  }

  return {
    ready: Boolean(n8nReachable),
    status: !n8nReachable ? 'DEGRADED' : 'READY',
    detail: !n8nReachable
      ? 'Drive folder ID configured, but n8n bridge is unreachable — media uploads will queue'
      : 'Drive folder configured; n8n bridge reachable',
    vaultRootConfigured: true
  };
}

// ---------------------------------------------------------------------------
// Meta family
// ---------------------------------------------------------------------------
async function probeFacebook(env, fetchImpl) {
  if (!isConfigured('facebook', env)) {
    return { ready: false, status: 'NEEDS_CONFIGURATION', detail: `missing ${missingKeys('facebook', env).join(', ')}` };
  }
  const res = await fetchImpl(
    `${GRAPH()}/${env.FACEBOOK_PAGE_ID}?fields=id,name&access_token=${encodeURIComponent(env.FACEBOOK_PAGE_ACCESS_TOKEN)}`
  );
  const body = await res.json().catch(() => null);
  if (!res.ok || body?.error) {
    const code = body?.error?.code;
    return {
      ready: false,
      status: code === 190 ? 'AUTH_EXPIRED' : code === 10 || (code >= 200 && code <= 299) ? 'PERMISSION_DENIED' : 'ERROR',
      detail: body?.error?.message || `HTTP ${res.status}`
    };
  }
  return { ready: true, status: 'READY', account: body.name, accountId: body.id };
}

async function probeInstagram(env, fetchImpl) {
  if (!isConfigured('instagram', env)) {
    return { ready: false, status: 'NEEDS_CONFIGURATION', detail: `missing ${missingKeys('instagram', env).join(', ')}` };
  }
  const res = await fetchImpl(
    `${GRAPH()}/${env.INSTAGRAM_BUSINESS_ACCOUNT_ID}?fields=id,username&access_token=${encodeURIComponent(env.FACEBOOK_PAGE_ACCESS_TOKEN)}`
  );
  const body = await res.json().catch(() => null);
  if (!res.ok || body?.error) {
    const code = body?.error?.code;
    return {
      ready: false,
      status: code === 190 ? 'AUTH_EXPIRED' : 'ERROR',
      detail: body?.error?.message || `HTTP ${res.status}`
    };
  }
  return { ready: true, status: 'READY', account: `@${body.username}`, accountId: body.id };
}

async function probeThreads(env, fetchImpl) {
  if (!isConfigured('threads', env)) {
    return { ready: false, status: 'NEEDS_CONFIGURATION', detail: `missing ${missingKeys('threads', env).join(', ')}` };
  }
  const res = await fetchImpl(
    `${THREADS_API}/me?fields=id,username&access_token=${encodeURIComponent(env.THREADS_ACCESS_TOKEN)}`
  );
  const body = await res.json().catch(() => null);
  if (!res.ok || body?.error) {
    return {
      ready: false,
      status: res.status === 401 ? 'AUTH_EXPIRED' : 'ERROR',
      detail: body?.error?.message || `HTTP ${res.status}`
    };
  }
  return { ready: true, status: 'READY', account: `@${body.username}`, accountId: body.id };
}

// ---------------------------------------------------------------------------
// YouTube — via the n8n bridge
// ---------------------------------------------------------------------------
/**
 * The Google OAuth credential lives in n8n. This therefore reports whether the
 * BRIDGE is reachable, and says so explicitly rather than implying a token was
 * validated. Refresh tokens and client secrets never appear here.
 */
async function probeYouTube(env, n8nReachable) {
  if (env.YOUTUBE_BRIDGE_ENABLED === 'false') {
    return { ready: false, status: 'DISABLED', detail: 'YOUTUBE_BRIDGE_ENABLED=false' };
  }
  return {
    ready: Boolean(n8nReachable),
    status: n8nReachable ? 'READY' : 'DEGRADED',
    detail: n8nReachable
      ? 'n8n YouTube Publisher reachable (OAuth credential is held by n8n, not verified here)'
      : 'n8n unreachable — YouTube publishes will queue until the workflow is up',
    via: 'n8n YouTube Publisher'
  };
}

// ---------------------------------------------------------------------------
/**
 * Is n8n itself up, and separately, is the content bridge answering?
 *
 * These were one probe, and the one it used was `/webhook/content-list` — a
 * WORKFLOW webhook. That conflated three different failures into a single
 * "n8n unreachable":
 *
 *   * the container is genuinely down,
 *   * the container is fine but the Content Ingestion Webhook is not ACTIVE,
 *   * both are fine but its Google Sheets credential has expired.
 *
 * The last one is the situation the practice is actually in, and it was being
 * reported as the first. Worse, YouTube readiness was gated on it, even though
 * the YouTube Publisher is schedule-triggered and never touches that webhook —
 * so an unrelated expired credential made YouTube look dead and held the whole
 * engine below GREEN_SIGNAL.
 *
 * `/healthz` is n8n's own liveness endpoint. It answers without authentication
 * and without involving any workflow or credential, which is exactly what a
 * reachability probe should depend on.
 */
async function probeN8nHealth(sendToN8n) {
  if (typeof sendToN8n !== 'function') return false;
  try {
    await sendToN8n('/healthz', { method: 'GET', timeout: 4000 });
    return true;
  } catch {
    return false;
  }
}

/**
 * Does the Content Ingestion Webhook answer?
 *
 * Reported, but deliberately NOT used to gate readiness: it says something
 * about one workflow, not about the engine.
 */
async function probeN8nBridge(sendToN8n) {
  if (typeof sendToN8n !== 'function') return false;
  try {
    await sendToN8n('/webhook/content-list', { method: 'GET', timeout: 10000 });
    return true;
  } catch {
    return false;
  }
}

/** Endpoint list, for the operator's benefit. Never includes credentials. */
function n8nTargets(env) {
  return [...new Set([
    env.N8N_INTERNAL_URL || 'http://n8n-automation:5678',
    'http://localhost:5678',
    (env.N8N_PUBLIC_URL || env.N8N_EXTERNAL_URL || '').replace(/\/+$/, '')
  ].filter(Boolean))];
}

/**
 * Runs the full pre-flight.
 *
 * @param {object} deps { db, sendToN8n, env, fetchImpl, timeoutMs }
 */
export async function runPreflight({
  db,
  sendToN8n,
  env = process.env,
  fetchImpl = fetch,
  timeoutMs = DEFAULT_TIMEOUT_MS
} = {}) {
  const startedAt = Date.now();

  // n8n gates both Drive and YouTube, so it is resolved first.
  const n8nReachable = await guarded('n8n', async () => ({
    ready: await probeN8nHealth(sendToN8n), status: 'probe'
  }), timeoutMs).then(r => r.ready === true);

  // Reported alongside, never used to gate readiness.
  const bridgeAnswering = n8nReachable
    ? await guarded('n8n-bridge', async () => ({
        ready: await probeN8nBridge(sendToN8n), status: 'probe'
      }), timeoutMs).then(r => r.ready === true)
    : false;

  const [supabase, drive, facebook, instagram, threads, youtube, linkedin, pinterest] = await Promise.all([
    guarded('supabase', () => probeSupabase(db, env, fetchImpl), timeoutMs),
    guarded('drive', () => probeDrive(env, n8nReachable, db), timeoutMs),
    guarded('facebook', () => probeFacebook(env, fetchImpl), timeoutMs),
    guarded('instagram', () => probeInstagram(env, fetchImpl), timeoutMs),
    guarded('threads', () => probeThreads(env, fetchImpl), timeoutMs),
    guarded('youtube', () => probeYouTube(env, n8nReachable), timeoutMs),
    guarded('linkedin', () => linkedinProbe(env, fetchImpl), timeoutMs),
    guarded('pinterest', () => pinterestProbe(env, fetchImpl), timeoutMs)
  ]);

  const channels = { facebook, instagram, threads, youtube, linkedin, pinterest };
  const services = {
    supabase,
    drive,
    n8n: {
      ready: n8nReachable,
      status: n8nReachable ? (bridgeAnswering ? 'READY' : 'DEGRADED') : 'UNREACHABLE',
      reachable: n8nReachable,
      // Separated so an expired Google credential reads as an expired Google
      // credential, not as a dead container.
      contentBridge: bridgeAnswering ? 'ANSWERING' : 'NOT_ANSWERING',
      // Shows the operator exactly which hosts were attempted, in order, so a
      // misconfigured N8N_PUBLIC_URL is visible rather than guessed at.
      targets: n8nTargets(env),
      detail: !n8nReachable
        ? 'No n8n endpoint answered /healthz — Drive uploads and YouTube publishes will queue'
        : bridgeAnswering
          ? 'Workflow hub reachable; content bridge answering'
          : 'Workflow hub is UP, but /webhook/content-list did not answer. '
            + 'Activate the Content Ingestion Webhook and reconnect the Google Sheets credential.'
    }
  };

  // The engine arms on the core four AND Supabase: without persistence a
  // publish cannot be made idempotent, so arming would be unsafe.
  const coreReady = CORE_PLATFORMS.every((p) => channels[p]?.ready === true);
  const allCoreOperational = coreReady && supabase.ready === true;

  const blockers = [];
  CORE_PLATFORMS.forEach((p) => {
    if (!channels[p]?.ready) blockers.push({ dependency: p, status: channels[p]?.status, detail: channels[p]?.detail });
  });
  if (!supabase.ready) blockers.push({ dependency: 'supabase', status: supabase.status, detail: supabase.detail });

  const readyChannels = Object.entries(channels).filter(([, v]) => v.ready).map(([k]) => k);
  const selectiveArmed = readyChannels.length > 0;

  return {
    signal: allCoreOperational ? 'GREEN_SIGNAL' : 'NOT_GREEN',
    armed: allCoreOperational,
    selectiveArmed,
    readyCount: readyChannels.length,
    totalCount: Object.keys(channels).length,
    checkedAt: new Date().toISOString(),
    durationMs: Date.now() - startedAt,
    core: CORE_PLATFORMS,
    optional: ['linkedin', 'pinterest'],
    services,
    channels,
    readyToPublish: readyChannels,
    blockers,
    inventory: channelInventory(env)
  };
}

export { DEFAULT_TIMEOUT_MS };
