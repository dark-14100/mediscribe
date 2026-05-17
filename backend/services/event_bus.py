"""In-process pub/sub for SSE pipeline events.

Lives in the FastAPI process. The pipeline route handler (publisher) and the
SSE stream handler (subscriber) run in the same Uvicorn process, so an
``asyncio.Queue``-backed broker is sufficient — no Redis pub/sub needed.

Architecture:
* Frontend opens SSE: ``GET /pipeline/stream/{visit_id}`` → ``subscribe(visit_id)``.
* Frontend then POSTs ``/pipeline/run`` → publisher emits events as each pipeline
  step completes → ``publish(visit_id, name, data)``.
* The publisher calls ``close(visit_id)`` when the pipeline finishes, which
  drops a sentinel in every queue so subscribers' async iterators exit cleanly.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("medscribe.event_bus")


@dataclass(frozen=True, slots=True)
class Event:
    name: str
    data: dict[str, Any]


_SENTINEL: Event | None = None  # explicit sentinel value used by close()


class EventBus:
    """Per-visit-id queue broker."""

    def __init__(self) -> None:
        # visit_id -> list of subscriber queues
        self._queues: dict[str, list[asyncio.Queue[Event | None]]] = {}

    async def subscribe(self, visit_id: str) -> AsyncIterator[Event]:
        """Yield events for a visit until a close sentinel is received."""
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._queues.setdefault(visit_id, []).append(queue)
        log.debug("[event_bus] subscribed visit_id=%s", visit_id)
        try:
            while True:
                event = await queue.get()
                if event is _SENTINEL:
                    return
                yield event
        finally:
            subs = self._queues.get(visit_id, [])
            if queue in subs:
                subs.remove(queue)
            if not subs:
                self._queues.pop(visit_id, None)
            log.debug("[event_bus] unsubscribed visit_id=%s", visit_id)

    async def publish(self, visit_id: str, name: str, data: dict[str, Any]) -> None:
        subs = self._queues.get(visit_id)
        if not subs:
            log.debug(
                "[event_bus] publish with no subscribers visit_id=%s name=%s",
                visit_id,
                name,
            )
            return
        event = Event(name=name, data=data)
        for queue in subs:
            await queue.put(event)
        log.debug(
            "[event_bus] published visit_id=%s name=%s subscribers=%d",
            visit_id,
            name,
            len(subs),
        )

    async def close(self, visit_id: str) -> None:
        subs = self._queues.get(visit_id, [])
        for queue in subs:
            await queue.put(_SENTINEL)
        log.debug("[event_bus] closed visit_id=%s subscribers=%d", visit_id, len(subs))

    def subscriber_count(self, visit_id: str) -> int:
        return len(self._queues.get(visit_id, []))


# Process-global instance shared across all routes.
_bus = EventBus()


def get_event_bus() -> EventBus:
    """FastAPI dependency for the shared in-process EventBus."""
    return _bus
