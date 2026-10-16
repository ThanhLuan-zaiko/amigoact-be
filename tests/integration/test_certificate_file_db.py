"""Integration tests: certificate PDF download over HTTP."""

from __future__ import annotations

from httpx import AsyncClient

from tests.integration.test_hours_db import _headers, _setup_attended, _token


async def _issue(
    client: AsyncClient, owner: dict, aid: str, student_id: str
) -> dict:
    issued = await client.post(
        f"/activities/{aid}/certificates/{student_id}", headers=owner
    )
    assert issued.status_code == 201, issued.text
    return issued.json()


async def test_certificate_file_download_and_reuse(
    client: AsyncClient,
) -> None:
    owner, student, org_id, aid, student_id = await _setup_attended(
        client, "cf1"
    )
    cert = await _issue(client, owner, aid, student_id)
    url = f"/certificates/{cert['certificate_id']}/file"

    first = await client.get(url, headers=student)
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "application/pdf"
    disposition = first.headers["content-disposition"]
    assert "attachment" in disposition
    assert f"certificate-{cert['serial_no']}.pdf" in disposition
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.content[:5] == b"%PDF-"

    # Second download serves the stored asset: identical bytes.
    second = await client.get(url, headers=student)
    assert second.status_code == 200
    assert second.content == first.content


async def test_certificate_file_authorization(client: AsyncClient) -> None:
    owner, student, org_id, aid, student_id = await _setup_attended(
        client, "cf2"
    )
    cert = await _issue(client, owner, aid, student_id)
    url = f"/certificates/{cert['certificate_id']}/file"

    managed = await client.get(url, headers=owner)
    assert managed.status_code == 200, managed.text
    assert managed.content[:5] == b"%PDF-"

    outsider = _headers(
        await _token(client, "x.cf2@example.com", "0903300077")
    )
    denied = await client.get(url, headers=outsider)
    assert denied.status_code == 403

    anonymous = await client.get(url)
    assert anonymous.status_code == 401

    missing = await client.get(
        "/certificates/00000000-0000-7000-8000-000000000000/file",
        headers=student,
    )
    assert missing.status_code == 404
