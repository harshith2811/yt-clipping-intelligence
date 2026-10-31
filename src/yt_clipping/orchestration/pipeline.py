"""
End-to-End Orchestrated Clipping Pipeline.
Wires together Discovery, RightsGate, Ingestion, Transcription,
Candidate Detection, Highlight Scoring, FFmpeg Rendering, QA Verification,
and Autopost Handoff with checkpoint recovery.
"""

from typing import Optional, List, Dict, Any
import uuid
import os
from datetime import datetime, timezone

from ..contracts.models import (
    ClipJob,
    JobStage,
    JobStatus,
    RenderProfile,
    HighlightCandidate,
)
from ..contracts.interfaces import (
    RightsPolicy,
    AssetProvider,
    Transcriber,
    HighlightDetector,
    HighlightScorer,
    Renderer,
    QualityVerifier,
    HandoffPublisher,
    RightsPolicyViolationError,
)
from ..orchestration.state_machine import JobJournal
from ..discovery.heatmap import HeatmapAnalyzer
from ..detection.segmenter import suppress_overlapping_candidates
from ..scoring.metadata_generator import MetadataGenerator


class ClippingPipeline:
    """
    Coordinates the full clipping intelligence lifecycle.
    Guarantees that a rights failure stops the pipeline before rendering,
    and a QA failure blocks autopost handoff.
    """

    def __init__(
        self,
        rights_policy: RightsPolicy,
        asset_provider: AssetProvider,
        transcriber: Transcriber,
        detector: HighlightDetector,
        scorer: HighlightScorer,
        renderer: Renderer,
        verifier: QualityVerifier,
        publisher: HandoffPublisher,
        journal: Optional[JobJournal] = None,
        heatmap_analyzer: Optional[HeatmapAnalyzer] = None,
        metadata_generator: Optional[MetadataGenerator] = None,
        output_dir: str = "data/rendered_clips",
    ):
        self.rights_policy = rights_policy
        self.asset_provider = asset_provider
        self.transcriber = transcriber
        self.detector = detector
        self.scorer = scorer
        self.renderer = renderer
        self.verifier = verifier
        self.publisher = publisher
        self.journal = journal or JobJournal()
        self.heatmap_analyzer = heatmap_analyzer or HeatmapAnalyzer()
        self.metadata_generator = metadata_generator or MetadataGenerator()
        self.output_dir = output_dir

    def reconcile_job_checkpoints(self, job: ClipJob) -> None:
        """
        BUG-27 fix: Validates on-disk artifacts for each recorded stage in sequential order.
        If any stage's artifact is missing, corrupted, or altered, invalidates that stage
        and all subsequent checkpoints so stale results are never erroneously reused.
        """
        stages_order = [
            JobStage.RIGHTS_CHECKED,
            JobStage.ASSET_INGESTED,
            JobStage.TRANSCRIBED,
            JobStage.SEGMENTED,
            JobStage.SCORED,
            JobStage.REVIEWED,
            JobStage.RENDERED,
            JobStage.QA_VERIFIED,
            JobStage.HANDED_OFF,
        ]

        def invalidate_from(stage_idx: int) -> None:
            for s in stages_order[stage_idx:]:
                if s.value in job.checkpoints:
                    del job.checkpoints[s.value]
            if stage_idx <= stages_order.index(JobStage.SCORED):
                job.candidate = None
            if stage_idx <= stages_order.index(JobStage.RENDERED):
                job.rendered_clip = None
            if stage_idx <= stages_order.index(JobStage.QA_VERIFIED):
                job.qa_report = None
            if stage_idx <= stages_order.index(JobStage.HANDED_OFF):
                job.handoff_receipt = None

        # 1. Rights checked
        if JobStage.RIGHTS_CHECKED.value in job.checkpoints:
            if not job.rights_manifest and self.rights_policy:
                try:
                    job.rights_manifest = self.rights_policy.check_rights(job.video_id)
                except Exception:
                    pass
            if not job.rights_manifest or (self.rights_policy and not self.rights_policy.verify_rights(job.rights_manifest)):
                invalidate_from(0)
                return

        # 2. Asset Ingested
        if JobStage.ASSET_INGESTED.value in job.checkpoints:
            cp_data = job.checkpoints[JobStage.ASSET_INGESTED.value].get("data", {})
            p = cp_data.get("asset_path")
            if not p or not os.path.exists(p) or os.path.getsize(p) == 0:
                invalidate_from(1)
                return

        # 3. Transcribed
        if JobStage.TRANSCRIBED.value in job.checkpoints:
            cached_t = self.transcriber.load_from_cache(job.video_id)
            if not cached_t or (not cached_t.segments and cached_t.duration_seconds <= 0):
                invalidate_from(2)
                return

        # 4 & 5. Scored
        if JobStage.SCORED.value in job.checkpoints:
            if not job.candidate:
                invalidate_from(3)
                return

        # 7. Rendered
        if JobStage.RENDERED.value in job.checkpoints:
            if not job.rendered_clip or not job.rendered_clip.file_path:
                invalidate_from(6)
                return
            clip_path = job.rendered_clip.file_path
            if not os.path.exists(clip_path) or os.path.getsize(clip_path) < 100:
                invalidate_from(6)
                return

        # 8. QA Verified
        if JobStage.QA_VERIFIED.value in job.checkpoints:
            if not job.qa_report or job.qa_report.status == "FAILED":
                invalidate_from(7)
                return

    def process_video(
        self,
        video_id: str,
        profile: Optional[RenderProfile] = None,
        dry_run: bool = True,
        auto_approve_threshold: float = 65.0,
        job_id: Optional[str] = None,
    ) -> ClipJob:
        """
        Executes the full pipeline for a video ID.
        Resumes from existing checkpoint if available.
        """
        render_profile = profile or RenderProfile()
        actual_job_id = job_id or f"job-{video_id}-{uuid.uuid4().hex[:8]}"

        # Check existing job for resumption (BUG-27 fix)
        job = self.journal.get_job(actual_job_id)
        if not job:
            job = ClipJob(
                job_id=actual_job_id,
                video_id=video_id,
                current_stage=JobStage.DISCOVERED,
                status=JobStatus.IN_PROGRESS,
            )
            self.journal.save_job(job)
        else:
            job.status = JobStatus.IN_PROGRESS
            job.error_message = None
            self.reconcile_job_checkpoints(job)

        try:
            # Stage 1: Rights Policy Check
            manifest = self.rights_policy.check_rights(video_id)
            job.rights_manifest = manifest
            if not self.rights_policy.verify_rights(manifest):
                err = (
                    f"Rights check failed for '{video_id}'. Status: {manifest.status.value}. "
                    f"Basis: {manifest.basis.value}. Processing halted before asset resolution."
                )
                self.journal.mark_failed(job, err)
                raise RightsPolicyViolationError(err)

            self.journal.record_stage_checkpoint(
                job, JobStage.RIGHTS_CHECKED, {"rights_id": manifest.rights_id, "basis": manifest.basis.value}
            )

            # Stage 2: Asset Resolution & Preflight Probe (with checkpoint resumption)
            asset_path = None
            probe_info = None
            if JobStage.ASSET_INGESTED.value in job.checkpoints:
                prev_data = job.checkpoints[JobStage.ASSET_INGESTED.value].get("data", {})
                candidate_path = prev_data.get("asset_path")
                if candidate_path and os.path.exists(candidate_path) and os.path.getsize(candidate_path) > 0:
                    asset_path = candidate_path
                    probe_info = {"duration": prev_data.get("duration", 60.0), "sha256": prev_data.get("sha256", "")}

            if not asset_path:
                try:
                    asset_path = self.asset_provider.resolve_asset(video_id, manifest)
                except FileNotFoundError:
                    # Ingest authorized asset via provider download if not present in local cache
                    asset_path = self.asset_provider.download_asset(video_id, manifest)
                probe_info = self.asset_provider.probe_asset(asset_path)
                self.journal.record_stage_checkpoint(
                    job,
                    JobStage.ASSET_INGESTED,
                    {
                        "asset_path": asset_path,
                        "sha256": probe_info.get("sha256"),
                        "duration": probe_info.get("duration", 0.0),
                    },
                )

            # Stage 3: Transcription (with checkpoint resumption)
            transcript = None
            if JobStage.TRANSCRIBED.value in job.checkpoints:
                transcript = self.transcriber.load_from_cache(video_id)

            if not transcript:
                transcript = self.transcriber.transcribe(asset_path, video_id)
                self.journal.record_stage_checkpoint(
                    job,
                    JobStage.TRANSCRIBED,
                    {"num_segments": len(transcript.segments), "duration": transcript.duration_seconds},
                )

            # Stage 4 & 5: Candidate Detection, Scoring, & Deduplication
            top_candidate = None
            if JobStage.SCORED.value in job.checkpoints and job.candidate:
                top_candidate = job.candidate
            else:
                # Stage 4a: Extract Audience Retention Heatmap
                heatmap_data = None
                try:
                    heatmap_data = self.heatmap_analyzer.extract_heatmap(
                        video_id=video_id,
                        duration_seconds=transcript.duration_seconds,
                        transcript=transcript,
                    )
                except Exception:
                    pass

                # Stage 4b: Candidate Detection with Heatmap Peak Integration
                try:
                    candidates = self.detector.detect_candidates(transcript, heatmap=heatmap_data)
                except TypeError:
                    candidates = self.detector.detect_candidates(transcript)

                if not candidates:
                    err = f"No valid highlight moments detected for video '{video_id}' within duration bounds."
                    self.journal.mark_failed(job, err)
                    raise RuntimeError(err)

                self.journal.record_stage_checkpoint(
                    job, JobStage.SEGMENTED, {"num_candidates": len(candidates)}
                )

                # Stage 5: Highlight Scoring & Reranking with Heatmap Intelligence
                scored_candidates = [
                    self.scorer.score_candidate(c, transcript, heatmap=heatmap_data)
                    for c in candidates
                ]
                scored_candidates.sort(key=lambda c: c.score, reverse=True)
                # BUG-10 fix: Suppress overlapping candidates on scored and ranked candidates
                filtered_candidates = suppress_overlapping_candidates(scored_candidates)
                top_candidate = filtered_candidates[0] if filtered_candidates else scored_candidates[0]
                job.candidate = top_candidate
                self.journal.record_stage_checkpoint(
                    job,
                    JobStage.SCORED,
                    {
                        "top_candidate_id": top_candidate.candidate_id,
                        "score": top_candidate.score,
                        "rationale": top_candidate.rationale,
                        "heatmap_source": heatmap_data.source if heatmap_data else "NONE",
                    },
                )

            # Stage 5b: AI Metadata & Alternative Hooks (FEATURE-09)
            if self.metadata_generator and transcript:
                try:
                    meta = self.metadata_generator.generate_metadata(top_candidate, transcript)
                    if meta.title:
                        top_candidate.hook_title = meta.title
                    if meta.description:
                        top_candidate.suggested_description = meta.description
                    top_candidate.ai_metadata = meta.to_dict()
                except Exception:
                    pass

            # Stage 5c: Ingest Discovered Attribution & Virality Metadata
            try:
                db_m = getattr(self.journal, "db", None)
                if db_m and top_candidate:
                    conn = db_m.get_connection()
                    try:
                        cur = conn.execute(
                            "SELECT attribution_text, hourly_velocity, velocity_multiplier, virality_classification FROM discovered_uploads WHERE video_id = ?",
                            (video_id,),
                        )
                        d_row = cur.fetchone()
                        if d_row:
                            d_attr, d_vel, d_mult, d_class = d_row
                            if d_attr and d_attr not in (top_candidate.suggested_description or ""):
                                top_candidate.suggested_description = f"{top_candidate.suggested_description or ''}\n\n{d_attr}".strip()
                    finally:
                        conn.close()
            except Exception:
                pass

            # Stage 6: Review / Approval Gate
            if top_candidate.score >= auto_approve_threshold:
                top_candidate.approval_status = "APPROVED"
            else:
                top_candidate.approval_status = "PENDING_APPROVAL"

            self.journal.record_stage_checkpoint(
                job, JobStage.REVIEWED, {"approval_status": top_candidate.approval_status}
            )

            # BUG-26 fix: Validate candidate bounds against actual source duration prior to rendering
            source_dur = probe_info.get("duration", transcript.duration_seconds) if probe_info else transcript.duration_seconds
            if not top_candidate.validate_bounds(source_dur):
                err = (
                    f"Candidate '{top_candidate.candidate_id}' bounds [{top_candidate.start_seconds:.2f}, {top_candidate.end_seconds:.2f}] "
                    f"exceed or violate source media duration {source_dur:.2f}s."
                )
                self.journal.mark_failed(job, err)
                raise ValueError(err)

            # Stage 7: Vertical Video Rendering (with checkpoint resumption)
            rendered_clip = None
            if JobStage.RENDERED.value in job.checkpoints and job.rendered_clip:
                if os.path.exists(job.rendered_clip.file_path) and os.path.getsize(job.rendered_clip.file_path) > 0:
                    rendered_clip = job.rendered_clip

            if not rendered_clip:
                rendered_clip = self.renderer.render_clip(
                    source_path=asset_path,
                    candidate=top_candidate,
                    profile=render_profile,
                    output_dir=self.output_dir,
                    transcript=transcript,
                )
                job.rendered_clip = rendered_clip
                self.journal.record_stage_checkpoint(
                    job,
                    JobStage.RENDERED,
                    {"clip_id": rendered_clip.clip_id, "file_path": rendered_clip.file_path, "sha256": rendered_clip.file_hash},
                )

            # Stage 8: Post-Render Quality Assurance Verification (with checkpoint resumption)
            qa_report = None
            if JobStage.QA_VERIFIED.value in job.checkpoints and job.qa_report and job.qa_report.status != "FAILED":
                qa_report = job.qa_report

            if not qa_report:
                qa_report = self.verifier.verify_clip(rendered_clip, top_candidate)
                job.qa_report = qa_report
                if qa_report.status == "FAILED":
                    err = f"QA verification failed for clip '{rendered_clip.clip_id}': {qa_report.errors}"
                    self.journal.mark_failed(job, err)
                    raise RuntimeError(err)

                self.journal.record_stage_checkpoint(
                    job, JobStage.QA_VERIFIED, {"qa_status": qa_report.status, "errors": qa_report.errors, "warnings": qa_report.warnings}
                )

            # Stage 9: Autopost Handoff (with checkpoint resumption)
            handoff_receipt = None
            if JobStage.HANDED_OFF.value in job.checkpoints and job.handoff_receipt:
                handoff_receipt = job.handoff_receipt
            else:
                handoff_receipt = self.publisher.publish_clip(
                    rendered_clip=rendered_clip,
                    candidate=top_candidate,
                    rights_manifest=manifest,
                    qa_report=qa_report,
                    dry_run=dry_run,
                )
                job.handoff_receipt = handoff_receipt

            if handoff_receipt.status in ["DELIVERED", "DRY_RUN_SIMULATED", "DUPLICATE_SKIPPED"]:
                job.current_stage = JobStage.HANDED_OFF
                job.status = JobStatus.SUCCEEDED
            else:
                job.status = JobStatus.FAILED
                job.error_message = f"Handoff returned status '{handoff_receipt.status}'."

            self.journal.record_stage_checkpoint(
                job,
                JobStage.HANDED_OFF,
                {"receipt_id": handoff_receipt.receipt_id, "status": handoff_receipt.status, "dry_run": dry_run},
            )

            return job

        except Exception as e:
            if job.status != JobStatus.FAILED:
                self.journal.mark_failed(job, str(e))
            raise

    def get_candidates(self, video_id: str) -> List[HighlightCandidate]:
        """
        Extracts, segments, and scores candidate highlights for a video
        without rendering, allowing operator inspection and preview.
        """
        manifest = self.rights_policy.check_rights(video_id)
        if not self.rights_policy.verify_rights(manifest):
            raise RightsPolicyViolationError(
                f"Rights check failed for '{video_id}'. Status: {manifest.status.value}."
            )
        transcript = self.transcriber.load_from_cache(video_id)
        if not transcript:
            try:
                asset_path = self.asset_provider.resolve_asset(video_id, manifest)
            except FileNotFoundError:
                asset_path = self.asset_provider.download_asset(video_id, manifest)
            transcript = self.transcriber.transcribe(asset_path, video_id)

        heatmap_data = None
        try:
            heatmap_data = self.heatmap_analyzer.extract_heatmap(
                video_id=video_id,
                duration_seconds=transcript.duration_seconds if transcript else 0.0,
                transcript=transcript,
            )
        except Exception:
            pass

        try:
            candidates = self.detector.detect_candidates(transcript, heatmap=heatmap_data)
        except TypeError:
            candidates = self.detector.detect_candidates(transcript)
        scored = [self.scorer.score_candidate(c, transcript, heatmap=heatmap_data) for c in candidates]
        scored.sort(key=lambda c: c.score, reverse=True)
        # BUG-10 fix: Suppress overlapping candidates on scored candidates
        deduped = suppress_overlapping_candidates(scored)
        return deduped
