"""Regression: the {code, message} envelope is the only error contract.

Before this change pydantic 422s leaked FastAPI's {"detail": [...]}
shape and unknown routes returned {"detail": "Not Found"} - clients had
to parse two different error bodies. Freeze the single envelope here.
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_validation_error_contract(client: AsyncClient) -> None:
    """422 carries exactly {code: VALIDATION_ERROR, message: str}."""
    response = await client.get("/orgs?sort=bogus")
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "VALIDATION_ERROR"
    assert "detail" not in body


async def test_unknown_route_contract(client: AsyncClient) -> None:
    """404 for an unmapped path stays inside the same envelope."""
    response = await client.get("/nope/still-nope")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "NOT_FOUND"
    assert "detail" not in body
