-- =============================================================================
-- AmigoACT — PostgreSQL schema (volunteer & extracurricular activity management)
-- File: schema.sql   (chuyển đổi từ amigoact-be/schemas.cql của ScyllaDB)
-- Yêu cầu: PostgreSQL 14+ (extension: citext, pg_trgm)
--
-- NGUYÊN TẮC CHUYỂN ĐỔI
-- ---------------------
-- 1. ScyllaDB là "query-first": mỗi truy vấn có một bảng riêng (xxx_by_yyy).
--    PostgreSQL là quan hệ: chỉ giữ bảng GỐC, các bảng truy vấn được thay bằng
--    INDEX (thường là partial index) hoặc VIEW. Không còn ghi trùng nhiều bảng.
-- 2. Khóa chính vẫn là uuid sinh ở phía ứng dụng (UUIDv7). uuid v7 sắp xếp theo
--    thời gian nên message_id / post_id / comment_id vẫn dùng làm cursor phân trang.
--    (PostgreSQL 18 có sẵn uuidv7() nếu muốn DEFAULT phía DB.)
-- 3. Kiểu dữ liệu:
--      timestamp -> timestamptz | double (giờ) -> numeric | decimal -> numeric
--      set<text>/list<text> -> text[] | map<text,boolean> -> jsonb
--      cột *_json (text chứa JSON) -> jsonb (GIỮ NGUYÊN TÊN cột để dễ ánh xạ ORM)
--      cột "enum bằng text" -> text + CHECK (dễ ALTER hơn CREATE TYPE)
-- 4. LWT (IF NOT EXISTS / IF ...) -> UNIQUE index + INSERT ... ON CONFLICT hoặc
--    UPDATE có điều kiện (ví dụ UPDATE qr_codes SET used_count = used_count + 1
--    WHERE code = $1 AND used_count < max_uses RETURNING ...). Không dùng khóa trong RAM.
-- 5. Counter (auth_rate_limits.hits, org_post_comment_counts) -> cột int thường,
--    tăng bằng INSERT ... ON CONFLICT DO UPDATE SET hits = hits + 1; số comment
--    dùng COUNT(*) theo index (post_id, comment_id).
-- 6. TTL của Scylla (ws_tickets, idempotency_keys, org_chat_timeouts) -> cột
--    expires_at + hàm purge_expired() ở cuối file (gọi bằng pg_cron hoặc job lease).
-- 7. Secondary index (hour_rules, certificate_templates) -> index thường.
-- 8. Có thêm khóa ngoại (FK) và CHECK để DB tự bảo vệ toàn vẹn (Scylla không có).
--    Cột "đa hình" (room_id, resource_id, owner_id) cố ý KHÔNG có FK.
-- 9. Giữ nguyên PERSISTENCE POLICY: DB là nguồn sự thật duy nhất, các bảng
--    idempotency_keys / auth_rate_limits / job_leases / ws_tickets vẫn nằm trong DB.
--
-- BẢNG SCYLLA ĐÃ ĐƯỢC GỘP / THAY BẰNG INDEX HOẶC VIEW (114 -> 87 bảng + 4 view)
-- ---------------------------------------------------------------------------
--   users_by_email, users_by_phone                  -> UNIQUE trên users
--   refresh_tokens_by_user, refresh_tokens_by_family-> index trên auth_refresh_tokens
--   organizations_by_slug / _by_tax_code            -> UNIQUE trên organizations
--   organizations_by_legal_status / organizations_public -> index trên organizations
--   members_by_user                                 -> index trên organization_members
--   campuses_by_org, departments_by_campus/_by_org  -> index trên campuses/departments
--   roles_by_org, roles_by_user, platform_role_roster, user_activity_roles,
--   api_keys_by_org, access_audit_by_resource       -> index trên bảng gốc
--   student_profiles_by_code, users_by_skill        -> index trên bảng gốc
--   activities_by_org/_by_status/_by_category/_by_slug, activities_trash_by_org,
--   activities_by_tag, tags_by_org, activity_tags_by_org,
--   trashed_tag_edges_by_org, public_tag_directory  -> tags + activity_tags + index/view
--   tags_by_user, post_tags_by_user, user_post_tag_sets,
--   activity_tags_by_user, user_activity_tag_sets   -> user_tags + post_user_tags + activity_user_tags
--   schedules_by_activity, partner_activities_by_org-> index
--   registrations_by_activity/_by_student/_by_activity_student/_by_token -> index/UNIQUE
--   attendance_by_registration/_by_activity/_by_student -> UNIQUE/index trên attendance_records
--   hour_entries_by_student, hours_by_activity, pending_hours_by_org -> index trên ledger
--   leaderboard_by_term, leaderboard_terms          -> VIEW
--   certificates_by_student/_by_serial/_by_id       -> UNIQUE/index trên certificates
--   media_by_owner/_by_hash/_by_uploader            -> index/UNIQUE trên media_assets
--   notifications_by_user                           -> index
--   reviews_by_activity + reviews_by_student        -> reviews
--   org_posts_feed/_trash/_pinned/announcements_feed/org_post_drafts -> partial index trên org_posts
--   trashed_post_tag_edges_by_org                   -> không cần (xóa mềm tag giữ nguyên cạnh)
--   org_room_media_by_author, org_room_media_authors-> index trên org_room_media
--   org_dm_rooms                                    -> VIEW trên org_dm_pairs
--   org_chat_channels_by_id, org_chat_room_threads, org_chat_channel_names,
--   org_chat_channel_memberships                    -> index/UNIQUE trên bảng gốc
--
-- Thứ tự mục giữ theo bản gốc; riêng media_assets đặt ở mục 1B để tránh FK vòng.
-- Phân vùng (PARTITION BY RANGE) cho access_audit_logs, org_room_messages,
-- qr_scan_logs là tùy chọn khi dữ liệu lớn; chưa bật để giữ schema đơn giản.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Tự cập nhật updated_at (gắn trigger tự động ở cuối file).
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- 1. AUTH & IDENTITY
-- JWT access (stateless) + refresh token opaque (lưu hash SHA-256).
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id                  uuid PRIMARY KEY,
    email               citext NOT NULL,
    phone               text,
    password_hash       text,
    full_name           text NOT NULL,
    account_type        text NOT NULL DEFAULT 'individual'
                        CHECK (account_type IN ('individual', 'business')),
    tax_code            text,
    company_name        text,
    legal_rep_name      text,
    legal_rep_id        text,
    legal_rep_position  text,
    date_of_birth       date,
    gender              text CHECK (gender IN ('male', 'female', 'other', 'unspecified')),
    address             text,
    avatar_media_id     uuid,                       -- FK thêm sau media_assets
    last_login_at       timestamptz,
    last_seen_at        timestamptz,                -- presence (socket connect/disconnect)
    email_verified_at   timestamptz,
    status              text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'suspended', 'deleted')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_email_uq UNIQUE (email),       -- thay users_by_email
    CONSTRAINT users_phone_uq UNIQUE (phone)        -- thay users_by_phone
);

-- Gộp auth_refresh_tokens + refresh_tokens_by_user + refresh_tokens_by_family.
CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
    token_hash    text PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id     uuid NOT NULL,
    expires_at    timestamptz NOT NULL,
    revoked_at    timestamptz,
    rotated_from  text REFERENCES auth_refresh_tokens(token_hash) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_refresh_tokens_user_idx   ON auth_refresh_tokens (user_id);
CREATE INDEX IF NOT EXISTS auth_refresh_tokens_family_idx ON auth_refresh_tokens (family_id);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id    uuid PRIMARY KEY,
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    device_label  text,
    user_agent    text,
    ip            text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz,
    expires_at    timestamptz,
    revoked_at    timestamptz                       -- revoked thắng expired
);
CREATE INDEX IF NOT EXISTS auth_sessions_user_idx ON auth_sessions (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS password_resets (
    token_hash  text PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz
);
CREATE INDEX IF NOT EXISTS password_resets_user_idx ON password_resets (user_id);

CREATE TABLE IF NOT EXISTS email_verifications (
    token_hash   text PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email        citext NOT NULL,
    expires_at   timestamptz NOT NULL,
    verified_at  timestamptz
);
CREATE INDEX IF NOT EXISTS email_verifications_user_idx ON email_verifications (user_id);

-- -----------------------------------------------------------------------------
-- 1B. MEDIA ASSETS (đặt sớm vì nhiều bảng tham chiếu)
-- File nhị phân nằm ở object storage; DB giữ metadata + tham chiếu.
-- media_assets là "file registry" trung tâm; file_hash UNIQUE = dedup nội dung.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS media_assets (
    asset_id       uuid PRIMARY KEY,
    owner_id       uuid,                            -- đa hình theo owner_type, không FK
    owner_type     text NOT NULL
                   CHECK (owner_type IN ('organization', 'chat', 'post', 'user', 'activity', 'certificate')),
    file_url       text,
    file_hash      text,
    mime           text,
    width          int,
    height         int,
    size_bytes     bigint,
    role           text,                            -- org: gallery | cover | logo; còn lại: attachment
    uploader_id    uuid REFERENCES users(id) ON DELETE SET NULL,
    storage_key    text,                            -- object key trong backend, duy nhất toàn cục
    backend        text CHECK (backend IN ('local', 's3', 'gcs')),
    original_name  text,
    visibility     text NOT NULL DEFAULT 'private'
                   CHECK (visibility IN ('private', 'organization', 'public')),
    upload_status  text NOT NULL DEFAULT 'pending'
                   CHECK (upload_status IN ('pending', 'active', 'failed', 'deleted')),
    metadata_json  jsonb,
    thumb_url      text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    deleted_at     timestamptz,
    CONSTRAINT media_assets_file_hash_uq   UNIQUE (file_hash),     -- thay media_by_hash
    CONSTRAINT media_assets_storage_key_uq UNIQUE (storage_key)
);
CREATE INDEX IF NOT EXISTS media_assets_owner_idx    ON media_assets (owner_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS media_assets_uploader_idx ON media_assets (uploader_id, created_at DESC) WHERE deleted_at IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_avatar_media_fk') THEN
        ALTER TABLE users
            ADD CONSTRAINT users_avatar_media_fk
            FOREIGN KEY (avatar_media_id) REFERENCES media_assets(asset_id) ON DELETE SET NULL;
    END IF;
END $$;

-- Lịch sử kiểm duyệt (append-only); dòng mới nhất = trạng thái hiện tại.
CREATE TABLE IF NOT EXISTS media_moderation (
    moderation_id  uuid PRIMARY KEY,
    asset_id       uuid NOT NULL REFERENCES media_assets(asset_id) ON DELETE CASCADE,
    status         text NOT NULL,
    reviewed_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    note           text,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS media_moderation_status_idx ON media_moderation (status, created_at DESC);
CREATE INDEX IF NOT EXISTS media_moderation_asset_idx  ON media_moderation (asset_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- 2. ORGANIZATIONS & MULTI-TENANCY
-- organization -> campus -> department. Mọi dòng nghiệp vụ mang org_id.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS organizations (
    id                  uuid PRIMARY KEY,
    name                text NOT NULL,
    slug                citext NOT NULL,
    description         text,
    org_type            text NOT NULL DEFAULT 'organization'
                        CHECK (org_type IN ('organization', 'club', 'group', 'business')),
    status              text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'suspended')),
    join_policy         text NOT NULL DEFAULT 'invite'
                        CHECK (join_policy IN ('invite', 'open')),
    owner_id            uuid NOT NULL REFERENCES users(id),
    tax_code            text,
    legal_rep_name      text,
    legal_rep_id        text,
    legal_rep_position  text,
    legal_status        text NOT NULL DEFAULT 'none'
                        CHECK (legal_status IN ('none', 'pending', 'verified')),
    email               text,
    phone               text,
    website             text,
    address             text,
    city                text,
    country             text,
    legal_name          text,                       -- tên đăng ký trên giấy phép
    license_number      text,
    is_personal         boolean NOT NULL DEFAULT false,  -- org cộng đồng cá nhân tự tạo
    logo_media_id       uuid REFERENCES media_assets(asset_id) ON DELETE SET NULL,
    cover_media_id      uuid REFERENCES media_assets(asset_id) ON DELETE SET NULL,
    verified_at         timestamptz,
    verified_by         uuid REFERENCES users(id) ON DELETE SET NULL,
    previous_slug       text,                       -- slug bị nhả khi xóa mềm; lấy lại khi restore
    deleted_at          timestamptz,                -- NULL = còn sống
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT organizations_slug_uq UNIQUE (slug)  -- thay organizations_by_slug
);
-- Mỗi tax_code chỉ có một org đã xác minh (thay organizations_by_tax_code + LWT).
CREATE UNIQUE INDEX IF NOT EXISTS organizations_tax_code_verified_uq
    ON organizations (tax_code)
    WHERE legal_status = 'verified' AND deleted_at IS NULL;
-- Hàng đợi xác minh của platform admin, cũ nhất trước (thay organizations_by_legal_status).
CREATE INDEX IF NOT EXISTS organizations_legal_queue_idx
    ON organizations (legal_status, created_at ASC) WHERE deleted_at IS NULL;
-- Danh bạ công khai theo loại, mới nhất trước (thay organizations_public).
CREATE INDEX IF NOT EXISTS organizations_public_idx
    ON organizations (org_type, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS organizations_owner_idx ON organizations (owner_id);
CREATE INDEX IF NOT EXISTS organizations_name_trgm_idx ON organizations USING gin (name gin_trgm_ops);

-- Bảng tra loại tổ chức (dữ liệu, không phải enum cứng).
CREATE TABLE IF NOT EXISTS org_types (
    code        text PRIMARY KEY,
    name        text NOT NULL,
    sort_order  int NOT NULL DEFAULT 0
);
INSERT INTO org_types (code, name, sort_order) VALUES
    ('school',      'School',       10),
    ('youth_union', 'Youth Union',  20),
    ('ngo',         'NGO',          30),
    ('nonprofit',   'Nonprofit',    40),
    ('business',    'Business',     50),
    ('government', 'Government',    60),
    ('community',   'Community',    70)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS membership_form_settings (
    org_id       uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    title        text,
    description  text
);

CREATE TABLE IF NOT EXISTS membership_forms (
    question_id    uuid PRIMARY KEY,
    org_id         uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    position       int NOT NULL,
    label          text NOT NULL,
    field_type     text NOT NULL CHECK (field_type IN ('text', 'textarea', 'choice', 'consent')),
    required       boolean NOT NULL DEFAULT false,
    options        jsonb,                           -- danh sách lựa chọn, chỉ cho 'choice'
    allow_other    boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS membership_forms_org_idx ON membership_forms (org_id, position);

CREATE TABLE IF NOT EXISTS membership_applications (
    org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    answers       jsonb,                            -- {question_id: answer}
    submitted_at  timestamptz,
    rejected_at   timestamptz,                      -- điều khiển cooldown nộp lại
    PRIMARY KEY (org_id, user_id)
);
CREATE INDEX IF NOT EXISTS membership_applications_user_idx ON membership_applications (user_id);

-- Gộp organization_members + members_by_user.
CREATE TABLE IF NOT EXISTS organization_members (
    org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status      text NOT NULL
                CHECK (status IN ('active', 'applied', 'invited', 'suspended', 'left', 'revoked')),
    invited_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    joined_at   timestamptz,
    PRIMARY KEY (org_id, user_id)
);
CREATE INDEX IF NOT EXISTS organization_members_user_idx   ON organization_members (user_id, status);
CREATE INDEX IF NOT EXISTS organization_members_status_idx ON organization_members (org_id, status);

CREATE TABLE IF NOT EXISTS campuses (
    id          uuid PRIMARY KEY,
    org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        text NOT NULL,
    address     text,
    status      text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS campuses_org_idx ON campuses (org_id);

-- Khoa/phòng ban; campus_id có thể NULL (không gắn campus).
CREATE TABLE IF NOT EXISTS departments (
    id          uuid PRIMARY KEY,
    org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    campus_id   uuid REFERENCES campuses(id) ON DELETE SET NULL,
    name        text NOT NULL,
    code        text,
    status      text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS departments_org_idx    ON departments (org_id);
CREATE INDEX IF NOT EXISTS departments_campus_idx ON departments (campus_id) WHERE campus_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 3. RBAC — PHÂN QUYỀN
-- Kiểm tra quyền = quyền của role + grant trực tiếp + quyền sở hữu.
-- Phạm vi role: platform (platform_user_roles), org (user_roles),
-- activity (activity_user_roles, đặt ở mục 5 vì cần bảng activities).
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS roles (
    id           uuid PRIMARY KEY,
    org_id       uuid REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = role hệ thống
    code         text NOT NULL,                     -- mã máy ổn định, duy nhất theo phạm vi
    name         text NOT NULL,
    description  text,
    is_system    boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    color        text NOT NULL DEFAULT '',          -- '' = mặc định
    position     int NOT NULL DEFAULT 0             -- thâm niên trong org; số lớn hơn cao hơn
);
CREATE UNIQUE INDEX IF NOT EXISTS roles_org_code_uq    ON roles (org_id, code) WHERE org_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS roles_system_code_uq ON roles (code)         WHERE org_id IS NULL;
CREATE INDEX IF NOT EXISTS roles_org_idx ON roles (org_id);

CREATE TABLE IF NOT EXISTS permissions (
    code         text PRIMARY KEY,                  -- ví dụ 'activity:create'
    module       text NOT NULL,
    description  text
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id          uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_code  text NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_code)
);

-- Quyền nền mọi thành viên active của org đều có.
CREATE TABLE IF NOT EXISTS org_member_defaults (
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    permission_code  text NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    PRIMARY KEY (org_id, permission_code)
);

-- Role cấp org (gộp user_roles + roles_by_user).
CREATE TABLE IF NOT EXISTS user_roles (
    org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    granted_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    granted_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz,                        -- ủy quyền tạm thời
    PRIMARY KEY (org_id, user_id, role_id)
);
CREATE INDEX IF NOT EXISTS user_roles_user_idx ON user_roles (user_id, org_id);
CREATE INDEX IF NOT EXISTS user_roles_role_idx ON user_roles (role_id);

-- Role cấp platform (gộp platform_user_roles + platform_role_roster).
CREATE TABLE IF NOT EXISTS platform_user_roles (
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id     uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    granted_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    granted_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz,
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX IF NOT EXISTS platform_user_roles_role_idx ON platform_user_roles (role_id);

CREATE TABLE IF NOT EXISTS user_permission_grants (
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission_code  text NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    reason           text,
    granted_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    granted_at       timestamptz NOT NULL DEFAULT now(),
    expires_at       timestamptz,
    PRIMARY KEY (org_id, user_id, permission_code)
);
CREATE INDEX IF NOT EXISTS user_permission_grants_user_idx ON user_permission_grants (user_id);

-- Gộp api_keys + api_keys_by_org.
CREATE TABLE IF NOT EXISTS api_keys (
    key_id        uuid PRIMARY KEY,
    key_hash      text NOT NULL,
    org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name          text NOT NULL,
    scopes        text[] NOT NULL DEFAULT '{}',
    expires_at    timestamptz,
    revoked_at    timestamptz,
    last_used_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT api_keys_key_hash_uq UNIQUE (key_hash)
);
CREATE INDEX IF NOT EXISTS api_keys_org_idx ON api_keys (org_id);

-- Nhật ký truy cập (append-only). Cố ý KHÔNG có FK: log phải sống lâu hơn dữ liệu gốc.
-- Gộp access_audit_logs + access_audit_by_resource.
CREATE TABLE IF NOT EXISTS access_audit_logs (
    log_id         uuid PRIMARY KEY,
    org_id         uuid,
    occurred_at    timestamptz NOT NULL DEFAULT now(),
    actor_id       uuid,
    action         text NOT NULL,
    resource_type  text,
    resource_id    uuid,
    result         text NOT NULL CHECK (result IN ('allowed', 'denied')),
    ip             text,
    metadata       jsonb
);
CREATE INDEX IF NOT EXISTS access_audit_logs_org_idx      ON access_audit_logs (org_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS access_audit_logs_resource_idx ON access_audit_logs (resource_id, occurred_at DESC)
    WHERE resource_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- 4. STUDENT PROFILES & SKILLS
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS student_profiles (
    user_id          uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    student_code     text,
    campus_id        uuid REFERENCES campuses(id) ON DELETE SET NULL,
    department_id    uuid REFERENCES departments(id) ON DELETE SET NULL,
    class_name       text,
    enrollment_year  int,
    school_name      text,                          -- trường ngoài org thành viên
    bio              text,
    interests        text[] NOT NULL DEFAULT '{}',
    status           text CHECK (status IN ('studying', 'graduated', 'suspended', 'working')),
    total_hours      numeric(9,2) NOT NULL DEFAULT 0,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT student_profiles_code_uq UNIQUE (campus_id, student_code)  -- thay student_profiles_by_code
);

CREATE TABLE IF NOT EXISTS emergency_contacts (
    contact_id  uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        text NOT NULL,
    relation    text,
    phone       text,
    is_primary  boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS emergency_contacts_user_idx ON emergency_contacts (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS emergency_contacts_primary_uq ON emergency_contacts (user_id) WHERE is_primary;

CREATE TABLE IF NOT EXISTS skills (
    id    uuid PRIMARY KEY,
    name  text NOT NULL,
    slug  citext NOT NULL,
    CONSTRAINT skills_slug_uq UNIQUE (slug)         -- thay skills_by_slug
);

CREATE TABLE IF NOT EXISTS user_skills (
    user_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id  uuid NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    level     int NOT NULL CHECK (level BETWEEN 1 AND 5),
    PRIMARY KEY (user_id, skill_id)
);
-- "Ai có first-aid level >= 3?" (thay users_by_skill)
CREATE INDEX IF NOT EXISTS user_skills_by_skill_idx ON user_skills (skill_id, level DESC);

-- -----------------------------------------------------------------------------
-- 5. ACTIVITIES / EVENTS
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS activity_categories (
    id             uuid PRIMARY KEY,
    org_id         uuid REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = danh mục toàn cục
    name           text NOT NULL,
    slug           citext NOT NULL,
    description    text,
    icon           text,
    default_hours  numeric(6,2),
    color          text
);
CREATE UNIQUE INDEX IF NOT EXISTS activity_categories_org_slug_uq    ON activity_categories (org_id, slug) WHERE org_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS activity_categories_global_slug_uq ON activity_categories (slug)         WHERE org_id IS NULL;

CREATE TABLE IF NOT EXISTS activities (
    id                     uuid PRIMARY KEY,
    org_id                 uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    campus_id              uuid REFERENCES campuses(id) ON DELETE SET NULL,
    title                  text NOT NULL,
    description            text,
    category_id            uuid REFERENCES activity_categories(id) ON DELETE SET NULL,
    status                 text NOT NULL DEFAULT 'draft'
                           CHECK (status IN ('draft', 'published', 'ongoing', 'completed', 'cancelled')),
    location               text,
    max_participants       int CHECK (max_participants IS NULL OR max_participants >= 0),
    start_at               timestamptz,
    end_at                 timestamptz,
    hours_awarded          numeric(6,2),
    requirements_json      jsonb,
    cover_media_id         uuid REFERENCES media_assets(asset_id) ON DELETE SET NULL,
    created_by             uuid REFERENCES users(id) ON DELETE SET NULL,
    slug                   citext,
    person_in_charge_id    uuid REFERENCES users(id) ON DELETE SET NULL,  -- người liên hệ tại chỗ
    address                text,
    city                   text,
    latitude               numeric(9,6),
    longitude              numeric(9,6),
    is_remote              boolean NOT NULL DEFAULT false,
    registration_deadline  timestamptz,
    published_at           timestamptz,
    deleted_at             timestamptz,             -- xóa mềm (thùng rác của manager)
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT activities_time_ck CHECK (end_at IS NULL OR start_at IS NULL OR end_at >= start_at)
);
-- Slug duy nhất theo org (thay activities_by_slug + LWT). Giữ cả dòng đã xóa mềm
-- để restore vẫn giữ nguyên URL.
CREATE UNIQUE INDEX IF NOT EXISTS activities_org_slug_uq ON activities (org_id, slug) WHERE slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS activities_org_idx      ON activities (org_id, start_at DESC)      WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS activities_status_idx   ON activities (status, start_at DESC)      WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS activities_category_idx ON activities (category_id, start_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS activities_trash_idx    ON activities (org_id, deleted_at DESC)    WHERE deleted_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS activities_title_trgm_idx ON activities USING gin (title gin_trgm_ops);

-- Danh mục tag theo org; (org_id, slug) là khóa duy nhất. Tên đầu tiên trong org là tên chuẩn.
-- Dùng chung cho tag của activity và của post. Xóa mềm tag = đặt deleted_at,
-- các cạnh activity_tags/post_tags được giữ nguyên nên restore không cần bảng "trashed edges".
CREATE TABLE IF NOT EXISTS tags (
    id          uuid PRIMARY KEY,
    org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    slug        citext NOT NULL,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz,
    CONSTRAINT tags_org_slug_uq UNIQUE (org_id, slug)
);
CREATE INDEX IF NOT EXISTS tags_slug_idx ON tags (slug) WHERE deleted_at IS NULL;

-- Thay public_tag_directory (typeahead công khai /tags).
CREATE OR REPLACE VIEW public_tag_directory AS
    SELECT slug, org_id, name FROM tags WHERE deleted_at IS NULL;

-- Thay activity_tags_by_org + activities_by_tag + trashed_tag_edges_by_org.
CREATE TABLE IF NOT EXISTS activity_tags (
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    tag_id       uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (activity_id, tag_id)
);
CREATE INDEX IF NOT EXISTS activity_tags_tag_idx ON activity_tags (tag_id);

-- Tag cá nhân của người dùng (thay tags_by_user, post_tags_by_user, activity_tags_by_user, user_*_tag_sets).
CREATE TABLE IF NOT EXISTS user_tags (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slug        citext NOT NULL,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_tags_user_slug_uq UNIQUE (user_id, slug)
);

CREATE TABLE IF NOT EXISTS activity_user_tags (
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    user_tag_id  uuid NOT NULL REFERENCES user_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (activity_id, user_tag_id)
);
CREATE INDEX IF NOT EXISTS activity_user_tags_tag_idx ON activity_user_tags (user_tag_id);

CREATE TABLE IF NOT EXISTS activity_skills (
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    skill_id     uuid NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    is_required  boolean NOT NULL DEFAULT false,
    PRIMARY KEY (activity_id, skill_id)
);
CREATE INDEX IF NOT EXISTS activity_skills_skill_idx ON activity_skills (skill_id);

CREATE TABLE IF NOT EXISTS activity_partners (
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role         text NOT NULL CHECK (role IN ('co_organizer', 'sponsor')),
    note         text,
    PRIMARY KEY (activity_id, org_id)
);
CREATE INDEX IF NOT EXISTS activity_partners_org_idx ON activity_partners (org_id);   -- thay partner_activities_by_org

CREATE TABLE IF NOT EXISTS activity_schedules (
    id           uuid PRIMARY KEY,
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    title        text,
    location     text,
    start_at     timestamptz,
    end_at       timestamptz,
    status       text NOT NULL DEFAULT 'scheduled'
                 CHECK (status IN ('scheduled', 'open', 'closed', 'cancelled')),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS activity_schedules_activity_idx ON activity_schedules (activity_id, start_at ASC);  -- thay schedules_by_activity

-- registered tăng bằng: UPDATE ... SET registered = registered + 1
--   WHERE slot_id = $1 AND (capacity IS NULL OR registered < capacity)   (thay LWT)
CREATE TABLE IF NOT EXISTS activity_slots (
    slot_id      uuid PRIMARY KEY,
    schedule_id  uuid NOT NULL REFERENCES activity_schedules(id) ON DELETE CASCADE,
    title        text,
    capacity     int CHECK (capacity IS NULL OR capacity >= 0),
    registered   int NOT NULL DEFAULT 0 CHECK (registered >= 0),
    start_at     timestamptz,
    end_at       timestamptz,
    CONSTRAINT activity_slots_capacity_ck CHECK (capacity IS NULL OR registered <= capacity)
);
CREATE INDEX IF NOT EXISTS activity_slots_schedule_idx ON activity_slots (schedule_id);

CREATE TABLE IF NOT EXISTS activity_staff (
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    staff_role   text NOT NULL CHECK (staff_role IN ('organizer', 'supervisor', 'supporter')),
    assigned_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    assigned_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (activity_id, user_id)
);
CREATE INDEX IF NOT EXISTS activity_staff_user_idx ON activity_staff (user_id);

CREATE TABLE IF NOT EXISTS activity_announcements (
    announcement_id  uuid PRIMARY KEY,
    activity_id      uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    published_at     timestamptz NOT NULL DEFAULT now(),
    title            text NOT NULL,
    body             text,
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS activity_announcements_activity_idx ON activity_announcements (activity_id, published_at DESC);

CREATE TABLE IF NOT EXISTS activity_media (
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    asset_id     uuid NOT NULL REFERENCES media_assets(asset_id) ON DELETE CASCADE,
    position     int NOT NULL DEFAULT 0,
    role         text NOT NULL CHECK (role IN ('cover', 'gallery', 'document')),
    caption      text,
    PRIMARY KEY (activity_id, asset_id)
);
CREATE INDEX IF NOT EXISTS activity_media_order_idx ON activity_media (activity_id, position);

-- Role cấp activity (thuộc RBAC, đặt ở đây vì cần activities).
-- Ví dụ: tình nguyện viên ngoài dẫn dắt một sự kiện mà không có quyền cấp org.
-- Gộp activity_user_roles + user_activity_roles.
CREATE TABLE IF NOT EXISTS activity_user_roles (
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id      uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    granted_by   uuid REFERENCES users(id) ON DELETE SET NULL,
    granted_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz,
    PRIMARY KEY (activity_id, user_id, role_id)
);
CREATE INDEX IF NOT EXISTS activity_user_roles_user_idx ON activity_user_roles (user_id, activity_id);
CREATE INDEX IF NOT EXISTS activity_user_roles_role_idx ON activity_user_roles (role_id);

-- -----------------------------------------------------------------------------
-- 6. REGISTRATIONS — quan hệ N-M Student <-> Activity
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS registrations (
    registration_id  uuid PRIMARY KEY,
    activity_id      uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    student_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slot_id          uuid REFERENCES activity_slots(slot_id) ON DELETE RESTRICT,  -- NULL = cả activity
    status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'approved', 'rejected', 'waitlisted', 'cancelled', 'attended')),
    form_data        jsonb,                         -- câu trả lời registration_forms
    note             text,
    review_note      text,
    reviewed_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at      timestamptz,
    checkin_token    uuid NOT NULL,                 -- payload QR cá nhân
    registered_at    timestamptz NOT NULL DEFAULT now(),
    cancelled_at     timestamptz,
    CONSTRAINT registrations_checkin_token_uq UNIQUE (checkin_token)   -- thay registrations_by_token
);
-- Thay registrations_by_activity_student: chống đăng ký trùng, cho phép đăng ký nhiều ca.
-- slot_id NULL được coi như "cả activity" (trước đây dùng UUID toàn số 0).
CREATE UNIQUE INDEX IF NOT EXISTS registrations_activity_student_slot_uq
    ON registrations (activity_id, student_id, COALESCE(slot_id, '00000000-0000-0000-0000-000000000000'::uuid));
CREATE INDEX IF NOT EXISTS registrations_activity_idx ON registrations (activity_id, registered_at ASC, registration_id);
CREATE INDEX IF NOT EXISTS registrations_activity_status_idx ON registrations (activity_id, status);
CREATE INDEX IF NOT EXISTS registrations_student_idx  ON registrations (student_id, registered_at DESC);
CREATE INDEX IF NOT EXISTS registrations_slot_idx     ON registrations (slot_id) WHERE slot_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS registration_status_history (
    history_id       uuid PRIMARY KEY,
    registration_id  uuid NOT NULL REFERENCES registrations(registration_id) ON DELETE CASCADE,
    changed_at       timestamptz NOT NULL DEFAULT now(),
    from_status      text,
    to_status        text NOT NULL,
    changed_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    note             text
);
CREATE INDEX IF NOT EXISTS registration_status_history_reg_idx ON registration_status_history (registration_id, changed_at DESC);

CREATE TABLE IF NOT EXISTS registration_forms (
    question_id  uuid PRIMARY KEY,
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    position     int NOT NULL,
    label        text NOT NULL,
    field_type   text NOT NULL CHECK (field_type IN ('text', 'choice', 'file', 'consent')),
    required     boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS registration_forms_activity_idx ON registration_forms (activity_id, position);

CREATE TABLE IF NOT EXISTS waitlist_entries (
    waitlist_id  uuid PRIMARY KEY,
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    student_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slot_id      uuid REFERENCES activity_slots(slot_id) ON DELETE CASCADE,
    status       text NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting', 'promoted', 'expired')),
    joined_at    timestamptz NOT NULL DEFAULT now(),
    promoted_at  timestamptz
);
CREATE INDEX IF NOT EXISTS waitlist_entries_queue_idx   ON waitlist_entries (activity_id, joined_at ASC, waitlist_id) WHERE status = 'waiting';
CREATE INDEX IF NOT EXISTS waitlist_entries_student_idx ON waitlist_entries (student_id);

-- -----------------------------------------------------------------------------
-- 7. QR CHECK-IN & ATTENDANCE
-- QR được cấp theo buổi; mỗi lần quét được log; tranh chấp đi qua appeals.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS attendance_sessions (
    session_id   uuid PRIMARY KEY,
    schedule_id  uuid NOT NULL REFERENCES activity_schedules(id) ON DELETE CASCADE,
    title        text,
    qr_code      text,
    opens_at     timestamptz,
    closes_at    timestamptz,
    status       text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'open', 'closed')),
    created_by   uuid REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS attendance_sessions_schedule_idx ON attendance_sessions (schedule_id);

-- used_count tăng bằng: UPDATE qr_codes SET used_count = used_count + 1
--   WHERE code = $1 AND status = 'active' AND expires_at > now()
--     AND (max_uses IS NULL OR used_count < max_uses) RETURNING ...
CREATE TABLE IF NOT EXISTS qr_codes (
    code         text PRIMARY KEY,
    session_id   uuid NOT NULL REFERENCES attendance_sessions(session_id) ON DELETE CASCADE,
    schedule_id  uuid NOT NULL REFERENCES activity_schedules(id) ON DELETE CASCADE,
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    expires_at   timestamptz,
    max_uses     int CHECK (max_uses IS NULL OR max_uses >= 0),
    used_count   int NOT NULL DEFAULT 0 CHECK (used_count >= 0),
    status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'disabled')),
    CONSTRAINT qr_codes_used_ck CHECK (max_uses IS NULL OR used_count <= max_uses)
);
CREATE INDEX IF NOT EXISTS qr_codes_session_idx ON qr_codes (session_id);

-- qr_code KHÔNG có FK: mã 'invalid' được log kể cả khi không tồn tại.
CREATE TABLE IF NOT EXISTS qr_scan_logs (
    log_id       uuid PRIMARY KEY,
    qr_code      text NOT NULL,
    scanned_at   timestamptz NOT NULL DEFAULT now(),
    student_id   uuid REFERENCES users(id) ON DELETE SET NULL,
    result       text NOT NULL CHECK (result IN ('accepted', 'duplicate', 'expired', 'invalid')),
    device_info  text
);
CREATE INDEX IF NOT EXISTS qr_scan_logs_code_idx ON qr_scan_logs (qr_code, scanned_at DESC);

-- Gộp attendance_records + attendance_by_registration/_by_activity/_by_student.
-- LƯU Ý: bản gốc chỉ cho 1 bản ghi / registration (UNIQUE(registration_id)) nhưng lại có
-- attendance_summaries đếm nhiều buổi. Ở đây dùng UNIQUE (registration_id, session_id)
-- để một registration điểm danh được nhiều buổi; muốn đúng bản gốc, đổi thành UNIQUE (registration_id).
CREATE TABLE IF NOT EXISTS attendance_records (
    record_id        uuid PRIMARY KEY,
    session_id       uuid NOT NULL REFERENCES attendance_sessions(session_id) ON DELETE CASCADE,
    schedule_id      uuid NOT NULL REFERENCES activity_schedules(id) ON DELETE CASCADE,
    activity_id      uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    registration_id  uuid NOT NULL REFERENCES registrations(registration_id) ON DELETE CASCADE,
    student_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    method           text NOT NULL CHECK (method IN ('qr', 'manual')),
    scanned_at       timestamptz NOT NULL DEFAULT now(),
    verified_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    checked_out_at   timestamptz,
    check_out_method text,
    actual_hours     numeric(6,2),                  -- ghi đè hours_awarded
    CONSTRAINT attendance_records_reg_session_uq UNIQUE (registration_id, session_id)
);
CREATE INDEX IF NOT EXISTS attendance_records_activity_idx ON attendance_records (activity_id, scanned_at DESC);
CREATE INDEX IF NOT EXISTS attendance_records_student_idx  ON attendance_records (student_id, scanned_at DESC);
CREATE INDEX IF NOT EXISTS attendance_records_session_idx  ON attendance_records (session_id);

CREATE TABLE IF NOT EXISTS attendance_appeals (
    appeal_id    uuid PRIMARY KEY,
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    student_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    record_id    uuid REFERENCES attendance_records(record_id) ON DELETE SET NULL,
    reason       text,
    status       text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    resolved_by  uuid REFERENCES users(id) ON DELETE SET NULL,
    resolved_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS attendance_appeals_activity_idx ON attendance_appeals (activity_id, status);
CREATE INDEX IF NOT EXISTS attendance_appeals_student_idx  ON attendance_appeals (student_id);

CREATE TABLE IF NOT EXISTS attendance_summaries (
    registration_id    uuid PRIMARY KEY REFERENCES registrations(registration_id) ON DELETE CASCADE,
    activity_id        uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    student_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    sessions_total     int NOT NULL DEFAULT 0,
    sessions_attended  int NOT NULL DEFAULT 0,
    minutes_attended   int NOT NULL DEFAULT 0,
    status             text NOT NULL DEFAULT 'incomplete' CHECK (status IN ('incomplete', 'complete')),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS attendance_summaries_activity_idx ON attendance_summaries (activity_id);
CREATE INDEX IF NOT EXISTS attendance_summaries_student_idx  ON attendance_summaries (student_id);

-- -----------------------------------------------------------------------------
-- 8. VOLUNTEER HOURS
-- Sổ cái giờ tình nguyện (chỉ thêm, không sửa). 'attendance' ghi khi hoàn thành điểm danh;
-- 'manual'/'adjustment' đi qua quy trình duyệt.
-- -----------------------------------------------------------------------------

-- Gộp volunteer_hour_ledger + hour_entries_by_student + hours_by_activity + pending_hours_by_org.
-- org_id được thêm vào (bản gốc phải suy ra từ activity) để hàng đợi duyệt của org là một partial index.
CREATE TABLE IF NOT EXISTS volunteer_hour_ledger (
    entry_id         uuid PRIMARY KEY,
    student_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    activity_id      uuid REFERENCES activities(id) ON DELETE SET NULL,
    org_id           uuid REFERENCES organizations(id) ON DELETE SET NULL,
    source           text NOT NULL CHECK (source IN ('attendance', 'manual', 'adjustment')),
    hours            numeric(7,2) NOT NULL,
    term             text,                          -- ví dụ '2026-H1'
    registration_id  uuid REFERENCES registrations(registration_id) ON DELETE SET NULL,
    status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    approved_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    approved_at      timestamptz,
    recorded_at      timestamptz NOT NULL DEFAULT now(),
    recorded_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    note             text
);
CREATE INDEX IF NOT EXISTS hour_ledger_student_idx  ON volunteer_hour_ledger (student_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS hour_ledger_activity_idx ON volunteer_hour_ledger (activity_id, recorded_at DESC)
    WHERE activity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS hour_ledger_pending_idx  ON volunteer_hour_ledger (org_id, recorded_at ASC)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS hours_by_student (
    student_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    term              text NOT NULL,
    total_hours       numeric(9,2) NOT NULL DEFAULT 0,
    activities_count  int NOT NULL DEFAULT 0,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, term)
);
CREATE INDEX IF NOT EXISTS hours_by_student_term_idx ON hours_by_student (term, total_hours DESC);

CREATE TABLE IF NOT EXISTS hour_adjustments (
    adjustment_id  uuid PRIMARY KEY,
    student_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    activity_id    uuid REFERENCES activities(id) ON DELETE SET NULL,
    delta_hours    numeric(7,2) NOT NULL,
    reason         text,
    created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hour_adjustments_student_idx ON hour_adjustments (student_id, created_at DESC);

CREATE TABLE IF NOT EXISTS hour_rules (
    rule_id      uuid PRIMARY KEY,
    org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    category_id  uuid REFERENCES activity_categories(id) ON DELETE CASCADE,
    multiplier   numeric(6,3) NOT NULL DEFAULT 1,
    cap_hours    numeric(7,2),
    term         text,
    is_active    boolean NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS hour_rules_by_org ON hour_rules (org_id);

-- Bảng xếp hạng theo kỳ + toàn thời gian ('all'): thay leaderboard_by_term (không phải
-- xóa/chèn lại dòng khi tổng đổi). Cần tốc độ cao hơn thì đổi thành MATERIALIZED VIEW.
CREATE OR REPLACE VIEW leaderboard_by_term AS
    SELECT h.term, h.student_id, u.full_name AS student_name, h.total_hours,
           rank() OVER (PARTITION BY h.term ORDER BY h.total_hours DESC) AS rank,
           h.updated_at
      FROM hours_by_student h
      JOIN users u ON u.id = h.student_id
    UNION ALL
    SELECT 'all'::text, a.student_id, a.full_name, a.total_hours,
           rank() OVER (ORDER BY a.total_hours DESC), a.updated_at
      FROM (
          SELECT h.student_id, u.full_name, sum(h.total_hours) AS total_hours,
                 max(h.updated_at) AS updated_at
            FROM hours_by_student h
            JOIN users u ON u.id = h.student_id
           GROUP BY h.student_id, u.full_name
      ) a;

-- Danh sách kỳ cho bộ lọc leaderboard (thay leaderboard_terms).
CREATE OR REPLACE VIEW leaderboard_terms AS
    SELECT DISTINCT term FROM hours_by_student;

-- -----------------------------------------------------------------------------
-- 9. CERTIFICATES
-- Mỗi (activity, student) một chứng nhận. PDF lưu như media_assets.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS certificate_templates (
    template_id          uuid PRIMARY KEY,
    org_id               uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name                 text NOT NULL,
    background_media_id  uuid REFERENCES media_assets(asset_id) ON DELETE SET NULL,
    layout_json          jsonb,
    is_active            boolean NOT NULL DEFAULT true,
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS certificate_templates_by_org ON certificate_templates (org_id);

-- Gộp certificates + certificates_by_student/_by_serial/_by_id.
CREATE TABLE IF NOT EXISTS certificates (
    certificate_id   uuid PRIMARY KEY,
    activity_id      uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    student_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    registration_id  uuid REFERENCES registrations(registration_id) ON DELETE SET NULL,
    template_id      uuid REFERENCES certificate_templates(template_id) ON DELETE SET NULL,
    serial_no        text NOT NULL,
    issued_at        timestamptz NOT NULL DEFAULT now(),
    issued_by        uuid REFERENCES users(id) ON DELETE SET NULL,
    file_media_id    uuid REFERENCES media_assets(asset_id) ON DELETE SET NULL,
    status           text NOT NULL DEFAULT 'issued' CHECK (status IN ('issued', 'revoked')),
    CONSTRAINT certificates_activity_student_uq UNIQUE (activity_id, student_id),
    CONSTRAINT certificates_serial_uq           UNIQUE (serial_no)      -- xác minh công khai theo serial
);
CREATE INDEX IF NOT EXISTS certificates_student_idx ON certificates (student_id, issued_at DESC);

-- activity_id / student_id của bản gốc suy ra được từ certificates nên bỏ cho khỏi lệch dữ liệu.
CREATE TABLE IF NOT EXISTS certificate_revocations (
    revocation_id   uuid PRIMARY KEY,
    certificate_id  uuid NOT NULL REFERENCES certificates(certificate_id) ON DELETE CASCADE,
    reason          text,
    revoked_by      uuid REFERENCES users(id) ON DELETE SET NULL,
    revoked_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS certificate_revocations_cert_idx ON certificate_revocations (certificate_id);

-- -----------------------------------------------------------------------------
-- 11. NOTIFICATIONS
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS notifications (
    notification_id  uuid PRIMARY KEY,
    user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type             text NOT NULL,                 -- registration | attendance | certificate | announcement | ...
    title            text,
    body             text,
    data_json        jsonb,
    channel          text NOT NULL DEFAULT 'inapp' CHECK (channel IN ('inapp', 'email')),
    status           text NOT NULL DEFAULT 'unread' CHECK (status IN ('unread', 'read')),
    read_at          timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notifications_user_idx   ON notifications (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS notifications_unread_idx ON notifications (user_id) WHERE status = 'unread';

CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id      uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    channels     jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {"email": true, "inapp": true}
    muted_types  text[] NOT NULL DEFAULT '{}',
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- 12. REPORTS, STATISTICS & EXPORTS
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS report_snapshots (
    snapshot_id   uuid PRIMARY KEY,
    org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    report_type   text NOT NULL,                    -- activity_summary | hours_leaderboard | participation
    period_start  timestamptz,
    period_end    timestamptz,
    payload_json  jsonb,
    created_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS report_snapshots_org_idx ON report_snapshots (org_id, created_at DESC);

CREATE TABLE IF NOT EXISTS activity_daily_stats (
    activity_id    uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    day            date NOT NULL,
    registrations  int NOT NULL DEFAULT 0,
    attendees      int NOT NULL DEFAULT 0,
    hours_awarded  numeric(9,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (activity_id, day)
);

CREATE TABLE IF NOT EXISTS org_monthly_stats (
    org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    month         text NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),   -- '2026-10'
    activities    int NOT NULL DEFAULT 0,
    participants  int NOT NULL DEFAULT 0,
    hours         numeric(10,2) NOT NULL DEFAULT 0,
    certificates  int NOT NULL DEFAULT 0,
    PRIMARY KEY (org_id, month)
);

CREATE TABLE IF NOT EXISTS export_jobs (
    job_id        uuid PRIMARY KEY,
    requested_by  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id        uuid REFERENCES organizations(id) ON DELETE CASCADE,
    job_type      text NOT NULL CHECK (job_type IN ('certificates_pdf', 'roster_csv', 'stats_xlsx')),
    status        text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    file_url      text,
    error         text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);
CREATE INDEX IF NOT EXISTS export_jobs_user_idx ON export_jobs (requested_by, created_at DESC);

-- -----------------------------------------------------------------------------
-- 13. REVIEWS & FEEDBACK
-- Gộp reviews_by_activity + reviews_by_student.
-- Giả định mỗi sinh viên chỉ đánh giá một lần cho mỗi activity (bản gốc không ép);
-- bỏ constraint reviews_activity_student_uq nếu cho phép nhiều đánh giá.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS reviews (
    review_id    uuid PRIMARY KEY,
    activity_id  uuid NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    student_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating       int NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment      text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reviews_activity_student_uq UNIQUE (activity_id, student_id)
);
CREATE INDEX IF NOT EXISTS reviews_activity_idx ON reviews (activity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS reviews_student_idx  ON reviews (student_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- 14. DURABILITY — thay cho trạng thái RAM
-- Retry dedup theo key, rate limit theo bucket, job nền lấy lease từ DB.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS idempotency_keys (
    key            text PRIMARY KEY,                -- hash của idempotency key do client gửi
    user_id        uuid,
    status         text NOT NULL CHECK (status IN ('in_progress', 'completed', 'failed')),
    response_json  jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),
    expires_at     timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS idempotency_keys_expiry_idx ON idempotency_keys (expires_at);

-- Tăng hit: INSERT INTO auth_rate_limits (bucket, window_start, hits) VALUES ($1, $2, 1)
--           ON CONFLICT (bucket, window_start) DO UPDATE SET hits = auth_rate_limits.hits + 1 RETURNING hits;
CREATE TABLE IF NOT EXISTS auth_rate_limits (
    bucket        text NOT NULL,                    -- 'login:<ip>', 'refresh:<user_id>', 'edge:<ip>'
    window_start  timestamptz NOT NULL,
    hits          int NOT NULL DEFAULT 0,
    PRIMARY KEY (bucket, window_start)
);
CREATE INDEX IF NOT EXISTS auth_rate_limits_window_idx ON auth_rate_limits (window_start);

-- Lấy lease: UPDATE job_leases SET owner = $2, status = 'held', acquired_at = now(), expires_at = $3
--            WHERE job_id = $1 AND (status = 'free' OR expires_at < now()) RETURNING job_id;
CREATE TABLE IF NOT EXISTS job_leases (
    job_id       uuid PRIMARY KEY,
    owner        text,
    status       text NOT NULL DEFAULT 'free' CHECK (status IN ('free', 'held', 'done')),
    acquired_at  timestamptz,
    expires_at   timestamptz
);

-- -----------------------------------------------------------------------------
-- 15. REALTIME — vé handshake WebSocket
-- Chỉ lưu hash SHA-256; dùng một lần: DELETE FROM ws_tickets WHERE ticket_hash = $1
-- AND expires_at > now() RETURNING user_id;  Hàng hết hạn dọn bởi purge_expired().
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ws_tickets (
    ticket_hash  text PRIMARY KEY,
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at   timestamptz NOT NULL DEFAULT (now() + interval '5 minutes'),
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ws_tickets_expiry_idx ON ws_tickets (expires_at);

-- -----------------------------------------------------------------------------
-- 16. ORG FEED & CHAT
-- Bài viết theo org (announcement | discussion), ghim, media, comment phẳng,
-- và phòng chat. UUIDv7 nên sắp xếp theo id = sắp xếp theo thời gian; id là cursor.
-- -----------------------------------------------------------------------------

-- Gộp org_posts + org_posts_feed + org_posts_trash + org_posts_pinned +
-- announcements_feed + org_post_drafts (tất cả là partial index bên dưới).
-- status = trạng thái xuất bản; deleted_at (thùng rác) trực giao nên restore trả về đúng trạng thái.
-- revision_of: bản nháp riêng chỉnh sửa bài đang xuất bản, thay thế khi publish.
-- visibility NOT NULL: dữ liệu cũ có NULL thì backfill announcement -> 'public', discussion -> 'members'.
CREATE TABLE IF NOT EXISTS org_posts (
    post_id          uuid PRIMARY KEY,
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    author_id        uuid NOT NULL REFERENCES users(id),
    kind             text NOT NULL CHECK (kind IN ('announcement', 'discussion')),
    title            text,
    body             text,                          -- bản plain-text của blocks_json
    blocks_json      jsonb,                         -- paragraph, heading, quote, list, image, video, divider
    cover_media_id   uuid REFERENCES media_assets(asset_id) ON DELETE SET NULL,
    status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'draft')),
    visibility       text NOT NULL DEFAULT 'members' CHECK (visibility IN ('public', 'members')),
    revision_of      uuid REFERENCES org_posts(post_id) ON DELETE CASCADE,
    pinned_at        timestamptz,
    edited_at        timestamptz,
    published_at     timestamptz,
    deleted_at       timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
-- Bảng tin org, mới nhất trước (org_posts_feed).
CREATE INDEX IF NOT EXISTS org_posts_feed_idx ON org_posts (org_id, post_id DESC)
    WHERE status = 'active' AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS org_posts_feed_kind_idx ON org_posts (org_id, kind, visibility, post_id DESC)
    WHERE status = 'active' AND deleted_at IS NULL;
-- Dòng thời gian công khai toàn hệ thống (announcements_feed).
CREATE INDEX IF NOT EXISTS org_posts_public_feed_idx ON org_posts (post_id DESC)
    WHERE status = 'active' AND deleted_at IS NULL AND visibility = 'public' AND revision_of IS NULL;
-- Bài ghim (org_posts_pinned).
CREATE INDEX IF NOT EXISTS org_posts_pinned_idx ON org_posts (org_id, post_id DESC)
    WHERE pinned_at IS NOT NULL AND deleted_at IS NULL;
-- Bản nháp của một tác giả trong một org (org_post_drafts).
CREATE INDEX IF NOT EXISTS org_posts_drafts_idx ON org_posts (org_id, author_id, post_id DESC)
    WHERE status = 'draft' AND deleted_at IS NULL;
-- Thùng rác (org_posts_trash); INCLUDE để lọc theo tác giả/trạng thái không cần đọc bảng.
CREATE INDEX IF NOT EXISTS org_posts_trash_idx ON org_posts (org_id, post_id DESC) INCLUDE (author_id, status)
    WHERE deleted_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS org_posts_revision_idx ON org_posts (revision_of) WHERE revision_of IS NOT NULL;
CREATE INDEX IF NOT EXISTS org_posts_author_idx   ON org_posts (author_id);

-- Tag của bài viết (dùng chung danh mục tags theo org), tối đa 3 tag / bài.
CREATE TABLE IF NOT EXISTS post_tags (
    post_id  uuid NOT NULL REFERENCES org_posts(post_id) ON DELETE CASCADE,
    tag_id   uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, tag_id)
);
CREATE INDEX IF NOT EXISTS post_tags_tag_idx ON post_tags (tag_id);

CREATE OR REPLACE FUNCTION enforce_post_tag_limit() RETURNS trigger AS $$
BEGIN
    -- Khóa dòng bài viết để hai lần chèn đồng thời không cùng vượt giới hạn.
    PERFORM 1 FROM org_posts WHERE post_id = NEW.post_id FOR UPDATE;
    IF (SELECT count(*) FROM post_tags WHERE post_id = NEW.post_id) >= 3 THEN
        RAISE EXCEPTION 'post % already has 3 tags', NEW.post_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_post_tags_limit ON post_tags;
CREATE TRIGGER trg_post_tags_limit
    BEFORE INSERT ON post_tags
    FOR EACH ROW EXECUTE FUNCTION enforce_post_tag_limit();

CREATE TABLE IF NOT EXISTS post_user_tags (
    post_id      uuid NOT NULL REFERENCES org_posts(post_id) ON DELETE CASCADE,
    user_tag_id  uuid NOT NULL REFERENCES user_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, user_tag_id)
);
CREATE INDEX IF NOT EXISTS post_user_tags_tag_idx ON post_user_tags (user_tag_id);

-- Ảnh/video đính kèm bài; asset vẫn thuộc org.
CREATE TABLE IF NOT EXISTS org_post_media (
    post_id   uuid NOT NULL REFERENCES org_posts(post_id) ON DELETE CASCADE,
    asset_id  uuid NOT NULL REFERENCES media_assets(asset_id) ON DELETE CASCADE,
    position  int NOT NULL DEFAULT 0,
    PRIMARY KEY (post_id, asset_id)
);
CREATE INDEX IF NOT EXISTS org_post_media_order_idx ON org_post_media (post_id, position);

-- Comment phẳng, cũ nhất trước. Tổng comment = COUNT(*) theo (post_id) (thay org_post_comment_counts).
CREATE TABLE IF NOT EXISTS org_post_comments (
    comment_id  uuid PRIMARY KEY,
    post_id     uuid NOT NULL REFERENCES org_posts(post_id) ON DELETE CASCADE,
    author_id   uuid NOT NULL REFERENCES users(id),
    body        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS org_post_comments_post_idx ON org_post_comments (post_id, comment_id);

-- ---- Chat ----
-- room_id có thể là: org id (phòng chung), activity id, channel id hoặc dm room id
-- (đa hình, không FK; service tự phân giải loại phòng).

CREATE TABLE IF NOT EXISTS org_chat_settings (
    org_id           uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    attach_restricted boolean NOT NULL DEFAULT false   -- true: đính kèm file cần quyền chat:attach
);

CREATE TABLE IF NOT EXISTS org_chat_timeouts (
    org_id    uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id   uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    until     timestamptz NOT NULL,                 -- luôn so sánh until > now(); dọn bởi purge_expired()
    set_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    reason    text,
    PRIMARY KEY (org_id, user_id)
);

-- Tin nhắn: bản gốc chia theo bucket 'YYYYMM'. Ở PostgreSQL một bảng + index (room_id, message_id)
-- là đủ; cần thì PARTITION BY RANGE theo thời gian sau. body mã hóa AES-256-GCM ('v1gcm:' prefix).
CREATE TABLE IF NOT EXISTS org_room_messages (
    message_id        uuid PRIMARY KEY,             -- uuid7: vừa là thứ tự vừa là cursor
    room_id           uuid NOT NULL,
    author_id         uuid NOT NULL REFERENCES users(id),
    body              text NOT NULL,
    reply_to_id       uuid,                         -- không FK: bản xem trước còn sau khi tin gốc bị xóa
    reply_to_author   text,
    reply_to_body     text,
    edited_at         timestamptz,
    attachments_json  jsonb,
    mentions_json     jsonb,                        -- [{id, name}]
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS org_room_messages_room_idx ON org_room_messages (room_id, message_id);

-- Con trỏ đã đọc của mỗi thành viên; chưa đọc = tin sau con trỏ.
CREATE TABLE IF NOT EXISTS org_room_reads (
    room_id               uuid NOT NULL,
    user_id               uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_read_message_id  uuid,
    last_read_at          timestamptz,
    PRIMARY KEY (room_id, user_id)
);
CREATE INDEX IF NOT EXISTS org_room_reads_user_idx ON org_room_reads (user_id);

-- Tin ghim (nhiều tin / phòng). Thay org_room_pins_v2; bảng single-slot cũ không còn.
CREATE TABLE IF NOT EXISTS org_room_pins (
    room_id     uuid NOT NULL,
    message_id  uuid NOT NULL REFERENCES org_room_messages(message_id) ON DELETE CASCADE,
    pinned_by   uuid REFERENCES users(id) ON DELETE SET NULL,
    pinned_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (room_id, message_id)
);

CREATE TABLE IF NOT EXISTS org_room_mutes (
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id     uuid NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, room_id)
);

-- Mỗi (tin, emoji, người) một dòng; số lượt = số dòng.
CREATE TABLE IF NOT EXISTS org_room_reactions (
    message_id  uuid NOT NULL REFERENCES org_room_messages(message_id) ON DELETE CASCADE,
    emoji       text NOT NULL,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id     uuid NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, emoji, user_id)
);

-- Chỉ mục mục chia sẻ cho tab thông tin phòng. Gộp org_room_media + org_room_media_by_author +
-- org_room_media_authors: hai index bên dưới phục vụ tab theo loại và lọc theo người gửi;
-- danh sách người gửi = SELECT DISTINCT author_id ... WHERE room_id = $1 AND kind = $2.
-- kind='link': url lưu bản mã hóa AES-256-GCM của body như org_room_messages.body.
CREATE TABLE IF NOT EXISTS org_room_media (
    message_id   uuid NOT NULL REFERENCES org_room_messages(message_id) ON DELETE CASCADE,
    item_index   int NOT NULL,                      -- attachments trước, rồi links
    room_id      uuid NOT NULL,
    kind         text NOT NULL CHECK (kind IN ('image', 'video', 'file', 'link')),
    author_id    uuid NOT NULL REFERENCES users(id),
    media_id     uuid REFERENCES media_assets(asset_id) ON DELETE SET NULL,
    url          text,
    mime         text,
    name         text,
    size_bytes   bigint,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, item_index)
);
CREATE INDEX IF NOT EXISTS org_room_media_kind_idx   ON org_room_media (room_id, kind, message_id DESC);
CREATE INDEX IF NOT EXISTS org_room_media_author_idx ON org_room_media (room_id, kind, author_id, message_id DESC);

-- Mỗi media chỉ được gắn vào đúng một tin nhắn (thay INSERT IF NOT EXISTS).
-- Gửi lần hai cùng media_id sẽ vi phạm PK thay vì lặng lẽ dùng chung một file.
-- message_id NULL = file mới "staged", chưa gửi; xóa tin nhắn sẽ giải phóng claim.
CREATE TABLE IF NOT EXISTS chat_attachment_claims (
    media_id    uuid PRIMARY KEY REFERENCES media_assets(asset_id) ON DELETE CASCADE,
    room_id     uuid NOT NULL,
    message_id  uuid REFERENCES org_room_messages(message_id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_attachment_claims_message_idx ON chat_attachment_claims (message_id)
    WHERE message_id IS NOT NULL;

-- Cặp DM chuẩn tắc: user_lo < user_hi nên mỗi cặp đúng một dòng; race tạo phòng
-- được giải quyết bằng INSERT ... ON CONFLICT DO NOTHING.
CREATE TABLE IF NOT EXISTS org_dm_pairs (
    org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_lo     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_hi     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id     uuid NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_lo, user_hi),
    CONSTRAINT org_dm_pairs_order_ck CHECK (user_lo < user_hi),
    CONSTRAINT org_dm_pairs_room_uq  UNIQUE (room_id)
);
CREATE INDEX IF NOT EXISTS org_dm_pairs_lo_idx ON org_dm_pairs (user_lo);
CREATE INDEX IF NOT EXISTS org_dm_pairs_hi_idx ON org_dm_pairs (user_hi);

-- Hộp thư DM của từng người; cũng dùng để chứng minh quyền thành viên cho ACL chat:{room_id}.
-- Thay bảng org_dm_rooms (hai dòng / phòng) bằng view suy ra từ org_dm_pairs.
CREATE OR REPLACE VIEW org_dm_rooms AS
    SELECT user_lo AS user_id, room_id, org_id, user_hi AS peer_id, created_at FROM org_dm_pairs
    UNION ALL
    SELECT user_hi AS user_id, room_id, org_id, user_lo AS peer_id, created_at FROM org_dm_pairs;

-- Kênh chat đặt tên của org. channel_id đồng thời là room_id trong org_room_messages nên
-- tin nhắn/đã đọc/ghim/mute/reaction không cần bảng mới.
-- parent_room_id: kênh này là sub-thread của phòng đó (phòng chung hoặc kênh cấp 1; không lồng nhau).
-- visibility='restricted': chỉ mở cho thành viên trong org_chat_channel_members.
-- Gộp org_chat_channels + _by_id + org_chat_room_threads + org_chat_channel_names.
CREATE TABLE IF NOT EXISTS org_chat_channels (
    channel_id        uuid PRIMARY KEY,
    org_id            uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name              text NOT NULL,
    name_folded       text NOT NULL,
    topic             text,
    kind              text,                         -- nhãn hiển thị: text | report | task
    post_policy       text,                         -- có thể giới hạn chỉ manager được đăng
    visibility        text,                         -- 'restricted' hoặc mở
    parent_room_id    uuid,                         -- org id (phòng chung) hoặc channel_id cấp 1
    activity_id       uuid REFERENCES activities(id) ON DELETE SET NULL,
    created_by        uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    archived_at       timestamptz,
    archived_by       uuid REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS org_chat_channels_org_idx    ON org_chat_channels (org_id, channel_id);
CREATE INDEX IF NOT EXISTS org_chat_channels_parent_idx ON org_chat_channels (parent_room_id, channel_id)
    WHERE parent_room_id IS NOT NULL;
-- Một tên sống / phạm vi (thay org_chat_channel_names + LWT). Phạm vi = org với kênh cấp 1,
-- = phòng cha với sub-thread (thread dưới phòng chung dùng chung không gian tên của org vì
-- parent_room_id = org_id). Đổi tên/lưu trữ kênh giải phóng tên.
CREATE UNIQUE INDEX IF NOT EXISTS org_chat_channels_name_uq
    ON org_chat_channels (COALESCE(parent_room_id, org_id), name_folded)
    WHERE archived_at IS NULL;

-- Danh sách người được vào kênh restricted (gộp _members + _memberships).
CREATE TABLE IF NOT EXISTS org_chat_channel_members (
    channel_id  uuid NOT NULL REFERENCES org_chat_channels(channel_id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_by    uuid REFERENCES users(id) ON DELETE SET NULL,
    added_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (channel_id, user_id)
);
CREATE INDEX IF NOT EXISTS org_chat_channel_members_user_idx ON org_chat_channel_members (user_id);

-- =============================================================================
-- TỰ ĐỘNG CẬP NHẬT updated_at cho mọi bảng có cột này
-- =============================================================================
DO $$
DECLARE
    t text;
BEGIN
    FOR t IN
        SELECT c.table_name
          FROM information_schema.columns c
          JOIN information_schema.tables tb
            ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name
         WHERE c.table_schema = current_schema()
           AND c.column_name = 'updated_at'
           AND tb.table_type = 'BASE TABLE'
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%1$s_updated_at ON %1$I', t);
        EXECUTE format(
            'CREATE TRIGGER trg_%1$s_updated_at BEFORE UPDATE ON %1$I
             FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t);
    END LOOP;
END $$;

-- =============================================================================
-- DỌN DỮ LIỆU HẾT HẠN (thay TTL của ScyllaDB)
-- Gọi định kỳ, ví dụ pg_cron mỗi 5 phút:
--   SELECT cron.schedule('purge-expired', '*/5 * * * *', 'SELECT purge_expired()');
-- hoặc từ job nền sau khi lấy lease trong job_leases.
-- =============================================================================
CREATE OR REPLACE FUNCTION purge_expired() RETURNS void AS $$
BEGIN
    DELETE FROM ws_tickets          WHERE expires_at < now();
    DELETE FROM idempotency_keys    WHERE expires_at < now();
    DELETE FROM auth_rate_limits    WHERE window_start < now() - interval '1 day';
    DELETE FROM org_chat_timeouts   WHERE until < now();
    DELETE FROM password_resets     WHERE expires_at < now() - interval '7 days';
    DELETE FROM email_verifications WHERE expires_at < now() - interval '7 days';
    DELETE FROM auth_refresh_tokens WHERE expires_at < now() - interval '7 days';
END;
$$ LANGUAGE plpgsql;
