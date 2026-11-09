import React from 'react';
import StatsGrid from './StatsGrid';
import ContentComposer from './ContentComposer';
import ContentFeed from './ContentFeed';

/**
 * UploaderModule — Complete Self-Contained Content Uploader & Pipeline Manager
 *
 * Can be embedded into any page, dashboard, or layout.
 * Handles drag & drop media upload, metadata generation, Google Drive filing,
 * Google Sheets insertion, and live calendar feed monitoring.
 */
export default function UploaderModule({ posts = [], loading = false, error = null, onRefresh, onUploadSuccess, onToast, config = {} }) {
  return (
    <div className="uploader-module">
      <StatsGrid posts={posts} />
      <div className="workspace-grid">
        <ContentComposer onUploadSuccess={onUploadSuccess} onToast={onToast} config={config} />
        <ContentFeed posts={posts} loading={loading} error={error} onRefresh={onRefresh} />
      </div>
    </div>
  );
}

export { StatsGrid, ContentComposer, ContentFeed };
