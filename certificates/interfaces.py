"""Abstract ports for the certificates bounded context (DIP wiring)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from certificates.model import (
    Certificate,
    CertificateTemplate,
    CertificatesBySerial,
)


class CertificateStore(ABC):
    """Persistence port for issuance, revocation, and verification."""

    @abstractmethod
    def issue(
        self,
        certificate_id: UUID,
        activity_id: UUID,
        student_id: UUID,
        registration_id: UUID | None,
        serial_no: str,
        issued_by: UUID,
        now: datetime,
        template_id: UUID | None = None,
    ) -> Certificate:
        """Claim the serial, then write canonical + student/serial feeds."""

    @abstractmethod
    def get(
        self, activity_id: UUID, student_id: UUID
    ) -> Certificate | None:
        """Load the canonical row by its composite key."""

    @abstractmethod
    def get_by_serial(
        self, serial_no: str
    ) -> CertificatesBySerial | None:
        """Resolve a printed serial for public verification."""

    @abstractmethod
    def revoke(
        self,
        certificate: Certificate,
        reason: str | None,
        revoked_by: UUID,
        now: datetime,
    ) -> Certificate:
        """Mark revoked across canonical + feeds; append audit row."""

    @abstractmethod
    def list_by_student(
        self, student_id: UUID, limit: int = 50
    ) -> list[Certificate]:
        """Student's issued certificates, newest first."""

    @abstractmethod
    def list_by_activity(
        self, activity_id: UUID, limit: int = 500
    ) -> list[Certificate]:
        """All certificates of one activity (partition-local read)."""


class TemplateStore(ABC):
    """Persistence port for the org's certificate template library."""

    @abstractmethod
    def create(
        self,
        template_id: UUID,
        org_id: UUID,
        name: str,
        background_media_id: UUID | None,
        layout_json: str | None,
        now: datetime,
    ) -> CertificateTemplate:
        """Insert one active template row."""

    @abstractmethod
    def get(self, template_id: UUID) -> CertificateTemplate | None:
        """Load one template by primary key."""

    @abstractmethod
    def list_by_org(self, org_id: UUID) -> list[CertificateTemplate]:
        """The org's template library (small set, secondary index)."""

    @abstractmethod
    def update(
        self,
        template_id: UUID,
        name: str | None = None,
        background_media_id: UUID | None = None,
        layout_json: str | None = None,
        is_active: bool | None = None,
    ) -> CertificateTemplate | None:
        """Patch provided columns only; None leaves them untouched."""
