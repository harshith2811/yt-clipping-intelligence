#!/usr/bin/env node
/**
 * Removes the automated verification posts from the practice's public feeds.
 *
 *   node automation/scripts/delete-test-posts.mjs          # check only
 *   node automation/scripts/delete-test-posts.mjs --delete # actually delete
 *
 * Deletion support is NOT uniform across Meta's surfaces:
 *
 *   Facebook Page  DELETE /{post-id}            supported with a Page token
 *   Threads        DELETE /{media-id}           supported with a user token
 *   Instagram      NOT SUPPORTED. The Content Publishing API can create media
 *                  but exposes no delete endpoint for published media, so an
 *                  Instagram post can only be removed by hand in the app.
 *
 * This script therefore reports honestly rather than pretending it cleaned
 * everything: a feed that still shows a test post must not be signed off as clean.
 */

import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '../.env') });

const DELETE = process.argv.includes('--delete');
const GRAPH = `https://graph.facebook.com/${process.env.META_GRAPH_VERSION || 'v21.0'}`;
const THREADS = 'https://graph.threads.net/v1.0';

const PAGE_TOKEN = process.env.FACEBOOK_PAGE_ACCESS_TOKEN || '';
const THREADS_TOKEN = process.env.THREADS_ACCESS_TOKEN || '';

const TARGETS = [
  {
    platform: 'threads',
    id: '18331274191276078',
    exists: `${THREADS}/18331274191276078?fields=id,permalink&access_token=${encodeURIComponent(THREADS_TOKEN)}`,
    del: `${THREADS}/18331274191276078?access_token=${encodeURIComponent(THREADS_TOKEN)}`,
    deletable: Boolean(THREADS_TOKEN)
  },
  {
    platform: 'facebook',
    id: '1323467794180143_122107161627464862',
    exists: `${GRAPH}/1323467794180143_122107161627464862?fields=id,permalink_url&access_token=${encodeURIComponent(PAGE_TOKEN)}`,
    del: `${GRAPH}/1323467794180143_122107161627464862?access_token=${encodeURIComponent(PAGE_TOKEN)}`,
    deletable: Boolean(PAGE_TOKEN)
  },
  {
    platform: 'instagram',
    id: '18071893007489889',
    exists: `${GRAPH}/18071893007489889?fields=id,permalink&access_token=${encodeURIComponent(PAGE_TOKEN)}`,
    del: null,
    deletable: false,
    note: 'Graph API exposes no delete for published IG media — remove it in the Instagram app.'
  }
];

async function req(url, method = 'GET') {
  const res = await fetch(url, { method });
  let body;
  try { body = await res.json(); } catch { body = null; }
  return { ok: res.ok && !body?.error, status: res.status, body };
}

const describe = (r) => r.body?.error
  ? `HTTP ${r.status} — ${r.body.error.message} (code ${r.body.error.code}${r.body.error.error_subcode ? `/${r.body.error.error_subcode}` : ''})`
  : `HTTP ${r.status}`;

console.log('\n==================================================');
console.log(' Verification post cleanup');
console.log('==================================================');
console.log(`Mode: ${DELETE ? 'DELETE' : 'CHECK ONLY (pass --delete to remove)'}\n`);

const summary = [];

for (const t of TARGETS) {
  const before = await req(t.exists);
  const present = before.ok;
  console.log(`${t.platform.padEnd(10)} ${t.id}`);
  console.log(`  present : ${present ? 'yes' : `no — ${describe(before)}`}`);

  if (!present) {
    summary.push({ platform: t.platform, state: 'already gone' });
    console.log('');
    continue;
  }
  if (!t.deletable) {
    console.log(`  delete  : NOT SUPPORTED. ${t.note || ''}`);
    summary.push({ platform: t.platform, state: 'MANUAL REMOVAL REQUIRED', note: t.note });
    console.log('');
    continue;
  }
  if (!DELETE) {
    console.log('  delete  : skipped (check-only run)');
    summary.push({ platform: t.platform, state: 'still live' });
    console.log('');
    continue;
  }

  const res = await req(t.del, 'DELETE');
  if (res.ok) {
    // Confirm by re-reading rather than trusting the delete response.
    const after = await req(t.exists);
    const gone = !after.ok;
    console.log(`  delete  : ${gone ? 'DELETED and confirmed gone' : 'API reported success but the post is still readable'}`);
    summary.push({ platform: t.platform, state: gone ? 'deleted' : 'delete unconfirmed' });
  } else {
    console.log(`  delete  : FAILED — ${describe(res)}`);
    summary.push({ platform: t.platform, state: 'delete failed', note: describe(res) });
  }
  console.log('');
}

console.log('--------------------------------------------------');
summary.forEach(s => console.log(`  ${s.platform.padEnd(10)} ${s.state}${s.note ? ` — ${s.note}` : ''}`));
const dirty = summary.filter(s => s.state !== 'deleted' && s.state !== 'already gone');
console.log(dirty.length === 0
  ? '\nAll verification posts removed.\n'
  : `\n${dirty.length} post(s) still public — see above.\n`);
