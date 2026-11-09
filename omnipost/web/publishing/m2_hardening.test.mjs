import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'url';

import * as schedule from './schedule.js';
import * as publishState from './state.js';
import * as db from '../db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Milestone 2 Production Hardening Verification Suite', () => {
  const NOW = Date.parse('2026-09-14T12:00:00Z');
  const past = '2026-09-14T09:00:00Z';
  const future = '2026-09-20T09:00:00Z';

  const postsFile = path.join(__dirname, '..', 'data', 'posts.json');
  let initialPosts;

  before(async () => {
    try {
      if (fs.existsSync(postsFile)) {
        initialPosts = JSON.parse(fs.readFileSync(postsFile, 'utf8'));
      }
    } catch (_) {
      initialPosts = [];
    }
  });

  after(async () => {
    if (initialPosts !== undefined) {
      fs.writeFileSync(postsFile, JSON.stringify(initialPosts, null, 2));
    }
  });

  // ==============================================================================
  // 1. DEF-06: Scheduler Due Status Alignment Tests
  // ==============================================================================
  describe('DEF-06: Scheduler Due Status Alignment', () => {
    test('accepts Status "Scheduled" when scheduled time is past', () => {
      const posts = [{ 'Content ID': 'SCH-1', Status: 'Scheduled', 'Scheduled DateTime': past }];
      const due = schedule.selectDue(posts, NOW);
      assert.equal(due.length, 1);
      assert.equal(due[0]['Content ID'], 'SCH-1');
    });

    test('rejects Status "Scheduled" when scheduled time is in future', () => {
      const posts = [{ 'Content ID': 'SCH-2', Status: 'Scheduled', 'Scheduled DateTime': future }];
      const due = schedule.selectDue(posts, NOW);
      assert.equal(due.length, 0);
    });

    test('accepts Status "Approved for Posting" when scheduled time is past', () => {
      const posts = [{ 'Content ID': 'APP-1', Status: 'Approved for Posting', 'Scheduled DateTime': past }];
      const due = schedule.selectDue(posts, NOW);
      assert.equal(due.length, 1);
      assert.equal(due[0]['Content ID'], 'APP-1');
    });

    test('handles whitespace trimming and case insensitivity', () => {
      const posts = [
        { 'Content ID': 'W-1', Status: '  scheduled  ', 'Scheduled DateTime': past },
        { 'Content ID': 'W-2', Status: 'APPROVED FOR POSTING', 'Scheduled DateTime': past },
        { 'Content ID': 'W-3', Status: 'AppRoved', 'Scheduled DateTime': past },
        { 'Content ID': 'W-4', Status: 'Draft', 'Scheduled DateTime': past }
      ];
      const due = schedule.selectDue(posts, NOW);
      assert.equal(due.length, 3);
      assert.deepEqual(due.map(d => d['Content ID']), ['W-1', 'W-2', 'W-3']);
    });

    test('excludes posts with terminal publish states (published, completed, failed)', () => {
      const posts = [
        { 'Content ID': 'TERM-1', Status: 'Approved', 'Scheduled DateTime': past, publish_state: 'published' },
        { 'Content ID': 'TERM-2', Status: 'Approved', 'Scheduled DateTime': past, publishState: 'completed' },
        { 'Content ID': 'TERM-3', Status: 'Approved', 'Scheduled DateTime': past, publish_state: 'failed' },
        { 'Content ID': 'ACTIVE-1', Status: 'Approved', 'Scheduled DateTime': past, publish_state: 'queued' }
      ];
      const due = schedule.selectDue(posts, NOW);
      assert.equal(due.length, 1);
      assert.equal(due[0]['Content ID'], 'ACTIVE-1');
    });

    test('skips active in_flight claims within TTL, recovers expired claims', () => {
      const recentClaim = new Date(NOW - 60 * 1000).toISOString(); // 1 min ago (< 5m TTL)
      const expiredClaim = new Date(NOW - 10 * 60 * 1000).toISOString(); // 10 min ago (> 5m TTL)

      const posts = [
        { 'Content ID': 'LOCKED-1', Status: 'Approved', 'Scheduled DateTime': past, publish_state: 'in_flight', last_attempt_at: recentClaim },
        { 'Content ID': 'EXPIRED-1', Status: 'Approved', 'Scheduled DateTime': past, publish_state: 'in_flight', last_attempt_at: expiredClaim }
      ];
      const due = schedule.selectDue(posts, NOW);
      assert.equal(due.length, 1);
      assert.equal(due[0]['Content ID'], 'EXPIRED-1');
    });
  });

  // ==============================================================================
  // 2. DEF-02 & DEF-15: Database Persistence & Sheet Sync State Preservation
  // ==============================================================================
  describe('DEF-02 & DEF-15: DB Persistence and State Preservation', () => {
    test('savePost preserves public_media_url, media_type, and link attributes', async () => {
      const post = {
        'Content ID': 'TEST-MEDIA-001',
        Title: 'Test Video Post',
        Caption: 'Test Caption',
        Platforms: 'facebook,instagram',
        'Scheduled DateTime': past,
        Status: 'Draft',
        'Public Media URL': 'https://storage.example.com/media/video1.mp4',
        'Media Type': 'video',
        Link: 'https://example.com/promo'
      };

      const saved = await db.savePost(post);
      assert.equal(saved.public_media_url, 'https://storage.example.com/media/video1.mp4');
      assert.equal(saved.media_type, 'video');
      assert.equal(saved.link, 'https://example.com/promo');

      // Verify cached in posts
      const posts = await db.getPosts();
      const found = posts.find(p => (p['Content ID'] || p.content_id) === 'TEST-MEDIA-001');
      assert.ok(found);
      assert.equal(found.public_media_url, 'https://storage.example.com/media/video1.mp4');
      assert.equal(found.media_type, 'video');
      assert.equal(found.link, 'https://example.com/promo');
    });

    test('savePosts merges incoming Google Sheet rows without wiping active platform execution states', async () => {
      // 1. Setup an active post with runtime states
      const initial = {
        'Content ID': 'TEST-MERGE-002',
        Title: 'Original Title',
        Caption: 'Original Caption',
        Platforms: 'facebook,linkedin',
        'Scheduled DateTime': past,
        Status: 'Publishing',
        platform_statuses: {
          facebook: { state: 'completed', status: 'published', postId: 'fb_123', releaseUrl: 'https://fb.com/123' },
          linkedin: { state: 'pending', status: 'in_flight', containerId: 'urn:li:share:456' }
        },
        publish_state: 'pending'
      };
      await db.savePost(initial);

      // 2. Simulate incoming Google Sheets sync row (only editorial columns)
      const incomingSheets = [
        {
          'Content ID': 'TEST-MERGE-002',
          Title: 'Updated Editorial Title',
          Caption: 'Updated Editorial Caption',
          Platforms: 'facebook,linkedin',
          'Scheduled DateTime': past,
          Status: 'Approved' // Sheet might say Approved
        }
      ];

      const merged = await db.savePosts(incomingSheets);
      const postAfterSync = merged.find(p => (p['Content ID'] || p.content_id) === 'TEST-MERGE-002');

      assert.ok(postAfterSync);
      assert.equal(postAfterSync.Title, 'Updated Editorial Title');
      // Crucial: runtime platform states and container IDs must be preserved!
      assert.ok(postAfterSync.platform_statuses.facebook);
      assert.equal(postAfterSync.platform_statuses.facebook.postId, 'fb_123');
      assert.equal(postAfterSync.platform_statuses.facebook.status, 'published');
      assert.equal(postAfterSync.platform_statuses.linkedin.containerId, 'urn:li:share:456');
      assert.equal(postAfterSync.publish_state, 'pending');
    });

    test('savePosts preserves local-only posts that are not in incoming sheet list', async () => {
      const localPost = {
        'Content ID': 'LOCAL-ONLY-999',
        Title: 'Local Staged Post',
        Platforms: 'instagram',
        Status: 'Scheduled'
      };
      await db.savePost(localPost);

      // Incoming list without LOCAL-ONLY-999
      const incomingList = [
        { 'Content ID': 'SHEET-001', Title: 'Sheet Post', Platforms: 'facebook', Status: 'Draft' }
      ];

      const result = await db.savePosts(incomingList);
      const stillThere = result.find(p => (p['Content ID'] || p.content_id) === 'LOCAL-ONLY-999');
      assert.ok(stillThere, 'Local-only post must not be erased when sheet does not contain it');
    });
  });

  // ==============================================================================
  // 3. Requirement R3: Independent Multi-Channel State Transitions & Double-Publish Prevention
  // ==============================================================================
  describe('Requirement R3: Multi-Channel State Machine & Partial Failure Safety', () => {
    test('isPlatformPublished detects completed and published states', () => {
      assert.equal(publishState.isPlatformPublished({ state: 'completed' }), true);
      assert.equal(publishState.isPlatformPublished({ state: 'published' }), true);
      assert.equal(publishState.isPlatformPublished({ status: 'published' }), true);
      assert.equal(publishState.isPlatformPublished({ status: 'completed' }), true);
      assert.equal(publishState.isPlatformPublished({ state: 'pending' }), false);
      assert.equal(publishState.isPlatformPublished({ state: 'failed' }), false);
    });

    test('advancePost skips already published platforms and only calls drivers for pending/failed channels', async () => {
      let fbDriverCalls = 0;
      let igDriverCalls = 0;

      const mockDrivers = {
        facebook: {
          createContainer: async () => {
            fbDriverCalls++;
            return { postId: 'fb_post_999' };
          }
        },
        instagram: {
          createContainer: async () => {
            igDriverCalls++;
            return { containerId: 'ig_container_111' };
          }
        }
      };

      // Facebook is ALREADY published; Instagram was failed and needs retry
      const initialStates = {
        facebook: {
          platform: 'facebook',
          state: 'completed',
          status: 'published',
          postId: 'existing_fb_id',
          retryCount: 0
        },
        instagram: {
          platform: 'instagram',
          state: 'queued',
          status: 'pending',
          containerId: null,
          retryCount: 1
        }
      };

      const nextStates = await publishState.advancePost(initialStates, mockDrivers);

      // Facebook driver MUST NOT be called!
      assert.equal(fbDriverCalls, 0, 'Already published facebook driver must never be reinvoked');
      // Instagram driver MUST be called
      assert.equal(igDriverCalls, 1, 'Pending/failed instagram driver should be called');

      assert.equal(nextStates.facebook.postId, 'existing_fb_id');
      assert.equal(nextStates.instagram.containerId, 'ig_container_111');
      assert.equal(nextStates.instagram.state, 'pending');
    });

    test('rollupStatus returns Partially Posted when one succeeds and one permanently fails', () => {
      const states = {
        facebook: { platform: 'facebook', state: 'completed', status: 'published' },
        instagram: { platform: 'instagram', state: 'failed', status: 'failed' }
      };

      assert.equal(publishState.isSettled(states), true);
      assert.equal(publishState.rollupStatus(states), 'Partially Posted');
    });

    test('rollupStatus returns Posted when all channels succeed', () => {
      const states = {
        facebook: { platform: 'facebook', state: 'completed', status: 'published' },
        instagram: { platform: 'instagram', state: 'published', status: 'published' }
      };

      assert.equal(publishState.isSettled(states), true);
      assert.equal(publishState.rollupStatus(states), 'Posted');
    });
  });
});
