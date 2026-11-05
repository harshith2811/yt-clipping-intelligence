"""
Pipeline execution and builder commands for CLI.
"""

import sys
import os
import argparse
from typing import Optional

from ...contracts.models import RenderProfile
from ...config import AppConfig
from ...rights.gate import LocalRightsPolicy
from ...ingestion.asset_provider import LocalAssetProvider, extract_youtube_video_id
from ...transcription.transcriber import LocalTranscriber
from ...detection.segmenter import ContextAwareSegmenter
from ...scoring.scorecard import ExplainableScorecardScorer
from ...scoring.metadata_generator import MetadataGenerator
from ...rendering.renderer import FFmpegRenderer
from ...qa.verifier import MediaQualityVerifier
from ...publisher.adapter import DualModeAutopostPublisher
from ...orchestration.state_machine import JobJournal
from ...orchestration.pipeline import ClippingPipeline


def build_pipeline(
    ledger_path: str = "data/rights_ledger.json",
    assets_dir: str = "data/assets",
    transcripts_dir: str = "data/transcripts",
    output_dir: str = "data/rendered_clips",
    autopost_inbox: str = "data/autopost_inbox",
    db_path: str = "data/jobs.db",
    min_duration: float = 15.0,
    max_duration: float = 60.0,
    autopost_mode: str = "watched_folder",
    webhook_url: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> ClippingPipeline:
    cfg = AppConfig()
    rights_policy = LocalRightsPolicy(ledger_path, db_path=db_path)
    asset_provider = LocalAssetProvider(assets_dir)
    transcriber = LocalTranscriber(transcripts_dir)
    detector = ContextAwareSegmenter(default_min_duration=min_duration, default_max_duration=max_duration)
    scorer = ExplainableScorecardScorer()
    renderer = FFmpegRenderer()
    verifier = MediaQualityVerifier()
    publisher = DualModeAutopostPublisher(
        mode=autopost_mode,
        watched_dir=autopost_inbox,
        webhook_url=webhook_url,
        auth_token=auth_token,
        db_path=db_path,
    )
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


def cmd_run(args: argparse.Namespace) -> None:
    vid_input = getattr(args, "video_id_pos", None) or getattr(args, "video_id", None)
    if not vid_input:
        print("[ERROR] Please provide a video ID or URL.", file=sys.stderr)
        sys.exit(1)
    video_id = extract_youtube_video_id(vid_input)

    min_dur = getattr(args, "min_duration", 15.0)
    max_dur = getattr(args, "max_duration", 60.0)
    autopost_mode = getattr(args, "autopost_mode", "watched_folder")
    omni_url = getattr(args, "omnipost_url", None) or getattr(args, "webhook_url", None)
    omni_key = getattr(args, "omnipost_key", None) or getattr(args, "auth_token", None)

    # Dynamic resolution supports test monkeypatching of master_cli.build_pipeline
    import sys
    mcli = sys.modules.get("src.yt_clipping.cli.master_cli") or sys.modules.get("yt_clipping.cli.master_cli")
    bp_factory = getattr(mcli, "build_pipeline", build_pipeline) if mcli else build_pipeline

    pipeline = bp_factory(
        output_dir=getattr(args, "output_dir", "data/rendered_clips"),
        min_duration=min_dur,
        max_duration=max_dur,
        autopost_mode=autopost_mode,
        webhook_url=omni_url,
        auth_token=omni_key,
    )
    vcodec = "h264_nvenc" if getattr(args, "gpu", False) else getattr(args, "vcodec", "libx264")
    sub_preset = getattr(args, "subtitle_preset", "hormozi")
    enable_cta = getattr(args, "enable_cta", False)
    cta_text = getattr(args, "cta_text", "Subscribe to this channel for more")
    cta_timing = getattr(args, "cta_timing", "end")
    cta_style = getattr(args, "cta_style", "modern_pill")
    cta_margin_bottom = getattr(args, "cta_margin_bottom", 440)
    enable_outro = getattr(args, "enable_outro_card", False)
    outro_dur = getattr(args, "outro_duration", 2.5)
    outro_channel = getattr(args, "outro_channel_name", None)
    enable_polish = getattr(args, "enable_polish", True)

    profile = RenderProfile(
        layout_mode=getattr(args, "layout", "blur_background"),
        vcodec=vcodec,
        subtitle_preset=sub_preset,
        enable_cta=enable_cta,
        cta_text=cta_text,
        cta_timing=cta_timing,
        cta_style=cta_style,
        cta_margin_bottom=cta_margin_bottom,
        enable_outro_card=enable_outro,
        outro_duration=outro_dur,
        outro_channel_name=outro_channel,
        enable_pacing_polish=enable_polish,
    )

    deadair_enabled = getattr(args, "enable_deadair_pruning", False)
    broll_enabled = getattr(args, "enable_broll", False)
    broll_dir = getattr(args, "broll_assets_dir", None)

    print(f"[*] Starting pipeline execution for video: {video_id}")
    print(f"[*] Profile: {profile.name} (layout={profile.layout_mode}, vcodec={profile.vcodec}, subs={profile.subtitle_preset}), dry_run={args.dry_run}, bounds=[{min_dur:.0f}s - {max_dur:.0f}s]")
    if deadair_enabled:
        print("[*] Enhancement: Dead-Air Pruning enabled")
    if broll_enabled:
        print(f"[*] Enhancement: B-Roll Overlay enabled (assets_dir={broll_dir or 'assets/broll'})")
    if enable_cta:
        print(f"[*] Enhancement: Animated CTA Overlay enabled ({cta_style}, timing={cta_timing})")
    if enable_outro:
        print(f"[*] Enhancement: Dedicated Animated Outro Card enabled (channel={outro_channel or 'auto'}, {outro_dur}s with bell chime)")

    try:
        job = pipeline.process_video(
            video_id=video_id,
            profile=profile,
            dry_run=args.dry_run,
            auto_approve_threshold=args.threshold,
            min_duration=min_dur,
            max_duration=max_dur,
            enable_deadair_pruning=deadair_enabled,
            enable_broll=broll_enabled,
            broll_assets_dir=broll_dir,
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
            from ...reporting.html_report import ExecutiveReportGenerator
            report_path = os.path.join(getattr(args, "output_dir", "data/rendered_clips"), f"report_{video_id}.html")
            ExecutiveReportGenerator.generate_html_report(job, output_path=report_path)
            print(f"Executive Report: {report_path}")
        except Exception:
            pass
    except Exception as e:
        print(f"\n[ERROR] Pipeline Failed: {e}", file=sys.stderr)
        sys.exit(1)
