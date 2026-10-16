"""cqlengine models for report_snapshots + export_jobs."""

from __future__ import annotations

from cassandra.cqlengine import columns, models


class ReportSnapshot(models.Model):
    """Saved report payload per org, newest first."""

    __table_name__ = "report_snapshots"
    __keyspace__ = "amigoact"

    org_id = columns.UUID(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    snapshot_id = columns.UUID(primary_key=True)
    report_type = columns.Text(required=True)
    period_start = columns.DateTime(required=False)
    period_end = columns.DateTime(required=False)
    payload_json = columns.Text(required=True)
    created_by = columns.UUID(required=True)


class ExportJob(models.Model):
    """Async export request owned by the requester, newest first."""

    __table_name__ = "export_jobs"
    __keyspace__ = "amigoact"

    requested_by = columns.UUID(primary_key=True, partition_key=True)
    created_at = columns.DateTime(primary_key=True, clustering_order="DESC")
    job_id = columns.UUID(primary_key=True)
    org_id = columns.UUID(required=True)
    job_type = columns.Text(required=True)
    status = columns.Text(required=True)
    file_url = columns.Text(required=False)
    error = columns.Text(required=False)
    finished_at = columns.DateTime(required=False)
