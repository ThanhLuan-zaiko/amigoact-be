"""cqlengine models for chat safety: attachment policy and timeouts."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from cassandra.cqlengine import columns, models


class OrgChatSettings(models.Model):
    """Per-org chat rules; a missing row means every default applies."""

    __table_name__ = "org_chat_settings"

    org_id = columns.UUID(primary_key=True)
    attach_restricted = columns.Boolean(required=True, default=False)


class OrgChatTimeout(models.Model):
    """A member muted in the org's chat until `until` (rows also carry a TTL)."""

    __table_name__ = "org_chat_timeouts"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    user_id = columns.UUID(primary_key=True, clustering_order="ASC")
    until = columns.DateTime(required=True)
    set_by = columns.UUID(required=True)
    reason = columns.Text(required=False, default="")
