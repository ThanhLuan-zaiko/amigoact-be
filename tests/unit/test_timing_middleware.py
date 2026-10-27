"""Unit tests for TimingMiddleware, GZip wiring and the public org cache."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.testclient import TestClient

from core.timing_middleware import TimingMiddleware
from orgs.public_cache import PUBLIC_ORGS_CACHE, invalidates_public


def _app(slow_ms: float = 500.0) -> FastAPI:
    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(TimingMiddleware, slow_ms=slow_ms)

    @app.get("/small")
    def small() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/big")
    def big() -> dict[str, str]:
        return {"data": "x" * 5000}

    return app


def test_server_timing_header_present() -> None:
    response = TestClient(_app()).get("/small")
    assert response.status_code == 200
    assert response.headers["server-timing"].startswith("app;dur=")


def test_large_json_is_gzipped_small_is_not() -> None:
    client = TestClient(_app())
    big = client.get("/big", headers={"accept-encoding": "gzip"})
    small = client.get("/small", headers={"accept-encoding": "gzip"})
    assert big.headers.get("content-encoding") == "gzip"
    assert big.json()["data"] == "x" * 5000
    assert "content-encoding" not in small.headers


def test_slow_request_logs_path_without_query(caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.WARNING, logger="amigoact.timing")
    TestClient(_app(slow_ms=0.0)).get("/small?token=secret")
    messages = [record.getMessage() for record in caplog.records]
    assert any("GET /small" in message for message in messages)
    assert all("secret" not in message for message in messages)


def test_org_writes_invalidate_public_cache() -> None:
    PUBLIC_ORGS_CACHE.clear()
    PUBLIC_ORGS_CACHE.get_or_load("ks", lambda: [])

    @invalidates_public
    def write() -> str:
        return "done"

    assert write() == "done"
    marker = object()
    assert PUBLIC_ORGS_CACHE.get_or_load("ks", lambda: [marker]) == [marker]
    PUBLIC_ORGS_CACHE.clear()
