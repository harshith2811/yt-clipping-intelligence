/**
 * Tests for the publishing taxonomy and state machine.
 *
 *   node automation/web/publishing/publishing.test.mjs
 *
 * The double-post tests are the important ones: they encode the failure mode
 * that a sleeping Render container would otherwise cause on a client-facing
 * feed.
 */

import assert from 'node:assert/strict';
import {
  classifyFailure, nextAction, backoffMs, MAX_RETRIES,
  AUTH_EXPIRED, TRANSIENT_NETWORK, FATAL_PAYLOAD
} from './classify.js';
import { advance, advancePost, emptyPlatformState, readPlatformStates, rollupStatus, isDue } from './state.js';

let pass = 0, fail = 0;
const t = (name, fn) => {
  try { fn(); pass++; console.log(`  ok   ${name}`); }
  catch (e) { fail++; console.log(`  FAIL ${name}\n       ${e.message}`); }
};
const ta = async (name, fn) => {
  try { await fn(); pass++; console.log(`  ok   ${name}`); }
  catch (e) { fail++; console.log(`  FAIL ${name}\n       ${e.message}`); }
};

console.log('\nclassifyFailure');

t('Meta expired token -> AUTH_EXPIRED, not retried', () => {
  const v = classifyFailure({ status: 400, body: { error: { code: 190, error_subcode: 463 } } });
  assert.equal(v.kind, AUTH_EXPIRED);
  assert.equal(v.retryable, false);
  assert.equal(v.channelStatus, 'Needs Reconnect');
});

t('Meta media aspect-ratio error -> FATAL_PAYLOAD', () => {
  const v = classifyFailure({ status: 400, body: { error: { code: 100, error_subcode: 2207009 } } });
  assert.equal(v.kind, FATAL_PAYLOAD);
  assert.equal(v.channelStatus, 'Failed - Revision Needed');
});

t('Meta throttle -> TRANSIENT_NETWORK', () => {
  assert.equal(classifyFailure({ status: 400, body: { error: { code: 4 } } }).kind, TRANSIENT_NETWORK);
});

t('Meta missing permission -> AUTH_EXPIRED (never loops)', () => {
  assert.equal(classifyFailure({ status: 403, body: { error: { code: 200 } } }).kind, AUTH_EXPIRED);
});

t('YouTube quotaExceeded -> TRANSIENT (quota resets)', () => {
  const v = classifyFailure({ status: 403, body: { error: { errors: [{ reason: 'quotaExceeded' }] } } });
  assert.equal(v.kind, TRANSIENT_NETWORK);
});

t('Google invalid_grant -> AUTH_EXPIRED', () => {
  const v = classifyFailure({ status: 400, body: { error: { errors: [{ reason: 'invalid_grant' }] } } });
  assert.equal(v.kind, AUTH_EXPIRED);
});

t('OAuth invalid_grant at token endpoint -> AUTH_EXPIRED', () => {
  assert.equal(classifyFailure({ status: 400, body: { error: 'invalid_grant' } }).kind, AUTH_EXPIRED);
});

t('socket reset -> TRANSIENT_NETWORK', () => {
  assert.equal(classifyFailure({ code: 'ECONNRESET' }).kind, TRANSIENT_NETWORK);
});

t('HTTP 500 -> TRANSIENT_NETWORK', () => {
  assert.equal(classifyFailure({ status: 503 }).kind, TRANSIENT_NETWORK);
});

t('bare 403 -> AUTH_EXPIRED (does not loop on revoked permission)', () => {
  assert.equal(classifyFailure({ status: 403, body: {} }).kind, AUTH_EXPIRED);
});

t('403 mentioning quota -> TRANSIENT_NETWORK', () => {
  assert.equal(classifyFailure({ status: 403, body: { message: 'User rate limit exceeded' } }).kind, TRANSIENT_NETWORK);
});

t('400 caption too long -> FATAL_PAYLOAD', () => {
  assert.equal(classifyFailure({ status: 400, body: { message: 'caption exceeds maximum length' } }).kind, FATAL_PAYLOAD);
});

console.log('\nnextAction / backoff');

t('auth failure halts immediately', () => {
  const a = nextAction({ status: 401 }, 0);
  assert.equal(a.action, 'halt');
  assert.equal(a.channelStatus, 'Needs Reconnect');
});

t('transient failure retries', () => {
  const a = nextAction({ status: 500 }, 0);
  assert.equal(a.action, 'retry');
  assert.equal(a.retryCount, 1);
  assert.ok(a.retryInMs > 0);
});

t('transient failure gives up at MAX_RETRIES', () => {
  const a = nextAction({ status: 500 }, MAX_RETRIES);
  assert.equal(a.action, 'halt');
  assert.equal(a.channelStatus, 'Failed - Revision Needed');
});

t('backoff grows and stays capped', () => {
  assert.ok(backoffMs(0) <= backoffMs(4));
  assert.ok(backoffMs(50) <= 6 * 60 * 60 * 1000);
});

console.log('\nstate machine');

await ta('queued -> pending -> ready -> completed', async () => {
  let s = emptyPlatformState('instagram');
  let phase = 'IN_PROGRESS';
  const driver = {
    createContainer: async () => ({ containerId: 'C1' }),
    checkContainer: async () => phase,
    publishContainer: async () => ({ postId: 'P1', releaseUrl: 'https://instagram.com/p/P1' })
  };

  s = await advance(s, driver);
  assert.equal(s.state, 'pending');
  assert.equal(s.containerId, 'C1');

  s = await advance(s, driver);
  assert.equal(s.state, 'pending', 'stays pending while transcoding');

  phase = 'FINISHED';
  s = await advance(s, driver);
  assert.equal(s.state, 'ready');

  s = await advance(s, driver);
  assert.equal(s.state, 'completed');
  assert.equal(s.postId, 'P1');
});

await ta('CRASH AFTER PUBLISH: does not post twice', async () => {
  // Simulates the Render failure: the container was published, but the process
  // died before persisting 'completed', so state on disk still says 'ready'.
  let publishCalls = 0;
  const driver = {
    createContainer: async () => ({ containerId: 'C9' }),
    checkContainer: async () => 'PUBLISHED',
    publishContainer: async () => { publishCalls++; return { postId: 'DUPLICATE' }; },
    describePublished: async () => ({ postId: 'ORIGINAL', releaseUrl: 'https://instagram.com/p/ORIGINAL' })
  };

  const stale = { ...emptyPlatformState('instagram'), state: 'ready', containerId: 'C9' };
  const s = await advance(stale, driver);

  assert.equal(publishCalls, 0, 'must NOT publish again');
  assert.equal(s.state, 'completed');
  assert.equal(s.postId, 'ORIGINAL');
});

await ta('crash while pending resolves to completed, not republished', async () => {
  let publishCalls = 0;
  const driver = {
    createContainer: async () => ({ containerId: 'C8' }),
    checkContainer: async () => 'PUBLISHED',
    publishContainer: async () => { publishCalls++; return { postId: 'DUPLICATE' }; }
  };
  const s = await advance({ ...emptyPlatformState('facebook'), state: 'pending', containerId: 'C8' }, driver);
  assert.equal(publishCalls, 0);
  assert.equal(s.state, 'completed');
});

await ta('single-step platform completes immediately', async () => {
  const driver = { createContainer: async () => ({ postId: 'L1', releaseUrl: 'https://linkedin.com/L1' }) };
  const s = await advance(emptyPlatformState('linkedin'), driver);
  assert.equal(s.state, 'completed');
  assert.equal(s.postId, 'L1');
});

await ta('auth failure marks failed, never retries', async () => {
  const err = Object.assign(new Error('bad token'), { status: 401 });
  const driver = { createContainer: async () => { throw err; } };
  const s = await advance(emptyPlatformState('threads'), driver);
  assert.equal(s.state, 'failed');
  assert.equal(s.failureKind, AUTH_EXPIRED);
  assert.equal(s.channelStatus, 'Needs Reconnect');
});

await ta('transient failure schedules a retry instead of failing', async () => {
  const err = Object.assign(new Error('boom'), { status: 503 });
  const driver = { createContainer: async () => { throw err; } };
  const s = await advance(emptyPlatformState('instagram'), driver);
  assert.equal(s.state, 'queued');
  assert.equal(s.retryCount, 1);
  assert.ok(s.retryAfter, 'retryAfter set');
  assert.equal(isDue(s, Date.now()), false, 'not due until backoff elapses');
  assert.equal(isDue(s, Date.parse(s.retryAfter) + 1), true);
});

await ta('container ERROR is terminal payload failure', async () => {
  const driver = {
    createContainer: async () => ({ containerId: 'CE' }),
    checkContainer: async () => 'ERROR'
  };
  const s = await advance({ ...emptyPlatformState('instagram'), state: 'pending', containerId: 'CE' }, driver);
  assert.equal(s.state, 'failed');
  assert.equal(s.failureKind, FATAL_PAYLOAD);
});

await ta('completed platform is never touched again', async () => {
  let calls = 0;
  const driver = { createContainer: async () => { calls++; return { postId: 'X' }; } };
  const states = { instagram: { ...emptyPlatformState('instagram'), state: 'completed', postId: 'P' } };
  await advancePost(states, { instagram: driver });
  assert.equal(calls, 0);
});

console.log('\nrollup');

t('readPlatformStates seeds from the Platforms column', () => {
  const s = readPlatformStates({ Platforms: 'instagram,facebook,youtube' });
  assert.deepEqual(Object.keys(s).sort(), ['facebook', 'instagram', 'youtube']);
  assert.equal(s.instagram.state, 'queued');
});

t('one dead channel surfaces as Needs Reconnect', () => {
  const s = {
    instagram: { state: 'completed' },
    threads: { state: 'failed', failureKind: AUTH_EXPIRED }
  };
  assert.equal(rollupStatus(s), 'Needs Reconnect');
});

t('all completed -> Posted', () => {
  assert.equal(rollupStatus({ a: { state: 'completed' }, b: { state: 'completed' } }), 'Posted');
});

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail === 0 ? 0 : 1);
