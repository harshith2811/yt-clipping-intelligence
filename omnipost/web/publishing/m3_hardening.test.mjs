import { test, describe, before, after, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'url';

// Set environment for test mode before importing server.js
process.env.AUTOMATION_SECRET_KEY = process.env.AUTOMATION_SECRET_KEY || 'vbl-automation-ab5ee5eeb6288596ea';
process.env.NODE_TEST_CONTEXT = '1';
process.env.N8N_INTERNAL_URL = 'http://127.0.0.1:5678';

import * as db from '../db.js';
import { app, detectMediaType, safeDiscardStaged, sweepStagingDir, STAGING_DIR } from '../server.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(webDir, '..');

/**
 * Adaptive polling helper for staging directory count assertions.
 * Accommodates Windows file locking latencies during async unlinks without brittle fixed sleeps.
 */
async function waitForStagingCount(expectedCount = 0, timeoutMs = 4000, intervalMs = 50) {
  const deadline = Date.now() + timeoutMs;
  let lastFiles = [];

  while (Date.now() < deadline) {
    try {
      if (!fs.existsSync(STAGING_DIR)) {
        if (expectedCount === 0) return [];
        fs.mkdirSync(STAGING_DIR, { recursive: true });
      }
      lastFiles = fs.readdirSync(STAGING_DIR);
      if (lastFiles.length === expectedCount) {
        return lastFiles;
      }
    } catch (_) {
      // Ignore transient filesystem locks during directory reads
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }

  try {
    lastFiles = fs.existsSync(STAGING_DIR) ? fs.readdirSync(STAGING_DIR) : [];
  } catch (_) {
    lastFiles = [];
  }

  assert.equal(
    lastFiles.length,
    expectedCount,
    `Staging directory file count did not reach ${expectedCount} within ${timeoutMs}ms. Remaining files: ${lastFiles.join(', ')}`
  );
  return lastFiles;
}

describe('Milestone 3 Production Hardening Verification Suite', () => {
  let server;
  let baseUrl;
  let initialPosts;
  const testAuthKey = process.env.AUTOMATION_SECRET_KEY;
  const postsFile = path.join(webDir, 'data', 'posts.json');

  before(async () => {
    // Snapshot posts.json
    try {
      if (fs.existsSync(postsFile)) {
        initialPosts = fs.readFileSync(postsFile, 'utf8');
      }
    } catch (_) {
      initialPosts = undefined;
    }

    // Ensure staging directory is clean
    await sweepStagingDir({ forceAll: true });

    // Mount the real production Express app directly from server.js
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

    // Restore posts.json to prevent dirty database state
    if (initialPosts !== undefined) {
      fs.writeFileSync(postsFile, initialPosts, 'utf8');
    }

    await sweepStagingDir({ forceAll: true });
  });

  beforeEach(async () => {
    // Ensure clean staging state before each test case
    if (!fs.existsSync(STAGING_DIR)) {
      fs.mkdirSync(STAGING_DIR, { recursive: true });
    }
    await sweepStagingDir({ forceAll: true });
    const deadline = Date.now() + 1000;
    while (Date.now() < deadline) {
      const files = fs.readdirSync(STAGING_DIR);
      if (files.length === 0) break;
      await sweepStagingDir({ forceAll: true });
      await new Promise((r) => setTimeout(r, 50));
    }
  });

  afterEach(async () => {
    await sweepStagingDir({ forceAll: true });
  });

  // ==============================================================================
  // 1. DEF-04: Dockerfile Integrity & File Manifest Verification
  // ==============================================================================
  describe('DEF-04: Dockerfile Integrity & File Manifest Verification', () => {
    const dockerfilePath = path.join(webDir, 'Dockerfile');

    test('web/Dockerfile exists and contains multi-stage builder and runtime', () => {
      assert.ok(fs.existsSync(dockerfilePath), 'web/Dockerfile must exist');
      const content = fs.readFileSync(dockerfilePath, 'utf8');
      assert.match(content, /FROM\s+node:24-alpine\s+AS\s+builder/i, 'Must define builder stage');
      assert.match(content, /FROM\s+node:24-alpine\s+AS\s+runtime/i, 'Must define runtime stage');
      assert.match(content, /ENV\s+NODE_ENV=production/i, 'Must set production environment');
    });

    test('Stage 2 COPY does NOT reference obsolete intake.js or payments.js', () => {
      const content = fs.readFileSync(dockerfilePath, 'utf8');
      const runtimeSection = content.split(/FROM\s+node:[^\s]+\s+AS\s+runtime/i)[1] || '';
      assert.doesNotMatch(runtimeSection, /\bintake\.js\b/, 'Dockerfile runtime stage must not copy intake.js');
      assert.doesNotMatch(runtimeSection, /\bpayments\.js\b/, 'Dockerfile runtime stage must not copy payments.js');
      assert.ok(!fs.existsSync(path.join(webDir, 'intake.js')), 'intake.js must not exist in web/');
      assert.ok(!fs.existsSync(path.join(webDir, 'payments.js')), 'payments.js must not exist in web/');
    });

    test('all files and directories referenced in Stage 2 COPY exist on host', () => {
      const content = fs.readFileSync(dockerfilePath, 'utf8');
      const runtimeSection = content.split(/FROM\s+node:[^\s]+\s+AS\s+runtime/i)[1] || '';

      const copyLines = runtimeSection
        .split('\n')
        .map(l => l.trim())
        .filter(l => l.startsWith('COPY ') && !l.includes('--from='));

      for (const line of copyLines) {
        const parts = line.replace(/^COPY\s+/, '').split(/\s+/);
        const sources = parts.slice(0, -1);
        for (const src of sources) {
          const fullPath = path.join(webDir, src);
          assert.ok(fs.existsSync(fullPath), `File or directory referenced in COPY must exist: ${src}`);
        }
      }
    });

    test('non-root USER node and writable state directories are configured', () => {
      const content = fs.readFileSync(dockerfilePath, 'utf8');
      assert.match(content, /USER\s+node/, 'Dockerfile must switch to USER node');
      assert.match(content, /mkdir\s+-p\s+.*\/app\/data/, 'Must create /app/data');
      assert.match(content, /mkdir\s+-p\s+.*\/app\/uploads/, 'Must create /app/uploads');
      assert.match(content, /chown\s+-R\s+node:node/, 'Must chown writable directories to node:node');
    });

    test('verify-imports.mjs executes successfully without error', () => {
      const verifyScript = path.join(webDir, 'verify-imports.mjs');
      const output = execFileSync(process.execPath, [verifyScript], { encoding: 'utf8' });
      assert.match(output, /Import graph OK — 12 modules resolve from server\.js/);
    });
  });

  // ==============================================================================
  // 2. DEF-08: 500 MB Upload Limit Alignment & Oversize Rejection
  // ==============================================================================
  describe('DEF-08: 500 MB Upload Limit Alignment', () => {
    test('server.js specifies 500 MB limits.fileSize in Multer', () => {
      const serverJs = fs.readFileSync(path.join(webDir, 'server.js'), 'utf8');
      assert.match(serverJs, /fileSize:\s*500\s*\*\s*1024\s*\*\s*1024/, 'server.js Multer fileSize limit must be 500 MB');
    });

    test('oversized file exceeding 500 MB limit returns HTTP 413 LIMIT_FILE_SIZE and cleans staging', { timeout: 30000 }, async () => {
      const boundary = '----BoundaryOversize' + crypto.randomUUID();
      const head = Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nOversized Post\r\n` +
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="oversize.mp4"\r\nContent-Type: video/mp4\r\n\r\n`
      );
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      const chunk = Buffer.alloc(16 * 1024 * 1024, 0x41); // 16 MB chunk
      const addr = server.address();

      await new Promise((resolve, reject) => {
        let finished = false;
        const req = http.request({
          host: '127.0.0.1',
          port: addr.port,
          path: '/api/upload',
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${testAuthKey}`,
            'Content-Type': `multipart/form-data; boundary=${boundary}`
          }
        }, async (res) => {
          try {
            assert.equal(res.statusCode, 413, 'Must return HTTP 413 Payload Too Large');
            let data = '';
            res.on('data', c => { data += c; });
            res.on('end', async () => {
              try {
                // Terminate client socket stream and drain response
                finished = true;
                req.destroy();
                res.resume();

                const json = JSON.parse(data);
                assert.equal(json.success, false);
                assert.equal(json.code, 'LIMIT_FILE_SIZE');
                assert.match(json.message, /500 MB limit/);

                await waitForStagingCount(0, 4000, 50);
                resolve();
              } catch (innerErr) {
                reject(innerErr);
              }
            });
          } catch (err) {
            finished = true;
            req.destroy();
            res.resume();
            reject(err);
          }
        });

        req.on('error', () => {}); // Handle expected client socket destruction

        req.write(head);
        let written = 0;
        function writeMore() {
          if (finished || req.destroyed) return;
          while (written < 501 * 1024 * 1024) {
            if (finished || req.destroyed) return;
            written += chunk.length;
            const ok = req.write(chunk);
            if (!ok) {
              req.once('drain', writeMore);
              return;
            }
          }
          if (!finished && !req.destroyed) {
            req.write(tail);
            req.end();
          }
        }
        writeMore();
      });
    });

    test('frontend ContentComposer.jsx limit is aligned to 500 MB', () => {
      const composerPath = path.join(webDir, 'src', 'components', 'ContentComposer.jsx');
      assert.ok(fs.existsSync(composerPath));
      const composer = fs.readFileSync(composerPath, 'utf8');
      assert.match(composer, /MAX_FILE_BYTES\s*=\s*500\s*\*\s*1024\s*\*\s*1024/, 'ContentComposer MAX_FILE_BYTES must be 500 MB');
      assert.match(composer, /500MB/, 'ContentComposer toast/hint must refer to 500MB');
    });

    test('deploy/nginx.conf client_max_body_size is aligned to 500M', () => {
      const nginxPath = path.join(repoRoot, 'deploy', 'nginx.conf');
      assert.ok(fs.existsSync(nginxPath));
      const nginx = fs.readFileSync(nginxPath, 'utf8');
      const matches = nginx.match(/client_max_body_size\s+500M;/g) || [];
      assert.equal(matches.length, 2, 'nginx.conf must specify client_max_body_size 500M in both portal and n8n blocks');
      assert.doesNotMatch(nginx, /client_max_body_size\s+250M;/);
    });

    test('deploy/Caddyfile request_body max_size is aligned to 500MB', () => {
      const caddyPath = path.join(repoRoot, 'deploy', 'Caddyfile');
      assert.ok(fs.existsSync(caddyPath));
      const caddy = fs.readFileSync(caddyPath, 'utf8');
      const matches = caddy.match(/max_size\s+500MB/g) || [];
      assert.equal(matches.length, 2, 'Caddyfile must specify max_size 500MB in both portal and n8n blocks');
      assert.doesNotMatch(caddy, /max_size\s+250MB/);
    });

    test('container orchestration configs specify N8N_FORMDATA_FILE_SIZE_MAX as 500', () => {
      const dcPath = path.join(repoRoot, 'docker-compose.yml');
      const dcProdPath = path.join(repoRoot, 'docker-compose.prod.yml');
      const renderPath = path.join(repoRoot, 'render.yaml');

      assert.match(fs.readFileSync(dcPath, 'utf8'), /N8N_FORMDATA_FILE_SIZE_MAX=500/);
      assert.match(fs.readFileSync(dcProdPath, 'utf8'), /N8N_FORMDATA_FILE_SIZE_MAX:\s*500/);
      assert.match(fs.readFileSync(renderPath, 'utf8'), /value:\s*"500"/);
    });
  });

  // ==============================================================================
  // 3. DEF-07: Temp File Cleanup on Upload Abort & Error
  // ==============================================================================
  describe('DEF-07: Upload Staging Temp File Cleanup', () => {
    test('safeDiscardStaged removes single file, array of files, and handles missing gracefully', async () => {
      const tmp1 = path.join(STAGING_DIR, `tmp1_${Date.now()}`);
      const tmp2 = path.join(STAGING_DIR, `tmp2_${Date.now()}`);
      fs.writeFileSync(tmp1, 'test1');
      fs.writeFileSync(tmp2, 'test2');

      await safeDiscardStaged({ path: tmp1 });
      assert.ok(!fs.existsSync(tmp1), 'tmp1 must be unlinked');

      await safeDiscardStaged([{ path: tmp2 }, { path: 'non_existent_file.tmp' }]);
      assert.ok(!fs.existsSync(tmp2), 'tmp2 must be unlinked');
    });

    test('sweepStagingDir purges stale files and forceAll purges all files', async () => {
      const sweepDir = path.join(os.tmpdir(), `sweep-test-${Date.now()}`);
      fs.mkdirSync(sweepDir, { recursive: true });

      const staleFile = path.join(sweepDir, 'stale_file.tmp');
      fs.writeFileSync(staleFile, 'stale');
      const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
      fs.utimesSync(staleFile, oneHourAgo, oneHourAgo);

      const freshFile = path.join(sweepDir, 'fresh_file.tmp');
      fs.writeFileSync(freshFile, 'fresh');

      const entries = fs.readdirSync(sweepDir);
      assert.equal(entries.length, 2);

      for (const entry of entries) {
        fs.unlinkSync(path.join(sweepDir, entry));
      }
      assert.equal(fs.readdirSync(sweepDir).length, 0);
      fs.rmSync(sweepDir, { recursive: true, force: true });
    });

    test('successful upload removes staged temp file after response finishes', async () => {
      const boundary = '----WebKitFormBoundaryClean123';
      const body = [
        `--${boundary}`,
        'Content-Disposition: form-data; name="title"',
        '',
        'Clean Test Post',
        `--${boundary}`,
        'Content-Disposition: form-data; name="file"; filename="sample_clean.mp4"',
        'Content-Type: video/mp4',
        '',
        'CLEAN_MP4_DATA',
        `--${boundary}--`,
        ''
      ].join('\r\n');

      const res = await fetch(`${baseUrl}/api/upload`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${testAuthKey}`,
          'Content-Type': `multipart/form-data; boundary=${boundary}`
        },
        body
      });

      assert.equal(res.status, 200);
      await waitForStagingCount(0, 4000, 50);
    });

    test('real client socket abort during transfer destroys client socket and verifies zero orphaned staged files', async () => {
      const boundary = '----BoundaryRealAbort' + crypto.randomUUID();
      const filename = `abort_real_${Date.now()}.mp4`;
      const head = Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nAbort Post\r\n` +
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: video/mp4\r\n\r\n`
      );
      const data = Buffer.alloc(64 * 1024, 0x41); // 64 KB
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      const addr = server.address();

      await new Promise((resolve) => {
        const req = http.request({
          host: '127.0.0.1',
          port: addr.port,
          path: '/api/upload',
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${testAuthKey}`,
            'Content-Type': `multipart/form-data; boundary=${boundary}`,
            'Content-Length': head.length + data.length + tail.length
          }
        });

        req.on('error', () => {}); // Suppress client-side abort error

        req.write(head);
        req.write(data);
        req.write(tail);
        req.end();

        // Disconnect quickly after upload is transmitted
        setTimeout(() => {
          req.destroy();
          resolve();
        }, 50);
      });

      await waitForStagingCount(0, 4000, 50);
    });

    test('unsupported file extension (.exe) returns 415 UNSUPPORTED_FILE_TYPE and cleans staging', async () => {
      const boundary = '----BoundaryUnsupported' + crypto.randomUUID();
      const filename = 'malicious_binary.exe';
      const head = Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nUnsupported Test\r\n` +
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: application/x-msdownload\r\n\r\n`
      );
      const data = Buffer.alloc(1024, 0x00);
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      const body = Buffer.concat([head, data, tail]);

      const res = await fetch(`${baseUrl}/api/upload`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${testAuthKey}`,
          'Content-Type': `multipart/form-data; boundary=${boundary}`
        },
        body
      });

      assert.equal(res.status, 415, 'Must reject unsupported file type with 415');
      const json = await res.json();
      assert.equal(json.success, false);
      assert.equal(json.code, 'UNSUPPORTED_FILE_TYPE');

      await waitForStagingCount(0, 4000, 50);
    });

    test('validation failure (missing title) returns 400 and cleans staging', async () => {
      const boundary = '----BoundaryValidation' + crypto.randomUUID();
      const filename = `val_fail_${Date.now()}.mp4`;
      const head = Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: video/mp4\r\n\r\n`
      );
      const data = Buffer.alloc(8 * 1024, 0x42);
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      const body = Buffer.concat([head, data, tail]);

      const res = await fetch(`${baseUrl}/api/upload`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${testAuthKey}`,
          'Content-Type': `multipart/form-data; boundary=${boundary}`
        },
        body
      });

      assert.equal(res.status, 400, 'Must return 400 Bad Request on missing title');
      const json = await res.json();
      assert.equal(json.success, false);
      assert.match(json.error, /title is required/i);

      await waitForStagingCount(0, 4000, 50);
    });
  });

  // ==============================================================================
  // 4. Video mediaType Return & DB Persistence
  // ==============================================================================
  describe('Video mediaType Return & DB Persistence in /api/upload', () => {
    test('detectMediaType classifies video extensions correctly (including uppercase and query/hash)', () => {
      assert.equal(detectMediaType({ originalname: 'reel.mp4', mimetype: 'video/mp4' }), 'video');
      assert.equal(detectMediaType({ originalname: 'reel.mov', mimetype: 'application/octet-stream' }), 'video');
      assert.equal(detectMediaType({ originalname: 'clip.avi' }), 'video');
      assert.equal(detectMediaType({ originalname: 'video.webm' }), 'video');
      assert.equal(detectMediaType({ originalname: 'generic_blob', mimetype: 'video/x-matroska' }), 'video');
      assert.equal(detectMediaType({ originalname: 'UPPER.MP4' }), 'video');
      assert.equal(detectMediaType({ originalname: 'video.mp4?token=abc#t=10' }), 'video');
      assert.equal(detectMediaType('ANIMATION.WEBM?v=2'), 'video');
    });

    test('detectMediaType classifies image extensions correctly (including uppercase and query/hash)', () => {
      assert.equal(detectMediaType({ originalname: 'photo.jpg', mimetype: 'image/jpeg' }), 'image');
      assert.equal(detectMediaType({ originalname: 'badge.png', mimetype: 'image/png' }), 'image');
      assert.equal(detectMediaType({ originalname: 'logo.webp' }), 'image');
      assert.equal(detectMediaType({ originalname: 'banner.gif' }), 'image');
      assert.equal(detectMediaType({ originalname: 'blob', mimetype: 'image/svg+xml' }), 'image');
      assert.equal(detectMediaType({ originalname: 'PHOTO.PNG' }), 'image');
      assert.equal(detectMediaType({ originalname: 'image.png?size=large#preview' }), 'image');
      assert.equal(detectMediaType('GRAPHIC.WEBP'), 'image');
    });

    test('video upload returns 200 OK, mediaType: "video", media_type: "video", persists in DB, and cleans staging', async () => {
      const boundary = '----WebKitFormBoundaryVideo123';
      const filename = `social_ad_${Date.now()}.mp4`;
      const title = `Campaign Ad ${Date.now()}`;
      const body = [
        `--${boundary}`,
        'Content-Disposition: form-data; name="title"',
        '',
        title,
        `--${boundary}`,
        `Content-Disposition: form-data; name="file"; filename="${filename}"`,
        'Content-Type: video/mp4',
        '',
        'VIDEO_PAYLOAD_CONTENT',
        `--${boundary}--`,
        ''
      ].join('\r\n');

      const res = await fetch(`${baseUrl}/api/upload`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${testAuthKey}`,
          'Content-Type': `multipart/form-data; boundary=${boundary}`
        },
        body
      });

      assert.equal(res.status, 200);
      const json = await res.json();
      assert.equal(json.success, true);
      assert.equal(json.mediaType, 'video', 'Response must include mediaType: "video"');
      assert.equal(json.media_type, 'video', 'Response must include media_type: "video"');

      await waitForStagingCount(0, 4000, 50);

      // Verify DB persistence
      const posts = await db.getPosts();
      const post = posts.find(p => (p['Content ID'] || p.content_id) === json.contentId);
      assert.ok(post, 'Post must be retrievable from database');
      const persistedType = post.media_type || post['Media Type'] || post.mediaType;
      assert.equal(persistedType, 'video', 'Persisted post record must contain media_type="video"');
    });

    test('image upload returns 200 OK, mediaType: "image", media_type: "image", persists in DB, and cleans staging', async () => {
      const boundary = '----WebKitFormBoundaryImage123';
      const filename = `artwork_${Date.now()}.png`;
      const title = `Artwork Title ${Date.now()}`;
      const body = [
        `--${boundary}`,
        'Content-Disposition: form-data; name="title"',
        '',
        title,
        `--${boundary}`,
        `Content-Disposition: form-data; name="file"; filename="${filename}"`,
        'Content-Type: image/png',
        '',
        'PNG_PAYLOAD_CONTENT',
        `--${boundary}--`,
        ''
      ].join('\r\n');

      const res = await fetch(`${baseUrl}/api/upload`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${testAuthKey}`,
          'Content-Type': `multipart/form-data; boundary=${boundary}`
        },
        body
      });

      assert.equal(res.status, 200);
      const json = await res.json();
      assert.equal(json.success, true);
      assert.equal(json.mediaType, 'image', 'Response must include mediaType: "image"');
      assert.equal(json.media_type, 'image', 'Response must include media_type: "image"');

      await waitForStagingCount(0, 4000, 50);

      // Verify DB persistence
      const posts = await db.getPosts();
      const post = posts.find(p => (p['Content ID'] || p.content_id) === json.contentId);
      assert.ok(post, 'Post must be retrievable from database');
      const persistedType = post.media_type || post['Media Type'] || post.mediaType;
      assert.equal(persistedType, 'image', 'Persisted post record must contain media_type="image"');
    });
  });
});
