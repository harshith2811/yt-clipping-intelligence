"""
Master CLI for YouTube Clipping Intelligence Platform.
Provides operational commands for rights inspection, discovery ranking,
pipeline execution, candidate review, and autopost handoff auditing.
"""

import argparse
import sys
import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from ..contracts.models import (
    CreatorSource,
    VideoCandidate,
    RightsManifest,
    RightsBasis,
    RightsStatus,
    RenderProfile,
    JobStatus,
)
from ..rights.gate import LocalRightsPolicy
from ..discovery.monitor import ChannelMonitor
from ..discovery.ranker import PublicMetricRanker
from ..discovery.heatmap import HeatmapAnalyzer
from ..discovery.trend_analyzer import TrendAnalyzer
from ..ingestion.asset_provider import LocalAssetProvider
from ..transcription.transcriber import LocalTranscriber
from ..detection.segmenter import ContextAwareSegmenter
from ..scoring.scorecard import ExplainableScorecardScorer
from ..rendering.renderer import FFmpegRenderer
from ..qa.verifier import MediaQualityVerifier
from ..publisher.adapter import DualModeAutopostPublisher
from ..orchestration.state_machine import JobJournal
from ..orchestration.pipeline import ClippingPipeline


def build_pipeline(
    ledger_path: str = "data/rights_ledger.json",
    assets_dir: str = "data/assets",
    transcripts_dir: str = "data/transcripts",
    output_dir: str = "data/rendered_clips",
    autopost_inbox: str = "data/autopost_inbox",
    db_path: str = "data/jobs.db",
) -> ClippingPipeline:
    rights_policy = LocalRightsPolicy(ledger_path)
    asset_provider = LocalAssetProvider(assets_dir)
    transcriber = LocalTranscriber(transcripts_dir)
    detector = ContextAwareSegmenter()
    scorer = ExplainableScorecardScorer()
    renderer = FFmpegRenderer()
    verifier = MediaQualityVerifier()
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=autopost_inbox)
    journal = JobJournal(db_path)

    return ClippingPipeline(
        rights_policy=rights_policy,
        asset_provider=asset_provider,
        transcriber=transcriber,
        detector=detector,
        scorer=scorer,
        renderer=renderer,
        verifier=verifier,
        publisher=publisher,
        journal=journal,
        output_dir=output_dir,
    )


def cmd_rights_register(args: argparse.Namespace) -> None:
    policy = LocalRightsPolicy(args.ledger)
    manifest = RightsManifest(
        rights_id=f"rights-{args.video_id}-{args.basis.lower()}",
        video_id=args.video_id,
        basis=RightsBasis(args.basis),
        status=RightsStatus.VERIFIED,
        owner_name=args.owner,
        license_url=args.license_url or "",
        proof_reference=args.proof or "Direct operator registration via CLI",
        valid_until=args.valid_until,
        verified_at=datetime.now(timezone.utc).isoformat(),
        audit_notes=args.notes or "Operator approved rights manifest.",
    )
    policy.register_rights(manifest)
    print(f"[OK] Registered rights manifest for video '{args.video_id}':")
    print(json.dumps(manifest.to_dict(), indent=2))


def cmd_rights_check(args: argparse.Namespace) -> None:
    policy = LocalRightsPolicy(args.ledger)
    manifest = policy.check_rights(args.video_id)
    is_valid = policy.verify_rights(manifest)
    print(f"Video: {args.video_id}")
    print(f"Status: {manifest.status.value} (Valid for processing: {is_valid})")
    print(f"Basis: {manifest.basis.value}")
    print(f"Owner: {manifest.owner_name}")
    print(f"Notes: {manifest.audit_notes}")


def cmd_run(args: argparse.Namespace) -> None:
    pipeline = build_pipeline(output_dir=args.output_dir)
    vcodec = "h264_nvenc" if getattr(args, "gpu", False) else getattr(args, "vcodec", "libx264")
    profile = RenderProfile(layout_mode=args.layout, vcodec=vcodec)

    print(f"[*] Starting pipeline execution for video: {args.video_id}")
    print(f"[*] Profile: {profile.name} (layout={profile.layout_mode}, vcodec={profile.vcodec}), dry_run={args.dry_run}")

    try:
        job = pipeline.process_video(
            video_id=args.video_id,
            profile=profile,
            dry_run=args.dry_run,
            auto_approve_threshold=args.threshold,
        )
        print("\n[SUCCESS] Pipeline Completed!")
        print(f"Job ID: {job.job_id}")
        print(f"Current Stage: {job.current_stage.value}")
        print(f"Job Status: {job.status.value}")
        if job.candidate:
            print(f"Highlight Candidate: {job.candidate.start_seconds:.1f}s - {job.candidate.end_seconds:.1f}s ({job.candidate.duration_seconds:.1f}s)")
            print(f"Score: {job.candidate.score}/100 | {job.candidate.rationale}")
        if job.rendered_clip:
            print(f"Rendered Clip: {job.rendered_clip.file_path}")
            print(f"Artifact SHA-256: {job.rendered_clip.file_hash}")
        if job.qa_report:
            print(f"QA Status: {job.qa_report.status} (Errors: {len(job.qa_report.errors)}, Warnings: {len(job.qa_report.warnings)})")
        if job.handoff_receipt:
            print(f"Autopost Handoff Status: {job.handoff_receipt.status}")
            print(f"Idempotency Key: {job.handoff_receipt.idempotency_key}")
            print(f"Receipt ID: {job.handoff_receipt.receipt_id}")
    except Exception as e:
        print(f"\n[ERROR] Pipeline Failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_jobs(args: argparse.Namespace) -> None:
    journal = JobJournal(args.db)
    filter_status = JobStatus(args.status) if args.status else None
    jobs = journal.list_jobs(filter_status)
    print(f"Found {len(jobs)} jobs (filter={args.status or 'ALL'}):")
    for j in jobs:
        print(f"- Job: {j.job_id} | Video: {j.video_id} | Stage: {j.current_stage.value} | Status: {j.status.value} | Updated: {j.updated_at}")
        if j.error_message:
            print(f"  Error: {j.error_message}")


def cmd_preview(args: argparse.Namespace) -> None:
    pipeline = build_pipeline()
    print(f"[*] Extracting candidate highlights for video: {args.video_id} (No video render)")
    try:
        candidates = pipeline.get_candidates(args.video_id)
        print(f"\n[OK] Found {len(candidates)} candidate moments (sorted by score):")
        for i, c in enumerate(candidates, 1):
            bd = c.breakdown
            print(f"\n--- Candidate #{i}: {c.candidate_id} ---")
            print(f"Time Range: {c.start_seconds:.1f}s -> {c.end_seconds:.1f}s (Duration: {c.duration_seconds:.1f}s)")
            conf = bd.confidence if bd else 0.8
            print(f"Score: {c.score}/100 (Confidence: {conf:.2f})")
            if bd:
                print(
                    f"Signals: Hook={bd.hook_score:.1f}/10, Moment={bd.moment_score:.1f}/10, "
                    f"Coherence={bd.coherence_score:.1f}/10, Pace={bd.pacing_score:.1f}/10, "
                    f"Energy={bd.audio_energy_score:.1f}/10"
                )
            print(f"Rationale: {c.rationale}")
            print(f"Title: {c.hook_title or 'N/A'}")
    except Exception as e:
        print(f"\n[ERROR] Preview failed: {e}", file=sys.stderr)
        sys.exit(1)


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


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="yt-clip",
        description="YouTube Clipping Intelligence Platform CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Rights command
    p_rights = subparsers.add_parser("rights", help="Inspect and register content rights")
    rights_sub = p_rights.add_subparsers(dest="rights_cmd", required=True)

    p_r_reg = rights_sub.add_parser("register", help="Register verified rights for a video")
    p_r_reg.add_argument("--video-id", required=True, help="YouTube Video ID")
    p_r_reg.add_argument("--basis", required=True, choices=["OWNED", "EXPLICIT_PERMISSION", "CREATIVE_COMMONS", "OPERATOR_ASSET"])
    p_r_reg.add_argument("--owner", required=True, help="Content owner or creator name")
    p_r_reg.add_argument("--license-url", default="", help="License documentation URL")
    p_r_reg.add_argument("--proof", default="", help="Proof reference / agreement ID")
    p_r_reg.add_argument("--valid-until", default=None, help="Expiration date (ISO 8601)")
    p_r_reg.add_argument("--notes", default="", help="Audit rationale")
    p_r_reg.add_argument("--ledger", default="data/rights_ledger.json", help="Path to rights ledger")
    p_r_reg.set_defaults(func=cmd_rights_register)

    p_r_chk = rights_sub.add_parser("check", help="Check rights status for a video")
    p_r_chk.add_argument("--video-id", required=True, help="YouTube Video ID")
    p_r_chk.add_argument("--ledger", default="data/rights_ledger.json", help="Path to rights ledger")
    p_r_chk.set_defaults(func=cmd_rights_check)

    # Run command
    p_run = subparsers.add_parser("run", help="Run end-to-end clipping pipeline on authorized asset")
    p_run.add_argument("--video-id", required=True, help="Video ID to process")
    p_run.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True, help="Simulate autopost handoff (default true)")
    p_run.add_argument("--layout", default="blur_background", choices=["blur_background", "crop_center", "split_screen"], help="Visual layout profile")
    p_run.add_argument("--threshold", type=float, default=65.0, help="Score threshold for auto-approval")
    p_run.add_argument("--gpu", action="store_true", help="Enable NVIDIA NVENC GPU hardware acceleration")
    p_run.add_argument("--vcodec", default="libx264", choices=["libx264", "h264_nvenc", "hevc_nvenc"], help="Video encoder codec")
    p_run.add_argument("--output-dir", default="data/rendered_clips", help="Directory for rendered clips")
    p_run.set_defaults(func=cmd_run)

    # Jobs command
    p_jobs = subparsers.add_parser("jobs", help="List and inspect pipeline jobs")
    p_jobs.add_argument("--status", choices=["PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED", "RETRY_PENDING"], help="Filter by job status")
    p_jobs.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_jobs.set_defaults(func=cmd_jobs)

    # Preview command
    p_prev = subparsers.add_parser("preview", help="Preview highlight candidates and scorecards without rendering")
    p_prev.add_argument("--video-id", required=True, help="Video ID to inspect")
    p_prev.set_defaults(func=cmd_preview)

    # Discovery command
    p_disc = subparsers.add_parser("discovery", help="Simulate or query channel discovery and observed view velocity")
    p_disc.add_argument("--channel-id", default="UC_sample_channel", help="Channel ID")
    p_disc.add_argument("--channel-name", default="Tech Innovators", help="Channel Name")
    p_disc.add_argument("--avg-views", type=float, default=50000.0, help="Channel average views baseline")
    p_disc.add_argument("--sample-video-id", default="vid_sample_01", help="Sample Video ID")
    p_disc.add_argument("--sample-title", default="Deep Learning Systems in 2026", help="Sample Video Title")
    p_disc.add_argument("--views", type=int, default=125000, help="Public view count")
    p_disc.add_argument("--duration", type=float, default=720.0, help="Duration in seconds")
    p_disc.set_defaults(func=cmd_discovery)

    # Heatmap command
    p_hm = subparsers.add_parser("heatmap", help="Analyze YouTube 'Most Replayed' retention curve & peak moments")
    p_hm.add_argument("--video-id", required=True, help="YouTube Video ID")
    p_hm.add_argument("--visual", action="store_true", help="Render ASCII retention waveform in terminal")
    p_hm.add_argument("--cache-dir", default="data/heatmaps", help="Heatmap cache directory")
    p_hm.set_defaults(func=cmd_heatmap)

    # Trends command
    p_tr = subparsers.add_parser("trends", help="Analyze real-time video virality or official YouTube Trending Charts")
    p_tr.add_argument("--video-id", default=None, help="Video ID to evaluate")
    p_tr.add_argument("--chart", choices=["popular"], default=None, help="Fetch official YouTube Trending chart")
    p_tr.add_argument("--region", default="US", help="ISO 3166-1 alpha-2 region code (e.g. US, GB, IN)")
    p_tr.add_argument("--category", default=None, help="YouTube Video Category ID (e.g. 24 for Entertainment, 20 for Gaming)")
    p_tr.add_argument("--limit", type=int, default=10, help="Maximum number of trending videos to display")
    p_tr.set_defaults(func=cmd_trends)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
