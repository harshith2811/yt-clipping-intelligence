import React, { useState, useRef, useEffect } from 'react';
import { UploadCloud, X, Send } from 'lucide-react';

export default function ContentComposer({ onUploadSuccess, onToast, config = {} }) {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [fileType, setFileType] = useState('');
  const [fileName, setFileName] = useState('');
  const [fileSize, setFileSize] = useState('');

  const [title, setTitle] = useState('');
  const [caption, setCaption] = useState('');
  const [platforms, setPlatforms] = useState({
    youtube: true,
    instagram: true,
    facebook: true,
    linkedin: true,
    pinterest: false,
    threads: true
  });
  const [scheduledDateTime, setScheduledDateTime] = useState('');
  const [status, setStatus] = useState('Pending Review');
  const [activeTimePreset, setActiveTimePreset] = useState('asap');
  const [channelStatus, setChannelStatus] = useState({});

  useEffect(() => {
    fetch('/api/channels', {
      headers: {
        Authorization: `Bearer ${sessionStorage.getItem('omnipost_auth_token') || sessionStorage.getItem('vbl_automation_token') || ''}`
      }
    })
      .then((res) => res.json())
      .then((data) => {
        if (data && Array.isArray(data.channels)) {
          const map = {};
          const configuredKeys = {};
          data.channels.forEach((c) => {
            const isConf = Boolean(c.configured ?? c.connected);
            map[c.id] = isConf;
            if (isConf) configuredKeys[c.id] = true;
          });
          setChannelStatus(map);
          if (Object.keys(configuredKeys).length > 0) {
            setPlatforms((prev) => ({
              youtube: Boolean(configuredKeys.youtube),
              instagram: Boolean(configuredKeys.instagram),
              facebook: Boolean(configuredKeys.facebook),
              linkedin: Boolean(configuredKeys.linkedin),
              pinterest: Boolean(configuredKeys.pinterest),
              threads: Boolean(configuredKeys.threads)
            }));
          }
        }
      })
      .catch(() => {});
  }, []);

  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [progressStatusText, setProgressStatusText] = useState('');
  const [isDragOver, setIsDragOver] = useState(false);

  const fileInputRef = useRef(null);

  useEffect(() => {
    setPublishAsapTime();
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setPublishAsapTime() {
    setActiveTimePreset('asap');
    const now = new Date();
    now.setMinutes(now.getMinutes() + 2);
    const localIso = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    setScheduledDateTime(localIso);
  }

  function setScheduleEvening() {
    setActiveTimePreset('evening');
    const date = new Date();
    date.setHours(18, 0, 0, 0);
    const localIso = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    setScheduledDateTime(localIso);
  }

  function setScheduleTomorrow() {
    setActiveTimePreset('tomorrow');
    const date = new Date();
    date.setDate(date.getDate() + 1);
    date.setHours(10, 0, 0, 0);
    const localIso = new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    setScheduledDateTime(localIso);
  }

  const ACCEPTED_TYPES = ['video/mp4', 'video/quicktime', 'video/webm', 'image/jpeg', 'image/png', 'image/webp'];
  const MAX_FILE_BYTES = 500 * 1024 * 1024;

  function handleFileSelected(selectedFile) {
    if (!selectedFile) return;

    if (!ACCEPTED_TYPES.includes(selectedFile.type)) {
      onToast('Unsupported file type. Please use MP4, MOV, WEBM, JPG, PNG or WEBP.', 'error');
      return;
    }
    if (selectedFile.size > MAX_FILE_BYTES) {
      onToast('File is too large. Maximum upload size is 500MB.', 'error');
      return;
    }

    setFile(selectedFile);
    setFileName(selectedFile.name);
    setFileSize(formatBytes(selectedFile.size));
    setFileType(selectedFile.type);

    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    setPreviewUrl(URL.createObjectURL(selectedFile));
  }

  function clearMedia(e) {
    if (e) e.stopPropagation();
    setFile(null);
    setFileName('');
    setFileSize('');
    setFileType('');
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl(null);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }

  function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  }

  function applyTopicTemplate(templateTitle, templateCaption, templateTags) {
    setTitle(templateTitle);
    setCaption(`${templateCaption}\n\n${templateTags}`);
    onToast('Topic template loaded!', 'success');
  }

  function insertHashtag(tag) {
    if (!caption.includes(tag)) {
      setCaption((prev) => (prev ? `${prev} ${tag}` : tag));
    }
  }

  function togglePlatform(key) {
    setPlatforms((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleSubmit(e) {
    e.preventDefault();

    if (!file) {
      onToast('Please attach a video or photo before submitting.', 'error');
      return;
    }

    if (!title.trim()) {
      onToast('Post title is required.', 'error');
      return;
    }

    const selectedPlats = Object.entries(platforms)
      .filter(([_, isChecked]) => isChecked)
      .map(([key]) => key);

    if (selectedPlats.length === 0) {
      onToast('Please select at least one target social platform.', 'error');
      return;
    }

    let scheduledIso = new Date().toISOString();
    if (scheduledDateTime) {
      scheduledIso = new Date(scheduledDateTime).toISOString();
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', title.trim());
    formData.append('caption', caption.trim());
    formData.append('platforms', selectedPlats.join(','));
    formData.append('scheduledDateTime', scheduledIso);
    formData.append('status', status);

    setIsUploading(true);
    setUploadProgress(0);
    setProgressStatusText('Starting upload to Google Drive...');

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload', true);

    const token = sessionStorage.getItem('omnipost_auth_token') || sessionStorage.getItem('vbl_automation_token');
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 90);
        setUploadProgress(percent);
        setProgressStatusText(`Uploading media to Google Drive (${percent}%)...`);
      }
    };

    xhr.onload = () => {
      setUploadProgress(100);
      setProgressStatusText('Filing into Google Sheet & Scheduling...');

      setTimeout(() => {
        setIsUploading(false);
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            const res = JSON.parse(xhr.responseText);
            onToast(`Success! Content ${res.contentId || ''} filed & scheduled!`, 'success');
          } catch (err) {
            onToast('Uploaded and scheduled successfully!', 'success');
          }
          setTitle('');
          setCaption('');
          clearMedia();
          setPublishAsapTime();
          onUploadSuccess();
        } else {
          let errMessage = 'Upload failed. Please check server logs.';
          try {
            const errRes = JSON.parse(xhr.responseText);
            errMessage = errRes.error || errRes.message || errMessage;
          } catch (err) {}
          onToast(errMessage, 'error');
        }
      }, 500);
    };

    xhr.onerror = () => {
      setIsUploading(false);
      onToast('Network error during upload. Please verify the server is running.', 'error');
    };

    xhr.send(formData);
  }

  return (
    <section className="card composer-card">
      <div className="card-header">
        <div className="card-header-left">
          <div className="card-title-group">
            <span className="badge-gold">1-Click Publisher</span>
            <h2 className="card-title">Schedule New Social Content</h2>
          </div>
          <p className="card-desc">
            Upload video/photo. It files into Google Drive, logs into Google Sheets, and publishes across channels.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="composer-form">
        {/* Media Dropzone */}
        <div className="form-group">
          <label className="form-label">
            <span>Media Asset (Video / Photo)</span>
            <span className="label-hint">MP4, MOV, JPG, PNG up to 500MB</span>
          </label>

          <div
            className={`dropzone ${isDragOver ? 'dragover' : ''}`}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                fileInputRef.current?.click();
              }
            }}
            role="button"
            tabIndex={0}
            aria-label="Upload media file"
            onDragEnter={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragOver(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setIsDragOver(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setIsDragOver(false);
              if (e.dataTransfer.files?.length > 0) {
                handleFileSelected(e.dataTransfer.files[0]);
              }
            }}
          >
            <input
              type="file"
              ref={fileInputRef}
              accept="video/mp4,video/quicktime,video/webm,image/jpeg,image/png,image/webp"
              style={{ display: 'none' }}
              onChange={(e) => {
                if (e.target.files?.length > 0) {
                  handleFileSelected(e.target.files[0]);
                }
              }}
            />

            {!file ? (
              <div className="dropzone-empty">
                <div className="dropzone-icon">
                  <UploadCloud size={26} />
                </div>
                <p className="dropzone-main-text">
                  Drag & drop video/image here, or <span className="browse-link">Browse files</span>
                </p>
                <p className="dropzone-sub-text">Recommended for Reels/Shorts: 1080x1920 (9:16 Vertical)</p>
              </div>
            ) : (
              <div className="dropzone-preview" style={{ display: 'flex' }}>
                <div className="preview-media-wrapper">
                  {fileType.startsWith('video/') ? (
                    <video src={previewUrl} controls muted />
                  ) : (
                    <img src={previewUrl} alt={fileName || 'Selected media preview'} />
                  )}
                </div>
                <div className="preview-meta">
                  <div className="preview-file-info">
                    <span className="preview-filename">{fileName}</span>
                    <span className="preview-filesize">{fileSize}</span>
                  </div>
                  <button
                    type="button"
                    className="btn-remove-media"
                    onClick={clearMedia}
                    title="Remove file"
                    aria-label="Remove selected file"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Quick Topic Suggestions */}
        <div className="form-group">
          <label className="form-label">
            <span>Quick Topics & Templates</span>
          </label>
          <div className="topic-chips">
            <button
              type="button"
              className="topic-chip"
              onClick={() =>
                applyTopicTemplate(
                  'Major Announcement & Product Launch',
                  'Excited to unveil our latest release! Here is a deep dive into what we built, why it matters, and how you can get started today.',
                  '#ProductLaunch #TechUpdate #Innovation #CreatorEconomy'
                )
              }
            >
              🚀 Product Announcement
            </button>
            <button
              type="button"
              className="topic-chip"
              onClick={() =>
                applyTopicTemplate(
                  'Quick Tutorial: Top 3 Pro Tips',
                  'Save hours each week with these three essential tips. Swipe or watch the full walkthrough to level up your workflow.',
                  '#Tutorial #Productivity #ProTips #LifeHacks #HowTo'
                )
              }
            >
              💡 Quick How-To Tutorial
            </button>
            <button
              type="button"
              className="topic-chip"
              onClick={() =>
                applyTopicTemplate(
                  'Behind the Scenes & Community Story',
                  'A look behind the scenes at how we build, iterate, and deliver results. Thank you to our incredible community for your continued support!',
                  '#BehindTheScenes #Community #Culture #Growth #Creators'
                )
              }
            >
              ✨ Behind the Scenes
            </button>
          </div>
        </div>

        {/* Post Title */}
        <div className="form-group">
          <label htmlFor="post-title" className="form-label">
            <span>Post Title / Headline</span>
            <span className="req">*</span>
          </label>
          <input
            type="text"
            id="post-title"
            className="input-text"
            placeholder={config.titlePlaceholder || "e.g., Video Showcase / Product Update / Behind the Scenes"}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </div>

        {/* Post Caption */}
        <div className="form-group">
          <div className="form-label-row">
            <label htmlFor="post-caption" className="form-label">
              Caption / Description
            </label>
            <span className="char-count">{caption.length.toLocaleString()} / 2,200</span>
          </div>
          <textarea
            id="post-caption"
            className="input-textarea"
            rows="4"
            maxLength={2200}
            placeholder={config.captionPlaceholder || "Write compelling post copy, keywords, hashtags, call-to-action, or links..."}
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
          />

          <div className="hashtag-row">
            <span className="hashtag-label">Quick Tags:</span>
            {((config.quickTags && config.quickTags.length > 0)
              ? config.quickTags
              : ['#Video', '#Trending', '#ContentCreator', '#SocialMedia', '#Automation']
            ).map((tag) => (
              <button
                key={tag}
                type="button"
                className="tag-btn"
                onClick={() => insertHashtag(tag)}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        {/* Target Platforms Multi-Select */}
        <div className="form-group">
          <label className="form-label">
            <span>Target Social Channels</span>
            <span className="label-hint">Select where to publish</span>
          </label>
          <div className="platforms-selector">
            <label className="platform-toggle">
              <input
                type="checkbox"
                checked={platforms.youtube}
                onChange={() => togglePlatform('youtube')}
              />
              <div className="platform-box">
                <span className="platform-icon yt-icon">
                  <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
                  </svg>
                </span>
                <span className="platform-name">YouTube</span>
              </div>
            </label>

            <label className="platform-toggle">
              <input
                type="checkbox"
                checked={platforms.instagram}
                onChange={() => togglePlatform('instagram')}
              />
              <div className="platform-box">
                <span className="platform-icon ig-icon">
                  <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z" />
                  </svg>
                </span>
                <span className="platform-name">
                  Instagram
                  {channelStatus.instagram !== undefined && (
                    <span
                      style={{
                        display: 'inline-block',
                        width: '7px',
                        height: '7px',
                        borderRadius: '50%',
                        marginLeft: '5px',
                        verticalAlign: 'middle',
                        background: channelStatus.instagram ? '#10B981' : '#F59E0B'
                      }}
                      title={channelStatus.instagram ? 'Channel Ready' : 'Needs Configuration'}
                    />
                  )}
                </span>
              </div>
            </label>

            <label className="platform-toggle">
              <input
                type="checkbox"
                checked={platforms.facebook}
                onChange={() => togglePlatform('facebook')}
              />
              <div className="platform-box">
                <span className="platform-icon fb-icon">
                  <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" />
                  </svg>
                </span>
                <span className="platform-name">
                  Facebook
                  {channelStatus.facebook !== undefined && (
                    <span
                      style={{
                        display: 'inline-block',
                        width: '7px',
                        height: '7px',
                        borderRadius: '50%',
                        marginLeft: '5px',
                        verticalAlign: 'middle',
                        background: channelStatus.facebook ? '#10B981' : '#F59E0B'
                      }}
                      title={channelStatus.facebook ? 'Channel Ready' : 'Needs Configuration'}
                    />
                  )}
                </span>
              </div>
            </label>

            <label className="platform-toggle">
              <input
                type="checkbox"
                checked={platforms.linkedin}
                onChange={() => togglePlatform('linkedin')}
              />
              <div className="platform-box">
                <span className="platform-icon in-icon">
                  <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
                  </svg>
                </span>
                <span className="platform-name">LinkedIn</span>
              </div>
            </label>

            <label className="platform-toggle">
              <input
                type="checkbox"
                checked={platforms.pinterest}
                onChange={() => togglePlatform('pinterest')}
              />
              <div className="platform-box">
                <span className="platform-icon pin-icon">
                  <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M12 0a12 12 0 0 0-4.37 23.18c-.06-.94-.12-2.39.02-3.42l1-4.24s-.26-.52-.26-1.28c0-1.2.7-2.1 1.57-2.1.74 0 1.1.56 1.1 1.23 0 .75-.48 1.86-.72 2.9-.2.87.43 1.58 1.29 1.58 1.55 0 2.74-1.63 2.74-3.99 0-2.09-1.5-3.55-3.64-3.55-2.48 0-3.94 1.86-3.94 3.78 0 .75.29 1.55.65 1.99.07.09.08.17.06.26l-.25 1.01c-.04.16-.13.2-.3.12-1.12-.52-1.82-2.16-1.82-3.48 0-2.83 2.06-5.43 5.94-5.43 3.12 0 5.54 2.22 5.54 5.19 0 3.1-1.95 5.59-4.66 5.59-.91 0-1.77-.47-2.06-1.03l-.56 2.14c-.2.78-.75 1.76-1.12 2.36A12 12 0 1 0 12 0z" />
                  </svg>
                </span>
                <span className="platform-name">
                  Pinterest
                  {channelStatus.pinterest !== undefined && (
                    <span
                      style={{
                        display: 'inline-block',
                        width: '7px',
                        height: '7px',
                        borderRadius: '50%',
                        marginLeft: '5px',
                        verticalAlign: 'middle',
                        background: channelStatus.pinterest ? '#10B981' : '#F59E0B'
                      }}
                      title={channelStatus.pinterest ? 'Channel Ready' : 'Needs Configuration'}
                    />
                  )}
                </span>
              </div>
            </label>

            <label className="platform-toggle">
              <input
                type="checkbox"
                checked={platforms.threads}
                onChange={() => togglePlatform('threads')}
              />
              <div className="platform-box">
                <span className="platform-icon th-icon">
                  <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221c-.135-.091-.284-.16-.445-.205a6.046 6.046 0 0 0-1.791-.252c-1.328 0-2.433.447-3.284 1.328-.852.881-1.278 2.06-1.278 3.537 0 1.477.426 2.656 1.278 3.537.851.881 1.956 1.328 3.284 1.328.791 0 1.503-.16 2.137-.479v2.109a8.163 8.163 0 0 1-2.137.281c-2.029 0-3.693-.667-4.992-2-1.299-1.333-1.949-3.093-1.949-5.276 0-2.183.65-3.943 1.949-5.276 1.299-1.333 2.963-2 4.992-2 .885 0 1.716.143 2.493.428.777.286 1.385.702 1.824 1.248l-2.102 1.638z" />
                  </svg>
                </span>
                <span className="platform-name">
                  Threads
                  {channelStatus.threads !== undefined && (
                    <span
                      style={{
                        display: 'inline-block',
                        width: '7px',
                        height: '7px',
                        borderRadius: '50%',
                        marginLeft: '5px',
                        verticalAlign: 'middle',
                        background: channelStatus.threads ? '#10B981' : '#F59E0B'
                      }}
                      title={channelStatus.threads ? 'Channel Ready' : 'Needs Configuration'}
                    />
                  )}
                </span>
              </div>
            </label>
          </div>
          {/* No per-post board picker: the practice has exactly one target
              board, configured once server-side (PINTEREST_BOARD_ID). The
              native engine reads it from there - a per-post field here would
              have no effect on the actual publish, only on this form. */}
        </div>

        {/* Scheduling & Approval Mode */}
        <div className="form-row-2">
          <div className="form-group">
            <label htmlFor="schedule-datetime" className="form-label">
              <span>Publish Schedule (IST)</span>
            </label>
            <input
              type="datetime-local"
              id="schedule-datetime"
              className="input-text"
              value={scheduledDateTime}
              onChange={(e) => {
                setScheduledDateTime(e.target.value);
                setActiveTimePreset('custom');
              }}
            />
            <div className="schedule-quick-options">
              <button
                type="button"
                className={`btn-time-quick ${activeTimePreset === 'asap' ? 'active' : ''}`}
                onClick={setPublishAsapTime}
              >
                ⚡ Publish ASAP
              </button>
              <button
                type="button"
                className={`btn-time-quick ${activeTimePreset === 'evening' ? 'active' : ''}`}
                onClick={setScheduleEvening}
              >
                🌆 Today 6:00 PM
              </button>
              <button
                type="button"
                className={`btn-time-quick ${activeTimePreset === 'tomorrow' ? 'active' : ''}`}
                onClick={setScheduleTomorrow}
              >
                🌅 Tomorrow 10:00 AM
              </button>
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="post-status-select" className="form-label">
              <span>Workflow Mode</span>
            </label>
            <select
              id="post-status-select"
              className="input-select"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="Pending Review">🛡️ Submit for Review (Sends Approval Notification)</option>
              <option value="Approved">🚀 Pre-Approved (Publish Directly on Schedule)</option>
              <option value="Draft">📝 Save as Draft</option>
            </select>
            <p className="field-help">
              {config.approverEmail
                ? `If "Pending Review" is selected, an approval email is sent to ${config.approverEmail} with [Approve] / [Decline] buttons.`
                : 'If "Pending Review" is selected, an approval notification is dispatched to reviewers before publishing.'}
            </p>
          </div>
        </div>

        {/* Submit & Progress Row */}
        <div className="form-submit-row">
          {isUploading && (
            <div className="progress-bar-container">
              <div className="progress-bar-fill" style={{ width: `${uploadProgress}%` }}></div>
              <span className="progress-text">{progressStatusText}</span>
            </div>
          )}

          <button type="submit" className="btn-primary" disabled={isUploading}>
            <Send size={18} />
            <span>{isUploading ? 'Uploading & Filing...' : 'Submit & Schedule Content'}</span>
          </button>
        </div>
      </form>
    </section>
  );
}
