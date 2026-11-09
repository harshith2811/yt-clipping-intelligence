#!/usr/bin/env node
/**
 * Verifies the Supabase provisioning for VBL Law Chambers.
 *
 * Run after applying schema.sql:
 *   node automation/supabase/verify-schema.js
 *
 * Checks, in order:
 *   1. the three tables exist (service role can reach them);
 *   2. the ANON/publishable key can read NOTHING from them.
 *
 * Check 2 is the important one. The publishable key is designed to be embedded
 * in browsers, so a permissive RLS policy on these tables publishes every
 * client's particulars and privileged instructions to anyone who asks. The
 * first version of schema.sql carried `FOR SELECT TO public USING (true)` on
 * will_submissions and submission_documents, which did exactly that.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, '../.env') });

const URL = process.env.SUPABASE_URL;
const SERVICE = process.env.SUPABASE_SERVICE_ROLE_KEY;
const ANON = process.env.SUPABASE_ANON_KEY;

const TABLES = ['will_submissions', 'submission_documents', 'content_calendar', 'profiles', 'consultations'];
const SENSITIVE = ['will_submissions', 'submission_documents', 'profiles', 'consultations'];

if (!URL || !SERVICE) {
  console.error('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in automation/.env');
  process.exit(2);
}

async function query(table, key) {
  const res = await fetch(`${URL}/rest/v1/${table}?select=*&limit=1`, {
    headers: { apikey: key, Authorization: `Bearer ${key}` }
  });
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error page */ }
  return { status: res.status, body };
}

let failures = 0;
const note = (ok, text) => {
  if (!ok) failures++;
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${text}`);
};

console.log('\n1. Tables reachable with the service role');
let schemaApplied = true;
for (const table of TABLES) {
  const { status, body } = await query(table, SERVICE);
  if (status === 404 || body?.code === 'PGRST205') {
    schemaApplied = false;
    note(false, `${table} — not found. Apply automation/supabase/schema.sql first.`);
  } else {
    note(status === 200, `${table} — HTTP ${status}`);
  }
}

if (!schemaApplied) {
  console.log('\nSchema is not applied yet; skipping the RLS checks.');
  console.log('Apply it in the Supabase dashboard -> SQL Editor, then re-run this script.\n');
  process.exit(1);
}

console.log('\n2. Publishable (anon) key must NOT read client data');
if (!ANON) {
  console.log('  SKIP  SUPABASE_ANON_KEY not set — cannot verify the exposure path.');
} else {
  for (const table of SENSITIVE) {
    const { status, body } = await query(table, ANON);
    const rows = Array.isArray(body) ? body.length : null;
    // Anything that returns rows to the anon key is an exposure. A 200 with an
    // empty array is the expected RLS default-deny result; 401/403/404 are fine too.
    const exposed = status === 200 && rows > 0;
    note(!exposed, `${table} — anon HTTP ${status}${rows !== null ? `, ${rows} row(s)` : ''}${exposed ? '  <-- CLIENT DATA EXPOSED' : ''}`);
  }
}

console.log(
  failures === 0
    ? '\nAll checks passed.\n'
    : `\n${failures} check(s) failed.\n`
);
process.exit(failures === 0 ? 0 : 1);
