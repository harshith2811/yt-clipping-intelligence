# Top Trending Videos in YouTube (10M+ Subscriber Channels)

This component automatically discovers, verifies, and exports high-retention trending YouTube videos exclusively from channels with **greater than 10,000,000 subscribers**, preparing them for direct streaming into the Autonomous YouTube Clipping Studio.

---

## 🎯 Why 10M+ Channels Only?
1. **Audience-Tested Pacing & Hooks:** Creators with > 10M subscribers (MrBeast, Marques Brownlee, Veritasium, Mark Rober, SmarterEveryDay, Kurzgesagt) invest hundreds of thousands of dollars into story structure, retention engineering, and visual quality.
2. **High-Definition Clean A/V:** Broadcast-grade 4K/1080p source video with crisp studio speech, ideal for face-tracking kinematics and anti-pop audio gates.
3. **High Virality Conversion:** Micro-clips cut from 10M+ creator long-form content consistently yield 2–5x higher retention metrics on YouTube Shorts, Instagram Reels, and TikTok.

---

## 📁 Output Artifacts
* **`video_links.json`**: Structured JSON catalog containing full metadata: video ID, direct URL, title, creator name, subscriber count (e.g. `21.4M`, `525M`), duration, view count, and clipping suitability rating.
* **`video_links.txt`**: Clean, line-delimited list of YouTube URLs ready for immediate piping or batch processing.

---

## 🚀 How to Use & Stream to Clipper

### 1. Refresh & List Trending Videos
```bash
# Refresh and list top trending videos
python -m top_trending_videos_in_youtube list

# Export top 20 trending videos
python -m top_trending_videos_in_youtube fetch --limit 20
```

### 2. Stream Directly to the Clipper
```bash
# Auto-select the #1 highest-ranked trending video and stream it to the clipper
python -m top_trending_videos_in_youtube stream

# Stream with custom parameters (e.g., 5 clips, split screen)
python -m top_trending_videos_in_youtube stream --clips 5 --layout split_screen --preset hormozi

# Stream a specific video URL from the list
python -m top_trending_videos_in_youtube stream --url https://www.youtube.com/watch?v=vS6HEes8daw
```

### 3. List Verified 10M+ Channel Registry
```bash
python -m top_trending_videos_in_youtube channels
```

### 4. In Python Code
```python
from top_trending_videos_in_youtube import TopTrending10MFetcher, ClipperStreamer

fetcher = TopTrending10MFetcher()
videos = fetcher.get_top_trending_10m_list(limit=10)

streamer = ClipperStreamer()
result = streamer.stream_top_video()
print("Render Job Started:", result["job_id"])
```

---

## 🌐 Web Studio Integration (`http://localhost:8000`)
The Web Studio directly integrates this component via:
* `GET /api/v1/trending/top10m`: Returns live ranked 10M+ trending videos.
* `POST /api/v1/trending/stream`: Streams a selected trending video directly into the clipper.
