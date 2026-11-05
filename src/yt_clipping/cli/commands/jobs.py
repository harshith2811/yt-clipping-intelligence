"""
Job management, SQLite state inspection, Queue, and DLQ commands for CLI.
"""

import sys
import argparse

from ...contracts.models import JobStatus
from ...orchestration.state_machine import JobJournal
from ...orchestration.queue import JobQueue
from ...publisher.adapter import DualModeAutopostPublisher
from .pipeline import build_pipeline


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
    import sys
    mcli = sys.modules.get("src.yt_clipping.cli.master_cli") or sys.modules.get("yt_clipping.cli.master_cli")
    bp_factory = getattr(mcli, "build_pipeline", build_pipeline) if mcli else build_pipeline
    pipeline = bp_factory(db_path=args.db)
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
    elif args.queue_cmd == "worker":
        from ...orchestration.pipeline import build_pipeline as build_pipe
        pipeline = build_pipe(
            output_dir=getattr(args, "output_dir", "data/rendered_clips"),
        )
        poll_int = getattr(args, "poll_interval", 5.0)
        max_jobs = getattr(args, "max_jobs", None)
        print(f"[*] Starting 24/7 Job Queue Worker on {args.db} (poll_interval={poll_int}s)...")
        queue.run_worker(
            pipeline_runner=lambda job: pipeline.process_job(job),
            poll_interval=poll_int,
            max_jobs=max_jobs,
        )


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
