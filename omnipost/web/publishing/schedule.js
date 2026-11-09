/**
 * When a calendar entry becomes eligible to publish.
 *
 * WHY THIS EXISTS
 * ---------------
 * Every content_calendar row has carried a `scheduled_datetime` since the
 * schema was written, and nothing ever compared it to the clock. The publish
 * tick selected work purely on Status:
 *
 *     posts.filter(p => p.Status === 'Approved' || ...)
 *
 * so an entry the advocate approved on Monday for publication on Friday went
 * live on the very next heartbeat — within six hours, and in whatever order
 * the rows came back from the database. The calendar was decorative.
 *
 * The gate applies ONLY to starting work. Anything already in flight is
 * carried forward regardless of its schedule: once a media container exists on
 * Meta, refusing to advance it because the clock says "not yet" would strand a
 * half-published post, which is worse than publishing early.
 */

export const CLAIM_TTL_MS = 5 * 60 * 1000; // 5 minutes TTL

const EXCLUDED_PUBLISH_STATES = new Set(['published', 'completed', 'failed']);
const ALLOWED_STATUSES = new Set(['approved', 'scheduled', 'approved for posting']);

/**
 * @param {object} row      a content_calendar row, in either casing
 * @param {number} [now]    epoch ms
 */
export function scheduleHasArrived(row, now = Date.now()) {
  const raw = row?.['Scheduled DateTime'] ?? row?.scheduled_datetime ?? row?.scheduledDateTime;
  if (!raw) return true;

  const at = new Date(raw).getTime();
  // An unparseable date must never strand a post forever. Publishing on the
  // next tick is recoverable; silence is not.
  if (Number.isNaN(at)) return true;

  return at <= now;
}

/** True when this entry has already begun publishing somewhere. */
export function isInFlight(row) {
  const status = String(row?.Status || row?.status || '').trim().toLowerCase();
  const publishState = String(row?.publishState || row?.publish_state || '').trim().toLowerCase();
  return publishState === 'pending' || status === 'publishing';
}

/**
 * The entries one tick should advance.
 *
 * @param {object[]} posts
 * @param {number} [now]
 */
export function selectDue(posts, now = Date.now()) {
  if (!Array.isArray(posts)) return [];
  return posts.filter((row) => {
    const pubState = String(row?.publishState || row?.publish_state || '').trim().toLowerCase();

    // 1. Never re-select rows in terminal publish states
    if (EXCLUDED_PUBLISH_STATES.has(pubState)) return false;

    // 2. Concurrency guard: Skip rows actively claimed by a worker/tick
    if (pubState === 'in_flight') {
      const lastAttempt = row?.last_attempt_at || row?.lastAttemptAt;
      if (lastAttempt) {
        const lastTime = new Date(lastAttempt).getTime();
        if (!Number.isNaN(lastTime) && (now - lastTime < CLAIM_TTL_MS)) {
          return false;
        }
      } else {
        return false;
      }
    }

    if (isInFlight(row)) return true;

    const status = String(row?.Status || row?.status || '').trim().toLowerCase();
    if (!ALLOWED_STATUSES.has(status)) return false;

    return scheduleHasArrived(row, now);
  });
}
