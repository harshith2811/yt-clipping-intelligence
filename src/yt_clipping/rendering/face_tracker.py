"""
Active-Speaker Detection and Dynamic Video Framing Engine using OpenCV.
Produces portrait (9:16) crops from landscape footage with:
1. Frame sampling across candidate time windows.
2. Multi-face detection with YuNet, Haar Cascade, and YOLOv8 fallbacks.
3. Constrained 1D kinematic camera trajectory optimization (AutoFlip-inspired).
4. Legacy EMA temporal smoothing fallback.
5. Scene-boundary aware crop stabilization and jump cut reset.
6. Deterministic, safe center-crop fallback.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Optional, Dict, Any, Sequence
import os
import math
import cv2
import numpy as np

try:
    from scipy.linalg import solveh_banded
except ImportError:
    solveh_banded = None


@dataclass
class TrajectoryConfig:
    canvas_width: int = 1920
    canvas_height: int = 1080
    crop_width: int = 608
    crop_height: int = 1080
    fps: float = 30.0
    max_velocity: float = 450.0          # Max panning speed (px/sec)
    max_acceleration: float = 750.0      # Max panning acceleration (px/sec^2)
    deadband_px: float = 24.0            # Micro-jitter deadband threshold (px)
    scene_cut_threshold: float = 0.35    # Normalized width jump to trigger shot reset
    smoothing_lambda_v: float = 0.10     # Velocity regularization weight
    smoothing_lambda_a: float = 0.05     # Acceleration/jerk regularization weight
    solver_mode: str = "hybrid"          # "hybrid" | "kinematic" | "convex"


@dataclass
class KinematicSegment:
    start_time: float
    end_time: float
    start_crop_x: int
    end_crop_x: int
    mode: str                           # "hold" | "pan" | "cut"
    max_velocity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrajectoryResult:
    raw_centers: np.ndarray             # (T,) raw detections
    smoothed_centers: np.ndarray        # (T,) smoothed centers in [c_min, c_max]
    smoothed_crop_x: np.ndarray         # (T,) even integers in [0, W - crop_w]
    timestamps: np.ndarray              # (T,) timestamps in seconds
    scene_cuts: List[float]             # Detected cut timestamps
    segments: List[KinematicSegment]     # Semantic camera actions (hold, pan, cut)
    ffmpeg_crop_filter: str             # libavfilter crop expression
    max_observed_velocity: float        # Observed max velocity (px/sec)
    max_observed_acceleration: float    # Observed max acceleration (px/sec^2)
    is_dynamic_pan: bool                # True if camera executes panning motion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_centers": self.raw_centers.tolist(),
            "smoothed_centers": self.smoothed_centers.tolist(),
            "smoothed_crop_x": self.smoothed_crop_x.tolist(),
            "timestamps": self.timestamps.tolist(),
            "scene_cuts": self.scene_cuts,
            "segments": [s.to_dict() for s in self.segments],
            "ffmpeg_crop_filter": self.ffmpeg_crop_filter,
            "max_observed_velocity": self.max_observed_velocity,
            "max_observed_acceleration": self.max_observed_acceleration,
            "is_dynamic_pan": self.is_dynamic_pan,
        }


class ConstrainedTrajectoryOptimizer:
    """
    AutoFlip-inspired 1D kinematic camera trajectory optimizer.
    Enforces viewport boundaries, velocity limits, acceleration ramps,
    and deadband hysteresis across scene shot segments.
    """

    def __init__(self, config: Optional[TrajectoryConfig] = None):
        self.config = config or TrajectoryConfig()

    def optimize(
        self,
        raw_centers: Sequence[Optional[float]],
        timestamps: Optional[Sequence[float]] = None,
        weights: Optional[Sequence[float]] = None,
        scene_cuts: Optional[Sequence[float]] = None,
        canvas_width: Optional[int] = None,
        crop_width: Optional[int] = None,
        crop_height: Optional[int] = None,
        fps: Optional[float] = None,
    ) -> TrajectoryResult:
        """
        Optimizes a 1D sequence of camera focal centers under kinematic constraints.
        Returns dense trajectory arrays, semantic segments, and FFmpeg filter expression.
        """
        canvas_w = int(canvas_width or self.config.canvas_width)
        crop_w = int(crop_width or self.config.crop_width)
        crop_h = int(crop_height or self.config.crop_height)
        fps_val = float(fps or self.config.fps)
        dt = 1.0 / max(fps_val, 1e-4)

        c_min = crop_w / 2.0
        c_max = canvas_w - crop_w / 2.0
        c_mid = canvas_w / 2.0
        x_mid = int(canvas_w - crop_w) // 2
        if x_mid % 2 != 0:
            x_mid = max(0, x_mid - 1)

        # Handle empty input
        if len(raw_centers) == 0:
            default_c = np.array([c_mid], dtype=np.float64)
            default_x = np.array([x_mid], dtype=int)
            default_t = np.array([0.0], dtype=np.float64)
            seg = KinematicSegment(start_time=0.0, end_time=0.0, start_crop_x=x_mid, end_crop_x=x_mid, mode="hold")
            return TrajectoryResult(
                raw_centers=default_c,
                smoothed_centers=default_c,
                smoothed_crop_x=default_x,
                timestamps=default_t,
                scene_cuts=[],
                segments=[seg],
                ffmpeg_crop_filter=f"crop={crop_w}:{crop_h}:{x_mid}:0",
                max_observed_velocity=0.0,
                max_observed_acceleration=0.0,
                is_dynamic_pan=False,
            )

        # Convert raw centers to float array with np.nan for None, non-finite, or invalid types
        sanitized_centers = []
        for c in raw_centers:
            if c is None:
                sanitized_centers.append(np.nan)
            else:
                try:
                    val = float(c)
                    sanitized_centers.append(val if np.isfinite(val) else np.nan)
                except (ValueError, TypeError):
                    sanitized_centers.append(np.nan)
        raw_arr = np.array(sanitized_centers, dtype=np.float64)
        T = len(raw_arr)

        if timestamps is None:
            ts = np.arange(T, dtype=np.float64) * dt
        else:
            ts = np.array(timestamps, dtype=np.float64)
            if len(ts) != T:
                ts = np.arange(T, dtype=np.float64) * dt

        # Impute missing centers
        imputed = self._impute_missing_centers(raw_arr, canvas_w)

        # Partition into contiguous shots
        cut_ts_list = list(scene_cuts) if scene_cuts else []
        shots = self._partition_into_shots(imputed, ts, cut_ts_list, canvas_w)

        # Process each shot independently to strictly prevent panning across cuts
        smoothed_centers = np.zeros(T, dtype=np.float64)
        solver_mode = self.config.solver_mode.lower()

        for s_idx, e_idx in shots:
            shot_targets = imputed[s_idx : e_idx + 1]
            shot_len = len(shot_targets)
            if shot_len == 1:
                smoothed_centers[s_idx] = np.clip(shot_targets[0], c_min, c_max)
                continue

            # 1. Apply deadband hysteresis to suppress micro-jitter
            db_targets = self._apply_deadband(shot_targets, self.config.deadband_px)

            # 2. Smooth trajectory
            shot_weights = None
            if weights is not None:
                if len(weights) == T:
                    shot_weights = weights[s_idx : e_idx + 1]
                elif len(weights) == shot_len:
                    shot_weights = weights

            if solver_mode == "convex":
                sc = self._solve_convex_banded(
                    db_targets, dt, shot_weights, self.config.smoothing_lambda_v, self.config.smoothing_lambda_a
                )
                sc = np.clip(sc, c_min, c_max)
            elif solver_mode == "kinematic":
                sc = self._apply_kinematic_forward_backward(
                    db_targets, dt, self.config.max_velocity, self.config.max_acceleration, c_min, c_max
                )
            else:  # "hybrid" default
                convex_c = self._solve_convex_banded(
                    db_targets, dt, shot_weights, self.config.smoothing_lambda_v, self.config.smoothing_lambda_a
                )
                sc = self._apply_kinematic_forward_backward(
                    convex_c, dt, self.config.max_velocity, self.config.max_acceleration, c_min, c_max
                )

            smoothed_centers[s_idx : e_idx + 1] = sc

        # Ensure bounds on all smoothed centers
        smoothed_centers = np.clip(smoothed_centers, c_min, c_max)

        # Convert centers to even crop X coordinates
        raw_crop_x = np.round(smoothed_centers - crop_w / 2.0).astype(int)
        raw_crop_x = np.clip(raw_crop_x, 0, canvas_w - crop_w)
        smoothed_crop_x = raw_crop_x - (raw_crop_x % 2)

        # Calculate observed kinematics (excluding shot cut boundaries)
        cut_start_indices = {s for s, e in shots if s > 0}
        max_obs_v = 0.0
        max_obs_a = 0.0

        if T >= 2:
            dts = np.maximum(np.diff(ts), 1e-4)
            diffs = np.diff(smoothed_centers)
            vels = np.zeros(T - 1, dtype=np.float64)
            for i in range(T - 1):
                if (i + 1) not in cut_start_indices:
                    vels[i] = abs(diffs[i]) / dts[i]
            max_obs_v = float(np.max(vels)) if len(vels) > 0 else 0.0

            if len(vels) >= 2:
                accs = np.zeros(len(vels) - 1, dtype=np.float64)
                for i in range(len(vels) - 1):
                    if (i + 1) not in cut_start_indices and (i + 2) not in cut_start_indices:
                        accs[i] = abs(vels[i + 1] - vels[i]) / dts[i]
                max_obs_a = float(np.max(accs)) if len(accs) > 0 else 0.0

        # Decompose into cinematic segments
        segments = self._decompose_segments(smoothed_crop_x, ts, shots, dt)

        # Build FFmpeg crop filter
        ffmpeg_filter, is_dynamic = self._build_ffmpeg_crop_expression(
            crop_w=crop_w,
            crop_h=crop_h,
            crop_xs=smoothed_crop_x,
            timestamps=ts,
            shots=shots,
            segments=segments,
            canvas_w=canvas_w,
        )

        return TrajectoryResult(
            raw_centers=raw_arr,
            smoothed_centers=smoothed_centers,
            smoothed_crop_x=smoothed_crop_x,
            timestamps=ts,
            scene_cuts=cut_ts_list,
            segments=segments,
            ffmpeg_crop_filter=ffmpeg_filter,
            max_observed_velocity=round(max_obs_v, 2),
            max_observed_acceleration=round(max_obs_a, 2),
            is_dynamic_pan=is_dynamic,
        )

    def _impute_missing_centers(self, raw: np.ndarray, canvas_w: float) -> np.ndarray:
        """Interpolates missing/dropped face detections across time."""
        c_mid = canvas_w / 2.0
        finite_mask = np.isfinite(raw)
        if not np.any(finite_mask):
            return np.full_like(raw, c_mid)
        if np.all(finite_mask):
            return raw.copy()

        indices = np.arange(len(raw))
        imputed = np.interp(indices, indices[finite_mask], raw[finite_mask])
        return imputed

    def _partition_into_shots(
        self,
        centers: np.ndarray,
        timestamps: np.ndarray,
        scene_cuts: List[float],
        canvas_w: float,
    ) -> List[Tuple[int, int]]:
        """Partitions sequence into continuous shots severed by cuts or large displacement jumps."""
        T = len(centers)
        if T <= 1:
            return [(0, T - 1)]

        jump_thresh = self.config.scene_cut_threshold * canvas_w
        shots: List[Tuple[int, int]] = []
        shot_start = 0

        for i in range(1, T):
            is_cut = False
            t_curr = timestamps[i]
            t_prev = timestamps[i - 1]

            # 1. External scene cut
            if any(t_prev < c <= t_curr for c in scene_cuts):
                is_cut = True
            # 2. Large spatial jump
            elif abs(centers[i] - centers[i - 1]) > jump_thresh:
                is_cut = True
            # 3. Temporal gap
            elif (t_curr - t_prev) > 1.0:
                is_cut = True

            if is_cut:
                shots.append((shot_start, i - 1))
                shot_start = i

        shots.append((shot_start, T - 1))
        return shots

    def _apply_deadband(self, targets: np.ndarray, deadband_px: float) -> np.ndarray:
        """Hysteresis deadband filter to eliminate micro-jitter and small head movements."""
        if deadband_px <= 0.0 or len(targets) <= 1:
            return targets.copy()

        out = np.zeros_like(targets)
        anchor = targets[0]
        out[0] = anchor

        for t in range(1, len(targets)):
            delta = targets[t] - anchor
            if abs(delta) <= deadband_px:
                out[t] = anchor
            else:
                anchor = targets[t] - np.sign(delta) * deadband_px
                out[t] = anchor

        return out

    def _solve_convex_banded(
        self,
        p: np.ndarray,
        dt: float,
        weights: Optional[Sequence[float]],
        lambda_v: float,
        lambda_a: float,
    ) -> np.ndarray:
        """Solves the pentadiagonal regularized quadratic smoothing system Ax = Wp in O(T) time."""
        T = len(p)
        if T <= 2:
            return p.copy()

        kv = lambda_v / max(dt ** 2, 1e-6)
        ka = lambda_a / max(dt ** 4, 1e-10)

        # Diagonals for banded format
        # ab shape: (3, T)
        # ab[2, :] = main diagonal
        # ab[1, 1:] = 1st superdiagonal
        # ab[0, 2:] = 2nd superdiagonal
        ab = np.zeros((3, T), dtype=np.float64)

        # Main diagonal
        ab[2, :] = 1.0 + 2.0 * kv + 6.0 * ka
        ab[2, 0] = 1.0 + kv + ka
        ab[2, -1] = 1.0 + kv + ka
        if T > 2:
            ab[2, 1] = 1.0 + 2.0 * kv + 5.0 * ka
            ab[2, -2] = 1.0 + 2.0 * kv + 5.0 * ka

        # 1st superdiagonal
        ab[1, 1:] = -kv - 4.0 * ka
        if T > 2:
            ab[1, 1] = -kv - 2.0 * ka
            ab[1, -1] = -kv - 2.0 * ka

        # 2nd superdiagonal
        if T > 2:
            ab[0, 2:] = ka

        # Weight modulation if provided
        if weights is not None and len(weights) == T:
            w_arr = np.array(weights, dtype=np.float64)
            ab[2, :] += (w_arr - 1.0)
            b = w_arr * p
        else:
            b = p.copy()

        if solveh_banded is not None:
            try:
                return solveh_banded(ab, b, lower=False)
            except Exception:
                pass

        # Fallback to dense symmetric banded linear solve
        A = np.zeros((T, T), dtype=np.float64)
        for i in range(T):
            A[i, i] = ab[2, i]
            if i + 1 < T:
                A[i, i + 1] = ab[1, i + 1]
                A[i + 1, i] = ab[1, i + 1]
            if i + 2 < T:
                A[i, i + 2] = ab[0, i + 2]
                A[i + 2, i] = ab[0, i + 2]
        return np.linalg.solve(A, b)

    def _apply_kinematic_forward_backward(
        self,
        p: np.ndarray,
        dt: float,
        v_max: float,
        a_max: float,
        c_min: float,
        c_max: float,
    ) -> np.ndarray:
        """Forward-backward pass clamping velocity and acceleration ramps."""
        N = len(p)
        if N <= 1:
            return np.clip(p, c_min, c_max)

        # 1. Forward Pass
        x_fwd = np.zeros(N, dtype=np.float64)
        v_fwd = np.zeros(N, dtype=np.float64)
        x_fwd[0] = np.clip(p[0], c_min, c_max)
        v_fwd[0] = 0.0

        for t in range(1, N):
            v_des = np.clip((p[t] - x_fwd[t - 1]) / dt, -v_max, v_max)
            v_t = np.clip(v_des, v_fwd[t - 1] - a_max * dt, v_fwd[t - 1] + a_max * dt)
            x_t = np.clip(x_fwd[t - 1] + v_t * dt, c_min, c_max)
            v_fwd[t] = (x_t - x_fwd[t - 1]) / dt
            x_fwd[t] = x_t

        # 2. Backward Pass (Safe deceleration distance to stop without jerk)
        x_bwd = np.zeros(N, dtype=np.float64)
        v_bwd = np.zeros(N, dtype=np.float64)
        x_bwd[-1] = x_fwd[-1]
        v_bwd[-1] = 0.0

        for t in range(N - 2, -1, -1):
            dist = abs(x_bwd[t + 1] - x_fwd[t])
            v_safe = math.sqrt(max(0.0, 2.0 * a_max * dist))
            v_lim = min(v_max, v_safe)
            diff = x_bwd[t + 1] - x_fwd[t]
            sign = 1.0 if diff >= 0 else -1.0
            v_des = sign * min(v_lim, abs(diff) / dt)
            v_t = np.clip(v_des, v_bwd[t + 1] - a_max * dt, v_bwd[t + 1] + a_max * dt)
            x_t = np.clip(x_bwd[t + 1] - v_t * dt, c_min, c_max)
            v_bwd[t] = (x_bwd[t + 1] - x_t) / dt
            x_bwd[t] = x_t

        # 3. Reconciliation & blend
        x_smooth = np.zeros(N, dtype=np.float64)
        for t in range(N):
            if t == 0:
                x_smooth[t] = x_fwd[0]
            elif t == N - 1:
                x_smooth[t] = x_fwd[-1]
            else:
                if x_fwd[t + 1] >= x_fwd[t - 1]:
                    x_smooth[t] = min(x_fwd[t], x_bwd[t])
                else:
                    x_smooth[t] = max(x_fwd[t], x_bwd[t])

        # 4. Final strict kinematic projection forward pass
        x_final = np.zeros(N, dtype=np.float64)
        v_final = np.zeros(N, dtype=np.float64)
        x_final[0] = np.clip(x_smooth[0], c_min, c_max)
        v_final[0] = 0.0

        for t in range(1, N):
            v_des = np.clip((x_smooth[t] - x_final[t - 1]) / dt, -v_max, v_max)
            v_t = np.clip(v_des, v_final[t - 1] - a_max * dt, v_final[t - 1] + a_max * dt)
            x_final[t] = np.clip(x_final[t - 1] + v_t * dt, c_min, c_max)
            v_final[t] = (x_final[t] - x_final[t - 1]) / dt

        return x_final

    def _decompose_segments(
        self,
        crop_xs: np.ndarray,
        timestamps: np.ndarray,
        shots: List[Tuple[int, int]],
        dt: float,
    ) -> List[KinematicSegment]:
        """Decomposes discrete camera path into semantic 'hold', 'pan', and 'cut' actions."""
        segments: List[KinematicSegment] = []
        T = len(crop_xs)
        if T == 0:
            return segments

        for s_idx, (s_start, s_end) in enumerate(shots):
            # If transition between shots exists, add a cut segment
            if s_idx > 0:
                prev_end = shots[s_idx - 1][1]
                segments.append(
                    KinematicSegment(
                        start_time=round(float(timestamps[prev_end]), 3),
                        end_time=round(float(timestamps[s_start]), 3),
                        start_crop_x=int(crop_xs[prev_end]),
                        end_crop_x=int(crop_xs[s_start]),
                        mode="cut",
                        max_velocity=0.0,
                    )
                )

            # Decompose within shot
            cur_start = s_start
            cur_mode = "hold"
            peak_v = 0.0

            for i in range(s_start + 1, s_end + 1):
                dx = abs(crop_xs[i] - crop_xs[i - 1])
                step_v = dx / dt
                is_moving = dx > 0

                step_mode = "pan" if is_moving else "hold"

                if step_mode != cur_mode:
                    # Flush current segment
                    segments.append(
                        KinematicSegment(
                            start_time=round(float(timestamps[cur_start]), 3),
                            end_time=round(float(timestamps[i - 1]), 3),
                            start_crop_x=int(crop_xs[cur_start]),
                            end_crop_x=int(crop_xs[i - 1]),
                            mode=cur_mode,
                            max_velocity=round(float(peak_v), 1),
                        )
                    )
                    cur_start = i - 1
                    cur_mode = step_mode
                    peak_v = step_v
                else:
                    peak_v = max(peak_v, step_v)

            # Flush tail segment of this shot
            segments.append(
                KinematicSegment(
                    start_time=round(float(timestamps[cur_start]), 3),
                    end_time=round(float(timestamps[s_end]), 3),
                    start_crop_x=int(crop_xs[cur_start]),
                    end_crop_x=int(crop_xs[s_end]),
                    mode=cur_mode,
                    max_velocity=round(float(peak_v), 1),
                )
            )

        return segments

    def _build_ffmpeg_crop_expression(
        self,
        crop_w: int,
        crop_h: int,
        crop_xs: np.ndarray,
        timestamps: np.ndarray,
        shots: List[Tuple[int, int]],
        segments: List[KinematicSegment],
        canvas_w: int,
    ) -> Tuple[str, bool]:
        """Constructs an executable FFmpeg filter expression representing holds, cuts, and smooth pans."""
        if len(crop_xs) == 0:
            center_x = (canvas_w - crop_w) // 2
            return f"crop={crop_w}:{crop_h}:{center_x}:0", False

        median_x = int(np.median(crop_xs))
        if median_x % 2 != 0:
            median_x = max(0, median_x - 1)

        # 1. Total variation check: static hold if camera barely moves (< 16 px)
        if np.ptp(crop_xs) < 16:
            return f"crop={crop_w}:{crop_h}:{median_x}:0", False

        # 2. Multi-shot cut step function check (if cuts exist without continuous pans)
        has_pan = any(s.mode == "pan" and abs(s.end_crop_x - s.start_crop_x) >= 20 for s in segments)
        has_cuts = len(shots) > 1

        if has_cuts and not has_pan:
            # Step function across shots
            shot_specs = []
            for s_start, s_end in shots:
                t_end = round(float(timestamps[s_end]), 3)
                med_shot = int(np.median(crop_xs[s_start : s_end + 1]))
                if med_shot % 2 != 0:
                    med_shot = max(0, med_shot - 1)
                shot_specs.append((t_end, med_shot))

            expr = str(shot_specs[-1][1])
            for k in range(len(shot_specs) - 2, -1, -1):
                t_b, x_v = shot_specs[k]
                expr = f"if(lt(t,{t_b:.2f}),{x_v},{expr})"
            return f"crop={crop_w}:{crop_h}:'{expr}':0", True

        # 3. Continuous pan ramp expressions
        pan_segments = [s for s in segments if s.mode == "pan" and (s.end_time - s.start_time) > 0.1]
        if not pan_segments:
            return f"crop={crop_w}:{crop_h}:{median_x}:0", False

        # Build ramp piecewise expression
        active_segs = [s for s in segments if s.mode in ("hold", "pan")]
        if not active_segs:
            return f"crop={crop_w}:{crop_h}:{median_x}:0", False

        # Build reverse nested if expression
        expr = str(active_segs[-1].end_crop_x)
        for s in reversed(active_segs):
            if s.mode == "hold":
                expr = f"if(lt(t,{s.end_time:.2f}),{s.start_crop_x},{expr})"
            elif s.mode == "pan":
                x0 = s.start_crop_x
                x1 = s.end_crop_x
                t0 = s.start_time
                t1 = s.end_time
                dur = max(t1 - t0, 0.05)
                ramp = f"round({x0}+({x1}-{x0})*(t-{t0:.2f})/{dur:.2f})"
                expr = f"if(lt(t,{s.end_time:.2f}),{ramp},{expr})"

        return f"crop={crop_w}:{crop_h}:'{expr}':0", True


class FaceFocusedFramer:
    """
    Computes smooth, face-focused 9:16 crop coordinates from source video.
    Supports both AutoFlip-inspired constrained trajectory optimization
    and legacy EMA temporal smoothing.
    """

    def __init__(
        self,
        sample_fps: float = 3.0,
        ema_alpha: float = 0.20,
        scene_jump_threshold: float = 0.35,  # Fraction of width jump to trigger cut reset
        yunet_model_path: Optional[str] = None,
        smoothing_mode: str = "constrained",  # "constrained" (default) or "ema"
        max_pan_velocity: float = 450.0,
        max_pan_acceleration: float = 750.0,
        deadband_px: float = 24.0,
        optimizer_config: Optional[TrajectoryConfig] = None,
    ):
        self.sample_fps = sample_fps
        self.ema_alpha = ema_alpha
        self.scene_jump_threshold = scene_jump_threshold
        self.smoothing_mode = smoothing_mode.lower()
        self.max_pan_velocity = max_pan_velocity
        self.max_pan_acceleration = max_pan_acceleration
        self.deadband_px = deadband_px
        self.model_type = "haar_cascade"

        # Initialize Trajectory Optimizer if constrained mode
        if self.smoothing_mode == "constrained":
            self.optimizer = ConstrainedTrajectoryOptimizer(
                config=optimizer_config
                or TrajectoryConfig(
                    max_velocity=max_pan_velocity,
                    max_acceleration=max_pan_acceleration,
                    deadband_px=deadband_px,
                    scene_cut_threshold=scene_jump_threshold,
                )
            )
        else:
            self.optimizer = None

        # 1. Initialize deep learning YuNet face detector if ONNX weights exist
        self.yunet = None
        yunet_candidates = [
            yunet_model_path,
            "models/face_detection_yunet_2023mar.onnx",
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../models/face_detection_yunet_2023mar.onnx")),
        ]
        for yp in yunet_candidates:
            if yp and os.path.exists(yp):
                try:
                    self.yunet = cv2.FaceDetectorYN.create(
                        model=os.path.abspath(yp),
                        config="",
                        input_size=(320, 320),
                        score_threshold=0.55,
                        nms_threshold=0.3,
                        top_k=5000,
                    )
                    self.model_type = "yunet_onnx"
                    break
                except Exception:
                    pass

        # 2. Initialize Haar cascade detector bundled with OpenCV as reliable fallback
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        # 3. Initialize deep learning YOLOv8 instance segmenter & subject finder
        self.subject_segmenter = None
        try:
            from .subject_segmenter import SubjectSegmenter
            self.subject_segmenter = SubjectSegmenter(device="cpu")
        except Exception:
            pass

    def analyze_crop_window(
        self,
        video_path: str,
        start_seconds: float,
        duration_seconds: float,
        target_aspect_ratio: float = 9.0 / 16.0,
    ) -> Dict[str, Any]:
        """
        Samples frames from video over [start_seconds, start_seconds + duration_seconds],
        detects face regions, and computes smoothed crop boundaries.
        Returns crop specifications compatible with FFmpeg crop filters.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return self._center_crop_fallback(1920, 1080, target_aspect_ratio)

        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        # Target crop dimensions (guaranteed even numbers)
        crop_h = src_h if src_h % 2 == 0 else src_h - 1
        crop_w = int(crop_h * target_aspect_ratio)
        if crop_w % 2 != 0:
            crop_w -= 1
        crop_w = min(crop_w, src_w)

        # Default center crop X coordinate
        center_x = max(0, (src_w - crop_w) // 2)
        if center_x % 2 != 0:
            center_x -= 1

        # 1. Detect scene shot boundaries across the clip window
        scene_cuts = [0.0]
        if duration_seconds >= 2.0:
            step_cut = max(1, int(fps * 0.20))  # sample 5 times per sec
            start_f = int(start_seconds * fps)
            end_f = int((start_seconds + duration_seconds) * fps)
            prev_h = None
            for f_idx in range(start_f, end_f, step_cut):
                cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                ret_c, frame_c = cap.read()
                if not ret_c or frame_c is None:
                    break
                gray_c = cv2.cvtColor(frame_c, cv2.COLOR_BGR2GRAY)
                hist_c = cv2.calcHist([gray_c], [0], None, [32], [0, 256])
                cv2.normalize(hist_c, hist_c)
                if prev_h is not None:
                    corr = cv2.compareHist(prev_h, hist_c, cv2.HISTCMP_CORREL)
                    if corr < 0.65:
                        t_rel = round((f_idx - start_f) / fps, 2)
                        if t_rel - scene_cuts[-1] >= 0.5:
                            scene_cuts.append(t_rel)
                prev_h = hist_c
            if scene_cuts[-1] < duration_seconds - 0.2:
                scene_cuts.append(round(duration_seconds, 2))

        # Sample representative frames across shots or clip window
        num_samples = max(min(int(duration_seconds * self.sample_fps), 48), 3)
        step_seconds = duration_seconds / max(num_samples, 1)

        raw_focal_centers: List[Optional[float]] = []
        sample_timestamps: List[float] = []

        detected_x_positions: List[float] = []
        smoothed_x_positions: List[float] = []
        time_positions: List[Tuple[float, float]] = []
        face_detected_count = 0
        subject_detected_count = 0
        multi_subject_count = 0

        current_smoothed_x = float(center_x)

        for i in range(num_samples):
            t_rel = i * step_seconds
            t = start_seconds + t_rel
            sample_timestamps.append(t_rel)

            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ret, frame = cap.read()
            if not ret or frame is None:
                raw_focal_centers.append(None)
                continue

            # Downsample frame for fast detection
            scale = 0.5
            small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            focal_x = None

            # 1. Primary: Try deep learning YuNet face detection first
            if self.yunet is not None:
                try:
                    self.yunet.setInputSize((small.shape[1], small.shape[0]))
                    _, y_faces = self.yunet.detect(small)
                    if y_faces is not None and len(y_faces) > 0:
                        best_y = max(y_faces, key=lambda f: f[2] * f[3])
                        fx = int((best_y[0] + best_y[2] / 2.0) / scale)
                        focal_x = fx
                        face_detected_count += 1
                        subject_detected_count += 1
                except Exception:
                    pass

            # 2. Secondary: Fallback to Haar Cascade face detector
            if focal_x is None:
                faces = self.face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.15,
                    minNeighbors=4,
                    minSize=(int(30 * scale), int(30 * scale)),
                )
                if len(faces) > 0:
                    best_face = max(faces, key=lambda f: f[2] * f[3])
                    fx = int((best_face[0] + best_face[2] / 2.0) / scale)
                    focal_x = fx
                    face_detected_count += 1
                    subject_detected_count += 1

            # 3. Tertiary: YOLOv8 Person & Subject Saliency
            if self.subject_segmenter is not None:
                try:
                    subjects = self.subject_segmenter.detect_subjects(frame)
                    if subjects:
                        subject_detected_count += 1
                        if len(subjects) >= 2:
                            xs = sorted([s["center_x"] for s in subjects])
                            if (xs[-1] - xs[0]) > (crop_w * 0.80):
                                multi_subject_count += 1

                        if focal_x is None:
                            primary_subj = max(subjects, key=lambda s: s["area"])
                            focal_x = primary_subj["center_x"]
                except Exception:
                    pass

            raw_focal_centers.append(focal_x)

            # Legacy EMA calculation
            if focal_x is not None:
                target_x = max(0, min(focal_x - (crop_w // 2), src_w - crop_w))
                jump_fraction = abs(target_x - current_smoothed_x) / float(src_w)
                if jump_fraction > self.scene_jump_threshold:
                    current_smoothed_x = float(target_x)
                else:
                    current_smoothed_x = (self.ema_alpha * target_x) + ((1.0 - self.ema_alpha) * current_smoothed_x)

                detected_x_positions.append(float(target_x))
                time_positions.append((t_rel, float(target_x)))
            else:
                current_smoothed_x = (0.05 * center_x) + (0.95 * current_smoothed_x)

            clamped_x = max(0.0, min(current_smoothed_x, float(src_w - crop_w)))
            smoothed_x_positions.append(clamped_x)

        cap.release()

        trajectory_dict = None

        if self.smoothing_mode == "constrained" and self.optimizer is not None:
            opt_res = self.optimizer.optimize(
                raw_centers=raw_focal_centers,
                timestamps=sample_timestamps,
                scene_cuts=scene_cuts,
                canvas_width=src_w,
                crop_width=crop_w,
                crop_height=crop_h,
                fps=self.sample_fps,
            )
            median_x = int(np.median(opt_res.smoothed_crop_x)) if len(opt_res.smoothed_crop_x) > 0 else center_x
            if median_x % 2 != 0:
                median_x = max(0, median_x - 1)
            crop_filter = opt_res.ffmpeg_crop_filter
            is_dynamic_pan = opt_res.is_dynamic_pan
            trajectory_dict = opt_res.to_dict()
        else:
            # Legacy EMA path
            if smoothed_x_positions:
                median_x = int(np.median(smoothed_x_positions))
            else:
                median_x = center_x
            if median_x % 2 != 0:
                median_x = max(0, median_x - 1)

            dynamic_crop_filter = None
            if len(scene_cuts) >= 3 and len(time_positions) >= 2:
                shot_crops = []
                for s_idx in range(len(scene_cuts) - 1):
                    t_s = scene_cuts[s_idx]
                    t_e = scene_cuts[s_idx + 1]
                    pts = [x for t_pos, x in time_positions if t_s <= t_pos <= t_e]
                    sx = int(np.median(pts)) if pts else median_x
                    sx = sx if sx % 2 == 0 else max(0, sx - 1)
                    sx = max(0, min(sx, src_w - crop_w))
                    shot_crops.append((t_s, t_e, sx))

                min_x = min(x for _, _, x in shot_crops)
                max_x = max(x for _, _, x in shot_crops)
                if (max_x - min_x) >= (src_w * 0.10):
                    expr = str(shot_crops[-1][2])
                    for k in range(len(shot_crops) - 2, -1, -1):
                        t_bound = shot_crops[k][1]
                        x_val = shot_crops[k][2]
                        expr = f"if(lt(t,{t_bound:.2f}),{x_val},{expr})"
                    dynamic_crop_filter = f"crop={crop_w}:{crop_h}:'{expr}':0"
            elif len(time_positions) >= 2:
                first_half = [x for t_pos, x in time_positions if t_pos < duration_seconds * 0.5]
                second_half = [x for t_pos, x in time_positions if t_pos >= duration_seconds * 0.5]
                if first_half and second_half:
                    med1 = int(np.median(first_half))
                    med2 = int(np.median(second_half))
                    med1 = med1 if med1 % 2 == 0 else max(0, med1 - 1)
                    med2 = med2 if med2 % 2 == 0 else max(0, med2 - 1)
                    if abs(med2 - med1) >= (src_w * 0.20):
                        cut_t = duration_seconds * 0.5
                        dynamic_crop_filter = f"crop={crop_w}:{crop_h}:'if(lt(t,{cut_t:.2f}),{med1},{med2})':0"

            crop_filter = dynamic_crop_filter or f"crop={crop_w}:{crop_h}:{median_x}:0"
            is_dynamic_pan = dynamic_crop_filter is not None

        face_conf = min(face_detected_count / float(max(num_samples, 1)), 1.0)
        subject_conf = min(subject_detected_count / float(max(num_samples, 1)), 1.0)
        is_multi_subj = (multi_subject_count / float(max(num_samples, 1))) >= 0.30

        res: Dict[str, Any] = {
            "crop_w": crop_w,
            "crop_h": crop_h,
            "crop_x": median_x,
            "crop_y": 0,
            "tracking_confidence": round(subject_conf, 2),
            "face_detected_ratio": round(face_conf, 2),
            "subject_detected_ratio": round(subject_conf, 2),
            "ffmpeg_crop_filter": crop_filter,
            "is_center_fallback": subject_conf < 0.20,
            "is_dynamic_pan": is_dynamic_pan,
            "is_multi_subject": is_multi_subj,
            "recommended_layout": "split_screen" if is_multi_subj else ("active_speaker" if subject_conf >= 0.35 else "blur_background"),
        }
        if trajectory_dict is not None:
            res["trajectory"] = trajectory_dict
        return res

    def _center_crop_fallback(self, src_w: int, src_h: int, target_aspect_ratio: float) -> Dict[str, Any]:
        crop_h = src_h if src_h % 2 == 0 else src_h - 1
        crop_w = int(crop_h * target_aspect_ratio)
        if crop_w % 2 != 0:
            crop_w -= 1
        crop_w = min(crop_w, src_w)
        center_x = max(0, (src_w - crop_w) // 2)
        if center_x % 2 != 0:
            center_x -= 1

        return {
            "crop_w": crop_w,
            "crop_h": crop_h,
            "crop_x": center_x,
            "crop_y": 0,
            "tracking_confidence": 0.0,
            "face_detected_ratio": 0.0,
            "ffmpeg_crop_filter": f"crop={crop_w}:{crop_h}:{center_x}:0",
            "is_center_fallback": True,
        }
