# Quản lý thành viên tổ chức (Members)

Tài liệu mô tả API, mô hình dữ liệu, ma trận quyền và hành vi vòng đời
thành viên của một tổ chức. Phần phân quyền dựa trên hạ tầng RBAC
(xem mục 4).

## 1. Mô hình dữ liệu

### 1.1 Trạng thái thành viên (`organization_members.status`)

| Trạng thái | Ý nghĩa | Chuyển tiếp hợp lệ |
|---|---|---|
| `invited` | Đã được mời, chờ chấp nhận | `accept` → `active`; `decline`/`remove` → `left` |
| `active` | Thành viên chính thức | `suspend` → `suspended`; `leave`/`remove` → `left` |
| `suspended` | Tạm khóa (mất quyền truy cập) | `reactivate` → `active`; `remove` → `left` |
| `left` | Đã rời/bị xóa — **giữ lại làm audit, không xóa row** | mời lại → `invited`; `open` join → `active` |

Mọi hành động rời/từ chối/xóa đều ghi `status='left'` thay vì xóa bản
ghi, đúng ý đồ audit của `schemas.cql`.

### 1.2 Chính sách gia nhập (`organizations.join_policy`)

| Giá trị | Hành vi |
|---|---|
| `invite` (mặc định) | Chỉ owner/admin mời mới vào được; `POST /join` trả `403 INVITE_ONLY` |
| `open` | Bất kỳ ai đăng nhập đều `POST /join` → `active` ngay |

Người tạo chọn khi tạo tổ chức; chỉ owner đổi được về sau qua `PATCH /orgs/{id}`.

### 1.3 Bảng dữ liệu (query-first)

| Bảng | Partition → Clustering | Phục vụ |
|---|---|---|
| `organization_members` | `org_id` → `user_id` | roster của một org (mọi status) |
| `members_by_user` | `user_id` → `org_id` | hộp thư lời mời + org của tôi |
| `user_roles` | `org_id` → `user_id, role_id` | vai trò RBAC trong org |
| `roles_by_user` | `user_id` → `org_id, role_id` | chiều ngược của `user_roles` |
| `access_audit_logs` | `org_id` → `occurred_at DESC, log_id` | nhật ký cho phép/từ chối |

Hai bảng membership luôn được ghi kép (dual-write) trong repository.

## 2. API

Tất cả endpoint yêu cầu Bearer token. Lỗi trả về envelope `{code, message}`.

| Method & Path | Quyền | Kết quả |
|---|---|---|
| `GET /orgs/{id}/members?q&status&sort&limit&offset` | member `active` | `200` `MemberListPage` |
| `POST /orgs/{id}/members` `{email, role?}` | owner, admin | `201` row `invited` |
| `PATCH /orgs/{id}/members/{uid}` `{role?|status?}` | role: owner; status: owner/admin | `200` |
| `DELETE /orgs/{id}/members/{uid}` | owner/admin; self = rời | `204`, status `left` |
| `POST /orgs/{id}/members/join` | ai cũng được | `open`: `201 active`; `invite`: `403 INVITE_ONLY` |
| `POST /orgs/{id}/members/me/accept` | người được mời | `200` `invited → active` |
| `POST /orgs/{id}/members/me/decline` | người được mời | `200` `invited → left` |
| `GET /orgs/memberships/mine?status=` | bản thân | hộp thư lời mời + org của tôi |
| `PATCH /orgs/{id}` `{join_policy}` | owner | đổi chính sách gia nhập |

### Envelope danh sách

```json
{
  "items": [{"user_id","org_id","full_name","email?","role","status","joined_at"}],
  "total": 12,
  "counts": [{"bucket":"active","count":9},{"bucket":"invited","count":2},{"bucket":"left","count":1}],
  "viewer_role": "owner"
}
```

`counts` đếm theo status trong phạm vi kết quả tìm kiếm (bỏ qua filter
status đang chọn), sort hỗ trợ `newest` (mặc định), `name`, `role`.

## 3. Quyền riêng tư email

- `viewer_role` là `owner` hoặc `admin` → `email` được trả về.
- `viewer_role` là `member` → chỉ thấy các row `active`, `email` luôn `null`.
- Người ngoài tổ chức → `403 FORBIDDEN`.

## 4. RBAC

Vai trò hiển thị (`role` trong response) suy ra từ:

1. `owner` — `organizations.owner_id` (nguồn sự thật duy nhất, không đổi được).
2. `admin` — có row `user_roles` trỏ tới role hệ thống `admin`.
3. `member` — mặc định cho mọi thành viên còn lại.

Role hệ thống `admin` (seed tự động, `is_system=true`) gồm các quyền:
`member:invite`, `member:suspend`, `member:remove`, `member:view`.

Việc kiểm tra quyền kết hợp: grant trực tiếp (`user_permission_grants`,
chưa hết hạn) **HOẶC** quyền từ role. Grant chỉ cấp thêm quyền, không
bao giờ deny. `expires_at` trên cả assignment lẫn grant được tôn trọng.

Mọi mutation member ghi một row `access_audit_logs` với
`result = allowed | denied` — ghi audit là best-effort, lỗi ghi không
làm hỏng request.

## 5. Ma trận quyền

| Hành động | owner | admin | member | khách |
|---|---|---|---|---|
| Xem roster đầy đủ + email | ✅ | ✅ | chỉ `active`, không email | ❌ |
| Mời | ✅ | ✅ | ❌ | ❌ |
| Mời làm admin | ✅ | ❌ | ❌ | ❌ |
| Suspend/reactivate/remove member thường | ✅ | ✅ | ❌ | ❌ |
| Đụng owner/admin (status/remove) | owner đụng admin ✅ | ❌ | ❌ | ❌ |
| Gán/thu hồi admin | ✅ | ❌ | ❌ | ❌ |
| Đổi `join_policy` | ✅ | ❌ | ❌ | ❌ |
| Rời tổ chức | ❌ `OWNER_IMMUTABLE` | ✅ | ✅ | — |

Admin muốn quản lý phải đồng thời là member `active` và có quyền RBAC
(admin bị suspend hoặc mới được mời nhưng chưa accept không hành động được).

## 6. Mã lỗi

| HTTP | `code` | Ý nghĩa |
|---|---|---|
| 400 | `OWNER_IMMUTABLE` | Owner không thể rời/bị xóa/bị sửa |
| 400 | `INVALID_MEMBER_STATE` | Chuyển trạng thái không hợp lệ |
| 400 | `INVALID_ROLE` | Vai trò không tồn tại |
| 403 | `FORBIDDEN` | Thiếu quyền (member thường/khách) |
| 403 | `INVITE_ONLY` | Org chỉ nhận lời mời |
| 404 | `USER_NOT_FOUND` | Email không có tài khoản active |
| 404 | `MEMBER_NOT_FOUND` | Không có membership (hoặc đã `left`) |
| 409 | `ALREADY_MEMBER` | Đã là member (hoặc đang suspended) |
| 409 | `ALREADY_INVITED` | Đã có lời mời đang chờ |

## 7. Realtime

Sau mỗi mutation thành công, `MemberService` phát qua port
`MemberEvents` (adapter `_WsMemberEvents` → `ConnectionManager`):

- `members:{org_id}`: roster đổi — action
  `invited`/`accepted`/`declined`/`joined`/`promoted`/`demoted`/
  `suspended`/`reactivated`/`removed`/`left`.
- `notifications:{user_id}`: người được mời/bị tác động nhận push
  `scope: "membership"` để inbox/badge cập nhật ngay cả khi họ chưa
  (hoặc không còn) là member.

Publish best-effort qua `schedule_publish` — không bao giờ làm hỏng
request. Chi tiết kênh/ACL: `docs/REALTIME.md` §5.

## 8. Migration cho keyspace đã deploy

```sql
ALTER TABLE organizations ADD join_policy text;
```

Hai bảng membership đã có `status` sẵn các giá trị cần thiết — không cần
ALTER. Catalog RBAC (`permissions` + role `admin`) được seed idempotent
bởi `rbac.seed.seed_rbac()` khi app khởi động.
