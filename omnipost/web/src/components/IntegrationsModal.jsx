import React, { useState, useEffect } from 'react';
import { X, Copy, Check, ExternalLink, Zap, Terminal, Code2, Share2, Globe, ShieldCheck } from 'lucide-react';

const CHANNELS_GUIDE = [
  {
    id: 'instagram',
    name: 'Instagram Business',
    icon: '📸',
    color: '#E1306C',
    portalUrl: 'https://developers.facebook.com/apps/',
    docsUrl: 'https://developers.facebook.com/docs/instagram-platform/instagram-graph-api',
    envKeys: ['INSTAGRAM_ACCESS_TOKEN', 'INSTAGRAM_ACCOUNT_ID'],
    steps: [
      'Create an app at developers.facebook.com (App Type: Business).',
      'Add "Instagram Graph API" and connect your professional Instagram account to a Facebook Page.',
      'Generate a User Access Token in Graph API Explorer with permissions: instagram_basic, instagram_content_publish, pages_show_list.',
      'Query GET /me/accounts to find your Page ID, then GET /{page-id}?fields=instagram_business_account to get your INSTAGRAM_ACCOUNT_ID.',
      'Exchange the short-lived token for a long-lived 60-day token using oauth/access_token.'
    ]
  },
  {
    id: 'facebook',
    name: 'Facebook Page',
    icon: '📘',
    color: '#1877F2',
    portalUrl: 'https://developers.facebook.com/apps/',
    docsUrl: 'https://developers.facebook.com/docs/pages-api',
    envKeys: ['FACEBOOK_PAGE_ACCESS_TOKEN', 'FACEBOOK_PAGE_ID'],
    steps: [
      'In Meta Developer Console, generate a Page Access Token with permissions: pages_manage_posts, pages_read_engagement.',
      'Find your Page ID under Page Settings -> General -> Page ID, or via GET /me/accounts.',
      'Add FACEBOOK_PAGE_ACCESS_TOKEN and FACEBOOK_PAGE_ID to your .env file.'
    ]
  },
  {
    id: 'threads',
    name: 'Threads',
    icon: '🧵',
    color: '#000000',
    portalUrl: 'https://developers.facebook.com/apps/',
    docsUrl: 'https://developers.facebook.com/docs/threads',
    envKeys: ['THREADS_ACCESS_TOKEN', 'THREADS_USER_ID'],
    steps: [
      'In Meta Developer Console, add the "Threads API" use case.',
      'Generate an access token with permissions: threads_basic, threads_content_publish.',
      'Retrieve your Threads User ID via GET https://graph.threads.net/v1.0/me?fields=id,username.',
      'Add THREADS_ACCESS_TOKEN and THREADS_USER_ID to your .env file.'
    ]
  },
  {
    id: 'linkedin',
    name: 'LinkedIn',
    icon: '💼',
    color: '#0A66C2',
    portalUrl: 'https://www.linkedin.com/developers/apps',
    docsUrl: 'https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin',
    envKeys: ['LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_AUTHOR_URN'],
    steps: [
      'Create an application in the LinkedIn Developer Portal.',
      'Under "Products", add "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect".',
      'Under Auth -> OAuth 2.0 Tools, generate an access token with scope: w_member_social.',
      'Your Author URN is formatted as: urn:li:person:<your_member_id> (found via GET /v2/userinfo).',
      'Add LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_URN to your .env file.'
    ]
  },
  {
    id: 'youtube',
    name: 'YouTube',
    icon: '🎬',
    color: '#FF0000',
    portalUrl: 'https://console.cloud.google.com/apis/credentials',
    docsUrl: 'https://developers.google.com/youtube/v3/guides/uploading_a_video',
    envKeys: ['N8N_INTERNAL_URL or n8n YouTube Publisher workflow'],
    steps: [
      'In Google Cloud Console, enable "YouTube Data API v3".',
      'Create OAuth 2.0 Client ID (Web Application).',
      'Connect YouTube credential inside n8n Workflow Hub (http://localhost:5678).',
      'Activate the "YouTube Publisher" webhook in n8n; OmniPost will automatically dispatch video uploads through it.'
    ]
  },
  {
    id: 'pinterest',
    name: 'Pinterest',
    icon: '📌',
    color: '#E60023',
    portalUrl: 'https://developers.pinterest.com/apps/',
    docsUrl: 'https://developers.pinterest.com/docs/api/v5/',
    envKeys: ['PINTEREST_ACCESS_TOKEN', 'PINTEREST_BOARD_ID'],
    steps: [
      'Create a Pinterest Developer account and register an app.',
      'Generate an access token with scopes: boards:read, pins:read, pins:write.',
      'Get your target Board ID via GET /v5/boards or from the Pinterest URL of your board.',
      'Add PINTEREST_ACCESS_TOKEN and PINTEREST_BOARD_ID to your .env file.'
    ]
  }
];

export default function IntegrationsModal({ isOpen, onClose, authToken }) {
  const [activeTab, setActiveTab] = useState('channels');
  const [channels, setChannels] = useState([]);
  const [copiedKey, setCopiedKey] = useState(null);
  const [selectedChannel, setSelectedChannel] = useState(null);

  // Playground builder state
  const [snippetTitle, setSnippetTitle] = useState('Weekly Company Update');
  const [snippetCaption, setSnippetCaption] = useState('Super excited to share our latest milestone with the community! 🚀 #innovation #startup');
  const [snippetMediaUrl, setSnippetMediaUrl] = useState('https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4');
  const [snippetPlatforms, setSnippetPlatforms] = useState({
    youtube: true,
    instagram: true,
    linkedin: true,
    facebook: false,
    threads: true,
    pinterest: false
  });
  const [snippetPublishNow, setSnippetPublishNow] = useState(true);
  const [activeSnippetLang, setActiveSnippetLang] = useState('curl');

  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3300';
  const apiKeyPlaceholder = 'YOUR_AUTOMATION_SECRET_KEY';

  useEffect(() => {
    if (!isOpen) return;

    fetch('/api/channels', {
      headers: {
        Authorization: `Bearer ${authToken || sessionStorage.getItem('omnipost_auth_token') || ''}`
      }
    })
      .then((res) => res.json())
      .then((data) => {
        if (data && Array.isArray(data.channels)) {
          setChannels(data.channels);
        }
      })
      .catch(() => {});
  }, [isOpen, authToken]);

  if (!isOpen) return null;

  const copyToClipboard = (text, key) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const selectedPlatsList = Object.entries(snippetPlatforms)
    .filter(([_, checked]) => checked)
    .map(([p]) => p);

  // Generate Snippets
  const curlSnippet = `curl -X POST ${origin}/api/webhook/publish \\
  -H "x-api-key: ${apiKeyPlaceholder}" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify({
    title: snippetTitle,
    caption: snippetCaption,
    mediaUrl: snippetMediaUrl,
    platforms: selectedPlatsList,
    publishNow: snippetPublishNow
  }, null, 2)}'`;

  const nodeSnippet = `import { OmniPost } from './sdk/omnipost.js';

const client = new OmniPost({
  baseUrl: '${origin}',
  apiKey: '${apiKeyPlaceholder}'
});

const result = await client.publish({
  title: ${JSON.stringify(snippetTitle)},
  caption: ${JSON.stringify(snippetCaption)},
  mediaUrl: ${JSON.stringify(snippetMediaUrl)},
  platforms: ${JSON.stringify(selectedPlatsList)}
});

console.log('Publish result:', result);`;

  const pythonSnippet = `from sdk.omnipost import OmniPost

client = OmniPost(
    base_url="${origin}",
    api_key="${apiKeyPlaceholder}"
)

result = client.publish(
    title=${JSON.stringify(snippetTitle)},
    caption=${JSON.stringify(snippetCaption)},
    media_url=${JSON.stringify(snippetMediaUrl)},
    platforms=${JSON.stringify(selectedPlatsList)}
)

print("Publish result:", result)`;

  const zapierSnippet = `// Zapier Webhooks by Zapier or Make.com HTTP Module:
// Method: POST
// URL: ${origin}/api/webhook/publish
// Headers:
//   x-api-key: ${apiKeyPlaceholder}
//   Content-Type: application/json

// JSON Body Payload:
{
  "title": "${snippetTitle}",
  "caption": "${snippetCaption}",
  "mediaUrl": "${snippetMediaUrl}",
  "platforms": ${JSON.stringify(selectedPlatsList)},
  "publishNow": ${snippetPublishNow}
}`;

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      background: 'rgba(15, 23, 42, 0.75)',
      backdropFilter: 'blur(4px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '20px'
    }}>
      <div style={{
        background: '#FFFFFF',
        borderRadius: '16px',
        width: '100%',
        maxWidth: '960px',
        maxHeight: '90vh',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
        border: '1px solid #E2E8F0',
        overflow: 'hidden'
      }}>
        {/* Modal Header */}
        <div style={{
          padding: '20px 24px',
          borderBottom: '1px solid #E2E8F0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: '#0F2942',
          color: '#FFFFFF'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{
              width: '36px',
              height: '36px',
              borderRadius: '8px',
              background: 'rgba(56, 189, 248, 0.15)',
              color: '#38BDF8',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <Zap size={20} />
            </div>
            <div>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, margin: 0 }}>
                Integrations, Channels & API Studio
              </h2>
              <p style={{ fontSize: '0.8rem', color: '#94A3B8', margin: 0, marginTop: '2px' }}>
                Connect social channels, copy Zapier/Make webhooks, or integrate via SDK.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94A3B8',
              cursor: 'pointer',
              padding: '6px',
              borderRadius: '6px'
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Navigation Tabs */}
        <div style={{
          display: 'flex',
          borderBottom: '1px solid #E2E8F0',
          background: '#F8FAFC',
          padding: '0 24px'
        }}>
          {[
            { id: 'channels', label: 'Social Channels Guide', icon: Share2 },
            { id: 'webhooks', label: 'Webhooks & API Playground', icon: Code2 },
            { id: 'cli', label: 'CLI Wizard & Setup', icon: Terminal }
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '14px 18px',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  border: 'none',
                  borderBottom: `2px solid ${isActive ? '#0284C7' : 'transparent'}`,
                  color: isActive ? '#0284C7' : '#64748B',
                  background: 'transparent',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease'
                }}
              >
                <Icon size={16} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Tab Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>
          {/* TAB 1: Channels Guide */}
          {activeTab === 'channels' && (
            <div>
              <div style={{ marginBottom: '16px' }}>
                <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#0F2942', margin: '0 0 6px 0' }}>
                  Platform Connection Guides
                </h3>
                <p style={{ fontSize: '0.82rem', color: '#64748B', margin: 0 }}>
                  Select any channel below to view exact setup instructions, required scopes, and developer console links.
                </p>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '14px', marginBottom: '24px' }}>
                {CHANNELS_GUIDE.map((ch) => {
                  const chInfo = channels.find((c) => c.id === ch.id);
                  const isConfigured = chInfo?.configured ?? chInfo?.connected ?? false;
                  const isSelected = selectedChannel?.id === ch.id;

                  return (
                    <div
                      key={ch.id}
                      onClick={() => setSelectedChannel(isSelected ? null : ch)}
                      style={{
                        padding: '14px 16px',
                        borderRadius: '10px',
                        border: `1px solid ${isSelected ? '#0284C7' : '#E2E8F0'}`,
                        background: isSelected ? '#F0F9FF' : '#FFFFFF',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontSize: '1.25rem' }}>{ch.icon}</span>
                          <span style={{ fontWeight: 700, fontSize: '0.9rem', color: '#0F2942' }}>{ch.name}</span>
                        </div>
                        <span style={{
                          fontSize: '0.7rem',
                          fontWeight: 700,
                          padding: '3px 8px',
                          borderRadius: '12px',
                          background: isConfigured ? '#DCFCE7' : '#FEF3C7',
                          color: isConfigured ? '#15803D' : '#B45309'
                        }}>
                          {isConfigured ? '🟢 Connected' : '🟡 Needs Setup'}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#64748B' }}>
                        {isConfigured ? 'Ready to publish' : 'Click to view setup instructions'}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Selected Channel Deep Dive */}
              {selectedChannel && (
                <div style={{
                  background: '#F8FAFC',
                  border: '1px solid #CBD5E1',
                  borderRadius: '12px',
                  padding: '20px',
                  animation: 'fadeIn 0.2s ease'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span style={{ fontSize: '1.6rem' }}>{selectedChannel.icon}</span>
                      <div>
                        <h4 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: '#0F2942' }}>
                          {selectedChannel.name} Configuration Guide
                        </h4>
                        <div style={{ fontSize: '0.75rem', color: '#64748B' }}>
                          Required keys: {selectedChannel.envKeys.join(', ')}
                        </div>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <a
                        href={selectedChannel.portalUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="btn-secondary"
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          fontSize: '0.75rem',
                          padding: '6px 12px',
                          background: '#0F2942',
                          color: '#FFFFFF',
                          borderRadius: '6px',
                          textDecoration: 'none'
                        }}
                      >
                        <span>Open Developer Portal</span>
                        <ExternalLink size={13} />
                      </a>
                    </div>
                  </div>

                  <div style={{ marginBottom: '12px' }}>
                    <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#334155', marginBottom: '6px' }}>
                      Step-by-Step Instructions:
                    </div>
                    <ol style={{ margin: 0, paddingLeft: '20px', fontSize: '0.8rem', color: '#475569', lineHeight: 1.6 }}>
                      {selectedChannel.steps.map((st, i) => (
                        <li key={i} style={{ marginBottom: '4px' }}>{st}</li>
                      ))}
                    </ol>
                  </div>

                  <div style={{
                    background: '#0F172A',
                    color: '#E2E8F0',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    fontSize: '0.75rem',
                    fontFamily: 'monospace',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between'
                  }}>
                    <span>
                      # Add to your .env file:<br />
                      {selectedChannel.envKeys.map((k) => `${k}=...`).join('\n')}
                    </span>
                    <button
                      type="button"
                      onClick={() => copyToClipboard(selectedChannel.envKeys.map((k) => `${k}=`).join('\n'), 'keys')}
                      style={{
                        background: 'rgba(255,255,255,0.1)',
                        border: 'none',
                        color: '#FFFFFF',
                        padding: '6px 10px',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontSize: '0.7rem'
                      }}
                    >
                      {copiedKey === 'keys' ? <Check size={14} color="#4ADE80" /> : <Copy size={14} />}
                      <span>{copiedKey === 'keys' ? 'Copied' : 'Copy Template'}</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* TAB 2: Webhooks & API Playground */}
          {activeTab === 'webhooks' && (
            <div>
              <div style={{ marginBottom: '18px' }}>
                <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#0F2942', margin: '0 0 6px 0' }}>
                  Interactive Webhook & Code Generator
                </h3>
                <p style={{ fontSize: '0.82rem', color: '#64748B', margin: 0 }}>
                  Configure your post below and copy ready-to-run snippets for Zapier, Make, cURL, Python, or Node.js.
                </p>
              </div>

              {/* Form parameters */}
              <div style={{
                background: '#F8FAFC',
                border: '1px solid #E2E8F0',
                borderRadius: '12px',
                padding: '18px',
                marginBottom: '18px',
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                gap: '14px'
              }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: '#475569', marginBottom: '4px' }}>
                    Post Title (Optional)
                  </label>
                  <input
                    type="text"
                    value={snippetTitle}
                    onChange={(e) => setSnippetTitle(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      fontSize: '0.85rem',
                      border: '1px solid #CBD5E1',
                      borderRadius: '6px',
                      boxSizing: 'border-box'
                    }}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: '#475569', marginBottom: '4px' }}>
                    Media URL (Video or Image)
                  </label>
                  <input
                    type="url"
                    value={snippetMediaUrl}
                    onChange={(e) => setSnippetMediaUrl(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      fontSize: '0.85rem',
                      border: '1px solid #CBD5E1',
                      borderRadius: '6px',
                      boxSizing: 'border-box'
                    }}
                  />
                </div>

                <div style={{ gridColumn: '1 / -1' }}>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: '#475569', marginBottom: '4px' }}>
                    Caption & Hashtags
                  </label>
                  <textarea
                    rows={2}
                    value={snippetCaption}
                    onChange={(e) => setSnippetCaption(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      fontSize: '0.85rem',
                      border: '1px solid #CBD5E1',
                      borderRadius: '6px',
                      boxSizing: 'border-box',
                      resize: 'vertical'
                    }}
                  />
                </div>

                <div style={{ gridColumn: '1 / -1' }}>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 700, color: '#475569', marginBottom: '6px' }}>
                    Target Platforms:
                  </label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                    {Object.keys(snippetPlatforms).map((plat) => (
                      <label key={plat} style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontSize: '0.8rem',
                        cursor: 'pointer',
                        padding: '4px 8px',
                        borderRadius: '6px',
                        background: snippetPlatforms[plat] ? '#E0F2FE' : '#FFFFFF',
                        border: `1px solid ${snippetPlatforms[plat] ? '#7DD3FC' : '#CBD5E1'}`
                      }}>
                        <input
                          type="checkbox"
                          checked={snippetPlatforms[plat]}
                          onChange={() => setSnippetPlatforms((prev) => ({ ...prev, [plat]: !prev[plat] }))}
                        />
                        <span style={{ textTransform: 'capitalize' }}>{plat}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              {/* Code Snippets Viewer */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    {[
                      { id: 'curl', label: 'cURL' },
                      { id: 'node', label: 'Node.js / JS' },
                      { id: 'python', label: 'Python' },
                      { id: 'zapier', label: 'Zapier / Make' }
                    ].map((lang) => (
                      <button
                        key={lang.id}
                        type="button"
                        onClick={() => setActiveSnippetLang(lang.id)}
                        style={{
                          padding: '6px 12px',
                          fontSize: '0.75rem',
                          fontWeight: 700,
                          borderRadius: '6px',
                          border: 'none',
                          background: activeSnippetLang === lang.id ? '#0F2942' : '#F1F5F9',
                          color: activeSnippetLang === lang.id ? '#FFFFFF' : '#475569',
                          cursor: 'pointer'
                        }}
                      >
                        {lang.label}
                      </button>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={() => {
                      const textToCopy =
                        activeSnippetLang === 'curl' ? curlSnippet :
                        activeSnippetLang === 'node' ? nodeSnippet :
                        activeSnippetLang === 'python' ? pythonSnippet : zapierSnippet;
                      copyToClipboard(textToCopy, activeSnippetLang);
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      fontSize: '0.75rem',
                      padding: '6px 12px',
                      borderRadius: '6px',
                      background: '#0284C7',
                      color: '#FFFFFF',
                      border: 'none',
                      cursor: 'pointer'
                    }}
                  >
                    {copiedKey === activeSnippetLang ? <Check size={14} color="#FFFFFF" /> : <Copy size={14} />}
                    <span>{copiedKey === activeSnippetLang ? 'Copied to Clipboard!' : 'Copy Code'}</span>
                  </button>
                </div>

                <pre style={{
                  background: '#0F172A',
                  color: '#38BDF8',
                  padding: '16px',
                  borderRadius: '10px',
                  fontSize: '0.8rem',
                  fontFamily: 'monospace',
                  overflowX: 'auto',
                  margin: 0,
                  maxHeight: '260px'
                }}>
                  <code>
                    {activeSnippetLang === 'curl' && curlSnippet}
                    {activeSnippetLang === 'node' && nodeSnippet}
                    {activeSnippetLang === 'python' && pythonSnippet}
                    {activeSnippetLang === 'zapier' && zapierSnippet}
                  </code>
                </pre>
              </div>
            </div>
          )}

          {/* TAB 3: CLI Wizard & Setup */}
          {activeTab === 'cli' && (
            <div>
              <div style={{ marginBottom: '18px' }}>
                <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#0F2942', margin: '0 0 6px 0' }}>
                  Interactive Terminal Setup Wizard
                </h3>
                <p style={{ fontSize: '0.82rem', color: '#64748B', margin: 0 }}>
                  For new installations or automated environment configuration, run the setup wizard in your terminal.
                </p>
              </div>

              <div style={{
                background: '#0F172A',
                color: '#F8FAFC',
                padding: '18px',
                borderRadius: '10px',
                marginBottom: '18px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}>
                <div>
                  <div style={{ fontSize: '0.75rem', color: '#94A3B8', marginBottom: '4px' }}>
                    Run in your project root or terminal:
                  </div>
                  <code style={{ fontSize: '1rem', fontWeight: 700, color: '#4ADE80' }}>
                    npm run setup
                  </code>
                </div>
                <button
                  type="button"
                  onClick={() => copyToClipboard('npm run setup', 'setup_cli')}
                  style={{
                    background: 'rgba(255,255,255,0.15)',
                    border: 'none',
                    color: '#FFFFFF',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '0.75rem'
                  }}
                >
                  {copiedKey === 'setup_cli' ? <Check size={14} color="#4ADE80" /> : <Copy size={14} />}
                  <span>{copiedKey === 'setup_cli' ? 'Copied' : 'Copy'}</span>
                </button>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '14px' }}>
                <div style={{ border: '1px solid #E2E8F0', borderRadius: '10px', padding: '16px', background: '#F8FAFC' }}>
                  <div style={{ fontWeight: 700, fontSize: '0.85rem', color: '#0F2942', marginBottom: '6px' }}>
                    ⚡ What the CLI Wizard Does:
                  </div>
                  <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.8rem', color: '#475569', lineHeight: 1.6 }}>
                    <li>Generates cryptographically secure passkeys</li>
                    <li>Configures Local Mode (zero config) or Supabase Cloud</li>
                    <li>Guided setup for Meta, LinkedIn, and Pinterest</li>
                    <li>Safely backs up and updates your .env file</li>
                    <li>Performs immediate diagnostic self-checks</li>
                  </ul>
                </div>

                <div style={{ border: '1px solid #E2E8F0', borderRadius: '10px', padding: '16px', background: '#F8FAFC' }}>
                  <div style={{ fontWeight: 700, fontSize: '0.85rem', color: '#0F2942', marginBottom: '6px' }}>
                    🛡️ Authentication Formats Supported:
                  </div>
                  <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.8rem', color: '#475569', lineHeight: 1.6 }}>
                    <li><strong>x-api-key:</strong> Standard webhook header</li>
                    <li><strong>x-admin-key:</strong> Chambers admin header</li>
                    <li><strong>Authorization:</strong> Bearer token</li>
                    <li><strong>?apiKey=...:</strong> Query parameter for simple webhooks</li>
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
