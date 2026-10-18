"""Unit tests for certificate PDF rendering and the download service."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
import uuid_utils
from PIL import Image

from certificates.file_service import CertificateFileService
from certificates.pdf import PillowCertificateRenderer
from core.exceptions import ForbiddenError, NotFoundError
from core.media import LocalMediaStore
from tests.unit.activity_fakes import (
    FakeActivities,
    _fields,
    _org_with_owner,
)
from tests.unit.hour_fakes import FakeCertificates, FakeTemplates
from tests.unit.member_fakes import FakeAccess, FakeUsers
from tests.unit.org_fakes import FakeMedia, FakeOrgs


def _render_kwargs(**overrides):
    base = dict(
        student_name="Nguy\u1ec5n V\u0103n \u0110\u1ee9c",
        org_name="CLB T\u00ecnh nguy\u1ec7n Xanh",
        activity_title="D\u1ecdn s\u1ea1ch b\u00e3i bi\u1ec3n",
        serial_no="AMG-2026-ABCDEF12",
        issued_at=datetime(2026, 10, 16, tzinfo=UTC),
        background=None,
        layout={},
    )
    base.update(overrides)
    return base


def _png_bytes(color: str = "#f59e0b", size: tuple = (400, 300)) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


class CountingRenderer(PillowCertificateRenderer):
    def __init__(self) -> None:
        self.calls = 0

    def render(self, **kwargs) -> bytes:  # noqa: ANN002, ANN003, ANN202
        self.calls += 1
        return super().render(**kwargs)


# Renderer ------------------------------------------------------------------


def test_render_produces_pdf_bytes() -> None:
    pdf = PillowCertificateRenderer().render(**_render_kwargs())
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000


def test_render_with_background_image() -> None:
    pdf = PillowCertificateRenderer().render(
        **_render_kwargs(background=_png_bytes())
    )
    assert pdf.startswith(b"%PDF-")


def test_render_survives_bad_background_and_layout() -> None:
    pdf = PillowCertificateRenderer().render(
        **_render_kwargs(
            background=b"not-an-image",
            layout={"title_y": "NaN", "title": 5, "accent": "zzz"},
        )
    )
    assert pdf.startswith(b"%PDF-")


def test_render_with_layout_overrides() -> None:
    pdf = PillowCertificateRenderer().render(
        **_render_kwargs(
            layout={
                "title": "CH\u1ee8NG NH\u1eacN",
                "title_y": 300,
                "name_y": 600,
                "ink": "#111111",
                "accent": "#0f766e",
            }
        )
    )
    assert pdf.startswith(b"%PDF-")


# File service --------------------------------------------------------------


def _file_service(tmp_path) -> tuple:
    certs = FakeCertificates()
    templates = FakeTemplates()
    activities = FakeActivities()
    orgs = FakeOrgs()
    users = FakeUsers()
    media = FakeMedia()
    store = LocalMediaStore(tmp_path)
    renderer = CountingRenderer()
    access = FakeAccess()
    service = CertificateFileService(
        certificates=certs,
        templates=templates,
        activities=activities,
        orgs=orgs,
        users=users,
        media=media,
        store=store,
        renderer=renderer,
        access=access,
    )
    return (
        service, certs, templates, activities, orgs, users, media,
        store, renderer, access,
    )


def _issued_cert(certs, activities, orgs, owner, student) -> SimpleNamespace:
    org = _org_with_owner(orgs, owner, slug=f"club-{owner.hex[:6]}")
    activity = activities.create(
        org.id, owner, _fields(None), datetime.now(UTC),
    )
    row = certs.issue(
        uuid_utils.uuid7(), activity.id, student, uuid_utils.uuid7(),
        "AMG-2026-TEST01", owner, datetime.now(UTC),
    )
    return row


def test_student_download_generates_and_caches(tmp_path) -> None:
    (
        service, certs, _t, _a, _o, users, media, store, renderer, _ac,
    ) = _file_service(tmp_path)
    owner, student = uuid_utils.uuid7(), uuid_utils.uuid7()
    users.add(student, "s@x.dev", "Sinh Vi\u00ean")
    cert = _issued_cert(certs, _a, _o, owner, student)

    first = service.download(cert.certificate_id, student)
    assert first.filename == f"certificate-{cert.serial_no}.pdf"
    assert first.content.startswith(b"%PDF-")
    assert renderer.calls == 1
    assert cert.file_media_id is not None
    asset = media.get_asset(cert.file_media_id)
    assert asset is not None
    assert asset.mime == "application/pdf"
    assert asset.role == "attachment"
    assert asset.owner_type == "certificate"
    assert store.resolve(asset.file_url).is_file()

    # Second download serves stored bytes; renderer is not re-run.
    second = service.download(cert.certificate_id, student)
    assert second.content == first.content
    assert renderer.calls == 1


def test_manager_can_download(tmp_path) -> None:
    (
        service, certs, _t, _a, _o, _u, _m, _s, _r, access,
    ) = _file_service(tmp_path)
    owner, student, manager = (
        uuid_utils.uuid7(), uuid_utils.uuid7(), uuid_utils.uuid7()
    )
    cert = _issued_cert(certs, _a, _o, owner, student)
    activity = _a.get(cert.activity_id)
    access.perms[(activity.org_id, manager)] = {"activity:manage"}

    blob = service.download(cert.certificate_id, owner)
    assert blob.content.startswith(b"%PDF-")
    blob2 = service.download(cert.certificate_id, manager)
    assert blob2.content == blob.content


def test_outsider_denied_and_audited(tmp_path) -> None:
    (
        service, certs, _t, _a, _o, _u, _m, _s, _r, access,
    ) = _file_service(tmp_path)
    owner, student, outsider = (
        uuid_utils.uuid7(), uuid_utils.uuid7(), uuid_utils.uuid7()
    )
    cert = _issued_cert(certs, _a, _o, owner, student)
    with pytest.raises(ForbiddenError):
        service.download(cert.certificate_id, outsider)
    assert any(
        entry[0] == "certificate.download" and entry[-1] == "denied"
        for entry in access.audit
    )


def test_unknown_certificate_404(tmp_path) -> None:
    service, *_ = _file_service(tmp_path)
    with pytest.raises(NotFoundError):
        service.download(uuid_utils.uuid7(), uuid_utils.uuid7())


def test_template_background_feeds_render(tmp_path) -> None:
    (
        service, certs, templates, _a, _o, _u, media, store, renderer, _ac,
    ) = _file_service(tmp_path)
    owner, student = uuid_utils.uuid7(), uuid_utils.uuid7()
    cert = _issued_cert(certs, _a, _o, owner, student)
    activity = _a.get(cert.activity_id)

    # Wire a template whose background is a real stored image.
    bg_id = uuid_utils.uuid7()
    rel = store.save_typed(
        activity.org_id, bg_id, "image/png", "bg.png", _png_bytes()
    )
    media.create_asset(
        bg_id, activity.org_id, rel, "image/png", 1,
        datetime.now(UTC), owner_type="organization")
    tpl = templates.create(
        uuid_utils.uuid7(), activity.org_id, "M\u1eabu", bg_id,
        '{"title_y": 250}', datetime.now(UTC),
    )
    cert.template_id = tpl.template_id

    blob = service.download(cert.certificate_id, student)
    assert blob.content.startswith(b"%PDF-")
    assert renderer.calls == 1


def test_missing_stored_file_regenerates(tmp_path) -> None:
    (
        service, certs, _t, _a, _o, _u, media, store, renderer, _ac,
    ) = _file_service(tmp_path)
    owner, student = uuid_utils.uuid7(), uuid_utils.uuid7()
    cert = _issued_cert(certs, _a, _o, owner, student)

    blob = service.download(cert.certificate_id, student)
    assert renderer.calls == 1
    # Delete the stored file; next download re-renders.
    store.delete_file(media.get_asset(cert.file_media_id).file_url)
    again = service.download(cert.certificate_id, student)
    assert again.content.startswith(b"%PDF-")
    assert renderer.calls == 2
