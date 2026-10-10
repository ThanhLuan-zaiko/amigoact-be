"""cqlengine persistence for certificates and the serial index.

Serial uniqueness uses raw CQL LWT because cqlengine cannot surface
`[applied]` from an ORM create (same justification as other claims).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from cassandra.cqlengine.connection import get_session

from certificates.interfaces import CertificateStore
from certificates.model import (
    Certificate,
    CertificateRevocation,
    CertificatesBySerial,
    CertificatesByStudent,
)
from core.exceptions import CertificateExistsError


class CqlCertificateStore(CertificateStore):
    """Canonical rows plus student/serial feed projections."""

    def __init__(self, keyspace: str) -> None:
        self._keyspace = keyspace

    def issue(
        self,
        certificate_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        registration_id: UUID | None,
        serial_no: str,
        issued_by: UUID,
        now: datetime,
    ) -> Certificate:
        """Claim serial via LWT, then fan out to both read paths."""
        claim = get_session().execute(
            f"INSERT INTO {self._keyspace}.certificates_by_serial"
            " (serial_no, certificate_id, activity_id, student_id, status)"
            " VALUES (%s, %s, %s, %s, %s) IF NOT EXISTS",
            [serial_no, certificate_id, activity_id, student_id, "issued"],
        )
        if not claim.was_applied:
            raise CertificateExistsError(
                "Serial number already taken; retry."
            )
        row = Certificate.create(
            activity_id=activity_id,
            student_id=student_id,
            certificate_id=certificate_id,
            registration_id=registration_id,
            serial_no=serial_no,
            issued_at=now,
            issued_by=issued_by,
            status="issued",
        )
        CertificatesByStudent.create(
            student_id=student_id,
            issued_at=now,
            certificate_id=certificate_id,
            activity_id=activity_id,
            serial_no=serial_no,
            status="issued",
        )
        return row

    def get(
        self, activity_id: UUID, student_id: UUID
    ) -> Certificate | None:
        try:
            return Certificate.get(
                activity_id=activity_id, student_id=student_id
            )
        except Certificate.DoesNotExist:
            return None

    def get_by_serial(
        self, serial_no: str
    ) -> CertificatesBySerial | None:
        try:
            return CertificatesBySerial.get(serial_no=serial_no)
        except CertificatesBySerial.DoesNotExist:
            return None

    def revoke(
        self,
        certificate: Certificate,
        reason: str | None,
        revoked_by: UUID,
        now: datetime,
    ) -> Certificate:
        Certificate.objects(
            activity_id=certificate.activity_id,
            student_id=certificate.student_id,
        ).update(status="revoked")
        CertificatesByStudent.objects(
            student_id=certificate.student_id,
            issued_at=certificate.issued_at,
            certificate_id=certificate.certificate_id,
        ).update(status="revoked")
        CertificatesBySerial.objects(
            serial_no=certificate.serial_no
        ).update(status="revoked")
        CertificateRevocation.create(
            certificate_id=certificate.certificate_id,
            activity_id=certificate.activity_id,
            student_id=certificate.student_id,
            reason=reason,
            revoked_by=revoked_by,
            revoked_at=now,
        )
        updated = self.get(
            certificate.activity_id, certificate.student_id
        )
        assert updated is not None
        return updated

    def list_by_student(
        self, student_id: UUID, limit: int = 50
    ) -> list[Certificate]:
        rows = list(
            CertificatesByStudent.objects(student_id=student_id).limit(
                limit
            )
        )
        out: list[Certificate] = []
        for feed in rows:
            row = self.get(feed.activity_id, student_id)
            if row is not None:
                out.append(row)
        return out

    def list_by_activity(
        self, activity_id: UUID, limit: int = 500
    ) -> list[Certificate]:
        return list(
            Certificate.objects(activity_id=activity_id).limit(limit)
        )
