"""Lock in the safe CORS defaults."""

from src.app import app
from src.cors import get_cors_settings
from tests.conftest import ApiContext


def test_cors_never_allows_credentials_or_wildcards(api: ApiContext) -> None:
    """Tokens travel in the Authorization header, never in cookies the browser adds."""
    origins = get_cors_settings().origins
    assert "*" not in origins
    origin = origins[0] if origins else "http://evil.test"
    response = api.client.get("/organizations", headers={"Origin": origin})
    assert "access-control-allow-credentials" not in response.headers
    assert response.headers.get("access-control-allow-origin") != "*"


def test_cors_middleware_is_outside_the_key_check() -> None:
    """CORSMiddleware must wrap InternalKeyMiddleware, so preflights get answered."""
    names = [layer.cls.__name__ for layer in app.user_middleware]  # type: ignore[attr-defined]
    assert names.index("CORSMiddleware") < names.index("InternalKeyMiddleware")
