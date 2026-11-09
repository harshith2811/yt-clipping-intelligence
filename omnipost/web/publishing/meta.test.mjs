/**
 * Tests for the Meta adapters.
 *
 *   node automation/web/publishing/meta.test.mjs
 *
 * A stub fetch records every request, so these assert the exact URLs and the
 * zero-RAM contract (media passed as a URL, never as a body) without touching
 * the live Graph API.
 */

import assert from 'node:assert/strict';
import { facebookAdapter, instagramAdapter, threadsAdapter, buildDrivers, MetaApiError, redactUrlSecrets } from './meta.js';
import { classifyFailure, AUTH_EXPIRED, FATAL_PAYLOAD, TRANSIENT_NETWORK } from './classify.js';
import { advance, emptyPlatformState } from './state.js';

let pass = 0, fail = 0;
const ta = async (name, fn) => {
  try { await fn(); pass++; console.log(`  ok   ${name}`); }
  catch (e) { fail++; console.log(`  FAIL ${name}\n       ${e.message}`); }
};

/** Returns a fetch stub that answers from `routes` and records calls. */
function stubFetch(routes) {
  const calls = [];
  const impl = async (url, opts = {}) => {
    calls.push({ url, method: opts.method || 'GET', hasBody: Boolean(opts.body) });
    for (const [pattern, responder] of routes) {
      if (url.includes(pattern)) {
        const r = typeof responder === 'function' ? responder(url) : responder;
        return {
          ok: r.ok !== false,
          status: r.status || 200,
          json: async () => r.body
        };
      }
    }
    throw new Error(`stubFetch: no route for ${url}`);
  };
  impl.calls = calls;
  return impl;
}

console.log('\nFacebook adapter');

await ta('text post -> /feed, returns post id immediately', async () => {
  const f = stubFetch([['/feed', { body: { id: '123_456' } }]]);
  const a = facebookAdapter({ pageId: '123', pageAccessToken: 'TK', post: { caption: 'Hello chambers' }, fetchImpl: f });
  const r = await a.createContainer();
  assert.equal(r.postId, '123_456');
  assert.match(f.calls[0].url, /\/123\/feed\?message=Hello%20chambers/);
  assert.equal(f.calls[0].method, 'POST');
});

await ta('photo post -> /photos with url= (no bytes uploaded)', async () => {
  const f = stubFetch([['/photos', { body: { id: 'p1', post_id: '123_789' } }]]);
  const a = facebookAdapter({
    pageId: '123', pageAccessToken: 'TK',
    post: { caption: 'c', mediaUrl: 'https://drive.example/x.jpg', mediaType: 'image' },
    fetchImpl: f
  });
  const r = await a.createContainer();
  assert.equal(r.postId, '123_789', 'prefers post_id over the photo id');
  assert.match(f.calls[0].url, /url=https%3A%2F%2Fdrive\.example%2Fx\.jpg/);
  assert.equal(f.calls[0].hasBody, false, 'ZERO-RAM: media passed as URL, not body');
});

await ta('video post -> /videos with file_url', async () => {
  const f = stubFetch([['/videos', { body: { id: 'v1' } }]]);
  const a = facebookAdapter({
    pageId: '123', pageAccessToken: 'TK',
    post: { caption: 'c', mediaUrl: 'https://drive.example/v.mp4', mediaType: 'video' },
    fetchImpl: f
  });
  await a.createContainer();
  assert.match(f.calls[0].url, /file_url=https%3A%2F%2Fdrive\.example%2Fv\.mp4/);
  assert.equal(f.calls[0].hasBody, false, 'ZERO-RAM');
});

console.log('\nInstagram adapter');

await ta('image: container -> status -> publish', async () => {
  const f = stubFetch([
    ['/media_publish', { body: { id: 'IG_POST' } }],
    ['/media?', { body: { id: 'IG_CONTAINER' } }],
    ['fields=status_code', { body: { status_code: 'FINISHED' } }]
  ]);
  const a = instagramAdapter({
    igUserId: '999', accessToken: 'TK',
    post: { caption: 'hello', mediaUrl: 'https://drive.example/x.jpg', mediaType: 'image' },
    fetchImpl: f
  });

  const created = await a.createContainer();
  assert.equal(created.containerId, 'IG_CONTAINER');
  assert.match(f.calls[0].url, /image_url=https%3A%2F%2Fdrive\.example%2Fx\.jpg/);
  assert.equal(f.calls[0].hasBody, false, 'ZERO-RAM');

  assert.equal(await a.checkContainer('IG_CONTAINER'), 'FINISHED');

  const published = await a.publishContainer('IG_CONTAINER');
  assert.equal(published.postId, 'IG_POST');
  assert.match(f.calls[2].url, /creation_id=IG_CONTAINER/);
});

await ta('reel uses media_type=REELS', async () => {
  const f = stubFetch([['/media?', { body: { id: 'C' } }]]);
  const a = instagramAdapter({
    igUserId: '999', accessToken: 'TK',
    post: { caption: 'c', mediaUrl: 'https://d/v.mp4', mediaType: 'video', isReel: true },
    fetchImpl: f
  });
  await a.createContainer();
  assert.match(f.calls[0].url, /media_type=REELS/);
  assert.match(f.calls[0].url, /video_url=/);
});

await ta('text-only rejected as FATAL_PAYLOAD, not sent to Meta', async () => {
  const f = stubFetch([]);
  const a = instagramAdapter({ igUserId: '999', accessToken: 'TK', post: { caption: 'no media' }, fetchImpl: f });
  await assert.rejects(() => a.createContainer(), MetaApiError);
  assert.equal(f.calls.length, 0, 'no request made');
  try { await a.createContainer(); } catch (e) {
    assert.equal(classifyFailure({ status: e.status, body: e.body }).kind, FATAL_PAYLOAD);
  }
});

console.log('\nThreads adapter');

await ta('text post: threads -> threads_publish -> permalink', async () => {
  const f = stubFetch([
    ['/threads_publish', { body: { id: 'TH_POST' } }],
    ['fields=id,permalink', { body: { id: 'TH_POST', permalink: 'https://threads.net/p/abc' } }],
    ['/threads?', { body: { id: 'TH_CONTAINER' } }]
  ]);
  const a = threadsAdapter({ userId: '279', accessToken: 'TK', post: { caption: 'Legal system test' }, fetchImpl: f });

  const created = await a.createContainer();
  assert.equal(created.containerId, 'TH_CONTAINER');
  assert.match(f.calls[0].url, /graph\.threads\.net/, 'Threads has its own host, not graph.facebook.com');
  assert.match(f.calls[0].url, /media_type=TEXT/);

  const published = await a.publishContainer('TH_CONTAINER');
  assert.equal(published.postId, 'TH_POST');
  assert.equal(published.releaseUrl, 'https://threads.net/p/abc');
});

await ta('permalink lookup failure does not fail a live post', async () => {
  const f = stubFetch([
    ['/threads_publish', { body: { id: 'TH_POST' } }],
    ['fields=id,permalink', { ok: false, status: 500, body: { error: { message: 'boom' } } }]
  ]);
  const a = threadsAdapter({ userId: '279', accessToken: 'TK', post: { caption: 'x' }, fetchImpl: f });
  const r = await a.publishContainer('C');
  assert.equal(r.postId, 'TH_POST');
  assert.equal(r.releaseUrl, null);
});

console.log('\nerror propagation into the taxonomy');

await ta('expired token surfaces as AUTH_EXPIRED through the state machine', async () => {
  const f = stubFetch([
    ['/media?', { ok: false, status: 400, body: { error: { message: 'expired', code: 190, error_subcode: 463 } } }]
  ]);
  const a = instagramAdapter({
    igUserId: '9', accessToken: 'TK',
    post: { caption: 'c', mediaUrl: 'https://d/x.jpg' }, fetchImpl: f
  });
  const s = await advance(emptyPlatformState('instagram'), a);
  assert.equal(s.state, 'failed');
  assert.equal(s.failureKind, AUTH_EXPIRED);
  assert.equal(s.channelStatus, 'Needs Reconnect');
});

await ta('rate limit becomes a scheduled retry, not a failure', async () => {
  const f = stubFetch([
    ['/media?', { ok: false, status: 400, body: { error: { message: 'throttled', code: 4 } } }]
  ]);
  const a = instagramAdapter({
    igUserId: '9', accessToken: 'TK',
    post: { caption: 'c', mediaUrl: 'https://d/x.jpg' }, fetchImpl: f
  });
  const s = await advance(emptyPlatformState('instagram'), a);
  assert.equal(s.state, 'queued');
  assert.equal(s.failureKind, TRANSIENT_NETWORK);
  assert.ok(s.retryAfter);
});

await ta('IG crash-after-publish does not post twice', async () => {
  let publishCalls = 0;
  const f = stubFetch([
    ['fields=status_code', { body: { status_code: 'PUBLISHED' } }],
    ['fields=id,permalink', { body: { id: 'ORIGINAL', permalink: 'https://instagram.com/p/ORIGINAL' } }],
    ['/media_publish', () => { publishCalls++; return { body: { id: 'DUPLICATE' } }; }]
  ]);
  const a = instagramAdapter({ igUserId: '9', accessToken: 'TK', post: { caption: 'c', mediaUrl: 'https://d/x.jpg' }, fetchImpl: f });
  const stale = { ...emptyPlatformState('instagram'), state: 'ready', containerId: 'C1' };
  const s = await advance(stale, a);
  assert.equal(publishCalls, 0, 'must not publish again');
  assert.equal(s.state, 'completed');
  assert.equal(s.postId, 'ORIGINAL');
});

console.log('\nbuildDrivers');

await ta('omits platforms without credentials', async () => {
  const d = buildDrivers({ caption: 'x' }, { THREADS_USER_ID: '1', THREADS_ACCESS_TOKEN: 'T' });
  assert.deepEqual(Object.keys(d), ['threads']);
});

await ta('builds all three when fully configured', async () => {
  const d = buildDrivers({ caption: 'x' }, {
    FACEBOOK_PAGE_ID: 'P', FACEBOOK_PAGE_ACCESS_TOKEN: 'T',
    INSTAGRAM_BUSINESS_ACCOUNT_ID: 'IG',
    THREADS_USER_ID: '1', THREADS_ACCESS_TOKEN: 'T'
  });
  assert.deepEqual(Object.keys(d).sort(), ['facebook', 'instagram', 'threads']);
});

console.log('\ncredential redaction (DEF-12)');

await ta('redactUrlSecrets strips access_token from query string', async () => {
  const url = 'https://graph.facebook.com/v21.0/123/feed?access_token=SECRET_TOKEN_XYZ&message=test';
  const redacted = redactUrlSecrets(url);
  assert.equal(redacted, 'https://graph.facebook.com/v21.0/123/feed?access_token=[REDACTED]&message=test');
  assert.ok(!redacted.includes('SECRET_TOKEN_XYZ'));
});

await ta('redactUrlSecrets strips multiple secret keys', async () => {
  const url = 'https://graph.facebook.com/v21.0/oauth?client_secret=SEC1&appsecret_proof=PROOF2&token=TOK3';
  const redacted = redactUrlSecrets(url);
  assert.equal(redacted, 'https://graph.facebook.com/v21.0/oauth?client_secret=[REDACTED]&appsecret_proof=[REDACTED]&token=[REDACTED]');
});

await ta('MetaApiError constructor redacts secret in endpoint', async () => {
  const err = new MetaApiError('Failed', {
    status: 400,
    platform: 'facebook',
    endpoint: 'https://graph.facebook.com/v21.0/123/photos?access_token=SECRET_123'
  });
  assert.equal(err.endpoint, 'https://graph.facebook.com/v21.0/123/photos?access_token=[REDACTED]');
  assert.ok(!err.endpoint.includes('SECRET_123'));
});

await ta('network error in call() throws MetaApiError with redacted endpoint', async () => {
  const f = stubFetch([['/feed', () => { const err = new Error('connect ETIMEDOUT'); err.code = 'ETIMEDOUT'; throw err; }]]);
  const a = facebookAdapter({ pageId: '123', pageAccessToken: 'SECRET_PAGE_TOKEN', post: { caption: 'hi' }, fetchImpl: f });
  try {
    await a.createContainer();
    assert.fail('should throw');
  } catch (err) {
    assert.equal(err.name, 'MetaApiError');
    assert.ok(err.endpoint.includes('access_token=[REDACTED]'));
    assert.ok(!err.endpoint.includes('SECRET_PAGE_TOKEN'));
  }
});

await ta('HTTP error in call() throws MetaApiError with redacted endpoint', async () => {
  const f = stubFetch([['/feed', { ok: false, status: 400, body: { error: { message: 'Expired', code: 190 } } }]]);
  const a = facebookAdapter({ pageId: '123', pageAccessToken: 'SECRET_PAGE_TOKEN_2', post: { caption: 'hi' }, fetchImpl: f });
  try {
    await a.createContainer();
    assert.fail('should throw');
  } catch (err) {
    assert.equal(err.name, 'MetaApiError');
    assert.ok(err.endpoint.includes('access_token=[REDACTED]'));
    assert.ok(!err.endpoint.includes('SECRET_PAGE_TOKEN_2'));
  }
});

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail === 0 ? 0 : 1);
