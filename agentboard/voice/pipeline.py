"""Voice interaction pipeline — STT and TTS for agent interaction.

Priority:
  1. Browser-native Web Speech API (free, offline-capable) — handled in frontend JS
  2. OpenAI Whisper (STT) / OpenAI TTS — server-side fallback

The server-side pipeline is only used when:
  - The browser doesn't support Web Speech API
  - The user explicitly requests server-side processing
  - For async/background voice processing
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from io import BytesIO

import httpx

from agentboard.config import VoiceConfig
from agentboard.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class STTResult:
    text: str
    confidence: float = 1.0
    provider: str = "unknown"
    elapsed_ms: float = 0


@dataclass
class TTSResult:
    audio_base64: str  # base64-encoded audio data
    format: str = "mp3"  # audio format
    provider: str = "unknown"
    elapsed_ms: float = 0


# ---------------------------------------------------------------------------
# Voice Pipeline
# ---------------------------------------------------------------------------


class VoicePipeline:
    """Server-side voice processing pipeline.

    For browser-native voice, see `session_live.js` which uses Web Speech API.
    This pipeline is the server-side fallback.
    """

    def __init__(self, config: VoiceConfig):
        self.config = config

    # ------------------------------------------------------------------
    # STT (Speech to Text)
    # ------------------------------------------------------------------

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        language: str = "zh",
        mime_type: str = "audio/webm",
    ) -> STTResult | None:
        """Transcribe audio to text.

        Args:
            audio_data: Raw audio bytes.
            language: Language code (zh, en, etc.).
            mime_type: MIME type of the audio.

        Returns:
            STTResult or None on failure.
        """
        provider = self.config.stt_provider

        if provider == "openai_whisper":
            return await self._whisper_transcribe(audio_data, language, mime_type)

        logger.warning("Unknown STT provider: %s", provider)
        return None

    async def _whisper_transcribe(
        self,
        audio_data: bytes,
        language: str,
        mime_type: str,
    ) -> STTResult | None:
        """Transcribe using OpenAI Whisper API."""
        import time

        api_key = os.environ.get(self.config.openai_api_key_env, "")
        if not api_key:
            logger.error("No OpenAI API key configured for Whisper")
            return None

        t0 = time.monotonic()

        # Map mime type to file extension
        ext_map = {
            "audio/webm": "webm",
            "audio/wav": "wav",
            "audio/mp3": "mp3",
            "audio/mp4": "mp4",
            "audio/ogg": "ogg",
        }
        ext = ext_map.get(mime_type, "webm")

        try:
            # OpenAI Whisper API expects multipart form data
            files = {
                "file": (f"audio.{ext}", BytesIO(audio_data), mime_type),
            }
            data = {
                "model": "whisper-1",
                "language": language,
                "response_format": "json",
            }
            headers = {"Authorization": f"Bearer {api_key}"}

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    files=files,
                    data=data,
                    headers=headers,
                )
                resp.raise_for_status()
                result = resp.json()

            elapsed = (time.monotonic() - t0) * 1000
            return STTResult(
                text=result.get("text", ""),
                confidence=0.9,
                provider="openai_whisper",
                elapsed_ms=elapsed,
            )
        except Exception as e:
            logger.error("Whisper API error: %s", e)
            return None

    # ------------------------------------------------------------------
    # TTS (Text to Speech)
    # ------------------------------------------------------------------

    async def synthesize(
        self,
        text: str,
        *,
        language: str = "zh",
        voice: str = "alloy",
        speed: float = 1.0,
    ) -> TTSResult | None:
        """Synthesize text to speech.

        Args:
            text: Text to synthesize.
            language: Language code.
            voice: Voice ID (OpenAI: alloy, echo, fable, onyx, nova, shimmer).
            speed: Playback speed (0.25 to 4.0).

        Returns:
            TTSResult with base64 audio, or None on failure.
        """
        provider = self.config.tts_provider

        if provider == "openai_tts":
            return await self._openai_tts(text, voice, speed)

        logger.warning("Unknown TTS provider: %s", provider)
        return None

    async def _openai_tts(
        self,
        text: str,
        voice: str,
        speed: float,
    ) -> TTSResult | None:
        """Synthesize using OpenAI TTS API."""
        import time

        api_key = os.environ.get(self.config.openai_api_key_env, "")
        if not api_key:
            logger.error("No OpenAI API key configured for TTS")
            return None

        t0 = time.monotonic()

        try:
            payload = {
                "model": "tts-1",
                "input": text,
                "voice": voice,
                "speed": speed,
                "response_format": "mp3",
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                audio_bytes = resp.content

            elapsed = (time.monotonic() - t0) * 1000
            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
            return TTSResult(
                audio_base64=audio_b64,
                format="mp3",
                provider="openai_tts",
                elapsed_ms=elapsed,
            )
        except Exception as e:
            logger.error("OpenAI TTS API error: %s", e)
            return None
