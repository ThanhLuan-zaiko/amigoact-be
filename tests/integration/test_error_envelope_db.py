"""Integration: every error response uses the {code, message} envelope."""

from __future__ import annotations

from httpx import AsyncClient


async def test_validation_errors_use_envelope(client: AsyncClient) -> None:
    """Bad query params return VALIDATION_ERROR, not FastAPI's detail list."""
    response = await client.get("/orgs?sort=oldest")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert isinstance(body["message"], str) and body["message"]


async def test_body_validation_uses_envelope(client: AsyncClient) -> None:
    """Pydantic field errors land on the same envelope shape."""
    response = await client.post("/auth/register", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_unknown_route_uses_envelope(client: AsyncClient) -> None:
    """A bare 404 still carries a stable code for clients."""
    response = await client.get("/definitely-not-a-route")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"


async def test_domain_errors_keep_envelope(client: AsyncClient) -> None:
    """Domain errors still flow through domain_error_handler unchanged."""
    response = await client.post(
        "/auth/login", json={"email": "nobody@test.dev", "password": "x"}
    )
    assert response.status_code in (401, 429)
    assert set(response.json()) == {"code", "message"}
