from __future__ import annotations

import json
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
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"
GROQ_LLM_MODEL = "llama-3.3-70b-versatile"

SPEAKERS = ("doctor", "patient")

# ---------------------------------------------------------------------------
# Fallback heuristic — question-mark only
# ---------------------------------------------------------------------------

def _assign_speaker_fallback(text: str, index: int) -> str:
    """
    Minimal fallback heuristic used only when LLaMA diarization fails.
    Lines ending with '?' are labelled doctor; everything else alternates.
    """
    if text.strip().endswith("?"):
        return "doctor"
    return SPEAKERS[index % 2]


# ---------------------------------------------------------------------------
# LLaMA diarization layer
# ---------------------------------------------------------------------------

_DIARIZE_SYSTEM_PROMPT = """You are a medical transcription assistant. 
You will be given a list of speech segments from a doctor-patient consultation, each with an index.
Your job is to label each segment as either "doctor" or "patient".

Rules:
- The conversation is strictly between one doctor and one patient.
- Only use the labels "doctor" or "patient" — no other values.
- Return ONLY a JSON object in this exact shape, with no explanation or extra text:
  {"labels": ["doctor", "patient", "doctor", ...]}
- The "labels" array must have exactly the same number of entries as the input segments, in the same order."""


def _build_diarize_user_message(segments: list[str]) -> str:
    numbered = "\n".join(f"{i}: {text}" for i, text in enumerate(segments))
    return f"Label each segment as doctor or patient:\n\n{numbered}"


async def _diarize_with_llama(
    texts: list[str],
) -> list[str] | None:
    """
    Calls LLaMA to assign speaker labels to a list of transcript texts.
    Returns a list of 'doctor'/'patient' strings in the same order,
    or None if the call fails or returns unusable output.
    """
    user_message = _build_diarize_user_message(texts)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GROQ_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": GROQ_LLM_MODEL,
                    "temperature": 0.1,
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": _DIARIZE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                },
                timeout=30.0,
            )

        if response.status_code != 200:
            logger.warning(
                "[TRANSCRIPTION] LLaMA diarization API error %s: %s",
                response.status_code,
                response.text,
            )
            return None

        payload = response.json()
        raw_content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(raw_content)
        labels: list[str] = parsed.get("labels", [])

        # Validate — must be same length and only valid speaker values
        valid = {"doctor", "patient"}
        if len(labels) != len(texts) or not all(l in valid for l in labels):
            logger.warning(
                "[TRANSCRIPTION] LLaMA diarization returned unexpected labels: %s",
                labels,
            )
            return None

        logger.info("[TRANSCRIPTION] LLaMA diarization succeeded")
        return labels

    except Exception:
        logger.warning(
            "[TRANSCRIPTION] LLaMA diarization failed, will use fallback",
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Transcript formatting
# ---------------------------------------------------------------------------

async def _format_transcript(segments: list[dict]) -> list[dict[str, str | int]]:
    """
    Converts raw Whisper segments into a diarized transcript.
    Tries LLaMA speaker labelling first; falls back to question-mark heuristic.
    """
    # Filter empty segments first
    texts: list[str] = []
    for segment in segments:
        text = (segment.get("text") or "").strip()
        if text:
            texts.append(text)

    if not texts:
        return []

    # Attempt LLaMA diarization
    labels = await _diarize_with_llama(texts)

    if labels is None:
        # Fallback — question-mark heuristic
        logger.info("[TRANSCRIPTION] Using question-mark fallback for diarization")
        labels = [_assign_speaker_fallback(text, i) for i, text in enumerate(texts)]

    transcript: list[dict[str, str | int]] = []
    for i, (text, speaker) in enumerate(zip(texts, labels)):
        transcript.append(
            {
                "speaker": speaker,
                "text": text,
                "line_index": i + 1,
            }
        )

    return transcript


# ---------------------------------------------------------------------------
# Groq Whisper call
# ---------------------------------------------------------------------------

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
                        "model": GROQ_WHISPER_MODEL,
                        "response_format": "verbose_json",
                    },
                    timeout=120.0,
                )

        if response.status_code != 200:
            logger.error(
                "[TRANSCRIPTION] Groq Whisper API error %s: %s",
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

        transcript = await _format_transcript(segments)
        if not transcript:
            raise ValueError("No non-empty transcription segments")
        return transcript

    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

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