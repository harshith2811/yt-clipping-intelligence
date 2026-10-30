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
        self.output_dir = output_dir

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

        # Check existing job for resumption
        job = self.journal.get_job(actual_job_id)
        if not job:
            job = ClipJob(
                job_id=actual_job_id,
                video_id=video_id,
                current_stage=JobStage.DISCOVERED,
                status=JobStatus.IN_PROGRESS,
            )
            self.journal.save_job(job)

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

            # Stage 2: Asset Resolution & Preflight Probe
            asset_path = self.asset_provider.resolve_asset(video_id, manifest)
            probe_info = self.asset_provider.probe_asset(asset_path)
            self.journal.record_stage_checkpoint(
                job, JobStage.ASSET_INGESTED, {"asset_path": asset_path, "sha256": probe_info.get("sha256")}
            )

            # Stage 3: Transcription
            transcript = self.transcriber.transcribe(asset_path, video_id)
            self.journal.record_stage_checkpoint(
                job,
                JobStage.TRANSCRIBED,
                {"num_segments": len(transcript.segments), "duration": transcript.duration_seconds},
            )

            # Stage 4: Candidate Segmentation
            candidates = self.detector.detect_candidates(transcript)
            if not candidates:
                err = f"No valid highlight moments detected for video '{video_id}' within duration bounds."
                self.journal.mark_failed(job, err)
                raise RuntimeError(err)

            self.journal.record_stage_checkpoint(
                job, JobStage.SEGMENTED, {"num_candidates": len(candidates)}
            )

            # Stage 5: Highlight Scoring & Reranking with Heatmap Intelligence
            heatmap_data = None
            try:
                heatmap_data = self.heatmap_analyzer.extract_heatmap(
                    video_id=video_id,
                    duration_seconds=transcript.duration_seconds,
                    transcript=transcript,
                )
            except Exception:
                pass

            scored_candidates = [
                self.scorer.score_candidate(c, transcript, heatmap=heatmap_data)
                for c in candidates
            ]
            scored_candidates.sort(key=lambda c: c.score, reverse=True)
            top_candidate = scored_candidates[0]
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

            # Stage 6: Review / Approval Gate
            if top_candidate.score >= auto_approve_threshold:
                top_candidate.approval_status = "APPROVED"
            else:
                top_candidate.approval_status = "PENDING_APPROVAL"

            self.journal.record_stage_checkpoint(
                job, JobStage.REVIEWED, {"approval_status": top_candidate.approval_status}
            )

            # Stage 7: Vertical Video Rendering
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

            # Stage 8: Post-Render Quality Assurance Verification
            qa_report = self.verifier.verify_clip(rendered_clip, top_candidate)
            job.qa_report = qa_report
            if qa_report.status == "FAILED":
                err = f"QA verification failed for clip '{rendered_clip.clip_id}': {qa_report.errors}"
                self.journal.mark_failed(job, err)
                raise RuntimeError(err)

            self.journal.record_stage_checkpoint(
                job, JobStage.QA_VERIFIED, {"qa_status": qa_report.status, "errors": qa_report.errors, "warnings": qa_report.warnings}
            )

            # Stage 9: Autopost Handoff
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
        asset_path = self.asset_provider.resolve_asset(video_id, manifest)
        transcript = self.transcriber.transcribe(asset_path, video_id)
        candidates = self.detector.detect_candidates(transcript)
        heatmap_data = None
        try:
            heatmap_data = self.heatmap_analyzer.extract_heatmap(
                video_id=video_id,
                duration_seconds=transcript.duration_seconds,
                transcript=transcript,
            )
        except Exception:
            pass
        scored = [self.scorer.score_candidate(c, transcript, heatmap=heatmap_data) for c in candidates]
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored
