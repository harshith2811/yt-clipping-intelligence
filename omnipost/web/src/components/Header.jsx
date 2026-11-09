import React from 'react';
import { Share2, Table, Folder, LogOut, Zap } from 'lucide-react';

const STATUS_COPY = {
  checking: { label: 'Checking…', className: 'status-checking' },
  online: { label: 'Pipeline Active', className: 'status-online' },
  standby: { label: 'Pipeline Standby', className: 'status-checking' },
  offline: { label: 'Pipeline Standby', className: 'status-offline' }
};

export default function Header({ pipelineStatus = 'checking', onLogout, onOpenIntegrations, config = {} }) {
  const { label, className } = STATUS_COPY[pipelineStatus] || STATUS_COPY.checking;
  const brandName = config.appName || 'OmniPost Automation';
  const subtitle = config.appSubtitle || 'Universal Multi-Platform Content Publishing Engine';
  const sheetUrl = config.sheetUrl;
  const driveUrl = config.driveFolderUrl;

  return (
    <header className="app-header">
      <div className="header-container">
        <div className="brand-group">
          <div className="brand-logo">
            <Share2 size={24} />
          </div>
          <div className="brand-text">
            <h1 className="brand-title">{brandName}</h1>
            <p className="brand-subtitle">{subtitle}</p>
          </div>
        </div>

        <div className="header-actions">
          <div className={`system-status ${className}`}>
            <span className={`status-dot ${pipelineStatus === 'online' ? 'pulsing' : ''}`}></span>
            <span className="status-text">{label}</span>
          </div>
          {onOpenIntegrations && (
            <button
              type="button"
              onClick={onOpenIntegrations}
              className="btn-secondary"
              id="btn-integrations"
              title="Integrations, Channels & API"
              style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <Zap size={15} style={{ color: '#F59E0B' }} />
              <span className="btn-secondary-label">Integrations & API</span>
            </button>
          )}
          {sheetUrl && (
            <a
              href={sheetUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary"
              id="btn-open-sheet"
            >
              <Table size={15} />
              <span className="btn-secondary-label">Google Sheet</span>
            </a>
          )}
          {driveUrl && (
            <a
              href={driveUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary"
              id="btn-open-drive"
            >
              <Folder size={15} />
              <span className="btn-secondary-label">Drive Folder</span>
            </a>
          )}
          {onLogout && (
            <button
              type="button"
              onClick={onLogout}
              className="btn-secondary"
              id="btn-logout"
              title="Lock Session"
              style={{ cursor: 'pointer' }}
            >
              <LogOut size={15} />
              <span className="btn-secondary-label">Lock</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
