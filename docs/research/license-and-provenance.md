# License, Provenance, and Policy Ledger

**Research Date:** 29 October 2026  
**Lead Orchestrator:** Antigravity Master Task — Agent B (License & Policy Auditor)

---

## 1. Component Provenance & Integration Decisions

| Component / Pattern | Upstream Source & Commit SHA | Upstream License | Master Repo Status | Conditions & Action Plan |
|---|---|---|---|---|
| **Highlight Chunking & Overlap Suppression** | `Anil-matcha/AI-Youtube-Shorts-Generator`<br>Commit: `315ea8d390b4791cc47151b14fd2cb5dfa94b147` | MIT | **Safe to Integrate (Adapted)** | Adapted into `src/yt_clipping/detection/segmenter.py`. Preserve MIT copyright notice in `THIRD_PARTY_NOTICES.md`. |
| **Hook vs Moment Scorecard Architecture** | `kleZ799/clipmint`<br>Commit: `9ddb5185bc7db2ae643d55c42588a21b3cabc2ff` | MIT | **Safe to Integrate (Adapted)** | Adapted into `src/yt_clipping/scoring/scorecard.py`. Include dual author attribution (Matcha & Bhadana). |
| **Checkpoint Journal & Post-Render QA** | `fralapo/clippyme`<br>Commit: `00b2f3a9d2b0cca8a77e7a51bc002f026d46d7ce` | MIT | **Safe to Integrate (Adapted)** | Adapted into `src/yt_clipping/orchestration/state_machine.py` and `src/yt_clipping/qa/verifier.py`. Full attribution in notices. |
| **Multi-Speaker Split Framing Pattern** | `mutonby/openshorts`<br>Commit: `b9f7a3564c54cc9d0e3f57effd83f20da74b8985` | MIT | **Pattern/Reference Only** | Layout concept referenced; code reimplemented cleanly in `src/yt_clipping/rendering/renderer.py`. |
| **Virality Metric & Caption Schema** | `FujiwaraChoki/supoclip`<br>Commit: `1b2f93a41d48c80c30807a1dda0c42a12c443cff` | **AGPL-3.0** | **Pattern/Reference Only** | **STRICT PROHIBITION:** No code or text copied from SupoClip into master repo core. Used solely as architectural reference to avoid copyleft taint. |
| **Channel Watchlist & Dedupe Cache** | `thevops/youtube-tracker`<br>Commit: `80b6db247254d6533ea14e98770a60f11e4f0e07` | MIT | **Safe to Integrate (Adapted)** | Adapted feed polling and hash caching in `src/yt_clipping/discovery/monitor.py`. |
| **View Velocity & Snapshot Delta Math** | `gpsyrou/tube-virality`<br>Commit: `f1a8e9...` | MIT | **Pattern/Reference Only** | Mathematical formulas for $\Delta \text{views} / \Delta t$ implemented cleanly in `src/yt_clipping/discovery/ranker.py`. |
| **Media Downloader Utility** | `yt-dlp/yt-dlp`<br>Release: `2026.02.04` | The Unlicense | **Integrate with Conditions** | Wrapped behind `AssetProvider` interface. **Condition:** Executed ONLY when source asset has verified `RightsManifest` (owner authorization, licensed archive, or operator asset). |
| **Scene Boundary Detection** | `Breakthrough/PySceneDetect`<br>Release: `v0.6.4` | BSD-3-Clause | **Integrate with Conditions** | Used via library interface for cut detection. BSD 3-Clause notices preserved. |
| **Face & Subject Tracking** | `google-ai-edge/mediapipe`<br>Release: `v0.10.14` | Apache-2.0 | **Integrate with Conditions** | Used via programmatic library API. Apache 2.0 notices preserved. |
| **Subtitle Word Timing & Formatting** | `jianfch/stable-ts`<br>Release: `v2.17.4` | MIT | **Safe to Integrate (Adapted)** | Subtitle margin and ASS format generation adapted into `src/yt_clipping/rendering/captions.py`. |

---

## 2. Platform Compliance & YouTube Terms of Service

### YouTube API Services Developer Policies
1. **Audiovisual Content Restrictions (Section III.E):**  
   API clients must **not** download, import, backup, cache, or store copies of YouTube audiovisual content without YouTube's prior written permission.  
   *Implementation Guarantee:* The discovery engine collects metadata only. Media retrieval requires explicit confirmation of content owner authorization or an operator-supplied source file.
2. **Scraping Prohibition:**  
   Bypassing bot detection, rotating scraping proxies, or parsing undocumented internal YouTube endpoints is prohibited.  
   *Implementation Guarantee:* Discovery utilizes official YouTube Data API v3 endpoints (`playlistItems.list`, `videos.list`) or public channel RSS feeds. No scraping techniques from projects like `youtube-scrapy-scraper` are permitted.
3. **Cross-Owner Data Aggregation:**  
   Aggregating API data across unrelated content owners for competitive benchmarking or commercial resale is restricted under API terms.  
   *Implementation Guarantee:* Channel monitoring is scoped strictly to configured user-authorized channels. Metrics are retained locally with expiration checkpoints.
4. **Separation of Public Views from Audience Retention:**  
   Public view counts represent cumulative video impressions and do not indicate retention peaks. The `audienceWatchRatio` metric is available exclusively via the YouTube Analytics API to authenticated channel owners. Highlight scores generated from transcripts or audio are formally labeled as **Predicted Highlight Scores**; retention is never simulated or falsely attributed to public metrics.

---

## 3. FFmpeg Licensing and Codec Considerations

FFmpeg is licensed under the **LGPL v2.1+** by default, but switches to **GPL v2.0+** or **GPL v3.0+** when compiled with specific options:
- Enabling `--enable-gpl` (required for `libx264`, `libx265`, `libxvid`).
- Enabling `--enable-nonfree` (required for certain proprietary hardware encoders like `libfdk_aac`).

### Master Repository Architecture Decision:
- The master repository executes FFmpeg strictly via isolated **subprocess command-line invocation** and does not link FFmpeg C-libraries dynamically or statically.
- The pipeline supports standard h264/aac encoding profiles. Users providing custom FFmpeg builds retain full compliance with their local binary licenses.
- Subprocess arguments are constructed deterministically with explicit codec fallback flags (`-c:v libx264` with fallback to native `-c:v h264_nvenc` or copy).

---

## 4. Rights Gate State Machine

To enforce lawful operations, every asset must traverse a deterministic rights verification gate before reaching any downstream stage:

```text
[Source Registered] 
        |
        v
[Rights Policy Check]
   |             |
   | (Invalid)   | (Verified: Owner / Authorized / CC BY)
   v             v
[BLOCKED:       [Asset Ingestion & Probe]
 Review Task            |
 Created]               v
                [Transcribe & Highlight Detection]
                        |
                        v
                [Render Vertical Clip]
                        |
                        v
                [Post-Render QA Verification]
                        |
                        v
                [Approved Handoff to Autopost]
```

A rights failure halts pipeline progress immediately. Media download, video rendering, and external handoff are strictly blocked until manual or cryptographic proof of rights is attached.
