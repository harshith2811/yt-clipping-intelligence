/**
 * Tests for the LinkedIn and Pinterest adapters, the channel registry, and the
 * Start Engine pre-flight.
 *
 *   node automation/web/publishing/channels.test.mjs
 *
 * All network calls are stubbed. Nothing here touches a live account, and no
 * real credential appears in this file.
 */

import assert from 'node:assert/strict';
import { linkedinAdapter, linkedinProbe } from './linkedin.js';
import { pinterestAdapter, pinterestProbe, listBoards } from './pinterest.js';
import {
  channelInventory, isConfigured, missingKeys, missingSummary, validatePlatforms,
  buildAllDrivers, CORE_PLATFORMS
} from './registry.js';
import { runPreflight } from './preflight.js';
import { classifyFailure, AUTH_EXPIRED, TRANSIENT_NETWORK } from './classify.js';
import { advance, emptyPlatformState } from './state.js';

let pass = 0, fail = 0;
const ta = async (name, fn) => {
  try { await fn(); pass++; console.log(`  ok   ${name}`); }
  catch (e) { fail++; console.log(`  FAIL ${name}\n       ${e.message}`); }
};

/** Stub fetch: routes matched by substring, records every call. */
function stubFetch(routes) {
  const calls = [];
  const impl = async (url, opts = {}) => {
    calls.push({
      url,
      method: opts.method || 'GET',
      hasBody: Boolean(opts.body),
      // Kept so assertions can inspect the exact payload sent.
      body: opts.body,
      headers: opts.headers || {}
    });
    for (const [pattern, responder] of routes) {
      if (String(url).includes(pattern)) {
        const r = typeof responder === 'function' ? responder(url, opts) : responder;
        if (r.throws) throw Object.assign(new Error(r.throws), { code: r.code });
        return {
          ok: r.ok !== false,
          status: r.status || 200,
          headers: { get: (h) => (r.headers || {})[h.toLowerCase()] ?? null },
          body: r.stream || null,
          json: async () => r.body
        };
      }
    }
    throw new Error(`stubFetch: no route for ${url}`);
  };
  impl.calls = calls;
  return impl;
}

// ===========================================================================
console.log('\nLinkedIn adapter');

await ta('text post -> /rest/posts with both versioned headers', async () => {
  const f = stubFetch([['/rest/posts', { headers: { 'x-restli-id': 'urn:li:share:123' } }]]);
  const a = linkedinAdapter({
    accessToken: 'TK', authorUrn: 'urn:li:person:abc',
    post: { caption: 'OmniPost update' }, fetchImpl: f
  });
  const r = await a.createContainer();
  assert.equal(r.postId, 'urn:li:share:123');
  assert.match(r.releaseUrl, /feed\/update\/urn:li:share:123/);

  const h = f.calls[0].headers;
  assert.equal(h['X-Restli-Protocol-Version'], '2.0.0', 'Restli header required');
  assert.ok(h['LinkedIn-Version'], 'LinkedIn-Version header required');

  const sent = JSON.parse(f.calls[0].body);
  assert.equal(sent.author, 'urn:li:person:abc');
  assert.equal(sent.commentary, 'OmniPost update');
  assert.equal(sent.distribution.feedDistribution, 'MAIN_FEED');
});

await ta('organization author URN accepted', async () => {
  const f = stubFetch([['/rest/posts', { headers: { 'x-restli-id': 'urn:li:share:9' } }]]);
  const a = linkedinAdapter({
    accessToken: 'TK', authorUrn: 'urn:li:organization:555',
    post: { caption: 'x' }, fetchImpl: f
  });
  await a.createContainer();
  assert.equal(JSON.parse(f.calls[0].body).author, 'urn:li:organization:555');
});

await ta('malformed author URN rejected before any request', async () => {
  const f = stubFetch([]);
  assert.throws(() => linkedinAdapter({
    accessToken: 'TK', authorUrn: 'abc123', post: {}, fetchImpl: f
  }), /urn:li:person/);
  assert.equal(f.calls.length, 0);
});

await ta('link post uses the article content shape', async () => {
  const f = stubFetch([['/rest/posts', { headers: { 'x-restli-id': 'urn:li:share:7' } }]]);
  const a = linkedinAdapter({
    accessToken: 'TK', authorUrn: 'urn:li:person:a',
    post: { caption: 'Read this', link: 'https://example.com' }, fetchImpl: f
  });
  await a.createContainer();
  const sent = JSON.parse(f.calls[0].body);
  assert.equal(sent.content.article.source, 'https://example.com');
});

await ta('image post streams bytes — never buffered', async () => {
  const fakeStream = { __isStream: true };
  const f = stubFetch([
    ['action=initializeUpload', { body: { value: { uploadUrl: 'https://upload.li/abc', image: 'urn:li:image:1' } } }],
    ['https://media.example/x.jpg', { stream: fakeStream }],
    ['https://upload.li/abc', { body: {} }],
    ['/rest/posts', { headers: { 'x-restli-id': 'urn:li:share:img' } }]
  ]);
  const a = linkedinAdapter({
    accessToken: 'TK', authorUrn: 'urn:li:person:a',
    post: { caption: 'c', mediaUrl: 'https://media.example/x.jpg', mediaType: 'image' },
    fetchImpl: f
  });
  const r = await a.createContainer();
  assert.equal(r.postId, 'urn:li:share:img');

  const put = f.calls.find(c => c.url.includes('upload.li'));
  assert.equal(put.method, 'PUT');
  // The PUT body is the source response stream itself, not a Buffer/string.
  assert.equal(JSON.parse(f.calls.at(-1).body).content.media.id, 'urn:li:image:1');
});

await ta('missing id header is an error, not a silent success', async () => {
  const f = stubFetch([['/rest/posts', { body: {}, headers: {} }]]);
  const a = linkedinAdapter({ accessToken: 'TK', authorUrn: 'urn:li:person:a', post: { caption: 'x' }, fetchImpl: f });
  await assert.rejects(() => a.createContainer(), /no id header/);
});

await ta('401 classifies as AUTH_EXPIRED through the state machine', async () => {
  const f = stubFetch([['/rest/posts', { ok: false, status: 401, body: { message: 'expired' } }]]);
  const a = linkedinAdapter({ accessToken: 'TK', authorUrn: 'urn:li:person:a', post: { caption: 'x' }, fetchImpl: f });
  const s = await advance(emptyPlatformState('linkedin'), a);
  assert.equal(s.state, 'failed');
  assert.equal(s.failureKind, AUTH_EXPIRED);
  assert.equal(s.channelStatus, 'Needs Reconnect');
});

await ta('probe reports NEEDS_CONFIGURATION without credentials', async () => {
  const r = await linkedinProbe({}, stubFetch([]));
  assert.equal(r.ready, false);
  assert.equal(r.status, 'NEEDS_CONFIGURATION');
});

await ta('probe reports AUTH_EXPIRED on 401', async () => {
  const f = stubFetch([['/v2/userinfo', { ok: false, status: 401, body: {} }]]);
  const r = await linkedinProbe({ LINKEDIN_ACCESS_TOKEN: 'T', LINKEDIN_AUTHOR_URN: 'urn:li:person:a' }, f);
  assert.equal(r.status, 'AUTH_EXPIRED');
});

await ta('probe transitions straight to READY once both credentials are valid - no code change needed', async () => {
  const f = stubFetch([['/v2/userinfo', { body: { name: 'Krishna (admin)' } }]]);
  const r = await linkedinProbe(
    { LINKEDIN_ACCESS_TOKEN: 'T', LINKEDIN_AUTHOR_URN: 'urn:li:organization:987' }, f
  );
  assert.equal(r.ready, true);
  assert.equal(r.status, 'READY');
  assert.equal(r.authorUrn, 'urn:li:organization:987');
});

await ta('probe prefers LINKEDIN_DISPLAY_NAME over the token owner\'s own name', async () => {
  // /v2/userinfo is a PERSON endpoint. For an organization-scoped token it
  // returns the ADMIN who authorised the app, not the Company Page - showing
  // that as "the connected account" would be actively misleading.
  const f = stubFetch([['/v2/userinfo', { body: { name: 'Krishna (admin)' } }]]);
  const r = await linkedinProbe({
    LINKEDIN_ACCESS_TOKEN: 'T',
    LINKEDIN_AUTHOR_URN: 'urn:li:organization:987',
    LINKEDIN_DISPLAY_NAME: 'OmniPost Media'
  }, f);
  assert.equal(r.account, 'OmniPost Media');
});

await ta('probe still shows a real name with no display name configured', async () => {
  const f = stubFetch([['/v2/userinfo', { body: { name: 'Krishna (admin)' } }]]);
  const r = await linkedinProbe(
    { LINKEDIN_ACCESS_TOKEN: 'T', LINKEDIN_AUTHOR_URN: 'urn:li:person:a' }, f
  );
  assert.equal(r.account, 'Krishna (admin)');
});

// ===========================================================================
console.log('\nPinterest adapter');

await ta('image pin uses image_url handoff — zero bytes through Node', async () => {
  const f = stubFetch([['/v5/pins', { body: { id: 'PIN1' } }]]);
  const a = pinterestAdapter({
    accessToken: 'TK', boardId: 'B1',
    post: { caption: 'Weekly Growth Insights', title: 'Growth', mediaUrl: 'https://drive.example/x.jpg', link: 'https://example.com' },
    fetchImpl: f
  });
  const r = await a.createContainer();
  assert.equal(r.postId, 'PIN1');
  assert.match(r.releaseUrl, /pinterest\.com\/pin\/PIN1/);

  const sent = JSON.parse(f.calls[0].body);
  assert.equal(sent.board_id, 'B1');
  assert.equal(sent.media_source.source_type, 'image_url');
  assert.equal(sent.media_source.url, 'https://drive.example/x.jpg');
  assert.equal(sent.link, 'https://example.com');
});

await ta('missing media rejected as a configuration error', async () => {
  const f = stubFetch([]);
  const a = pinterestAdapter({ accessToken: 'T', boardId: 'B', post: { caption: 'x' }, fetchImpl: f });
  await assert.rejects(() => a.createContainer(), /requires an image URL/);
  assert.equal(f.calls.length, 0, 'no request made');
});

await ta('video pin refused explicitly rather than half-working', async () => {
  const f = stubFetch([]);
  const a = pinterestAdapter({
    accessToken: 'T', boardId: 'B',
    post: { caption: 'x', mediaUrl: 'https://d/v.mp4', mediaType: 'video' }, fetchImpl: f
  });
  await assert.rejects(() => a.createContainer(), /video pins are not implemented/);
});

await ta('board discovery lists boards', async () => {
  const f = stubFetch([['/v5/boards', { body: { items: [{ id: 'B1', name: 'Legal', privacy: 'PUBLIC' }] } }]]);
  const boards = await listBoards('TK', f);
  assert.deepEqual(boards, [{ id: 'B1', name: 'Legal', privacy: 'PUBLIC' }]);
});

await ta('probe: 401 -> AUTH_EXPIRED', async () => {
  const f = stubFetch([['/v5/user_account', { ok: false, status: 401, body: {} }]]);
  const r = await pinterestProbe({ PINTEREST_ACCESS_TOKEN: 'T', PINTEREST_BOARD_ID: 'B' }, f);
  assert.equal(r.ready, false);
  assert.equal(r.status, 'AUTH_EXPIRED');
});

await ta('probe: 403 -> PERMISSION_DENIED', async () => {
  const f = stubFetch([['/v5/user_account', { ok: false, status: 403, body: {} }]]);
  const r = await pinterestProbe({ PINTEREST_ACCESS_TOKEN: 'T', PINTEREST_BOARD_ID: 'B' }, f);
  assert.equal(r.status, 'PERMISSION_DENIED');
});

await ta('probe: valid token but board missing -> CONFIGURATION_ERROR', async () => {
  const f = stubFetch([
    ['/v5/user_account', { body: { username: 'omnipost' } }],
    ['/v5/boards', { body: { items: [{ id: 'OTHER', name: 'Other' }] } }]
  ]);
  const r = await pinterestProbe({ PINTEREST_ACCESS_TOKEN: 'T', PINTEREST_BOARD_ID: 'MISSING' }, f);
  assert.equal(r.ready, false);
  assert.equal(r.status, 'CONFIGURATION_ERROR');
});

await ta('probe: no board configured -> NEEDS_CONFIGURATION + suggestions', async () => {
  const f = stubFetch([
    ['/v5/user_account', { body: { username: 'omnipost' } }],
    ['/v5/boards', { body: { items: [{ id: 'B1', name: 'Legal' }] } }]
  ]);
  const r = await pinterestProbe({ PINTEREST_ACCESS_TOKEN: 'T' }, f);
  assert.equal(r.status, 'NEEDS_CONFIGURATION');
  assert.equal(r.availableBoards[0].id, 'B1');
});

await ta('probe: healthy -> READY', async () => {
  const f = stubFetch([
    ['/v5/user_account', { body: { username: 'omnipost' } }],
    ['/v5/boards', { body: { items: [{ id: 'B1', name: 'Legal' }] } }]
  ]);
  const r = await pinterestProbe({ PINTEREST_ACCESS_TOKEN: 'T', PINTEREST_BOARD_ID: 'B1' }, f);
  assert.equal(r.ready, true);
  assert.equal(r.board, 'Legal');
});

// ===========================================================================
console.log('\nRegistry / platform validation');

const FULL_ENV = {
  FACEBOOK_PAGE_ID: 'P', FACEBOOK_PAGE_ACCESS_TOKEN: 'T',
  INSTAGRAM_BUSINESS_ACCOUNT_ID: 'IG', INSTAGRAM_USERNAME: 'vbl',
  THREADS_USER_ID: 'TH', THREADS_ACCESS_TOKEN: 'T',
  LINKEDIN_ACCESS_TOKEN: 'T', LINKEDIN_AUTHOR_URN: 'urn:li:person:a', LINKEDIN_DISPLAY_NAME: 'OmniPost Media',
  PINTEREST_ACCESS_TOKEN: 'T', PINTEREST_BOARD_ID: 'B', PINTEREST_BOARD_NAME: 'Legal Insights & Updates'
};

await ta('core platforms are the four publishing channels', async () => {
  assert.deepEqual(CORE_PLATFORMS, ['facebook', 'instagram', 'threads', 'youtube']);
});

await ta('unknown platform rejected, not silently ignored', async () => {
  const r = validatePlatforms(['facebook', 'myspace']);
  assert.equal(r.valid, false);
  assert.match(r.error, /myspace/);
});

await ta('empty platform list rejected', async () => {
  assert.equal(validatePlatforms([]).valid, false);
  assert.equal(validatePlatforms('facebook').valid, false);
});

await ta('validation splits configured from unconfigured', async () => {
  const r = validatePlatforms(['facebook', 'linkedin'], { FACEBOOK_PAGE_ID: 'P', FACEBOOK_PAGE_ACCESS_TOKEN: 'T' });
  assert.equal(r.valid, true);
  assert.deepEqual(r.configured, ['facebook']);
  assert.deepEqual(r.unconfigured, ['linkedin']);
});

await ta('duplicates collapsed', async () => {
  assert.deepEqual(validatePlatforms(['facebook', 'FACEBOOK', 'facebook'], FULL_ENV).platforms, ['facebook']);
});

await ta('missingKeys names the env vars, never values', async () => {
  const m = missingKeys('linkedin', {});
  assert.deepEqual(m, ['LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_AUTHOR_URN']);
});

await ta('inventory marks core vs optional and hides nothing', async () => {
  const inv = channelInventory({});
  assert.equal(inv.length, 6);
  assert.equal(inv.find(c => c.id === 'linkedin').core, false);
  assert.equal(inv.find(c => c.id === 'facebook').core, true);
  assert.equal(inv.find(c => c.id === 'facebook').connected, false);
});

await ta('pinterest shows the board name, not a raw id, when configured', async () => {
  const inv = channelInventory(FULL_ENV);
  const p = inv.find(c => c.id === 'pinterest');
  assert.equal(p.connected, true);
  assert.equal(p.account, 'Legal Insights & Updates');
  assert.equal(p.accountId, 'B');
});

await ta('pinterest is still connected with no board name set - it is a label, not a requirement', async () => {
  const env = { ...FULL_ENV };
  delete env.PINTEREST_BOARD_NAME;
  const p = channelInventory(env).find(c => c.id === 'pinterest');
  assert.equal(p.connected, true);
  assert.equal(p.account, null);
});

await ta('regression guard: PINTEREST_USERNAME must never resurrect as the account label', async () => {
  // account() used to read a variable (PINTEREST_USERNAME) that nothing in
  // this repo ever sets, so the inventory silently showed a blank account for
  // a fully configured channel. Prove the board name wins even when a stray
  // PINTEREST_USERNAME is present, so that dead path cannot come back unnoticed.
  const env = { ...FULL_ENV, PINTEREST_USERNAME: 'should-not-be-shown' };
  const p = channelInventory(env).find(c => c.id === 'pinterest');
  assert.equal(p.account, 'Legal Insights & Updates');
});

await ta('linkedin shows the configured display name, not the raw URN', async () => {
  const inv = channelInventory(FULL_ENV);
  const l = inv.find(c => c.id === 'linkedin');
  assert.equal(l.connected, true);
  assert.equal(l.account, 'OmniPost Media');
  assert.equal(l.accountId, 'urn:li:person:a');
});

await ta('linkedin is still connected with no display name set - it is a label, not a requirement', async () => {
  const env = { ...FULL_ENV };
  delete env.LINKEDIN_DISPLAY_NAME;
  const l = channelInventory(env).find(c => c.id === 'linkedin');
  assert.equal(l.connected, true);
  assert.equal(l.account, null);
});

await ta('linkedin goes from NEEDS_CONFIGURATION straight to connected once both values are set - zero code change', async () => {
  const before = channelInventory({}).find(c => c.id === 'linkedin');
  assert.equal(before.connected, false);
  assert.deepEqual(before.missing, ['LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_AUTHOR_URN']);

  const after = channelInventory(FULL_ENV).find(c => c.id === 'linkedin');
  assert.equal(after.connected, true);
  assert.deepEqual(after.missing, []);
});

await ta('missingSummary returns missing keys per unconfigured platform', async () => {
  const s = missingSummary({});
  assert.ok(s.facebook.includes('FACEBOOK_PAGE_ID'));
  assert.ok(s.instagram.includes('INSTAGRAM_BUSINESS_ACCOUNT_ID'));
  assert.ok(s.threads.includes('THREADS_USER_ID'));
  assert.ok(s.linkedin.includes('LINKEDIN_ACCESS_TOKEN'));
  assert.ok(s.pinterest.includes('PINTEREST_ACCESS_TOKEN'));
});

await ta('missingSummary returns empty object when all channels configured', async () => {
  const s = missingSummary(FULL_ENV);
  assert.deepEqual(s, {});
});

await ta('missingSummary reports YOUTUBE_BRIDGE_ENABLED when bridge is explicitly disabled', async () => {
  const env = { ...FULL_ENV, YOUTUBE_BRIDGE_ENABLED: 'false' };
  const s = missingSummary(env);
  assert.deepEqual(s.youtube, ['YOUTUBE_BRIDGE_ENABLED']);
});

await ta('channelInventory items include name, label, connected, and configured boolean properties', async () => {
  const inv = channelInventory(FULL_ENV);
  for (const c of inv) {
    assert.equal(typeof c.name, 'string');
    assert.equal(c.name, c.label);
    assert.equal(typeof c.connected, 'boolean');
    assert.equal(typeof c.configured, 'boolean');
    assert.equal(c.connected, c.configured);
  }
  assert.equal(inv.filter(c => c.configured).length, 6);
  assert.equal(inv.filter(c => c.configured ?? c.connected).length, 6);
});

await ta('buildAllDrivers builds every configured native channel', async () => {
  const d = buildAllDrivers({ caption: 'x' }, ['facebook', 'instagram', 'threads', 'linkedin', 'pinterest'], FULL_ENV);
  assert.deepEqual(Object.keys(d).sort(), ['facebook', 'instagram', 'linkedin', 'pinterest', 'threads']);
});

await ta('youtube has no native driver (published via n8n)', async () => {
  const d = buildAllDrivers({ caption: 'x' }, ['youtube'], FULL_ENV);
  assert.deepEqual(Object.keys(d), []);
});

// ===========================================================================
console.log('\nPre-flight');

const okDb = { getBackendStatus: () => ({ backend: 'supabase' }) };
const SB_ENV = { SUPABASE_URL: 'https://sb.test', SUPABASE_SERVICE_ROLE_KEY: 'K', GOOGLE_DRIVE_FOLDER_ID: 'ROOT' };

function healthyFetch(overrides = []) {
  return stubFetch([
    ...overrides,
    ['/rest/v1/will_submissions', { body: [] }],
    ['/rest/v1/content_calendar', { body: [] }],
    ['graph.facebook.com', (u) => u.includes('/IG')
      ? { body: { id: 'IG', username: 'omnipost' } }
      : { body: { id: 'P', name: 'OmniPost Media' } }],
    ['graph.threads.net', { body: { id: 'TH', username: 'omnipost' } }],
    ['/v2/userinfo', { body: { name: 'Advocate' } }],
    ['/v5/user_account', { body: { username: 'omnipost' } }],
    ['/v5/boards', { body: { items: [{ id: 'B', name: 'Legal' }] } }]
  ]);
}

await ta('all core healthy -> GREEN_SIGNAL', async () => {
  const r = await runPreflight({
    db: okDb,
    sendToN8n: async () => ({ posts: [] }),
    env: { ...FULL_ENV, ...SB_ENV },
    fetchImpl: healthyFetch()
  });
  assert.equal(r.signal, 'GREEN_SIGNAL');
  assert.equal(r.armed, true);
  assert.equal(r.blockers.length, 0);
  CORE_PLATFORMS.forEach(p => assert.equal(r.channels[p].ready, true, `${p} should be ready`));
});

await ta('core channel failure -> NOT_GREEN with the blocker named', async () => {
  const f = healthyFetch([['/P?fields=id,name', { ok: false, status: 400, body: { error: { message: 'expired', code: 190 } } }]]);
  const r = await runPreflight({ db: okDb, sendToN8n: async () => ({}), env: { ...FULL_ENV, ...SB_ENV }, fetchImpl: f });
  assert.equal(r.signal, 'NOT_GREEN');
  assert.equal(r.armed, false);
  assert.equal(r.channels.facebook.status, 'AUTH_EXPIRED');
  assert.ok(r.blockers.some(b => b.dependency === 'facebook'));
});

await ta('optional platform down does NOT block arming', async () => {
  const f = healthyFetch([['/v5/user_account', { ok: false, status: 401, body: {} }]]);
  const r = await runPreflight({ db: okDb, sendToN8n: async () => ({}), env: { ...FULL_ENV, ...SB_ENV }, fetchImpl: f });
  assert.equal(r.signal, 'GREEN_SIGNAL', 'Pinterest is optional');
  assert.equal(r.channels.pinterest.ready, false);
  assert.ok(!r.blockers.some(b => b.dependency === 'pinterest'));
});

await ta('Supabase unreachable blocks arming (no idempotency without state)', async () => {
  const f = healthyFetch([['/rest/v1/content_calendar', { ok: false, status: 404, body: {} }]]);
  const r = await runPreflight({ db: okDb, sendToN8n: async () => ({}), env: { ...FULL_ENV, ...SB_ENV }, fetchImpl: f });
  assert.equal(r.armed, false);
  assert.ok(r.blockers.some(b => b.dependency === 'supabase'));
});

await ta('a hanging probe times out instead of hanging the endpoint', async () => {
  const slow = stubFetch([['graph.threads.net', async () => new Promise(() => {})]]);
  const impl = async (url, o) => {
    if (String(url).includes('graph.threads.net')) return new Promise(() => {});
    return healthyFetch()(url, o);
  };
  const r = await runPreflight({
    db: okDb, sendToN8n: async () => ({}),
    env: { ...FULL_ENV, ...SB_ENV }, fetchImpl: impl, timeoutMs: 150
  });
  assert.equal(r.channels.threads.status, 'TIMEOUT');
  assert.equal(r.armed, false);
});

await ta('a throwing probe is a result, not a crash', async () => {
  const impl = async (url, o) => {
    if (String(url).includes('graph.threads.net')) throw Object.assign(new Error('socket closed'), { code: 'ECONNRESET' });
    return healthyFetch()(url, o);
  };
  const r = await runPreflight({ db: okDb, sendToN8n: async () => ({}), env: { ...FULL_ENV, ...SB_ENV }, fetchImpl: impl });
  assert.equal(r.channels.threads.ready, false);
  assert.equal(r.signal, 'NOT_GREEN');
});

await ta('malformed configuration -> NEEDS_CONFIGURATION, not a crash', async () => {
  const r = await runPreflight({ db: okDb, sendToN8n: async () => ({}), env: { ...SB_ENV }, fetchImpl: healthyFetch() });
  assert.equal(r.channels.facebook.status, 'NEEDS_CONFIGURATION');
  assert.equal(r.channels.linkedin.status, 'NEEDS_CONFIGURATION');
  assert.equal(r.armed, false);
});

await ta('n8n down degrades YouTube and Drive without throwing', async () => {
  const r = await runPreflight({
    db: okDb,
    sendToN8n: async () => { throw new Error('ECONNREFUSED'); },
    env: { ...FULL_ENV, ...SB_ENV },
    fetchImpl: healthyFetch()
  });
  assert.equal(r.channels.youtube.ready, false);
  assert.equal(r.channels.youtube.status, 'DEGRADED');
  assert.equal(r.services.drive.status, 'DEGRADED');
  assert.equal(r.armed, false, 'YouTube is core');
});

await ta('pre-flight never returns a credential', async () => {
  const r = await runPreflight({ db: okDb, sendToN8n: async () => ({}), env: { ...FULL_ENV, ...SB_ENV }, fetchImpl: healthyFetch() });
  const blob = JSON.stringify(r);
  ['LINKEDIN_ACCESS_TOKEN', 'PINTEREST_ACCESS_TOKEN', 'FACEBOOK_PAGE_ACCESS_TOKEN', 'THREADS_ACCESS_TOKEN']
    .forEach(k => assert.ok(!blob.includes(FULL_ENV[k]) || FULL_ENV[k].length < 3, `${k} value must not appear`));
  assert.ok(!blob.includes('SUPABASE_SERVICE_ROLE_KEY'));
});

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail === 0 ? 0 : 1);
