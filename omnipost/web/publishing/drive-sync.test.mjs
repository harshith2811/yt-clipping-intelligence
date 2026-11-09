import test from 'node:test';
import assert from 'node:assert/strict';
import { createDriveSync } from '../drive-sync.js';

// A tiny in-memory stand-in for the portal: records, a fake n8n that can be
// "asleep", and a clock the test moves by hand.
function harness({ records = [], onDisk = () => true } = {}) {
  const db = new Map(records.map((r) => [r.refId, { ...r }]));
  const calls = [];
  const state = { asleep: false, folderSeq: 0, clock: 1_000_000 };
  const quiet = { log() {}, warn() {} };
  const provision = async (record, { onlyFiles } = {}) => {
    calls.push({ refId: record.refId, onlyFiles: onlyFiles || null, hadFolder: Boolean(record.driveFolderId) });
    if (state.asleep) throw Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } });
    if (!record.driveFolderId) db.set(record.refId, { ...record, driveFolderId: `FOLDER_${++state.folderSeq}` });
    return true;
  };
  const sync = createDriveSync({
    getRecord: async (refId) => db.get(refId) || null,
    listRecords: async () => [...db.values()],
    provision,
    needsProvisioning: (r) => !r.driveFolderId,
    hasFilesOnDisk: onDisk,
    baseDelayMs: 1000,
    maxDelayMs: 8000,
    now: () => state.clock,
    log: quiet
  });
  return { db, calls, state, sync };
}

test('a submission that arrives while n8n sleeps reaches Drive on a later sweep, without anyone draining it', async () => {
  const h = harness({ records: [{ refId: 'VBL-1' }] });
  h.state.asleep = true;
  assert.equal((await h.sync.sync('VBL-1')).ok, false);
  assert.deepEqual(h.sync.status().outstanding, ['VBL-1']);

  h.state.asleep = false;
  await h.sync.sweep();                       // not due yet: backoff holds
  assert.equal(h.calls.length, 1);
  h.state.clock += 1000;
  await h.sync.sweep();
  assert.equal(h.db.get('VBL-1').driveFolderId, 'FOLDER_1');
  assert.deepEqual(h.sync.status().outstanding, []);
});

test('a supplementary upload during an outage is retried with only its own files, into the existing folder', async () => {
  const h = harness({ records: [{ refId: 'VBL-2', driveFolderId: 'CLIENT_FOLDER' }] });
  h.state.asleep = true;
  await h.sync.sync('VBL-2', { onlyFiles: ['4_deed.pdf'] });
  await h.sync.sync('VBL-2', { onlyFiles: ['5_passbook.pdf'] });
  assert.deepEqual(h.sync.status().unsyncedFiles, { 'VBL-2': ['4_deed.pdf', '5_passbook.pdf'] });

  h.state.asleep = false;
  h.state.clock += 60_000;
  await h.sync.sweep();
  const last = h.calls.at(-1);
  assert.deepEqual(last, { refId: 'VBL-2', onlyFiles: ['4_deed.pdf', '5_passbook.pdf'], hadFolder: true });
  assert.equal(h.db.get('VBL-2').driveFolderId, 'CLIENT_FOLDER');
  assert.deepEqual(h.sync.status(), { outstanding: [], unsyncedFiles: {} });
});

test('two syncs for one client never provision twice: the second sees the folder the first created', async () => {
  const h = harness({ records: [{ refId: 'VBL-3' }] });
  await Promise.all([h.sync.sync('VBL-3'), h.sync.sync('VBL-3', { onlyFiles: ['2_extra.pdf'] })]);
  const firstProvisionings = h.calls.filter((c) => !c.hadFolder);
  assert.equal(firstProvisionings.length, 1);
  assert.equal(h.state.folderSeq, 1);
});

test('a first provisioning carries every file, so queued supplementary files are not sent again', async () => {
  const h = harness({ records: [{ refId: 'VBL-4' }] });
  h.state.asleep = true;
  await h.sync.sync('VBL-4', { onlyFiles: ['3_late.pdf'] });
  h.state.asleep = false;
  h.state.clock += 60_000;
  await h.sync.sweep();
  assert.deepEqual(h.calls.map((c) => c.onlyFiles), [null, null]);
  assert.deepEqual(h.sync.status(), { outstanding: [], unsyncedFiles: {} });
});

test('backoff doubles and is capped, so a broken n8n is not woken every few minutes forever', async () => {
  const h = harness({ records: [{ refId: 'VBL-5' }] });
  h.state.asleep = true;
  await h.sync.sync('VBL-5');                 // attempt 1 -> wait 1s
  const gaps = [];
  for (let i = 0; i < 5; i++) {
    const before = h.calls.length;
    let waited = 0;
    while (h.calls.length === before) { h.state.clock += 500; waited += 500; await h.sync.sweep(); }
    gaps.push(waited);
  }
  assert.deepEqual(gaps, [1000, 2000, 4000, 8000, 8000]);
});

test('after a restart only pending records whose files are still on disk are retried', async () => {
  const h = harness({
    records: [{ refId: 'VBL-6' }, { refId: 'VBL-7' }, { refId: 'VBL-8', driveFolderId: 'DONE' }],
    onDisk: (r) => r.refId === 'VBL-6'
  });
  await h.sync.sweep();
  assert.deepEqual(h.calls.map((c) => c.refId), ['VBL-6']);
  assert.equal(h.db.get('VBL-7').driveFolderId, undefined);   // not hidden behind an empty folder
});

test('with nothing outstanding a sweep does not call n8n at all', async () => {
  const h = harness({ records: [{ refId: 'VBL-9', driveFolderId: 'DONE' }] });
  await h.sync.sweep();
  await h.sync.sweep();
  assert.equal(h.calls.length, 0);
});
