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

## 4. Thư viện ảnh/video

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
- Xóa cứng gọi `delete_org_dir` rồi `sweep_orphans` (xóa thư mục không còn
  org nào trỏ tới). Thư mục `media/` đã gitignore, không bao giờ commit.

## 5. Mở rộng lên cloud

`core/media.py` định nghĩa port `MediaStore` (`save`, `resolve`,
`delete_file`, `delete_org_dir`, `sweep_orphans`); `LocalMediaStore` là
backend hiện tại. Muốn lên S3/GCS: cài đặt class mới theo port, đổi một dòng
trong `core/dependencies.py:get_media_store`, giữ nguyên service, router,
test (viết fake `MediaStore` như test media hiện tại). Đường dẫn tương đối
`orgs/<org_id>/...` giữ nguyên nên `file_url` không phải migrate.

## 6. Bảng liên quan (`schemas.cql`)

- `organizations`: thêm `deleted_at` (`null` = đang sống; có giá trị =
  thùng rác, khôi phục được). Các cột pháp lý: `owner_id`, `tax_code`,
  `legal_rep_name/id/position`, `legal_status` (`none`/`pending`/`verified`).
- `organizations_by_slug`: giữ slug duy nhất bằng LWT, xóa cùng org khi
  xóa cứng nên slug được tái sử dụng.
- `organization_members` + `members_by_user`: thành viên hai chiều, xóa
  cứng dọn cả hai phía.
- `media_assets` + `media_by_owner`: metadata (`role` = `gallery`/`cover`/
  `logo`) và feed mới-nhất-trước của từng org.

## 7. Quy tắc quyền

- Mọi mutation tổ chức và xóa tệp: chỉ chủ (`owner_id`). Trái chủ `403`.
- Upload và xem thư viện: thành viên của org đó.
- Tải tệp qua `/media/...`: công khai bằng UUID (ảnh sự kiện vốn bán công
  khai). Muốn kín hoàn toàn thì chuyển sang URL ký trong `MediaStore` mới.

## 8. Kiểm thử

- `tests/unit/test_orgs_service.py`: vòng đời sửa → xóa mềm → ẩn → khôi
  phục → xóa cứng, chặn trái chủ.
- `tests/unit/test_media_store.py`: lưu/đọc/xóa theo tmp dir, chặn thoát
  root (`../`), quét mồ côi.
- `tests/integration/test_orgs_db.py`: CRUD qua HTTP, upload `multipart`,
  phục vụ tệp, xóa cứng dọn thư mục đĩa thật.
- `tests/regression/test_orgs_regression.py`: khóa hợp đồng thùng rác
  (`deleted_at`, `ORG_DELETED`, `204` xóa cứng) và media (`kind`, `role`,
  một `cover` duy nhất, mã lỗi `INVALID_MEDIA_ROLE`).
