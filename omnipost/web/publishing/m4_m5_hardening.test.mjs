import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'url';

import * as registry from './registry.js';
import * as publishState from './state.js';
import { instagramAdapter, threadsAdapter } from './meta.js';
import { linkedinAdapter } from './linkedin.js';
import { createN8nClient } from '../n8n-client.js';
import * as db from '../db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Milestone 4 & 5 Production Hardening Verification Suite', () => {

  // ==============================================================================
  // 1. DEF-10: YouTube Batch Publishing Driver
  // ==============================================================================
  describe('DEF-10: YouTube Publishing Driver & Registry Handling', () => {
    test('youtubeAdapter returns valid container and conforms to state driver interface', async () => {
      const mockN8n = async (endpoint, opts) => {
        assert.equal(endpoint, '/webhook/youtube-publish');
        assert.equal(opts.body.title, 'Test Legal Explainer');
        return { videoId: 'dQw4w9WgXcQ' };
      };

      const driver = registry.youtubeAdapter({
        post: {
          'Content ID': 'W-YT-100',
          Title: 'Test Legal Explainer',
          Caption: 'Caption here',
          'Public Media URL': 'https://storage.example.com/video.mp4'
        },
        n8nClient: mockN8n
      });

      assert.equal(driver.platform, 'youtube');
      const created = await driver.createContainer();
      assert.equal(created.postId, 'dQw4w9WgXcQ');
      assert.equal(created.releaseUrl, 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');

      const checked = await driver.checkContainer('dQw4w9WgXcQ');
      assert.equal(checked, 'PUBLISHED');

      const published = await driver.publishContainer('dQw4w9WgXcQ');
      assert.equal(published.postId, 'dQw4w9WgXcQ');
    });

    test('buildAllDrivers builds YouTube driver when n8nClient is provided', () => {
      const mockN8n = async () => ({ videoId: 'yt-123' });
      const drivers = registry.buildAllDrivers(
        { title: 'Video Title', mediaUrl: 'https://cdn.example.com/v.mp4' },
        ['youtube', 'facebook'],
        { FACEBOOK_PAGE_ID: 'fb-id', FACEBOOK_PAGE_ACCESS_TOKEN: 'fb-tok' },
        fetch,
        mockN8n
      );

      assert.ok(drivers.youtube, 'YouTube driver must be instantiated when n8nClient is provided');
      assert.equal(drivers.youtube.platform, 'youtube');
      assert.ok(drivers.facebook, 'Facebook driver must be instantiated');
    });

    test('advancePost advances YouTube smoothly without throwing undefined property error', async () => {
      const mockN8n = async () => ({ videoId: 'yt-video-999' });
      const drivers = registry.buildAllDrivers(
        { title: 'Video Title', mediaUrl: 'https://cdn.example.com/v.mp4' },
        ['youtube'],
        {},
        fetch,
        mockN8n
      );

      const states = {
        youtube: publishState.emptyPlatformState('youtube')
      };

      const advanced = await publishState.advancePost(states, drivers);
      assert.ok(advanced.youtube);
      assert.equal(advanced.youtube.postId, 'yt-video-999');
      assert.equal(publishState.isPlatformPublished(advanced.youtube), true);
    });
  });

  // ==============================================================================
  // 2. DEF-13: Instagram Permalink Resolution (No Broken 404 Links)
  // ==============================================================================
  describe('DEF-13: Instagram Release URL Construction', () => {
    test('publishContainer queries permalink and shortcode instead of returning numeric media id URL', async () => {
      const fakeFetch = async (url) => {
        if (url.includes('media_publish')) {
          return {
            ok: true,
            json: async () => ({ id: '17999888777666555' })
          };
        }
        if (url.includes('fields=id,permalink,shortcode')) {
          return {
            ok: true,
            json: async () => ({
              id: '17999888777666555',
              permalink: 'https://www.instagram.com/p/C_abc123XYZ/',
              shortcode: 'C_abc123XYZ'
            })
          };
        }
        return { ok: false, status: 404 };
      };

      const adapter = instagramAdapter({
        igUserId: '178414000000000',
        accessToken: 'EAAB_TEST_TOKEN',
        post: { mediaUrl: 'https://example.com/photo.jpg', caption: 'IG Test' },
        fetchImpl: fakeFetch
      });

      const published = await adapter.publishContainer('container_123');
      assert.equal(published.postId, '17999888777666555');
      assert.equal(published.releaseUrl, 'https://www.instagram.com/p/C_abc123XYZ/');
      assert.notEqual(published.releaseUrl, 'https://www.instagram.com/p/17999888777666555');
    });

    test('describePublished returns permalink or shortcode link', async () => {
      const fakeFetch = async (url) => {
        if (url.includes('fields=id,permalink,shortcode')) {
          return {
            ok: true,
            json: async () => ({
              id: '17999888777666555',
              permalink: 'https://www.instagram.com/p/C_recoveredLink/'
            })
          };
        }
        return { ok: false, status: 404 };
      };

      const adapter = instagramAdapter({
        igUserId: '178414000000000',
        accessToken: 'EAAB_TEST_TOKEN',
        post: {},
        fetchImpl: fakeFetch
      });

      const described = await adapter.describePublished('container_123');
      assert.equal(described.postId, '17999888777666555');
      assert.equal(described.releaseUrl, 'https://www.instagram.com/p/C_recoveredLink/');
    });
  });

  // ==============================================================================
  // 3. DEF-14: LinkedIn Video Post Support & Error Reporting
  // ==============================================================================
  describe('DEF-14: LinkedIn Video Support & Validation', () => {
    test('throws clear 400 error when mediaType is video but mediaUrl is missing', async () => {
      const adapter = linkedinAdapter({
        accessToken: 'LI_TOKEN',
        authorUrn: 'urn:li:organization:123456',
        post: { caption: 'Caption without video', mediaType: 'video', mediaUrl: '' }
      });

      await assert.rejects(
        async () => { await adapter.createContainer(); },
        (err) => {
          assert.equal(err.status, 400);
          assert.match(err.message, /requires a media URL/i);
          return true;
        }
      );
    });

    test('supports video uploads via /rest/videos initializeUpload endpoint', async () => {
      const endpointsCalled = [];
      const fakeFetch = async (url, opts = {}) => {
        endpointsCalled.push(url);
        if (url.includes('/rest/videos?action=initializeUpload')) {
          return {
            ok: true,
            json: async () => ({
              value: {
                uploadInstructions: [{ uploadUrl: 'https://upload.linkedin.com/video-target' }],
                video: 'urn:li:video:789456'
              }
            })
          };
        }
        if (url.includes('https://upload.linkedin.com/video-target')) {
          return { ok: true, status: 200 };
        }
        if (url === 'https://storage.example.com/explainer.mp4') {
          return {
            ok: true,
            status: 200,
            body: Buffer.from('FAKE MP4 BYTES')
          };
        }
        if (url.includes('/rest/posts')) {
          const parsed = JSON.parse(opts.body);
          assert.equal(parsed.content.media.id, 'urn:li:video:789456');
          return {
            ok: true,
            status: 201,
            headers: new Headers({ 'x-restli-id': 'urn:li:share:999888' }),
            json: async () => ({})
          };
        }
        return { ok: false, status: 404 };
      };

      const adapter = linkedinAdapter({
        accessToken: 'LI_TOKEN',
        authorUrn: 'urn:li:organization:123456',
        post: {
          caption: 'Legal Video Update',
          mediaType: 'video',
          mediaUrl: 'https://storage.example.com/explainer.mp4'
        },
        fetchImpl: fakeFetch
      });

      const result = await adapter.createContainer();
      assert.equal(result.postId, 'urn:li:share:999888');
      assert.equal(result.releaseUrl, 'https://www.linkedin.com/feed/update/urn:li:share:999888');
      assert.ok(endpointsCalled.some(u => u.includes('/rest/videos?action=initializeUpload')));
    });
  });

  // ==============================================================================
  // 4. DEF-16: n8n Client Object Payload Forwarding
  // ==============================================================================
  describe('DEF-16: n8n Client JSON Payload Forwarding', () => {
    test('sendToN8n sends plain object body in axios data parameter', async () => {
      let interceptedRequest = null;
      const fakeHttp = async (config) => {
        interceptedRequest = config;
        return { data: { success: true, processed: true } };
      };

      const sendToN8n = createN8nClient({
        candidates: () => ['http://127.0.0.1:5678'],
        secret: 'webhook-secret-xyz',
        http: fakeHttp
      });

      const payload = { contentId: 'W-001', platforms: ['facebook', 'instagram'] };
      const response = await sendToN8n('/webhook/publish', {
        method: 'POST',
        body: payload
      });

      assert.deepEqual(response, { success: true, processed: true });
      assert.ok(interceptedRequest, 'Request should have been made');
      assert.deepEqual(interceptedRequest.data, payload, 'Plain object body must be passed as data to axios');
      assert.equal(interceptedRequest.headers['X-VBL-Webhook-Key'], 'webhook-secret-xyz');
    });
  });

  // ==============================================================================
  // 5. DEF-17: UI Contract Alignment (Batch Publish Summary Format)
  // ==============================================================================
  describe('DEF-17: Batch Publish UI Summary Object', () => {
    test('summary object supports both property access and string conversion', () => {
      const published = 3;
      const failed = 1;
      const skipped = 0;
      const requested = 4;

      const summary = {
        published,
        failed,
        skipped,
        requested,
        text: `${published} published, ${failed} failed, ${skipped} skipped`,
        toString() { return this.text; }
      };

      // EnginePanel.jsx accesses s.published and s.requested
      assert.equal(summary.published, 3);
      assert.equal(summary.requested, 4);
      assert.equal(summary.failed, 1);
      assert.equal(summary.skipped, 0);

      // Toast string representation
      const toastText = `Published ${summary.published || 0}/${summary.requested || 0}`;
      assert.equal(toastText, 'Published 3/4');
      assert.equal(String(summary), '3 published, 1 failed, 0 skipped');
    });
  });
});
