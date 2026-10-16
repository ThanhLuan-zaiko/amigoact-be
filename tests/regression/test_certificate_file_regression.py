"""Regression: freeze the certificate PDF download contract.

Locks GET /certificates/{id}/file: PDF bytes, attachment filename
certificate-<serial>.pdf, nosniff, and the 401/403/404 envelope.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.regression.test_hours_regression import (
    _attended,
    _headers,
    _token,
)


async def _issue(
    client: AsyncClient, owner: dict, aid: str, student_id: str
) -> dict:
    issued = await client.post(
        f"/activities/{aid}/certificates/{student_id}", headers=owner
    )
    assert issued.status_code == 201, issued.text
    return issued.json()


async def test_certificate_file_contract(client: AsyncClient) -> None:
    owner, student, _org_id, aid, student_id = await _attended(
        client, "cfshape"
    )
    cert = await _issue(client, owner, aid, student_id)

    response = await client.get(
        f"/certificates/{cert['certificate_id']}/file", headers=student
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert (
        response.headers["content-disposition"]
        == f'attachment; filename="certificate-{cert["serial_no"]}.pdf"'
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content[:5] == b"%PDF-"
    assert len(response.content) > 1000


async def test_certificate_file_error_contract(
    client: AsyncClient,
) -> None:
    owner, student, _org_id, aid, student_id = await _attended(
        client, "cferr"
    )
    cert = await _issue(client, owner, aid, student_id)
    url = f"/certificates/{cert['certificate_id']}/file"

    assert (await client.get(url)).status_code == 401

    outsider = _headers(
        await _token(client, "x.cferr@example.com", "0903400099")
    )
    denied = await client.get(url, headers=outsider)
    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"

    missing = await client.get(
        "/certificates/00000000-0000-7000-8000-000000000000/file",
        headers=student,
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
