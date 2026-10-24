"""Edge guard: the second defensive wall behind the CDN (Cloudflare).

Three cheap checks run before any route work:

- a bounded in-flight slot pool sheds excess concurrency with 503, so a
  thundering herd can never occupy the app or the database at once;
- a per-IP fixed-window counter in ScyllaDB (`auth_rate_limits`, bucket
  `edge:<ip>`) rate-limits floods with 429;
- a hot-IP suppression map short-circuits IPs already proven over the
  limit, so a flood stops paying counter round-trips for the rest of
  the window.

The suppression map is derived, non-authoritative state: the ScyllaDB
counter stays the source of truth. Losing an
entry on restart only costs one extra counter read per IP - request
correctness never depends on process memory. Slot waiting uses plain
ints plus per-request `asyncio.Event` objects, so nothing in this class
is bound to a specific event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger("amigoact.guard")

# Cheap endpoints that must keep answering during an incident: liveness
# probes and API docs stay reachable even while floods are being shed.
DEFAULT_EXEMPT_PATHS = frozenset(
    {
        "/health",
        "/ready",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/docs/oauth2-redirect",
    }
)

_SUPPRESSION_CAP = 10_000

# counter(bucket, window_seconds) -> new hit count; the production
# implementation is CqlRateLimiter.hit against auth_rate_limits.
HitCounter = Callable[[str, int], int]


@dataclass(frozen=True)
class GuardPolicy:
    """Immutable edge-guard knobs derived from Settings per request."""

    enabled: bool = True
    max_concurrent: int = 256
    queue_ms: int = 250
    ip_max_hits: int = 300
    ip_window_seconds: int = 60
    max_body_bytes: int = 128 * 1024 * 1024
    client_ip_header: str = "cf-connecting-ip"
    exempt_paths: frozenset[str] = field(
        default_factory=lambda: DEFAULT_EXEMPT_PATHS
    )

    @classmethod
    def from_settings(cls, settings) -> GuardPolicy:
        """Translate env-backed Settings into an immutable policy."""
        return cls(
            enabled=settings.guard_enabled,
            max_concurrent=settings.guard_max_concurrent,
            queue_ms=settings.guard_queue_ms,
            ip_max_hits=settings.guard_ip_max_hits,
            ip_window_seconds=settings.guard_ip_window_seconds,
            max_body_bytes=settings.guard_max_body_mb * 1024 * 1024,
            client_ip_header=settings.guard_client_ip_header.strip().lower(),
            exempt_paths=DEFAULT_EXEMPT_PATHS
            | settings.guard_exempt_paths_set,
        )


class EdgeGuard:
    """In-flight slot pool plus hot-IP suppression around a DB counter."""

    def __init__(self, policy: GuardPolicy, counter: HitCounter) -> None:
        self._policy = policy
        self._counter = counter
        self._in_flight = 0
        self._waiters: list[asyncio.Event] = []
        self._suppressed: dict[str, float] = {}

    @property
    def policy(self) -> GuardPolicy:
        return self._policy

    def is_exempt(self, path: str) -> bool:
        """Probe/doc paths bypass every check by definition."""
        return path in self._policy.exempt_paths

    def body_allowed(self, headers: dict[str, str]) -> bool:
        """Reject oversized bodies early via Content-Length (cheap)."""
        limit = self._policy.max_body_bytes
        if limit <= 0:
            return True
        try:
            return int(headers.get("content-length", "")) <= limit
        except (TypeError, ValueError):
            # Missing or chunked length: downstream parsers still enforce.
            return True

    def client_ip(self, headers: dict[str, str], peer: str | None) -> str:
        """Resolve the client IP through the configured edge header.

        Only trustworthy when the origin is locked to the edge proxy;
        otherwise set GUARD_CLIENT_IP_HEADER empty to use the TCP peer.
        """
        header = self._policy.client_ip_header
        if header:
            ip = headers.get(header, "").split(",", 1)[0].strip()
            if ip:
                return ip
        return peer or "unknown"

    def suppressed_retry(self, ip: str) -> float:
        """Seconds until this IP may retry; 0 when not suppressed."""
        until = self._suppressed.get(ip)
        if until is None:
            return 0.0
        remaining = until - time.monotonic()
        if remaining <= 0:
            self._suppressed.pop(ip, None)
            return 0.0
        return remaining

    async def acquire_slot(self) -> bool:
        """Take an in-flight slot, queueing up to queue_ms; False sheds."""
        limit = self._policy.max_concurrent
        if limit <= 0:
            return True
        deadline = time.monotonic() + self._policy.queue_ms / 1000
        while True:
            if self._in_flight < limit:
                self._in_flight += 1
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            waiter = asyncio.Event()
            self._waiters.append(waiter)
            try:
                await asyncio.wait_for(waiter.wait(), remaining)
            except TimeoutError:
                return False
            finally:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)

    def release_slot(self) -> None:
        """Free one in-flight slot and wake the oldest queued request."""
        if self._policy.max_concurrent <= 0:
            return
        self._in_flight = max(0, self._in_flight - 1)
        if self._waiters:
            self._waiters[0].set()

    async def check_ip(self, ip: str) -> float:
        """Count one request for this IP; retry seconds when over, else 0.

        Best-effort like every other limiter here: a counter failure
        fails open so the wall never turns into the outage it prevents.
        """
        limit = self._policy.ip_max_hits
        if limit <= 0:
            return 0.0
        try:
            hits = await asyncio.to_thread(
                self._counter, f"edge:{ip}", self._policy.ip_window_seconds
            )
        except Exception as exc:
            logger.warning("edge guard counter unavailable: %s", exc)
            return 0.0
        if hits <= limit:
            return 0.0
        return self._suppress(ip)

    def _suppress(self, ip: str) -> float:
        """Short-circuit this IP until the fixed window rolls over."""
        window = self._policy.ip_window_seconds
        retry = max(1, window - (int(time.time()) % window))
        if len(self._suppressed) >= _SUPPRESSION_CAP:
            now = time.monotonic()
            stale = [k for k, v in self._suppressed.items() if v <= now]
            for key in stale:
                self._suppressed.pop(key, None)
        if len(self._suppressed) < _SUPPRESSION_CAP:
            self._suppressed[ip] = time.monotonic() + retry
        return float(retry)
