import test from 'node:test';
import assert from 'node:assert/strict';
import { app } from '../server.js';
import { presentedKeys } from '../auth.js';
import { OmniPost } from '../../sdk/omnipost.js';

test('OmniPost Integrations & Developer Experience Suite', async (t) => {
  const adminKey = process.env.CHAMBERS_ADMIN_SECRET_KEY || 'test_admin_key_12345';
  const autoKey = process.env.AUTOMATION_SECRET_KEY || 'test_auto_key_12345';

  let server;
  let baseUrl;

  t.before(async () => {
    await new Promise((resolve) => {
      server = app.listen(0, '127.0.0.1', () => {
        const addr = server.address();
        baseUrl = `http://127.0.0.1:${addr.port}`;
        resolve();
      });
    });
  });

  t.after(async () => {
    if (server) {
      await new Promise((resolve) => server.close(resolve));
    }
  });

  await t.test('1. presentedKeys accepts x-api-key and query apiKey', () => {
    // x-api-key header
    const req1 = { headers: { 'x-api-key': 'my_webhook_key' } };
    assert.deepEqual(presentedKeys(req1), ['my_webhook_key']);

    // query parameter ?apiKey=
    const req2 = { headers: {}, query: { apiKey: 'query_param_key' } };
    assert.deepEqual(presentedKeys(req2), ['query_param_key']);

    // x-admin-key still takes priority
    const req3 = { headers: { 'x-admin-key': 'admin_prio', 'x-api-key': 'ignored' } };
    assert.deepEqual(presentedKeys(req3), ['admin_prio']);
  });

  await t.test('2. GET /api/webhook/info returns self-documenting JSON schema without auth', async () => {
    const res = await fetch(`${baseUrl}/api/webhook/info`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.name, 'OmniPost Universal Webhook Ingress');
    assert.ok(body.endpoints.publish);
    assert.ok(body.endpoints.schedule);
    assert.ok(body.endpoints.status);
    assert.ok(Array.isArray(body.supportedPlatforms));
  });

  await t.test('3. POST /api/webhook/publish requires authentication', async () => {
    const res = await fetch(`${baseUrl}/api/webhook/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: 'Unauthenticated Post',
        caption: 'This should fail'
      })
    });

    assert.equal(res.status, 401);
  });

  await t.test('4. POST /api/webhook/publish succeeds with x-api-key header', async () => {
    const res = await fetch(`${baseUrl}/api/webhook/publish`, {
      method: 'POST',
      headers: {
        'x-api-key': autoKey,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        title: 'Automated Webhook Post',
        caption: 'Publishing via incoming webhook! #omnipost #automation',
        mediaUrl: 'https://example.com/demo.mp4',
        platforms: ['linkedin'],
        publishNow: false
      })
    });

    assert.equal(res.status, 201);
    const body = await res.json();
    assert.equal(body.success, true);
    assert.ok(body.contentId);
    assert.equal(body.scheduled, true);
  });

  await t.test('5. GET /api/webhook/status/:contentId fetches state for post', async () => {
    // First create a post
    const createRes = await fetch(`${baseUrl}/api/webhook/schedule`, {
      method: 'POST',
      headers: {
        'x-api-key': autoKey,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        title: 'Status Check Post',
        caption: 'Checking status endpoint',
        scheduledDateTime: '2026-12-01T10:00:00Z',
        platforms: ['youtube']
      })
    });

    assert.equal(createRes.status, 201);
    const createBody = await createRes.json();
    const contentId = createBody.contentId;

    // Now query status
    const statusRes = await fetch(`${baseUrl}/api/webhook/status/${contentId}`, {
      headers: {
        'x-api-key': autoKey
      }
    });

    assert.equal(statusRes.status, 200);
    const statusBody = await statusRes.json();
    assert.equal(statusBody.success, true);
    assert.equal(statusBody.contentId, contentId);
    assert.equal(statusBody.status, 'Scheduled');
    assert.ok(statusBody.platforms.includes('youtube'));
  });

  await t.test('6. JavaScript OmniPost SDK integration with live server', async () => {
    const client = new OmniPost({
      baseUrl,
      apiKey: autoKey
    });

    assert.equal(client.baseUrl, baseUrl);
    assert.equal(client.apiKey, autoKey);

    // Schedule post via SDK
    const scheduled = await client.schedule({
      title: 'SDK Scheduled Post',
      caption: 'Created using OmniPost JS SDK',
      scheduledDateTime: '2026-12-25T12:00:00Z',
      platforms: ['pinterest']
    });

    assert.equal(scheduled.success, true);
    assert.ok(scheduled.contentId);

    // Fetch status via SDK
    const status = await client.getStatus(scheduled.contentId);
    assert.equal(status.success, true);
    assert.equal(status.contentId, scheduled.contentId);
  });
});
