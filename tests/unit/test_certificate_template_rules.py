import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.certificates.template_schemas import (
    Layout,
    Placement,
    TemplateCreate,
    TemplateUpdate,
)
from src.certificates.templates import to_response
from src.models.certificates import CertificateTemplate


def test_default_layout_places_all_five_texts_in_range() -> None:
    layout = Layout().model_dump()
    assert set(layout) == {"name", "activity", "hours", "date", "serial"}
    for placement in layout.values():
        assert 0 <= placement["x"] <= 100
        assert 0 <= placement["y"] <= 100
        assert 8 <= placement["size"] <= 72


def test_placement_outside_the_page_is_refused() -> None:
    with pytest.raises(ValidationError):
        Placement(x=101, y=10, size=12)
    with pytest.raises(ValidationError):
        Placement(x=10, y=-1, size=12)
    with pytest.raises(ValidationError):
        Placement(x=10, y=10, size=7)


def test_layout_refuses_unknown_texts() -> None:
    with pytest.raises(ValidationError):
        Layout.model_validate({"logo": {"x": 1, "y": 1, "size": 10}})


def test_template_name_is_trimmed_and_limited() -> None:
    payload = TemplateCreate(name="  Giay khen  ")
    assert payload.name == "Giay khen"
    with pytest.raises(ValidationError):
        TemplateCreate(name="a")
    with pytest.raises(ValidationError):
        TemplateCreate(name="a\x00b cd")


def test_update_remembers_which_fields_were_sent() -> None:
    payload = TemplateUpdate.model_validate({"background_asset_id": None})
    assert "background_asset_id" in payload.model_fields_set
    assert "name" not in payload.model_fields_set


def test_response_links_the_background_and_keeps_the_layout() -> None:
    background = uuid.uuid7()
    template = CertificateTemplate(
        template_id=uuid.uuid7(),
        org_id=uuid.uuid7(),
        name="Giay khen",
        background_media_id=background,
        layout_json=Layout().model_dump(mode="json"),
        is_active=True,
        created_at=datetime.now(UTC),
    )
    response = to_response(template)
    assert response.background_url == f"/media/{background}/file"
    assert response.layout == Layout()


def test_response_without_background_has_no_url() -> None:
    template = CertificateTemplate(
        template_id=uuid.uuid7(),
        org_id=uuid.uuid7(),
        name="Trong",
        background_media_id=None,
        layout_json=None,
        is_active=False,
        created_at=datetime.now(UTC),
    )
    response = to_response(template)
    assert response.background_url is None
    assert response.layout == Layout()
