# Quản lý thành viên tổ chức (Members)

Tài liệu mô tả API, mô hình dữ liệu, ma trận quyền và hành vi vòng đời
thành viên của một tổ chức. Phần phân quyền dựa trên hạ tầng RBAC
(xem mục 4).

## 1. Mô hình dữ liệu

### 1.1 Trạng thái thành viên (`organization_members.status`)

| Trạng thái | Ý nghĩa | Chuyển tiếp hợp lệ |
|---|---|---|
| `applied` | Ứng viên đã nộp hồ sơ theo biểu mẫu, chờ quản lý duyệt | `approve` → `active`; `reject` → `left`; ứng viên tự rút → `left` |
| `invited` | Đã được mời, chờ chấp nhận | `accept` → `active`; `decline`/`remove` → `left`; `revoke` → `revoked` |
| `active` | Thành viên chính thức | `suspend` → `suspended`; `leave`/`remove` → `left` |
| `suspended` | Tạm khóa (mất quyền truy cập) | `reactivate` → `active`; `remove` → `left` |
| `left` | Đã rời/từ chối/bị xóa — **giữ lại làm audit, không xóa row** | mời lại → `invited`; `open` join → `active` |
| `revoked` | Lời mời bị quản lý thu hồi trước khi được phản hồi — audit riêng, không trùng `left` | mời lại → `invited`; `open` join → `active` |

Mọi hành động rời/từ chối/xóa đều ghi `status='left'` thay vì xóa bản
ghi, đúng ý đồ audit của `schemas.cql`. Riêng thu hồi lời mời ghi
`status='revoked'` để nhật ký phân biệt "tổ chức rút lời mời" với
"người dùng tự rời/từ chối". Row `revoked` không còn là member:
`PATCH`/`DELETE member` trả `404 MEMBER_NOT_FOUND`.

### 1.2 Chính sách gia nhập (`organizations.join_policy`)

| Giá trị | Hành vi |
|---|---|
| `invite` (mặc định) | Chỉ owner/admin mời mới vào được; `POST /join` trả `403 INVITE_ONLY` |
| `open` | Bất kỳ ai đăng nhập đều `POST /join` → `active` ngay |
| `review` | Ứng viên trả lời biểu mẫu rồi `POST /apply` → `applied`; `POST /join` trả `403 APPLICATION_REQUIRED` |

Người tạo chọn khi tạo tổ chức; chỉ owner đổi được về sau qua `PATCH /orgs/{id}`.

Với `review`, biểu mẫu là danh sách câu hỏi lưu trong `membership_forms` (theo `org_id`,
sắp theo vị trí). Câu trả lời của mỗi ứng viên nằm trong `membership_applications`
(một dòng theo `(org_id, user_id)`, nộp lại thì ghi đè). Việc nộp giữ trạng thái
`applied` trên `organization_members` và `members_by_user`, nên hộp thư, danh sách
thành viên và thẻ thống kê đều thấy trạng thái mới. Ứng viên không thấy các dòng
`applied` của người khác; chỉ người có `member:invite` mới đọc được hồ sơ.
Ứng viên đang có lời mời (`invited`) phải phản hồi lời mời trước. Thông báo cho
owner khi có hồ sơ mới; người nộp được báo khi được duyệt hoặc bị từ chối.

Chống spam nộp hồ sơ gồm bốn lớp. Sau khi bị từ chối, người nộp phải chờ 7 ngày
(`membership_applications.rejected_at`, đọc trong `_check_cooldown`); tự rút hồ sơ
thì nộp lại ngay vì không có dấu từ chối. Mỗi người nộp tối đa 5 lần nộp trong một
giờ, kể cả lần bị từ chối (bucket `membership_apply:{uid}`). Owner nhận tối đa một
thông báo "có hồ sơ mới" trong 15 phút (bucket `membership_notify:{org}`); danh sách
chờ duyệt vẫn cập nhật realtime cho từng hồ sơ. Giới hạn đếm qua `RateLimiter` có
sẵn trên ScyllaDB, không dùng bộ nhớ tiến trình.

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
| `DELETE /orgs/{id}/members/{uid}/invitation` | quyền `member:invite` | `204`, status `revoked`; `400 INVALID_MEMBER_STATE` nếu không còn chờ |
| `POST /orgs/{id}/members/join` | ai cũng được | `open`: `201 active`; `invite`: `403 INVITE_ONLY`; `review`: `403 APPLICATION_REQUIRED` |
| `GET /orgs/{id}/membership-form` | đã đăng nhập | `200` `{title, description, questions}`; câu hỏi `choice` có `options` (tối đa 20 phương án, không có `|`) và `allow_other` (thêm lựa chọn "Khác": người nộp tự nhập đáp án; tổng số lựa chọn kể cả "Khác" tối thiểu 2); các kiểu khác `options` rỗng và `allow_other` false |
| `PUT /orgs/{id}/membership-form` `{title, description, questions}` | `member:invite` hoặc owner | `200` thay toàn bộ biểu mẫu và tiêu đề (`title` tối đa 120, `description` tối đa 1000); đơn đã nộp giữ nguyên câu trả lời; đáp án `choice` ngoài danh sách phương án bị bỏ qua |
| `POST /orgs/{id}/membership-applications/files` (multipart `file`) | đã đăng nhập, chính sách `invite` hoặc `review`, chưa là thành viên | `201` `{media_id, name, mime, size_bytes}`; chỉ PDF hoặc ảnh, tối đa 10 MB (`415 UNSUPPORTED_MEDIA`, `413 MEDIA_TOO_LARGE`); file chỉ nằm trong `media/orgs/` và không vào feed, không qua `/media` công khai |
| `GET /orgs/{id}/members/{uid}/application-files/{media_id}` | `member:invite` hoặc owner | `200` tải file; chỉ file mà đơn của `uid` thực sự tham chiếu mới tải được |
| `POST /orgs/{id}/members/apply` `{answers}` | ai cũng được, chính sách `invite` hoặc `review` | `201` + `Location`, trạng thái `applied`; `403 NOT_ACCEPTING_APPLICATIONS` nếu là chính sách `open`; `400 ANSWER_REQUIRED`; `409 ALREADY_APPLIED` / `INVITE_PENDING` / `ALREADY_MEMBER` / `APPLICATION_COOLDOWN`; `429 TOO_MANY_REQUESTS` khi vượt giới hạn tốc độ |
| `GET /orgs/{id}/members/{uid}/application` | `member:invite` hoặc owner | `200` câu trả lời kèm nhãn câu hỏi hiện tại |
| `POST /orgs/{id}/members/{uid}/approve` | `member:invite` hoặc owner | `200` `applied → active`; `400 INVALID_MEMBER_STATE` nếu không còn chờ |
| `POST /orgs/{id}/members/{uid}/reject` | `member:invite` hoặc owner | `200` `applied → left`; người nộp chờ 7 ngày rồi mới nộp lại (trước đó `409 APPLICATION_COOLDOWN`) |
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
| Thu hồi lời mời đang chờ | ✅ | ✅ (trừ invite gắn role admin) | ❌ | ❌ |
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
| 400 | `INVALID_MEMBER_STATE` | Chuyển trạng thái không hợp lệ (kể cả thu hồi lời mời không còn chờ) |
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
  `suspended`/`reactivated`/`removed`/`left`/`revoked`.
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
