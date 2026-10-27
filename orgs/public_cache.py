"""Short-lived cache for the public org directory (N+1 read per org)."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar
from uuid import UUID

from core.cql import TtlCache
from orgs.model import Organization

R = TypeVar("R")

# Public directory = one read per listed org; cache it briefly. Every org
# write in this process clears it, other workers converge within the TTL.
PUBLIC_ORGS_CACHE: TtlCache[list[Organization]] = TtlCache(ttl_seconds=10.0)


def invalidates_public(method: Callable[..., R]) -> Callable[..., R]:
    """Clear the directory cache before and after an org write."""

    @wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> R:
        PUBLIC_ORGS_CACHE.clear()
        try:
            return method(*args, **kwargs)
        finally:
            PUBLIC_ORGS_CACHE.clear()

    return wrapper


def owns(row: object | None, org_id: UUID) -> bool:
    """True when an index row exists and points at this org."""
    return row is not None and getattr(row, "org_id", None) == org_id
