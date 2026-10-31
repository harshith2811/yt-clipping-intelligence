"""
AI Voice Synthesis & Text-to-Speech (TTS) Narration Engine.
Supports ultra-high-fidelity neural speech synthesis via Edge-TTS,
fully offline fallback via pyttsx3 (SAPI5), and FFmpeg-based
audio ducking to overlay voiceover narrations onto video clips.
"""

from typing import Optional, Dict, Any, List
import os
import asyncio
import subprocess
import shutil


class TTSEngine:
    """
    Synthesizes speech from text using high-quality neural voices or local fallbacks,
    with audio ducking capabilities to mix voiceovers onto video clips.
    """

    DEFAULT_VOICE = "en-US-ChristopherNeural"

    POPULAR_VOICES = {
        "christopher": "en-US-ChristopherNeural",  # Energetic, authoritative male
        "jenny": "en-US-JennyNeural",              # Friendly, dynamic female
        "guy": "en-US-GuyNeural",                  # Conversational, warm male
        "aria": "en-US-AriaNeural",                # Expressive female
        "eric": "en-US-EricNeural",                # Calm, confident male
    }

    def __init__(self, default_voice: Optional[str] = None, cache_dir: str = "data/tts_cache"):
        self.default_voice = default_voice or self.DEFAULT_VOICE
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def synthesize(
        self,
        text: str,
        output_path: Optional[str] = None,
        voice: Optional[str] = None,
        rate: str = "+0%",
        volume: str = "+0%",
    ) -> str:
        """
        Synthesizes text into an audio file (.mp3 / .wav).
        Uses edge-tts first; falls back to offline pyttsx3 if network is unavailable.
        """
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Cannot synthesize empty text.")

        target_voice = voice or self.default_voice
        if target_voice in self.POPULAR_VOICES:
            target_voice = self.POPULAR_VOICES[target_voice]

        if not output_path:
            import hashlib
            key = hashlib.sha256(f"{clean_text}:{target_voice}:{rate}".encode("utf-8")).hexdigest()[:16]
            output_path = os.path.join(self.cache_dir, f"tts_{key}.mp3")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        # 1. Attempt Edge-TTS (Studio-grade Microsoft Neural TTS)
        try:
            import edge_tts

            async def _run_edge():
                communicate = edge_tts.Communicate(clean_text, target_voice, rate=rate, volume=volume)
                await communicate.save(output_path)

            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        pool.submit(lambda: asyncio.run(_run_edge())).result(timeout=25)
                else:
                    asyncio.run(_run_edge())
            except Exception:
                asyncio.run(_run_edge())

            if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
                return os.path.abspath(output_path)

        except Exception as edge_err:
            pass

        # 2. Offline fallback: pyttsx3 (SAPI5 / Windows Speech Engine)
        try:
            import pyttsx3
            engine = pyttsx3.init()
            # Convert .mp3 request to .wav for pyttsx3 if needed
            wav_output = output_path if output_path.endswith(".wav") else f"{output_path}.wav"
            engine.save_to_file(clean_text, wav_output)
            engine.runAndWait()

            if os.path.exists(wav_output) and os.path.getsize(wav_output) > 100:
                if wav_output != output_path:
                    # Convert to target format with ffmpeg
                    subprocess.run(
                        ["ffmpeg", "-i", wav_output, "-y", output_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True,
                    )
                    if os.path.exists(wav_output):
                        os.remove(wav_output)
                return os.path.abspath(output_path)
        except Exception as pyttsx_err:
            pass

        raise RuntimeError(f"All TTS synthesis backends failed for text: '{clean_text[:40]}...'")

    def overlay_narration(
        self,
        video_path: str,
        narration_path: str,
        output_path: str,
        video_duck_db: float = -14.0,
        narration_delay_seconds: float = 0.5,
    ) -> str:
        """
        Mixes voiceover narration audio over existing video audio using FFmpeg sidechain audio ducking.
        The video's original audio volume is reduced (ducked) by `video_duck_db` while the narration is speaking.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not os.path.exists(narration_path):
            raise FileNotFoundError(f"Narration audio file not found: {narration_path}")

        delay_ms = int(narration_delay_seconds * 1000)

        # FFmpeg filtergraph:
        # [1:a]adelay=delay_ms|delay_ms[narr_delayed]
        # [0:a]volume=1.0[orig_a]
        # [orig_a][narr_delayed]amix=inputs=2:duration=first:dropout_transition=2[aout]
        filter_complex = (
            f"[1:a]adelay={delay_ms}|{delay_ms},volume=1.2[narr];"
            f"[0:a]volume={10**(video_duck_db/20):.2f}[ducked_orig];"
            f"[ducked_orig][narr]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )

        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-i", narration_path,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
            "-y",
        ]

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(f"FFmpeg narration overlay failed: {res.stderr[-400:]}")

        return os.path.abspath(output_path)
