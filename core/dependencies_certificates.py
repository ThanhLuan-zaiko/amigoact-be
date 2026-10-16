"""Depends wiring for certificate services (split for the 350-line rule)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends

from core.config import Settings, get_settings
from core.dependencies import get_access_control, get_media_store
from core.dependencies import get_notification_service, user_directory

if TYPE_CHECKING:  # pragma: no cover - type imports only
    from certificates.file_service import CertificateFileService
    from certificates.service import CertificateService
    from certificates.template_service import TemplateService
    from notifications.service import NotificationService
    from rbac.interfaces import AccessControl


def get_certificate_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
    notifications: NotificationService = Depends(get_notification_service),
) -> CertificateService:
    """Build one CertificateService per request over cert tables."""
    from activities.repository import CqlActivityStore
    from certificates.repository import (
        CqlCertificateStore,
        CqlTemplateStore,
    )
    from certificates.service import CertificateService
    from orgs.repository import CqlOrgRepository
    from registrations.repository import CqlRegistrationStore

    return CertificateService(
        certificates=CqlCertificateStore(settings.scylla_keyspace),
        registrations=CqlRegistrationStore(settings.scylla_keyspace),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        access=access,
        notifications=notifications,
        templates=CqlTemplateStore(),
    )


def get_certificate_file_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> "CertificateFileService":
    """Build the PDF download service over cert + media stores."""
    from activities.repository import CqlActivityStore
    from certificates.file_service import CertificateFileService
    from certificates.pdf import PillowCertificateRenderer
    from certificates.repository import (
        CqlCertificateStore,
        CqlTemplateStore,
    )
    from orgs.media_repository import CqlMediaRepository
    from orgs.repository import CqlOrgRepository

    return CertificateFileService(
        certificates=CqlCertificateStore(settings.scylla_keyspace),
        templates=CqlTemplateStore(),
        activities=CqlActivityStore(settings.scylla_keyspace),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        users=user_directory(settings),
        media=CqlMediaRepository(),
        store=get_media_store(settings),
        renderer=PillowCertificateRenderer(),
        access=access,
    )


def get_template_service(
    settings: Settings = Depends(get_settings),
    access: AccessControl = Depends(get_access_control),
) -> TemplateService:
    """Build one TemplateService per request over template rows."""
    from certificates.repository import CqlTemplateStore
    from certificates.template_service import TemplateService
    from orgs.repository import CqlOrgRepository

    return TemplateService(
        templates=CqlTemplateStore(),
        orgs=CqlOrgRepository(settings.scylla_keyspace),
        access=access,
    )
