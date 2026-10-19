"""Integration: migrate.org_tags backfills org catalogs on a real keyspace."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from activities.model import Activity
from activities.tag_model import (
    ActivityTagsByOrg,
    PublicTagDirectory,
    TagByOrg,
)
from core.ids import uuid7
from migrate import activity_tags, org_tags
from migrate import common as migrate_common

NOW = datetime.now(timezone.utc)


def _seed(org_a: UUID, org_b: UUID) -> list[UUID]:
    """Three tagged activities: org A (one live, one trashed), org B."""
    owner = uuid7()
    ids = [uuid7() for _ in range(3)]
    base = dict(
        created_by=owner,
        status="published",
        description="",
        start_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    Activity.create(
        id=ids[0], org_id=org_a, title="A one", slug="a-one",
        tag_names=["M\u00f4i tr\u01b0\u1eddng", "Y t\u1ebf"], **base,
    )
    Activity.create(
        id=ids[1], org_id=org_a, title="A two", slug="a-two",
        tag_names=["Y t\u1ebf"], deleted_at=NOW, **base,
    )
    Activity.create(
        id=ids[2], org_id=org_b, title="B one", slug="b-one",
        tag_names=["moi truong"], **base,
    )
    return ids


def _plain_session():  # noqa: ANN202
    """Plain driver session, as migrate.common.connect builds it.

    cqlengine's shared session reads rows as dicts; the migrator reads
    them by attribute, exactly like the CLI does on a plain session.
    """
    from cassandra.cluster import Cluster
    from cassandra.io.asyncioreactor import AsyncioConnection

    cluster = Cluster(
        ["127.0.0.1"],
        port=9042,
        protocol_version=4,
        connection_class=AsyncioConnection,
        connect_timeout=10.0,
    )
    return cluster, cluster.connect()


def test_dry_run_writes_nothing_then_apply_backfills_idempotently(
    clean_tables: str,
) -> None:
    org_a, org_b = uuid7(), uuid7()
    ids = _seed(org_a, org_b)
    cluster, session = _plain_session()
    try:
        dry = org_tags.run(session, clean_tables, dry_run=True)
        assert dry == {
            "activities": 3,
            "catalog_created": 3,
            "edges": 4,
            "directory": 4,
        }
        assert not list(TagByOrg.objects().all())
        assert not list(ActivityTagsByOrg.objects().all())
        assert not list(PublicTagDirectory.objects().all())

        applied = org_tags.run(session, clean_tables, dry_run=False)
        assert applied == {
            "activities": 3,
            "catalog_created": 3,
            "edges": 4,
            "directory": 4,
        }
        assert migrate_common.table_exists(
            session, clean_tables, "trashed_tag_edges_by_org"
        )
        assert activity_tags._column_exists(
            session, clean_tables, "tags_by_org", "deleted_at"
        )

        catalog = {(r.org_id, r.slug): r for r in TagByOrg.objects().all()}
        assert set(catalog) == {
            (org_a, "moi-truong"),
            (org_a, "y-te"),
            (org_b, "moi-truong"),
        }
        assert catalog[(org_a, "moi-truong")].name == (
            "M\u00f4i tr\u01b0\u1eddng"
        )
        assert catalog[(org_b, "moi-truong")].name == "moi truong"

        edges = {
            (r.org_id, r.tag_slug, r.activity_id)
            for r in ActivityTagsByOrg.objects().all()
        }
        assert edges == {
            (org_a, "moi-truong", ids[0]),
            (org_a, "y-te", ids[0]),
            (org_a, "y-te", ids[1]),
            (org_b, "moi-truong", ids[2]),
        }
        directory = {
            (r.slug, r.org_id)
            for r in PublicTagDirectory.objects().all()
        }
        assert directory == {
            ("moi-truong", org_a),
            ("y-te", org_a),
            ("moi-truong", org_b),
        }

        again = org_tags.run(session, clean_tables, dry_run=False)
        assert again["catalog_created"] == 0
    finally:
        cluster.shutdown()
