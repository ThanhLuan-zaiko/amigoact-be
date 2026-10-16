# Tổ chức và thư viện media — `orgs/`

## 1. Tổng quan

Mỗi tài khoản thuộc một trong hai tầng: `individual` (cá nhân) hoặc `business`
(doanh nghiệp, bắt buộc `tax_code`, `company_name`, `legal_rep_name`,
`legal_rep_id`). Mọi tài khoản đều tạo được tổ chức trong `my-dashboard`;
riêng `kind = business` phải kèm MST và người đại diện pháp luật, org sinh ra
ở trạng thái `legal_status = pending`.

CRUD đầy đủ: tạo (`POST /orgs`), sửa (`PATCH /orgs/{id}`), xóa mềm
(`DELETE /orgs/{id}`), khôi phục (`POST /orgs/{id}/restore`), xóa cứng
(`DELETE /orgs/{id}?hard=true`). Thư viện ảnh/video của org lưu file vật lý
dưới `MEDIA_ROOT`, metadata lưu ScyllaDB.

## 2. Tài khoản và người đại diện pháp luật

- Đăng ký cá nhân: `email`, `phone` (di động Việt Nam), `password`
  (≥ 8 ký tự gồm hoa, thường, số, ký tự đặc biệt), `full_name`.
- Đăng ký doanh nghiệp (`account_type = business`): thêm `tax_code`
  (10 số, chi nhánh `10so-XXX`), `company_name`, `legal_rep_name`,
  `legal_rep_id` (CCCD 12 số), `legal_rep_position` (tùy chọn). Thiếu là `422`.
- Cá nhân KHÔNG cần CCCD: SIM Việt Nam đã chính chủ bằng CCCD nên OTP
  phone là đủ định danh gián tiếp; thu CCCD hàng loạt kéo theo nghĩa vụ
  dữ liệu nhạy cảm theo Nghị định 13/2023 mà không tăng xác thực thật
  (số gõ tay không kiểm được nếu thiếu eKYC).

## 3. API tổ chức

| Thao tác | Endpoint | Trạng thái |
|---|---|---|
| Tạo (người gọi thành chủ) | `POST /orgs` | `201`, slug trùng `409 SLUG_TAKEN`; `join_policy`: `invite` (mặc định) \| `open` |
| Danh sách của tôi | `GET /orgs/mine` | `200` envelope `{items, total, counts}` (mặc định ẩn thùng rác) |
| Kèm thùng rác | `GET /orgs/mine?include_deleted=true` | `200` |
| Tìm/lọc/sắp xếp/trang | `GET /orgs/mine?q=&status=&sort=&limit=&offset=` | `200`, `sort` sai `422` |

- `q`: khớp tên/slug, không phân biệt hoa thường và dấu tiếng Việt
  (`hoi an` khớp `Hội An`). `status`: `active` | `pending` (giá trị lạ trả
  rỗng, không `422`). `sort`: `newest` (mặc định) | `name` | `members`.
  `limit` 1–100 (mặc định 20), `offset` ≥ 0 (mặc định 0). `total` là số
  lượng sau lọc, `counts` là số lượng từng trạng thái sau `q` (cho chip lọc).
- Đọc `mine` chỉ chạm một partition `members_by_user` nên lọc/sắp xếp/trang
  chạy trong service (`orgs/listing.py`), không cần bảng query mới và không
  `ALLOW FILTERING`. Chỉ xem lại khi một user có hàng trăm org.
| Sửa tên/mô tả/`join_policy` (slug, kind đóng băng) | `PATCH /orgs/{id}` | `200`, khác chủ `403` |
| Xóa mềm | `DELETE /orgs/{id}` | `200` + `deleted_at` |
| Khôi phục | `POST /orgs/{id}/restore` | `200`, chưa xóa `400 INVALID_BUSINESS_PROFILE` |
| Xóa cứng | `DELETE /orgs/{id}?hard=true` | `204`, xóa cả tệp vật lý |

Org đã xóa mềm: mọi thao tác đọc/ghi trả `410 ORG_DELETED`, trừ xem thùng
rác và khôi phục. Org không tồn tại trả `404`.

`join_policy` quyết định cách thành viên gia nhập: `invite` chỉ qua lời
mời của owner/admin, `open` cho bất kỳ ai `POST /join` vào thẳng `active`.
Vòng đời thành viên, phân quyền RBAC và API members: xem `docs/MEMBERS.md`.

## 4. Bề mặt công khai (`orgs/public_router.py` + `public_service.py`)

Hai endpoint guest (không auth), phục vụ trang khám phá `/orgs` bên FE:

| Thao tác | Endpoint | Trạng thái |
|---|---|---|
| Thư mục công khai | `GET /orgs?q=&kind=&sort=&limit=&offset=` | `200` `{items, total, counts}` |
| Hồ sơ công khai | `GET /orgs/{slug}` | `200`, slug lạ/xóa/không active `404` |

- Router public được include **sau** `orgs_router` trong `main.py` nên
  `GET /orgs/mine` luôn thắng `{slug}` — regression test khóa thứ tự này.
- `GET /orgs` đọc bảng denormalized `organizations_public` rồi rehydrate
  canonical rows; mọi mutation trong `CqlOrgRepository` (create/update/
  mark_deleted/mark_restored/delete_everything) dual-write feed này nên
  org ẩn/xóa biến mất khỏi đọc tiếp theo ngay, không `ALLOW FILTERING`.
- `PublicOrgService` chỉ trả field public: card giấu `owner_id`,
  `legal_rep_*`, contact, `deleted_at`; `owner_name`/`owner_avatar_url`
  (resolve qua `UserDirectory` + media) là danh tính hiển thị public giống
  `author_*` của bài đăng — danh tính con người đứng sau card. Card còn
  kèm `media[]` (tối đa 6 tile `{url, kind, mime}`, role `cover` xếp đầu
  rồi gallery mới nhất — ảnh lẫn video, loại `logo`/`attachment`) và
  `media_count` (tổng số media đủ điều kiện để UI hiện `+N`); preview chỉ
  gắn sau khi cắt trang nên không tốn read ngoài item hiển thị. Lightbox
  feed đọc `GET /orgs/{slug}/gallery` → `PublicOrgMediaPage` — toàn bộ
  media `cover`+`gallery` (ảnh lẫn video, cover dẫn đầu, tối đa 100),
  không giới hạn 8 ảnh như `gallery` của detail; cùng bộ lọc public
  (loại `logo`/`attachment`/asset chết, `404` khi org thiếu/đã xóa).
  Path nói `/gallery` vì route member `GET /orgs/{id}/media` đã chiếm
  shape `{id}/media`. Detail trả
  tín hiệu tin cậy
  (`verified_at`, `legal_status`, `legal_name`, `license_number`,
  `tax_code`, contact, `member_count`, `activity_count`, 6 activity
  public gần nhất, gallery ảnh) nhưng vẫn giấu `owner_id`/`legal_rep_*`/
  `previous_slug`.
- Hoạt động đi qua port `ActivityDirectory` → adapter
  `CqlOrgActivityDirectory` đọc `activities_by_org`, chỉ giữ status public
  (`published`/`ongoing`/`completed`), đếm đủ và hydrate 6 item gần nhất.
- Realtime: mutation ảnh hưởng hiển thị phát `event.v1` lên kênh public
  `orgs:directory` qua port `OrgDirectoryEvents` — chi tiết ở
  `docs/REALTIME.md` §5. `MediaService` cũng phát `"updated"` sau khi
  upload/đổi vai trò/thay bytes/xóa media public (`gallery`/`cover`/`logo`),
  nên đổi logo hay cover cập nhật ngay danh bạ, trang chi tiết và rail
  phải; role `attachment` (media bài đăng) không bao giờ phát vì nó nằm
  ngoài mọi bề mặt public.

## 5. Thư viện ảnh/video

| Thao tác | Endpoint | Ghi chú |
|---|---|---|
| Upload (thành viên) | `POST /orgs/{id}/media` (`multipart`, field `file` + `role`) | `201`, sai định dạng `415 UNSUPPORTED_MEDIA`, quá cỡ `413 MEDIA_TOO_LARGE`, vai trò sai `400 INVALID_MEDIA_ROLE` |
| Đặt vai trò (chủ org) | `PATCH /orgs/{id}/media/{media_id}` `{role}` | `200`, vai trò sai `400 INVALID_MEDIA_ROLE`, trái chủ `403` |
| Danh sách (thành viên) | `GET /orgs/{id}/media` | Mới nhất trước |
| Xóa tệp (chủ org) | `DELETE /orgs/{id}/media/{media_id}` | `204`, xóa cả bytes |
| Xóa toàn bộ (chủ org) | `DELETE /orgs/{id}/media` | `204`, xóa mọi metadata + bytes của gallery |
| Tải/xem tệp | `GET /media/orgs/{org_id}/{file}` | Công khai bằng UUID khó đoán, hỗ trợ `Range` |

- `role` nhận `gallery` (mặc định) | `cover` | `logo`. `cover`/`logo` chỉ
  nhận ảnh và chỉ chủ org đặt được; mỗi org chỉ giữ một `cover` và một
  `logo` — đánh dấu mới tự hạ vai trò cũ về `gallery`.
- Giới hạn: ảnh `MEDIA_MAX_IMAGE_MB` (mặc định 10: JPG, PNG, WebP, GIF,
  AVIF, BMP, TIFF, HEIC/HEIF), video `MEDIA_MAX_VIDEO_MB` (mặc định 100:
  MP4, WebM, MOV). Đọc upload chặn ở `max + 1` byte nên không nuốt RAM.
- Ảnh không web-safe (HEIC, TIFF, BMP…) được `normalize_image`
  (Pillow + pillow-heif) transcode sang JPEG/PNG lúc upload — áp dụng
  `exif_transpose`, giữ alpha bằng PNG. Định dạng web-safe đi qua nguyên
  vẹn (GIF giữ animation). Decode lỗi thì giữ bytes gốc.
- Layout đĩa: `<MEDIA_ROOT>/orgs/<org_id>/<media_id>.<ext>` — mỗi org đúng
  một thư mục, tên file là UUID nên không đụng độ và không lộ tên gốc.
- ScyllaDB chỉ giữ metadata (`media_assets` + `media_by_owner` với
  `owner_type = organization`); bytes nằm ở `MediaStore`.
- Tài liệu sinh tự động (PDF chứng nhận) lưu qua `save_typed` với
  `role = attachment`, `owner_type = certificate` — không vào gallery,
  tải qua endpoint có phân quyền `GET /certificates/{id}/file` chứ không
  qua upload. `application/pdf`/`.pdf` nằm trong allowlist nhưng
  `media_kind` trả `None` nên user không upload được.
- Xóa cứng gọi `delete_org_dir` rồi `sweep_orphans` (xóa thư mục không còn
  org nào trỏ tới). Thư mục `media/` đã gitignore, không bao giờ commit.

## 6. Mở rộng lên cloud

`core/media.py` định nghĩa port `MediaStore` (`save`, `resolve`,
`delete_file`, `delete_org_dir`, `sweep_orphans`); `LocalMediaStore` là
backend hiện tại. Muốn lên S3/GCS: cài đặt class mới theo port, đổi một dòng
trong `core/dependencies.py:get_media_store`, giữ nguyên service, router,
test (viết fake `MediaStore` như test media hiện tại). Đường dẫn tương đối
`orgs/<org_id>/...` giữ nguyên nên `file_url` không phải migrate.

## 7. Bảng liên quan (`schemas.cql`)

- `organizations`: thêm `deleted_at` (`null` = đang sống; có giá trị =
  thùng rác, khôi phục được). Các cột pháp lý: `owner_id`, `tax_code`,
  `legal_rep_name/id/position`, `legal_status` (`none`/`pending`/`verified`).
- `organizations_by_slug`: giữ slug duy nhất bằng LWT, xóa cùng org khi
  xóa cứng nên slug được tái sử dụng.
- `organization_members` + `members_by_user`: thành viên hai chiều, xóa
  cứng dọn cả hai phía.
- `organizations_public`: feed denormalized của thư mục guest — partition
  theo `visibility` cho quét không lọc; repository dual-write trên mọi
  mutation nên tự đồng bộ (org cũ trước bảng này cần backfill một lần,
  `CREATE TABLE IF NOT EXISTS` không đụng data hiện có).
- `media_assets` + `media_by_owner`: metadata (`role` = `gallery`/`cover`/
  `logo`/`attachment`) và feed mới-nhất-trước của từng org.
- `certificates_by_id`: feed `certificate_id -> (activity_id, student_id)`
  cho download PDF (bảng chính partition theo `activity_id`); tạo bằng
  `migrate/certificate_files.py` (additive, backfill idempotent).

## 8. Quy tắc quyền

- Mọi mutation tổ chức và xóa tệp: chỉ chủ (`owner_id`). Trái chủ `403`.
- Upload và xem thư viện: thành viên của org đó.
- Tải tệp qua `/media/...`: công khai bằng UUID (ảnh sự kiện vốn bán công
  khai). Muốn kín hoàn toàn thì chuyển sang URL ký trong `MediaStore` mới.

## 9. Kiểm thử

- `tests/unit/test_orgs_service.py`: vòng đời sửa → xóa mềm → ẩn → khôi
  phục → xóa cứng, chặn trái chủ.
- `tests/unit/test_media_store.py`: lưu/đọc/xóa theo tmp dir, chặn thoát
  root (`../`), quét mồ côi.
- `tests/integration/test_orgs_db.py`: CRUD qua HTTP, upload `multipart`,
  phục vụ tệp, xóa cứng dọn thư mục đĩa thật.
- `tests/regression/test_orgs_regression.py`: khóa hợp đồng thùng rác
  (`deleted_at`, `ORG_DELETED`, `204` xóa cứng) và media (`kind`, `role`,
  một `cover` duy nhất, mã lỗi `INVALID_MEDIA_ROLE`), khóa thứ tự route
  `/orgs/mine` vs `/orgs/{slug}`.
- Bề mặt public: `test_orgs_service.py` (ẩn org thùng rác, không rò
  PII, gallery/trust signals, emit `OrgDirectoryEvents` đúng action),
  `test_orgs_db.py` (`GET /orgs` + `GET /orgs/{slug}` end-to-end).
- Realtime public: `tests/unit/test_realtime.py` (parse `orgs:directory`,
  `authorize` cho guest), `tests/integration/test_ws_db.py` (socket ẩn
  danh subscribe + nhận `created`/`removed` trực tiếp, kênh private
  `4403`), `tests/regression/test_ws_regression.py` (khóa payload
  `{action, org_id, slug}`).
