"""Backblaze B2 audio storage.

The B2 Python SDK (``b2sdk``) is fully synchronous, so we wrap blocking calls
in ``asyncio.to_thread`` to stay non-blocking inside FastAPI handlers.

Design:
* ``B2Storage`` is the real client (lazy SDK init — won't fail at import time
  if B2 credentials aren't configured).
* ``InMemoryStorage`` is a test fake — stores blobs in a dict.
* ``get_storage()`` is the FastAPI dependency; tests override it.

Audio object keys follow the format ``audio/{visit_id}.{ext}``.

PHI posture: ``upload_audio`` returns the durable *object key* (not a public
URL), and the bucket is expected to be **private**. Callers persist the key and
mint a short-lived signed URL via ``signed_download_url`` only when a download
is actually needed, so we never store a long-lived, directly-fetchable link to
patient audio.
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
    ) -> str:
        """Upload audio and return its durable object key (not a fetchable URL)."""
        ...

    async def signed_download_url(self, object_key: str, expires_in: int) -> str:
        """Return a time-limited authorized URL for a previously stored object."""
        ...


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

        self._bucket_name = bucket_name
        self._info = InMemoryAccountInfo()
        self._api = B2Api(self._info)
        self._api.authorize_account("production", key_id, app_key)
        self._bucket = self._api.get_bucket_by_name(bucket_name)

    def _upload_sync(
        self, audio_bytes: bytes, object_name: str, content_type: str
    ) -> str:
        self._bucket.upload_bytes(
            data_bytes=audio_bytes,
            file_name=object_name,
            content_type=content_type,
        )
        # Return the object key; downloads use short-lived signed URLs minted on
        # demand (the bucket is private, so a bare URL would not be fetchable).
        return object_name

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

    def _signed_url_sync(self, object_key: str, expires_in: int) -> str:
        token = self._bucket.get_download_authorization(
            file_name_prefix=object_key,
            valid_duration_in_seconds=expires_in,
        )
        base = self._api.get_download_url_for_file_name(self._bucket_name, object_key)
        return f"{base}?Authorization={token}"

    async def signed_download_url(self, object_key: str, expires_in: int) -> str:
        return await asyncio.to_thread(self._signed_url_sync, object_key, expires_in)


class InMemoryStorage:
    """Test fake — stores blobs in a dict, returns the object key."""

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
        return name

    async def signed_download_url(self, object_key: str, expires_in: int) -> str:
        return f"https://fake-b2.local/{object_key}?Authorization=test&expires_in={expires_in}"


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
