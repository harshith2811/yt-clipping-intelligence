import React from 'react';
import { Calendar, Clock, CheckCircle2, Zap } from 'lucide-react';

export default function StatsGrid({ posts = [] }) {
  const total = posts.length;
  let pending = 0;
  let approved = 0;
  let posted = 0;

  posts.forEach((p) => {
    const s = (p.Status || '').trim().toLowerCase();
    if (s === 'pending review' || s === 'awaiting response') pending++;
    else if (s === 'approved') approved++;
    else if (s === 'posted') posted++;
  });

  return (
    <section className="stats-grid">
      <div className="stat-card">
        <div className="stat-icon icon-gold">
          <Calendar size={24} />
        </div>
        <div className="stat-info">
          <span className="stat-label">Total Content</span>
          <span className="stat-value" id="stat-total">
            {total}
          </span>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-icon icon-amber">
          <Clock size={24} />
        </div>
        <div className="stat-info">
          <span className="stat-label">Pending Approval</span>
          <span className="stat-value" id="stat-pending">
            {pending}
          </span>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-icon icon-blue">
          <CheckCircle2 size={24} />
        </div>
        <div className="stat-info">
          <span className="stat-label">Approved / Scheduled</span>
          <span className="stat-value" id="stat-approved">
            {approved}
          </span>
        </div>
      </div>

      <div className="stat-card">
        <div className="stat-icon icon-green">
          <Zap size={24} />
        </div>
        <div className="stat-info">
          <span className="stat-label">Published Live</span>
          <span className="stat-value" id="stat-posted">
            {posted}
          </span>
        </div>
      </div>
    </section>
  );
}
