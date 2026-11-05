"""
Asset ingestion, rights management, quota inspection, TTS synthesis, preview, and storage cleanup commands for CLI.
"""

import sys
import os
import json
import argparse
from datetime import datetime, timezone

from ...contracts.models import RightsManifest, RightsBasis, RightsStatus
from ...rights.gate import LocalRightsPolicy
from ...ingestion.asset_provider import LocalAssetProvider
from ...discovery.quota_governor import APIQuotaGovernor
from ...orchestration.storage_manager import StorageManager
from .pipeline import build_pipeline


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


def cmd_quota(args: argparse.Namespace) -> None:
    gov = APIQuotaGovernor(db_path=args.db)
    st = gov.get_status()
    print("\n[OK] YouTube Data API Quota Governor Status:")
    print(f"  Units Spent Today: {st['units_spent']:,} / {st['daily_limit']:,} ({st['pct_consumed']}%)")
    print(f"  Units Remaining: {st['units_remaining']:,}")
    print(f"  Cost Control Active (90% threshold): {st['cost_control_active']}")
    print(f"  Reset Schedule: {st['reset_time_utc']}")


def cmd_tts(args: argparse.Namespace) -> None:
    from ...audio.tts_engine import TTSEngine
    engine = TTSEngine(default_voice=args.voice)
    print(f"[*] Synthesizing voiceover narration (voice={args.voice or engine.default_voice})...")
    out = engine.synthesize(args.text, output_path=args.output, voice=args.voice)
    print(f"\n[OK] Voiceover synthesized successfully!")
    print(f"File: {out}")
    print(f"Size: {os.path.getsize(out):,} bytes")


def cmd_preview(args: argparse.Namespace) -> None:
    min_dur = getattr(args, "min_duration", 15.0)
    max_dur = getattr(args, "max_duration", 60.0)
    import sys
    mcli = sys.modules.get("src.yt_clipping.cli.master_cli") or sys.modules.get("yt_clipping.cli.master_cli")
    bp_factory = getattr(mcli, "build_pipeline", build_pipeline) if mcli else build_pipeline
    pipeline = bp_factory(min_duration=min_dur, max_duration=max_dur)
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
