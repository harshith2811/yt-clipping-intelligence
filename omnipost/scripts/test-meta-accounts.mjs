#!/usr/bin/env node
/**
 * Meta asset discovery for VBL Law Chambers.
 *
 *   node automation/scripts/test-meta-accounts.mjs
 *
 * Discovers, and writes into automation/.env (gitignored):
 *   FACEBOOK_PAGE_ID / FACEBOOK_PAGE_NAME / FACEBOOK_PAGE_ACCESS_TOKEN
 *   INSTAGRAM_BUSINESS_ACCOUNT_ID / INSTAGRAM_USERNAME
 *
 * IMPORTANT - which token does what
 *   An APP token ("{app_id}|{app_secret}") identifies the *application*. It can
 *   read app metadata, but Meta rejects it for /me/accounts, because "me" is
 *   meaningless without a user. Page discovery therefore REQUIRES a User Access
 *   Token carrying pages_show_list (plus pages_manage_posts to publish, and
 *   instagram_basic + instagram_content_publish for Instagram).
 *
 *   Supply one as FACEBOOK_USER_TOKEN in automation/.env, or pass it as the
 *   first argument. Generate it at:
 *     https://developers.facebook.com/tools/explorer/
 *   selecting app 4446798632297061 and the scopes above.
 *
 *   A short-lived Explorer token lasts ~1 hour; this script immediately
 *   exchanges it for a long-lived one (~60 days), and Page tokens derived from
 *   a long-lived user token do not expire.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENV_PATH = path.join(__dirname, '../.env');
dotenv.config({ path: ENV_PATH });

const GRAPH = `https://graph.facebook.com/${process.env.META_GRAPH_VERSION || 'v21.0'}`;
const THREADS = 'https://graph.threads.net/v1.0';

const APP_ID = process.env.FACEBOOK_APP_ID;
const APP_SECRET = process.env.FACEBOOK_APP_SECRET;
let USER_TOKEN = process.argv[2] || process.env.FACEBOOK_USER_TOKEN || '';
if (!USER_TOKEN) {
  const metagraphPath = path.join(__dirname, '../secrets/metagraph.txt');
  if (fs.existsSync(metagraphPath)) {
    USER_TOKEN = fs.readFileSync(metagraphPath, 'utf8').trim();
  }
}
const THREADS_TOKEN = process.env.THREADS_ACCESS_TOKEN || '';
const THREADS_USER_ID = process.env.THREADS_USER_ID || '';

if (!APP_ID || !APP_SECRET) {
  console.error('FACEBOOK_APP_ID / FACEBOOK_APP_SECRET missing from automation/.env');
  process.exit(2);
}

const APP_TOKEN = `${APP_ID}|${APP_SECRET}`;
const mask = (s) => (!s ? '<none>' : `${String(s).slice(0, 6)}…${String(s).slice(-4)} (${String(s).length} chars)`);

async function get(url, label) {
  const res = await fetch(url);
  let body;
  try { body = await res.json(); } catch { body = { raw: await res.text().catch(() => '') }; }
  return { ok: res.ok && !body?.error, status: res.status, body, label };
}

function reportError(r) {
  const e = r.body?.error;
  if (!e) return `HTTP ${r.status}`;
  return `HTTP ${r.status} — ${e.message} (code ${e.code}${e.error_subcode ? `/${e.error_subcode}` : ''}, type ${e.type})`;
}

/** Writes/updates keys in automation/.env without disturbing anything else. */
function upsertEnv(pairs) {
  let text = fs.existsSync(ENV_PATH) ? fs.readFileSync(ENV_PATH, 'utf8') : '';
  const eol = text.includes('\r\n') ? '\r\n' : '\n';
  for (const [key, value] of Object.entries(pairs)) {
    if (value === undefined || value === null || value === '') continue;
    const line = `${key}=${value}`;
    const re = new RegExp(`^${key}=.*$`, 'm');
    if (re.test(text)) text = text.replace(re, line);
    else text = text.replace(/\s*$/, '') + eol + line + eol;
  }
  fs.writeFileSync(ENV_PATH, text, 'utf8');
}

const discovered = {};

console.log('\n=============================================');
console.log(' Meta Asset Discovery — VBL Law Chambers');
console.log('=============================================');
console.log(`App ID      : ${APP_ID}`);
console.log(`App secret  : ${mask(APP_SECRET)}`);
console.log(`User token  : ${mask(USER_TOKEN)}`);
console.log(`Graph       : ${GRAPH}`);

// ---------------------------------------------------------------------------
console.log('\n[1] Application reachable (app token)');
{
  const r = await get(`${GRAPH}/${APP_ID}?fields=id,name,category&access_token=${encodeURIComponent(APP_TOKEN)}`);
  if (r.ok) console.log(`    OK   ${r.body.name} (id ${r.body.id}, category ${r.body.category || 'n/a'})`);
  else console.log(`    FAIL ${reportError(r)}`);
}

// ---------------------------------------------------------------------------
console.log('\n[2] Facebook Page discovery  —  GET /me/accounts');
let pageToken = '';
if (!USER_TOKEN) {
  // Demonstrate precisely why the app token cannot stand in for a user token,
  // rather than merely asserting it.
  const probe = await get(`${GRAPH}/me/accounts?access_token=${encodeURIComponent(APP_TOKEN)}`);
  console.log('    No FACEBOOK_USER_TOKEN set. Probing with the APP token to show the actual response:');
  console.log(`    ${reportError(probe)}`);
  console.log('    -> A User Access Token is required. See the header of this file.');
} else {
  // Exchange for a long-lived user token first; Page tokens inherit its life.
  const ll = await get(
    `${GRAPH}/oauth/access_token?grant_type=fb_exchange_token` +
    `&client_id=${APP_ID}&client_secret=${encodeURIComponent(APP_SECRET)}` +
    `&fb_exchange_token=${encodeURIComponent(USER_TOKEN)}`
  );
  const longLived = ll.ok && ll.body.access_token ? ll.body.access_token : USER_TOKEN;
  console.log(ll.ok
    ? `    Long-lived user token obtained (expires_in ${ll.body.expires_in || 'n/a'}s)`
    : `    Could not exchange for long-lived token: ${reportError(ll)} — continuing with the supplied token`);

  const r = await get(
    `${GRAPH}/me/accounts?fields=id,name,username,access_token,category&limit=100` +
    `&access_token=${encodeURIComponent(longLived)}`
  );
  if (!r.ok) {
    console.log(`    FAIL ${reportError(r)}`);
  } else {
    const pages = r.body.data || [];
    if (pages.length === 0) {
      console.log('    No Pages returned. The token holder must have a role on the Chambers Page.');
    }
    pages.forEach((p, i) => {
      console.log(`    [${i}] ${p.name}  id=${p.id}  category=${p.category || 'n/a'}`);
    });
    const page = pages[0];
    if (page) {
      pageToken = page.access_token || '';
      discovered.FACEBOOK_PAGE_ID = page.id;
      discovered.FACEBOOK_PAGE_NAME = page.name;
      discovered.FACEBOOK_PAGE_ACCESS_TOKEN = pageToken;
      discovered.FACEBOOK_USER_TOKEN = longLived;
      console.log(`    Page token: ${mask(pageToken)}`);
    }
  }
}

// ---------------------------------------------------------------------------
console.log('\n[3] Instagram Business Account  —  Page?fields=instagram_business_account');
if (!discovered.FACEBOOK_PAGE_ID) {
  console.log('    SKIP — depends on the Page discovered in [2].');
} else {
  const r = await get(
    `${GRAPH}/${discovered.FACEBOOK_PAGE_ID}` +
    `?fields=instagram_business_account{id,username,name}` +
    `&access_token=${encodeURIComponent(pageToken || USER_TOKEN)}`
  );
  const iga = r.body?.instagram_business_account;
  if (r.ok && iga) {
    console.log(`    OK   @${iga.username} (id ${iga.id}, name ${iga.name || 'n/a'})`);
    discovered.INSTAGRAM_BUSINESS_ACCOUNT_ID = iga.id;
    discovered.INSTAGRAM_USERNAME = iga.username;
  } else if (r.ok) {
    console.log('    No Instagram Business Account linked to this Page.');
    console.log('    Link it: Instagram app -> Settings -> Account type -> switch to Business, then connect the Page.');
  } else {
    console.log(`    FAIL ${reportError(r)}`);
  }
}

// ---------------------------------------------------------------------------
console.log('\n[4] Threads account');
if (!THREADS_TOKEN) {
  console.log('    SKIP — THREADS_ACCESS_TOKEN not set.');
} else {
  const r = await get(`${THREADS}/me?fields=id,username&access_token=${encodeURIComponent(THREADS_TOKEN)}`);
  if (r.ok) {
    console.log(`    OK   @${r.body.username} (id ${r.body.id})`);
    if (THREADS_USER_ID && r.body.id !== THREADS_USER_ID) {
      console.log(`    NOTE token belongs to ${r.body.id}, but THREADS_USER_ID is ${THREADS_USER_ID}`);
    }
    discovered.THREADS_USER_ID = r.body.id;
  } else {
    console.log(`    FAIL ${reportError(r)}`);
    console.log('    Threads tokens are 60-day; refresh via /refresh_access_token before expiry.');
  }
}

// ---------------------------------------------------------------------------
console.log('\n[5] Persisting to automation/.env (gitignored)');
if (Object.keys(discovered).length === 0) {
  console.log('    Nothing discovered — .env unchanged.');
} else {
  upsertEnv(discovered);
  Object.entries(discovered).forEach(([k, v]) => {
    console.log(`    ${k} = ${/TOKEN|SECRET/.test(k) ? mask(v) : v}`);
  });
}

console.log('\nDone.\n');
