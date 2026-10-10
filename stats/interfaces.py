"""Ports for the stats context: it reuses other features' stores.

Stats is a read-only projection over existing feeds, so its ports are
the already-defined store interfaces (ActivityStore, MemberRepository,
HourLedgerStore, AttendanceStore, CertificateStore). No new persistence
lives here; see core/dependencies_features.py for the wiring.
"""
