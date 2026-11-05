"""
End-to-End Orchestrated Clipping Pipeline.
Wires together Discovery, RightsGate, Ingestion, Transcription,
Candidate Detection, Highlight Scoring, FFmpeg Rendering, QA Verification,
and Autopost Handoff with checkpoint recovery.
"""

from typing import Optional, List, Dict, Any, Tuple
import uuid
import os
import subprocess
from datetime import datetime, timezone

from ..contracts.models import (
    ClipJob,
    JobStage,
    JobStatus,
    RenderProfile,
    HighlightCandidate,
    Transcript,
    TranscriptSegment,
    WordTimestamp,
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
from ..detection.short_viability import ShortViabilityValidator
from ..scoring.metadata_generator import MetadataGenerator
from ..detection.deadair import DeadAirPruner, PruneResult
from ..rendering.b_roll import BRollOverlayEngine, BRollConfig, BRollOverlayResult


def remap_transcript_for_keep_intervals(
    transcript: Transcript,
    keep_intervals: List[Tuple[float, float]],
    candidate_start: float = 0.0,
) -> Transcript:
    """
    Constructs a new continuous Transcript relative to 0.0 with timestamps shifted
    to account for excised dead-air intervals.
    """
    remapped_segments: List[TranscriptSegment] = []
    current_time_offset = 0.0

    # Calculate cumulative offset mappings for each keep interval
    interval_mappings = []
    for k_start, k_end in keep_intervals:
        dur = k_end - k_start
        # An event at source time t in [k_start, k_end] maps to: current_time_offset + (t - k_start)
        interval_mappings.append((k_start, k_end, current_time_offset))
        current_time_offset += dur

    for seg in transcript.segments:
        new_words: List[WordTimestamp] = []
        for w in seg.words:
            w_mid = (w.start + w.end) / 2.0
            for k_start, k_end, out_offset in interval_mappings:
                if k_start <= w_mid <= k_end:
                    s_rel = out_offset + (w.start - k_start)
                    e_rel = out_offset + (w.end - k_start)
                    new_words.append(
                        WordTimestamp(
                            word=w.word,
                            start=round(s_rel, 3),
                            end=round(e_rel, 3),
                        )
                    )
                    break

        if new_words:
            remapped_segments.append(
                TranscriptSegment(
                    segment_id=len(remapped_segments) + 1,
                    start=new_words[0].start,
                    end=new_words[-1].end,
                    text=" ".join(w.word for w in new_words),
                    words=new_words,
                    speaker_tag=seg.speaker_tag,
                )
            )

    return Transcript(
        video_id=transcript.video_id,
        language=transcript.language,
        duration_seconds=round(current_time_offset, 3),
        text=" ".join(s.text for s in remapped_segments),
        segments=remapped_segments,
    )


def apply_pacing_polish(
    candidate: HighlightCandidate,
    transcript: Transcript,
) -> HighlightCandidate:
    """
    Broadcast Hook Pacing Polish & Word Boundary Protection:
    1. Trims leading dead air > 0.15s down to ~0.10s preceding speech onset.
    2. Protects speech onset against mid-word truncation if cut boundary starts inside a word.
    3. Protects outro boundary against mid-word truncation.
    4. Trims excessive trailing dead air (> 0.40s) down to ~0.25s for clean fade transitions.
    """
    cand_words: List[WordTimestamp] = []
    for s in transcript.segments:
        for w in s.words:
            if w.end > candidate.start_seconds and w.start < candidate.end_seconds:
                cand_words.append(w)

    if cand_words:
        # 1. Start boundary: avoid mid-word truncation or trim leading dead-air to ~0.10s
        first_w = cand_words[0]
        if first_w.start < candidate.start_seconds:
            candidate.start_seconds = max(0.0, round(first_w.start - 0.10, 2))
        else:
            leading_pause = first_w.start - candidate.start_seconds
            if leading_pause > 0.15:
                candidate.start_seconds = max(0.0, round(first_w.start - 0.10, 2))

        # 2. Outro boundary: protect against mid-word cutoffs and prune excessive dead-air tails
        last_w = cand_words[-1]
        if last_w.start < candidate.end_seconds < last_w.end:
            candidate.end_seconds = round(last_w.end, 2)
        elif candidate.end_seconds - last_w.end > 0.40:
            candidate.end_seconds = round(last_w.end + 0.25, 2)

        candidate.duration_seconds = round(candidate.end_seconds - candidate.start_seconds, 2)

    return candidate


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
        viability_validator: Optional[ShortViabilityValidator] = None,
        dead_air_pruner: Optional[DeadAirPruner] = None,
        b_roll_engine: Optional[BRollOverlayEngine] = None,
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
        self.viability_validator = viability_validator or ShortViabilityValidator()
        self.dead_air_pruner = dead_air_pruner or DeadAirPruner()
        self.b_roll_engine = b_roll_engine or BRollOverlayEngine()
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
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
        enable_deadair_pruning: bool = False,
        enable_broll: bool = False,
        broll_assets_dir: Optional[str] = None,
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
                        min_duration=min_duration or 15.0,
                        max_duration=max_duration or 60.0,
                    )
                except Exception:
                    pass

                # Stage 4b: Candidate Detection with Heatmap Peak Integration
                try:
                    candidates = self.detector.detect_candidates(
                        transcript,
                        min_duration=min_duration,
                        max_duration=max_duration,
                        heatmap=heatmap_data,
                    )
                except TypeError:
                    try:
                        candidates = self.detector.detect_candidates(
                            transcript,
                            min_duration=min_duration,
                            max_duration=max_duration,
                        )
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
                # Select highest scoring candidate from deduplicated pool
                top_candidate = max(filtered_candidates, key=lambda c: c.score) if filtered_candidates else scored_candidates[0]
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

            return self._process_candidate_lifecycle(
                job=job,
                candidate=top_candidate,
                transcript=transcript,
                asset_path=asset_path,
                probe_info=probe_info,
                manifest=manifest,
                render_profile=render_profile,
                auto_approve_threshold=auto_approve_threshold,
                dry_run=dry_run,
                enable_deadair_pruning=enable_deadair_pruning,
                enable_broll=enable_broll,
                broll_assets_dir=broll_assets_dir,
            )

        except Exception as e:
            if job.status != JobStatus.FAILED:
                self.journal.mark_failed(job, str(e))
            raise

    def _process_candidate_lifecycle(
        self,
        job: ClipJob,
        candidate: HighlightCandidate,
        transcript: Transcript,
        asset_path: str,
        probe_info: Optional[Dict[str, Any]],
        manifest: Optional[Any],
        render_profile: RenderProfile,
        auto_approve_threshold: float,
        dry_run: bool,
        enable_deadair_pruning: bool,
        enable_broll: bool,
        broll_assets_dir: Optional[str],
    ) -> ClipJob:
        job.candidate = candidate

        # Stage 6: Review / Approval Gate (Stand-Alone Short Viability Check)
        viability_checkpoint = {}
        if self.viability_validator:
            try:
                viability_report = self.viability_validator.validate_candidate(candidate, transcript)
                viability_checkpoint["viability"] = viability_report.to_dict()
                candidate.loop_affinity_score = round(viability_report.loop_hook_score * 10.0, 1)
                if not viability_report.is_viable:
                    candidate.approval_status = "REJECTED"
                    critique_str = "; ".join(viability_report.reasons_for_rejection)
                    candidate.rationale = f"{candidate.rationale} [Viability Rejected: {critique_str}]".strip()
                elif candidate.score >= auto_approve_threshold:
                    candidate.approval_status = "APPROVED"
                else:
                    candidate.approval_status = "PENDING_APPROVAL"
            except Exception:
                if candidate.score >= auto_approve_threshold:
                    candidate.approval_status = "APPROVED"
                else:
                    candidate.approval_status = "PENDING_APPROVAL"
        else:
            if candidate.score >= auto_approve_threshold:
                candidate.approval_status = "APPROVED"
            else:
                candidate.approval_status = "PENDING_APPROVAL"

        # Stage 6b: Broadcast Hook Pacing Polish & Word Boundary Protection
        if getattr(render_profile, "enable_pacing_polish", False) and transcript and not enable_deadair_pruning:
            candidate = apply_pacing_polish(candidate, transcript)

        checkpoint_payload = {
            "approval_status": candidate.approval_status,
            "loop_affinity_score": getattr(candidate, "loop_affinity_score", 0.0),
        }
        checkpoint_payload.update(viability_checkpoint)
        self.journal.record_stage_checkpoint(
            job, JobStage.REVIEWED, checkpoint_payload
        )

        # Validate candidate bounds against actual source duration prior to rendering
        source_dur = probe_info.get("duration", transcript.duration_seconds) if probe_info else transcript.duration_seconds
        if not candidate.validate_bounds(source_dur):
            err = (
                f"Candidate '{candidate.candidate_id}' bounds [{candidate.start_seconds:.2f}, {candidate.end_seconds:.2f}] "
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
            active_source_path = asset_path
            active_candidate = candidate
            active_transcript = transcript
            deadair_telemetry = None

            # Pre-render micro-jump-cuts via DeadAirPruner if enabled
            if enable_deadair_pruning and self.dead_air_pruner and transcript:
                prune_res = self.dead_air_pruner.prune_candidate(candidate, transcript)
                deadair_telemetry = prune_res.to_dict()
                if prune_res.keep_intervals and (candidate.duration_seconds - prune_res.pruned_duration > 0.1):
                    pruned_tmp_path = os.path.join(self.output_dir, f"pruned_{candidate.candidate_id}.mp4")
                    os.makedirs(self.output_dir, exist_ok=True)
                    v_expr, a_expr = self.dead_air_pruner.generate_select_expressions(
                        prune_res.keep_intervals, offset_seconds=0.0
                    )
                    if os.path.exists(asset_path) and os.path.getsize(asset_path) > 1000:
                        cut_cmd = [
                            "ffmpeg", "-y", "-i", asset_path,
                            "-filter_complex", f"[0:v]{v_expr}[v];[0:a]{a_expr}[a]",
                            "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-preset", "ultrafast",
                            "-c:a", "aac",
                            pruned_tmp_path,
                        ]
                        try:
                            res = subprocess.run(cut_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                            if res.returncode == 0 and os.path.exists(pruned_tmp_path) and os.path.getsize(pruned_tmp_path) > 0:
                                active_source_path = pruned_tmp_path
                        except Exception:
                            pass

                    candidate.start_seconds = 0.0
                    candidate.end_seconds = prune_res.pruned_duration
                    candidate.duration_seconds = prune_res.pruned_duration
                    active_transcript = remap_transcript_for_keep_intervals(
                        transcript,
                        prune_res.keep_intervals,
                        candidate_start=0.0,
                    )

            rendered_clip = self.renderer.render_clip(
                source_path=active_source_path,
                candidate=candidate,
                profile=render_profile,
                output_dir=self.output_dir,
                transcript=active_transcript,
            )

            # Post-render Automated B-Roll Overlay if enabled
            broll_telemetry = None
            if enable_broll and self.b_roll_engine and active_transcript:
                words = []
                for seg in active_transcript.segments:
                    words.extend(seg.words)
                broll_out_path = os.path.join(
                    self.output_dir,
                    f"{os.path.splitext(os.path.basename(rendered_clip.file_path))[0]}_broll.mp4"
                )
                broll_res = self.b_roll_engine.apply_broll_overlay(
                    video_path=rendered_clip.file_path,
                    output_path=broll_out_path,
                    words=words,
                    candidate=candidate,
                    clip_start=0.0 if enable_deadair_pruning else candidate.start_seconds,
                    clip_end=candidate.duration_seconds if enable_deadair_pruning else candidate.end_seconds,
                    assets_dir=broll_assets_dir,
                )
                broll_telemetry = broll_res.to_dict()
                if broll_res.applied:
                    rendered_clip.file_path = broll_res.output_video_path
                    if broll_res.file_hash:
                        rendered_clip.file_hash = broll_res.file_hash

            job.rendered_clip = rendered_clip
            checkpoint_payload = {
                "clip_id": rendered_clip.clip_id,
                "file_path": rendered_clip.file_path,
                "sha256": rendered_clip.file_hash,
            }
            if deadair_telemetry:
                checkpoint_payload["deadair_pruned"] = deadair_telemetry
            if broll_telemetry:
                checkpoint_payload["broll_overlay"] = broll_telemetry

            self.journal.record_stage_checkpoint(
                job,
                JobStage.RENDERED,
                checkpoint_payload,
            )

        # Stage 8: Post-Render Quality Assurance Verification (with checkpoint resumption)
        qa_report = None
        if JobStage.QA_VERIFIED.value in job.checkpoints and job.qa_report and job.qa_report.status != "FAILED":
            qa_report = job.qa_report

        if not qa_report:
            qa_report = self.verifier.verify_clip(rendered_clip, candidate)
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
                candidate=candidate,
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

    def process_video_multi(
        self,
        video_id: str,
        max_clips: int = 3,
        profile: Optional[RenderProfile] = None,
        dry_run: bool = True,
        auto_approve_threshold: float = 65.0,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
        enable_deadair_pruning: bool = False,
        enable_broll: bool = False,
        broll_assets_dir: Optional[str] = None,
    ) -> List[ClipJob]:
        """
        Extracts, ranks, and renders up to max_clips distinct, non-overlapping
        viral moments from a single source video.
        """
        render_profile = profile or RenderProfile()
        manifest = self.rights_policy.check_rights(video_id)
        if not self.rights_policy.verify_rights(manifest):
            raise RightsPolicyViolationError(
                f"Rights check failed for '{video_id}'. Status: {manifest.status.value}."
            )

        try:
            asset_path = self.asset_provider.resolve_asset(video_id, manifest)
        except FileNotFoundError:
            asset_path = self.asset_provider.download_asset(video_id, manifest)

        probe_info = None
        try:
            probe_info = self.asset_provider.probe_asset(asset_path)
        except Exception:
            pass

        transcript = self.transcriber.load_from_cache(video_id)
        if not transcript or not transcript.segments:
            transcript = self.transcriber.transcribe(asset_path, video_id)

        heatmap_data = None
        try:
            heatmap_data = self.heatmap_analyzer.extract_heatmap(
                video_id=video_id,
                duration_seconds=transcript.duration_seconds if transcript else 0.0,
                transcript=transcript,
                min_duration=min_duration or 15.0,
                max_duration=max_duration or 60.0,
            )
        except Exception:
            pass

        try:
            candidates = self.detector.detect_candidates(
                transcript, min_duration=min_duration, max_duration=max_duration, heatmap=heatmap_data
            )
        except TypeError:
            try:
                candidates = self.detector.detect_candidates(
                    transcript, min_duration=min_duration, max_duration=max_duration
                )
            except TypeError:
                candidates = self.detector.detect_candidates(transcript)

        if not candidates:
            raise RuntimeError(f"No valid highlight moments detected for video '{video_id}' within duration bounds.")

        scored_candidates = [
            self.scorer.score_candidate(c, transcript, heatmap=heatmap_data)
            for c in candidates
        ]
        from ..detection.solid_shorts import SolidShortsDecider
        decider = SolidShortsDecider()
        decision = decider.decide(
            candidates=scored_candidates,
            duration_seconds=transcript.duration_seconds if transcript else 0.0,
            heatmap_data=heatmap_data,
            target_count=max_clips,
            strict_quality=True,
        )
        target_clips = decision.selected_candidates
        if not target_clips and scored_candidates:
            target_clips = [scored_candidates[0]]

        completed_jobs: List[ClipJob] = []
        for idx, cand in enumerate(target_clips, 1):
            clip_job_id = f"job-{video_id}-c{idx}-{uuid.uuid4().hex[:6]}"
            job = ClipJob(
                job_id=clip_job_id,
                video_id=video_id,
                current_stage=JobStage.SCORED,
                status=JobStatus.IN_PROGRESS,
                rights_manifest=manifest,
                candidate=cand,
            )
            self.journal.save_job(job)

            if self.metadata_generator and transcript:
                try:
                    meta = self.metadata_generator.generate_metadata(cand, transcript)
                    if meta.title:
                        cand.hook_title = meta.title
                    if meta.description:
                        cand.suggested_description = meta.description
                    cand.ai_metadata = meta.to_dict()
                except Exception:
                    pass

            rendered_job = self._process_candidate_lifecycle(
                job=job,
                candidate=cand,
                transcript=transcript,
                asset_path=asset_path,
                probe_info=probe_info,
                manifest=manifest,
                render_profile=render_profile,
                auto_approve_threshold=auto_approve_threshold,
                dry_run=dry_run,
                enable_deadair_pruning=enable_deadair_pruning,
                enable_broll=enable_broll,
                broll_assets_dir=broll_assets_dir,
            )
            completed_jobs.append(rendered_job)

        return completed_jobs

    def get_candidates(
        self,
        video_id: str,
        min_duration: Optional[float] = None,
        max_duration: Optional[float] = None,
    ) -> List[HighlightCandidate]:
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
                min_duration=min_duration or 15.0,
                max_duration=max_duration or 60.0,
            )
        except Exception:
            pass

        try:
            candidates = self.detector.detect_candidates(
                transcript,
                min_duration=min_duration,
                max_duration=max_duration,
                heatmap=heatmap_data,
            )
        except TypeError:
            try:
                candidates = self.detector.detect_candidates(
                    transcript,
                    min_duration=min_duration,
                    max_duration=max_duration,
                )
            except TypeError:
                candidates = self.detector.detect_candidates(transcript)
        scored = [self.scorer.score_candidate(c, transcript, heatmap=heatmap_data) for c in candidates]
        scored.sort(key=lambda c: c.score, reverse=True)
        # BUG-10 fix: Suppress overlapping candidates on scored candidates
        deduped = suppress_overlapping_candidates(scored)
        return deduped


PipelineCoordinator = ClippingPipeline

__all__ = [
    "ClippingPipeline",
    "PipelineCoordinator",
    "remap_transcript_for_keep_intervals",
    "apply_pacing_polish",
]
