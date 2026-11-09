/**
 * OmniPost Universal Social Automation - Persistence Layer
 *
 * Supabase PostgreSQL holds relational METADATA only (testator particulars,
 * reference ids, scrutiny stages, document descriptors + Google Drive ids).
 * Every heavy binary lives in the Google Drive vault. See
 * automation/supabase/schema.sql for the full storage contract.
 *
 * Local JSON under ./data is a write-through cache, not a second database:
 * it keeps the automation suite usable when the network or Supabase is down,
 * and it is reconciled back into Supabase as soon as the link returns.
 *
 * Failure policy: Supabase errors are reported, never swallowed. supabase-js
 * RESOLVES with an { error } object instead of throwing, so a bare try/catch
 * around these calls silently loses schema mismatches, RLS denials and failed
 * writes - which is exactly how a submission can appear saved while never
 * reaching the database.
 */

import { createClient } from '@supabase/supabase-js';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const DATA_DIR = path.join(__dirname, 'data');
const SUBMISSIONS_FILE = path.join(DATA_DIR, 'submissions.json');
const POSTS_FILE = path.join(DATA_DIR, 'posts.json');

const IST_DATE_FORMAT = {
  timeZone: 'Asia/Kolkata',
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit'
};

// Render/containers run in UTC. Without an explicit timeZone the chambers
// suite would show every submission in UTC while the practice works in IST.
function formatIst(value) {
  const d = value ? new Date(value) : new Date();
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('en-IN', IST_DATE_FORMAT);
}

// ==============================================================================
// Client bootstrap
// ==============================================================================
let SUPABASE_URL = process.env.SUPABASE_URL || '';
let SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_KEY || '';

// Local developer convenience: automation/secrets/ is git-ignored, so reading
// the key from there never risks committing it.
if (!SUPABASE_KEY) {
  const secretPath = path.join(__dirname, '../secrets/supabase.txt');
  if (fs.existsSync(secretPath)) {
    try {
      const content = fs.readFileSync(secretPath, 'utf8');
      const secretMatch = content.match(/Secret keys?\s*:\s*([^\r\n\s]+)/i);
      const projectMatch = content.match(/project id\s*:\s*([^\r\n\s]+)/i);
      if (secretMatch) SUPABASE_KEY = secretMatch[1].trim();
      if (projectMatch && !SUPABASE_URL) {
        SUPABASE_URL = `https://${projectMatch[1].trim()}.supabase.co`;
      }
    } catch (err) {
      console.warn('[Database] Could not read local Supabase secret:', err.message);
    }
  }
}

let supabase = null;
if (SUPABASE_URL && SUPABASE_KEY) {
  try {
    supabase = createClient(SUPABASE_URL, SUPABASE_KEY, { auth: { persistSession: false } });
    console.log('[Database] Supabase client initialised.');
  } catch (err) {
    console.warn('[Database] Failed to initialise Supabase client:', err.message);
  }
} else {
  console.warn('[Database] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set - running on local cache only.');
}

// Live backend state, surfaced through /api/health so a silent demotion to the
// local cache is visible instead of looking like normal operation.
const state = {
  configured: Boolean(supabase),
  reachable: false,
  schemaReady: false,
  lastError: null,
  lastErrorAt: null,
  reconciled: false
};

// PGRST205 = table missing from the schema cache, i.e. schema.sql was never
// applied. That is a provisioning problem, not a transient outage, so it is
// called out distinctly rather than logged as a generic failure.
function noteFailure(operation, error) {
  const message = error?.message || String(error);
  state.lastError = `${operation}: ${message}`;
  state.lastErrorAt = new Date().toISOString();

  if (error?.code === 'PGRST205' || /schema cache/i.test(message)) {
    state.reachable = true;
    state.schemaReady = false;
    if (!noteFailure._warnedSchema) {
      noteFailure._warnedSchema = true;
      console.error(
        '[Database] Supabase reachable but the tables do not exist. ' +
        'Apply automation/supabase/schema.sql (Supabase dashboard -> SQL Editor). ' +
        'Serving the local cache until then.'
      );
    }
    return;
  }

  state.reachable = false;
  console.error(`[Database] Supabase ${operation} failed - falling back to local cache:`, message);
}

function noteSuccess() {
  state.reachable = true;
  state.schemaReady = true;
  state.lastError = null;
}

export function getBackendStatus() {
  return {
    backend: state.schemaReady && state.reachable ? 'supabase' : 'local-cache',
    supabaseConfigured: state.configured,
    supabaseReachable: state.reachable,
    schemaReady: state.schemaReady,
    lastError: state.lastError,
    lastErrorAt: state.lastErrorAt
  };
}

/**
 * Establishes the backend state with a cheap real query.
 *
 * Without this, the status above reports whatever the last operation saw - so
 * immediately after a restart, before any request has touched the database, it
 * reported "local-cache" even when Supabase was perfectly healthy. A health
 * check or uptime monitor polling straight after a deploy would therefore read
 * a degraded backend that was not degraded.
 */
let probed = false;
let probeInFlight = null;

export function ensureProbed() {
  if (!supabase || probed) return Promise.resolve(getBackendStatus());
  if (probeInFlight) return probeInFlight;

  probeInFlight = supabase
    .from('will_submissions')
    .select('ref_id')
    .limit(1)
    .then(({ error }) => {
      if (error) noteFailure('probe', error);
      else noteSuccess();
      probed = true;
      probeInFlight = null;
      return getBackendStatus();
    })
    .catch((err) => {
      noteFailure('probe', err);
      probed = true;
      probeInFlight = null;
      return getBackendStatus();
    });

  return probeInFlight;
}

// ==============================================================================
// Local write-through cache
// ==============================================================================
function readJsonArray(file, label) {
  try {
    if (fs.existsSync(file)) {
      const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
      if (Array.isArray(parsed)) {
        return parsed.filter(item => item !== null && typeof item === 'object' && !Array.isArray(item));
      }
    }
  } catch (err) {
    console.warn(`[Database] Error reading local ${label}:`, err.message);
  }
  return [];
}

function writeJsonArray(file, list, label) {
  try {
    if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
    const cleanList = Array.isArray(list)
      ? list.filter(item => item !== null && typeof item === 'object' && !Array.isArray(item))
      : [];
    fs.writeFileSync(file, JSON.stringify(cleanList, null, 2), 'utf8');
  } catch (err) {
    console.warn(`[Database] Error writing local ${label}:`, err.message);
  }
}

export const loadLocalSubmissions = () => readJsonArray(SUBMISSIONS_FILE, 'submissions');
export const saveLocalSubmissions = (list) => writeJsonArray(SUBMISSIONS_FILE, list, 'submissions');
export const loadLocalPosts = () => readJsonArray(POSTS_FILE, 'posts');
export const saveLocalPosts = (list) => writeJsonArray(POSTS_FILE, list, 'posts');

const MEDIA_URL_KEYS = ['Public Media URL', 'public_media_url', 'mediaUrl', 'publicMediaUrl'];
const MEDIA_TYPE_KEYS = ['Media Type', 'media_type', 'mediaType'];
const LINK_KEYS = ['Link', 'link'];

/**
 * Resolves a field from incoming record against existing stored record.
 * - If incoming specifies a defined value (including "" or null), it takes precedence.
 * - null is normalized to defaultVal ('').
 * - Strings are trimmed.
 * - If incoming has no defined value among the keys, falls back to existing record.
 */
function resolveMergedField(incoming, existing, keys, defaultVal = '') {
  if (incoming && typeof incoming === 'object') {
    for (const k of keys) {
      if (incoming[k] !== undefined) {
        if (incoming[k] === null) return defaultVal;
        return typeof incoming[k] === 'string' ? incoming[k].trim() : incoming[k];
      }
    }
  }
  if (existing && typeof existing === 'object') {
    for (const k of keys) {
      if (existing[k] !== undefined && existing[k] !== null) {
        return typeof existing[k] === 'string' ? existing[k].trim() : existing[k];
      }
    }
  }
  return defaultVal;
}

// ==============================================================================
// Row <-> application shape
// ==============================================================================
function parseSizeToBytes(size) {
  if (typeof size === 'number' && Number.isFinite(size)) return Math.max(0, Math.round(size));
  if (typeof size !== 'string') return 0;
  const match = size.trim().match(/^([\d.]+)\s*(B|KB|MB|GB)?$/i);
  if (!match) return 0;
  const scale = { b: 1, kb: 1024, mb: 1024 ** 2, gb: 1024 ** 3 };
  return Math.round(parseFloat(match[1]) * (scale[(match[2] || 'b').toLowerCase()] || 1));
}

function rowToSubmission(row) {
  return {
    refId: row.ref_id,
    userId: row.user_id || null,
    date: formatIst(row.created_at),
    createdAt: row.created_at,
    fullName: row.full_name,
    parentSpouseName: row.parent_spouse_name,
    age: row.age,
    phone: row.phone,
    whatsapp: row.whatsapp || '',
    email: row.email,
    city: row.city,
    address: row.address,
    familyMembers: row.family_members || [],
    serviceType: row.service_type,
    serviceLabel: row.service_label,
    assetTypes: row.asset_types || [],
    assetDetails: row.asset_details || {},
    executorName: row.executor_name,
    specialInstructions: row.special_instructions,
    folderName: row.folder_name,
    driveFolderName: row.folder_name,
    driveFolderId: row.drive_folder_id || '',
    driveFolderUrl: row.drive_folder_url || '',
    driveProvisionState: row.drive_provision_state || 'pending',
    status: row.status,
    deficiencies: row.deficiencies || [],
    deficiencyStatus: row.deficiency_status || 'none',
    deficiencyUpdatedAt: row.deficiency_updated_at || null,
    supplementaryReceivedAt: row.supplementary_received_at || null,
    paymentStatus: row.payment_status || 'unpaid',
    paymentOrderId: row.payment_order_id || '',
    paymentId: row.payment_id || '',
    documents: (row.documents || [])
      .slice()
      .sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
      .map(doc => ({
        name: doc.file_name,
        size: doc.file_size,
        sizeBytes: doc.file_size_bytes || 0,
        mimeType: doc.mime_type || '',
        url: doc.url,
        driveFileId: doc.drive_file_id || '',
        driveUrl: doc.drive_url || row.drive_folder_url || '',
        driveFolderUrl: row.drive_folder_url || '',
        supplementary: Boolean(doc.is_supplementary),
        uploadedAt: doc.created_at || null
      }))
  };
}

function submissionToRow(record) {
  return {
    ref_id: record.refId,
    user_id: record.userId || record.user_id || null,
    full_name: record.fullName,
    parent_spouse_name: record.parentSpouseName || '',
    age: record.age || 'N/A',
    phone: record.phone,
    whatsapp: record.whatsapp || '',
    email: record.email || '',
    city: record.city || 'Andhra Pradesh / Telangana',
    address: record.address || '',
    family_members: record.familyMembers || [],
    service_type: record.serviceType,
    service_label: record.serviceLabel,
    asset_types: record.assetTypes || [],
    asset_details: record.assetDetails || {},
    executor_name: record.executorName || '',
    special_instructions: record.specialInstructions || '',
    folder_name: record.folderName,
    drive_folder_id: record.driveFolderId || '',
    drive_folder_url: record.driveFolderUrl || '',
    drive_provision_state: record.driveProvisionState || 'pending',
    status: record.status || 'New Submission',
    deficiencies: record.deficiencies || [],
    deficiency_status: record.deficiencyStatus || 'none',
    deficiency_updated_at: record.deficiencyUpdatedAt || null,
    supplementary_received_at: record.supplementaryReceivedAt || null,
    payment_status: record.paymentStatus || 'unpaid',
    payment_order_id: record.paymentOrderId || '',
    payment_id: record.paymentId || ''
  };
}

function documentRows(record) {
  const docs = Array.isArray(record.documents) ? record.documents : [];
  // The unique key is (submission_ref_id, file_name); duplicates within a single
  // submission would make the upsert fail as "affects row a second time".
  const seen = new Set();
  return docs
    .filter(d => d && d.name && !seen.has(d.name) && seen.add(d.name) !== false)
    .map(d => ({
      submission_ref_id: record.refId,
      file_name: d.name,
      file_size: typeof d.size === 'string' ? d.size : String(d.size ?? ''),
      file_size_bytes: d.sizeBytes ?? parseSizeToBytes(d.size),
      mime_type: d.mimeType || 'application/octet-stream',
      url: d.url || '',
      drive_file_id: d.driveFileId || '',
      drive_url: d.driveUrl || record.driveFolderUrl || '',
      folder_name: record.folderName || '',
      is_supplementary: Boolean(d.supplementary)
    }));
}

// ==============================================================================
// One-time reconciliation
// ==============================================================================
/**
 * Pushes locally cached submissions into Supabase the first time the database
 * is reachable with the schema in place.
 *
 * Without this, switching the source of truth to Supabase would make existing
 * records disappear from the automation suite the moment the tables are created,
 * because the database starts empty.
 */
async function reconcileLocalIntoSupabase() {
  if (!supabase || state.reconciled || !state.schemaReady) return;
  state.reconciled = true;

  const local = loadLocalSubmissions();
  if (local.length === 0) return;

  const { data: existing, error } = await supabase
    .from('will_submissions')
    .select('ref_id');
  if (error) {
    state.reconciled = false;
    noteFailure('reconcile/select', error);
    return;
  }

  const known = new Set((existing || []).map(r => r.ref_id));
  const missing = local.filter(r => r.refId && !known.has(r.refId));
  if (missing.length === 0) return;

  console.log(`[Database] Reconciling ${missing.length} cached submission(s) into Supabase.`);
  for (const record of missing) {
    await writeSubmissionToSupabase(record, 'reconcile');
  }
}

async function writeSubmissionToSupabase(record, operation) {
  const { error: subErr } = await supabase
    .from('will_submissions')
    .upsert(submissionToRow(record), { onConflict: 'ref_id' });

  if (subErr) {
    noteFailure(`${operation}/will_submissions`, subErr);
    return false;
  }

  const rows = documentRows(record);
  if (rows.length > 0) {
    const { error: docErr } = await supabase
      .from('submission_documents')
      .upsert(rows, { onConflict: 'submission_ref_id,file_name' });
    if (docErr) {
      noteFailure(`${operation}/submission_documents`, docErr);
      return false;
    }
  }

  noteSuccess();
  return true;
}

// ==============================================================================
// Will submissions
// ==============================================================================
export async function getSubmissions() {
  if (supabase) {
    const { data, error } = await supabase
      .from('will_submissions')
      .select('*, documents:submission_documents(*)')
      .order('created_at', { ascending: false });

    if (error) {
      noteFailure('getSubmissions', error);
    } else {
      noteSuccess();
      await reconcileLocalIntoSupabase();

      // Re-read only when reconciliation actually pushed rows, so the caller
      // never sees a database that looks empty purely because of first-run
      // timing.
      let rows = data;
      if ((data || []).length === 0 && loadLocalSubmissions().length > 0) {
        const retry = await supabase
          .from('will_submissions')
          .select('*, documents:submission_documents(*)')
          .order('created_at', { ascending: false });
        if (!retry.error) rows = retry.data;
      }

      const mapped = (rows || []).map(rowToSubmission);
      saveLocalSubmissions(mapped);
      return mapped;
    }
  }
  return loadLocalSubmissions();
}

export async function getSubmissionByRef(refId) {
  if (!refId) return null;
  const cleanRef = String(refId).trim().toUpperCase();

  if (supabase) {
    const { data, error } = await supabase
      .from('will_submissions')
      .select('*, documents:submission_documents(*)')
      .eq('ref_id', cleanRef)
      .maybeSingle();

    if (error) {
      noteFailure('getSubmissionByRef', error);
    } else {
      noteSuccess();
      if (data) return rowToSubmission(data);
      // A clean "not found" is authoritative only once the cache has been
      // reconciled; before that the record may exist locally and not yet
      // upstream.
    }
  }

  return loadLocalSubmissions().find(
    s => s.refId && s.refId.toUpperCase() === cleanRef
  ) || null;
}

export async function getSubmissionsByUser(userId) {
  if (!userId) return [];
  if (supabase) {
    const { data, error } = await supabase
      .from('will_submissions')
      .select('*, documents:submission_documents(*)')
      .eq('user_id', userId)
      .order('created_at', { ascending: false });

    if (error) {
      noteFailure('getSubmissionsByUser', error);
    } else {
      noteSuccess();
      return (data || []).map(rowToSubmission);
    }
  }

  return loadLocalSubmissions().filter(
    s => s.userId && s.userId === userId
  );
}

export async function saveSubmission(record) {
  // Cache first: a submission must never be lost because the network blinked.
  const current = loadLocalSubmissions();
  saveLocalSubmissions([record, ...current.filter(s => s.refId !== record.refId)]);

  if (supabase) {
    await writeSubmissionToSupabase(record, 'saveSubmission');
  }
  return record;
}

/**
 * saveSubmission, but reports whether the registry accepted the write.
 *
 * saveSubmission is cache-first and silent by design, so that a client's
 * intake is never lost. An advocate's checklist update or a client's
 * supplementary upload must instead be told when Supabase refused it: the
 * one-time reconcile only pushes records Supabase lacks, not updates, so a
 * refused update would be lost at the next restart.
 */
export async function saveSubmissionChecked(record) {
  const current = loadLocalSubmissions();
  saveLocalSubmissions([record, ...current.filter(s => s.refId !== record.refId)]);
  if (!supabase) return true;
  return writeSubmissionToSupabase(record, 'saveSubmissionChecked');
}

/**
 * Merges fields into an existing submission in BOTH stores.
 *
 * Used by the n8n callback that returns the real per-client Drive folder.
 * That callback previously wrote through the local-only helpers in server.js,
 * so the Drive ids never reached Supabase and the row kept pointing at the
 * shared vault root.
 */
export async function patchSubmission(refId, patch) {
  const current = loadLocalSubmissions();
  const target = current.find(s => s.refId === refId);
  if (!target) return null;

  Object.assign(target, patch);
  if (patch.driveFolderUrl || patch.driveFileIds) {
    (target.documents || []).forEach(doc => {
      if (patch.driveFolderUrl) {
        doc.driveFolderUrl = patch.driveFolderUrl;
        if (!doc.driveUrl || doc.driveUrl === patch.previousDriveUrl) {
          doc.driveUrl = patch.driveFolderUrl;
        }
      }
      const fileId = patch.driveFileIds?.[doc.name];
      if (fileId) doc.driveFileId = fileId;
    });
  }
  delete target.previousDriveUrl;
  saveLocalSubmissions(current);

  if (supabase) {
    await writeSubmissionToSupabase(target, 'patchSubmission');
  }
  return target;
}

export async function updateSubmissionStatus(refId, newStatus) {
  const current = loadLocalSubmissions();
  const target = current.find(s => s.refId === refId);
  if (target) {
    target.status = newStatus;
    saveLocalSubmissions(current);
  }

  if (supabase) {
    const { error } = await supabase
      .from('will_submissions')
      .update({ status: newStatus })
      .eq('ref_id', refId);
    if (error) noteFailure('updateSubmissionStatus', error);
    else noteSuccess();
  }

  return target;
}

// ==============================================================================
// Content calendar
// ==============================================================================
function rowToPost(row) {
  return {
    'Content ID': row.content_id,
    content_id: row.content_id,
    Title: row.title,
    title: row.title,
    Caption: row.caption || '',
    caption: row.caption || '',
    Platforms: row.platforms,
    platforms: row.platforms,
    'Scheduled DateTime': row.scheduled_datetime,
    scheduled_datetime: row.scheduled_datetime,
    Status: row.status,
    status: row.status,
    'Drive File ID': row.drive_file_id || '',
    drive_file_id: row.drive_file_id || '',
    'Retry Count': row.retry_count ?? 0,
    retry_count: row.retry_count ?? 0,
    'Posted At': row.posted_at || null,
    posted_at: row.posted_at || null,
    Error: row.error_log || '',
    error_log: row.error_log || '',
    'Public Media URL': row.public_media_url || '',
    public_media_url: row.public_media_url || '',
    mediaUrl: row.public_media_url || '',
    publicMediaUrl: row.public_media_url || '',
    'Media Type': row.media_type || '',
    media_type: row.media_type || '',
    mediaType: row.media_type || '',
    Link: row.link || '',
    link: row.link || '',
    platform_statuses: row.platform_statuses || {},
    platformStatuses: row.platform_statuses || {},
    publish_state: row.publish_state || 'queued',
    publishState: row.publish_state || 'queued',
    last_attempt_at: row.last_attempt_at || null,
    lastAttemptAt: row.last_attempt_at || null,
    failure_kind: row.failure_kind || null,
    failureKind: row.failure_kind || null
  };
}

export async function getPosts() {
  if (supabase) {
    const { data, error } = await supabase
      .from('content_calendar')
      .select('*')
      .order('scheduled_datetime', { ascending: false });

    if (error) {
      noteFailure('getPosts', error);
    } else if ((data || []).length > 0) {
      noteSuccess();
      const mapped = data
        .filter(r => r && typeof r === 'object' && !Array.isArray(r) && r.content_id)
        .map(rowToPost);
      saveLocalPosts(mapped);
      return mapped;
    } else {
      // Calendar seeds ship with schema.sql; an empty table means the seed
      // block has not run, so the local baseline is still the better answer.
      noteSuccess();
    }
  }
  return loadLocalPosts();
}

export async function savePost(postRecord) {
  if (!postRecord || typeof postRecord !== 'object' || Array.isArray(postRecord)) {
    throw new TypeError('savePost: postRecord must be a non-null object');
  }

  const current = loadLocalPosts();
  const id = postRecord['Content ID'] || postRecord.content_id;
  if (!id) {
    console.warn('[Database] savePost called without Content ID:', postRecord);
    return postRecord;
  }

  const existing = current.find(p => p && typeof p === 'object' && !Array.isArray(p) && (p['Content ID'] || p.content_id) === id);

  const mergedPublicMediaUrl = resolveMergedField(postRecord, existing, MEDIA_URL_KEYS, '');
  const mergedMediaType = resolveMergedField(postRecord, existing, MEDIA_TYPE_KEYS, '');
  const mergedLink = resolveMergedField(postRecord, existing, LINK_KEYS, '');
  let mergedPlatformStatuses = postRecord.platform_statuses || postRecord.platformStatuses || (existing ? (existing.platform_statuses || existing.platformStatuses || {}) : {});

  const existingPublishState = existing ? (existing.publish_state || existing.publishState || 'queued') : 'queued';
  const incomingPublishState = postRecord.publish_state || postRecord.publishState;
  const existingStatusRaw = existing ? (existing.Status || existing.status || '') : '';
  const incomingStatusRaw = postRecord.Status || postRecord.status || '';
  const existingStatusNorm = existingStatusRaw.trim().toLowerCase();
  const incomingStatusNorm = incomingStatusRaw.trim().toLowerCase();

  const isSettled = existingPublishState === 'completed' || existingStatusNorm === 'posted';
  const isInFlight = existingPublishState === 'in_flight' || existingPublishState === 'pending' || existingStatusNorm === 'publishing';
  const isFailed = existingPublishState === 'failed' || existingStatusNorm === 'failed' || existingStatusNorm === 'needs reconnect' || (existingStatusNorm === 'partially posted' && existingPublishState !== 'completed');
  const ACTIVE_EDITORIAL_STATUSES = new Set(['scheduled', 'approved', 'approved for posting']);
  const isIncomingActive = ACTIVE_EDITORIAL_STATUSES.has(incomingStatusNorm);
  const isRetry = !isSettled && !isInFlight && isFailed && isIncomingActive && (!incomingPublishState || incomingPublishState === 'queued');

  let mergedPublishState;
  let mergedStatus;
  let mergedRetryCount;
  let mergedFailureKind;
  let mergedLastAttemptAt;
  let mergedError;

  if (isSettled) {
    mergedPublishState = 'completed';
    mergedStatus = 'Posted';
    mergedRetryCount = postRecord['Retry Count'] ?? postRecord.retry_count ?? (existing ? (existing['Retry Count'] ?? existing.retry_count ?? 0) : 0);
    mergedFailureKind = null;
    mergedLastAttemptAt = existing?.last_attempt_at || existing?.lastAttemptAt || null;
    mergedError = existing?.Error || existing?.error_log || '';
  } else if (isInFlight) {
    mergedPublishState = existingPublishState;
    mergedStatus = 'Publishing';
    mergedRetryCount = postRecord['Retry Count'] ?? postRecord.retry_count ?? (existing ? (existing['Retry Count'] ?? existing.retry_count ?? 0) : 0);
    mergedFailureKind = postRecord.failure_kind || postRecord.failureKind || (existing ? (existing.failure_kind || existing.failureKind || null) : null);
    mergedLastAttemptAt = postRecord.last_attempt_at || postRecord.lastAttemptAt || (existing ? (existing.last_attempt_at || existing.lastAttemptAt || null) : null);
    mergedError = postRecord.Error || postRecord.error_log || (existing ? (existing.Error || existing.error_log || '') : '');
  } else if (isRetry) {
    mergedPublishState = 'queued';
    mergedStatus = incomingStatusRaw || 'Scheduled';
    mergedRetryCount = postRecord['Retry Count'] ?? postRecord.retry_count ?? 0;
    mergedFailureKind = null;
    mergedLastAttemptAt = null;
    mergedError = postRecord.Error || postRecord.error_log || '';

    if (mergedPlatformStatuses && typeof mergedPlatformStatuses === 'object') {
      const resetPlatformStatuses = {};
      for (const [platform, pState] of Object.entries(mergedPlatformStatuses)) {
        if (!pState || typeof pState !== 'object') continue;
        const pStatus = String(pState.status || '').toLowerCase();
        const pStateName = String(pState.state || '').toLowerCase();
        const isChanPublished = pStateName === 'completed' || pStateName === 'published' || pStatus === 'published' || pStatus === 'completed';
        const isChanFailed = pStateName === 'failed' || pStatus === 'failed' || pStateName === 'unconfigured';

        if (isChanPublished) {
          resetPlatformStatuses[platform] = pState;
        } else if (isChanFailed) {
          resetPlatformStatuses[platform] = {
            ...pState,
            state: 'queued',
            status: 'pending',
            failureKind: null,
            lastError: null,
            retryCount: 0,
            retryAfter: null
          };
        } else {
          resetPlatformStatuses[platform] = pState;
        }
      }
      mergedPlatformStatuses = resetPlatformStatuses;
    }
  } else {
    mergedPublishState = (incomingPublishState && incomingPublishState !== 'queued')
      ? incomingPublishState
      : (existingPublishState !== 'queued' ? existingPublishState : (incomingPublishState || 'queued'));
    mergedStatus = incomingStatusRaw || existingStatusRaw || 'Draft';
    if (mergedPublishState === 'completed') {
      mergedStatus = 'Posted';
    } else if (mergedPublishState === 'pending' || mergedPublishState === 'in_flight') {
      mergedStatus = 'Publishing';
    }
    mergedRetryCount = postRecord['Retry Count'] ?? postRecord.retry_count ?? (existing ? (existing['Retry Count'] ?? existing.retry_count ?? 0) : 0);
    mergedFailureKind = postRecord.failure_kind || postRecord.failureKind || (existing ? (existing.failure_kind || existing.failureKind || null) : null);
    mergedLastAttemptAt = postRecord.last_attempt_at || postRecord.lastAttemptAt || (existing ? (existing.last_attempt_at || existing.lastAttemptAt || null) : null);
    mergedError = postRecord.Error || postRecord.error_log || (existing ? (existing.Error || existing.error_log || '') : '');
  }

  const mergedPostedAt = postRecord['Posted At'] || postRecord.posted_at || (existing ? (existing['Posted At'] || existing.posted_at || null) : null);

  const normalizedRecord = {
    ...(existing || {}),
    ...postRecord,
    'Content ID': id,
    content_id: id,
    Title: postRecord.Title || postRecord.title || existing?.Title || existing?.title || '',
    title: postRecord.Title || postRecord.title || existing?.Title || existing?.title || '',
    Caption: postRecord.Caption !== undefined ? postRecord.Caption : (postRecord.caption !== undefined ? postRecord.caption : (existing?.Caption || existing?.caption || '')),
    caption: postRecord.Caption !== undefined ? postRecord.Caption : (postRecord.caption !== undefined ? postRecord.caption : (existing?.Caption || existing?.caption || '')),
    Platforms: postRecord.Platforms || postRecord.platforms || existing?.Platforms || existing?.platforms || '',
    platforms: postRecord.Platforms || postRecord.platforms || existing?.Platforms || existing?.platforms || '',
    'Scheduled DateTime': postRecord['Scheduled DateTime'] || postRecord.scheduled_datetime || postRecord.scheduledDateTime || existing?.['Scheduled DateTime'] || existing?.scheduled_datetime || new Date().toISOString(),
    scheduled_datetime: postRecord['Scheduled DateTime'] || postRecord.scheduled_datetime || postRecord.scheduledDateTime || existing?.['Scheduled DateTime'] || existing?.scheduled_datetime || new Date().toISOString(),
    Status: mergedStatus,
    status: mergedStatus,
    'Drive File ID': postRecord['Drive File ID'] !== undefined ? postRecord['Drive File ID'] : (postRecord.drive_file_id !== undefined ? postRecord.drive_file_id : (existing?.['Drive File ID'] || existing?.drive_file_id || '')),
    drive_file_id: postRecord['Drive File ID'] !== undefined ? postRecord['Drive File ID'] : (postRecord.drive_file_id !== undefined ? postRecord.drive_file_id : (existing?.['Drive File ID'] || existing?.drive_file_id || '')),
    'Public Media URL': mergedPublicMediaUrl,
    public_media_url: mergedPublicMediaUrl,
    mediaUrl: mergedPublicMediaUrl,
    publicMediaUrl: mergedPublicMediaUrl,
    'Media Type': mergedMediaType,
    media_type: mergedMediaType,
    mediaType: mergedMediaType,
    Link: mergedLink,
    link: mergedLink,
    platform_statuses: mergedPlatformStatuses,
    platformStatuses: mergedPlatformStatuses,
    publish_state: mergedPublishState,
    publishState: mergedPublishState,
    last_attempt_at: mergedLastAttemptAt,
    lastAttemptAt: mergedLastAttemptAt,
    failure_kind: mergedFailureKind,
    failureKind: mergedFailureKind,
    'Retry Count': mergedRetryCount,
    retry_count: mergedRetryCount,
    'Posted At': mergedPostedAt,
    posted_at: mergedPostedAt,
    Error: mergedError,
    error_log: mergedError
  };

  saveLocalPosts([
    normalizedRecord,
    ...current.filter(p => p && typeof p === 'object' && !Array.isArray(p) && (p['Content ID'] || p.content_id) !== id)
  ]);

  if (supabase) {
    const dbRow = {
      content_id: id,
      title: normalizedRecord.Title,
      caption: normalizedRecord.Caption,
      platforms: normalizedRecord.Platforms,
      scheduled_datetime: normalizedRecord['Scheduled DateTime'],
      status: normalizedRecord.Status,
      drive_file_id: normalizedRecord['Drive File ID'],
      public_media_url: normalizedRecord.public_media_url,
      media_type: normalizedRecord.media_type,
      link: normalizedRecord.link,
      platform_statuses: normalizedRecord.platform_statuses,
      publish_state: normalizedRecord.publish_state,
      last_attempt_at: normalizedRecord.last_attempt_at,
      failure_kind: normalizedRecord.failure_kind,
      retry_count: normalizedRecord.retry_count,
      posted_at: normalizedRecord.posted_at,
      error_log: normalizedRecord.error_log
    };

    const { error } = await supabase
      .from('content_calendar')
      .upsert(dbRow, { onConflict: 'content_id' });
    if (error) noteFailure('savePost', error);
    else noteSuccess();
  }

  return normalizedRecord;
}

/**
 * Reads the resumable publish state for one calendar entry.
 *
 * Returned to the dispatcher so it can resume a publish that was interrupted -
 * on Render the container can sleep between creating a media container and
 * publishing it. See automation/web/publishing/state.js.
 */
export async function getPublishState(contentId) {
  if (supabase) {
    const { data, error } = await supabase
      .from('content_calendar')
      .select('content_id, platforms, platform_statuses, publish_state, retry_count, last_attempt_at, failure_kind')
      .eq('content_id', contentId)
      .maybeSingle();
    if (error) noteFailure('getPublishState', error);
    else if (data) { noteSuccess(); return data; }
  }

  const local = loadLocalPosts().find(p => p && typeof p === 'object' && !Array.isArray(p) && (p['Content ID'] || p.content_id) === contentId);
  if (!local) return null;
  return {
    content_id: contentId,
    platforms: local.Platforms || local.platforms || '',
    platform_statuses: local.platform_statuses || local.platformStatuses || {},
    publish_state: local.publish_state || local.publishState || 'queued',
    retry_count: local['Retry Count'] ?? local.retry_count ?? 0,
    last_attempt_at: local.last_attempt_at || local.lastAttemptAt || null,
    failure_kind: local.failure_kind || local.failureKind || null
  };
}

/**
 * Persists per-channel publish state. This is the durable half of the
 * idempotency guarantee: the container id recorded here is what a later pass
 * checks before publishing, so a crash cannot cause a second post.
 */
export async function savePublishState(contentId, platformStates, rollup) {
  const posts = loadLocalPosts();
  const target = posts.find(p => p && typeof p === 'object' && !Array.isArray(p) && (p['Content ID'] || p.content_id) === contentId);
  if (target) {
    target.platform_statuses = platformStates;
    target.platformStatuses = platformStates;
    target.publish_state = rollup.publishState;
    target.publishState = rollup.publishState;
    target.Status = rollup.status || target.Status;
    target.status = rollup.status || target.status;
    target.failure_kind = rollup.failureKind || null;
    target.failureKind = rollup.failureKind || null;
    target.last_attempt_at = new Date().toISOString();
    target.lastAttemptAt = target.last_attempt_at;
    saveLocalPosts(posts);
  }

  if (supabase) {
    const { error } = await supabase
      .from('content_calendar')
      .update({
        platform_statuses: platformStates,
        publish_state: rollup.publishState,
        status: rollup.status,
        failure_kind: rollup.failureKind || null,
        last_attempt_at: new Date().toISOString(),
        ...(rollup.publishState === 'completed' ? { posted_at: new Date().toISOString() } : {})
      })
      .eq('content_id', contentId);
    if (error) noteFailure('savePublishState', error);
    else noteSuccess();
  }

  return platformStates;
}

/**
 * Bulk-syncs the calendar returned by n8n (whose source of truth is the
 * Google Sheet) into both stores in one round trip.
 */
export async function savePosts(list) {
  if (!Array.isArray(list) || list.length === 0) return [];

  const currentLocal = loadLocalPosts();
  const existingMap = new Map();
  for (const post of currentLocal) {
    if (!post || typeof post !== 'object' || Array.isArray(post)) continue;
    const id = post['Content ID'] || post.content_id;
    if (id) existingMap.set(id, { ...post });
  }

  if (supabase) {
    try {
      const { data: dbRows, error } = await supabase
        .from('content_calendar')
        .select('*');
      if (!error && Array.isArray(dbRows)) {
        for (const row of dbRows) {
          if (!row || typeof row !== 'object' || Array.isArray(row) || !row.content_id) continue;
          const mapped = rowToPost(row);
          const current = existingMap.get(row.content_id);
          if (current) {
            const mergedPublicMediaUrl = resolveMergedField(current, mapped, MEDIA_URL_KEYS, '');
            const mergedMediaType = resolveMergedField(current, mapped, MEDIA_TYPE_KEYS, '');
            const mergedLink = resolveMergedField(current, mapped, LINK_KEYS, '');
            existingMap.set(row.content_id, {
              ...mapped,
              ...current,
              platform_statuses: current.platform_statuses || current.platformStatuses || mapped.platform_statuses,
              platformStatuses: current.platformStatuses || current.platform_statuses || mapped.platformStatuses,
              publish_state: current.publish_state || current.publishState || mapped.publish_state,
              publishState: current.publishState || current.publish_state || mapped.publishState,
              public_media_url: mergedPublicMediaUrl,
              'Public Media URL': mergedPublicMediaUrl,
              mediaUrl: mergedPublicMediaUrl,
              publicMediaUrl: mergedPublicMediaUrl,
              media_type: mergedMediaType,
              'Media Type': mergedMediaType,
              mediaType: mergedMediaType,
              link: mergedLink,
              Link: mergedLink
            });
          } else {
            existingMap.set(row.content_id, mapped);
          }
        }
      }
    } catch (err) {
      console.warn('[Database] Could not fetch existing content_calendar for merge:', err.message);
    }
  }

  const mergedList = [];
  const processedIds = new Set();

  for (const incoming of list) {
    if (!incoming || typeof incoming !== 'object' || Array.isArray(incoming)) continue;
    const id = incoming['Content ID'] || incoming.content_id;
    if (!id) {
      continue;
    }
    processedIds.add(id);
    const existing = existingMap.get(id);

    if (!existing) {
      const newMediaUrl = resolveMergedField(incoming, null, MEDIA_URL_KEYS, '');
      const newMediaType = resolveMergedField(incoming, null, MEDIA_TYPE_KEYS, '');
      const newLink = resolveMergedField(incoming, null, LINK_KEYS, '');
      const normalizedNew = {
        ...incoming,
        'Content ID': id,
        content_id: id,
        'Public Media URL': newMediaUrl,
        public_media_url: newMediaUrl,
        mediaUrl: newMediaUrl,
        publicMediaUrl: newMediaUrl,
        'Media Type': newMediaType,
        media_type: newMediaType,
        mediaType: newMediaType,
        Link: newLink,
        link: newLink
      };
      mergedList.push(normalizedNew);
      continue;
    }

    const existingPlatformStatuses = existing.platform_statuses || existing.platformStatuses || {};
    const incomingPlatformStatuses = incoming.platform_statuses || incoming.platformStatuses || {};
    let mergedPlatformStatuses = Object.keys(incomingPlatformStatuses).length > 0
      ? { ...existingPlatformStatuses, ...incomingPlatformStatuses }
      : existingPlatformStatuses;

    const existingPublishState = existing.publish_state || existing.publishState || 'queued';
    const incomingPublishState = incoming.publish_state || incoming.publishState;
    const existingStatusRaw = existing.Status || existing.status || '';
    const incomingStatusRaw = incoming.Status || incoming.status || '';
    const existingStatusNorm = existingStatusRaw.trim().toLowerCase();
    const incomingStatusNorm = incomingStatusRaw.trim().toLowerCase();

    // 1. Settled post protection: never regress posted posts
    const isSettled = existingPublishState === 'completed' || existingStatusNorm === 'posted';

    // 2. In-flight protection: never disrupt active publishing
    const isInFlight = existingPublishState === 'in_flight' || existingPublishState === 'pending' || existingStatusNorm === 'publishing';

    // 3. Failure detection
    const isFailed = existingPublishState === 'failed' || existingStatusNorm === 'failed' || existingStatusNorm === 'needs reconnect' || (existingStatusNorm === 'partially posted' && existingPublishState !== 'completed');

    // 4. Active editorial statuses (matching schedule.js ALLOWED_STATUSES)
    const ACTIVE_EDITORIAL_STATUSES = new Set(['scheduled', 'approved', 'approved for posting']);
    const isIncomingActive = ACTIVE_EDITORIAL_STATUSES.has(incomingStatusNorm);

    // 5. Intentional retry trigger
    const isRetry = !isSettled && !isInFlight && isFailed && isIncomingActive && (!incomingPublishState || incomingPublishState === 'queued');

    let mergedPublishState;
    let mergedStatus;
    let mergedRetryCount;
    let mergedFailureKind;
    let mergedErrorLog;
    let mergedLastAttemptAt;

    if (isSettled) {
      mergedPublishState = 'completed';
      mergedStatus = 'Posted';
      mergedRetryCount = incoming['Retry Count'] ?? incoming.retry_count ?? existing['Retry Count'] ?? existing.retry_count ?? 0;
      mergedFailureKind = null;
      mergedErrorLog = existing.Error || existing.error_log || '';
      mergedLastAttemptAt = existing.last_attempt_at || existing.lastAttemptAt || null;
    } else if (isInFlight) {
      mergedPublishState = existingPublishState;
      mergedStatus = 'Publishing';
      mergedRetryCount = incoming['Retry Count'] ?? incoming.retry_count ?? existing['Retry Count'] ?? existing.retry_count ?? 0;
      mergedFailureKind = incoming.failure_kind || incoming.failureKind || existing.failure_kind || existing.failureKind || null;
      mergedErrorLog = incoming.Error || incoming.error_log || existing.Error || existing.error_log || '';
      mergedLastAttemptAt = incoming.last_attempt_at || incoming.lastAttemptAt || existing.last_attempt_at || existing.lastAttemptAt || null;
    } else if (isRetry) {
      // Unlatch state machine for retry
      mergedPublishState = 'queued';
      mergedStatus = incomingStatusRaw || 'Scheduled';
      mergedRetryCount = incoming['Retry Count'] ?? incoming.retry_count ?? 0;
      mergedFailureKind = null;
      mergedErrorLog = incoming.Error || incoming.error_log || '';
      mergedLastAttemptAt = null;

      // Reset failed channels while strictly preserving completed channels
      if (mergedPlatformStatuses && typeof mergedPlatformStatuses === 'object') {
        const resetPlatformStatuses = {};
        for (const [platform, pState] of Object.entries(mergedPlatformStatuses)) {
          if (!pState || typeof pState !== 'object') continue;
          const pStatus = String(pState.status || '').toLowerCase();
          const pStateName = String(pState.state || '').toLowerCase();
          const isChanPublished = pStateName === 'completed' || pStateName === 'published' || pStatus === 'published' || pStatus === 'completed';
          const isChanFailed = pStateName === 'failed' || pStatus === 'failed' || pStateName === 'unconfigured';

          if (isChanPublished) {
            resetPlatformStatuses[platform] = pState;
          } else if (isChanFailed) {
            resetPlatformStatuses[platform] = {
              ...pState,
              state: 'queued',
              status: 'pending',
              failureKind: null,
              lastError: null,
              retryCount: 0,
              retryAfter: null
            };
          } else {
            resetPlatformStatuses[platform] = pState;
          }
        }
        mergedPlatformStatuses = resetPlatformStatuses;
      }
    } else {
      mergedPublishState = (incomingPublishState && incomingPublishState !== 'queued')
        ? incomingPublishState
        : (existingPublishState !== 'queued' ? existingPublishState : (incomingPublishState || 'queued'));

      mergedStatus = incomingStatusRaw || existingStatusRaw || 'Draft';
      if (mergedPublishState === 'completed') {
        mergedStatus = 'Posted';
      } else if (mergedPublishState === 'pending' || mergedPublishState === 'in_flight') {
        mergedStatus = 'Publishing';
      }

      mergedRetryCount = incoming['Retry Count'] ?? incoming.retry_count ?? existing['Retry Count'] ?? existing.retry_count ?? 0;
      mergedFailureKind = incoming.failure_kind || incoming.failureKind || existing.failure_kind || existing.failureKind || null;
      mergedErrorLog = incoming.Error || incoming.error_log || existing.Error || existing.error_log || '';
      mergedLastAttemptAt = incoming.last_attempt_at || incoming.lastAttemptAt || existing.last_attempt_at || existing.lastAttemptAt || null;
    }

    const mergedPublicMediaUrl = resolveMergedField(incoming, existing, MEDIA_URL_KEYS, '');
    const mergedMediaType = resolveMergedField(incoming, existing, MEDIA_TYPE_KEYS, '');
    const mergedLink = resolveMergedField(incoming, existing, LINK_KEYS, '');
    const mergedPostedAt = incoming['Posted At'] || incoming.posted_at || existing['Posted At'] || existing.posted_at || null;

    const merged = {
      ...existing,
      ...incoming,
      'Content ID': id,
      content_id: id,
      Title: incoming.Title || incoming.title || existing.Title || existing.title || '',
      title: incoming.Title || incoming.title || existing.Title || existing.title || '',
      Caption: incoming.Caption !== undefined ? incoming.Caption : (incoming.caption !== undefined ? incoming.caption : (existing.Caption || existing.caption || '')),
      caption: incoming.Caption !== undefined ? incoming.Caption : (incoming.caption !== undefined ? incoming.caption : (existing.Caption || existing.caption || '')),
      Platforms: incoming.Platforms || incoming.platforms || existing.Platforms || existing.platforms || '',
      platforms: incoming.Platforms || incoming.platforms || existing.Platforms || existing.platforms || '',
      'Scheduled DateTime': incoming['Scheduled DateTime'] || incoming.scheduled_datetime || incoming.scheduledDateTime || existing['Scheduled DateTime'] || existing.scheduled_datetime || new Date().toISOString(),
      scheduled_datetime: incoming['Scheduled DateTime'] || incoming.scheduled_datetime || incoming.scheduledDateTime || existing['Scheduled DateTime'] || existing.scheduled_datetime || new Date().toISOString(),
      Status: mergedStatus,
      status: mergedStatus,
      'Drive File ID': incoming['Drive File ID'] !== undefined ? incoming['Drive File ID'] : (incoming.drive_file_id !== undefined ? incoming.drive_file_id : (existing['Drive File ID'] || existing.drive_file_id || '')),
      drive_file_id: incoming['Drive File ID'] !== undefined ? incoming['Drive File ID'] : (incoming.drive_file_id !== undefined ? incoming.drive_file_id : (existing['Drive File ID'] || existing.drive_file_id || '')),
      'Public Media URL': mergedPublicMediaUrl,
      public_media_url: mergedPublicMediaUrl,
      mediaUrl: mergedPublicMediaUrl,
      publicMediaUrl: mergedPublicMediaUrl,
      'Media Type': mergedMediaType,
      media_type: mergedMediaType,
      mediaType: mergedMediaType,
      Link: mergedLink,
      link: mergedLink,
      platform_statuses: mergedPlatformStatuses,
      platformStatuses: mergedPlatformStatuses,
      publish_state: mergedPublishState,
      publishState: mergedPublishState,
      last_attempt_at: mergedLastAttemptAt,
      lastAttemptAt: mergedLastAttemptAt,
      failure_kind: mergedFailureKind,
      failureKind: mergedFailureKind,
      'Retry Count': mergedRetryCount,
      retry_count: mergedRetryCount,
      'Posted At': mergedPostedAt,
      posted_at: mergedPostedAt,
      Error: mergedErrorLog,
      error_log: mergedErrorLog
    };

    mergedList.push(merged);
  }

  for (const [id, existingPost] of existingMap.entries()) {
    if (!processedIds.has(id)) {
      mergedList.push(existingPost);
    }
  }

  saveLocalPosts(mergedList);

  if (supabase) {
    const rows = mergedList
      .filter(p => p && typeof p === 'object' && !Array.isArray(p) && (p['Content ID'] || p.content_id))
      .map(p => ({
        content_id: p['Content ID'] || p.content_id,
        title: p.Title || p.title || '',
        caption: p.Caption || p.caption || '',
        platforms: p.Platforms || p.platforms || '',
        scheduled_datetime: p['Scheduled DateTime'] || p.scheduled_datetime || new Date().toISOString(),
        status: p.Status || p.status || 'Draft',
        drive_file_id: p['Drive File ID'] || p.drive_file_id || '',
        public_media_url: p.public_media_url ?? p['Public Media URL'] ?? p.mediaUrl ?? p.publicMediaUrl ?? '',
        media_type: p.media_type ?? p['Media Type'] ?? p.mediaType ?? '',
        link: p.link ?? p.Link ?? '',
        platform_statuses: p.platform_statuses || p.platformStatuses || {},
        publish_state: p.publish_state || p.publishState || 'queued',
        last_attempt_at: p.last_attempt_at || p.lastAttemptAt || null,
        failure_kind: p.failure_kind || p.failureKind || null,
        retry_count: p['Retry Count'] ?? p.retry_count ?? 0,
        posted_at: p['Posted At'] || p.posted_at || null,
        error_log: p.Error || p.error_log || ''
      }));
    if (rows.length > 0) {
      const { error } = await supabase
        .from('content_calendar')
        .upsert(rows, { onConflict: 'content_id' });
      if (error) noteFailure('savePosts', error);
      else noteSuccess();
    }
  }
  return mergedList;
}

export { supabase, parseSizeToBytes, formatIst, resolveMergedField, MEDIA_URL_KEYS, MEDIA_TYPE_KEYS, LINK_KEYS };
