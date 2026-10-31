"""
Channel Watcher CLI Management Tool.
Provides operational commands to add, list, pause, resume, scan,
and inspect monitored creator channels and their clipping policies.
"""

from typing import Optional, List, Dict, Any, Tuple
import argparse
import sys
import json
import os
import urllib.request
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..orchestration.db import DatabaseManager
from .attribution_engine import CreatorPolicy, AttributionEngine
from .trend_scorer import TrendScorer
from .pinger_daemon import PingerDaemon

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def resolve_channel_identifier(identifier: str) -> Tuple[str, str, str]:
    """
    Resolves channel handle (@handle), URL, or raw ID into (channel_id, handle, name).
    Uses lightweight web scraping of channel page if not starting with UC.
    """
    ident = identifier.strip()

    # If already a canonical channel ID
    if ident.startswith("UC") and "/" not in ident and not ident.startswith("@"):
        return ident, f"@{ident}", ident

    # Extract handle or path
    handle = ""
    if "youtube.com" in ident or "youtu.be" in ident:
        parsed = urlparse(ident)
        path = parsed.path.strip("/")
        if path.startswith("channel/UC"):
            cid = path.split("/")[1]
            return cid, f"@{cid}", cid
        elif path.startswith("@"):
            handle = path.split("/")[0]
        elif path.startswith("c/") or path.startswith("user/"):
            handle = "@" + path.split("/")[1]
    elif ident.startswith("@"):
        handle = ident
    else:
        handle = f"@{ident}"

    # 1. Check YouTube Data API v3 for rapid official handle resolution if key is present
    api_key = os.getenv("YOUTUBE_API_KEY")
    if api_key and handle:
        try:
            handle_clean = handle.lstrip("@")
            api_url = f"https://www.googleapis.com/youtube/v3/channels?part=id,snippet&forHandle={handle_clean}&key={api_key}"
            req = urllib.request.Request(api_url, headers={"User-Agent": "Antigravity-Watcher/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if items:
                    cid = items[0]["id"]
                    title = items[0].get("snippet", {}).get("title", handle[1:])
                    return cid, handle, title
        except Exception:
            pass

    # 2. Resolve handle to channel_id by fetching channel HTML
    channel_url = f"https://www.youtube.com/{handle}"
    req = urllib.request.Request(channel_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            # Look for channelId or externalId
            m = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)
            if not m:
                m = re.search(r'itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]{22})"', html)
            if m:
                cid = m.group(1)
                # Look for channel title
                title_m = re.search(r'<meta property="og:title"\s+content="([^"]+)"', html)
                name = title_m.group(1) if title_m else handle[1:]
                return cid, handle, name
    except Exception:
        pass

    # If offline or resolution fails, fallback to sanitized handle
    fallback_id = f"UC{re.sub(r'[^a-zA-Z0-9]', '', handle)[:22]}"
    return fallback_id, handle, handle[1:]


class ChannelWatcher:
    """
    Manages channel registry persistence and manual live scan sweeps.
    """

    def __init__(self, db_path: str = "data/jobs.db"):
        self.db = DatabaseManager(db_path)
        self.attribution_engine = AttributionEngine(db_path)
        self.trend_scorer = TrendScorer(db_path)

    def add_channel(
        self,
        identifier: str,
        name: Optional[str] = None,
        baseline_views: float = 20000.0,
        policy: CreatorPolicy = CreatorPolicy.OPEN_AFFILIATE,
    ) -> Dict[str, Any]:
        """Adds or updates a monitored channel in the SQLite registry."""
        cid, handle, resolved_name = resolve_channel_identifier(identifier)
        final_name = name or resolved_name
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = self.db.get_connection()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT INTO monitored_channels (
                        channel_id, name, channel_url, handle, baseline_views, active, clipping_policy, created_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        name=excluded.name,
                        handle=excluded.handle,
                        baseline_views=excluded.baseline_views,
                        clipping_policy=excluded.clipping_policy,
                        active=1,
                        paused=0
                    """,
                    (
                        cid,
                        final_name,
                        f"https://www.youtube.com/{handle}",
                        handle,
                        baseline_views,
                        policy.value,
                        now_iso,
                    ),
                )
        finally:
            conn.close()

        # Save permission in a separate transaction to avoid concurrent locks
        self.attribution_engine.set_creator_policy(
            channel_id=cid,
            channel_name=final_name,
            policy=policy,
            notes=f"Registered via ChannelWatcher CLI for {handle}",
        )

        return {
            "channel_id": cid,
            "name": final_name,
            "handle": handle,
            "baseline_views": baseline_views,
            "policy": policy.value,
        }

    def list_channels(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """Lists all registered channels."""
        conn = self.db.get_connection()
        try:
            query = "SELECT channel_id, name, handle, baseline_views, active, paused, clipping_policy, last_polled_at FROM monitored_channels"
            if active_only:
                query += " WHERE active = 1 AND paused = 0"
            cursor = conn.execute(query)
            cols = [col[0] for col in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def set_pause(self, channel_id: str, paused: bool) -> bool:
        """Pauses or resumes monitoring for a channel."""
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE monitored_channels SET paused = ? WHERE channel_id = ? OR handle = ?",
                    (1 if paused else 0, channel_id, channel_id),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def remove_channel(self, channel_id: str) -> bool:
        """Deactivates a monitored channel."""
        conn = self.db.get_connection()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE monitored_channels SET active = 0 WHERE channel_id = ? OR handle = ?",
                    (channel_id, channel_id),
                )
                return cursor.rowcount > 0
        finally:
            conn.close()

    def scan_now(self) -> List[Dict[str, Any]]:
        """Triggers an immediate live RSS discovery sweep of all active channels."""
        daemon = PingerDaemon(db_path=self.db.db_path)
        daemon.poll_all_channels_once()

        # Fetch recently discovered uploads
        conn = self.db.get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT video_id, channel_id, title, published_at, hourly_velocity,
                       velocity_multiplier, virality_classification, status
                FROM discovered_uploads
                ORDER BY velocity_multiplier DESC
                LIMIT 20
                """
            )
            cols = [col[0] for col in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="YouTube Channel Watcher & Clipping Registry CLI")
    subparsers = parser.add_subparsers(dest="subcmd", help="Subcommand to execute")

    # add
    p_add = subparsers.add_parser("add", help="Add or update a monitored creator")
    p_add.add_argument("identifier", help="Channel @handle, URL, or UC... ID")
    p_add.add_argument("--name", default=None, help="Creator display name (optional)")
    p_add.add_argument("--baseline", type=float, default=20000.0, help="Expected 48h view baseline (default: 20000)")
    p_add.add_argument("--policy", choices=["OPEN_AFFILIATE", "CREATIVE_COMMONS", "PARTNER_PROGRAM", "STRICT_COPYRIGHT"], default="OPEN_AFFILIATE", help="Clipping rights policy")

    # list
    p_list = subparsers.add_parser("list", help="List monitored channels")
    p_list.add_argument("--all", action="store_true", help="Include inactive/paused channels")

    # pause
    p_pause = subparsers.add_parser("pause", help="Pause monitoring for a channel")
    p_pause.add_argument("channel", help="Channel ID or handle")

    # resume
    p_resume = subparsers.add_parser("resume", help="Resume monitoring for a channel")
    p_resume.add_argument("channel", help="Channel ID or handle")

    # remove
    p_rm = subparsers.add_parser("remove", help="Remove/deactivate a channel")
    p_rm.add_argument("channel", help="Channel ID or handle")

    # scan
    p_scan = subparsers.add_parser("scan", help="Trigger immediate discovery sweep of all channels")

    # test-feed
    p_tf = subparsers.add_parser("test-feed", help="Test fetching and parsing a YouTube RSS/Atom feed")
    p_tf.add_argument("identifier", help="Channel handle or UC... ID")

    args = parser.parse_args()
    if not args.subcmd:
        parser.print_help()
        sys.exit(1)

    watcher = ChannelWatcher()

    if args.subcmd == "add":
        pol = CreatorPolicy(args.policy)
        res = watcher.add_channel(args.identifier, name=args.name, baseline_views=args.baseline, policy=pol)
        print(f"[OK] Added/Updated Monitored Channel:")
        print(f"  Name     : {res['name']}")
        print(f"  ChannelID: {res['channel_id']}")
        print(f"  Handle   : {res['handle']}")
        print(f"  Baseline : {res['baseline_views']:,.0f} views")
        print(f"  Policy   : {res['policy']}")

    elif args.subcmd == "list":
        channels = watcher.list_channels(active_only=not args.all)
        print(f"\n[OK] Monitored Channels ({len(channels)} total):")
        print("-" * 75)
        for ch in channels:
            status = "PAUSED" if ch.get("paused") else ("ACTIVE" if ch.get("active") else "INACTIVE")
            print(f"  [{status}] {ch['name']} ({ch['handle'] or ch['channel_id']})")
            print(f"       ID      : {ch['channel_id']}")
            print(f"       Policy  : {ch.get('clipping_policy', 'OPEN_AFFILIATE')}")
            print(f"       Baseline: {ch.get('baseline_views', 0):,.0f} views | Last Polled: {ch.get('last_polled_at') or 'Never'}")
        print("-" * 75)

    elif args.subcmd == "pause":
        ok = watcher.set_pause(args.channel, paused=True)
        print(f"[{'OK' if ok else 'WARN'}] Paused monitoring for '{args.channel}'.")

    elif args.subcmd == "resume":
        ok = watcher.set_pause(args.channel, paused=False)
        print(f"[{'OK' if ok else 'WARN'}] Resumed monitoring for '{args.channel}'.")

    elif args.subcmd == "remove":
        ok = watcher.remove_channel(args.channel)
        print(f"[{'OK' if ok else 'WARN'}] Deactivated channel '{args.channel}'.")

    elif args.subcmd == "scan":
        print("[*] Running immediate live RSS discovery sweep on all active channels...")
        results = watcher.scan_now()
        print(f"\n[OK] Scan complete! Top Discovered Uploads ({len(results)} total):")
        for r in results:
            title_text = str(r['title']).encode("ascii", "replace").decode("ascii") if sys.platform == "win32" and not sys.stdout.encoding.lower().startswith("utf") else str(r['title'])
            print(f"  - [{r['virality_classification']}] {title_text} ({r['video_id']})")
            print(f"    Velocity Multiplier: {r['velocity_multiplier']:.1f}x | Hourly Velocity: {r['hourly_velocity']:,.0f} views/hr | Status: {r['status']}")

    elif args.subcmd == "test-feed":
        cid, handle, name = resolve_channel_identifier(args.identifier)
        print(f"[*] Testing RSS feed for {name} ({cid})...")
        daemon = PingerDaemon()
        xml_data, modified, etag, last_mod = daemon.fetch_channel_feed(cid)
        if xml_data:
            videos = daemon.parse_atom_feed(xml_data)
            print(f"[OK] Successfully parsed {len(videos)} recent uploads from feed!")
            for v in videos[:5]:
                t_text = str(v['title']).encode("ascii", "replace").decode("ascii") if sys.platform == "win32" and not sys.stdout.encoding.lower().startswith("utf") else str(v['title'])
                print(f"  - {t_text} (ID: {v['video_id']}, Published: {v['published_at']})")
        else:
            print("[WARN] Feed returned empty or not modified.")


if __name__ == "__main__":
    main()
