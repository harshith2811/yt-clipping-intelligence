"""
Cloudflare Workers AI FLUX.1 Engine.
Integrates Black Forest Labs FLUX.1 Schnell (@cf/black-forest-labs/flux-1-schnell)
via Cloudflare Workers AI REST API for automated generation of:
1. High-impact 9:16 vertical hook backdrops
2. Contextual visual B-roll cards and Ken Burns motion video clips
3. Short thumbnail cover art and title cards
"""

import os
import re
import time
import shutil
import base64
import hashlib
import logging
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
import requests

from ..config import AppConfig

logger = logging.getLogger("flux_generator")

STYLE_PRESETS: Dict[str, str] = {
    "cinematic_hook": (
        "Cinematic vertical 9:16 frame, striking focal subject, dramatic lighting, "
        "high depth of field, sharp photorealistic detail, uncompressed, dynamic contrast: {prompt}"
    ),
    "tech_minimal": (
        "Clean modern tech aesthetic, sleek minimal composition, studio key lighting, "
        "matte backdrop, high visual clarity: {prompt}"
    ),
    "documentary": (
        "Documentary realism, 35mm film grain, authentic texture, cinematic color grading, "
        "raw candid angle: {prompt}"
    ),
    "neon_cyber": (
        "High energy cyberpunk aesthetic, vibrant neon rim lighting, deep shadows, "
        "cinematic atmosphere: {prompt}"
    ),
    "raw": "{prompt}",
}


@dataclass
class FluxGenerationResult:
    """Provenance telemetry resulting from FLUX image generation."""
    success: bool
    prompt: str
    styled_prompt: str
    style_preset: str
    file_path: str
    image_base64: str
    width: int
    height: int
    steps: int
    latency_ms: float
    is_fallback: bool = False
    error: Optional[str] = None
    broll_video_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Avoid huge payload in serialized logs if needed, but keep base64 accessible
        return d


class FluxImageGenerator:
    """
    Client for Cloudflare Workers AI FLUX.1 Schnell image generation.
    Supports real-time edge inference and offline fallback generation.
    """

    MODEL_ID = "@cf/black-forest-labs/flux-1-schnell"

    def __init__(
        self,
        account_id: Optional[str] = None,
        api_token: Optional[str] = None,
        output_dir: Optional[str] = None,
    ):
        cfg = AppConfig()
        self.account_id = (
            account_id
            or cfg.cloudflare_account_id
            or os.environ.get("CLOUDFLARE_ACCOUNT_ID")
            or os.environ.get("CF_ACCOUNT_ID")
            or ""
        )
        self.api_token = (
            api_token
            or cfg.cloudflare_api_token
            or os.environ.get("CLOUDFLARE_API_TOKEN")
            or os.environ.get("CF_API_TOKEN")
            or ""
        )
        self.output_dir = output_dir or os.path.join(cfg.assets_dir, "flux")
        os.makedirs(self.output_dir, exist_ok=True)

    @property
    def is_configured(self) -> bool:
        """Returns True if Cloudflare account ID and API token are set."""
        return bool(self.account_id and self.api_token)

    def get_status(self) -> Dict[str, Any]:
        """Returns operational readiness and credential status."""
        return {
            "configured": self.is_configured,
            "model": self.MODEL_ID,
            "provider": "Cloudflare Workers AI",
            "account_id_masked": (
                f"{self.account_id[:4]}...{self.account_id[-4:]}"
                if len(self.account_id) > 8
                else ("set" if self.account_id else "missing")
            ),
            "free_tier_active": True,
            "output_dir": self.output_dir,
            "style_presets": list(STYLE_PRESETS.keys()),
        }

    def build_prompt(self, prompt: str, style_preset: str = "cinematic_hook") -> str:
        """Applies visual style template to raw prompt."""
        template = STYLE_PRESETS.get(style_preset, STYLE_PRESETS["cinematic_hook"])
        return template.format(prompt=prompt.strip())

    def generate_image(
        self,
        prompt: str,
        style_preset: str = "cinematic_hook",
        width: int = 768,
        height: int = 1344,
        steps: int = 4,
        output_path: Optional[str] = None,
    ) -> FluxGenerationResult:
        """
        Generates an image from text using Cloudflare Workers AI FLUX.1.
        Falls back smoothly to procedural card if credentials are absent.
        """
        start_t = time.perf_counter()
        styled_prompt = self.build_prompt(prompt, style_preset)
        steps = max(1, min(steps, 8))

        if not output_path:
            prompt_hash = hashlib.sha256(styled_prompt.encode("utf-8")).hexdigest()[:12]
            ts = int(time.time())
            filename = f"flux_{ts}_{prompt_hash}.png"
            output_path = os.path.join(self.output_dir, filename)

        # Path 1: Cloudflare Workers AI REST API
        if self.is_configured:
            endpoint = (
                f"https://api.cloudflare.com/client/v4/accounts/"
                f"{self.account_id}/ai/run/{self.MODEL_ID}"
            )
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "prompt": styled_prompt,
                "steps": steps,
            }

            try:
                logger.info(f"Calling Cloudflare Workers AI FLUX.1 with prompt: '{prompt[:60]}...'")
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
                latency_ms = round((time.perf_counter() - start_t) * 1000, 2)

                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    img_bytes: bytes

                    if "application/json" in content_type:
                        data = resp.json()
                        if "result" in data and "image" in data["result"]:
                            b64_str = data["result"]["image"]
                            img_bytes = base64.b64decode(b64_str)
                        else:
                            raise ValueError(f"Unexpected JSON schema from Cloudflare: {list(data.keys())}")
                    else:
                        img_bytes = resp.content

                    with open(output_path, "wb") as f:
                        f.write(img_bytes)

                    b64_output = base64.b64encode(img_bytes).decode("utf-8")
                    return FluxGenerationResult(
                        success=True,
                        prompt=prompt,
                        styled_prompt=styled_prompt,
                        style_preset=style_preset,
                        file_path=output_path,
                        image_base64=f"data:image/png;base64,{b64_output}",
                        width=width,
                        height=height,
                        steps=steps,
                        latency_ms=latency_ms,
                        is_fallback=False,
                    )
                else:
                    logger.warning(
                        f"Cloudflare Workers AI returned status {resp.status_code}: {resp.text[:200]}. "
                        f"Falling back to procedural visual card."
                    )
            except Exception as e:
                logger.warning(f"Error querying Cloudflare Workers AI: {e}. Falling back to procedural card.")

        # Path 2: Procedural Visual Card Fallback
        latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
        fallback_res = self._generate_procedural_fallback(
            prompt=prompt,
            styled_prompt=styled_prompt,
            style_preset=style_preset,
            width=width,
            height=height,
            steps=steps,
            output_path=output_path,
            latency_ms=latency_ms,
        )
        return fallback_res

    def _generate_procedural_fallback(
        self,
        prompt: str,
        styled_prompt: str,
        style_preset: str,
        width: int,
        height: int,
        steps: int,
        output_path: str,
        latency_ms: float,
    ) -> FluxGenerationResult:
        """
        Creates an offline procedural visual card (PNG) when Cloudflare credentials are unset.
        Guarantees zero crashes for offline local execution, tests, and preview modes.
        """
        if not output_path.endswith(".png"):
            output_path = output_path + ".png"

        try:
            import cv2
            import numpy as np

            # Create dark gradient background
            img = np.zeros((height, width, 3), dtype=np.uint8)
            for y in range(height):
                ratio = y / height
                # Smooth dark gradient from deep navy to slate black
                b = int(24 + 18 * (1 - ratio))
                g = int(15 + 10 * (1 - ratio))
                r = int(15 + 25 * ratio)
                img[y, :] = [b, g, r]

            # Subtle grid overlay
            grid_spacing = 40
            for x in range(0, width, grid_spacing):
                cv2.line(img, (x, 0), (x, height), (35, 45, 60), 1)
            for y in range(0, height, grid_spacing):
                cv2.line(img, (0, y), (width, y), (35, 45, 60), 1)

            # Draw top badge pill
            cv2.rectangle(img, (50, 70), (280, 115), (245, 130, 49), -1)  # Accent blue
            cv2.putText(
                img,
                "FLUX.1 SCHNELL",
                (65, 102),
                cv2.FONT_HERSHEY_DUPLEX,
                0.7,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            # Style preset badge
            badge_text = style_preset.replace("_", " ").upper()
            cv2.rectangle(img, (50, 130), (50 + len(badge_text) * 14 + 30, 168), (60, 40, 30), -1)
            cv2.putText(
                img,
                badge_text,
                (65, 156),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (200, 220, 240),
                1,
                cv2.LINE_AA,
            )

            # Main Title
            cv2.putText(
                img,
                "VISUAL HOOK CARD",
                (50, height // 2 - 90),
                cv2.FONT_HERSHEY_DUPLEX,
                1.0,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )

            # Multi-line Prompt Text Wrapping
            clean_p = prompt.strip().replace("\n", " ")
            words = clean_p.split(" ")
            lines = []
            curr_line = []
            max_chars = max(24, width // 28)
            for w in words:
                curr_line.append(w)
                if len(" ".join(curr_line)) > max_chars:
                    lines.append(" ".join(curr_line))
                    curr_line = []
                    if len(lines) >= 5:
                        break
            if curr_line and len(lines) < 5:
                lines.append(" ".join(curr_line))

            y_text = height // 2 - 30
            for line in lines:
                cv2.putText(
                    img,
                    line,
                    (50, y_text),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (180, 190, 205),
                    2,
                    cv2.LINE_AA,
                )
                y_text += 36

            # Bottom info bar
            footer = f"Cloudflare Workers AI (Free) | {width}x{height} | 4 Steps"
            cv2.putText(
                img,
                footer,
                (50, height - 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (100, 115, 130),
                1,
                cv2.LINE_AA,
            )

            cv2.imwrite(output_path, img)

        except Exception as e:
            logger.warning(f"OpenCV card render failed: {e}. Writing minimal PNG.")
            # Minimal 1x1 PNG fallback if cv2 failed
            minimal_png = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
                b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            with open(output_path, "wb") as f:
                f.write(minimal_png)

        with open(output_path, "rb") as f:
            file_bytes = f.read()

        b64_output = base64.b64encode(file_bytes).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64_output}"

        return FluxGenerationResult(
            success=True,
            prompt=prompt,
            styled_prompt=styled_prompt,
            style_preset=style_preset,
            file_path=output_path,
            image_base64=data_uri,
            width=width,
            height=height,
            steps=steps,
            latency_ms=latency_ms,
            is_fallback=True,
        )

    def create_broll_clip(
        self,
        image_path: str,
        duration: float = 3.5,
        motion: str = "zoom_in",
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Transforms a static FLUX.1 visual into a 9:16 (1080x1920) smooth video clip
        with cinematic Ken Burns motion (zoom-in or pan) for seamless short B-roll overlays.
        """
        if not os.path.exists(image_path):
            logger.error(f"Image not found at {image_path}")
            return None

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            logger.warning("FFmpeg not available to render B-roll video clip.")
            return None

        if not output_path:
            base, _ = os.path.splitext(image_path)
            output_path = f"{base}_broll.mp4"

        fps = 30
        total_frames = int(duration * fps)

        # Aspect ratio preservation: scale and center-crop to 9:16 before applying Ken Burns motion
        pre_scale = "scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"

        # Build zoompan filter based on motion type
        if motion == "zoom_in":
            vf = (
                f"{pre_scale}zoompan=z='min(zoom+0.0012,1.20)':d={total_frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
                f"format=yuv420p"
            )
        elif motion == "zoom_out":
            vf = (
                f"{pre_scale}zoompan=z='if(lte(zoom,1.0),1.20,max(1.0,zoom-0.0012))':d={total_frames}:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
                f"format=yuv420p"
            )
        else:  # subtle pan
            vf = (
                f"{pre_scale}zoompan=z=1.10:d={total_frames}:"
                f"x='if(lte(on,1),(iw-iw/zoom)/2,x+0.5)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps},"
                f"format=yuv420p"
            )

        cmd = [
            ffmpeg_bin,
            "-y",
            "-loop", "1",
            "-i", image_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)
            if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"Generated Ken Burns B-roll video clip: {output_path} ({os.path.getsize(output_path)} bytes)")
                return output_path
            else:
                logger.warning(f"FFmpeg Ken Burns failed: {res.stderr[:200]}")
                return None
        except Exception as e:
            logger.warning(f"Failed to create B-roll video clip: {e}")
            return None

    @staticmethod
    def extract_broll_concepts(transcript_text: str, max_concepts: int = 3) -> List[Dict[str, str]]:
        """
        Analyzes dialogue transcript to extract vivid visual concepts suitable for
        Cloudflare FLUX.1 image generation.
        """
        if not transcript_text:
            return [
                {
                    "concept": "Dramatic Studio Lighting",
                    "prompt": "Professional dark studio with warm directional rim lighting and dynamic shadows",
                    "style": "cinematic_hook",
                }
            ]

        sentences = re.split(r"[.!?]+", transcript_text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 15]

        concepts = []
        # Target action-oriented, metaphorical, or descriptive phrases
        keywords_map = {
            "money": "Stack of gold bullion bars and digital currency holograms floating in dark space",
            "future": "Futuristic skyline of a sustainable neon city bathed in golden twilight",
            "build": "Architectural blueprints illuminated with cyan neon wireframe structures",
            "ai": "Glowing neural network synapsing in deep indigo space with quantum light particles",
            "code": "Sleek dark minimalist workspace with ultrawide monitors displaying clean code",
            "podcast": "Broadcast studio microphone in focus with dramatic bokeh lights in background",
            "growth": "Dramatic geometric graph climbing exponentially against dark textured slate",
            "focus": "Macro close-up of a human eye with digital reflections of data points",
        }

        matched = set()
        for s in sentences:
            s_lower = s.lower()
            for kw, prompt_desc in keywords_map.items():
                if kw in s_lower and kw not in matched:
                    concepts.append({
                        "concept": f"{kw.capitalize()} Visual Hook",
                        "prompt": prompt_desc,
                        "style": "cinematic_hook",
                    })
                    matched.add(kw)
                    if len(concepts) >= max_concepts:
                        break
            if len(concepts) >= max_concepts:
                break

        if not concepts:
            # Fallback to key sentence
            key_sentence = sentences[0] if sentences else transcript_text[:80]
            concepts.append({
                "concept": "Main Topic Hook",
                "prompt": f"Striking cinematic visual illustrating: {key_sentence}",
                "style": "cinematic_hook",
            })

        return concepts
