import React, { useState } from 'react';

/**
 * Start Engine — pre-flight diagnostics and one-click multi-channel publishing.
 *
 * Two deliberate behaviours:
 *
 *  1. The publish action is DISABLED until the engine is armed. Arming requires
 *     the four core channels plus Supabase; without persistence a publish
 *     cannot be made idempotent, so allowing it would risk duplicate posts on
 *     a client-facing feed.
 *
 *  2. Every channel is listed with its real state, including the ones that are
 *     down or unconfigured. Hiding an unavailable channel would imply the
 *     chambers has reach it does not have.
 */

const PROGRESS_STEPS = [
  'Waking cloud container...',
  'Checking Supabase...',
  'Checking Drive Vault...',
  'Checking Facebook...',
  'Checking Instagram...',
  'Checking Threads...',
  'Checking YouTube...',
  'Checking LinkedIn...',
  'Checking Pinterest...'
];

const STATUS_TONE = {
  READY: { bg: '#ECFDF5', fg: '#065F46', br: '#A7F3D0', dot: '#10B981' },
  DEGRADED: { bg: '#FFFBEB', fg: '#92400E', br: '#FDE68A', dot: '#F59E0B' },
  TIMEOUT: { bg: '#FFFBEB', fg: '#92400E', br: '#FDE68A', dot: '#F59E0B' },
  AUTH_EXPIRED: { bg: '#FEF2F2', fg: '#991B1B', br: '#FCA5A5', dot: '#EF4444' },
  PERMISSION_DENIED: { bg: '#FEF2F2', fg: '#991B1B', br: '#FCA5A5', dot: '#EF4444' },
  ERROR: { bg: '#FEF2F2', fg: '#991B1B', br: '#FCA5A5', dot: '#EF4444' },
  NEEDS_CONFIGURATION: { bg: '#F1F5F9', fg: '#475569', br: '#E2E8F0', dot: '#94A3B8' },
  CONFIGURATION_ERROR: { bg: '#FEF2F2', fg: '#991B1B', br: '#FCA5A5', dot: '#EF4444' },
  DISABLED: { bg: '#F1F5F9', fg: '#475569', br: '#E2E8F0', dot: '#94A3B8' },
  NETWORK_ERROR: { bg: '#FEF2F2', fg: '#991B1B', br: '#FCA5A5', dot: '#EF4444' }
};

const CHANNEL_LABELS = {
  facebook: 'Facebook',
  instagram: 'Instagram',
  threads: 'Threads',
  youtube: 'YouTube',
  linkedin: 'LinkedIn',
  pinterest: 'Pinterest'
};

const PUBLISH_TONE = {
  PUBLISHED: '#065F46',
  ALREADY_PUBLISHED: '#0369A1',
  PROCESSING: '#92400E',
  SKIPPED: '#64748B',
  FAILED: '#991B1B'
};

export default function EnginePanel({ authToken, posts = [], onToast }) {
  const [checking, setChecking] = useState(false);
  const [step, setStep] = useState('');
  const [report, setReport] = useState(null);
  const [publishing, setPublishing] = useState(false);
  const [publishResults, setPublishResults] = useState(null);
  const [selectedId, setSelectedId] = useState('');

  const headers = () => ({
    Authorization: `Bearer ${authToken || sessionStorage.getItem('omnipost_auth_token') || sessionStorage.getItem('vbl_automation_token') || ''}`
  });

  async function startEngine() {
    setChecking(true);
    setReport(null);
    setPublishResults(null);

    // Cosmetic only: the real work is one request. The steps exist so a ~50s
    // cold start does not look like a hang.
    let i = 0;
    setStep(PROGRESS_STEPS[0]);
    const ticker = setInterval(() => {
      i = Math.min(i + 1, PROGRESS_STEPS.length - 1);
      setStep(PROGRESS_STEPS[i]);
    }, 700);

    try {
      const res = await fetch('/api/engine/preflight', { headers: headers() });
      if (res.status === 401) throw new Error('Session expired — sign in again.');
      const data = await res.json();
      setReport(data);
      onToast?.(
        data.armed ? 'Engine armed — GREEN SIGNAL' : 'Engine not armed — see diagnostics',
        data.armed ? 'success' : 'error'
      );
    } catch (err) {
      setReport({ signal: 'NOT_GREEN', armed: false, error: err.message });
      onToast?.(err.message || 'Pre-flight failed', 'error');
    } finally {
      clearInterval(ticker);
      setStep('');
      setChecking(false);
    }
  }

  async function publishAll() {
    if (!selectedId) {
      onToast?.('Choose a calendar entry first', 'error');
      return;
    }
    setPublishing(true);
    setPublishResults(null);
    try {
      const res = await fetch('/api/publish/batch', {
        method: 'POST',
        headers: { ...headers(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contentId: selectedId,
          // Only channels the pre-flight actually found ready.
          platforms: report?.readyToPublish?.length ? report.readyToPublish : undefined
        })
      });
      const data = await res.json();
      if (!res.ok || data.success === false) throw new Error(data.message || `HTTP ${res.status}`);
      setPublishResults(data);

      const s = data.summary || {};
      onToast?.(
        `Published ${s.published || 0}/${s.requested || 0}` +
        (s.failed ? ` — ${s.failed} failed` : '') +
        (s.skipped ? `, ${s.skipped} skipped` : ''),
        s.failed ? 'error' : 'success'
      );
    } catch (err) {
      onToast?.(err.message || 'Batch publish failed', 'error');
    } finally {
      setPublishing(false);
    }
  }

  const armed = report?.armed === true;
  const selectiveArmed = report?.selectiveArmed || (report?.readyToPublish && report.readyToPublish.length > 0);
  const canPublish = armed || selectiveArmed;
  const readyCount = report?.readyToPublish?.length || 0;
  const channels = report?.channels || {};

  return (
    <div style={{
      background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '12px',
      padding: '16px', marginBottom: '16px'
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: '13px', fontWeight: 700, color: '#0F2942' }}>Publishing Engine</div>
          <div style={{ fontSize: '12px', color: '#64748B' }}>
            {report
              ? (armed ? 'All core channels operational' : (selectiveArmed ? `${readyCount} channel(s) ready for selective publishing` : 'Core dependencies unavailable'))
              : 'Run pre-flight diagnostics before publishing'}
          </div>
        </div>

        <button
          type="button"
          onClick={startEngine}
          disabled={checking}
          style={{
            background: checking ? '#94A3B8' : '#0F2942', color: '#FFFFFF',
            border: 'none', borderRadius: '8px', padding: '10px 18px',
            fontSize: '13px', fontWeight: 700, letterSpacing: '0.03em',
            cursor: checking ? 'not-allowed' : 'pointer'
          }}
        >
          {checking ? 'CHECKING…' : 'START ENGINE'}
        </button>
      </div>

      {/* Progress */}
      {checking && (
        <div style={{
          marginTop: '12px', padding: '10px 12px', background: '#F8FAFC',
          border: '1px solid #E2E8F0', borderRadius: '8px',
          fontSize: '12px', color: '#475569', fontFamily: 'ui-monospace, monospace'
        }}>
          {step}
        </div>
      )}

      {/* Signal banner */}
      {report && !checking && (
        <div style={{
          marginTop: '12px', padding: '12px 14px', borderRadius: '10px',
          background: armed ? '#ECFDF5' : (selectiveArmed ? '#F0FDF4' : '#FEF2F2'),
          border: `1px solid ${armed ? '#A7F3D0' : (selectiveArmed ? '#86EFAC' : '#FCA5A5')}`
        }}>
          <div style={{
            fontSize: '14px', fontWeight: 800, letterSpacing: '0.04em',
            color: armed ? '#065F46' : (selectiveArmed ? '#15803D' : '#991B1B')
          }}>
            {armed ? 'ENGINE FULLY ARMED · GREEN SIGNAL' : (selectiveArmed ? `SELECTIVE PUBLISHING READY · ${readyCount} CHANNEL(S) ACTIVE` : 'ENGINE NOT ARMED · NO CHANNELS READY')}
          </div>
          {!armed && Array.isArray(report.blockers) && report.blockers.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: '18px', fontSize: '12px', color: '#991B1B' }}>
              {report.blockers.map((b) => (
                <li key={b.dependency}>
                  <strong>{CHANNEL_LABELS[b.dependency] || b.dependency}</strong>
                  {b.status ? ` — ${b.status}` : ''}{b.detail ? `: ${b.detail}` : ''}
                </li>
              ))}
            </ul>
          )}
          {report.error && (
            <div style={{ fontSize: '12px', color: '#991B1B', marginTop: '4px' }}>{report.error}</div>
          )}
        </div>
      )}

      {/* Per-channel status */}
      {report && !checking && Object.keys(channels).length > 0 && (
        <div style={{ marginTop: '12px', display: 'grid', gap: '6px' }}>
          {Object.entries(channels).map(([id, c]) => {
            const tone = STATUS_TONE[c.status] || STATUS_TONE.ERROR;
            const isCore = (report.core || []).includes(id);
            return (
              <div
                key={id}
                style={{
                  display: 'flex', alignItems: 'center', gap: '10px',
                  padding: '7px 10px', borderRadius: '8px',
                  background: tone.bg, border: `1px solid ${tone.br}`
                }}
              >
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: tone.dot, flexShrink: 0 }} />
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#0F2942', minWidth: '90px' }}>
                  {CHANNEL_LABELS[id] || id}
                </span>
                <span style={{
                  fontSize: '10px', fontWeight: 700, letterSpacing: '0.05em',
                  color: '#64748B', minWidth: '62px'
                }}>
                  {isCore ? 'CORE' : 'OPTIONAL'}
                </span>
                <span style={{ fontSize: '12px', fontWeight: 700, color: tone.fg, minWidth: '150px' }}>
                  {c.ready ? 'READY' : (c.status || 'UNKNOWN')}
                </span>
                <span style={{ fontSize: '11px', color: '#64748B', flex: 1, wordBreak: 'break-word' }}>
                  {c.account || c.detail || ''}
                </span>
              </div>
            );
          })}

          {report.services?.supabase && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '10px',
              padding: '7px 10px', borderRadius: '8px',
              background: report.services.supabase.ready ? '#ECFDF5' : '#FEF2F2',
              border: `1px solid ${report.services.supabase.ready ? '#A7F3D0' : '#FCA5A5'}`
            }}>
              <span style={{
                width: '8px', height: '8px', borderRadius: '50%',
                background: report.services.supabase.ready ? '#10B981' : '#EF4444', flexShrink: 0
              }} />
              <span style={{ fontSize: '12px', fontWeight: 700, color: '#0F2942', minWidth: '90px' }}>Supabase</span>
              <span style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', minWidth: '62px' }}>REQUIRED</span>
              <span style={{
                fontSize: '12px', fontWeight: 700,
                color: report.services.supabase.ready ? '#065F46' : '#991B1B'
              }}>
                {report.services.supabase.ready ? 'READY' : (report.services.supabase.status || 'ERROR')}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Publish action */}
      {report && !checking && (
        <div style={{
          marginTop: '14px', paddingTop: '12px', borderTop: '1px solid #E2E8F0',
          display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center'
        }}>
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            disabled={!canPublish}
            style={{
              flex: '1 1 240px', padding: '9px 10px', fontSize: '12px',
              border: '1px solid #CBD5E1', borderRadius: '8px',
              background: canPublish ? '#FFFFFF' : '#F1F5F9', color: '#0F2942'
            }}
          >
            <option value="">Select a calendar entry…</option>
            {posts.map((p) => (
              <option key={p['Content ID']} value={p['Content ID']}>
                {p['Content ID']} — {String(p.Title || '').slice(0, 60)} ({p.Status})
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={publishAll}
            disabled={!canPublish || publishing || !selectedId}
            title={canPublish ? `Publish to ${readyCount} ready channel(s)` : 'Connect at least one channel to publish'}
            style={{
              background: (!canPublish || publishing || !selectedId) ? '#CBD5E1' : '#047857',
              color: '#FFFFFF', border: 'none', borderRadius: '8px',
              padding: '10px 18px', fontSize: '13px', fontWeight: 700,
              cursor: (!canPublish || publishing || !selectedId) ? 'not-allowed' : 'pointer'
            }}
          >
            {publishing ? 'PUBLISHING…' : (armed ? 'Publish to All Core Channels' : `Publish to Ready Channels (${readyCount})`)}
          </button>
        </div>
      )}

      {/* Per-platform outcome, including partial failure */}
      {publishResults && (
        <div style={{ marginTop: '12px', display: 'grid', gap: '4px' }}>
          {(publishResults.results || []).map((r) => (
            <div key={r.platform} style={{
              display: 'flex', gap: '10px', alignItems: 'center',
              fontSize: '12px', padding: '5px 8px',
              background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: '6px'
            }}>
              <span style={{ fontWeight: 700, color: '#0F2942', minWidth: '90px' }}>
                {CHANNEL_LABELS[r.platform] || r.platform}
              </span>
              <span style={{ fontWeight: 700, color: PUBLISH_TONE[r.result] || '#475569', minWidth: '150px' }}>
                {r.result}{r.errorCode ? ` — ${r.errorCode}` : ''}{r.reason ? ` — ${r.reason}` : ''}
              </span>
              {r.permalink ? (
                <a href={r.permalink} target="_blank" rel="noreferrer" style={{ color: '#0369A1', fontSize: '11px' }}>
                  view post
                </a>
              ) : (
                <span style={{ color: '#64748B', fontSize: '11px' }}>{r.error || ''}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
