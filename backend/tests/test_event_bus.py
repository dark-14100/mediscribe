"""Tests for the in-process EventBus that backs SSE streaming."""
import asyncio

import pytest

from services.event_bus import EventBus


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_noop():
    bus = EventBus()
    # Should not raise.
    await bus.publish("visit-1", "soap_ready", {"x": 1})


@pytest.mark.asyncio
async def test_subscriber_receives_published_events_in_order():
    bus = EventBus()
    received = []

    async def consume():
        async for event in bus.subscribe("visit-1"):
            received.append((event.name, event.data))

    consumer_task = asyncio.create_task(consume())

    # Wait until the subscriber's queue is registered.
    for _ in range(10):
        if bus.subscriber_count("visit-1") == 1:
            break
        await asyncio.sleep(0.01)
    assert bus.subscriber_count("visit-1") == 1

    await bus.publish("visit-1", "soap_ready", {"step": 1})
    await bus.publish("visit-1", "anomalies_ready", {"step": 2})
    await bus.close("visit-1")
    await asyncio.wait_for(consumer_task, timeout=1.0)

    assert received == [
        ("soap_ready", {"step": 1}),
        ("anomalies_ready", {"step": 2}),
    ]
    assert bus.subscriber_count("visit-1") == 0


@pytest.mark.asyncio
async def test_two_subscribers_each_get_a_copy():
    bus = EventBus()

    async def consume() -> list[str]:
        out: list[str] = []
        async for event in bus.subscribe("visit-1"):
            out.append(event.name)
        return out

    t1 = asyncio.create_task(consume())
    t2 = asyncio.create_task(consume())

    for _ in range(20):
        if bus.subscriber_count("visit-1") == 2:
            break
        await asyncio.sleep(0.01)
    assert bus.subscriber_count("visit-1") == 2

    await bus.publish("visit-1", "soap_ready", {})
    await bus.close("visit-1")
    a, b = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)
    assert a == ["soap_ready"]
    assert b == ["soap_ready"]
