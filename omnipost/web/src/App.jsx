import React, { useState, useEffect, useCallback } from 'react';
import Header from './components/Header';
import Toast from './components/Toast';
import UploaderModule from './components/UploaderModule';
import EnginePanel from './components/EnginePanel';
import IntegrationsModal from './components/IntegrationsModal';
import { Lock, KeyRound, AlertCircle, Share2 } from 'lucide-react';

export default function App() {
  const [authToken, setAuthToken] = useState(() => 
    sessionStorage.getItem('omnipost_auth_token') || sessionStorage.getItem('vbl_automation_token') || ''
  );
  const [isAuthenticated, setIsAuthenticated] = useState(() => 
    Boolean(sessionStorage.getItem('omnipost_auth_token') || sessionStorage.getItem('vbl_automation_token'))
  );
  const [passcode, setPasscode] = useState('');
  const [authError, setAuthError] = useState(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isIntegrationsOpen, setIsIntegrationsOpen] = useState(false);

  const [config, setConfig] = useState({
    appName: 'OmniPost Automation',
    appSubtitle: 'Universal Multi-Platform Content Publishing Engine',
    quickTags: ['#Video', '#Trending', '#ContentCreator', '#SocialMedia', '#Automation'],
    captionPlaceholder: 'Write compelling post copy, keywords, hashtags, call-to-action, or links...'
  });

  useEffect(() => {
    fetch('/api/config')
      .then((res) => res.json())
      .then((data) => {
        if (data && data.success && data.config) {
          setConfig((prev) => ({ ...prev, ...data.config }));
        }
      })
      .catch((err) => console.debug('Config load fallback:', err.message));
  }, []);

  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [feedError, setFeedError] = useState(null);
  const [pipelineStatus, setPipelineStatus] = useState('checking');
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((message, type = 'success') => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  const handleLogin = async (e) => {
    e.preventDefault();
    if (!passcode) return;

    setIsVerifying(true);
    setAuthError(null);

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ passcode: passcode.trim() }),
      });

      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.message || 'Invalid passcode or secret key.');
      }

      sessionStorage.setItem('omnipost_auth_token', data.token);
      setAuthToken(data.token);
      setIsAuthenticated(true);
      setPasscode('');
      addToast('Signed in to Publishing Studio', 'success');
    } catch (err) {
      setAuthError(err.message || 'Authentication failed.');
    } finally {
      setIsVerifying(false);
    }
  };

  const handleLogout = () => {
    sessionStorage.removeItem('omnipost_auth_token');
    sessionStorage.removeItem('vbl_automation_token');
    sessionStorage.removeItem('vbl_roles');
    setAuthToken('');
    setIsAuthenticated(false);
    setPosts([]);
    addToast('Logged out of Publishing Studio', 'info');
  };

  const fetchPosts = useCallback(async () => {
    const currentToken = authToken || sessionStorage.getItem('omnipost_auth_token') || sessionStorage.getItem('vbl_automation_token');
    if (!currentToken) {
      setLoading(false);
      return;
    }

    try {
      const response = await fetch('/api/posts', {
        headers: {
          Authorization: `Bearer ${currentToken}`,
        },
      });

      if (response.status === 401) {
        handleLogout();
        throw new Error('Session expired. Please sign in again.');
      }

      const data = await response.json();
      if (!response.ok || data.success === false) {
        throw new Error(data.error || data.message || `Request failed (${response.status})`);
      }
      if (data.posts && Array.isArray(data.posts)) {
        setPosts(data.posts);
        setFeedError(null);
        setPipelineStatus(data.offline ? 'standby' : 'online');
      }
    } catch (err) {
      if (!err.message?.includes('standby') && !err.message?.includes('ECONNREFUSED')) {
        console.warn('Fetch posts status:', err.message);
      }
      setFeedError(err.message || 'Automation pipeline in standby mode.');
      setPipelineStatus('standby');
    } finally {
      setLoading(false);
    }
  }, [authToken]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchPosts();
      const interval = setInterval(fetchPosts, 15000);
      return () => clearInterval(interval);
    }
  }, [isAuthenticated, fetchPosts]);

  useEffect(() => {
    document.title = `${config.appName || 'OmniPost Automation'} — Social Publishing Studio`;
  }, [config.appName]);

  // If unauthenticated, show clean login modal
  if (!isAuthenticated) {
    return (
      <div style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#F8FAFC',
        padding: '24px',
        position: 'relative'
      }}>
        <div className="glow-orb glow-1" />
        <div className="glow-orb glow-2" />

        <div style={{
          maxWidth: '420px',
          width: '100%',
          background: '#FFFFFF',
          borderRadius: '16px',
          padding: '36px',
          boxShadow: '0 12px 32px -4px rgba(15, 23, 42, 0.08), 0 4px 12px -2px rgba(15, 23, 42, 0.04)',
          border: '1px solid #E2E8F0',
          textAlign: 'center',
          position: 'relative',
          zIndex: 10
        }}>
          <div style={{
            width: '60px',
            height: '60px',
            borderRadius: '50%',
            background: '#0F2942',
            color: '#38BDF8',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 18px',
            boxShadow: '0 4px 14px rgba(15, 41, 66, 0.2)'
          }}>
            <Share2 size={28} />
          </div>

          <h2 style={{
            fontSize: '1.4rem',
            fontWeight: 700,
            color: '#0F2942',
            marginBottom: '4px',
            letterSpacing: '-0.01em'
          }}>
            {config.appName || 'OmniPost Automation'}
          </h2>
          <p style={{
            fontSize: '0.82rem',
            color: '#64748B',
            marginBottom: '24px',
            fontWeight: 500
          }}>
            {config.appSubtitle || 'Universal Multi-Platform Content Publishing Studio'}
          </p>

          <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ textAlign: 'left' }}>
              <label style={{
                display: 'block',
                fontSize: '0.75rem',
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                color: '#475569',
                marginBottom: '6px'
              }}>
                Passcode / Secret Key
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type="password"
                  value={passcode}
                  onChange={(e) => { setPasscode(e.target.value); setAuthError(null); }}
                  placeholder="Enter passcode or secret key..."
                  required
                  autoFocus
                  autoComplete="off"
                  data-lpignore="true"
                  style={{
                    width: '100%',
                    padding: '12px 14px 12px 38px',
                    borderRadius: '8px',
                    border: '1px solid #CBD5E1',
                    fontSize: '0.9rem',
                    outline: 'none',
                    transition: 'border-color 0.2s',
                    boxSizing: 'border-box'
                  }}
                />
                <Lock size={16} style={{
                  position: 'absolute',
                  left: '12px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: '#94A3B8'
                }} />
              </div>
            </div>

            {authError && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 12px',
                borderRadius: '8px',
                background: '#FEF2F2',
                border: '1px solid #FCA5A5',
                color: '#DC2626',
                fontSize: '0.8rem',
                fontWeight: 600,
                textAlign: 'left'
              }}>
                <AlertCircle size={16} style={{ flexShrink: 0 }} />
                <span>{authError}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={isVerifying}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: '8px',
                background: '#0F2942',
                color: '#FFFFFF',
                fontSize: '0.9rem',
                fontWeight: 600,
                border: 'none',
                cursor: isVerifying ? 'wait' : 'pointer',
                transition: 'background 0.2s',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px'
              }}
            >
              <KeyRound size={16} />
              <span>{isVerifying ? 'Verifying...' : 'Unlock Studio'}</span>
            </button>
          </form>

          <p style={{
            marginTop: '24px',
            fontSize: '0.72rem',
            color: '#94A3B8'
          }}>
            Protected console for authorized publishing managers and automated agents.
          </p>
        </div>

        <Toast toasts={toasts} />
      </div>
    );
  }

  return (
    <>
      {/* Ambient background glow orbs */}
      <div className="glow-orb glow-1" />
      <div className="glow-orb glow-2" />
      <div className="glow-orb glow-3" />

      <Header
        pipelineStatus={pipelineStatus}
        onLogout={handleLogout}
        onOpenIntegrations={() => setIsIntegrationsOpen(true)}
        config={config}
      />

      <main className="main-layout" style={{ maxWidth: '1440px', margin: '0 auto', padding: '24px 20px' }}>
        {/* Diagnostics & Green-signal Start Engine */}
        <EnginePanel authToken={authToken} posts={posts} onToast={addToast} />

        {/* Video & Media Publishing Suite */}
        <UploaderModule
          posts={posts}
          loading={loading}
          error={feedError}
          onRefresh={fetchPosts}
          onUploadSuccess={fetchPosts}
          onToast={addToast}
          config={config}
        />
      </main>

      <IntegrationsModal
        isOpen={isIntegrationsOpen}
        onClose={() => setIsIntegrationsOpen(false)}
        authToken={authToken}
      />

      <Toast toasts={toasts} />
    </>
  );
}
