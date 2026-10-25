"""cqlengine models for api_keys + api_keys_by_org."""

from __future__ import annotations

from cassandra.cqlengine import columns, models


class ApiKey(models.Model):
    """Programmatic credential; lookup by digest only."""

    __table_name__ = "api_keys"

    key_hash = columns.Text(primary_key=True)
    key_id = columns.UUID(required=True)
    org_id = columns.UUID(required=True)
    name = columns.Text(required=True)
    scopes = columns.Set(columns.Text, required=False)
    expires_at = columns.DateTime(required=False)
    revoked_at = columns.DateTime(required=False)
    last_used_at = columns.DateTime(required=False)
    created_at = columns.DateTime(required=False)


class ApiKeyByOrg(models.Model):
    """Query table: list one org's keys by key_id."""

    __table_name__ = "api_keys_by_org"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    key_id = columns.UUID(primary_key=True)
    key_hash = columns.Text(required=True)
    name = columns.Text(required=True)
    scopes = columns.Set(columns.Text, required=False)
    expires_at = columns.DateTime(required=False)
    revoked_at = columns.DateTime(required=False)
    last_used_at = columns.DateTime(required=False)
    created_at = columns.DateTime(required=False)
