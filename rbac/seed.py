"""Idempotent RBAC catalog seeding: permissions + system roles.

Runs at application startup and inside the test-keyspace fixture. Every
step is a read-then-create check, so concurrent boots stay harmless
(last writer wins on identical rows).
"""

from __future__ import annotations

from datetime import datetime

from core.security import utcnow
from rbac.catalog import PERMISSIONS, SYSTEM_ROLES
from rbac.model import Permission, Role, RolePermission


def seed_rbac(now: datetime | None = None) -> None:
    """Insert missing catalog rows; safe to run on every boot."""
    stamp = now or utcnow()
    for code, description in PERMISSIONS.items():
        if Permission.objects(code=code).first() is None:
            Permission.create(code=code, module="org", description=description)
    for name, meta in SYSTEM_ROLES.items():
        role_id = meta["id"]
        if Role.objects(id=role_id).first() is None:  # type: ignore[arg-type]
            Role.create(
                id=role_id,  # type: ignore[arg-type]
                org_id=None,
                name=name,
                description=str(meta["description"]),
                is_system=True,
                created_at=stamp,
            )
        held = {
            row.permission_code
            for row in RolePermission.objects(
                role_id=role_id  # type: ignore[arg-type]
            ).all()
        }
        for code in meta["permissions"] - held:  # type: ignore[operator]
            RolePermission.create(role_id=role_id, permission_code=code)  # type: ignore[arg-type]
