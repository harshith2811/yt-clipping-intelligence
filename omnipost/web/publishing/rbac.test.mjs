/**
 * Role-based access control tests.
 *
 *   node automation/web/publishing/rbac.test.mjs
 *
 * These exercise the same decision logic server.js uses, without standing up
 * Express. The rule being protected: a social media assistant holding the
 * automation key must never reach a client's will, testator PII or a partition
 * deed — while the advocate's chambers key reaches everything.
 */

import assert from 'node:assert/strict';
import crypto from 'node:crypto';

let pass = 0, fail = 0;
const t = (name, fn) => {
  try { fn(); pass++; console.log(`  ok   ${name}`); }
  catch (e) { fail++; console.log(`  FAIL ${name}\n       ${e.message}`); }
};

// --- Mirror of the server's guard -------------------------------------------
const ROLE_GRANTS = { chambers: ['chambers', 'automation'], automation: ['automation'] };

function keyMatches(provided, expected) {
  if (!provided || !expected) return false;
  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function makeAuth(chambersKey, automationKey) {
  // Mirrors presentedKeys() in server.js: BOTH the decoded and the raw bearer
  // are candidates, because Buffer.from(x,'base64') never throws on bad input.
  const presented = (req) => {
    const custom = req.headers['x-admin-key'];
    if (custom) return [String(custom).trim()];
    const auth = req.headers['authorization'];
    if (auth && auth.startsWith('Bearer ')) {
      const raw = auth.substring(7).trim();
      const out = [raw];
      const decoded = Buffer.from(raw, 'base64').toString('utf-8').trim();
      if (decoded) out.unshift(decoded);
      return out;
    }
    return [];
  };
  const rolesFor = (req) => {
    for (const key of presented(req)) {
      if (!key) continue;
      if (keyMatches(key, chambersKey)) return ROLE_GRANTS.chambers;
      if (automationKey && keyMatches(key, automationKey)) return ROLE_GRANTS.automation;
    }
    return [];
  };
  // Returns the HTTP status the guard would produce.
  return (role, req) => {
    const roles = rolesFor(req);
    if (roles.includes(role)) return 200;
    return roles.length > 0 ? 403 : 401;
  };
}

const CHAMBERS = 'chambers-key-aaaaaaaaaaaa';
const AUTOMATION = 'automation-key-bbbbbbbbb';
const guard = makeAuth(CHAMBERS, AUTOMATION);

const bearer = (key) => ({ headers: { authorization: 'Bearer ' + Buffer.from(key).toString('base64') } });
const header = (key) => ({ headers: { 'x-admin-key': key } });
const anon = () => ({ headers: {} });

console.log('\nChambers role (client legal vault)');

t('chambers key opens the vault', () => {
  assert.equal(guard('chambers', bearer(CHAMBERS)), 200);
});

t('AUTOMATION KEY IS FORBIDDEN from the vault', () => {
  // The heart of the separation.
  assert.equal(guard('chambers', bearer(AUTOMATION)), 403);
});

t('no credential is 401, not 403', () => {
  assert.equal(guard('chambers', anon()), 401);
});

t('wrong key is 401', () => {
  assert.equal(guard('chambers', bearer('not-a-real-key-xxxxxxxxx')), 401);
});

console.log('\nAutomation role (publishing engine)');

t('automation key reaches publishing', () => {
  assert.equal(guard('automation', bearer(AUTOMATION)), 200);
});

t('chambers key ALSO reaches publishing (superset)', () => {
  // The advocate owns both surfaces; forcing a second credential would just
  // push them to reuse one key for everything.
  assert.equal(guard('automation', bearer(CHAMBERS)), 200);
});

t('anonymous is refused', () => {
  assert.equal(guard('automation', anon()), 401);
});

console.log('\nCredential presentation');

t('x-admin-key header works', () => {
  assert.equal(guard('chambers', header(CHAMBERS)), 200);
});

t('raw (non-base64) bearer still accepted', () => {
  assert.equal(guard('chambers', { headers: { authorization: 'Bearer ' + CHAMBERS } }), 200);
});

t('a valid key with trailing whitespace still matches', () => {
  assert.equal(guard('chambers', header(CHAMBERS + '   ')), 200);
});

t('prefix of a valid key is refused (no truncation match)', () => {
  assert.equal(guard('chambers', header(CHAMBERS.slice(0, 10))), 401);
});

t('key with extra suffix is refused', () => {
  assert.equal(guard('chambers', header(CHAMBERS + 'X')), 401);
});

console.log('\nDegenerate configuration');

t('no automation key set -> only chambers works', () => {
  const g = makeAuth(CHAMBERS, '');
  assert.equal(g('automation', bearer(CHAMBERS)), 200);
  assert.equal(g('automation', bearer(AUTOMATION)), 401);
});

t('identical keys collapse the separation (why the server warns)', () => {
  const g = makeAuth(CHAMBERS, CHAMBERS);
  // Documents the consequence: the automation holder gains the vault.
  assert.equal(g('chambers', bearer(CHAMBERS)), 200);
});

t('empty presented key never matches an empty configured key', () => {
  const g = makeAuth('', '');
  assert.equal(g('chambers', header('')), 401);
  assert.equal(g('chambers', anon()), 401);
});

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail === 0 ? 0 : 1);
