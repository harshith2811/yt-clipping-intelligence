import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createN8nClient, multipartBody, WEBHOOK_KEY_HEADER } from '../n8n-client.js';

const REFUSED = 'http://127.0.0.1:1';

function startServer(handler) {
  const server = http.createServer(handler);
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve({ server, base: `http://127.0.0.1:${server.address().port}` }));
  });
}

function fixture(t, bytes) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'omnipost-n8n-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'deed.pdf');
  fs.writeFileSync(file, Buffer.alloc(bytes, 7));
  return file;
}

test('multipart body reaches the working candidate intact after a refused one', async (t) => {
  const { server, base } = await startServer((req, res) => {
    let received = 0;
    req.on('data', (c) => { received += c.length; });
    req.on('end', () => res.end(JSON.stringify({ received, declared: Number(req.headers['content-length']) })));
  });
  try {
    const file = fixture(t, 300 * 1024);
    const send = createN8nClient({ candidates: () => [REFUSED, REFUSED, base] });
    const out = await send('/webhook/content-upload', {
      method: 'POST',
      timeout: 5000,
      body: multipartBody({ contentId: 'P-000001' }, [
        { field: 'document_0', path: file, filename: 'deed.pdf', size: 300 * 1024 }
      ])
    });
    assert.ok(out.received > 300 * 1024);
    assert.equal(out.received, out.declared);
  } finally {
    server.close();
  }
});

test('every attempt builds its own body and releases it', async () => {
  const built = [];
  const body = () => {
    const part = { form: { getHeaders: () => ({}) }, released: false };
    part.release = () => { part.released = true; };
    built.push(part);
    return part;
  };
  const refused = Object.assign(new Error('refused'), { code: 'ECONNREFUSED' });
  const send = createN8nClient({
    candidates: () => ['a', 'b', 'c'],
    http: async ({ url }) => {
      if (url !== 'c/x') throw refused;
      return { data: { ok: true } };
    }
  });
  assert.deepEqual(await send('/x', { method: 'POST', body }), { ok: true });
  assert.equal(built.length, 3);
  assert.equal(new Set(built.map((p) => p.form)).size, 3);
  assert.ok(built.every((p) => p.released));
});

test('the webhook key header is sent only when a secret is configured', async () => {
  const seen = [];
  const http = async ({ headers }) => { seen.push(headers); return { data: {} }; };
  await createN8nClient({ candidates: () => ['a'], secret: 's3cret', http })('/x');
  await createN8nClient({ candidates: () => ['a'], http })('/x');
  assert.equal(seen[0][WEBHOOK_KEY_HEADER], 's3cret');
  assert.equal(WEBHOOK_KEY_HEADER in seen[1], false);
});

test('redirects are never followed, so the body is streamed rather than retained', async (t) => {
  // follow-redirects (axios' transport whenever redirects are allowed) keeps
  // a copy of the whole request body in memory. A 3xx that is NOT followed
  // proves the real axios stack is on Node's own transport.
  let hits = 0;
  const { server, base } = await startServer((req, res) => {
    hits += 1;
    req.resume();
    req.on('end', () => { res.writeHead(307, { location: `${base}/elsewhere` }); res.end(); });
  });
  try {
    const file = fixture(t, 64 * 1024);
    const send = createN8nClient({ candidates: () => [base] });
    await assert.rejects(
      send('/webhook/content-upload', {
        method: 'POST',
        timeout: 5000,
        body: multipartBody({ contentId: 'P-000002' }, [
          { field: 'document_0', path: file, filename: 'deed.pdf', size: 64 * 1024 }
        ])
      }),
      (err) => err.response?.status === 307
    );
    assert.equal(hits, 1);
  } finally {
    server.close();
  }
});

test('an HTTP error from n8n is final - the request is not replayed elsewhere', async () => {
  const calls = [];
  const forbidden = Object.assign(new Error('403'), { code: 'ERR_BAD_REQUEST', response: { status: 403 } });
  const send = createN8nClient({
    candidates: () => ['a', 'b'],
    http: async ({ url }) => { calls.push(url); throw forbidden; }
  });
  await assert.rejects(send('/webhook/content-upload', { method: 'POST' }), forbidden);
  assert.deepEqual(calls, ['a/webhook/content-upload']);
});
