"""Shared WebSocket test helpers: single-loop client and frame draining."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import anyio.from_thread
from fastapi.testclient import TestClient


@contextmanager
def pinned_loop(client: TestClient) -> Iterator[TestClient]:
    """Run every socket of this client on one event loop, like production.

    A bare TestClient starts a private loop per websocket_connect and
    tears it down when that socket closes, killing background work the
    socket scheduled (the offline presence fan-out). Pinning one portal
    keeps it alive. Unlike `with TestClient(...)`, lifespan does not run,
    so the test settings overrides stay in charge.
    """
    with anyio.from_thread.start_blocking_portal(**client.async_backend) as portal:
        client.portal = portal
        try:
            yield client
        finally:
            client.portal = None


def next_presence(sock: Any, channel: str, limit: int = 8) -> dict:
    """Drain frames until a presence event.v1 on the channel arrives.

    Control frames may interleave with event delivery; heartbeat pings
    get a pong like the real client so the socket survives the 4408
    pong-timeout while the test waits.
    """
    skipped: list[dict] = []
    for _ in range(limit):
        frame = sock.receive_json()
        if frame["type"] == "ping.v1":
            sock.send_json({"type": "pong.v1", "data": {}})
            continue
        if frame["type"] != "event.v1":
            skipped.append(frame)
            continue
        payload = frame["data"].get("payload") or {}
        if frame["data"].get("channel") == channel and "presence" in payload:
            return payload
        skipped.append(frame)
    raise AssertionError(f"no presence frame on {channel}; skipped: {skipped}")


def next_frame(sock: Any, frame_type: str, limit: int = 8) -> dict:
    """Drain frames (answering pings) until one of frame_type arrives."""
    skipped: list[dict] = []
    for _ in range(limit):
        frame = sock.receive_json()
        if frame["type"] == "ping.v1":
            sock.send_json({"type": "pong.v1", "data": {}})
            continue
        if frame["type"] == frame_type:
            return frame
        skipped.append(frame)
    raise AssertionError(f"no {frame_type} frame; skipped: {skipped}")
