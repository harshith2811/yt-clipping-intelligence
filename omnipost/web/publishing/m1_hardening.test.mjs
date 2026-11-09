import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import express from 'express';
import { fileURLToPath } from 'url';

import * as authz from '../auth.js';
import * as registry from './registry.js';
import { MetaApiError, redactUrlSecrets } from './meta.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webDir = path.resolve(__dirname, '..');
const uploadsDir = path.join(webDir, 'uploads');
const mediaDir = path.join(uploadsDir, 'media');

describe('Milestone 1 Production Hardening Verification Suite', () => {
  let server;
  let baseUrl;
  const testChambersKey = 'test-chambers-passkey-123456';
  const testAutomationKey = 'test-automation-passkey-789012';
  const sessionKey = authz.sessionSigningKey(testChambersKey, testAutomationKey);

  // Setup test files in uploads
  const testVaultDir = path.join(uploadsDir, 'REF-TEST-001 - Test Client');
  const testWillFile = path.join(testVaultDir, 'draft-will.pdf');
  const testMediaFile = path.join(mediaDir, 'test-social-asset.mp4');
  const testForbiddenMediaFile = path.join(mediaDir, 'leak.pdf');

  before(async () => {
    if (!fs.existsSync(testVaultDir)) fs.mkdirSync(testVaultDir, { recursive: true });
    if (!fs.existsSync(mediaDir)) fs.mkdirSync(mediaDir, { recursive: true });
    fs.writeFileSync(testWillFile, 'CONFIDENTIAL WILL CONTENT: TEST ONLY');
    fs.writeFileSync(testMediaFile, 'PUBLIC MP4 VIDEO DATA');
    fs.writeFileSync(testForbiddenMediaFile, 'FORBIDDEN FILE IN MEDIA DIR');

    // Create a mini Express application mirroring server.js configuration for route integration tests
    const app = express();
    app.use(express.json());

    const PUBLIC_MEDIA_EXTS = new Set([
      '.mp4', '.mov', '.webm', '.mkv', '.avi', '.wmv',
      '.jpg', '.jpeg', '.png', '.webp', '.gif'
    ]);

    const resolver = authz.createResolver({
      chambersKey: testChambersKey,
      automationKey: testAutomationKey,
      sessionKey
    });

    // 1. Public Media Route
    app.get('/uploads/media/:filename(*)', (req, res) => {
      const filename = req.params.filename;
      if (!filename) return res.status(404).json({ success: false, message: 'File not found' });

      const ext = path.extname(filename).toLowerCase();
      if (!PUBLIC_MEDIA_EXTS.has(ext)) {
        return res.status(403).json({ success: false, message: 'Access to this file type is forbidden' });
      }

      const safePath = path.resolve(mediaDir, filename);
      const relative = path.relative(mediaDir, safePath);
      if (relative.startsWith('..') || path.isAbsolute(relative)) {
        return res.status(403).json({ success: false, message: 'Access denied' });
      }

      if (!fs.existsSync(safePath) || fs.statSync(safePath).isDirectory()) {
        return res.status(404).json({ success: false, message: 'Media not found' });
      }

      res.setHeader('X-Content-Type-Options', 'nosniff');
      return res.sendFile(safePath);
    });

    // 2. Protected General / Vault Uploads Route
    app.get('/uploads/:filepath(*)', async (req, res) => {
      const rawPath = req.params.filepath;
      if (!rawPath) return res.status(404).json({ success: false, message: 'File not found' });

      const safePath = path.resolve(uploadsDir, rawPath);
      const relative = path.relative(uploadsDir, safePath);
      if (relative.startsWith('..') || path.isAbsolute(relative)) {
        return res.status(403).json({ success: false, message: 'Access denied' });
      }

      if (!fs.existsSync(safePath) || fs.statSync(safePath).isDirectory()) {
        return res.status(404).json({ success: false, message: 'File not found' });
      }

      // Check Option A: Signed URL
      const { sig, exp } = req.query;
      const isSigned = authz.verifyVaultSignedUrl(req.path, sig, exp, sessionKey);
      if (isSigned) {
        res.setHeader('X-Content-Type-Options', 'nosniff');
        return res.sendFile(safePath);
      }

      // Check Option B: Authentication headers / session
      let identity;
      try {
        identity = await resolver.resolve(req);
      } catch (err) {
        identity = { roles: [] };
      }

      const roles = identity?.roles || [];
      if (roles.includes('chambers')) {
        res.setHeader('X-Content-Type-Options', 'nosniff');
        return res.sendFile(safePath);
      }

      const authenticated = roles.length > 0;
      return res.status(authenticated ? 403 : 401).json({
        success: false,
        code: authenticated ? 'FORBIDDEN' : 'UNAUTHORIZED',
        message: authenticated
          ? 'Access to chambers client documents requires the chambers role.'
          : 'Authentication or a valid signed document link is required.'
      });
    });

    // Auth Login
    app.post('/api/auth/login', (req, res) => {
      const { passcode } = req.body;
      if (!passcode) {
        return res.status(400).json({ success: false, message: 'Passcode is required' });
      }

      const entered = String(passcode).trim();
      const roles = authz.rolesForPasskey(entered, {
        chambersKey: testChambersKey,
        chambersPasskey: testChambersKey,
        automationKey: testAutomationKey,
        automationPasskey: testAutomationKey
      });

      if (!roles.length) {
        return res.status(401).json({
          success: false,
          message: 'Invalid access key. Please check your credentials.'
        });
      }

      const role = roles.includes('chambers') ? 'chambers' : 'automation';
      const token = authz.mintSessionToken(role, sessionKey);

      return res.json({
        success: true,
        token,
        role,
        roles,
        message: 'Authentication successful'
      });
    });

    // Channels
    app.get('/api/channels', async (req, res) => {
      const identity = await resolver.resolve(req);
      if (!identity.roles.includes('automation')) {
        return res.status(401).json({ success: false, code: 'UNAUTHORIZED' });
      }
      try {
        const channels = registry.channelInventory();
        res.json({
          channels,
          missingSummary: registry.missingSummary(),
          configuredCount: channels.filter(c => c.configured ?? c.connected).length,
          totalCount: channels.length
        });
      } catch (err) {
        res.status(500).json({ success: false, error: err.message });
      }
    });

    await new Promise((resolve) => {
      server = app.listen(0, '127.0.0.1', () => {
        const addr = server.address();
        baseUrl = `http://127.0.0.1:${addr.port}`;
        resolve();
      });
    });
  });

  after(async () => {
    if (server) {
      await new Promise((resolve) => server.close(resolve));
    }
    // Cleanup test files
    try {
      if (fs.existsSync(testWillFile)) fs.unlinkSync(testWillFile);
      if (fs.existsSync(testMediaFile)) fs.unlinkSync(testMediaFile);
      if (fs.existsSync(testForbiddenMediaFile)) fs.unlinkSync(testForbiddenMediaFile);
      if (fs.existsSync(testVaultDir)) fs.rmdirSync(testVaultDir);
    } catch {
      // ignore cleanup errors
    }
  });

  // DEF-01 Tests
  test('DEF-01: /api/auth/login mints valid token using string role and rolesForPasskey', async () => {
    const res = await fetch(`${baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ passcode: testChambersKey })
    });

    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.success, true);
    assert.equal(body.role, 'chambers');
    assert.ok(body.token.startsWith('vbls1.'));

    // Authenticate with the minted token to /api/channels
    const chanRes = await fetch(`${baseUrl}/api/channels`, {
      headers: { Authorization: `Bearer ${body.token}` }
    });
    assert.equal(chanRes.status, 200);
  });

  // DEF-05 Tests
  test('DEF-05: /api/auth/login rejects default dev key omnipost2026', async () => {
    const res = await fetch(`${baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ passcode: 'omnipost2026' })
    });

    assert.equal(res.status, 401);
  });

  // DEF-18 Public Media Tests
  test('DEF-18: Public media route serves whitelisted video files unauthenticated', async () => {
    const res = await fetch(`${baseUrl}/uploads/media/test-social-asset.mp4`);
    assert.equal(res.status, 200);
    const text = await res.text();
    assert.equal(text, 'PUBLIC MP4 VIDEO DATA');
    assert.equal(res.headers.get('x-content-type-options'), 'nosniff');
  });

  test('DEF-18: Public media route forbids non-whitelisted extensions (e.g. .pdf)', async () => {
    const res = await fetch(`${baseUrl}/uploads/media/leak.pdf`);
    assert.equal(res.status, 403);
  });

  test('DEF-18: Public media route blocks path traversal attempts', async () => {
    const res = await fetch(`${baseUrl}/uploads/media/..%2fREF-TEST-001%20-%20Test%20Client%2fdraft-will.pdf`);
    assert.equal(res.status, 403);
  });

  // DEF-18 Protected Legal Vault Tests
  test('DEF-18: Legal vault document requires chambers authentication', async () => {
    const vaultUrl = `${baseUrl}/uploads/REF-TEST-001 - Test Client/draft-will.pdf`;

    // 1. Unauthenticated -> 401
    const unauthRes = await fetch(vaultUrl);
    assert.equal(unauthRes.status, 401);

    // 2. Automation role only -> 403 (insufficient permissions)
    const autoRes = await fetch(vaultUrl, {
      headers: { 'x-admin-key': testAutomationKey }
    });
    assert.equal(autoRes.status, 403);

    // 3. Chambers role -> 200 OK
    const chamRes = await fetch(vaultUrl, {
      headers: { 'x-admin-key': testChambersKey }
    });
    assert.equal(chamRes.status, 200);
    const content = await chamRes.text();
    assert.equal(content, 'CONFIDENTIAL WILL CONTENT: TEST ONLY');
  });

  test('DEF-18: Legal vault document accessible via valid signed URL query', async () => {
    const docPath = '/uploads/REF-TEST-001 - Test Client/draft-will.pdf';
    const signedUrlPart = authz.mintVaultSignedUrl(docPath, sessionKey, { ttlSeconds: 120 });
    const fullSignedUrl = `${baseUrl}${signedUrlPart}`;

    const res = await fetch(fullSignedUrl);
    assert.equal(res.status, 200);
    const content = await res.text();
    assert.equal(content, 'CONFIDENTIAL WILL CONTENT: TEST ONLY');
  });

  test('DEF-18: Legal vault document rejects expired or tampered signed URL query', async () => {
    const docPath = '/uploads/REF-TEST-001 - Test Client/draft-will.pdf';
    // Expired in past
    const expiredUrlPart = authz.mintVaultSignedUrl(docPath, sessionKey, { ttlSeconds: -10 });
    const fullExpiredUrl = `${baseUrl}${expiredUrlPart}`;

    const resExpired = await fetch(fullExpiredUrl);
    assert.equal(resExpired.status, 401);

    // Tampered signature
    const validUrlPart = authz.mintVaultSignedUrl(docPath, sessionKey, { ttlSeconds: 120 });
    const tamperedUrl = `${baseUrl}${validUrlPart}tampered`;
    const resTampered = await fetch(tamperedUrl);
    assert.equal(resTampered.status, 401);
  });

  // DEF-09 Channel Inventory Tests
  test('DEF-09: /api/channels returns channels with configured property and missingSummary', async () => {
    const res = await fetch(`${baseUrl}/api/channels`, {
      headers: { 'x-admin-key': testAutomationKey }
    });
    assert.equal(res.status, 200);
    const data = await res.json();

    assert.ok(Array.isArray(data.channels));
    assert.ok(typeof data.configuredCount === 'number');
    assert.ok(typeof data.totalCount === 'number');
    assert.ok(typeof data.missingSummary === 'object' && data.missingSummary !== null);

    for (const ch of data.channels) {
      assert.ok(ch.id);
      assert.ok(ch.name);
      assert.equal(typeof ch.connected, 'boolean');
      assert.equal(typeof ch.configured, 'boolean');
      assert.equal(ch.connected, ch.configured);
    }
  });

  // DEF-12 Token Redaction Tests
  test('DEF-12: redactUrlSecrets sanitizes access_token, client_secret, token, appsecret_proof', () => {
    const sensitive = 'https://graph.facebook.com/v21.0/feed?access_token=EAAB...&client_secret=XYZ&appsecret_proof=PROOF&token=TOK&other=safe';
    const redacted = redactUrlSecrets(sensitive);
    assert.ok(!redacted.includes('EAAB...'));
    assert.ok(!redacted.includes('XYZ'));
    assert.ok(!redacted.includes('PROOF'));
    assert.ok(!redacted.includes('TOK'));
    assert.ok(redacted.includes('access_token=[REDACTED]'));
    assert.ok(redacted.includes('client_secret=[REDACTED]'));
    assert.ok(redacted.includes('appsecret_proof=[REDACTED]'));
    assert.ok(redacted.includes('token=[REDACTED]'));
    assert.ok(redacted.includes('other=safe'));
  });

  test('DEF-12: MetaApiError automatically strips tokens in endpoint property', () => {
    const err = new MetaApiError('Request Failed', {
      status: 401,
      endpoint: 'https://graph.facebook.com/v21.0/me?access_token=TOP_SECRET_123'
    });
    assert.ok(!err.endpoint.includes('TOP_SECRET_123'));
    assert.equal(err.endpoint, 'https://graph.facebook.com/v21.0/me?access_token=[REDACTED]');
  });
});
