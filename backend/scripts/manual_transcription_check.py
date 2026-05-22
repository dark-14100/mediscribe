"""Manual smoke check for services.transcription against the real Groq API.

This is NOT a pytest test — it is a developer convenience script that hits the
real Groq endpoint and prints the diarised transcript. It lives in
``backend/scripts/`` (outside ``backend/tests/``) so pytest never collects it
and never burns Groq credits during the test suite.

Run it from the repo root with a populated ``GROQ_API_KEY`` in your environment:

    python backend/scripts/manual_transcription_check.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Make backend/ importable when running from the repo root.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_ROOT))

from services.transcription import transcribe_audio  # noqa: E402


class FakeFile:
    """Minimal stand-in for ``fastapi.UploadFile`` used by transcribe_audio."""

    def __init__(self, path: str | Path) -> None:
        with open(path, "rb") as f:
            self.content = f.read()
        self.filename = "test.wav"
        self.content_type = "audio/wav"

    async def read(self) -> bytes:
        return self.content


async def main() -> None:
    audio_path = Path(__file__).resolve().parent / "test_audio.wav"
    print(f"Loading {audio_path}...")
    fake = FakeFile(audio_path)
    print("Calling transcribe_audio (will hit Groq)...")
    result = await transcribe_audio(fake)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
