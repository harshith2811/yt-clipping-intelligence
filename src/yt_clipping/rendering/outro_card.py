"""
Dedicated Animated Outro Card & Bell Sound Engine.
Generates a standalone, broadcast-quality outro frame for the subscribe CTA:
- High-contrast animated subscribe sequence:
  Phase 1: Pulsing red [ SUBSCRIBE ] pill button
  Phase 2: Transition to [ 🔔 SUBSCRIBED ] with animated rocking bell icon
- Local-first synthetic bell notification chime (pure Python math/wave synthesis)
- Seamless video concatenation with format normalization and A/V sync protection
- Optional cinematic background blur sampled from the main video's final frame
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, Tuple
import os
import math
import struct
import wave
import subprocess
import tempfile
import logging

logger = logging.getLogger(__name__)


def synthesize_bell_chime(
    output_wav_path: str,
    duration: float = 1.8,
    sample_rate: int = 44100,
    f0: float = 523.25,
    chime_style: str = "soft_zen",
) -> str:
    """
    Synthesizes a soft, warm, broadcast-grade notification sound effect.
    Supports:
    - "soft_zen" (default): Warm, gentle acoustic marimba/celesta chime (C5 + G5 fifth),
      30ms raised-cosine soft attack, mellow body, non-intrusive ~ -12.5 dB peak.
    - "soft_double": Gentle ascending double-tone chime (G5 -> C6), modern minimalist UI feel.
    - "classic_bell": Original bright metallic bell (880Hz + metallic resonance).
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_wav_path)), exist_ok=True)
    num_samples = int(sample_rate * duration)
    samples = [0.0] * num_samples

    if chime_style == "classic_bell":
        notes = [
            {"t0": 0.0, "f0": f0 or 880.0, "gain": 0.45, "dur": 1.6, "tau": 0.45}
        ]
        attack_samples = int(0.005 * sample_rate)
    elif chime_style == "soft_double":
        notes = [
            {"t0": 0.0, "f0": 783.99, "gain": 0.12, "dur": 1.2, "tau": 0.35},
            {"t0": 0.12, "f0": 1046.50, "gain": 0.15, "dur": 1.5, "tau": 0.45},
        ]
        attack_samples = int(0.025 * sample_rate)
    else:  # "soft_zen" (default)
        base_f0 = f0 if (f0 and f0 != 880.0) else 523.25
        notes = [
            {"t0": 0.0, "f0": base_f0, "gain": 0.16, "dur": 1.6, "tau": 0.48}
        ]
        attack_samples = int(0.030 * sample_rate)  # 30ms raised cosine attack

    for note in notes:
        t0 = note["t0"]
        n_f0 = note["f0"]
        base_gain = note["gain"]
        tau = note["tau"]
        start_idx = int(t0 * sample_rate)

        if chime_style == "classic_bell":
            harmonics = [
                (n_f0, 1.0, tau),
                (n_f0 * 2.0, 0.55, tau * 0.78),
                (n_f0 * 3.0, 0.30, tau * 0.49),
                (n_f0 * 4.0, 0.18, tau * 0.33),
                (1318.51, 0.40, tau * 0.67),
                (5274.04, 0.12, tau * 0.18),
            ]
        else:
            # Soft harmonic series: fundamental + mellow fifth + gentle octave, NO shrill frequencies
            harmonics = [
                (n_f0, 1.0, tau),
                (n_f0 * 1.4983, 0.35, tau * 0.8),  # pure perfect fifth
                (n_f0 * 2.0, 0.18, tau * 0.6),     # octave
            ]

        for i in range(start_idx, num_samples):
            t = (i - start_idx) / sample_rate
            rel_i = i - start_idx
            if rel_i < attack_samples:
                env_attack = 0.5 * (1.0 - math.cos(math.pi * rel_i / attack_samples))
            else:
                env_attack = 1.0

            val = 0.0
            for freq, amp, t_decay in harmonics:
                decay = math.exp(-t / t_decay)
                val += amp * decay * math.sin(2.0 * math.pi * freq * t)

            samples[i] += val * env_attack * base_gain

    with wave.open(output_wav_path, "wb") as wf:
        wf.setnchannels(2)  # Stereo
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        stereo_data = bytearray()
        for s in samples:
            clamped = max(-0.99, min(0.99, s))
            pcm = int(clamped * 32767.0)
            stereo_data.extend(struct.pack("<hh", pcm, pcm))
        wf.writeframes(stereo_data)

    return output_wav_path


@dataclass
class OutroCardConfig:
    """Configuration for animated outro card and notification chime."""
    channel_name: str = "Subscribe for More"
    sub_heading: str = "Thanks for watching!"
    cta_prompt: str = "Turn on notifications for more clips!"
    duration: float = 2.5
    button_transform_time: float = 0.70
    theme: str = "cinematic_dark"    # cinematic_dark, cinematic_blur, minimal
    enable_chime: bool = True
    chime_style: str = "soft_zen"    # soft_zen, soft_double, classic_bell
    chime_freq: float = 523.25
    width: int = 1080
    height: int = 1920
    fps: float = 60.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OutroCardConfig:
        return cls(**data)


class OutroCardEngine:
    """
    Orchestrates the generation of dedicated animated outro cards:
    - Generates animated ASS script for button pulse, transition, and bell rocking
    - Renders the standalone outro video with synchronized chime sound effect
    - Concatenates the main video clip and outro card into a seamless master MP4
    """

    def __init__(self, default_config: Optional[OutroCardConfig] = None):
        self.default_config = default_config or OutroCardConfig()

    def generate_outro_ass(
        self,
        config: Optional[OutroCardConfig] = None,
        output_ass_path: Optional[str] = None,
    ) -> str:
        """
        Generates choreographed ASS subtitle script for the outro screen.
        """
        cfg = config or self.default_config
        w, h = cfg.width, cfg.height
        dur = cfg.duration
        t_trans = cfg.button_transform_time

        # Format timestamps in H:MM:SS.cs
        def to_ts(sec: float) -> str:
            hrs = int(sec // 3600)
            mins = int((sec % 3600) // 60)
            secs = sec % 60
            return f"{hrs}:{mins:02d}:{secs:05.2f}"

        t0_str = to_ts(0.0)
        dur_str = to_ts(dur)
        trans_str = to_ts(t_trans)
        rock1_str = to_ts(min(dur, t_trans + 0.15))
        rock2_str = to_ts(min(dur, t_trans + 0.30))
        rock3_str = to_ts(min(dur, t_trans + 0.45))
        prompt_in_str = to_ts(min(dur, t_trans + 0.10))

        channel_display = cfg.channel_name.upper().strip()
        sub_heading = cfg.sub_heading.strip()
        cta_prompt = cfg.cta_prompt.strip()

        # Styles definition (strictly no commas in font name to prevent ASS parser corruption)
        ass_content = f"""[Script Info]
Title: Dedicated Animated Outro Card
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ChannelTitle,Impact,68,&H00FFFFFF,&H0000FFFF,&H00180F08,&H0000E6FF,-1,0,0,0,100,100,2,0,1,6,3,8,40,40,480,1
Style: SubHeading,Arial,36,&H00CBD5E1,&H0000FFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,2,0,8,40,40,580,1
Style: SubBtnRed,Impact,56,&H00FFFFFF,&H0000FFFF,&H002010E0,&H00100870,-1,0,0,0,100,100,2,0,3,26,6,5,40,40,960,1
Style: SubBtnActive,Impact,56,&H00FFFFFF,&H0000FFFF,&H002A170F,&H0000E6FF,-1,0,0,0,100,100,2,0,3,26,6,5,40,40,960,1
Style: FooterPrompt,Impact,38,&H0000E6FF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,4,2,2,40,40,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,{t0_str},{dur_str},ChannelTitle,,0,0,0,,{{\\fad(250,200)}}{channel_display}
Dialogue: 1,{t0_str},{dur_str},SubHeading,,0,0,0,,{{\\fad(250,200)}}{sub_heading}
Dialogue: 2,{t0_str},{trans_str},SubBtnRed,,0,0,0,,{{\\an5\\pos({w // 2},{h // 2})\\t(0,350,\\fscx106\\fscy106)\\t(350,700,\\fscx100\\fscy100)}}SUBSCRIBE
Dialogue: 2,{trans_str},{rock1_str},SubBtnActive,,0,0,0,,{{\\an5\\pos({w // 2},{h // 2})\\frz10\\fscx108\\fscy108}}{{\\fnSegoe UI Emoji}}🔔{{\\fnImpact}}  SUBSCRIBED
Dialogue: 2,{rock1_str},{rock2_str},SubBtnActive,,0,0,0,,{{\\an5\\pos({w // 2},{h // 2})\\frz-10\\fscx108\\fscy108}}{{\\fnSegoe UI Emoji}}🔔{{\\fnImpact}}  SUBSCRIBED
Dialogue: 2,{rock2_str},{rock3_str},SubBtnActive,,0,0,0,,{{\\an5\\pos({w // 2},{h // 2})\\frz5\\fscx104\\fscy104}}{{\\fnSegoe UI Emoji}}🔔{{\\fnImpact}}  SUBSCRIBED
Dialogue: 2,{rock3_str},{dur_str},SubBtnActive,,0,0,0,,{{\\an5\\pos({w // 2},{h // 2})\\frz0\\fscx100\\fscy100}}{{\\fnSegoe UI Emoji}}🔔{{\\fnImpact}}  SUBSCRIBED
Dialogue: 1,{prompt_in_str},{dur_str},FooterPrompt,,0,0,0,,{{\\fad(200,200)}}{cta_prompt}
"""
        if output_ass_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_ass_path)), exist_ok=True)
            with open(output_ass_path, "w", encoding="utf-8") as f:
                f.write(ass_content)
        return ass_content

    def render_outro_clip(
        self,
        output_mp4_path: str,
        config: Optional[OutroCardConfig] = None,
        background_image_path: Optional[str] = None,
        vcodec: str = "h264_nvenc",
    ) -> str:
        """
        Renders a standalone animated outro MP4 video with synchronized bell chime audio.
        """
        cfg = config or self.default_config
        os.makedirs(os.path.dirname(os.path.abspath(output_mp4_path)), exist_ok=True)

        temp_dir = tempfile.mkdtemp(prefix="outro_card_")
        ass_path = os.path.join(temp_dir, "outro_anim.ass")
        self.generate_outro_ass(cfg, output_ass_path=ass_path)

        escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
        w, h = cfg.width, cfg.height
        dur = cfg.duration
        fps = cfg.fps
        delay_ms = int(cfg.button_transform_time * 1000)

        # Build FFmpeg command inputs and filtergraphs
        cmd: list[str] = ["ffmpeg", "-y"]

        # Background video input
        if background_image_path and os.path.exists(background_image_path):
            cmd.extend(["-loop", "1", "-t", f"{dur:.2f}", "-i", background_image_path])
            vf = (
                f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                f"boxblur=45:5,drawbox=x=0:y=0:w={w}:h={h}:color=0x060913@0.82:t=fill,"
                f"subtitles='{escaped_ass}'[v]"
            )
        else:
            cmd.extend(["-f", "lavfi", "-i", f"color=c=0x0B0F19:s={w}x{h}:d={dur:.2f}:r={fps}"])
            vf = (
                f"[0:v]drawbox=x=0:y=0:w={w}:h={h}:color=0x0F172A@0.5:t=fill,"
                f"subtitles='{escaped_ass}'[v]"
            )

        # Audio input (synthesized bell chime)
        if cfg.enable_chime:
            chime_wav_path = os.path.join(temp_dir, "bell_chime.wav")
            synthesize_bell_chime(
                chime_wav_path,
                duration=1.8,
                sample_rate=44100,
                f0=cfg.chime_freq,
                chime_style=getattr(cfg, "chime_style", "soft_zen"),
            )
            cmd.extend(["-i", chime_wav_path])
            af = f"[1:a]adelay={delay_ms}|{delay_ms},apad=whole_dur={dur:.2f}[a]"
        else:
            cmd.extend(["-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo", "-t", f"{dur:.2f}"])
            af = f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a]"

        filter_complex = f"{vf};{af}"

        # Test whether requested encoder works or fallback
        test_vcodec = vcodec
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", test_vcodec,
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-r", str(int(fps)),
            output_mp4_path,
        ])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError:
            # Fallback to libx264 if NVENC fails
            if test_vcodec != "libx264":
                idx = cmd.index(test_vcodec)
                cmd[idx] = "libx264"
                subprocess.run(cmd, capture_output=True, text=True, check=True)

        return output_mp4_path

    def concat_clip_with_outro(
        self,
        main_clip_path: str,
        outro_clip_path: str,
        output_path: str,
        vcodec: str = "h264_nvenc",
    ) -> str:
        """
        Concatenates the main video clip and outro card into a seamless master MP4.
        Standardizes SAR, framerate (60fps), and audio sample rate for click-free playback.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        tmp_output = output_path + ".tmp.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-i", main_clip_path,
            "-i", outro_clip_path,
            "-filter_complex",
            (
                "[0:v]setsar=1,fps=60[v0];"
                "[1:v]setsar=1,fps=60[v1];"
                "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];"
                "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];"
                "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
            ),
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", vcodec,
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            tmp_output,
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError:
            # Fallback to libx264 if hardware encoder unavailable
            if vcodec != "libx264":
                idx = cmd.index(vcodec)
                cmd[idx] = "libx264"
                subprocess.run(cmd, capture_output=True, text=True, check=True)

        if os.path.exists(tmp_output):
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(tmp_output, output_path)

        return output_path
