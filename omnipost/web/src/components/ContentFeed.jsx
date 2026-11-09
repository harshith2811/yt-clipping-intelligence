import React, { useState } from 'react';
import { RotateCw, Search, AlertTriangle } from 'lucide-react';
import PostCard from './PostCard';

export default function ContentFeed({ posts = [], loading = false, error = null, onRefresh }) {
  const [currentFilter, setCurrentFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  const filterTabs = [
    { key: 'all', label: 'All' },
    { key: 'Pending Review', label: 'Pending Review' },
    { key: 'Approved', label: 'Approved' },
    { key: 'Posted', label: 'Posted' },
    { key: 'Retry Pending', label: 'Retry / Failed' }
  ];

  const filteredPosts = posts.filter((post) => {
    const status = (post.Status || '').toLowerCase();
    const title = (post.Title || '').toLowerCase();
    const contentId = (post['Content ID'] || '').toLowerCase();
    const query = searchQuery.toLowerCase().trim();

    let matchesTab = true;
    if (currentFilter !== 'all') {
      const filterKey = currentFilter.toLowerCase();
      if (filterKey === 'retry pending') {
        matchesTab = status.includes('retry') || status.includes('failed');
      } else {
        matchesTab = status === filterKey;
      }
    }

    const matchesSearch = !query || title.includes(query) || contentId.includes(query);
    return matchesTab && matchesSearch;
  });

  return (
    <section className="card dashboard-card">
      <div className="card-header">
        <div className="card-header-left">
          <div className="card-title-group">
            <span className="badge-blue">Live Schedule</span>
            <h2 className="card-title">Content Calendar & Feed</h2>
          </div>
          <p className="card-desc">Real-time status sync with the Publishing Content Calendar</p>
        </div>
        <button
          type="button"
          className="btn-icon-refresh"
          onClick={onRefresh}
          title="Refresh Feed"
        >
          <RotateCw size={18} />
        </button>
      </div>

      <div className="filter-bar">
        <div className="filter-tabs">
          {filterTabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={`filter-tab ${currentFilter === tab.key ? 'active' : ''}`}
              onClick={() => setCurrentFilter(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="search-box">
          <Search size={15} className="search-icon" />
          <input
            type="text"
            placeholder="Search by title, ID..."
            className="input-search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      <div className="posts-list-wrapper" id="posts-container">
        {error ? (
          <div className="empty-state error-state">
            <AlertTriangle size={28} />
            <p>Couldn't reach the Content Calendar.</p>
            <p className="error-detail">{error}</p>
            <button type="button" className="btn-time-quick" onClick={onRefresh}>
              Try Again
            </button>
          </div>
        ) : loading ? (
          <div className="loading-state">
            <div className="spinner"></div>
            <p>Syncing Content Calendar from Google Sheets...</p>
          </div>
        ) : filteredPosts.length === 0 ? (
          <div className="empty-state">
            <p>No content items found matching the selected filter.</p>
          </div>
        ) : (
          filteredPosts.map((post, idx) => (
            <PostCard key={post['Content ID'] || idx} post={post} />
          ))
        )}
      </div>
    </section>
  );
}
