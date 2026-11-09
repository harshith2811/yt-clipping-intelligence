import { test, describe, before, after, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '..', '..');
const webDir = path.resolve(repoRoot, 'web');

process.env.AUTOMATION_SECRET_KEY = process.env.AUTOMATION_SECRET_KEY || 'vbl-automation-ab5ee5eeb6288596ea';
process.env.NODE_TEST_CONTEXT = '1';
process.env.N8N_INTERNAL_URL = 'http://127.0.0.1:5678';

const { app, safeDiscardStaged, sweepStagingDir, STAGING_DIR } = await import('../../web/server.js');
const db = await import('../../web/db.js');

const testAuthKey = process.env.AUTOMATION_SECRET_KEY;
const postsFile = path.join(webDir, 'data', 'posts.json');

/**
 * Adaptive polling helper for staging directory count assertions.
 * Accommodates Windows file locking latencies during async unlinks.
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

/**
 * Helper to build valid multipart body buffer.
 */
function buildMultipartBuffer({ title, filename, contentType, size, payloadByte = 0x42 }) {
  const boundary = '----BoundaryStress' + crypto.randomUUID();
  const head = Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\n${title}\r\n` +
    `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: ${contentType}\r\n\r\n`
  );
  const data = Buffer.alloc(size, payloadByte);
  const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
  return {
    boundary,
    body: Buffer.concat([head, data, tail]),
    head,
    data,
    tail,
    totalLength: head.length + data.length + tail.length
  };
}

describe('Empirical Challenger: M3 Upload Pipeline & Cleanup Stress Harness', { concurrency: false }, () => {
  let server;
  let baseUrl;
  let initialPosts;

  before(async () => {
    // Snapshot posts.json byte-for-byte
    try {
      if (fs.existsSync(postsFile)) {
        initialPosts = fs.readFileSync(postsFile, 'utf8');
      }
    } catch (_) {
      initialPosts = undefined;
    }

    if (!fs.existsSync(STAGING_DIR)) {
      fs.mkdirSync(STAGING_DIR, { recursive: true });
    }
    await sweepStagingDir({ forceAll: true });

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

    if (initialPosts !== undefined) {
      fs.writeFileSync(postsFile, initialPosts, 'utf8');
    }

    await sweepStagingDir({ forceAll: true });
  });

  beforeEach(async () => {
    if (!fs.existsSync(STAGING_DIR)) {
      fs.mkdirSync(STAGING_DIR, { recursive: true });
    }
    await sweepStagingDir({ forceAll: true });
    await waitForStagingCount(0, 4000, 50);
  });

  afterEach(async () => {
    await sweepStagingDir({ forceAll: true });
    await waitForStagingCount(0, 4000, 50);
  });

  // ============================================================================
  // Challenge 1: Windows File Lock Simulation (EBUSY / EPERM backoff)
  // ============================================================================
  describe('Challenge 1: Windows File Lock (EBUSY / EPERM) Retry Backoff Simulation', () => {
    test('safeDiscardStaged retries on locked file and unlinks after lock release mid-backoff', async () => {
      const testLockedFile = path.join(STAGING_DIR, `lock_test_${Date.now()}.tmp`);
      fs.writeFileSync(testLockedFile, 'LOCK_TEST_CONTENT');
      assert.ok(fs.existsSync(testLockedFile), 'File must exist before lock');

      await new Promise((resolve, reject) => {
        const child = spawn('powershell', [
          '-ExecutionPolicy', 'Bypass',
          '-File', path.join(repoRoot, 'tests', 'stress', 'lock_helper.ps1'),
          '-Path', testLockedFile,
          '-HoldMs', '120'
        ]);

        let started = false;
        child.stdout.on('data', async (d) => {
          if (!started && d.toString().includes('LOCKED')) {
            started = true;
            try {
              const start = Date.now();
              await safeDiscardStaged([{ path: testLockedFile }], 5);
              const elapsed = Date.now() - start;
              assert.ok(elapsed >= 100, `Must have performed backoff sleep (elapsed: ${elapsed}ms)`);
              assert.ok(!fs.existsSync(testLockedFile), 'File must be unlinked after lock release');
              resolve();
            } catch (err) {
              reject(err);
            }
          }
        });
        child.on('error', reject);
      });
    });

    test('safeDiscardStaged gracefully exhausts maxRetries without throwing when lock is never released', async () => {
      const testLockedFile = path.join(STAGING_DIR, `lock_perm_${Date.now()}.tmp`);
      fs.writeFileSync(testLockedFile, 'PERM_LOCKED');

      await new Promise((resolve, reject) => {
        const child = spawn('powershell', [
          '-ExecutionPolicy', 'Bypass',
          '-File', path.join(repoRoot, 'tests', 'stress', 'lock_helper.ps1'),
          '-Path', testLockedFile,
          '-HoldMs', '600'
        ]);

        let started = false;
        child.stdout.on('data', async (d) => {
          if (!started && d.toString().includes('LOCKED')) {
            started = true;
            try {
              const start = Date.now();
              await safeDiscardStaged([{ path: testLockedFile }], 3);
              const elapsed = Date.now() - start;
              assert.ok(elapsed >= 150, `Must have performed backoff retries (elapsed: ${elapsed}ms)`);
              assert.ok(fs.existsSync(testLockedFile), 'File should still exist while locked');
              resolve();
            } catch (err) {
              reject(err);
            }
          }
        });
        child.on('error', reject);
      });

      // Allow PS lock to finish releasing, then clean up
      await new Promise((r) => setTimeout(r, 650));
      if (fs.existsSync(testLockedFile)) {
        try { fs.unlinkSync(testLockedFile); } catch (_) {}
      }
    });
  });

  // ============================================================================
  // Challenge 2: High Concurrency Multipart Uploads (10-20 connections)
  // ============================================================================
  describe('Challenge 2: High Concurrency Multipart Uploads (20 concurrent connections)', () => {
    test('20 concurrent multipart uploads succeed with 200 OK and settle to 0 staging files', { timeout: 35000 }, async () => {
      const concurrency = 20;
      const tasks = [];

      for (let i = 0; i < concurrency; i++) {
        const isVideo = i % 2 === 0;
        const ext = isVideo ? 'mp4' : 'jpg';
        const mime = isVideo ? 'video/mp4' : 'image/jpeg';
        const filename = `concurrent_20_${i}_${Date.now()}.${ext}`;
        const title = `Concurrent Post 20 #${i} ${Date.now()}`;
        const payloadSize = 64 * 1024; // 64 KB per upload

        const { boundary, body } = buildMultipartBuffer({
          title,
          filename,
          contentType: mime,
          size: payloadSize,
          payloadByte: 0x41 + (i % 20)
        });

        tasks.push(
          (async () => {
            const res = await fetch(`${baseUrl}/api/upload`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${testAuthKey}`,
                'Content-Type': `multipart/form-data; boundary=${boundary}`
              },
              body
            });

            const status = res.status;
            const data = await res.json();
            return { index: i, status, data, isVideo };
          })()
        );
      }

      const results = await Promise.all(tasks);

      // Verify all 20 succeeded
      for (const res of results) {
        assert.equal(res.status, 200, `Task ${res.index} failed with status ${res.status}`);
        assert.equal(res.data.success, true, `Task ${res.index} success flag false`);
        assert.ok(res.data.contentId, `Task ${res.index} missing contentId`);
        const expectedType = res.isVideo ? 'video' : 'image';
        assert.equal(res.data.mediaType, expectedType);
      }

      // Verify STAGING_DIR settled to 0
      await waitForStagingCount(0, 4000, 50);

      // Verify DB contains all 20 posts
      const posts = await db.getPosts();
      for (const res of results) {
        const found = posts.find((p) => (p['Content ID'] || p.content_id) === res.data.contentId);
        assert.ok(found, `Post ${res.data.contentId} must be persisted in DB`);
      }
    });
  });

  // ============================================================================
  // Challenge 3: Aborts at Diverse Transfer Milestones (0%, 25%, 50%, 100%)
  // ============================================================================
  describe('Challenge 3: Aborts at Diverse Milestones (0%, 25%, 50%, 100%)', () => {
    const addr = () => server.address();

    test('Milestone 0% abort: client connects, sends headers, immediately destroys socket', async () => {
      const boundary = '----BoundaryAbort0Pct' + crypto.randomUUID();
      await new Promise((resolve) => {
        const req = http.request({
          host: '127.0.0.1',
          port: addr().port,
          path: '/api/upload',
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${testAuthKey}`,
            'Content-Type': `multipart/form-data; boundary=${boundary}`,
            'Content-Length': 1024 * 1024 // Claim 1 MB
          }
        });

        req.on('error', () => {}); // Handle expected abort error
        // Destroy immediately without writing any body bytes
        req.destroy();
        setTimeout(resolve, 100);
      });

      await waitForStagingCount(0, 4000, 50);
    });

    test('Milestone 25% abort: client sends 25% of body and aborts mid-transfer', async () => {
      const boundary = '----BoundaryAbort25Pct' + crypto.randomUUID();
      const filename = `abort25_${Date.now()}.mp4`;
      const head = Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nAbort 25%\r\n` +
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: video/mp4\r\n\r\n`
      );
      const totalPayloadSize = 1024 * 1024; // 1 MB total
      const chunk25 = Buffer.alloc(256 * 1024, 0x32); // 256 KB = 25%
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      const totalLen = head.length + totalPayloadSize + tail.length;

      await new Promise((resolve) => {
        const req = http.request({
          host: '127.0.0.1',
          port: addr().port,
          path: '/api/upload',
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${testAuthKey}`,
            'Content-Type': `multipart/form-data; boundary=${boundary}`,
            'Content-Length': totalLen
          }
        });

        req.on('error', () => {});

        req.write(head);
        req.write(chunk25);

        // Allow server to process chunk, then abort
        setTimeout(() => {
          req.destroy();
          setTimeout(resolve, 150);
        }, 50);
      });

      await waitForStagingCount(0, 4000, 50);
    });

    test('Milestone 50% abort: client sends 50% of body and aborts mid-transfer', async () => {
      const boundary = '----BoundaryAbort50Pct' + crypto.randomUUID();
      const filename = `abort50_${Date.now()}.mp4`;
      const head = Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nAbort 50%\r\n` +
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: video/mp4\r\n\r\n`
      );
      const totalPayloadSize = 1024 * 1024;
      const chunk50 = Buffer.alloc(512 * 1024, 0x35); // 512 KB = 50%
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      const totalLen = head.length + totalPayloadSize + tail.length;

      await new Promise((resolve) => {
        const req = http.request({
          host: '127.0.0.1',
          port: addr().port,
          path: '/api/upload',
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${testAuthKey}`,
            'Content-Type': `multipart/form-data; boundary=${boundary}`,
            'Content-Length': totalLen
          }
        });

        req.on('error', () => {});

        req.write(head);
        req.write(chunk50);

        setTimeout(() => {
          req.destroy();
          setTimeout(resolve, 150);
        }, 60);
      });

      await waitForStagingCount(0, 4000, 50);
    });

    test('Milestone 100% abort: client sends 100% of body, immediately drops socket before receiving response', async () => {
      const boundary = '----BoundaryAbort100Pct' + crypto.randomUUID();
      const filename = `abort100_${Date.now()}.mp4`;
      const { head, data, tail, totalLength } = buildMultipartBuffer({
        title: 'Abort 100%',
        filename,
        contentType: 'video/mp4',
        size: 128 * 1024,
        payloadByte: 0x99
      });

      await new Promise((resolve) => {
        const req = http.request({
          host: '127.0.0.1',
          port: addr().port,
          path: '/api/upload',
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${testAuthKey}`,
            'Content-Type': `multipart/form-data; boundary=${boundary}`,
            'Content-Length': totalLength
          }
        });

        req.on('error', () => {});

        req.write(head);
        req.write(data);
        req.write(tail);
        req.end();

        // Destroy socket immediately as soon as transmission finishes
        req.destroy();
        setTimeout(resolve, 200);
      });

      await waitForStagingCount(0, 4000, 50);
    });

    test('Rapid consecutive aborts (5 in sequence) do not leak staging files or corrupt state', async () => {
      for (let i = 0; i < 5; i++) {
        const boundary = `----BoundaryRapidAbort${i}_` + crypto.randomUUID();
        const filename = `rapid_abort_${i}.mp4`;
        const head = Buffer.from(
          `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nRapid ${i}\r\n` +
          `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="${filename}"\r\nContent-Type: video/mp4\r\n\r\n`
        );
        const chunk = Buffer.alloc(128 * 1024, 0x41);

        await new Promise((resolve) => {
          const req = http.request({
            host: '127.0.0.1',
            port: addr().port,
            path: '/api/upload',
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${testAuthKey}`,
              'Content-Type': `multipart/form-data; boundary=${boundary}`,
              'Content-Length': head.length + (chunk.length * 2)
            }
          });
          req.on('error', () => {});
          req.write(head);
          req.write(chunk);
          setTimeout(() => {
            req.destroy();
            resolve();
          }, 30);
        });
      }

      await waitForStagingCount(0, 4000, 50);
    });
  });

  // ============================================================================
  // Challenge 4: Oversized Payloads (> 500 MB) Triggering LIMIT_FILE_SIZE 413
  // ============================================================================
  describe('Challenge 4: Oversized Payloads (> 500 MB) LIMIT_FILE_SIZE 413 & Zero Leak', () => {
    test('single > 500 MB upload triggers 413 LIMIT_FILE_SIZE, zero residual staging files, server intact', { timeout: 35000 }, async () => {
      const boundary = '----BoundaryOversizeSingle' + crypto.randomUUID();
      const head = Buffer.from(
        `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nOversize Single\r\n` +
        `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="oversize_single.mp4"\r\nContent-Type: video/mp4\r\n\r\n`
      );
      const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
      const chunk = Buffer.alloc(16 * 1024 * 1024, 0x5a); // 16 MB chunk
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
        }, (res) => {
          assert.equal(res.statusCode, 413, 'Must return HTTP 413');
          let data = '';
          res.on('data', (c) => { data += c; });
          res.on('end', async () => {
            finished = true;
            req.destroy();
            res.resume();

            try {
              const json = JSON.parse(data);
              assert.equal(json.success, false);
              assert.equal(json.code, 'LIMIT_FILE_SIZE');
              await waitForStagingCount(0, 4000, 50);
              resolve();
            } catch (err) {
              reject(err);
            }
          });
        });

        req.on('error', () => {});

        req.write(head);
        let written = 0;
        function writeMore() {
          if (finished || req.destroyed) return;
          while (written < 505 * 1024 * 1024) {
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

      // Verify server remains responsive after handling 500MB rejection
      const pingRes = await fetch(`${baseUrl}/health`);
      assert.ok(pingRes.status === 200 || pingRes.status === 404, 'Server must remain responsive');
      await waitForStagingCount(0, 4000, 50);
    });

    test('concurrent oversized uploads (> 500 MB) all trigger 413 without collision or leak', { timeout: 45000 }, async () => {
      const concurrency = 2;
      const addr = server.address();

      const runOversized = (idx) => {
        return new Promise((resolve, reject) => {
          const boundary = `----BoundaryOversizeConc${idx}_` + crypto.randomUUID();
          const head = Buffer.from(
            `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nOversize Conc ${idx}\r\n` +
            `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="oversize_${idx}.mp4"\r\nContent-Type: video/mp4\r\n\r\n`
          );
          const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
          const chunk = Buffer.alloc(16 * 1024 * 1024, 0x4f);
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
          }, (res) => {
            assert.equal(res.statusCode, 413, `Concurrent oversized ${idx} must return 413`);
            let data = '';
            res.on('data', (c) => { data += c; });
            res.on('end', async () => {
              finished = true;
              req.destroy();
              res.resume();
              try {
                const json = JSON.parse(data);
                assert.equal(json.code, 'LIMIT_FILE_SIZE');
                resolve();
              } catch (e) {
                reject(e);
              }
            });
          });

          req.on('error', () => {});

          req.write(head);
          let written = 0;
          function writeMore() {
            if (finished || req.destroyed) return;
            while (written < 505 * 1024 * 1024) {
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
      };

      await Promise.all([runOversized(1), runOversized(2)]);
      await waitForStagingCount(0, 4000, 50);
    });
  });

  // ============================================================================
  // Challenge 5: Mixed Concurrency Storm
  // ============================================================================
  describe('Challenge 5: Mixed Concurrency Storm (Legitimate + Aborts + Limits + Invalid)', () => {
    test('18 mixed concurrent operations complete safely with zero staging leaks', { timeout: 45000 }, async () => {
      const addr = server.address();
      const operations = [];

      // Category A: 6 Legitimate uploads (3 video, 3 image)
      for (let i = 0; i < 6; i++) {
        const isVideo = i % 2 === 0;
        const ext = isVideo ? 'mp4' : 'jpg';
        const mime = isVideo ? 'video/mp4' : 'image/jpeg';
        const { boundary, body } = buildMultipartBuffer({
          title: `Storm Valid Post #${i}`,
          filename: `storm_valid_${i}.${ext}`,
          contentType: mime,
          size: 32 * 1024,
          payloadByte: 0x55 + i
        });

        operations.push(
          (async () => {
            const res = await fetch(`${baseUrl}/api/upload`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${testAuthKey}`,
                'Content-Type': `multipart/form-data; boundary=${boundary}`
              },
              body
            });
            const data = await res.json();
            return { type: 'valid', status: res.status, data };
          })()
        );
      }

      // Category B: 3 Aborts at 25%
      for (let i = 0; i < 3; i++) {
        operations.push(
          new Promise((resolve) => {
            const boundary = `----BoundaryStormAbort25_${i}_` + crypto.randomUUID();
            const head = Buffer.from(
              `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nStorm Abort 25% ${i}\r\n` +
              `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="storm_ab25_${i}.mp4"\r\nContent-Type: video/mp4\r\n\r\n`
            );
            const chunk = Buffer.alloc(128 * 1024, 0x66);
            const req = http.request({
              host: '127.0.0.1',
              port: addr.port,
              path: '/api/upload',
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${testAuthKey}`,
                'Content-Type': `multipart/form-data; boundary=${boundary}`,
                'Content-Length': head.length + (chunk.length * 4)
              }
            });
            req.on('error', () => {});
            req.write(head);
            req.write(chunk);
            setTimeout(() => {
              req.destroy();
              resolve({ type: 'abort_25', status: 'aborted' });
            }, 40);
          })
        );
      }

      // Category C: 3 Aborts at 50%
      for (let i = 0; i < 3; i++) {
        operations.push(
          new Promise((resolve) => {
            const boundary = `----BoundaryStormAbort50_${i}_` + crypto.randomUUID();
            const head = Buffer.from(
              `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nStorm Abort 50% ${i}\r\n` +
              `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="storm_ab50_${i}.mp4"\r\nContent-Type: video/mp4\r\n\r\n`
            );
            const chunk = Buffer.alloc(256 * 1024, 0x77);
            const req = http.request({
              host: '127.0.0.1',
              port: addr.port,
              path: '/api/upload',
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${testAuthKey}`,
                'Content-Type': `multipart/form-data; boundary=${boundary}`,
                'Content-Length': head.length + (chunk.length * 2)
              }
            });
            req.on('error', () => {});
            req.write(head);
            req.write(chunk);
            setTimeout(() => {
              req.destroy();
              resolve({ type: 'abort_50', status: 'aborted' });
            }, 50);
          })
        );
      }

      // Category D: 2 Aborts at 100% (immediate client drop)
      for (let i = 0; i < 2; i++) {
        operations.push(
          new Promise((resolve) => {
            const { boundary, head, data, tail, totalLength } = buildMultipartBuffer({
              title: `Storm Abort 100% ${i}`,
              filename: `storm_ab100_${i}.mp4`,
              contentType: 'video/mp4',
              size: 64 * 1024,
              payloadByte: 0x88
            });
            const req = http.request({
              host: '127.0.0.1',
              port: addr.port,
              path: '/api/upload',
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${testAuthKey}`,
                'Content-Type': `multipart/form-data; boundary=${boundary}`,
                'Content-Length': totalLength
              }
            });
            req.on('error', () => {});
            req.write(head);
            req.write(data);
            req.write(tail);
            req.end();
            req.destroy();
            resolve({ type: 'abort_100', status: 'aborted' });
          })
        );
      }

      // Category E: 2 Oversized uploads (> 500 MB)
      for (let i = 0; i < 2; i++) {
        operations.push(
          new Promise((resolve) => {
            const boundary = `----BoundaryStormOver_${i}_` + crypto.randomUUID();
            const head = Buffer.from(
              `--${boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nStorm Over ${i}\r\n` +
              `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="storm_over_${i}.mp4"\r\nContent-Type: video/mp4\r\n\r\n`
            );
            const chunk = Buffer.alloc(16 * 1024 * 1024, 0x4f);
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
            }, (res) => {
              let d = '';
              res.on('data', (c) => { d += c; });
              res.on('end', () => {
                finished = true;
                req.destroy();
                res.resume();
                try {
                  const j = JSON.parse(d);
                  resolve({ type: 'oversize', status: res.statusCode, data: j });
                } catch (_) {
                  resolve({ type: 'oversize', status: res.statusCode });
                }
              });
            });
            req.on('error', () => {});
            req.write(head);
            let written = 0;
            function writeMore() {
              if (finished || req.destroyed) return;
              while (written < 505 * 1024 * 1024) {
                if (finished || req.destroyed) return;
                written += chunk.length;
                const ok = req.write(chunk);
                if (!ok) {
                  req.once('drain', writeMore);
                  return;
                }
              }
              if (!finished && !req.destroyed) {
                req.end();
              }
            }
            writeMore();
          })
        );
      }

      // Category F: 2 Unsupported file types (.exe, .sh)
      for (let i = 0; i < 2; i++) {
        const ext = i === 0 ? 'exe' : 'sh';
        const mime = i === 0 ? 'application/x-msdownload' : 'application/x-sh';
        const { boundary, body } = buildMultipartBuffer({
          title: `Storm Unsupported ${i}`,
          filename: `malicious_${i}.${ext}`,
          contentType: mime,
          size: 1024,
          payloadByte: 0x00
        });

        operations.push(
          (async () => {
            const res = await fetch(`${baseUrl}/api/upload`, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${testAuthKey}`,
                'Content-Type': `multipart/form-data; boundary=${boundary}`
              },
              body
            });
            const data = await res.json();
            return { type: 'unsupported', status: res.status, data };
          })()
        );
      }

      assert.equal(operations.length, 18, 'Total storm operations must be 18');

      // Execute all 18 concurrently
      const results = await Promise.all(operations);

      // Verify legitimate uploads succeeded
      const validResults = results.filter((r) => r.type === 'valid');
      assert.equal(validResults.length, 6);
      for (const v of validResults) {
        assert.equal(v.status, 200);
        assert.equal(v.data.success, true);
      }

      // Verify oversized uploads returned 413
      const oversizeResults = results.filter((r) => r.type === 'oversize');
      assert.equal(oversizeResults.length, 2);
      for (const o of oversizeResults) {
        assert.equal(o.status, 413);
        assert.equal(o.data.code, 'LIMIT_FILE_SIZE');
      }

      // Verify unsupported returned 415
      const unsupportedResults = results.filter((r) => r.type === 'unsupported');
      assert.equal(unsupportedResults.length, 2);
      for (const u of unsupportedResults) {
        assert.equal(u.status, 415);
        assert.equal(u.data.code, 'UNSUPPORTED_FILE_TYPE');
      }

      // Verify STAGING_DIR settles to exactly 0
      await waitForStagingCount(0, 4000, 50);

      // Verify server is healthy and alive
      const healthCheck = await fetch(`${baseUrl}/health`);
      assert.ok(healthCheck.status === 200 || healthCheck.status === 404);
    });
  });

  // ============================================================================
  // Challenge 6: Zero Residual Files in Global STAGING_DIR
  // ============================================================================
  describe('Challenge 6: Global STAGING_DIR File Count & Database Hygiene', () => {
    test('STAGING_DIR contains exactly 0 files across all stress suites', async () => {
      const remaining = await waitForStagingCount(0, 4000, 50);
      assert.equal(remaining.length, 0, `Staging directory must contain 0 files, found: ${remaining.join(', ')}`);
    });

    test('posts.json remains valid JSON and can be restored cleanly', async () => {
      assert.ok(fs.existsSync(postsFile), 'posts.json must exist');
      const content = fs.readFileSync(postsFile, 'utf8');
      assert.doesNotThrow(() => JSON.parse(content), 'posts.json must be valid JSON');
    });
  });
});
