"""
Registry and Verification Engine for Premier YouTube Channels (> 10M Subscribers).
Provides curated list of verified 10M+ subscriber channels across high-retention clipping niches
and dynamic API verification functions to guarantee only channels with >= 10M subscribers are used.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any
import os
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv()

MIN_SUBSCRIBER_THRESHOLD = 10_000_000  # 10 Million Subscribers


@dataclass
class ChannelInfo:
    channel_id: str
    handle: str
    title: str
    subscriber_count: int
    category: str
    baseline_views: float
    uploads_playlist_id: str

    @property
    def subscriber_count_formatted(self) -> str:
        """Formats subscriber count into human-readable representation (e.g. 21.4M)."""
        if self.subscriber_count >= 1_000_000_000:
            return f"{self.subscriber_count / 1_000_000_000:.1f}B"
        elif self.subscriber_count >= 1_000_000:
            return f"{self.subscriber_count / 1_000_000:.1f}M"
        elif self.subscriber_count >= 1_000:
            return f"{self.subscriber_count / 1_000:.1f}K"
        return str(self.subscriber_count)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["subscriber_count_formatted"] = self.subscriber_count_formatted
        d["url"] = f"https://www.youtube.com/{self.handle}"
        return d


# Pre-verified 10M+ Channels categorized by high-retention clipping potential
VERIFIED_10M_CHANNELS: List[ChannelInfo] = [
    # --- Science, Education & Engineering ---
    ChannelInfo(
        channel_id="UCY1kMZp36IQSyNx_9h4mpCg",
        handle="@markrober",
        title="Mark Rober",
        subscriber_count=85_800_000,
        category="Science & Engineering",
        baseline_views=35_000_000.0,
        uploads_playlist_id="UUY1kMZp36IQSyNx_9h4mpCg",
    ),
    ChannelInfo(
        channel_id="UCHnyfMqiRRG1u-2MsSQLbXA",
        handle="@veritasium",
        title="Veritasium",
        subscriber_count=21_400_000,
        category="Science & Education",
        baseline_views=8_000_000.0,
        uploads_playlist_id="UUHnyfMqiRRG1u-2MsSQLbXA",
    ),
    ChannelInfo(
        channel_id="UCsXVk37bltHxD1rDPwtNM8Q",
        handle="@kurzgesagt",
        title="Kurzgesagt – In a Nutshell",
        subscriber_count=25_800_000,
        category="Science & Animation",
        baseline_views=9_500_000.0,
        uploads_playlist_id="UUsXVk37bltHxD1rDPwtNM8Q",
    ),
    ChannelInfo(
        channel_id="UC6nSFpj9HTCZ5t-N3Rm3-HA",
        handle="@Vsauce",
        title="Vsauce",
        subscriber_count=25_300_000,
        category="Science & Philosophy",
        baseline_views=7_000_000.0,
        uploads_playlist_id="UU6nSFpj9HTCZ5t-N3Rm3-HA",
    ),
    ChannelInfo(
        channel_id="UC6107grRI4m0o2-emgoDnAA",
        handle="@smartereveryday",
        title="SmarterEveryDay",
        subscriber_count=11_900_000,
        category="Science & Exploration",
        baseline_views=5_000_000.0,
        uploads_playlist_id="UU6107grRI4m0o2-emgoDnAA",
    ),
    ChannelInfo(
        channel_id="UCAuUUnT6oDeKwE6v1NGQxug",
        handle="@TED",
        title="TED",
        subscriber_count=28_000_000,
        category="Ideas & Talks",
        baseline_views=1_200_000.0,
        uploads_playlist_id="UUAuUUnT6oDeKwE6v1NGQxug",
    ),
    ChannelInfo(
        channel_id="UCpVm7bg6pXKo1Pr6k5kxG9A",
        handle="@natgeo",
        title="National Geographic",
        subscriber_count=26_600_000,
        category="Nature & Exploration",
        baseline_views=1_500_000.0,
        uploads_playlist_id="UUpVm7bg6pXKo1Pr6k5kxG9A",
    ),
    ChannelInfo(
        channel_id="UCX6b17PVsYBQ0ip5gyeme-Q",
        handle="@crashcourse",
        title="CrashCourse",
        subscriber_count=17_300_000,
        category="Education & History",
        baseline_views=800_000.0,
        uploads_playlist_id="UUX6b17PVsYBQ0ip5gyeme-Q",
    ),

    # --- Technology & Gear ---
    ChannelInfo(
        channel_id="UCBJycsmduvYEL83R_U4JriQ",
        handle="@mkbhd",
        title="Marques Brownlee",
        subscriber_count=21_400_000,
        category="Technology & Gadgets",
        baseline_views=4_500_000.0,
        uploads_playlist_id="UUBJycsmduvYEL83R_U4JriQ",
    ),
    ChannelInfo(
        channel_id="UCXuqSBlHAE6Xw-yeJA0Tunw",
        handle="@LinusTechTips",
        title="Linus Tech Tips",
        subscriber_count=16_900_000,
        category="Tech & Hardware",
        baseline_views=2_000_000.0,
        uploads_playlist_id="UUXuqSBlHAE6Xw-yeJA0Tunw",
    ),
    ChannelInfo(
        channel_id="UCsTcErHg8oDvUnTzoqsYeNw",
        handle="@unboxtherapy",
        title="Unbox Therapy",
        subscriber_count=25_600_000,
        category="Tech & Unboxing",
        baseline_views=2_500_000.0,
        uploads_playlist_id="UUsTcErHg8oDvUnTzoqsYeNw",
    ),

    # --- High-Production Entertainment & Storytelling ---
    ChannelInfo(
        channel_id="UCX6OQ3DkcsbYNE6H8uQQuVA",
        handle="@MrBeast",
        title="MrBeast",
        subscriber_count=525_000_000,
        category="High-Concept Entertainment",
        baseline_views=150_000_000.0,
        uploads_playlist_id="UUX6OQ3DkcsbYNE6H8uQQuVA",
    ),
    ChannelInfo(
        channel_id="UCRijo3ddMTht_IHyNSNXpNQ",
        handle="@dudeperfect",
        title="Dude Perfect",
        subscriber_count=62_800_000,
        category="Action & Stunts",
        baseline_views=18_000_000.0,
        uploads_playlist_id="UURijo3ddMTht_IHyNSNXpNQ",
    ),
    ChannelInfo(
        channel_id="UC-lHJZR3Gqxm24_Vd_AJ5Yw",
        handle="@pewdiepie",
        title="PewDiePie",
        subscriber_count=109_000_000,
        category="Commentary & Gaming",
        baseline_views=4_000_000.0,
        uploads_playlist_id="UU-lHJZR3Gqxm24_Vd_AJ5Yw",
    ),
    ChannelInfo(
        channel_id="UCDogdKl7t7NHzQ95aEwkdMw",
        handle="@sidemen",
        title="Sidemen",
        subscriber_count=23_400_000,
        category="Group Entertainment",
        baseline_views=8_000_000.0,
        uploads_playlist_id="UUDogdKl7t7NHzQ95aEwkdMw",
    ),
    ChannelInfo(
        channel_id="UCJjSDX-jUChzOEyok9XYRJQ",
        handle="@jubilee",
        title="Jubilee",
        subscriber_count=11_000_000,
        category="Social Experiments & Debates",
        baseline_views=3_500_000.0,
        uploads_playlist_id="UUJjSDX-jUChzOEyok9XYRJQ",
    ),
]


def get_channel_by_id(channel_id: str) -> Optional[ChannelInfo]:
    """Finds channel by canonical channel ID."""
    for ch in VERIFIED_10M_CHANNELS:
        if ch.channel_id == channel_id:
            return ch
    return None


def verify_channels_batch(channel_ids: List[str], api_key: Optional[str] = None) -> Dict[str, ChannelInfo]:
    """
    Batches channel IDs up to 50 at a time and retrieves official statistics
    from YouTube Data API v3, filtering for channels with >= 10M subscribers.
    """
    key = api_key or os.getenv("YOUTUBE_API_KEY")
    if not key or not channel_ids:
        # Fallback to local verified registry
        return {ch.channel_id: ch for ch in VERIFIED_10M_CHANNELS if ch.channel_id in channel_ids}

    verified: Dict[str, ChannelInfo] = {}
    # Batch in chunks of 50
    for i in range(0, len(channel_ids), 50):
        chunk = channel_ids[i:i + 50]
        ids_param = ",".join(chunk)
        url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&id={ids_param}&key={key}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-10M-Verifier/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            for item in data.get("items", []):
                cid = item.get("id", "")
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                subs = int(stats.get("subscriberCount", 0))

                if subs >= MIN_SUBSCRIBER_THRESHOLD:
                    handle = snippet.get("customUrl", f"@{cid}")
                    if not handle.startswith("@"):
                        handle = "@" + handle
                    uploads_id = "UU" + cid[2:] if cid.startswith("UC") else cid

                    info = ChannelInfo(
                        channel_id=cid,
                        handle=handle,
                        title=snippet.get("title", "YouTube Creator"),
                        subscriber_count=subs,
                        category="Trending 10M+",
                        baseline_views=float(stats.get("viewCount", 0)) / max(float(stats.get("videoCount", 1)), 1.0),
                        uploads_playlist_id=uploads_id,
                    )
                    verified[cid] = info
        except Exception:
            # On network/quota error, fallback to known registry
            for cid in chunk:
                local_ch = get_channel_by_id(cid)
                if local_ch:
                    verified[cid] = local_ch

    return verified
