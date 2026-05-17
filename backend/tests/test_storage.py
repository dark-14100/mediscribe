"""Tests for services.storage.

We don't exercise the real B2Storage (would require live credentials).
We test the InMemoryStorage fake's contract — the real client must adhere
to the same protocol, so route-level tests can substitute the fake safely.
"""
import pytest

from services.storage import InMemoryStorage, audio_object_name


@pytest.mark.asyncio
async def test_in_memory_storage_round_trip():
    storage = InMemoryStorage()
    url = await storage.upload_audio(b"hello-world-bytes", "abc-123")
    assert url == "https://fake-b2.local/audio/abc-123.webm"
    assert storage.blobs["audio/abc-123.webm"] == b"hello-world-bytes"


@pytest.mark.asyncio
async def test_in_memory_storage_uses_content_type_extension():
    storage = InMemoryStorage()
    url = await storage.upload_audio(b"x", "vid-1", content_type="audio/mp3")
    assert url.endswith(".mp3")


def test_audio_object_name_default_extension():
    assert audio_object_name("v1") == "audio/v1.webm"
    assert audio_object_name("v1", "mp3") == "audio/v1.mp3"
