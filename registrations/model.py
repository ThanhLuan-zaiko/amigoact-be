"""cqlengine models for registrations and attendance projections."""

from __future__ import annotations

import core.database  # noqa: F401  (reactor compat shim must run first)
from core.ids import uuid7
from cassandra.cqlengine import columns, models


class Registration(models.Model):
    """Authoritative registration row (one student x one activity)."""

    __table_name__ = "registrations"
    __keyspace__ = "amigoact"

    registration_id = columns.UUID(primary_key=True, default=uuid7)
    activity_id = columns.UUID(required=True)
    student_id = columns.UUID(required=True)
    slot_id = columns.UUID(required=False)
    status = columns.Text(required=True)
    form_data = columns.Text(required=False)
    note = columns.Text(required=False)
    review_note = columns.Text(required=False)
    reviewed_by = columns.UUID(required=False)
    reviewed_at = columns.DateTime(required=False)
    checkin_token = columns.UUID(required=False)
    registered_at = columns.DateTime(required=False)
    cancelled_at = columns.DateTime(required=False)


class RegistrationsByActivity(models.Model):
    """Roster feed for org managers, oldest application first."""

    __table_name__ = "registrations_by_activity"
    __keyspace__ = "amigoact"

    activity_id = columns.UUID(primary_key=True)
    registered_at = columns.DateTime(
        primary_key=True, clustering_order="ASC"
    )
    registration_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    student_id = columns.UUID()
    slot_id = columns.UUID()
    status = columns.Text()


class RegistrationsByStudent(models.Model):
    """Student's own application history, newest first."""

    __table_name__ = "registrations_by_student"
    __keyspace__ = "amigoact"

    student_id = columns.UUID(primary_key=True)
    registered_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    registration_id = columns.UUID(
        primary_key=True, clustering_order="ASC"
    )
    activity_id = columns.UUID()
    status = columns.Text()


class RegistrationsByActivityStudent(models.Model):
    """Duplicate guard: one row per (activity, student, slot)."""

    __table_name__ = "registrations_by_activity_student"
    __keyspace__ = "amigoact"

    activity_id = columns.UUID(primary_key=True)
    student_id = columns.UUID(primary_key=True)
    slot_id = columns.UUID(primary_key=True)
    registration_id = columns.UUID()
    status = columns.Text()
    registered_at = columns.DateTime()


class RegistrationsByToken(models.Model):
    """Personal-QR path: checkin_token resolves to a registration."""

    __table_name__ = "registrations_by_token"
    __keyspace__ = "amigoact"

    checkin_token = columns.UUID(primary_key=True)
    registration_id = columns.UUID()
    activity_id = columns.UUID()
    student_id = columns.UUID()
    slot_id = columns.UUID()
    status = columns.Text()


class RegistrationStatusHistory(models.Model):
    """Audit feed of every status change on one registration."""

    __table_name__ = "registration_status_history"
    __keyspace__ = "amigoact"

    registration_id = columns.UUID(primary_key=True)
    changed_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    history_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    from_status = columns.Text()
    to_status = columns.Text()
    changed_by = columns.UUID()
    note = columns.Text()


class WaitlistEntry(models.Model):
    """FIFO queue row for one activity that hit its capacity."""

    __table_name__ = "waitlist_entries"
    __keyspace__ = "amigoact"

    activity_id = columns.UUID(primary_key=True)
    joined_at = columns.DateTime(
        primary_key=True, clustering_order="ASC"
    )
    waitlist_id = columns.UUID(
        primary_key=True, clustering_order="ASC", default=uuid7
    )
    student_id = columns.UUID()
    slot_id = columns.UUID()
    status = columns.Text()
    promoted_at = columns.DateTime()


class AttendanceRecord(models.Model):
    """Authoritative check-in/out row for one student x one activity."""

    __table_name__ = "attendance_records"
    __keyspace__ = "amigoact"

    record_id = columns.UUID(primary_key=True, default=uuid7)
    session_id = columns.UUID()
    schedule_id = columns.UUID()
    activity_id = columns.UUID()
    student_id = columns.UUID()
    method = columns.Text()
    scanned_at = columns.DateTime()
    verified_by = columns.UUID()
    checked_out_at = columns.DateTime()
    check_out_method = columns.Text()
    actual_hours = columns.Double()


class AttendanceByRegistration(models.Model):
    """One attendance record per registration (UNIQUE equivalent)."""

    __table_name__ = "attendance_by_registration"
    __keyspace__ = "amigoact"

    registration_id = columns.UUID(primary_key=True)
    record_id = columns.UUID()
    activity_id = columns.UUID()
    student_id = columns.UUID()
    session_id = columns.UUID()
    scanned_at = columns.DateTime()


class AttendanceByActivity(models.Model):
    """Org feed: every check-in of one activity, newest first."""

    __table_name__ = "attendance_by_activity"
    __keyspace__ = "amigoact"

    activity_id = columns.UUID(primary_key=True)
    scanned_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    record_id = columns.UUID(primary_key=True, clustering_order="ASC")
    student_id = columns.UUID()
    session_id = columns.UUID()
    method = columns.Text()


class AttendanceByStudent(models.Model):
    """Student feed: their check-ins across activities."""

    __table_name__ = "attendance_by_student"
    __keyspace__ = "amigoact"

    student_id = columns.UUID(primary_key=True)
    scanned_at = columns.DateTime(
        primary_key=True, clustering_order="DESC"
    )
    record_id = columns.UUID(primary_key=True, clustering_order="ASC")
    activity_id = columns.UUID()
    session_id = columns.UUID()
    method = columns.Text()
