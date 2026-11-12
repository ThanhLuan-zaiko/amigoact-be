"""Every route that changes data says what it sends live. See src/realtime/coverage.py."""

from src.app import app
from src.realtime.coverage import ROUTES

MUTATING = {"post", "put", "patch", "delete"}
PREFIXES = ("emits:", "none:", "pending:")


def _mutating_routes() -> set[tuple[str, str]]:
    paths = app.openapi()["paths"]
    return {
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if method in MUTATING
    }


def test_every_mutating_route_is_listed() -> None:
    missing = sorted(_mutating_routes() - set(ROUTES))
    assert missing == [], f"Add these to src/realtime/coverage.py: {missing}"


def test_no_listed_route_is_stale() -> None:
    stale = sorted(set(ROUTES) - _mutating_routes())
    assert stale == [], f"Remove these from src/realtime/coverage.py: {stale}"


def test_every_entry_says_what_it_does() -> None:
    for route, value in ROUTES.items():
        assert value.startswith(PREFIXES), route
        assert len(value.split(":", 1)[1].strip()) > 5, route
