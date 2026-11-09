import fs from 'fs';
import axios from 'axios';
import FormData from 'form-data';

// Failures where the candidate never took the request, so the next one may.
const FALL_THROUGH = new Set(['ECONNREFUSED', 'ENOTFOUND', 'ECONNABORTED', 'ETIMEDOUT', 'EAI_AGAIN']);

// n8n's Header Auth credential on each workflow webhook must use this name.
export const WEBHOOK_KEY_HEADER = 'X-VBL-Webhook-Key';

/**
 * Builds sendToN8n(endpoint, options), which tries each candidate base URL in
 * turn. `options.body` may be a factory from multipartBody(): a multipart body
 * is a one-shot stream, and handing the same one to the next candidate after a
 * refusal sends it nothing, so that request hangs until its timeout. On Render
 * that was every provisioning call, because the internal address always
 * refuses and the public one is last.
 */
export function createN8nClient({ candidates, secret = '', http = axios }) {
  return async function sendToN8n(endpoint, options = {}) {
    const { body, ...request } = options;
    let lastError;
    for (const base of candidates()) {
      const part = typeof body === 'function' ? body() : null;
      const dataPayload = part
        ? part.form
        : (request.data !== undefined ? request.data : (body !== undefined ? body : undefined));
      try {
        // Default first so the caller's timeout wins (preflight needs its 4s probe).
        const response = await http({
          timeout: 60000,
          // n8n webhooks never redirect, and allowing it costs the whole body:
          // with redirects on, axios sends through follow-redirects, which
          // keeps every byte written so it can replay the body elsewhere.
          // Measured in a 512 MB container: forwarding one 200 MB document
          // held 200 MB of the portal's memory for the 2.5 minutes n8n took
          // to answer, and three concurrent 80 MB submissions reached 330 MB.
          // With 0, axios uses Node's own http/https and the files stream.
          maxRedirects: 0,
          url: `${base}${endpoint}`,
          ...request,
          ...(dataPayload !== undefined ? { data: dataPayload } : {}),
          headers: {
            ...(request.headers || {}),
            ...(part ? part.form.getHeaders() : {}),
            ...(secret ? { [WEBHOOK_KEY_HEADER]: secret } : {})
          }
        });
        return response.data;
      } catch (err) {
        lastError = err;
        if (FALL_THROUGH.has(err.code)) continue;
        throw err;
      } finally {
        part?.release();
      }
    }
    throw lastError;
  };
}

/**
 * A body factory for sendToN8n. Each call opens its own file streams, and
 * release() closes whichever of them a failed attempt left open.
 *
 * @param {Record<string,string>} fields
 * @param {{field:string, path:string, filename:string, size:number, contentType?:string}[]} files
 */
export function multipartBody(fields, files) {
  return () => {
    const form = new FormData();
    for (const [name, value] of Object.entries(fields)) form.append(name, value ?? '');
    const streams = files.map((file) => fs.createReadStream(file.path));
    files.forEach((file, i) => {
      form.append(file.field, streams[i], {
        filename: file.filename,
        knownLength: file.size,
        ...(file.contentType ? { contentType: file.contentType } : {})
      });
    });
    return { form, release: () => streams.forEach((s) => s.destroy()) };
  };
}
