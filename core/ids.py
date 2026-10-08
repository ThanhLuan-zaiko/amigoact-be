"""UUIDv7 generation. uuid-utils creates them, stdlib types carry them.

The cassandra-driver UUID column only accepts stdlib uuid.UUID, so every
generated value is normalized here. Single home for ID creation.
"""

from __future__ import annotations

import uuid as stdlib_uuid

import uuid_utils


def uuid7() -> stdlib_uuid.UUID:
    """Generate a UUIDv7 as a stdlib UUID (driver-compatible)."""
    value = uuid_utils.uuid7()
    if isinstance(value, stdlib_uuid.UUID):
        return value
    return stdlib_uuid.UUID(str(value))
