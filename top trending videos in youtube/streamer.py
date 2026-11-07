"""
Clipper Streamer Service for 10M+ Trending Videos.
Streams discovered top-tier YouTube videos directly into the clipping pipeline,
triggering automated moment extraction, face-tracking gimbal, Hormozi subtitles,
and AI caption generation.
"""

from typing import Dict, Any, Optional, List
import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

from .fetcher import TopTrending10MFetcher, QualityTrendingVideo


class ClipperStreamer:
    """
    Streams curated videos from channels > 10M subscribers directly into the YouTube Clipper.
    Supports local web server streaming via HTTP API and in-process execution via RenderPipeline.
    """

    def __init__(self, studio_url: str = "http://localhost:8000"):
        self.studio_url = studio_url.rstrip("/")
        self.fetcher = TopTrending10MFetcher()

    def is_studio_online(self) -> bool:
        """Checks if the local Clipping Studio web server is active."""
        try:
            url = f"{self.studio_url}/api/v1/health"
            req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Streamer/1.0"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def stream_to_studio(
        self,
        video_url_or_id: str,
        max_clips: int = 3,
        layout: str = "active_speaker",
        subtitle_preset: str = "hormozi",
        gpu: bool = True,
    ) -> Dict[str, Any]:
        """
        Streams a video into the Clipping Studio server (POST /api/v1/render).
        Returns the created render job details.
        """
        payload = {
            "video_id_or_url": video_url_or_id,
            "max_clips": max_clips,
            "layout": layout,
            "subtitle_preset": subtitle_preset,
            "gpu": gpu,
        }

        url = f"{self.studio_url}/api/v1/render"
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Antigravity-Streamer/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                return {
                    "success": True,
                    "mode": "studio_api",
                    "job_id": res_data.get("job_id"),
                    "status": res_data.get("status", "discovering"),
                    "video_id": res_data.get("video_id"),
                    "title": res_data.get("title", ""),
                    "message": "Video successfully streamed to Clipping Studio! Open http://localhost:8000 to watch progress.",
                    "studio_url": f"{self.studio_url}/",
                }
        except urllib.error.URLError:
            # Fallback to local in-process pipeline if web server is not currently running
            return self.stream_in_process(
                video_url_or_id=video_url_or_id,
                max_clips=max_clips,
                layout=layout,
                subtitle_preset=subtitle_preset,
                gpu=gpu,
            )

    def stream_in_process(
        self,
        video_url_or_id: str,
        max_clips: int = 3,
        layout: str = "active_speaker",
        subtitle_preset: str = "hormozi",
        gpu: bool = False,
    ) -> Dict[str, Any]:
        """
        Streams a video directly using in-process Python pipeline when web server is offline.
        """
        try:
            from ..orchestration.pipeline import RenderPipeline
            pipeline = RenderPipeline()
            # Run moment discovery and rendering
            result = pipeline.run_pipeline(
                video_id_or_url=video_url_or_id,
                max_clips=max_clips,
                layout=layout,
                subtitle_preset=subtitle_preset,
                gpu=gpu,
            )
            return {
                "success": True,
                "mode": "in_process",
                "result": result,
                "message": f"Successfully processed {video_url_or_id} via in-process RenderPipeline.",
            }
        except Exception as e:
            return {
                "success": False,
                "mode": "in_process_fallback",
                "error": str(e),
                "message": f"Could not stream video to clipper: {e}",
            }

    def stream_top_video(
        self,
        max_clips: int = 3,
        layout: str = "active_speaker",
        subtitle_preset: str = "hormozi",
        gpu: bool = True,
    ) -> Dict[str, Any]:
        """
        Discovers the #1 highest-ranked video from channels > 10M subscribers
        and streams it immediately to the clipper.
        """
        videos = self.fetcher.get_top_trending_10m_list(limit=5)
        if not videos:
            return {"success": False, "message": "No trending videos found from 10M+ channels."}

        top_video = videos[0]
        print(f"[*] Streaming #1 Top Trending Video to Clipper:")
        print(f"    Title: {top_video.title}")
        print(f"    Creator: {top_video.channel_name} ({top_video.channel_subscribers_formatted} Subs)")
        print(f"    URL: {top_video.url}")
        print(f"    Virality Score: {top_video.virality_score}/100 ({top_video.clipping_suitability})")

        res = self.stream_to_studio(
            video_url_or_id=top_video.url,
            max_clips=max_clips,
            layout=layout,
            subtitle_preset=subtitle_preset,
            gpu=gpu,
        )
        res["video"] = top_video.to_dict()
        return res

    def export_fresh_links(
        self,
        json_path: str = "top_trending_videos_in_youtube/video_links.json",
        txt_path: str = "top_trending_videos_in_youtube/video_links.txt",
        limit: int = 20,
    ) -> List[QualityTrendingVideo]:
        """
        Refreshes trending videos from 10M+ channels and saves them into clean JSON and TXT link files.
        """
        videos = self.fetcher.get_top_trending_10m_list(limit=limit)

        # Write JSON
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([v.to_dict() for v in videos], f, indent=2, ensure_ascii=False)

        # Write plain TXT URLs
        os.makedirs(os.path.dirname(txt_path), exist_ok=True)
        with open(txt_path, "w", encoding="utf-8") as f:
            for v in videos:
                f.write(f"{v.url}\n")

        return videos
