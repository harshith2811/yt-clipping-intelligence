#!/usr/bin/env node
/**
 * Live publication verification for the native Meta adapters.
 *
 *   node automation/scripts/test-meta-publishing.mjs            # dry run
 *   node automation/scripts/test-meta-publishing.mjs --live     # actually posts
 *
 * --live PUBLISHES TO THE PRACTICE'S REAL PUBLIC ACCOUNTS. A Threads post is
 * visible to anyone immediately. The flag exists so this can never fire by
 * accident from a test runner or a CI step; delete the test post afterwards.
 *
 * Optional:
 *   --platforms=threads,facebook,instagram   limit the run
 *   --media=<public url>                     required for Instagram
 *   --content-id=<id>                        content_calendar row to update
 */

import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '../.env') });

const { buildDrivers } = await import('../web/publishing/meta.js');
const { advance, emptyPlatformState, rollupStatus } = await import('../web/publishing/state.js');
const db = await import('../web/db.js');

const argv = process.argv.slice(2);
const arg = (name, fallback = '') => {
  const hit = argv.find(a => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : fallback;
};
const LIVE = argv.includes('--live');
const ONLY = arg('platforms', '').split(',').map(s => s.trim()).filter(Boolean);
const MEDIA_URL = arg('media', '');
const CONTENT_ID = arg('content-id', `TEST-${Date.now().toString().slice(-6)}`);

const CAPTION = 'VBL Law Chambers Legal Technology System Test [Automated Verification]';

const post = {
  caption: CAPTION,
  mediaUrl: MEDIA_URL,
  mediaType: MEDIA_URL ? (/\.(mp4|mov|webm)$/i.test(MEDIA_URL) ? 'video' : 'image') : 'text'
};

console.log('\n===========================================================');
console.log(' Live Meta Publication Verification');
console.log('===========================================================');
console.log(`Mode       : ${LIVE ? 'LIVE — will post publicly' : 'DRY RUN — nothing will be posted'}`);
console.log(`Content ID : ${CONTENT_ID}`);
console.log(`Caption    : ${CAPTION}`);
console.log(`Media      : ${MEDIA_URL || '<none — text only>'}`);

let drivers = buildDrivers(post);
if (ONLY.length) {
  drivers = Object.fromEntries(Object.entries(drivers).filter(([k]) => ONLY.includes(k)));
}

// Report configuration honestly: a channel with no credentials is not a
// channel that passed, and must never be shown as one.
const ALL = ['facebook', 'instagram', 'threads'];
console.log('\nChannel configuration');
for (const p of ALL) {
  if (drivers[p]) {
    console.log(`  ${p.padEnd(10)} configured`);
  } else {
    const why = p === 'facebook' ? 'FACEBOOK_PAGE_ID / FACEBOOK_PAGE_ACCESS_TOKEN not set'
      : p === 'instagram' ? 'INSTAGRAM_BUSINESS_ACCOUNT_ID / FACEBOOK_PAGE_ACCESS_TOKEN not set'
      : 'THREADS_USER_ID / THREADS_ACCESS_TOKEN not set';
    console.log(`  ${p.padEnd(10)} NOT CONFIGURED — ${why}`);
  }
}

if (Object.keys(drivers).length === 0) {
  console.log('\nNothing to do.\n');
  process.exit(1);
}

if (!LIVE) {
  console.log('\nDry run complete. Re-run with --live to publish.\n');
  process.exit(0);
}

// ---------------------------------------------------------------------------
// Drive each channel through the state machine to a terminal state.
// ---------------------------------------------------------------------------
const MAX_PASSES = 40;       // ~2 minutes at 3s — IG transcoding is 30-60s
const PASS_DELAY_MS = 3000;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const states = Object.fromEntries(Object.keys(drivers).map(p => [p, emptyPlatformState(p)]));
const results = {};

console.log('\nPublishing');
for (let pass = 0; pass < MAX_PASSES; pass++) {
  let active = false;

  for (const [platform, driver] of Object.entries(drivers)) {
    const current = states[platform];
    if (current.state === 'completed' || current.state === 'failed') continue;
    active = true;

    const before = current.state;
    states[platform] = await advance(current, driver);
    const after = states[platform];

    if (before !== after.state) {
      console.log(`  ${platform.padEnd(10)} ${before} -> ${after.state}` +
        (after.containerId ? `  container=${after.containerId}` : '') +
        (after.postId ? `  post=${after.postId}` : ''));
    }
    if (after.state === 'failed') {
      console.log(`  ${platform.padEnd(10)} FAILED  kind=${after.failureKind}  ${after.lastError}`);
    }
  }

  if (!active) break;
  await sleep(PASS_DELAY_MS);
}

// ---------------------------------------------------------------------------
console.log('\nResults');
for (const [platform, s] of Object.entries(states)) {
  results[platform] = s;
  const line = s.state === 'completed'
    ? `postId=${s.postId}  ${s.releaseUrl || '(no permalink)'}`
    : `${s.failureKind || 'incomplete'} — ${s.lastError || s.state}`;
  console.log(`  ${platform.padEnd(10)} ${s.state.toUpperCase().padEnd(10)} ${line}`);
}

// ---------------------------------------------------------------------------
console.log('\nSyncing to Supabase content_calendar');
try {
  await db.savePost({
    'Content ID': CONTENT_ID,
    Title: 'Automated Meta publication verification',
    Caption: CAPTION,
    Platforms: Object.keys(drivers).join(','),
    'Scheduled DateTime': new Date().toISOString(),
    Status: 'Publishing',
    'Drive File ID': ''
  });

  const rollup = rollupStatus(states);
  const settled = Object.values(states).every(s => s.state === 'completed' || s.state === 'failed');
  await db.savePublishState(CONTENT_ID, states, {
    publishState: settled
      ? (Object.values(states).every(s => s.state === 'completed') ? 'completed' : 'failed')
      : 'pending',
    status: rollup,
    failureKind: Object.values(states).find(s => s.failureKind)?.failureKind || null
  });

  const backend = db.getBackendStatus();
  console.log(`  saved to ${backend.backend} (schemaReady=${backend.schemaReady})`);
  console.log(`  rollup status: ${rollup}`);
} catch (err) {
  console.log(`  Supabase sync failed: ${err.message}`);
}

const ok = Object.values(states).some(s => s.state === 'completed');
console.log(`\n${ok ? 'At least one channel published.' : 'No channel published.'}\n`);
process.exit(ok ? 0 : 1);
