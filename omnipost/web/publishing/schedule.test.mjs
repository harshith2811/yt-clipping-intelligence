import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scheduleHasArrived, isInFlight, selectDue } from './schedule.js';

const NOW = Date.parse('2026-09-14T12:00:00Z');
const past = '2026-09-14T09:00:00Z';
const future = '2026-09-20T09:00:00Z';

test('a schedule in the future has not arrived', () => {
  assert.equal(scheduleHasArrived({ 'Scheduled DateTime': future }, NOW), false);
});

test('a schedule in the past has arrived', () => {
  assert.equal(scheduleHasArrived({ 'Scheduled DateTime': past }, NOW), true);
});

test('the exact scheduled instant counts as arrived', () => {
  assert.equal(scheduleHasArrived({ 'Scheduled DateTime': '2026-09-14T12:00:00Z' }, NOW), true);
});

test('snake_case rows from Supabase are read too', () => {
  assert.equal(scheduleHasArrived({ scheduled_datetime: future }, NOW), false);
  assert.equal(scheduleHasArrived({ scheduled_datetime: past }, NOW), true);
});

test('an unscheduled row is due immediately', () => {
  assert.equal(scheduleHasArrived({}, NOW), true);
});

test('an unparseable date is due rather than stranded forever', () => {
  assert.equal(scheduleHasArrived({ 'Scheduled DateTime': 'next Tuesday-ish' }, NOW), true);
});

test('in-flight detection covers both the status and the publish state', () => {
  assert.equal(isInFlight({ Status: 'Publishing' }), true);
  assert.equal(isInFlight({ publishState: 'pending' }), true);
  assert.equal(isInFlight({ publish_state: 'pending' }), true);
  assert.equal(isInFlight({ Status: 'Approved' }), false);
  assert.equal(isInFlight({}), false);
});

// --- the regression this module exists for -------------------------------
test('an approved post scheduled for next week is NOT published today', () => {
  const posts = [{ 'Content ID': 'W-100', Status: 'Approved', 'Scheduled DateTime': future }];
  assert.deepEqual(selectDue(posts, NOW), []);
});

test('an approved post whose moment has come IS published', () => {
  const posts = [{ 'Content ID': 'W-101', Status: 'Approved', 'Scheduled DateTime': past }];
  assert.equal(selectDue(posts, NOW).length, 1);
});

test('a post already in flight is advanced even though it is scheduled later', () => {
  // Once a container exists on Meta, stalling it is worse than publishing early.
  const posts = [{
    'Content ID': 'W-102', Status: 'Publishing',
    'Scheduled DateTime': future, publishState: 'pending'
  }];
  assert.equal(selectDue(posts, NOW).length, 1);
});

test('drafts and posts awaiting review are never picked up', () => {
  const posts = [
    { 'Content ID': 'W-103', Status: 'Draft', 'Scheduled DateTime': past },
    { 'Content ID': 'W-104', Status: 'Pending Review', 'Scheduled DateTime': past },
    { 'Content ID': 'W-105', Status: 'Posted', 'Scheduled DateTime': past }
  ];
  assert.deepEqual(selectDue(posts, NOW), []);
});

test('status matching is case-insensitive', () => {
  assert.equal(selectDue([{ Status: 'APPROVED', 'Scheduled DateTime': past }], NOW).length, 1);
  assert.equal(selectDue([{ Status: 'approved', 'Scheduled DateTime': past }], NOW).length, 1);
});

test('a mixed calendar selects only what is genuinely due', () => {
  const posts = [
    { 'Content ID': 'A', Status: 'Approved',       'Scheduled DateTime': past },
    { 'Content ID': 'B', Status: 'Approved',       'Scheduled DateTime': future },
    { 'Content ID': 'C', Status: 'Draft',          'Scheduled DateTime': past },
    { 'Content ID': 'D', Status: 'Publishing',     'Scheduled DateTime': future },
    { 'Content ID': 'E', Status: 'Pending Review', 'Scheduled DateTime': past }
  ];
  assert.deepEqual(selectDue(posts, NOW).map(p => p['Content ID']), ['A', 'D']);
});

test('a non-array input cannot crash the tick', () => {
  assert.deepEqual(selectDue(null, NOW), []);
  assert.deepEqual(selectDue(undefined, NOW), []);
});

// --- guards against a post that can never settle -------------------------
// Lives here rather than in state.test because it is the same class of defect
// as the schedule gate: work that silently never finishes.
import { advancePost, emptyPlatformState, isSettled } from './state.js';

test('an unconfigured platform fails the entry instead of stranding it', async () => {
  const states = {
    facebook: emptyPlatformState('facebook'),
    linkedin: emptyPlatformState('linkedin')   // no token -> no driver
  };
  const drivers = {
    facebook: {
      createContainer: async () => ({ postId: 'fb_1', releaseUrl: 'https://fb/1' })
    }
  };

  const next = await advancePost(states, drivers);

  assert.equal(next.facebook.state, 'completed');
  assert.equal(next.linkedin.state, 'failed');
  assert.equal(next.linkedin.failureKind, 'CONFIGURATION_ERROR');
  // The whole point: the post can now reach a terminal state.
  assert.equal(isSettled(next), true);
});

test('an already-terminal platform is never re-touched', async () => {
  const states = {
    facebook: { ...emptyPlatformState('facebook'), state: 'completed', postId: 'fb_1' },
    threads: { ...emptyPlatformState('threads'), state: 'failed', failureKind: 'FATAL_PAYLOAD' }
  };
  let called = false;
  const drivers = { facebook: { createContainer: async () => { called = true; return {}; } } };

  const next = await advancePost(states, drivers);

  assert.equal(called, false, 'a completed platform must never be published again');
  assert.equal(next.facebook.postId, 'fb_1');
  assert.equal(next.threads.state, 'failed');
});
