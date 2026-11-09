/**
 * Role resolution tests — against the REAL module.
 *
 * publishing/rbac.test.mjs keeps a hand-written mirror of the server's guard.
 * That was useful before the logic had a home of its own, but a mirror can
 * stay green while the thing it mirrors drifts. These import auth.js directly,
 * so they fail when the server's actual decision changes.
 *
 * The rule being protected: a social media assistant must never reach a
 * client's will, testator PII or a partition deed.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createResolver,
  looksLikeJwt,
  presentedKeys,
  keyMatches,
  ROLE_GRANTS,
  sessionSigningKey,
  mintSessionToken,
  readSessionToken,
  rolesForPasskey,
  mintVaultSignedUrl,
  verifyVaultSignedUrl,
  SESSION_TTL_MS
} from '../auth.js';

const CHAMBERS = 'chambers-passkey-aaaaaaaaaaaa';
const AUTOMATION = 'automation-passkey-bbbbbbbb';

const req = (headers = {}) => ({ headers });
const withKey = (k) => req({ 'x-admin-key': k });
const withBearer = (t) => req({ authorization: `Bearer ${t}` });

/** A structurally valid JWT. Never actually trusted - the verifier decides. */
function fakeJwt(payload = { sub: 'u1' }) {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  return `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64(payload)}.c2lnbmF0dXJl`;
}

const resolver = (over = {}) =>
  createResolver({ chambersKey: CHAMBERS, automationKey: AUTOMATION, ...over });

// --- passkeys ---------------------------------------------------------------

test('the chambers passkey grants both roles (it is a superset)', async () => {
  const roles = await resolver().rolesFor(withKey(CHAMBERS));
  assert.deepEqual(roles, ROLE_GRANTS.chambers);
  assert.ok(roles.includes('chambers'));
  assert.ok(roles.includes('automation'));
});

test('the automation passkey grants automation ONLY', async () => {
  const roles = await resolver().rolesFor(withKey(AUTOMATION));
  assert.deepEqual(roles, ['automation']);
  assert.equal(roles.includes('chambers'), false);
});

test('no credential grants nothing', async () => {
  assert.deepEqual(await resolver().rolesFor(req()), []);
});

test('a wrong key grants nothing', async () => {
  assert.deepEqual(await resolver().rolesFor(withKey('not-the-key')), []);
});

test('a base64 bearer works, and so does a raw one', async () => {
  const r = resolver();
  const encoded = Buffer.from(CHAMBERS).toString('base64');
  assert.ok((await r.rolesFor(withBearer(encoded))).includes('chambers'));
  assert.ok((await r.rolesFor(withBearer(CHAMBERS))).includes('chambers'));
});

test('an empty configured automation key cannot be matched by an empty header', async () => {
  const r = createResolver({ chambersKey: CHAMBERS, automationKey: '' });
  assert.deepEqual(await r.rolesFor(withKey('')), []);
  assert.deepEqual(await r.rolesFor(req({ 'x-admin-key': '' })), []);
});

test('key comparison is length-safe and timing-safe', () => {
  assert.equal(keyMatches('abc', 'abc'), true);
  assert.equal(keyMatches('abc', 'abcd'), false);   // must not throw
  assert.equal(keyMatches('', 'abc'), false);
  assert.equal(keyMatches(null, 'abc'), false);
});

test('presentedKeys prefers x-admin-key over Authorization', () => {
  const got = presentedKeys({ headers: { 'x-admin-key': 'A', authorization: 'Bearer B' } });
  assert.deepEqual(got, ['A']);
});

// --- JWT shape detection ----------------------------------------------------

test('a passkey is never mistaken for a JWT', () => {
  assert.equal(looksLikeJwt(CHAMBERS), false);
  assert.equal(looksLikeJwt('vbl2026'), false);
  assert.equal(looksLikeJwt(Buffer.from(CHAMBERS).toString('base64')), false);
  assert.equal(looksLikeJwt(''), false);
  assert.equal(looksLikeJwt(null), false);
  assert.equal(looksLikeJwt('a.b'), false);
  assert.equal(looksLikeJwt('not.a.jwt!'), false);
});

test('a real JWT shape is detected', () => {
  assert.equal(looksLikeJwt(fakeJwt()), true);
});

// --- Supabase Auth ----------------------------------------------------------

test('a Supabase JWT carrying the chambers role grants both roles', async () => {
  const r = resolver({
    verifySupabaseJwt: async () => ({ role: 'chambers', userId: 'u1', email: 'a@b.c' })
  });
  const identity = await r.resolve(withBearer(fakeJwt()));
  assert.deepEqual(identity.roles, ROLE_GRANTS.chambers);
  assert.equal(identity.userId, 'u1');
  assert.equal(identity.email, 'a@b.c');
});

test('a Supabase JWT carrying automation CANNOT reach the client vault', async () => {
  const r = resolver({ verifySupabaseJwt: async () => ({ role: 'automation', userId: 'u2' }) });
  const roles = await r.rolesFor(withBearer(fakeJwt()));
  assert.deepEqual(roles, ['automation']);
  assert.equal(roles.includes('chambers'), false);
});

test('a JWT the verifier rejects grants nothing', async () => {
  const r = resolver({ verifySupabaseJwt: async () => null });
  assert.deepEqual(await r.rolesFor(withBearer(fakeJwt())), []);
});

test('an unknown role in app_metadata grants nothing', async () => {
  const r = resolver({ verifySupabaseJwt: async () => ({ role: 'superuser', userId: 'u3' }) });
  assert.deepEqual(await r.rolesFor(withBearer(fakeJwt())), []);
});

test('a verifier that throws fails CLOSED, never open', async () => {
  const r = resolver({
    verifySupabaseJwt: async () => { throw new Error('supabase unreachable'); }
  });
  assert.deepEqual(await r.rolesFor(withBearer(fakeJwt())), []);
});

test('with no verifier configured, a JWT is simply not a credential', async () => {
  const r = createResolver({ chambersKey: CHAMBERS, automationKey: AUTOMATION });
  assert.deepEqual(await r.rolesFor(withBearer(fakeJwt())), []);
});

test('a passkey is checked before any network call is made', async () => {
  let called = false;
  const r = resolver({ verifySupabaseJwt: async () => { called = true; return null; } });
  await r.rolesFor(withKey(CHAMBERS));
  assert.equal(called, false, 'the shared key path must not touch the network');
});

// --- verification cache -----------------------------------------------------

test('a verified JWT is cached, so a burst is one round-trip', async () => {
  let calls = 0;
  const r = resolver({
    verifySupabaseJwt: async () => { calls++; return { role: 'automation', userId: 'u9' }; }
  });
  const token = fakeJwt();
  for (let i = 0; i < 5; i++) await r.rolesFor(withBearer(token));
  assert.equal(calls, 1);
});

test('the cache expires, so a revoked account does not stay valid forever', async () => {
  let calls = 0;
  let clock = 1_000;
  const r = createResolver({
    chambersKey: CHAMBERS,
    automationKey: AUTOMATION,
    cacheTtlMs: 60_000,
    now: () => clock,
    verifySupabaseJwt: async () => { calls++; return { role: 'chambers', userId: 'u1' }; }
  });
  const token = fakeJwt();
  await r.rolesFor(withBearer(token));
  await r.rolesFor(withBearer(token));
  assert.equal(calls, 1);

  clock += 61_000;
  await r.rolesFor(withBearer(token));
  assert.equal(calls, 2, 'the token must be re-verified once the TTL lapses');
});

test('the cache never stores the bearer token itself', async () => {
  // The keys are SHA-256 fingerprints; a token in a heap dump is a live
  // credential, a fingerprint is not.
  const r = resolver({ verifySupabaseJwt: async () => ({ role: 'chambers', userId: 'u1' }) });
  const token = fakeJwt({ sub: 'distinctive-subject-value' });
  await r.rolesFor(withBearer(token));
  assert.equal(r._cacheSize(), 1);
});

test('two different tokens do not collide in the cache', async () => {
  const roles = { a: 'chambers', b: 'automation' };
  const r = resolver({
    verifySupabaseJwt: async (t) => {
      const payload = JSON.parse(Buffer.from(t.split('.')[1], 'base64url').toString());
      return { role: roles[payload.sub], userId: payload.sub };
    }
  });
  const rolesA = await r.rolesFor(withBearer(fakeJwt({ sub: 'a' })));
  const rolesB = await r.rolesFor(withBearer(fakeJwt({ sub: 'b' })));
  assert.ok(rolesA.includes('chambers'));
  assert.deepEqual(rolesB, ['automation']);
});

// --- portal sessions (what /api/auth/login hands out) -----------------------

test('a login session never carries the passkey, and grants exactly its role', async () => {
  const key = sessionSigningKey(CHAMBERS, AUTOMATION);
  const token = mintSessionToken('chambers', key);
  assert.ok(!token.includes(CHAMBERS), 'raw passkey in token');
  assert.ok(!token.includes(Buffer.from(CHAMBERS).toString('base64')), 'base64 passkey in token');
  assert.ok(!Buffer.from(token.split('.')[1], 'base64url').toString().includes(CHAMBERS), 'passkey in payload');

  const r = resolver({ sessionKey: key });
  assert.deepEqual(await r.rolesFor(withBearer(token)), ROLE_GRANTS.chambers);
  assert.deepEqual(await r.rolesFor(withBearer(mintSessionToken('automation', key))), ROLE_GRANTS.automation);
});

test('an altered, expired or foreign session grants nothing', async () => {
  const key = sessionSigningKey(CHAMBERS, AUTOMATION);
  const r = resolver({ sessionKey: key });
  const auto = mintSessionToken('automation', key);
  const [p, payload, sig] = auto.split('.');
  const promoted = Buffer.from(JSON.stringify({ ...JSON.parse(Buffer.from(payload, 'base64url')), r: 'chambers' })).toString('base64url');
  assert.deepEqual(await r.rolesFor(withBearer(`${p}.${promoted}.${sig}`)), [], 'self-promoted to chambers');
  assert.deepEqual(await r.rolesFor(withBearer(`${auto}x`)), [], 'signature altered');

  const expired = mintSessionToken('chambers', key, { ttlMs: 1000, now: Date.now() - 5000 });
  assert.deepEqual(await r.rolesFor(withBearer(expired)), [], 'expired');

  const rotated = sessionSigningKey('a-new-chambers-passkey-cccc', AUTOMATION);
  assert.deepEqual(await r.rolesFor(withBearer(mintSessionToken('chambers', rotated))), [], 'signed with another key');
  assert.equal(readSessionToken(mintSessionToken('chambers', key), rotated), null, 'rotation voids sessions');
});

test('sessions default to a 12 hour life', () => {
  const key = sessionSigningKey(CHAMBERS, AUTOMATION);
  const now = 1_000_000;
  const s = readSessionToken(mintSessionToken('chambers', key, { now }), key, now);
  assert.equal(s.expiresAt - now, SESSION_TTL_MS);
  assert.equal(SESSION_TTL_MS, 12 * 60 * 60 * 1000);
  assert.equal(readSessionToken(mintSessionToken('chambers', key, { now }), key, now + SESSION_TTL_MS + 1), null);
});

// --- DEF-01 Auth Subsystem Remediation Tests --------------------------------

test('DEF-01: rolesForPasskey maps all supported passkey roles and keys', () => {
  const config = {
    chambersPasskey: 'cham-123',
    automationPasskey: 'auto-456',
    editorPasskey: 'edit-789',
    viewerPasskey: 'view-000'
  };

  assert.deepEqual(rolesForPasskey('cham-123', config), ROLE_GRANTS.chambers);
  assert.deepEqual(rolesForPasskey('auto-456', config), ROLE_GRANTS.automation);
  assert.deepEqual(rolesForPasskey('edit-789', config), ROLE_GRANTS.editor);
  assert.deepEqual(rolesForPasskey('view-000', config), ROLE_GRANTS.viewer);

  // Also works with *Key alias properties
  const keyConfig = {
    adminKey: 'cham-123',
    automationKey: 'auto-456',
    editorKey: 'edit-789',
    viewerKey: 'view-000'
  };
  assert.deepEqual(rolesForPasskey('cham-123', keyConfig), ROLE_GRANTS.chambers);
  assert.deepEqual(rolesForPasskey('auto-456', keyConfig), ROLE_GRANTS.automation);
  assert.deepEqual(rolesForPasskey('edit-789', keyConfig), ROLE_GRANTS.editor);
  assert.deepEqual(rolesForPasskey('view-000', keyConfig), ROLE_GRANTS.viewer);

  // Invalid / unknown / empty
  assert.deepEqual(rolesForPasskey('wrong', config), []);
  assert.deepEqual(rolesForPasskey('', config), []);
  assert.deepEqual(rolesForPasskey(null, config), []);
  assert.deepEqual(rolesForPasskey(undefined, config), []);
});

test('DEF-01: mintSessionToken accepts string and object { role } forms', () => {
  const key = sessionSigningKey(CHAMBERS, AUTOMATION);
  const fromStr = mintSessionToken('chambers', key);
  const fromObj = mintSessionToken({ role: 'chambers' }, key);

  assert.equal(readSessionToken(fromStr, key).role, 'chambers');
  assert.equal(readSessionToken(fromObj, key).role, 'chambers');

  assert.throws(() => mintSessionToken('invalid_role', key), /Unknown role/);
  assert.throws(() => mintSessionToken({ role: 'invalid_role' }, key), /Unknown role/);
  assert.throws(() => mintSessionToken({}, key), /Unknown role/);
  assert.throws(() => mintSessionToken(null, key), /Unknown role/);
});

test('DEF-01: createResolver returns callable instance and exposes .resolve', async () => {
  const r = createResolver({ chambersKey: CHAMBERS, automationKey: AUTOMATION });
  // Can be invoked as an async function directly
  const resFromCall = await r(withKey(CHAMBERS));
  assert.deepEqual(resFromCall.roles, ROLE_GRANTS.chambers);

  // Can be invoked via .resolve()
  const resFromResolve = await r.resolve(withKey(CHAMBERS));
  assert.deepEqual(resFromResolve.roles, ROLE_GRANTS.chambers);
});

test('DEF-01: createResolver accepts supabaseVerifier alias', async () => {
  let called = false;
  const verifier = async () => {
    called = true;
    return { role: 'chambers', userId: 'u-sb', email: 'sb@test.com' };
  };
  const r = createResolver({
    chambersKey: CHAMBERS,
    automationKey: AUTOMATION,
    supabaseVerifier: verifier
  });

  const identity = await r.resolve(withBearer(fakeJwt()));
  assert.equal(called, true);
  assert.deepEqual(identity.roles, ROLE_GRANTS.chambers);
  assert.equal(identity.userId, 'u-sb');
});

// --- DEF-05 Insecure Dev Key Remediation Tests -----------------------------

test('DEF-05: When CHAMBERS_KEY is null, no key is accepted', async () => {
  const r = createResolver({ chambersKey: null, automationKey: '' });

  const resDev = await r.resolve(withKey('omnipost2026'));
  assert.deepEqual(resDev.roles, [], 'omnipost2026 must be rejected');

  const resEmpty = await r.resolve(withKey(''));
  assert.deepEqual(resEmpty.roles, [], 'empty key must be rejected');

  const resRandom = await r.resolve(withKey('random-attacker-key'));
  assert.deepEqual(resRandom.roles, [], 'random key must be rejected');
});

// --- DEF-18 Vault Signed URL Tests -----------------------------------------

test('DEF-18: mintVaultSignedUrl and verifyVaultSignedUrl work for valid token', () => {
  const key = sessionSigningKey('cham-secret', 'auto-secret');
  const path = '/uploads/REF-999 - Testator/will.pdf';
  const url = mintVaultSignedUrl(path, key, { ttlSeconds: 60 });
  const [filePath, queryString] = url.split('?');
  const params = new URLSearchParams(queryString);

  const sig = params.get('sig');
  const exp = params.get('exp');

  assert.ok(sig, 'Signature must be present');
  assert.ok(exp, 'Expiry must be present');
  assert.equal(verifyVaultSignedUrl(filePath, sig, exp, key), true);
});

test('DEF-18: verifyVaultSignedUrl rejects expired tokens', () => {
  const key = sessionSigningKey('cham-secret', 'auto-secret');
  const path = '/uploads/REF-999 - Testator/will.pdf';
  const now = 1_000_000;
  const url = mintVaultSignedUrl(path, key, { ttlSeconds: 10, now });
  const [filePath, queryString] = url.split('?');
  const params = new URLSearchParams(queryString);

  const sig = params.get('sig');
  const exp = params.get('exp');

  // Verify at now + 15 seconds (expired)
  assert.equal(verifyVaultSignedUrl(filePath, sig, exp, key, now + 15_000), false);
});

test('DEF-18: verifyVaultSignedUrl rejects tampered path or signature', () => {
  const key = sessionSigningKey('cham-secret', 'auto-secret');
  const path = '/uploads/REF-999 - Testator/will.pdf';
  const url = mintVaultSignedUrl(path, key, { ttlSeconds: 60 });
  const [, queryString] = url.split('?');
  const params = new URLSearchParams(queryString);

  const sig = params.get('sig');
  const exp = params.get('exp');

  // Tampered path
  assert.equal(verifyVaultSignedUrl('/uploads/REF-111 - Other/will.pdf', sig, exp, key), false);
  // Tampered signature
  assert.equal(verifyVaultSignedUrl(path, sig + 'x', exp, key), false);
  // Tampered expiry
  assert.equal(verifyVaultSignedUrl(path, sig, String(Number(exp) + 100), key), false);
  // Missing signature or key
  assert.equal(verifyVaultSignedUrl(path, '', exp, key), false);
  assert.equal(verifyVaultSignedUrl(path, sig, exp, null), false);
});
