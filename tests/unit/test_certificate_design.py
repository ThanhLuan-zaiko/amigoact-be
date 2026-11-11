import uuid
from datetime import UTC, datetime

from src.certificates.template_schemas import CertificateDesign, Layout
from src.certificates.templates import design_of
from src.models.certificates import CertificateTemplate


def template(**fields: object) -> CertificateTemplate:
    values: dict[str, object] = {
        "template_id": uuid.uuid7(),
        "org_id": uuid.uuid7(),
        "name": "Giay khen",
        "background_media_id": None,
        "layout_json": Layout().model_dump(mode="json"),
        "is_active": True,
        "created_at": datetime.now(UTC),
    }
    values.update(fields)
    return CertificateTemplate(**values)


def test_no_template_means_no_design() -> None:
    assert design_of(None) is None


def test_design_links_the_background_and_keeps_the_layout() -> None:
    background = uuid.uuid7()
    layout = Layout.model_validate({"name": {"x": 20, "y": 30, "size": 40}}).model_dump(
        mode="json"
    )

    design = design_of(template(background_media_id=background, layout_json=layout))

    assert design is not None
    assert design.background_url == f"/media/{background}/file"
    assert design.layout.name.x == 20
    assert design.layout.name.size == 40
    assert design.layout.serial == Layout().serial


def test_design_without_background_or_layout_uses_defaults() -> None:
    design = design_of(template(layout_json=None))

    assert design == CertificateDesign(background_url=None, layout=Layout())


def test_inactive_template_still_gives_its_design() -> None:
    assert design_of(template(is_active=False)) is not None


def test_design_holds_nothing_that_names_the_template() -> None:
    design = design_of(template())

    assert design is not None
    assert set(design.model_dump()) == {"background_url", "layout"}
