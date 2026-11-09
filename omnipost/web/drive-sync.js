/**
 * Keeps each client's Drive folder in step with the documents on the portal's
 * disk when n8n cannot take them at the moment they arrive.
 *
 * On Render's free tier n8n sleeps after 15 idle minutes and takes minutes to
 * wake, answering 502 meanwhile. A will submission or a supplementary upload
 * that lands then used to get exactly one attempt: a first submission waited,
 * "pending", for someone to call /api/drive/provision-pending, and a
 * supplementary upload was never retried at all. Either way the documents sat
 * only on this container's ephemeral disk, where the next deploy erases them.
 *
 * Here every failed sync is remembered and retried with backoff; the first
 * failed call is also what wakes n8n. Work for one client is serialised, and
 * each attempt re-reads the record, so a retry queued behind a slow first
 * provisioning sees the folder it created instead of creating a second one.
 *
 * Outstanding work is held in memory on purpose. On Render the files live
 * only on this container's disk, so they and this list are lost together; a
 * restart must not "provision" a record whose documents are already gone into
 * an empty folder that would hide the loss. At startup, only records whose
 * files are still on disk are picked up again.
 */
export function createDriveSync({
  getRecord,          // (refId) => latest record, or null
  listRecords,        // () => all records (read once, at the first sweep)
  provision,          // (record, { onlyFiles }) => true when Drive has them
  needsProvisioning,  // (record) => true while it has no folder of its own
  hasFilesOnDisk,     // (record) => true when its documents can still be sent
  baseDelayMs = 3 * 60 * 1000,
  maxDelayMs = 6 * 60 * 60 * 1000,
  now = Date.now,
  log = console
}) {
  const chains = new Map();        // refId -> tail of that client's queue
  const outstanding = new Map();   // refId -> { attempts, nextAt }
  const unsyncedFiles = new Map(); // refId -> Set of supplementary disk names
  let seeded = false;
  let sweeping = false;

  function serialised(refId, task) {
    const run = (chains.get(refId) || Promise.resolve()).then(task, task);
    const tail = run.catch(() => {});
    chains.set(refId, tail);
    tail.then(() => { if (chains.get(refId) === tail) chains.delete(refId); });
    return run;
  }

  function failed(refId, error) {
    const attempts = (outstanding.get(refId)?.attempts || 0) + 1;
    const delay = Math.min(baseDelayMs * 2 ** (attempts - 1), maxDelayMs);
    outstanding.set(refId, { attempts, nextAt: now() + delay });
    return { ok: false, error };
  }

  async function attempt(refId) {
    const record = await getRecord(refId);
    if (!record) {
      outstanding.delete(refId);
      unsyncedFiles.delete(refId);
      return { ok: false, error: 'record not found' };
    }
    try {
      if (needsProvisioning(record)) {
        // A first provisioning sends every file on disk, supplementary ones
        // included, so nothing queued for this client is left over.
        if (!(await provision(record, {}))) return failed(refId, 'n8n did not confirm a folder');
        unsyncedFiles.delete(refId);
      } else if (unsyncedFiles.get(refId)?.size) {
        const names = [...unsyncedFiles.get(refId)];
        if (!(await provision(record, { onlyFiles: names }))) return failed(refId, 'n8n did not confirm the upload');
        // Files that arrived while this upload ran stay queued; their own
        // sync() call is already waiting behind this one.
        const left = unsyncedFiles.get(refId);
        names.forEach((name) => left?.delete(name));
        if (left && !left.size) unsyncedFiles.delete(refId);
      }
      if (unsyncedFiles.has(refId)) outstanding.set(refId, { attempts: 0, nextAt: 0 });
      else outstanding.delete(refId);
      return { ok: true };
    } catch (err) {
      return failed(refId, err.message);
    }
  }

  /** Sends a client's outstanding documents to Drive now, in turn with any other attempt for them. */
  function sync(refId, { onlyFiles = [] } = {}) {
    if (onlyFiles.length) {
      const set = unsyncedFiles.get(refId) || new Set();
      onlyFiles.forEach((name) => set.add(name));
      unsyncedFiles.set(refId, set);
    }
    return serialised(refId, () => attempt(refId));
  }

  /** Retries whatever is due. Touches n8n only when something is outstanding. */
  async function sweep() {
    if (sweeping) return { attempted: 0, ok: 0 };
    sweeping = true;
    try {
      if (!seeded) {
        for (const record of await listRecords()) {
          if (!needsProvisioning(record) || outstanding.has(record.refId)) continue;
          if (hasFilesOnDisk(record)) outstanding.set(record.refId, { attempts: 0, nextAt: 0 });
          else log.warn(`[Drive] ${record.refId} is pending but its documents are no longer on this server - ask the client to upload them again.`);
        }
        seeded = true;
      }
      const due = [...outstanding].filter(([, s]) => s.nextAt <= now()).map(([refId]) => refId);
      let ok = 0;
      for (const refId of due) {
        const result = await sync(refId);
        if (result.ok) ok += 1;
        else log.warn(`[Drive] ${refId}: still not in Drive (${result.error}); next retry in ${Math.round((outstanding.get(refId)?.nextAt - now()) / 60000)} min.`);
      }
      if (ok) log.log(`[Drive] Retry sweep: ${ok}/${due.length} client(s) now in Drive.`);
      return { attempted: due.length, ok };
    } finally {
      sweeping = false;
    }
  }

  return {
    sync,
    sweep,
    status: () => ({
      outstanding: [...outstanding.keys()],
      unsyncedFiles: Object.fromEntries([...unsyncedFiles].map(([k, v]) => [k, [...v]]))
    })
  };
}
