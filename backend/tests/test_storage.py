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
    key = await storage.upload_audio(b"hello-world-bytes", "abc-123")
    # upload_audio returns the durable object key (not a fetchable URL).
    assert key == "audio/abc-123.webm"
    assert storage.blobs["audio/abc-123.webm"] == b"hello-world-bytes"


@pytest.mark.asyncio
async def test_in_memory_storage_uses_content_type_extension():
    storage = InMemoryStorage()
    key = await storage.upload_audio(b"x", "vid-1", content_type="audio/mp3")
    assert key.endswith(".mp3")


@pytest.mark.asyncio
async def test_signed_download_url_includes_key_and_ttl():
    storage = InMemoryStorage()
    key = await storage.upload_audio(b"x", "vid-1")
    url = await storage.signed_download_url(key, expires_in=300)
    assert key in url
    assert "expires_in=300" in url


def test_audio_object_name_default_extension():
    assert audio_object_name("v1") == "audio/v1.webm"
    assert audio_object_name("v1", "mp3") == "audio/v1.mp3"
