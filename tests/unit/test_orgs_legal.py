"""Unit tests for OrgService legal-identity edits and their audit rows."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from core.exceptions import InvalidBusinessProfileError
from orgs.interfaces import OrgLegalEdit
from orgs.service import OrgService, OrgSnapshot
from tests.unit.org_fakes import FakeOrgs, new_owner


def _business_org(service: OrgService, owner: UUID) -> OrgSnapshot:
    return service.create_org(
        owner,
        "Biz A",
        "biz-a",
        "",
        "business",
        tax_code="0312345678",
        legal_rep_name="Nguyen A",
        legal_rep_id="111111111112",
    )


def test_update_org_edits_business_legal_identity() -> None:
    service = OrgService(FakeOrgs())
    owner = new_owner()
    org = _business_org(service, owner)
    updated = service.update_org(
        org.id,
        owner,
        "Biz A",
        "",
        legal=OrgLegalEdit(
            tax_code="0987654321",
            legal_rep_position="Giam doc",
            provided=frozenset({"tax_code", "legal_rep_position"}),
        ),
    )
    assert updated.tax_code == "0987654321"
    assert updated.legal_rep_position == "Giam doc"
    # Unsent legal keys keep their old values.
    assert updated.legal_rep_name == "Nguyen A"


def test_update_org_keeps_legal_identity_when_unsent() -> None:
    service = OrgService(FakeOrgs())
    owner = new_owner()
    org = _business_org(service, owner)
    updated = service.update_org(org.id, owner, "Biz Renamed", "desc")
    assert updated.tax_code == "0312345678"
    assert updated.legal_rep_name == "Nguyen A"


def test_update_org_rejects_legal_edits_on_non_business() -> None:
    service = OrgService(FakeOrgs())
    owner = new_owner()
    org = service.create_org(owner, "Club", "club-x", "", "club")
    with pytest.raises(InvalidBusinessProfileError):
        service.update_org(
            org.id,
            owner,
            "Club",
            "",
            legal=OrgLegalEdit(
                tax_code="0312345678", provided=frozenset({"tax_code"})
            ),
        )


def test_update_org_rejects_clearing_required_legal_trio() -> None:
    service = OrgService(FakeOrgs())
    owner = new_owner()
    org = _business_org(service, owner)
    with pytest.raises(InvalidBusinessProfileError):
        service.update_org(
            org.id,
            owner,
            "Biz A",
            "",
            legal=OrgLegalEdit(provided=frozenset({"tax_code"})),
        )


def test_update_org_writes_audit_rows() -> None:
    records: list[tuple] = []
    access = SimpleNamespace(
        record=lambda *args: records.append(args),
        has_permission=lambda *args: False,
    )
    service = OrgService(FakeOrgs(), access=access)
    owner = new_owner()
    org = _business_org(service, owner)
    service.update_org(
        org.id,
        owner,
        "Biz A",
        "",
        legal=OrgLegalEdit(
            tax_code="0987654321", provided=frozenset({"tax_code"})
        ),
    )
    actions = [row[2] for row in records]
    assert "org.update" in actions
    assert "org.legal:tax_code" in actions
    # Legal row carries an old->new JSON diff in its metadata payload.
    legal_meta = records[actions.index("org.legal:tax_code")][6]
    assert json.loads(legal_meta) == {
        "tax_code": {"old": "0312345678", "new": "0987654321"}
    }
