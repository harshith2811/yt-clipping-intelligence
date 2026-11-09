/**
 * OmniPost Universal JavaScript & TypeScript SDK
 *
 * Lightweight, zero-dependency client for OmniPost Social Media Automation & Publishing Engine.
 * Compatible with Node.js (>=18), Bun, Deno, and modern browser environments.
 *
 * @example
 * ```javascript
 * import { OmniPost } from './sdk/omnipost.js';
 *
 * const client = new OmniPost({
 *   baseUrl: 'http://localhost:3300',
 *   apiKey: 'my_automation_secret_key'
 * });
 *
 * // 1. Check which social platforms are ready
 * const status = await client.preflight();
 * console.log('Ready channels:', status.readyToPublish);
 *
 * // 2. Publish immediately to ready channels
 * const result = await client.publish({
 *   title: 'Product Launch Video',
 *   caption: 'Excited to announce our new update! #tech #startup',
 *   mediaUrl: 'https://example.com/video.mp4',
 *   platforms: ['youtube', 'linkedin', 'instagram']
 * });
 * console.log('Published:', result);
 * ```
 */

export class OmniPostError extends Error {
  constructor(message, { status = 500, code = 'OMNIPOST_ERROR', details = null } = {}) {
    super(message);
    this.name = 'OmniPostError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export class OmniPost {
  /**
   * Initialize OmniPost client.
   * @param {object} options
   * @param {string} [options.baseUrl='http://localhost:3300'] Base URL of the OmniPost API server.
   * @param {string} [options.apiKey=''] Automation secret key or Chambers admin key.
   * @param {number} [options.timeout=30000] Request timeout in milliseconds.
   */
  constructor({ baseUrl = 'http://localhost:3300', apiKey = '', timeout = 30000 } = {}) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.apiKey = apiKey || (typeof process !== 'undefined' ? process.env?.AUTOMATION_SECRET_KEY || process.env?.CHAMBERS_ADMIN_SECRET_KEY : '');
    this.timeout = timeout;
  }

  /**
   * Internal request helper with timeout and error classification.
   * @private
   */
  async _request(endpoint, { method = 'GET', body = null, headers = {} } = {}) {
    const url = `${this.baseUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
    const reqHeaders = {
      'Accept': 'application/json',
      ...headers
    };

    if (this.apiKey) {
      reqHeaders['x-api-key'] = this.apiKey;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.timeout);

    let requestBody = body;
    if (body && typeof body === 'object' && !(body instanceof FormData) && !(typeof Blob !== 'undefined' && body instanceof Blob)) {
      reqHeaders['Content-Type'] = 'application/json';
      requestBody = JSON.stringify(body);
    }

    try {
      const response = await fetch(url, {
        method,
        headers: reqHeaders,
        body: requestBody,
        signal: controller.signal
      });

      const contentType = response.headers.get('content-type') || '';
      let data;
      if (contentType.includes('application/json')) {
        data = await response.json();
      } else {
        const text = await response.text();
        try {
          data = JSON.parse(text);
        } catch {
          data = { rawText: text };
        }
      }

      if (!response.ok) {
        throw new OmniPostError(
          data?.message || data?.error || `HTTP ${response.status} from OmniPost`,
          {
            status: response.status,
            code: data?.code || `HTTP_${response.status}`,
            details: data
          }
        );
      }

      return data;
    } catch (err) {
      if (err instanceof OmniPostError) throw err;
      if (err.name === 'AbortError') {
        throw new OmniPostError(`Request to ${endpoint} timed out after ${this.timeout}ms`, {
          status: 408,
          code: 'REQUEST_TIMEOUT'
        });
      }
      throw new OmniPostError(`Network error communicating with OmniPost: ${err.message}`, {
        status: 502,
        code: 'NETWORK_ERROR'
      });
    } finally {
      clearTimeout(timeoutId);
    }
  }

  /**
   * Pre-flight health and reachability check for all configured social channels.
   * @returns {Promise<{ signal: string, armed: boolean, selectiveArmed: boolean, readyToPublish: string[], channels: object }>}
   */
  async preflight() {
    return this._request('/api/engine/preflight');
  }

  /**
   * Get channel configuration inventory and missing credential diagnostics.
   * @returns {Promise<{ channels: Array<{ id: string, name: string, configured: boolean, missingKeys: string[] }> }>}
   */
  async getChannels() {
    return this._request('/api/channels');
  }

  /**
   * Publish a social post immediately to one or more platforms.
   *
   * @param {object} params
   * @param {string} [params.title=''] Post title.
   * @param {string} params.caption Caption copy, hashtags, or text content.
   * @param {string} [params.mediaUrl=''] Publicly accessible URL of video or image.
   * @param {string} [params.mediaType] 'video' | 'image' | 'text' (auto-detected if omitted).
   * @param {string[]|string} [params.platforms] Target platforms (e.g. ['youtube', 'linkedin', 'instagram']).
   * @param {string} [params.link] External click-through link (optional).
   * @returns {Promise<{ success: boolean, contentId: string, status: string, results: Array<{ platform: string, status: string, permalink?: string }> }>}
   */
  async publish({ title = '', caption = '', mediaUrl = '', mediaType = '', platforms = [], link = '' } = {}) {
    const platformList = Array.isArray(platforms)
      ? platforms
      : (typeof platforms === 'string' && platforms.trim() ? platforms.split(',').map(s => s.trim()) : []);

    return this._request('/api/webhook/publish', {
      method: 'POST',
      body: {
        title,
        caption,
        mediaUrl,
        mediaType,
        platforms: platformList,
        link,
        publishNow: true
      }
    });
  }

  /**
   * Schedule a post for automated publishing at a designated date and time.
   *
   * @param {object} params
   * @param {string} [params.title=''] Post title.
   * @param {string} params.caption Caption copy, hashtags, or text content.
   * @param {string|Date} params.scheduledDateTime ISO 8601 date string or Date object.
   * @param {string} [params.mediaUrl=''] Publicly accessible URL of video or image.
   * @param {string} [params.mediaType] 'video' | 'image' | 'text' (auto-detected if omitted).
   * @param {string[]|string} [params.platforms] Target platforms.
   * @param {string} [params.link] External click-through link (optional).
   * @returns {Promise<{ success: boolean, contentId: string, scheduledDateTime: string }>}
   */
  async schedule({
    title = '',
    caption = '',
    scheduledDateTime = '',
    mediaUrl = '',
    mediaType = '',
    platforms = [],
    link = ''
  } = {}) {
    const scheduledIso = scheduledDateTime instanceof Date
      ? scheduledDateTime.toISOString()
      : (scheduledDateTime ? new Date(scheduledDateTime).toISOString() : new Date().toISOString());

    const platformList = Array.isArray(platforms)
      ? platforms
      : (typeof platforms === 'string' && platforms.trim() ? platforms.split(',').map(s => s.trim()) : []);

    return this._request('/api/webhook/schedule', {
      method: 'POST',
      body: {
        title,
        caption,
        mediaUrl,
        mediaType,
        platforms: platformList,
        scheduledDateTime: scheduledIso,
        link
      }
    });
  }

  /**
   * Check the current publication status and release permalinks for a content ID.
   *
   * @param {string} contentId Content ID (e.g. 'P-12345678')
   * @returns {Promise<{ success: boolean, contentId: string, status: string, publishState: string, platformStatuses: object }>}
   */
  async getStatus(contentId) {
    if (!contentId) throw new OmniPostError('contentId is required', { status: 400 });
    return this._request(`/api/webhook/status/${encodeURIComponent(contentId)}`);
  }

  /**
   * Fetch all posts from the content calendar.
   * @returns {Promise<{ count: number, posts: Array<object> }>}
   */
  async getPosts() {
    return this._request('/api/v1/posts');
  }

  /**
   * Upload media file (video or image) directly to OmniPost.
   *
   * @param {File|Blob|Buffer} fileData File object or Buffer.
   * @param {string} filename Name of the file with extension.
   * @param {object} [metadata]
   * @param {string} [metadata.title]
   * @param {string} [metadata.caption]
   * @param {string[]|string} [metadata.platforms]
   * @param {string} [metadata.scheduledDateTime]
   * @returns {Promise<{ success: boolean, contentId: string, publicMediaUrl: string, mediaType: string }>}
   */
  async uploadMedia(fileData, filename = 'media.mp4', metadata = {}) {
    const formData = new FormData();

    if (typeof Blob !== 'undefined' && (fileData instanceof Blob || fileData instanceof File)) {
      formData.append('file', fileData, filename);
    } else if (Buffer.isBuffer(fileData)) {
      const blob = new Blob([fileData]);
      formData.append('file', blob, filename);
    } else {
      formData.append('file', fileData, filename);
    }

    if (metadata.title) formData.append('title', metadata.title);
    if (metadata.caption) formData.append('caption', metadata.caption);
    if (metadata.platforms) {
      const plats = Array.isArray(metadata.platforms) ? metadata.platforms.join(',') : metadata.platforms;
      formData.append('platforms', plats);
    }
    if (metadata.scheduledDateTime) {
      formData.append('scheduledDateTime', metadata.scheduledDateTime);
    }
    formData.append('status', metadata.status || 'Approved for Posting');

    return this._request('/api/upload', {
      method: 'POST',
      body: formData
    });
  }
}

export default OmniPost;
