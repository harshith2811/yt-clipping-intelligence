import React from 'react';
import { Clock, ExternalLink } from 'lucide-react';

export default function PostCard({ post }) {
  const id = post['Content ID'] || 'W-000';
  const title = post.Title || 'Untitled Post';
  const caption = post.Caption || '';
  const status = post.Status || 'Draft';
  const driveId = post['Drive File ID'] || '';
  const scheduled = formatScheduleDate(post['Scheduled DateTime']);
  const platforms = (post.Platforms || '')
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean);

  function getStatusClass(s) {
    const st = (s || '').toLowerCase();
    if (st === 'pending review') return 'status-pending';
    if (st === 'awaiting response') return 'status-awaiting';
    if (st === 'approved') return 'status-approved';
    if (st === 'posted') return 'status-posted';
    if (st.includes('fail') || st.includes('retry')) return 'status-failed';
    return 'status-draft';
  }

  function formatScheduleDate(isoStr) {
    if (!isoStr) return 'Unscheduled';
    try {
      const d = new Date(isoStr);
      return d.toLocaleString('en-IN', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true
      });
    } catch (e) {
      return isoStr;
    }
  }

  const statusClass = getStatusClass(status);

  return (
    <div className="post-item">
      <div className="post-top">
        <span className="post-id-badge">{id}</span>
        <span className={`status-pill ${statusClass}`}>{status}</span>
      </div>

      <h3 className="post-title">{title}</h3>
      {caption && <p className="post-caption">{caption}</p>}

      <div className="post-platforms-row">
        {platforms.map((plat) => {
          const colName = plat.charAt(0).toUpperCase() + plat.slice(1) + ' Status';
          const platStatus = post[colName] || '';
          let platStatusClass = '';
          if (platStatus.toLowerCase().includes('posted')) platStatusClass = 'posted';
          else if (platStatus.toLowerCase().includes('fail')) platStatusClass = 'failed';

          return (
            <span key={plat} className={`chip-platform ${platStatusClass}`}>
              {plat}
              {platStatus ? ` (${platStatus.slice(0, 6)})` : ''}
            </span>
          );
        })}
      </div>

      <div className="post-footer">
        <span className="post-time">
          <Clock size={12} />
          {scheduled}
        </span>
        {driveId && (
          <a
            href={`https://drive.google.com/file/d/${driveId}/view`}
            target="_blank"
            rel="noopener noreferrer"
            className="post-drive-link"
          >
            <ExternalLink size={12} />
            Drive File
          </a>
        )}
      </div>
    </div>
  );
}
