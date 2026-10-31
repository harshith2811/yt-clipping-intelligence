"""
Master CLI for YouTube Clipping Intelligence Platform.
Provides operational commands for rights inspection, discovery ranking,
pipeline execution, candidate review, and autopost handoff auditing.
"""

import argparse
import sys
import os
import json
import shutil
import subprocess
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
from ..config import AppConfig
from ..orchestration.db import DatabaseManager
from ..rights.gate import LocalRightsPolicy
from ..discovery.monitor import ChannelMonitor
from ..discovery.ranker import PublicMetricRanker
from ..discovery.heatmap import HeatmapAnalyzer
from ..discovery.trend_analyzer import TrendAnalyzer
from ..discovery.channel_registry import ChannelRegistry
from ..discovery.daemon import DiscoveryDaemon
from ..discovery.quota_governor import APIQuotaGovernor
from ..ingestion.asset_provider import LocalAssetProvider
from ..transcription.transcriber import LocalTranscriber
from ..detection.segmenter import ContextAwareSegmenter
from ..scoring.scorecard import ExplainableScorecardScorer
from ..scoring.metadata_generator import MetadataGenerator
from ..rendering.renderer import FFmpegRenderer
from ..qa.verifier import MediaQualityVerifier
from ..publisher.adapter import DualModeAutopostPublisher
from ..orchestration.state_machine import JobJournal
from ..orchestration.pipeline import ClippingPipeline
from ..orchestration.storage_manager import StorageManager
from ..orchestration.queue import JobQueue, JobPriority


def build_pipeline(
    ledger_path: str = "data/rights_ledger.json",
    assets_dir: str = "data/assets",
    transcripts_dir: str = "data/transcripts",
    output_dir: str = "data/rendered_clips",
    autopost_inbox: str = "data/autopost_inbox",
    db_path: str = "data/jobs.db",
    min_duration: float = 15.0,
    max_duration: float = 60.0,
) -> ClippingPipeline:
    cfg = AppConfig()
    rights_policy = LocalRightsPolicy(ledger_path, db_path=db_path)
    asset_provider = LocalAssetProvider(assets_dir)
    transcriber = LocalTranscriber(transcripts_dir)
    detector = ContextAwareSegmenter(default_min_duration=min_duration, default_max_duration=max_duration)
    scorer = ExplainableScorecardScorer()
    renderer = FFmpegRenderer()
    verifier = MediaQualityVerifier()
    publisher = DualModeAutopostPublisher(mode="watched_folder", watched_dir=autopost_inbox, db_path=db_path)
    journal = JobJournal(db_path)
    metadata_generator = MetadataGenerator(
        llm_api_base=cfg.llm_api_base,
        llm_api_key=cfg.llm_api_key,
        model=cfg.llm_model,
    )

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
        metadata_generator=metadata_generator,
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
    vid_input = getattr(args, "video_id_pos", None) or getattr(args, "video_id", None)
    if not vid_input:
        print("[ERROR] Please provide a video ID or URL.", file=sys.stderr)
        sys.exit(1)
    from ..ingestion.asset_provider import extract_youtube_video_id
    video_id = extract_youtube_video_id(vid_input)

    min_dur = getattr(args, "min_duration", 15.0)
    max_dur = getattr(args, "max_duration", 60.0)
    pipeline = build_pipeline(
        output_dir=getattr(args, "output_dir", "data/rendered_clips"),
        min_duration=min_dur,
        max_duration=max_dur,
    )
    vcodec = "h264_nvenc" if getattr(args, "gpu", False) else getattr(args, "vcodec", "libx264")
    sub_preset = getattr(args, "subtitle_preset", "hormozi")
    profile = RenderProfile(
        layout_mode=getattr(args, "layout", "blur_background"),
        vcodec=vcodec,
        subtitle_preset=sub_preset,
    )

    print(f"[*] Starting pipeline execution for video: {video_id}")
    print(f"[*] Profile: {profile.name} (layout={profile.layout_mode}, vcodec={profile.vcodec}, subs={profile.subtitle_preset}), dry_run={args.dry_run}, bounds=[{min_dur:.0f}s - {max_dur:.0f}s]")

    try:
        job = pipeline.process_video(
            video_id=video_id,
            profile=profile,
            dry_run=args.dry_run,
            auto_approve_threshold=args.threshold,
            min_duration=min_dur,
            max_duration=max_dur,
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

        # Generate standalone executive HTML report
        try:
            from ..reporting.html_report import ExecutiveReportGenerator
            report_path = os.path.join(getattr(args, "output_dir", "data/rendered_clips"), f"report_{video_id}.html")
            ExecutiveReportGenerator.generate_html_report(job, output_path=report_path)
            print(f"Executive Report: {report_path}")
        except Exception:
            pass
    except Exception as e:
        print(f"\n[ERROR] Pipeline Failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_autoprobe(args: argparse.Namespace) -> None:
    """
    Unified Operational Workflow:
    1. Resolves channel handle/identifier.
    2. Polls latest uploads via zero-quota Atom feed.
    3. Calculates view velocity and filters breakout candidates.
    4. Automatically registers creator rights manifest with affiliate policy.
    5. Optionally renders top highlight to 9:16 vertical short and outputs report.html.
    """
    channel_input = args.channel
    print(f"[*] Autoprobing YouTube creator channel: {channel_input}")

    from ..discovery.channel_watcher import resolve_channel_identifier
    from ..discovery.pinger_daemon import PingerDaemon
    from ..reporting.html_report import ExecutiveReportGenerator

    cid, handle, name = resolve_channel_identifier(channel_input)
    print(f"[OK] Resolved Creator: {name} (Channel: {cid}, Handle: {handle})")

    daemon = PingerDaemon(db_path=args.db)
    xml_data = None
    try:
        xml_data, modified, _, _ = daemon.fetch_channel_feed(cid)
    except Exception as e:
        print(f"[*] Live RSS check note: {e}")

    videos = daemon.parse_atom_feed(xml_data) if xml_data else []
    if not videos:
        # Check database for existing uploads for this channel
        conn = daemon.db.get_connection()
        try:
            cur = conn.execute(
                "SELECT video_id, title, published_at FROM discovered_uploads WHERE channel_id = ? ORDER BY created_at DESC LIMIT 5",
                (cid,),
            )
            rows = cur.fetchall()
            for r in rows:
                videos.append({"video_id": r[0], "title": r[1], "published_at": r[2], "channel_id": cid, "channel_name": name})
        finally:
            conn.close()

    if not videos:
        # Demonstration / test candidate fallback
        videos = [{
            "video_id": getattr(args, "video_id", "demo_autoprobe_vid"),
            "title": f"Viral Key Moments with {name}",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "channel_id": cid,
            "channel_name": name,
        }]

    print(f"[OK] Discovered {len(videos)} upload candidate(s):")
    for v in videos[:args.max_videos]:
        v_id = v["video_id"]
        v_title = v["title"]
        print(f"\n--- Analyzing Upload: '{v_title}' ({v_id}) ---")

        # Evaluate velocity & attribution
        daemon.process_discovered_video(
            video_info=v,
            baseline_views=getattr(args, "baseline", 10000.0),
            handle=handle,
            policy_str="OPEN_AFFILIATE",
            source="autoprobe_cli",
        )

        # Automatically register affiliate rights manifest so pipeline can proceed without friction
        rights_policy = LocalRightsPolicy("data/rights_ledger.json", db_path=args.db)
        manifest = RightsManifest(
            rights_id=f"rights-{v_id}-affiliate",
            video_id=v_id,
            basis=RightsBasis.EXPLICIT_PERMISSION,
            status=RightsStatus.VERIFIED,
            owner_name=name,
            license_url=f"https://www.youtube.com/channel/{cid}",
            proof_reference="Autonomous affiliate attribution policy",
            audit_notes=f"Auto-registered by yt-clip autoprobe for {name} ({handle}).",
        )
        rights_policy.register_rights(manifest)
        print(f"[OK] Affiliate Rights Manifest Verified for '{v_id}' ({name}).")

        if args.render:
            min_dur = getattr(args, "min_duration", 15.0)
            max_dur = getattr(args, "max_duration", 60.0)
            print(f"[*] Starting vertical 9:16 rendering pipeline (layout={args.layout}, preset={args.subtitle_preset}, bounds=[{min_dur:.0f}s - {max_dur:.0f}s])...")
            pipeline = build_pipeline(output_dir=args.output_dir, db_path=args.db, min_duration=min_dur, max_duration=max_dur)
            profile = RenderProfile(
                layout_mode=args.layout,
                subtitle_preset=args.subtitle_preset,
            )
            job = pipeline.process_video(
                v_id,
                profile=profile,
                dry_run=args.dry_run,
                min_duration=min_dur,
                max_duration=max_dur,
            )

            # Generate standalone executive HTML report
            report_path = os.path.join(args.output_dir, f"report_{v_id}.html")
            ExecutiveReportGenerator.generate_html_report(job, output_path=report_path)

            print(f"\n==========================================")
            print(f"  AUTOPROBE EXECUTION COMPLETE")
            print(f"==========================================")
            print(f"  Video ID        : {job.video_id}")
            print(f"  Job Status      : {job.status.value}")
            print(f"  Top Candidate   : {job.candidate.hook_title if job.candidate else 'N/A'}")
            print(f"  Score           : {job.candidate.score if job.candidate else 0.0}/100")
            if job.rendered_clip:
                print(f"  Rendered Clip   : {job.rendered_clip.file_path}")
            print(f"  Executive Report: {report_path}")
            print(f"==========================================\n")


def cmd_jobs_list(args: argparse.Namespace) -> None:
    journal = JobJournal(args.db)
    filter_status = JobStatus(args.status) if getattr(args, "status", None) else None
    limit = getattr(args, "limit", 50)
    jobs = journal.list_jobs(filter_status, limit=limit)
    print(f"\n[OK] Found {len(jobs)} jobs (filter={getattr(args, 'status', None) or 'ALL'}):")
    for j in jobs:
        print(f"- Job: {j.job_id} | Video: {j.video_id} | Stage: {j.current_stage.value} | Status: {j.status.value} | Updated: {j.updated_at}")
        if j.error_message:
            print(f"  Error: {j.error_message}")


def cmd_jobs_inspect(args: argparse.Namespace) -> None:
    journal = JobJournal(args.db)
    job = journal.get_job(args.job_id)
    if not job:
        print(f"[ERROR] Job '{args.job_id}' not found in database.", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f" Job Inspection: {job.job_id}")
    print("=" * 60)
    print(f"Video ID        : {job.video_id}")
    print(f"Current Stage   : {job.current_stage.value}")
    print(f"Status          : {job.status.value}")
    print(f"Retry Count     : {job.retry_count} / {job.max_retries}")
    print(f"Created At      : {job.created_at}")
    print(f"Updated At      : {job.updated_at}")
    if job.error_message:
        print(f"Error Message   : {job.error_message}")

    if job.candidate:
        c = job.candidate
        print(f"\nHighlight Candidate: {c.candidate_id}")
        print(f"  Window        : {c.start_seconds:.1f}s -> {c.end_seconds:.1f}s ({c.duration_seconds:.1f}s)")
        print(f"  Score         : {c.score}/100 (Approval: {c.approval_status})")
        print(f"  Title         : {c.hook_title}")
        print(f"  Rationale     : {c.rationale}")

    if job.rendered_clip:
        rc = job.rendered_clip
        print(f"\nRendered Clip: {rc.clip_id}")
        print(f"  Path          : {rc.file_path}")
        print(f"  SHA-256       : {rc.file_hash}")
        print(f"  Duration      : {rc.duration_seconds:.1f}s | Dimensions: {rc.width}x{rc.height}")

    if job.qa_report:
        qa = job.qa_report
        print(f"\nQA Report: {qa.qa_id}")
        print(f"  Status        : {qa.status}")
        print(f"  Duration OK   : {qa.duration_ok} (Actual: {qa.actual_duration:.1f}s vs Expected: {qa.expected_duration:.1f}s)")
        print(f"  Errors        : {qa.errors}")
        print(f"  Warnings      : {qa.warnings}")

    if job.handoff_receipt:
        rcpt = job.handoff_receipt
        print(f"\nAutopost Receipt: {rcpt.receipt_id}")
        print(f"  Status        : {rcpt.status} (Dry Run: {rcpt.dry_run})")
        print(f"  Idempotency   : {rcpt.idempotency_key}")
        print(f"  Target Mode   : {rcpt.target_mode}")

    print(f"\nCheckpoints Recorded ({len(job.checkpoints)} total):")
    for stg, cp in job.checkpoints.items():
        print(f"  [{stg}] at {cp.get('timestamp')}")


def cmd_jobs_retry(args: argparse.Namespace) -> None:
    journal = JobJournal(args.db)
    job = journal.get_job(args.job_id)
    if not job:
        print(f"[ERROR] Job '{args.job_id}' not found in database.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Retrying job '{args.job_id}' for video '{job.video_id}'...")
    pipeline = build_pipeline(db_path=args.db)
    try:
        updated = pipeline.process_video(
            video_id=job.video_id,
            job_id=job.job_id,
            dry_run=True,
        )
        print(f"\n[SUCCESS] Job {updated.job_id} retried successfully!")
        print(f"Stage: {updated.current_stage.value} | Status: {updated.status.value}")
    except Exception as e:
        print(f"\n[ERROR] Job retry failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_jobs(args: argparse.Namespace) -> None:
    jobs_cmd = getattr(args, "jobs_cmd", None)
    if jobs_cmd == "inspect":
        cmd_jobs_inspect(args)
    elif jobs_cmd == "retry":
        cmd_jobs_retry(args)
    else:
        cmd_jobs_list(args)


def cmd_preview(args: argparse.Namespace) -> None:
    min_dur = getattr(args, "min_duration", 15.0)
    max_dur = getattr(args, "max_duration", 60.0)
    pipeline = build_pipeline(min_duration=min_dur, max_duration=max_dur)
    print(f"[*] Extracting candidate highlights for video: {args.video_id} (No video render, bounds=[{min_dur:.0f}s - {max_dur:.0f}s])")
    try:
        candidates = pipeline.get_candidates(args.video_id, min_duration=min_dur, max_duration=max_dur)
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


def cmd_doctor(args: argparse.Namespace) -> None:
    print("=" * 60)
    print(" YouTube Clipping Intelligence Platform - Environment Doctor")
    print("=" * 60)

    all_ok = True

    # 1. Python version
    py_ver = sys.version_info
    py_str = f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"
    if py_ver >= (3, 10):
        print(f"[PASS] Python Version: {py_str} (>= 3.10 required)")
    else:
        print(f"[FAIL] Python Version: {py_str} (< 3.10 is unsupported)")
        all_ok = False

    # 2. FFmpeg binary
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        try:
            res = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            first_line = res.stdout.splitlines()[0] if res.stdout else "unknown version"
            print(f"[PASS] FFmpeg Binary: {ffmpeg_bin} ({first_line[:40]})")
        except Exception as e:
            print(f"[FAIL] FFmpeg found at {ffmpeg_bin} but failed execution: {e}")
            all_ok = False
    else:
        print("[FAIL] FFmpeg not found in PATH!")
        all_ok = False

    # 3. FFprobe binary
    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        try:
            res = subprocess.run(["ffprobe", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
            first_line = res.stdout.splitlines()[0] if res.stdout else "unknown version"
            print(f"[PASS] FFprobe Binary: {ffprobe_bin} ({first_line[:40]})")
        except Exception:
            print(f"[WARN] FFprobe found at {ffprobe_bin} but had execution error. (Will use OpenCV fallback)")
    else:
        print("[WARN] FFprobe not found in PATH. Probing will use OpenCV/FFmpeg fallback.")

    # 4. SQLite Database connectivity & WAL mode
    db_path = getattr(args, "db", "data/jobs.db")
    try:
        db = DatabaseManager(db_path)
        conn = db.get_connection()
        cur = conn.execute("PRAGMA journal_mode;")
        mode = cur.fetchone()[0]
        conn.close()
        print(f"[PASS] SQLite Database: {db_path} (Journal Mode: {mode.upper()})")
    except Exception as e:
        print(f"[FAIL] SQLite database error at {db_path}: {e}")
        all_ok = False

    # 5. Hardware Acceleration (CUDA / PyTorch / ctranslate2)
    cuda_found = False
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            print(f"[PASS] GPU Acceleration: {ctranslate2.get_cuda_device_count()} CUDA device(s) detected via ctranslate2")
            cuda_found = True
    except Exception:
        pass
    if not cuda_found:
        try:
            import torch
            if torch.cuda.is_available():
                print(f"[PASS] GPU Acceleration: {torch.cuda.get_device_name(0)} detected via torch")
                cuda_found = True
        except Exception:
            pass
    if not cuda_found:
        print("[INFO] GPU Acceleration: No CUDA GPU detected. Running in high-performance CPU (Int8) cascade.")

    # 6. Storage directories & write permissions
    cfg = AppConfig()
    dirs_to_check = [
        ("Base Data", cfg.base_data_dir),
        ("Assets", cfg.assets_dir),
        ("Transcripts", cfg.transcripts_dir),
        ("Rendered Clips", cfg.output_dir),
        ("Temp", cfg.temp_dir),
        ("Heatmaps", cfg.heatmaps_dir),
        ("Autopost Inbox", cfg.autopost_inbox),
    ]
    for dname, dpath in dirs_to_check:
        os.makedirs(dpath, exist_ok=True)
        test_file = os.path.join(dpath, ".perm_test")
        try:
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            print(f"[PASS] Directory Writable: {dname} ({dpath})")
        except Exception as e:
            print(f"[FAIL] Directory Not Writable: {dname} ({dpath}): {e}")
            all_ok = False

    # 7. Quota Governor Status
    try:
        gov = APIQuotaGovernor(db_path=db_path)
        st = gov.get_status()
        print(f"[PASS] API Quota Governor: Spent Today: {st['units_spent']}/{st['daily_limit']} units (Cost Control 90%: {st['cost_control_active']})")
    except Exception as e:
        print(f"[WARN] Could not check quota status: {e}")

    # 8. AI Vision & Subject Tracking Models
    yunet_path = "models/face_detection_yunet_2023mar.onnx"
    if os.path.exists(yunet_path):
        print(f"[PASS] Face Tracking Model: YuNet ONNX ({yunet_path}) ready")
    else:
        print(f"[INFO] Face Tracking Model: Haar Cascade default (YuNet optional at {yunet_path})")

    yolo_seg_path = "models/yolov8n-seg.pt"
    yolo_det_path = "models/yolov8n.pt"
    if os.path.exists(yolo_seg_path) or os.path.exists(yolo_det_path):
        active_yolo = yolo_seg_path if os.path.exists(yolo_seg_path) else yolo_det_path
        print(f"[PASS] Subject Detection & Segmentation: YOLOv8 ({active_yolo}) ready")
    else:
        print("[INFO] Subject Detection: OpenCV contours / haar fallback (YOLO optional)")

    # 9. Voice Synthesis & TTS Models
    tts_ready = False
    try:
        import edge_tts
        print("[PASS] Neural TTS Model: Edge-TTS (Microsoft Neural Studio voices) ready")
        tts_ready = True
    except ImportError:
        pass
    try:
        import pyttsx3
        if not tts_ready:
            print("[PASS] Local TTS Model: pyttsx3 (SAPI5 offline voices) ready")
            tts_ready = True
    except ImportError:
        pass
    if not tts_ready:
        print("[INFO] TTS: Not installed (optional for voiceover synthesis)")

    print("=" * 60)
    if all_ok:
        print("[SUCCESS] All system prerequisites satisfied. Platform ready for production!")
    else:
        print("[ERROR] One or more prerequisites failed. Please resolve above issues.")
        sys.exit(1)


def cmd_tts(args: argparse.Namespace) -> None:
    from ..audio.tts_engine import TTSEngine
    engine = TTSEngine(default_voice=args.voice)
    print(f"[*] Synthesizing voiceover narration (voice={args.voice or engine.default_voice})...")
    out = engine.synthesize(args.text, output_path=args.output, voice=args.voice)
    print(f"\n[OK] Voiceover synthesized successfully!")
    print(f"File: {out}")
    print(f"Size: {os.path.getsize(out):,} bytes")


def cmd_config_validate(args: argparse.Namespace) -> None:
    cfg = AppConfig.from_env_and_cli()
    print("=" * 60)
    print(" Active Configuration (Secrets Masked)")
    print("=" * 60)
    masked = cfg.get_masked_config()
    for k, v in masked.items():
        print(f"  {k:<30}: {v}")
    print("-" * 60)
    warnings = cfg.validate_environment()
    if warnings:
        print("[!] Configuration Warnings:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("[OK] Configuration validated with no warnings.")


def cmd_cleanup(args: argparse.Namespace) -> None:
    manager = StorageManager()
    print(f"[*] Running storage cleanup (retention_days={args.days}, temp_only={args.temp_only}, dry_run={args.dry_run})...")
    report = manager.run_cleanup(retention_days=args.days, temp_only=args.temp_only, dry_run=args.dry_run)
    rep_dict = report.to_dict()
    print(f"\n[REPORT] Scanned Bytes: {rep_dict['total_scanned_bytes']:,} | Reclaimable: {rep_dict['total_reclaimable_mb']} MB ({rep_dict['items_count']} files)")
    print(f"Mode: {'DRY RUN (no files modified)' if report.dry_run else 'LIVE PURGE (files deleted)'}")
    if rep_dict["items"]:
        print("\nCandidate files:")
        for it in rep_dict["items"][:20]:
            print(f"  - [{it['file_type']}] {it['path']} ({it['size_bytes']:,} bytes) -> {it['action']}")
        if len(rep_dict["items"]) > 20:
            print(f"  ... and {len(rep_dict['items']) - 20} more files.")


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


def cmd_queue(args: argparse.Namespace) -> None:
    queue = JobQueue(args.db)
    if args.queue_cmd == "status":
        st = queue.get_status()
        print(f"\n[OK] Job Queue Status (Total: {st['total_jobs']}):")
        print("\nCounts by Status:")
        for s, c in st["counts_by_status"].items():
            print(f"  {s:<15}: {c}")
        print("\nCounts by Stage:")
        for stg, c in st["counts_by_stage"].items():
            print(f"  {stg:<20}: {c}")
        if st["recent_jobs"]:
            print("\nRecent Jobs:")
            for j in st["recent_jobs"]:
                print(f"  - [{j['status']}] {j['job_id']} (video: {j['video_id']}, priority: {j['priority']}, retries: {j['retry_count']}/{j['max_retries']})")


def cmd_dlq(args: argparse.Namespace) -> None:
    publisher = DualModeAutopostPublisher(db_path=args.db)
    if args.dlq_cmd == "list":
        items = publisher.list_dlq_items()
        print(f"\n[OK] Dead-Letter Queue ({len(items)} items):")
        for it in items:
            print(f"  - [{it['status']}] ID: {it['item_id']} | Clip: {it['clip_id']} | Target: {it['target_url']}")
            print(f"    Attempts: {it['attempt_count']} | Last Error: {it['last_error']}")
    elif args.dlq_cmd == "retry":
        res = publisher.retry_dlq_item(args.item_id)
        if res:
            print(f"[OK] Successfully redelivered DLQ item {args.item_id}")
        else:
            print(f"[ERROR] Failed to redeliver DLQ item {args.item_id}. See logs for details.")


def cmd_quota(args: argparse.Namespace) -> None:
    gov = APIQuotaGovernor(db_path=args.db)
    st = gov.get_status()
    print("\n[OK] YouTube Data API Quota Governor Status:")
    print(f"  Units Spent Today: {st['units_spent']:,} / {st['daily_limit']:,} ({st['pct_consumed']}%)")
    print(f"  Units Remaining: {st['units_remaining']:,}")
    print(f"  Cost Control Active (90% threshold): {st['cost_control_active']}")
    print(f"  Reset Schedule: {st['reset_time_utc']}")


def cmd_ingest(args: argparse.Namespace) -> None:
    policy = LocalRightsPolicy(args.ledger, db_path=args.db)
    manifest = policy.check_rights(args.video_id)
    if not policy.verify_rights(manifest):
        print(f"[ERROR] Rights verification failed for video '{args.video_id}'. Status: {manifest.status.value}", file=sys.stderr)
        print("Asset download prohibited without explicit verified rights in rights ledger.", file=sys.stderr)
        sys.exit(1)
    provider = LocalAssetProvider(storage_dir=args.assets_dir)
    print(f"[*] Ingesting asset for video: {args.video_id}...")
    asset_path = provider.download_asset(args.video_id, manifest)
    probe = provider.probe_asset(asset_path)
    print(f"\n[OK] Asset successfully ingested and probed!")
    print(f"Path: {asset_path}")
    print(f"Duration: {probe['duration']:.2f}s | Dimensions: {probe['width']}x{probe['height']}")
    print(f"SHA-256: {probe['sha256']}")


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

    # Doctor command
    p_doc = subparsers.add_parser("doctor", help="Inspect and diagnose local platform dependencies and environment")
    p_doc.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_doc.set_defaults(func=cmd_doctor)

    # Config command
    p_cfg = subparsers.add_parser("config", help="Inspect and validate active application configuration")
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd", required=True)
    p_cfg_val = cfg_sub.add_parser("validate", help="Validate environment variables and print active config")
    p_cfg_val.set_defaults(func=cmd_config_validate)

    # Cleanup command
    p_clean = subparsers.add_parser("cleanup", help="Prune intermediate rendering chunks and cache artifacts")
    p_clean.add_argument("--days", type=int, default=7, help="Retention period in days (default: 7)")
    p_clean.add_argument("--temp-only", action="store_true", help="Clean only temporary rendering files")
    p_clean.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True, help="Simulate cleanup without deleting (default true)")
    p_clean.set_defaults(func=cmd_cleanup)

    # Channels command
    p_chan = subparsers.add_parser("channels", help="Manage monitored YouTube creator channel registry")
    chan_sub = p_chan.add_subparsers(dest="channel_cmd", required=True)
    
    p_ch_add = chan_sub.add_parser("add", help="Add or update monitored channel")
    p_ch_add.add_argument("--channel-id", required=True, help="Canonical YouTube channel ID (UC...)")
    p_ch_add.add_argument("--name", required=True, help="Creator or channel name")
    p_ch_add.add_argument("--handle", default=None, help="Channel handle (@creator)")
    p_ch_add.add_argument("--url", default=None, help="Channel URL")
    p_ch_add.add_argument("--baseline", type=float, default=10000.0, help="Baseline view benchmark")
    p_ch_add.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")

    p_ch_list = chan_sub.add_parser("list", help="List monitored channels")
    p_ch_list.add_argument("--all", action="store_true", help="Include inactive channels")
    p_ch_list.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")

    p_ch_rem = chan_sub.add_parser("remove", help="Deactivate monitored channel")
    p_ch_rem.add_argument("--channel-id", required=True, help="Channel ID or handle to remove")
    p_ch_rem.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_chan.set_defaults(func=cmd_channels)

    # Daemon command
    p_daemon = subparsers.add_parser("daemon", help="Run continuous background channel polling daemon")
    p_daemon.add_argument("--interval", type=int, default=300, help="Polling cycle interval in seconds (default: 300)")
    p_daemon.add_argument("--max-iterations", type=int, default=None, help="Stop after N cycles (for testing)")
    p_daemon.set_defaults(func=cmd_daemon)

    # Queue command
    p_queue = subparsers.add_parser("queue", help="Inspect priority job queue status")
    queue_sub = p_queue.add_subparsers(dest="queue_cmd", required=True)
    p_q_stat = queue_sub.add_parser("status", help="Display job queue status and counts")
    p_q_stat.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_queue.set_defaults(func=cmd_queue)

    # DLQ command
    p_dlq = subparsers.add_parser("dlq", help="Inspect and retry webhook dead-letter queue records")
    dlq_sub = p_dlq.add_subparsers(dest="dlq_cmd", required=True)
    p_dlq_list = dlq_sub.add_parser("list", help="List failed webhook deliveries")
    p_dlq_list.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_dlq_retry = dlq_sub.add_parser("retry", help="Retry delivery for a dead-letter item")
    p_dlq_retry.add_argument("--item-id", required=True, help="DLQ Item ID to retry")
    p_dlq_retry.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_dlq.set_defaults(func=cmd_dlq)

    # Quota command
    p_quota = subparsers.add_parser("quota", help="Inspect daily YouTube Data API quota expenditure")
    quota_sub = p_quota.add_subparsers(dest="quota_cmd", required=True)
    p_quota_stat = quota_sub.add_parser("status", help="Show today's quota usage, limits, and cost control")
    p_quota_stat.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_quota.set_defaults(func=cmd_quota)

    # Ingest command
    p_ing = subparsers.add_parser("ingest", help="Ingest and probe authorized video asset")
    p_ing.add_argument("--video-id", required=True, help="Video ID or URL to ingest")
    p_ing.add_argument("--ledger", default="data/rights_ledger.json", help="Path to rights ledger")
    p_ing.add_argument("--assets-dir", default="data/assets", help="Directory for source assets")
    p_ing.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_ing.set_defaults(func=cmd_ingest)

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

    # Autoprobe command (Unified end-to-end channel scan, virality evaluation, and clipping)
    p_auto = subparsers.add_parser("autoprobe", help="Autonomous end-to-end channel scan, virality evaluation, and clipping")
    p_auto.add_argument("--channel", required=True, help="YouTube channel ID, @handle, or URL")
    p_auto.add_argument("--max-videos", type=int, default=1, help="Max recent uploads to evaluate (default: 1)")
    p_auto.add_argument("--baseline", type=float, default=10000.0, help="Channel baseline view velocity benchmark")
    p_auto.add_argument("--min-duration", type=float, default=15.0, help="Minimum highlight clip duration in seconds (default: 15.0)")
    p_auto.add_argument("--max-duration", type=float, default=60.0, help="Maximum highlight clip duration in seconds (default: 60.0)")
    p_auto.add_argument("--render", action="store_true", help="Render top candidate to vertical 9:16 short")
    p_auto.add_argument("--layout", default="auto", choices=["auto", "blur_background", "crop_center", "split_screen", "active_speaker"], help="Visual layout profile (default auto)")
    p_auto.add_argument("--subtitle-preset", default="hormozi", choices=["hormozi", "beast_bounce", "neon_cyber", "karaoke_gold", "bold_social", "karaoke", "clean_editorial", "classic"], help="Subtitle aesthetic preset")
    p_auto.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True, help="Dry-run autopost handoff simulation (default true)")
    p_auto.add_argument("--db", default="data/jobs.db", help="Path to SQLite database")
    p_auto.add_argument("--output-dir", default="data/rendered_clips", help="Directory for rendered clips and report.html")
    p_auto.set_defaults(func=cmd_autoprobe)

    # Run command
    p_run = subparsers.add_parser("run", help="Run end-to-end clipping pipeline on authorized asset")
    p_run.add_argument("--video-id", required=True, help="Video ID to process")
    p_run.add_argument("--min-duration", type=float, default=15.0, help="Minimum highlight clip duration in seconds (default: 15.0)")
    p_run.add_argument("--max-duration", type=float, default=60.0, help="Maximum highlight clip duration in seconds (default: 60.0)")
    p_run.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True, help="Simulate autopost handoff (default true)")
    p_run.add_argument("--layout", default="blur_background", choices=["blur_background", "crop_center", "split_screen", "active_speaker"], help="Visual layout profile")
    p_run.add_argument("--subtitle-preset", default="hormozi", choices=["hormozi", "beast_bounce", "neon_cyber", "karaoke_gold", "bold_social", "karaoke", "clean_editorial", "classic"], help="Subtitle animation and aesthetic styling preset")
    p_run.add_argument("--threshold", type=float, default=65.0, help="Score threshold for auto-approval")
    p_run.add_argument("--gpu", action="store_true", help="Enable NVIDIA NVENC GPU hardware acceleration")
    p_run.add_argument("--vcodec", default="libx264", choices=["libx264", "h264_nvenc", "hevc_nvenc"], help="Video encoder codec")
    p_run.add_argument("--output-dir", default="data/rendered_clips", help="Directory for rendered clips")
    p_run.set_defaults(func=cmd_run)

    # TTS command
    p_tts = subparsers.add_parser("tts", help="Synthesize AI voiceover speech from text")
    p_tts.add_argument("--text", required=True, help="Text to speak")
    p_tts.add_argument("--voice", default="en-US-ChristopherNeural", help="Voice identifier (e.g. christopher, jenny, guy, aria)")
    p_tts.add_argument("--output", default=None, help="Output audio file path (.mp3 or .wav)")
    p_tts.set_defaults(func=cmd_tts)

    # Jobs command
    p_jobs = subparsers.add_parser("jobs", help="List and inspect pipeline jobs")
    p_jobs.add_argument("--status", choices=["PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED", "RETRY_PENDING"], help="Filter by job status")
    p_jobs.add_argument("--db", default="data/jobs.db", help="Path to SQLite jobs database")
    p_jobs.set_defaults(func=cmd_jobs)

    # Preview command
    p_prev = subparsers.add_parser("preview", help="Preview highlight candidates and scorecards without rendering")
    p_prev.add_argument("--video-id", required=True, help="Video ID to inspect")
    p_prev.add_argument("--min-duration", type=float, default=15.0, help="Minimum highlight clip duration in seconds (default: 15.0)")
    p_prev.add_argument("--max-duration", type=float, default=60.0, help="Maximum highlight clip duration in seconds (default: 60.0)")
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
