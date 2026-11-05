"""
Discovery, heatmap, trend analysis, channel registry, and daemon commands for CLI.
"""

import argparse
import json
from datetime import datetime, timezone

from ...contracts.models import CreatorSource, VideoCandidate, RightsStatus
from ...discovery.monitor import ChannelMonitor
from ...discovery.ranker import PublicMetricRanker
from ...discovery.heatmap import HeatmapAnalyzer
from ...discovery.trend_analyzer import TrendAnalyzer
from ...discovery.channel_registry import ChannelRegistry
from ...discovery.daemon import DiscoveryDaemon


def cmd_discovery(args: argparse.Namespace) -> None:
    monitor = ChannelMonitor()
    ranker = PublicMetricRanker()

    creator = CreatorSource(
        creator_id=args.channel_id,
        name=args.channel_name or args.channel_id,
        channel_id=args.channel_id,
        channel_url=f"https://www.youtube.com/channel/{args.channel_id}",
        baseline_views=args.avg_views,
    )
    monitor.register_creator(creator)

    now_iso = datetime.now(timezone.utc).isoformat()
    candidate = VideoCandidate(
        video_id=args.sample_video_id,
        title=args.sample_title or f"Recent Upload from {creator.name}",
        url=f"https://www.youtube.com/watch?v={args.sample_video_id}",
        creator_id=args.channel_id,
        published_at=now_iso,
        retrieved_at=now_iso,
        duration_seconds=args.duration,
        view_count=args.views,
        rights_status=RightsStatus.VERIFIED,
    )
    monitor.register_mock_video(args.channel_id, candidate)

    discovered = monitor.fetch_recent_videos(args.channel_id)
    print(f"[*] Discovery results for channel '{creator.name}':")
    for v in discovered:
        ranker.record_snapshot(
            v.video_id,
            int(v.view_count * 0.8),
            like_count=500,
        )
        ranker.record_snapshot(
            v.video_id,
            v.view_count,
            like_count=800,
        )

        snapshots = ranker._snapshots.get(v.video_id, [])
        velocity = ranker.calculate_view_velocity(snapshots)
        score = ranker.compute_discovery_score(v, creator)

        print(f"\n- Video: {v.video_id} | Title: {v.title}")
        print(f"  Public Views: {v.view_count:,} | Duration: {v.duration_seconds:.0f}s")
        print(f"  Observed View Velocity: {velocity:.1f} views/hour")
        print(f"  Channel-Normalized Discovery Score: {score:.1f}/100")


def cmd_heatmap(args: argparse.Namespace) -> None:
    analyzer = HeatmapAnalyzer(cache_dir=args.cache_dir)
    print(f"[*] Extracting audience retention heatmap for: {args.video_id}")
    hm = analyzer.extract_heatmap(args.video_id)
    print(f"\n[OK] Heatmap Ingestion Source: {hm.source} ({len(hm.points)} points)")
    if hm.global_peak:
        gp = hm.global_peak
        print(f"Global Peak (#1 Most Replayed): {gp.center_time:.1f}s ({gp.center_time/60:.1f}m) | Intensity: {gp.intensity*100:.1f}%, Prominence: {gp.prominence*100:.1f}%")
        print(f"Recommended Clip Window: {gp.suggested_clip_start:.1f}s -> {gp.suggested_clip_end:.1f}s ({gp.suggested_clip_end - gp.suggested_clip_start:.1f}s duration)")

    print(f"\nDetected {len(hm.peaks)} Prominent Viral Peaks:")
    for idx, pk in enumerate(hm.peaks[:6], 1):
        print(f"  #{idx} [{pk.classification}] At {pk.center_time:.1f}s ({pk.center_time/60:.1f}m) | "
              f"Intensity: {pk.intensity*100:.1f}% | Prominence: {pk.prominence*100:.1f}% | "
              f"Window: {pk.suggested_clip_start:.1f}s - {pk.suggested_clip_end:.1f}s")

    if args.visual:
        print("\n" + analyzer.render_ascii_curve(hm))


def cmd_trends(args: argparse.Namespace) -> None:
    analyzer = TrendAnalyzer()
    if args.chart:
        print(f"[*] Querying YouTube Trending Chart (region={args.region}, limit={args.limit})...")
        trending = analyzer.fetch_trending_chart(region_code=args.region, category_id=args.category, limit=args.limit)
        if not trending:
            print("[WARN] No trending videos returned. Check YouTube Data API key in .env.")
            return

        print(f"\n[OK] Found {len(trending)} Trending Videos Ranked by Virality Index:")
        for idx, t in enumerate(trending, 1):
            print(f"\n#{idx} [{t.classification}] {t.title}")
            print(f"    Video ID: {t.video_id} | Channel: {t.channel_title}")
            print(f"    Views: {t.view_count:,} | Velocity: {t.view_velocity_per_hour:,.0f} views/hr ({t.velocity_multiplier:.1f}x baseline)")
            print(f"    Engagement: Likes={t.like_ratio_pct:.2f}%, Comments={t.comment_ratio_pct:.3f}% | Virality Index: {t.virality_index}/100")
            print(f"    Rationale: {t.rationale}")
    elif args.video_id:
        print(f"[*] Analyzing real-time virality telemetry for video: {args.video_id}")
        report = analyzer.analyze_video_id(args.video_id)
        if not report:
            print(f"[ERROR] Could not retrieve telemetry for video {args.video_id}. Check API key and video ID.")
            return

        print(f"\n[OK] Virality Intelligence Report for: {report.title}")
        print(f"Classification: {report.classification} (Virality Index: {report.virality_index}/100)")
        print(f"Channel: {report.channel_title} ({report.channel_id})")
        print(f"Published: {report.published_at}")
        print(f"Public Views: {report.view_count:,}")
        print(f"Hourly View Velocity: {report.view_velocity_per_hour:,.0f} views/hour")
        print(f"Velocity Multiplier: {report.velocity_multiplier:.2f}x channel baseline")
        print(f"Engagement: LVR (Like Ratio) = {report.like_ratio_pct:.2f}% | CVR (Comment Ratio) = {report.comment_ratio_pct:.3f}%")
        print(f"Auditing Rationale: {report.rationale}")
    else:
        print("Please specify --video-id <ID> or --chart popular")


def cmd_channels(args: argparse.Namespace) -> None:
    registry = ChannelRegistry(args.db)
    if args.channel_cmd == "add":
        registry.add_channel(
            channel_id=args.channel_id,
            name=args.name,
            handle=args.handle,
            channel_url=args.url,
            baseline_views=args.baseline,
        )
        print(f"[OK] Added/Updated monitored channel: {args.name} ({args.channel_id})")
    elif args.channel_cmd == "list":
        channels = registry.list_channels(active_only=not args.all)
        print(f"\n[OK] Monitored Channels ({len(channels)} total):")
        for ch in channels:
            status = "ACTIVE" if ch["active"] else "INACTIVE"
            print(f"  [{status}] {ch['name']} ({ch['channel_id']})")
            print(f"       Handle: {ch['handle'] or 'N/A'} | Baseline: {ch['baseline_views']:,.0f} views")
            print(f"       Last Polled: {ch['last_polled_at'] or 'Never'}")
    elif args.channel_cmd == "remove":
        removed = registry.remove_channel(args.channel_id)
        if removed:
            print(f"[OK] Deactivated channel {args.channel_id} from monitoring.")
        else:
            print(f"[WARN] Channel {args.channel_id} not found.")


def cmd_daemon(args: argparse.Namespace) -> None:
    print(f"[*] Starting continuous Discovery Daemon (interval={args.interval}s, max_iterations={args.max_iterations})...")
    daemon = DiscoveryDaemon(interval_seconds=args.interval)
    telemetry = daemon.run(max_iterations=args.max_iterations)
    print("\n[OK] Daemon stopped. Telemetry summary:")
    print(json.dumps(telemetry, indent=2))
