// =============================================================================
// AmigoACT — ScyllaDB schema (volunteer & extracurricular activity management)
// File: amigoact-be/schemas.cql
//
// Conventions (must match AGENTS.md):
// - All primary keys are CQL `uuid`, generated application-side as UUIDv7
//   (uuid_utils.uuid7()). Exceptions are natural-key lookup tables where
//   the key itself IS the query path (users_by_email, qr_codes.code,
//   permissions.code, organizations_by_tax_code, certificates_by_serial,
//   media_by_hash, api_keys.key_hash, idempotency_keys, ws_tickets, ...).
// - No Secondary Indexes and no ALLOW FILTERING. Every access path has its own
//   query table (e.g. registrations_by_activity / registrations_by_student).
// - Time-ordered feeds use CLUSTERING ORDER BY ... DESC.
// - The Student <-> Activity N-M relationship is modeled explicitly through
//   `registrations` plus both directional query tables.
// - Raw CQL here is the migration/reference source. Runtime access goes through
//   `cassandra.cqlengine` Models in each feature's repository.py (AGENTS.md #5).
// - PERSISTENCE POLICY (no RAM state): ScyllaDB is the single source of truth.
//   Process restarts must lose nothing. Forbidden: in-memory session stores,
//   token caches, rate-limit buckets, request-dedup sets, locks, QR/slot
//   counters kept in app RAM. Read-through caches are allowed only with TTL
//   and DB fallback, never as authoritative state. Concurrent increments
//   (qr_codes.used_count, activity_slots.registered, rate-limit hits) use
//   lightweight transactions (IF / IF NOT EXISTS), never in-process locks.
//   Ephemeral coordination that is typically kept in RAM is persisted instead:
//   `idempotency_keys` (safe retries), `auth_rate_limits` (durable buckets),
//   `job_leases` (single-worker background jobs).
// - Feature lineage: concepts ported from the PostgreSQL reference design
//   (../schema.sql) — scoped RBAC grants (platform/org/activity), central
//   file-registry fields on media_assets, skills matching, activity
//   partners, legal org identity, per-registration check-in tokens, and
//   hour approval queues. Everything is re-modeled query-first: no joins.
// - 114 tables total: 9 auth + 11 org + 14 rbac + 7 student/skills
//   + 13 activity + 8 registration + 9 attendance + 6 hours
//   + 5 certificate + 6 media + 3 notification + 4 report + 2 review
//   + 3 durability + 1 realtime + 13 feed/chat.
// =============================================================================

CREATE KEYSPACE IF NOT EXISTS amigoact
WITH replication = {'class': 'NetworkTopologyStrategy', 'datacenter1': 1};

USE amigoact;

// -----------------------------------------------------------------------------
// 1. AUTH & IDENTITY (9 tables)
// Hybrid auth: stateless JWT access + stateful opaque refresh (SHA-256 hashes).
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    email text,
    phone text,
    password_hash text,
    full_name text,
    account_type text, // individual | business
    tax_code text,
    company_name text,
    legal_rep_name text,
    legal_rep_id text,
    legal_rep_position text,
    // Profile fields from the relational design (deployed keyspaces:
    // ALTER TABLE users ADD date_of_birth date, ADD gender text,
    // ADD address text, ADD avatar_media_id uuid, ADD last_login_at timestamp).
    date_of_birth date,
    gender text, // male | female | other | unspecified
    address text,
    avatar_media_id uuid, // -> media_assets
    last_login_at timestamp,
    email_verified_at timestamp,
    status text, // active | suspended | deleted
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE IF NOT EXISTS users_by_email (
    email text PRIMARY KEY,
    user_id uuid
);

CREATE TABLE IF NOT EXISTS users_by_phone (
    phone text PRIMARY KEY,
    user_id uuid
);

CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
    token_hash text PRIMARY KEY,
    user_id uuid,
    family_id uuid,
    expires_at timestamp,
    revoked_at timestamp,
    rotated_from text,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS refresh_tokens_by_user (
    user_id uuid,
    token_hash text,
    family_id uuid,
    expires_at timestamp,
    revoked_at timestamp,
    PRIMARY KEY ((user_id), token_hash)
);

CREATE TABLE IF NOT EXISTS refresh_tokens_by_family (
    family_id uuid,
    token_hash text,
    user_id uuid,
    expires_at timestamp,
    revoked_at timestamp,
    PRIMARY KEY ((family_id), token_hash)
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    user_id uuid,
    session_id uuid,
    device_label text,
    user_agent text,
    ip text,
    created_at timestamp,
    last_seen_at timestamp,
    // revoked beats expired (deployed keyspaces: ALTER TABLE auth_sessions
    // ADD user_agent text, ADD expires_at timestamp).
    expires_at timestamp,
    revoked_at timestamp,
    PRIMARY KEY ((user_id), session_id)
);

CREATE TABLE IF NOT EXISTS password_resets (
    token_hash text PRIMARY KEY,
    user_id uuid,
    expires_at timestamp,
    used_at timestamp
);

CREATE TABLE IF NOT EXISTS email_verifications (
    token_hash text PRIMARY KEY,
    user_id uuid,
    email text,
    expires_at timestamp,
    verified_at timestamp
);

// -----------------------------------------------------------------------------
// 2. ORGANIZATIONS & MULTI-TENANCY (11 tables)
// Enterprise scoping: organization -> campus -> department. Every business row
// carries org_id so data never leaks across tenants.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS organizations (
    id uuid PRIMARY KEY,
    name text,
    slug text,
    description text,
    org_type text, // organization | club | group | business
    status text, // active | suspended
    join_policy text, // invite | open (deployed keyspaces: ALTER TABLE organizations ADD join_policy text)
    owner_id uuid,
    tax_code text,
    legal_rep_name text,
    legal_rep_id text,
    legal_rep_position text,
    legal_status text, // none | pending | verified
    // Contact channels + legal identity + verification trail from the
    // relational design (deployed keyspaces: ALTER TABLE organizations ADD
    // email text, ADD phone text, ADD website text, ADD address text,
    // ADD city text, ADD country text, ADD legal_name text,
    // ADD license_number text, ADD is_personal boolean,
    // ADD logo_media_id uuid, ADD cover_media_id uuid,
    // ADD verified_at timestamp, ADD verified_by uuid,
    // ADD previous_slug text).
    email text,
    phone text,
    website text,
    address text,
    city text,
    country text,
    legal_name text, // registered name on the license
    license_number text, // operating license / permit number
    is_personal boolean, // auto-created personal community org
    logo_media_id uuid,
    cover_media_id uuid,
    verified_at timestamp,
    verified_by uuid,
    previous_slug text, // slug vacated by soft-delete; reclaim on restore
    deleted_at timestamp, // null = alive; set = soft-deleted, restorable
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE IF NOT EXISTS organizations_by_slug (
    slug text PRIMARY KEY,
    org_id uuid
);

// One verified org per tax code; claimed with LWT like users_by_email.
CREATE TABLE IF NOT EXISTS organizations_by_tax_code (
    tax_code text PRIMARY KEY,
    org_id uuid
);

// Platform-admin verification queue, oldest first.
CREATE TABLE IF NOT EXISTS organizations_by_legal_status (
    legal_status text, // none | pending | verified
    created_at timestamp,
    org_id uuid,
    name text,
    slug text,
    PRIMARY KEY ((legal_status), created_at, org_id)
) WITH CLUSTERING ORDER BY (created_at ASC, org_id ASC);

// Guest-readable org directory, partitioned by kind, newest first. Rows
// join back to the canonical organizations row at read time.
CREATE TABLE IF NOT EXISTS organizations_public (
    kind text, // organization | club | group | business
    created_at timestamp,
    org_id uuid,
    name text,
    slug text,
    PRIMARY KEY ((kind), created_at, org_id)
) WITH CLUSTERING ORDER BY (created_at DESC, org_id ASC);

// Org-kind lookup — a table (not a hard-coded enum) so new kinds ship with
// data instead of schema churn. Seed: school, youth_union, ngo, nonprofit,
// business, government, community.
CREATE TABLE IF NOT EXISTS org_types (
    code text PRIMARY KEY,
    name text,
    sort_order int
);

CREATE TABLE IF NOT EXISTS organization_members (
    org_id uuid,
    user_id uuid,
    status text, // active | invited | suspended | left
    invited_by uuid, // (deployed keyspaces: ALTER TABLE organization_members ADD invited_by uuid)
    joined_at timestamp,
    PRIMARY KEY ((org_id), user_id)
);

CREATE TABLE IF NOT EXISTS members_by_user (
    user_id uuid,
    org_id uuid,
    status text,
    invited_by uuid, // (deployed keyspaces: ALTER TABLE members_by_user ADD invited_by uuid)
    joined_at timestamp,
    PRIMARY KEY ((user_id), org_id)
);

CREATE TABLE IF NOT EXISTS campuses (
    id uuid PRIMARY KEY,
    org_id uuid,
    name text,
    address text,
    status text,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS campuses_by_org (
    org_id uuid,
    campus_id uuid,
    name text,
    PRIMARY KEY ((org_id), campus_id)
);

CREATE TABLE IF NOT EXISTS departments (
    id uuid PRIMARY KEY,
    org_id uuid,
    campus_id uuid,
    name text,
    code text,
    status text,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS departments_by_campus (
    campus_id uuid,
    department_id uuid,
    name text,
    code text,
    PRIMARY KEY ((campus_id), department_id)
);

// -----------------------------------------------------------------------------
// 3. RBAC — ENTERPRISE AUTHORIZATION (14 tables)
// Layered model: system/org roles -> permissions, plus direct per-user grants
// with expiry, API keys for integrations, and a full access audit trail.
// Checks always combine role permissions AND direct grants AND ownership.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS roles (
    id uuid PRIMARY KEY,
    org_id uuid, // null = system-wide role
    code text, // stable machine code, unique per scope ('org_admin')
    name text,
    description text,
    is_system boolean,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS roles_by_org (
    org_id uuid,
    role_id uuid,
    name text,
    PRIMARY KEY ((org_id), role_id)
);

CREATE TABLE IF NOT EXISTS permissions (
    code text PRIMARY KEY, // e.g. 'activity:create'
    module text, // auth | org | activity | attendance | certificate | report
    description text
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id uuid,
    permission_code text,
    PRIMARY KEY ((role_id), permission_code)
);

CREATE TABLE IF NOT EXISTS user_roles (
    org_id uuid,
    user_id uuid,
    role_id uuid,
    granted_by uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((org_id), user_id, role_id)
);

CREATE TABLE IF NOT EXISTS roles_by_user (
    user_id uuid,
    org_id uuid,
    role_id uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((user_id), org_id, role_id)
);

// Scoped role grants. PK columns cannot be null, so the three scope levels
// of the relational user_role_assignments get separate tables:
//   platform_user_roles          -> platform-wide grant (platform admins)
//   user_roles / roles_by_user   -> organization-wide grant (above)
//   activity_user_roles          -> single-activity grant (an external
//                                   volunteer leading one corporate event
//                                   without holding org rights)
// expires_at enables temporary delegation; granted_by keeps the audit trail.
CREATE TABLE IF NOT EXISTS platform_user_roles (
    user_id uuid,
    role_id uuid,
    granted_by uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((user_id), role_id)
);

CREATE TABLE IF NOT EXISTS platform_role_roster (
    role_id uuid,
    user_id uuid,
    granted_by uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((role_id), user_id)
);

CREATE TABLE IF NOT EXISTS activity_user_roles (
    activity_id uuid,
    user_id uuid,
    role_id uuid,
    org_id uuid,
    granted_by uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((activity_id), user_id, role_id)
);

CREATE TABLE IF NOT EXISTS user_activity_roles (
    user_id uuid,
    activity_id uuid,
    role_id uuid,
    org_id uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((user_id), activity_id, role_id)
);

CREATE TABLE IF NOT EXISTS user_permission_grants (
    org_id uuid,
    user_id uuid,
    permission_code text,
    reason text,
    granted_by uuid,
    granted_at timestamp,
    expires_at timestamp,
    PRIMARY KEY ((org_id), user_id, permission_code)
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash text PRIMARY KEY,
    key_id uuid,
    org_id uuid,
    name text,
    scopes set<text>,
    expires_at timestamp,
    revoked_at timestamp,
    last_used_at timestamp
);

CREATE TABLE IF NOT EXISTS access_audit_logs (
    org_id uuid,
    occurred_at timestamp,
    log_id uuid,
    actor_id uuid,
    action text,
    resource_type text,
    resource_id uuid,
    result text, // allowed | denied
    ip text,
    metadata text,
    PRIMARY KEY ((org_id), occurred_at, log_id)
) WITH CLUSTERING ORDER BY (occurred_at DESC, log_id ASC);

// Per-resource history ("everything that happened to object X"), e.g. the
// revocation trail of one certificate or the grant history of one event.
CREATE TABLE IF NOT EXISTS access_audit_by_resource (
    resource_id uuid,
    occurred_at timestamp,
    log_id uuid,
    org_id uuid,
    actor_id uuid,
    action text,
    result text, // allowed | denied
    PRIMARY KEY ((resource_id), occurred_at, log_id)
) WITH CLUSTERING ORDER BY (occurred_at DESC, log_id ASC);

// -----------------------------------------------------------------------------
// 4. STUDENT PROFILES & SKILLS (7 tables)
// Profiles extend users 1-1; skills are a seeded lookup powering the
// volunteer <-> activity matching (self-declared, level app-validated 1-5).
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS student_profiles (
    user_id uuid PRIMARY KEY,
    student_code text,
    campus_id uuid,
    department_id uuid,
    class_name text,
    enrollment_year int,
    school_name text, // free-text school outside a member org
    bio text,
    interests set<text>,
    status text, // studying | graduated | suspended | working
    total_hours double,
    updated_at timestamp
);

CREATE TABLE IF NOT EXISTS student_profiles_by_code (
    campus_id uuid,
    student_code text,
    user_id uuid,
    PRIMARY KEY ((campus_id), student_code)
);

CREATE TABLE IF NOT EXISTS emergency_contacts (
    user_id uuid,
    contact_id uuid,
    name text,
    relation text,
    phone text,
    is_primary boolean,
    PRIMARY KEY ((user_id), contact_id)
);

// Skill catalog — seeded lookup (first-aid, teaching, translation, ...).
CREATE TABLE IF NOT EXISTS skills (
    id uuid PRIMARY KEY,
    name text,
    slug text
);

CREATE TABLE IF NOT EXISTS skills_by_slug (
    slug text PRIMARY KEY,
    skill_id uuid
);

// n-m: user <-> skill (self-declared). Both directions: profile listing on
// user_skills, coordinator matching on users_by_skill ("who has first-aid
// level >= 3?"). Activity-side requirements live in section 5.
CREATE TABLE IF NOT EXISTS user_skills (
    user_id uuid,
    skill_id uuid,
    level int, // 1-5
    PRIMARY KEY ((user_id), skill_id)
);

CREATE TABLE IF NOT EXISTS users_by_skill (
    skill_id uuid,
    user_id uuid,
    level int,
    PRIMARY KEY ((skill_id), user_id)
);

// -----------------------------------------------------------------------------
// 5. ACTIVITIES / EVENTS (13 tables)
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS activities (
    id uuid PRIMARY KEY,
    org_id uuid,
    campus_id uuid,
    title text,
    description text,
    category_id uuid,
    status text, // draft | published | ongoing | completed | cancelled
    location text,
    max_participants int,
    start_at timestamp,
    end_at timestamp,
    hours_awarded double,
    requirements_json text,
    cover_media_id uuid,
    created_by uuid,
    // Relational parity (deployed keyspaces: ALTER TABLE activities ADD
    // slug text, ADD person_in_charge_id uuid, ADD address text,
    // ADD city text, ADD latitude decimal, ADD longitude decimal,
    // ADD is_remote boolean, ADD registration_deadline timestamp,
    // ADD published_at timestamp).
    slug text, // unique per org via activities_by_slug (LWT claim)
    person_in_charge_id uuid, // on-site answerable contact, != created_by
    address text,
    city text,
    latitude decimal,
    longitude decimal,
    is_remote boolean,
    registration_deadline timestamp,
    published_at timestamp,
    created_at timestamp,
    updated_at timestamp
);

CREATE TABLE IF NOT EXISTS activities_by_org (
    org_id uuid,
    start_at timestamp,
    activity_id uuid,
    title text,
    status text,
    campus_id uuid,
    PRIMARY KEY ((org_id), start_at, activity_id)
) WITH CLUSTERING ORDER BY (start_at DESC, activity_id ASC);

CREATE TABLE IF NOT EXISTS activities_by_status (
    status text,
    start_at timestamp,
    activity_id uuid,
    org_id uuid,
    title text,
    PRIMARY KEY ((status), start_at, activity_id)
) WITH CLUSTERING ORDER BY (start_at DESC, activity_id ASC);

CREATE TABLE IF NOT EXISTS activities_by_category (
    category_id uuid,
    start_at timestamp,
    activity_id uuid,
    org_id uuid,
    title text,
    PRIMARY KEY ((category_id), start_at, activity_id)
) WITH CLUSTERING ORDER BY (start_at DESC, activity_id ASC);

// Pretty URLs + per-org slug uniqueness (relational UNIQUE(org, slug)).
CREATE TABLE IF NOT EXISTS activities_by_slug (
    org_id uuid,
    slug text,
    activity_id uuid,
    title text,
    status text,
    start_at timestamp,
    PRIMARY KEY ((org_id), slug)
);

CREATE TABLE IF NOT EXISTS activity_categories (
    id uuid PRIMARY KEY,
    org_id uuid, // null = global category
    name text,
    slug text,
    description text,
    icon text,
    default_hours double,
    color text
);

// n-m: activity <-> skill (required/desired skills for volunteers).
CREATE TABLE IF NOT EXISTS activity_skills (
    activity_id uuid,
    skill_id uuid,
    is_required boolean,
    PRIMARY KEY ((activity_id), skill_id)
);

// n-m: activity <-> partner orgs (businesses co-organizing/sponsoring).
CREATE TABLE IF NOT EXISTS activity_partners (
    activity_id uuid,
    org_id uuid,
    role text, // co_organizer | sponsor
    note text,
    PRIMARY KEY ((activity_id), org_id)
);

CREATE TABLE IF NOT EXISTS partner_activities_by_org (
    org_id uuid,
    start_at timestamp,
    activity_id uuid,
    title text,
    role text, // co_organizer | sponsor
    PRIMARY KEY ((org_id), start_at, activity_id)
) WITH CLUSTERING ORDER BY (start_at DESC, activity_id ASC);

CREATE TABLE IF NOT EXISTS activity_schedules (
    id uuid PRIMARY KEY,
    activity_id uuid,
    title text,
    location text,
    start_at timestamp,
    end_at timestamp,
    status text, // scheduled | open | closed | cancelled
    created_at timestamp
);

// Per-activity session feed: the main row is keyed by id, this is the
// "list sessions of one activity" query table.
CREATE TABLE IF NOT EXISTS schedules_by_activity (
    activity_id uuid,
    start_at timestamp,
    schedule_id uuid,
    title text,
    status text,
    PRIMARY KEY ((activity_id), start_at, schedule_id)
) WITH CLUSTERING ORDER BY (start_at ASC, schedule_id ASC);

CREATE TABLE IF NOT EXISTS activity_slots (
    schedule_id uuid,
    slot_id uuid,
    title text,
    capacity int,
    registered int,
    start_at timestamp,
    end_at timestamp,
    PRIMARY KEY ((schedule_id), slot_id)
);

CREATE TABLE IF NOT EXISTS activity_staff (
    activity_id uuid,
    user_id uuid,
    staff_role text, // organizer | supervisor | supporter
    assigned_by uuid,
    assigned_at timestamp,
    PRIMARY KEY ((activity_id), user_id)
);

CREATE TABLE IF NOT EXISTS activity_announcements (
    activity_id uuid,
    published_at timestamp,
    announcement_id uuid,
    title text,
    body text,
    created_by uuid,
    PRIMARY KEY ((activity_id), published_at, announcement_id)
) WITH CLUSTERING ORDER BY (published_at DESC, announcement_id ASC);

// -----------------------------------------------------------------------------
// 6. REGISTRATIONS — STUDENT <-> ACTIVITY N-M (8 tables)
// The N-M join is explicit: `registrations` + directional query tables.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS registrations (
    registration_id uuid PRIMARY KEY,
    activity_id uuid,
    student_id uuid,
    slot_id uuid,
    status text, // pending | approved | rejected | waitlisted | cancelled | attended
    form_data text, // JSON answers to registration_forms questions
    note text, // volunteer's message / motivation
    review_note text, // reviewer feedback or rejection reason
    reviewed_by uuid,
    reviewed_at timestamp,
    checkin_token uuid, // personal QR payload; resolve via registrations_by_token
    registered_at timestamp,
    cancelled_at timestamp
);

CREATE TABLE IF NOT EXISTS registrations_by_activity (
    activity_id uuid,
    registered_at timestamp,
    registration_id uuid,
    student_id uuid,
    slot_id uuid,
    status text,
    PRIMARY KEY ((activity_id), registered_at, registration_id)
) WITH CLUSTERING ORDER BY (registered_at ASC, registration_id ASC);

CREATE TABLE IF NOT EXISTS registrations_by_student (
    student_id uuid,
    registered_at timestamp,
    registration_id uuid,
    activity_id uuid,
    status text,
    PRIMARY KEY ((student_id), registered_at, registration_id)
) WITH CLUSTERING ORDER BY (registered_at DESC, registration_id ASC);

// Per-student registration lookup inside one activity — the CQL answer to
// the relational UNIQUE(activity, slot, student): duplicate checks plus
// multi-shift registrations of the same event. slot_id = zero UUID marks
// a whole-activity registration (PK columns cannot be null).
CREATE TABLE IF NOT EXISTS registrations_by_activity_student (
    activity_id uuid,
    student_id uuid,
    slot_id uuid, // 00000000-0000-0000-0000-000000000000 = whole activity
    registration_id uuid,
    status text,
    registered_at timestamp,
    PRIMARY KEY ((activity_id), student_id, slot_id)
);

// Personal-QR check-in path: staff scans the volunteer's checkin_token and
// lands straight on the registration (per-session staff QR is section 7).
CREATE TABLE IF NOT EXISTS registrations_by_token (
    checkin_token uuid PRIMARY KEY,
    registration_id uuid,
    activity_id uuid,
    student_id uuid,
    slot_id uuid,
    status text
);

CREATE TABLE IF NOT EXISTS registration_status_history (
    registration_id uuid,
    changed_at timestamp,
    history_id uuid,
    from_status text,
    to_status text,
    changed_by uuid,
    note text,
    PRIMARY KEY ((registration_id), changed_at, history_id)
) WITH CLUSTERING ORDER BY (changed_at DESC, history_id ASC);

CREATE TABLE IF NOT EXISTS registration_forms (
    activity_id uuid,
    position int,
    question_id uuid,
    label text,
    field_type text, // text | choice | file | consent
    required boolean,
    PRIMARY KEY ((activity_id), position, question_id)
);

CREATE TABLE IF NOT EXISTS waitlist_entries (
    activity_id uuid,
    joined_at timestamp,
    waitlist_id uuid,
    student_id uuid,
    slot_id uuid,
    status text, // waiting | promoted | expired
    promoted_at timestamp,
    PRIMARY KEY ((activity_id), joined_at, waitlist_id)
) WITH CLUSTERING ORDER BY (joined_at ASC, waitlist_id ASC);

// -----------------------------------------------------------------------------
// 7. QR CHECK-IN & ATTENDANCE (9 tables)
// QR flow is simulated: qr_codes are issued per session, scans are validated
// against expiry/max_uses, every scan is logged, disputes go to appeals.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS attendance_sessions (
    schedule_id uuid,
    session_id uuid,
    title text,
    qr_code text,
    opens_at timestamp,
    closes_at timestamp,
    status text, // scheduled | open | closed
    created_by uuid,
    PRIMARY KEY ((schedule_id), session_id)
);

CREATE TABLE IF NOT EXISTS qr_codes (
    code text PRIMARY KEY,
    session_id uuid,
    schedule_id uuid,
    activity_id uuid,
    expires_at timestamp,
    max_uses int,
    used_count int,
    status text // active | expired | disabled
);

CREATE TABLE IF NOT EXISTS qr_scan_logs (
    qr_code text,
    scanned_at timestamp,
    log_id uuid,
    student_id uuid,
    result text, // accepted | duplicate | expired | invalid
    device_info text,
    PRIMARY KEY ((qr_code), scanned_at, log_id)
) WITH CLUSTERING ORDER BY (scanned_at DESC, log_id ASC);

CREATE TABLE IF NOT EXISTS attendance_records (
    record_id uuid PRIMARY KEY,
    session_id uuid,
    schedule_id uuid,
    activity_id uuid,
    student_id uuid,
    method text, // qr | manual
    scanned_at timestamp,
    verified_by uuid,
    checked_out_at timestamp, // optional check-out for actual-hours credit
    check_out_method text,
    actual_hours double // staff-set or derived from in/out; overrides hours_awarded
);

// One attendance record per registration (relational UNIQUE(registration_id)).
CREATE TABLE IF NOT EXISTS attendance_by_registration (
    registration_id uuid PRIMARY KEY,
    record_id uuid,
    activity_id uuid,
    student_id uuid,
    session_id uuid,
    scanned_at timestamp
);

CREATE TABLE IF NOT EXISTS attendance_by_activity (
    activity_id uuid,
    scanned_at timestamp,
    record_id uuid,
    student_id uuid,
    session_id uuid,
    method text,
    PRIMARY KEY ((activity_id), scanned_at, record_id)
) WITH CLUSTERING ORDER BY (scanned_at DESC, record_id ASC);

CREATE TABLE IF NOT EXISTS attendance_by_student (
    student_id uuid,
    scanned_at timestamp,
    record_id uuid,
    activity_id uuid,
    session_id uuid,
    method text,
    PRIMARY KEY ((student_id), scanned_at, record_id)
) WITH CLUSTERING ORDER BY (scanned_at DESC, record_id ASC);

CREATE TABLE IF NOT EXISTS attendance_appeals (
    activity_id uuid,
    student_id uuid,
    appeal_id uuid,
    record_id uuid,
    reason text,
    status text, // pending | approved | rejected
    resolved_by uuid,
    resolved_at timestamp,
    created_at timestamp,
    PRIMARY KEY ((activity_id), student_id, appeal_id)
);

CREATE TABLE IF NOT EXISTS attendance_summaries (
    registration_id uuid PRIMARY KEY,
    activity_id uuid,
    student_id uuid,
    sessions_total int,
    sessions_attended int,
    minutes_attended int,
    status text, // incomplete | complete
    updated_at timestamp
);

// -----------------------------------------------------------------------------
// 8. VOLUNTEER HOURS (8 tables)
// Hours are append-only ledger entries; summaries are maintained per term.
// 'attendance' rows are written on attendance completion; 'manual' and
// 'adjustment' rows let staff add or correct hours through the approval
// workflow (pending_hours_by_org is the staff queue).
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS volunteer_hour_ledger (
    entry_id uuid PRIMARY KEY,
    student_id uuid,
    activity_id uuid,
    source text, // attendance | manual | adjustment
    hours double,
    term text, // e.g. '2026-H1'
    registration_id uuid, // link back to the attended registration
    status text, // pending | approved | rejected
    approved_by uuid,
    approved_at timestamp,
    recorded_at timestamp,
    recorded_by uuid,
    note text
);

CREATE TABLE IF NOT EXISTS hours_by_student (
    student_id uuid,
    term text,
    total_hours double,
    activities_count int,
    updated_at timestamp,
    PRIMARY KEY ((student_id), term)
);

// Student-facing ledger history, newest first (source-of-truth ledger is
// keyed by entry_id only, so this feed keeps reads partition-local).
CREATE TABLE IF NOT EXISTS hour_entries_by_student (
    student_id uuid,
    recorded_at timestamp,
    entry_id uuid,
    activity_id uuid,
    hours double,
    source text,
    status text,
    PRIMARY KEY ((student_id), recorded_at, entry_id)
) WITH CLUSTERING ORDER BY (recorded_at DESC, entry_id ASC);

// Per-activity hours feed for event reports and dashboards.
CREATE TABLE IF NOT EXISTS hours_by_activity (
    activity_id uuid,
    recorded_at timestamp,
    entry_id uuid,
    student_id uuid,
    hours double,
    status text,
    PRIMARY KEY ((activity_id), recorded_at, entry_id)
) WITH CLUSTERING ORDER BY (recorded_at DESC, entry_id ASC);

// Staff approval queue: pending entries per org, oldest first. Rows are
// deleted when the ledger entry gets approved or rejected.
CREATE TABLE IF NOT EXISTS pending_hours_by_org (
    org_id uuid,
    recorded_at timestamp,
    entry_id uuid,
    student_id uuid,
    activity_id uuid,
    hours double,
    PRIMARY KEY ((org_id), recorded_at, entry_id)
) WITH CLUSTERING ORDER BY (recorded_at ASC, entry_id ASC);

CREATE TABLE IF NOT EXISTS hour_adjustments (
    adjustment_id uuid PRIMARY KEY,
    student_id uuid,
    activity_id uuid,
    delta_hours double,
    reason text,
    created_by uuid,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS hour_rules (
    rule_id uuid PRIMARY KEY,
    org_id uuid,
    category_id uuid,
    multiplier double,
    cap_hours double,
    term text,
    is_active boolean
);

// Term leaderboard, top hours first. A student's row moves when the
// approved total changes: delete the old-total clustering row, insert
// the new one. term='all' keeps the all-time board beside term boards.
CREATE TABLE IF NOT EXISTS leaderboard_by_term (
    term text,
    total_hours double,
    student_id uuid,
    student_name text,
    updated_at timestamp,
    PRIMARY KEY ((term), total_hours, student_id)
) WITH CLUSTERING ORDER BY (total_hours DESC, student_id ASC);

// Distinct term list for leaderboard filters — one row per known term.
CREATE TABLE IF NOT EXISTS leaderboard_terms (
    term text PRIMARY KEY
);

// -----------------------------------------------------------------------------
// 9. CERTIFICATES (5 tables)
// One certificate per (activity, student). PDFs are stored as media_assets.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS certificate_templates (
    template_id uuid PRIMARY KEY,
    org_id uuid,
    name text,
    background_media_id uuid,
    layout_json text,
    is_active boolean,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS certificates (
    activity_id uuid,
    student_id uuid,
    certificate_id uuid,
    registration_id uuid, // the completed registration this cert rewards
    template_id uuid,
    serial_no text,
    issued_at timestamp,
    issued_by uuid,
    file_media_id uuid,
    status text, // issued | revoked
    PRIMARY KEY ((activity_id), student_id)
);

CREATE TABLE IF NOT EXISTS certificates_by_student (
    student_id uuid,
    issued_at timestamp,
    certificate_id uuid,
    activity_id uuid,
    serial_no text,
    status text,
    PRIMARY KEY ((student_id), issued_at, certificate_id)
) WITH CLUSTERING ORDER BY (issued_at DESC, certificate_id ASC);

// Public verification by the human-readable serial printed on the PDF.
CREATE TABLE IF NOT EXISTS certificates_by_serial (
    serial_no text PRIMARY KEY,
    certificate_id uuid,
    activity_id uuid,
    student_id uuid,
    status text
);

CREATE TABLE IF NOT EXISTS certificate_revocations (
    revocation_id uuid PRIMARY KEY,
    certificate_id uuid,
    activity_id uuid,
    student_id uuid,
    reason text,
    revoked_by uuid,
    revoked_at timestamp
);

// -----------------------------------------------------------------------------
// 10. MEDIA & IMAGES (6 tables)
// Binary files live in object storage; ScyllaDB stores metadata + references.
// Moderation is an append-only review history; latest row = current status.
// media_assets doubles as the central file registry: upload_status tracks
// the async upload flow ('pending' while the presigned upload is open,
// 'active' once confirmed), media_by_hash dedups by content checksum.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS media_assets (
    asset_id uuid PRIMARY KEY,
    owner_id uuid,
    owner_type text, // user | activity | certificate | announcement
    file_url text,
    file_hash text,
    mime text,
    width int,
    height int,
    size_bytes bigint,
    role text, // gallery | cover | logo (one cover and one logo per owner)
    // Central file-registry fields from the relational design (deployed
    // keyspaces: ALTER TABLE media_assets ADD uploader_id uuid,
    // ADD storage_key text, ADD backend text, ADD original_name text,
    // ADD visibility text, ADD upload_status text, ADD metadata_json text,
    // ADD thumb_url text, ADD updated_at timestamp, ADD deleted_at timestamp).
    uploader_id uuid,
    storage_key text, // object key inside the backend; globally unique
    backend text, // local | s3 | gcs
    original_name text,
    visibility text, // private | organization | public
    upload_status text, // pending | active | failed | deleted
    metadata_json text, // per-file attributes (page count, scan result...)
    thumb_url text, // generated thumbnail/poster derivative
    created_at timestamp,
    updated_at timestamp,
    deleted_at timestamp
);

CREATE TABLE IF NOT EXISTS media_by_owner (
    owner_id uuid,
    created_at timestamp,
    asset_id uuid,
    file_url text,
    mime text,
    owner_type text,
    PRIMARY KEY ((owner_id), created_at, asset_id)
) WITH CLUSTERING ORDER BY (created_at DESC, asset_id ASC);

// Dedup + integrity: identical uploads reuse one asset (LWT-claimed).
CREATE TABLE IF NOT EXISTS media_by_hash (
    file_hash text PRIMARY KEY,
    asset_id uuid
);

CREATE TABLE IF NOT EXISTS media_by_uploader (
    uploader_id uuid,
    created_at timestamp,
    asset_id uuid,
    file_url text,
    mime text,
    owner_type text,
    PRIMARY KEY ((uploader_id), created_at, asset_id)
) WITH CLUSTERING ORDER BY (created_at DESC, asset_id ASC);

CREATE TABLE IF NOT EXISTS activity_media (
    activity_id uuid,
    position int,
    asset_id uuid,
    role text, // cover | gallery | document
    caption text,
    PRIMARY KEY ((activity_id), position, asset_id)
);

CREATE TABLE IF NOT EXISTS media_moderation (
    status text,
    created_at timestamp,
    moderation_id uuid,
    asset_id uuid,
    reviewed_by uuid,
    note text,
    PRIMARY KEY ((status), created_at, moderation_id)
) WITH CLUSTERING ORDER BY (created_at DESC, moderation_id ASC);

// -----------------------------------------------------------------------------
// 11. NOTIFICATIONS (3 tables)
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS notifications (
    notification_id uuid PRIMARY KEY,
    user_id uuid,
    type text, // registration | attendance | certificate | announcement
    title text,
    body text,
    data_json text,
    channel text, // inapp | email
    status text, // unread | read
    read_at timestamp,
    created_at timestamp
);

CREATE TABLE IF NOT EXISTS notifications_by_user (
    user_id uuid,
    created_at timestamp,
    notification_id uuid,
    title text,
    status text,
    PRIMARY KEY ((user_id), created_at, notification_id)
) WITH CLUSTERING ORDER BY (created_at DESC, notification_id ASC);

CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id uuid PRIMARY KEY,
    channels map<text, boolean>,
    muted_types set<text>,
    updated_at timestamp
);

// -----------------------------------------------------------------------------
// 12. REPORTS, STATISTICS & EXPORTS (4 tables)
// Pre-aggregated stats keep dashboards fast; exports run as async jobs.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS report_snapshots (
    org_id uuid,
    created_at timestamp,
    snapshot_id uuid,
    report_type text, // activity_summary | hours_leaderboard | participation
    period_start timestamp,
    period_end timestamp,
    payload_json text,
    created_by uuid,
    PRIMARY KEY ((org_id), created_at, snapshot_id)
) WITH CLUSTERING ORDER BY (created_at DESC, snapshot_id ASC);

CREATE TABLE IF NOT EXISTS activity_daily_stats (
    activity_id uuid,
    day date,
    registrations int,
    attendees int,
    hours_awarded double,
    PRIMARY KEY ((activity_id), day)
) WITH CLUSTERING ORDER BY (day DESC);

CREATE TABLE IF NOT EXISTS org_monthly_stats (
    org_id uuid,
    month text, // e.g. '2026-10'
    activities int,
    participants int,
    hours double,
    certificates int,
    PRIMARY KEY ((org_id), month)
) WITH CLUSTERING ORDER BY (month DESC);

CREATE TABLE IF NOT EXISTS export_jobs (
    requested_by uuid,
    created_at timestamp,
    job_id uuid,
    org_id uuid,
    job_type text, // certificates_pdf | roster_csv | stats_xlsx
    status text, // queued | running | done | failed
    file_url text,
    error text,
    finished_at timestamp,
    PRIMARY KEY ((requested_by), created_at, job_id)
) WITH CLUSTERING ORDER BY (created_at DESC, job_id ASC);

// -----------------------------------------------------------------------------
// 13. REVIEWS & FEEDBACK (2 tables)
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reviews_by_activity (
    activity_id uuid,
    created_at timestamp,
    review_id uuid,
    student_id uuid,
    rating int,
    comment text,
    PRIMARY KEY ((activity_id), created_at, review_id)
) WITH CLUSTERING ORDER BY (created_at DESC, review_id ASC);

CREATE TABLE IF NOT EXISTS reviews_by_student (
    student_id uuid,
    created_at timestamp,
    review_id uuid,
    activity_id uuid,
    rating int,
    PRIMARY KEY ((student_id), created_at, review_id)
) WITH CLUSTERING ORDER BY (created_at DESC, review_id ASC);

// -----------------------------------------------------------------------------
// 14. DURABILITY — REPLACES TYPICAL RAM STATE (3 tables)
// Nothing authoritative lives in process memory. Retries deduplicate by key,
// rate limits accumulate in counter buckets, background jobs take DB leases.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key text PRIMARY KEY, // client-supplied idempotency key (hash)
    user_id uuid,
    status text, // in_progress | completed | failed
    response_json text, // stored response for safe replay
    created_at timestamp,
    expires_at timestamp
);

CREATE TABLE IF NOT EXISTS auth_rate_limits (
    bucket text, // e.g. 'login:192.0.2.10', 'refresh:<user_id>', 'edge:<ip>'
    window_start timestamp, // fixed window start (e.g. per minute)
    hits counter,
    PRIMARY KEY ((bucket), window_start)
);

CREATE TABLE IF NOT EXISTS job_leases (
    job_id uuid PRIMARY KEY,
    owner text, // worker identity holding the lease
    status text, // free | held | done
    acquired_at timestamp,
    expires_at timestamp // acquire with LWT: IF status = 'free' OR expired
);

// -----------------------------------------------------------------------------
// 15. REALTIME — WEBSOCKET HANDSHAKE TICKETS (1 table)
// One-time tickets bridge REST auth and the WS handshake (AGENTS.md §16):
// browsers cannot set Authorization on the WS upgrade, so clients call
// POST /ws/tickets then open /ws?ticket=<token>. Only the SHA-256 hash is
// stored; rows self-expire via TTL and are consumed with DELETE IF EXISTS.
// -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ws_tickets (
    ticket_hash text PRIMARY KEY,
    user_id uuid,
    expires_at timestamp,
    created_at timestamp
) WITH default_time_to_live = 300;

// -----------------------------------------------------------------------------
// 16. ORG FEED & CHAT (13 tables)
// The member workspace: org-scoped posts (announcement | discussion) with
// pins, media links and flat comments, plus one org-wide chat room. Ids are
// UUIDv7 so clustering by the id itself gives time order; that makes the
// entity id the pagination cursor on every feed.
// -----------------------------------------------------------------------------

// Canonical post row; single-partition lookups for detail/edit/delete.
// Articles: blocks_json holds the typed block list (paragraph, heading,
// quote, list, image, video, divider; media blocks carry asset ids only),
// body is its plain-text projection. status is the publish state; trash
// is the orthogonal deleted_at stamp so restore returns to that state.
// revision_of links a private draft to the live post it replaces on
// publish (parallel-draft editing: the published version stays up while
// the author stages edits).
// (deployed keyspaces: ALTER TABLE org_posts ADD blocks_json text,
//  ADD cover_media_id uuid, ADD published_at timestamp,
//  ADD deleted_at timestamp, ADD revision_of uuid, ADD visibility text)
CREATE TABLE IF NOT EXISTS org_posts (
    post_id uuid PRIMARY KEY,
    org_id uuid,
    author_id uuid,
    kind text, // announcement | discussion (post type, not the audience)
    title text,
    body text,
    blocks_json text,
    cover_media_id uuid,
    status text, // active (published) | draft
    visibility text, // public | members; NULL derives from kind
    revision_of uuid, // draft staging edits for a live post
    pinned_at timestamp,
    edited_at timestamp,
    published_at timestamp,
    deleted_at timestamp, // set = in the trash (soft delete)
    created_at timestamp,
    updated_at timestamp
);

// One author's unpublished drafts inside one org, newest first. Drafts
// never touch org_posts_feed, so the board and its realtime fan-out stay
// silent until publish.
CREATE TABLE IF NOT EXISTS org_post_drafts (
    org_id uuid,
    author_id uuid,
    post_id uuid,
    PRIMARY KEY ((org_id, author_id), post_id)
) WITH CLUSTERING ORDER BY (post_id DESC);

// Soft-deleted posts of one org (the trash bin), newest post first.
// author_id lets authors list only their own rows; status is the publish
// state at delete time so managers can skip trashed drafts (and page
// totals) without loading the canonical rows.
// (deployed keyspaces: ALTER TABLE org_posts_trash ADD status text)
CREATE TABLE IF NOT EXISTS org_posts_trash (
    org_id uuid,
    post_id uuid,
    author_id uuid,
    status text,
    PRIMARY KEY ((org_id), post_id)
) WITH CLUSTERING ORDER BY (post_id DESC);

// Org board, newest first. Rows join back to org_posts at read time;
// post_id IS the cursor (uuid7 ordering, no timestamp ties). kind and
// visibility are denormalized for filtered page windows and totals.
// (deployed keyspaces: ALTER TABLE org_posts_feed ADD kind text,
//  ADD visibility text)
CREATE TABLE IF NOT EXISTS org_posts_feed (
    org_id uuid,
    post_id uuid,
    kind text,
    visibility text, // public | members; NULL derives from kind
    PRIMARY KEY ((org_id), post_id)
) WITH CLUSTERING ORDER BY (post_id DESC);

// Global public post timeline, newest first. One literal 'all' bucket
// partitions every published public-visibility post so a single bounded
// read serves the guest feed; rows join back to org_posts at read time
// (dead rows are skipped lazily, same as org_posts_feed drift).
// (deployed keyspaces: CREATE TABLE announcements_feed (...); backfill
//  one row per org_posts_feed row where kind = 'announcement'; after the
//  visibility column, also drop rows whose visibility = 'members')
CREATE TABLE IF NOT EXISTS announcements_feed (
    bucket  text,
    post_id uuid,
    org_id  uuid,
    PRIMARY KEY ((bucket), post_id)
) WITH CLUSTERING ORDER BY (post_id DESC);

// Pinned posts of one org, newest post first. Unpin deletes the row;
// ordering by post age (not pin time) keeps stale pins below fresh ones.
CREATE TABLE IF NOT EXISTS org_posts_pinned (
    org_id uuid,
    post_id uuid,
    PRIMARY KEY ((org_id), post_id)
) WITH CLUSTERING ORDER BY (post_id DESC);

// Gallery attachments per post; the asset itself stays owned by the org.
CREATE TABLE IF NOT EXISTS org_post_media (
    post_id uuid,
    position int,
    asset_id uuid,
    PRIMARY KEY ((post_id), position, asset_id)
) WITH CLUSTERING ORDER BY (position ASC, asset_id ASC);

// Flat comment thread of one post, oldest first (uuid7 order).
CREATE TABLE IF NOT EXISTS org_post_comments (
    post_id uuid,
    comment_id uuid,
    author_id uuid,
    body text,
    created_at timestamp,
    PRIMARY KEY ((post_id), comment_id)
) WITH CLUSTERING ORDER BY (comment_id ASC);

// Atomic comment totals; counter column, so no cqlengine model and no
// row deletes (TRUNCATE only in tests, per the counter-table rule).
CREATE TABLE IF NOT EXISTS org_post_comment_counts (
    post_id uuid PRIMARY KEY,
    comments counter
);

// Chat rooms. A room id is either the org id (general room), an activity
// id (activity room), or a generated dm room id; the service resolves the
// kind by lookup. Monthly bucket keeps each partition bounded;
// message_id (uuid7) is both order and cursor.
CREATE TABLE IF NOT EXISTS org_room_messages (
    room_id uuid,
    bucket text, // 'YYYYMM' of created_at
    message_id uuid,
    author_id uuid,
    body text,
    created_at timestamp,
    PRIMARY KEY ((room_id, bucket), message_id)
) WITH CLUSTERING ORDER BY (message_id ASC);

// Per-member read pointer per room; unread = messages after the pointer.
CREATE TABLE IF NOT EXISTS org_room_reads (
    room_id uuid,
    user_id uuid,
    last_read_message_id uuid,
    last_read_at timestamp,
    PRIMARY KEY ((room_id), user_id)
);

// Canonical dm pair -> room. user_lo < user_hi keeps exactly one row per
// pair; creation races resolve through IF NOT EXISTS on this partition.
CREATE TABLE IF NOT EXISTS org_dm_pairs (
    org_id uuid,
    user_lo uuid,
    user_hi uuid,
    room_id uuid,
    created_at timestamp,
    PRIMARY KEY ((org_id), user_lo, user_hi)
);

// Each participant's dm inbox; the row doubles as the room lookup the
// chat service uses to prove membership for chat:{room_id} ACL checks.
CREATE TABLE IF NOT EXISTS org_dm_rooms (
    user_id uuid,
    room_id uuid,
    org_id uuid,
    peer_id uuid,
    created_at timestamp,
    PRIMARY KEY ((user_id), room_id)
);
