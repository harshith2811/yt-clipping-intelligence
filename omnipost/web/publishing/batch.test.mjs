/**
 * Batch publishing, idempotency and partial-success tests.
 *
 *   node automation/web/publishing/batch.test.mjs
 *
 * These exercise the same decision logic /api/publish/batch runs: skip
 * already-published platforms, skip unconfigured ones, advance the rest, and
 * never let one channel's failure undo another's success.
 *
 * The duplicate-prevention tests are the ones that matter. A duplicate post on
 * a client-facing feed cannot be taken back.
 */

import assert from 'node:assert/strict';
import { advance, advancePost, emptyPlatformState, rollupStatus, isSettled } from './state.js';
import { validatePlatforms, buildAllDrivers, missingKeys } from './registry.js';
import { AUTH_EXPIRED, TRANSIENT_NETWORK, FATAL_PAYLOAD } from './classify.js';

let pass = 0, fail = 0;
const ta = async (name, fn) => {
  try { await fn(); pass++; console.log(`  ok   ${name}`); }
  catch (e) { fail++; console.log(`  FAIL ${name}\n       ${e.message}`); }
};

/**
 * Mirrors the per-platform decision in /api/publish/batch so the rules are
 * testable without standing up Express.
 */
async function runBatch(platforms, existingStates, drivers, env = {}) {
  const states = {};
  const results = [];

  for (const platform of platforms) {
    const prior = existingStates[platform];

    if (prior?.state === 'completed') {
      states[platform] = prior;
      results.push({ platform, result: 'ALREADY_PUBLISHED', postId: prior.postId });
      continue;
    }
    if (!drivers[platform]) {
      states[platform] = {
        ...emptyPlatformState(platform),
        state: 'failed',
        failureKind: 'CONFIGURATION_ERROR',
        lastError: 'not configured'
      };
      results.push({ platform, result: 'SKIPPED', reason: 'NOT_CONFIGURED', missing: missingKeys(platform, env) });
      continue;
    }

    const next = await advance(prior || emptyPlatformState(platform), drivers[platform]);
    states[platform] = next;
    results.push({
      platform,
      result: next.state === 'completed' ? 'PUBLISHED' : next.state === 'failed' ? 'FAILED' : 'PROCESSING',
      postId: next.postId || null,
      errorCode: next.failureKind || null
    });
  }

  return { states: { ...existingStates, ...states }, results };
}

const okDriver = (postId) => {
  let calls = 0;
  return {
    createContainer: async () => { calls++; return { postId, releaseUrl: `https://x/${postId}` }; },
    checkContainer: async () => 'PUBLISHED',
    publishContainer: async () => ({ postId }),
    get calls() { return calls; }
  };
};

console.log('\nBatch — success paths');

await ta('all configured channels succeed', async () => {
  const drivers = { facebook: okDriver('FB1'), instagram: okDriver('IG1'), threads: okDriver('TH1') };
  const { states, results } = await runBatch(['facebook', 'instagram', 'threads'], {}, drivers);
  assert.equal(results.filter(r => r.result === 'PUBLISHED').length, 3);
  assert.equal(rollupStatus(states), 'Posted');
  assert.equal(isSettled(states), true);
});

await ta('partial success: one fails, others still publish', async () => {
  const drivers = {
    facebook: okDriver('FB1'),
    instagram: okDriver('IG1'),
    pinterest: { createContainer: async () => { throw Object.assign(new Error('bad token'), { status: 401 }); } }
  };
  const { states, results } = await runBatch(['facebook', 'instagram', 'pinterest'], {}, drivers);

  assert.equal(results.find(r => r.platform === 'facebook').result, 'PUBLISHED');
  assert.equal(results.find(r => r.platform === 'instagram').result, 'PUBLISHED');
  assert.equal(results.find(r => r.platform === 'pinterest').result, 'FAILED');
  assert.equal(results.find(r => r.platform === 'pinterest').errorCode, AUTH_EXPIRED);

  // The failure must not have rolled back the successes.
  assert.equal(states.facebook.state, 'completed');
  assert.equal(states.facebook.postId, 'FB1');
  assert.equal(states.instagram.state, 'completed');
});

await ta('unconfigured platform SKIPPED, never failed-as-error', async () => {
  const drivers = { facebook: okDriver('FB1') };
  const { results } = await runBatch(['facebook', 'linkedin'], {}, drivers, {});
  const li = results.find(r => r.platform === 'linkedin');
  assert.equal(li.result, 'SKIPPED');
  assert.equal(li.reason, 'NOT_CONFIGURED');
  assert.deepEqual(li.missing, ['LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_AUTHOR_URN']);
});

console.log('\nIdempotency — duplicate prevention');

await ta('already-published platform is skipped without any API call', async () => {
  const fb = okDriver('FB_NEW');
  const existing = {
    facebook: { ...emptyPlatformState('facebook'), state: 'completed', postId: 'FB_ORIGINAL', releaseUrl: 'https://x/FB_ORIGINAL' }
  };
  const { states, results } = await runBatch(['facebook'], existing, { facebook: fb });

  assert.equal(fb.calls, 0, 'must not call the platform again');
  assert.equal(results[0].result, 'ALREADY_PUBLISHED');
  assert.equal(results[0].postId, 'FB_ORIGINAL');
  assert.equal(states.facebook.postId, 'FB_ORIGINAL', 'original id preserved');
});

await ta('replaying the same batch produces no second post', async () => {
  const drivers = { facebook: okDriver('FB1'), threads: okDriver('TH1') };
  const first = await runBatch(['facebook', 'threads'], {}, drivers);
  assert.equal(drivers.facebook.calls, 1);

  const second = await runBatch(['facebook', 'threads'], first.states, drivers);
  assert.equal(drivers.facebook.calls, 1, 'no additional publish on replay');
  assert.equal(drivers.threads.calls, 1);
  assert.ok(second.results.every(r => r.result === 'ALREADY_PUBLISHED'));
});

await ta('container already PUBLISHED upstream is adopted, not republished', async () => {
  // Simulates a restart after the platform published but before we persisted it.
  let publishCalls = 0;
  const driver = {
    createContainer: async () => ({ containerId: 'C1' }),
    checkContainer: async () => 'PUBLISHED',
    publishContainer: async () => { publishCalls++; return { postId: 'DUPLICATE' }; },
    describePublished: async () => ({ postId: 'ORIGINAL', releaseUrl: 'https://x/ORIGINAL' })
  };
  const stale = { instagram: { ...emptyPlatformState('instagram'), state: 'ready', containerId: 'C1' } };
  const { states } = await runBatch(['instagram'], stale, { instagram: driver });

  assert.equal(publishCalls, 0);
  assert.equal(states.instagram.state, 'completed');
  assert.equal(states.instagram.postId, 'ORIGINAL');
});

await ta('cold start resumes a pending container instead of recreating it', async () => {
  let createCalls = 0;
  const driver = {
    createContainer: async () => { createCalls++; return { containerId: 'NEW' }; },
    checkContainer: async () => 'FINISHED',
    publishContainer: async () => ({ postId: 'IG1' })
  };
  // State as persisted in Supabase before the container was recycled.
  const persisted = { instagram: { ...emptyPlatformState('instagram'), state: 'pending', containerId: 'C_EXISTING' } };
  const { states } = await runBatch(['instagram'], persisted, { instagram: driver });

  assert.equal(createCalls, 0, 'must not create a second container');
  assert.equal(states.instagram.containerId, 'C_EXISTING');
  assert.equal(states.instagram.state, 'ready');
});

console.log('\nFailure classification');

await ta('retryable failure stays queued with a backoff, not failed', async () => {
  const driver = { createContainer: async () => { throw Object.assign(new Error('boom'), { status: 503 }); } };
  const { states, results } = await runBatch(['facebook'], {}, { facebook: driver });
  assert.equal(states.facebook.state, 'queued');
  assert.equal(states.facebook.failureKind, TRANSIENT_NETWORK);
  assert.ok(states.facebook.retryAfter);
  assert.equal(results[0].result, 'PROCESSING');
});

await ta('permanent payload failure is terminal', async () => {
  const driver = {
    createContainer: async () => {
      throw Object.assign(new Error('aspect'), {
        status: 400, body: { error: { code: 100, error_subcode: 2207009 } }
      });
    }
  };
  const { states } = await runBatch(['instagram'], {}, { instagram: driver });
  assert.equal(states.instagram.state, 'failed');
  assert.equal(states.instagram.failureKind, FATAL_PAYLOAD);
});

await ta('auth failure halts and flags the channel for reconnection', async () => {
  const driver = { createContainer: async () => { throw Object.assign(new Error('x'), { status: 401 }); } };
  const { states } = await runBatch(['threads'], {}, { threads: driver });
  assert.equal(states.threads.state, 'failed');
  assert.equal(states.threads.channelStatus, 'Needs Reconnect');
});

await ta('one dead channel surfaces in the rollup', async () => {
  const drivers = {
    facebook: okDriver('FB1'),
    threads: { createContainer: async () => { throw Object.assign(new Error('x'), { status: 401 }); } }
  };
  const { states } = await runBatch(['facebook', 'threads'], {}, drivers);
  assert.equal(rollupStatus(states), 'Needs Reconnect');
});

console.log('\nRequest validation');

await ta('batch rejects an unknown platform outright', async () => {
  assert.equal(validatePlatforms(['facebook', 'orkut']).valid, false);
});

await ta('advancePost never touches a settled platform', async () => {
  const d = okDriver('X');
  const states = { facebook: { ...emptyPlatformState('facebook'), state: 'completed', postId: 'P' } };
  await advancePost(states, { facebook: d });
  assert.equal(d.calls, 0);
});

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail === 0 ? 0 : 1);
