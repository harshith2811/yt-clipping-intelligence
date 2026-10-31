# Virality Scoring, Early-Hour Velocity & Creator Attribution Engine

Technical specification for zero-quota detection, statistical velocity analysis, and legal attribution governance.

---

## 1. Zero-Quota Polling & WebSub Architecture

To monitor hundreds of creator channels without exhausting YouTube Data API v3 quota limits (10,000 units/day), the platform uses YouTube's public Atom XML syndication feeds:

$$\text{Feed URL} = \text{https://www.youtube.com/feeds/videos.xml?channel\_id}=\{CHANNEL\_ID\}$$

### Conditional GET with ETag & If-Modified-Since
Every outgoing HTTP request transmits cached headers:
- `If-None-Match`: Previously stored `ETag` string.
- `If-Modified-Since`: Previously recorded `Last-Modified` timestamp.

When no new video has been published, YouTube's CDN returns **HTTP 304 Not Modified**, transmitting empty response bodies and consuming zero API quota units.

### WebSub (PubSubHubbub) Push Notifications
For sub-second alerts, the daemon features an integrated W3C WebSub HTTP listener (`/websub`):
1. **Subscription Validation:** Responds to hub verification challenges (`hub.challenge`) echoing the verification token with HTTP 200.
2. **Push Delivery:** Hub dispatches an HTTP POST payload containing XML Atom snippets the moment a video transitions to public status on YouTube.

---

## 2. Statistical Virality Algorithm

### A. Hourly View Velocity ($V_{\text{hourly}}$)
Measures the real-time velocity of views accumulated since publication, clamping young videos (< 15 min) to prevent divide-by-zero singularities:

$$V_{\text{hourly}} = \frac{\text{Current Views}}{\max(\text{Age in Hours}, 0.25)}$$

### B. Baseline Velocity & Velocity Multiplier ($M_v$)
Normalizes current view performance against the creator's 30-day baseline over a standard 48-hour maturity window:

$$V_{\text{baseline}} = \max\left(\frac{\text{Baseline Views}}{48.0}, 10.0\right)$$

$$M_v = \frac{V_{\text{hourly}}}{V_{\text{baseline}}}$$

### C. Virality Classification Tiering
Candidate uploads are categorized based on their velocity multiplier:
- **$M_v \ge 3.0\times$**: `VIRAL_EXPLOSION` $\rightarrow$ Leased with `JobPriority.CRITICAL`.
- **$1.5\times \le M_v < 3.0\times$**: `TRENDING_HIGH` $\rightarrow$ Leased with `JobPriority.HIGH`.
- **$0.8\times \le M_v < 1.5\times$**: `STEADY` $\rightarrow$ Evaluated normally.
- **$M_v < 0.8\times$**: `UNDERPERFORMING` $\rightarrow$ Logged without immediate queuing.

---

## 3. Audience Resonance & Clickbait Filtering

Raw view counts alone can be skewed by bot networks, misleading thumbnails, or synthetic spikes. The platform validates viewer resonance before approving highlight extraction:

$$\text{Like-to-View Ratio (LVR)} = \frac{\text{Likes}}{\text{Views}} \ge 1.2\%$$

$$\text{Comment-to-View Ratio (CVR)} = \frac{\text{Comments}}{\text{Views}} \ge 0.03\%$$

- Uploads failing the threshold are marked `is_resonant = False` with telemetry flags (`SUSPICIOUS_LOW_LIKE_RATIO`, `SUSPICIOUS_LOW_COMMENT_RATIO`) and disqualified from automated priority queuing.

---

## 4. Attribution & Legal Compliance Engine

### A. Structured Caption Formatting
Every generated short automatically receives an attribution package formatted for social distribution:

```text
Original Content by: @{Creator_Handle} ({Creator_Name})
Watch the full episode: https://youtu.be/{VIDEO_ID}

Curated for educational discussion, commentary, and audience discovery. 
All media and intellectual property rights belong to the original creator.

#shorts #podcast #highlights #{Tag1} #{Tag2} #{CreatorTag}
```

### B. Sponsor & Ad Purge
To prevent commercial trademark dilution or third-party sponsor conflicts, promotional segments are detected via regex token matching and excluded:
- Targeted keywords: `sponsored by`, `use code`, `link in description`, `percent off`, `patreon`, `merch`, `displate`, `nordvpn`, `betterhelp`, `ag1`, `athletic greens`.
- Matches are purged from generated descriptions and candidate transcripts.

### C. Creator Policy Governance Matrix
| Policy Type | Commercial Allowed | Manual Approval | Automated Clipping Behavior |
| :--- | :---: | :---: | :--- |
| `OPEN_AFFILIATE` | Yes | No | Instant auto-clipping and publication with attribution. |
| `CREATIVE_COMMONS` | Yes | No | Permitted under CC-BY guidelines. |
| `PARTNER_PROGRAM` | Yes | Yes | Queues highlight; requires operator sign-off before dispatch. |
| `STRICT_COPYRIGHT` | No | Yes | **QUARANTINED.** Hard-blocked to prevent DMCA strikes. |
