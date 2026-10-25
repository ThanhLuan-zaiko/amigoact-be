"""cqlengine models for volunteer certificates and serial lookup."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class Certificate(models.Model):
    """Canonical certificate row, one per (activity, student)."""

    __table_name__ = "certificates"

    activity_id = columns.UUID(primary_key=True)
    student_id = columns.UUID(primary_key=True)
    certificate_id = columns.UUID(required=True, default=uuid7)
    registration_id = columns.UUID()
    template_id = columns.UUID()
    serial_no = columns.Text(required=True)
    issued_at = columns.DateTime()
    issued_by = columns.UUID()
    file_media_id = columns.UUID()
    status = columns.Text(required=True)  # issued | revoked


class CertificatesByStudent(models.Model):
    """Student's certificate wall, newest first."""

    __table_name__ = "certificates_by_student"

    student_id = columns.UUID(primary_key=True)
    issued_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    certificate_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    activity_id = columns.UUID()
    serial_no = columns.Text()
    status = columns.Text()


class CertificatesBySerial(models.Model):
    """Public verification path keyed by the printed serial."""

    __table_name__ = "certificates_by_serial"

    serial_no = columns.Text(primary_key=True)
    certificate_id = columns.UUID()
    activity_id = columns.UUID()
    student_id = columns.UUID()
    status = columns.Text()


class CertificatesById(models.Model):
    """Certificate-id lookup feeding the PDF download endpoint."""

    __table_name__ = "certificates_by_id"

    certificate_id = columns.UUID(primary_key=True)
    activity_id = columns.UUID()
    student_id = columns.UUID()


class CertificateRevocation(models.Model):
    """Append-only revocation trail."""

    __table_name__ = "certificate_revocations"

    revocation_id = columns.UUID(primary_key=True, default=uuid7)
    certificate_id = columns.UUID()
    activity_id = columns.UUID()
    student_id = columns.UUID()
    reason = columns.Text()
    revoked_by = columns.UUID()
    revoked_at = columns.DateTime()


class CertificateTemplate(models.Model):
    """Per-org visual template (background + layout JSON)."""

    __table_name__ = "certificate_templates"

    template_id = columns.UUID(primary_key=True, default=uuid7)
    org_id = columns.UUID(index=True)
    name = columns.Text()
    background_media_id = columns.UUID()
    layout_json = columns.Text()
    is_active = columns.Boolean()
    created_at = columns.DateTime()
