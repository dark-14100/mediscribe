"""Backblaze B2 audio storage.

The B2 Python SDK (``b2sdk``) is fully synchronous, so we wrap blocking calls
in ``asyncio.to_thread`` to stay non-blocking inside FastAPI handlers.

Design:
* ``B2Storage`` is the real client (lazy SDK init — won't fail at import time
  if B2 credentials aren't configured).
* ``InMemoryStorage`` is a test fake — stores blobs in a dict.
* ``get_storage()`` is the FastAPI dependency; tests override it.

Audio object keys follow the format ``audio/{visit_id}.{ext}``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Protocol
from uuid import UUID

from core.config import settings

log = logging.getLogger("medscribe.storage")


def audio_object_name(visit_id: UUID | str, ext: str = "webm") -> str:
    return f"audio/{visit_id}.{ext}"


class StorageClient(Protocol):
    async def upload_audio(
        self, audio_bytes: bytes, visit_id: UUID | str, content_type: str = "audio/webm"
    ) -> str: ...


class B2Storage:
    """Real Backblaze B2 client. SDK is sync; calls are dispatched to a thread."""

    def __init__(
        self,
        key_id: str,
        app_key: str,
        bucket_name: str,
    ) -> None:
        if not (key_id and app_key and bucket_name):
            raise ValueError(
                "B2Storage requires BACKBLAZE_KEY_ID, BACKBLAZE_APP_KEY, "
                "and BACKBLAZE_BUCKET to be set."
            )
        # Defer SDK import so test environments without b2sdk don't fail at module load.
        from b2sdk.v2 import B2Api, InMemoryAccountInfo

        self._info = InMemoryAccountInfo()
        self._api = B2Api(self._info)
        self._api.authorize_account("production", key_id, app_key)
        self._bucket = self._api.get_bucket_by_name(bucket_name)

    def _upload_sync(
        self, audio_bytes: bytes, object_name: str, content_type: str
    ) -> str:
        file_info = self._bucket.upload_bytes(
            data_bytes=audio_bytes,
            file_name=object_name,
            content_type=content_type,
        )
        return self._api.get_download_url_for_fileid(file_info.id_)

    async def upload_audio(
        self,
        audio_bytes: bytes,
        visit_id: UUID | str,
        content_type: str = "audio/webm",
    ) -> str:
        ext = "webm" if "webm" in content_type else content_type.split("/")[-1]
        object_name = audio_object_name(visit_id, ext)
        log.info(
            "[storage] uploading audio object_name=%s bytes=%d",
            object_name,
            len(audio_bytes),
        )
        return await asyncio.to_thread(
            self._upload_sync, audio_bytes, object_name, content_type
        )


class InMemoryStorage:
    """Test fake — stores blobs in a dict, returns a fake URL."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def upload_audio(
        self,
        audio_bytes: bytes,
        visit_id: UUID | str,
        content_type: str = "audio/webm",
    ) -> str:
        ext = "webm" if "webm" in content_type else content_type.split("/")[-1]
        name = audio_object_name(visit_id, ext)
        self.blobs[name] = audio_bytes
        return f"https://fake-b2.local/{name}"


_storage: StorageClient | None = None


def get_storage() -> StorageClient:
    """FastAPI dependency. Lazily initialised singleton."""
    global _storage
    if _storage is None:
        try:
            _storage = B2Storage(
                key_id=settings.BACKBLAZE_KEY_ID,
                app_key=settings.BACKBLAZE_APP_KEY,
                bucket_name=settings.BACKBLAZE_BUCKET,
            )
            log.info("[storage] B2Storage initialised bucket=%s", settings.BACKBLAZE_BUCKET)
        except Exception as exc:  # noqa: BLE001
            # In production, refuse to silently fall back to non-persistent
            # in-memory storage — that would drop patient audio while looking
            # healthy. Fail closed so the misconfiguration is visible.
            if settings.is_production:
                log.error("[storage] B2 misconfigured in production: %s", exc)
                raise
            log.warning(
                "[storage] B2 credentials missing or auth failed (%s); "
                "falling back to in-memory storage. Audio URLs will not be persistent.",
                exc,
            )
            _storage = InMemoryStorage()
    return _storage
