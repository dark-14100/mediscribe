from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from core.config import settings

if TYPE_CHECKING:
    from fastapi import UploadFile

logger = logging.getLogger(__name__)

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
SPEAKERS = ("doctor", "patient")


def _format_transcript(segments: list[dict]) -> list[dict[str, str | int]]:
    transcript: list[dict[str, str | int]] = []
    for i, segment in enumerate(segments):
        text = (segment.get("text") or "").strip()
        if not text:
            continue
        transcript.append(
            {
                "speaker": SPEAKERS[i % 2],
                "text": text,
                "line_index": len(transcript) + 1,
            }
        )
    return transcript


async def _call_groq_whisper(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
) -> list[dict[str, str | int]]:
    temp_dir: str | None = None
    try:
        suffix = Path(filename).suffix or ".webm"
        temp_dir = tempfile.mkdtemp()
        temp_path = Path(temp_dir) / f"audio{suffix}"
        temp_path.write_bytes(audio_bytes)

        async with httpx.AsyncClient() as client:
            with temp_path.open("rb") as audio_file:
                response = await client.post(
                    GROQ_TRANSCRIPTION_URL,
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                    files={"file": (filename, audio_file, content_type)},
                    data={
                        "model": GROQ_MODEL,
                        "response_format": "verbose_json",
                    },
                    timeout=120.0,
                )

        if response.status_code != 200:
            logger.error(
                "[TRANSCRIPTION] Groq API error %s: %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()

        payload = response.json()
        segments: list[dict] = payload.get("segments") or []
        if not segments:
            full_text = (payload.get("text") or "").strip()
            if full_text:
                segments = [{"text": full_text}]
            else:
                raise ValueError("Groq returned no transcription segments")

        transcript = _format_transcript(segments)
        if not transcript:
            raise ValueError("No non-empty transcription segments")
        return transcript

    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


async def transcribe(audio_bytes: bytes) -> list[dict[str, str | int]]:
    """Pipeline entry point: diarised transcript lines from raw audio bytes."""
    logger.info("[TRANSCRIPTION] Starting transcription")
    if not audio_bytes:
        raise ValueError("Audio file is empty")
    try:
        transcript = await _call_groq_whisper(audio_bytes)
        logger.info(
            "[TRANSCRIPTION] Transcription successful (%d lines)",
            len(transcript),
        )
        return transcript
    except Exception:
        logger.exception("[TRANSCRIPTION] Transcription failed")
        raise


async def transcribe_audio(file: UploadFile) -> dict:
    contents = await file.read()
    transcript = await _call_groq_whisper(
        contents,
        filename=file.filename or "audio.webm",
        content_type=file.content_type or "audio/webm",
    )
    return {"transcript": transcript}
