# Kiến trúc backend — amigoact-be

## 1. Tổng quan

`amigoact-be` là API FastAPI duy nhất, phục vụ frontend qua JSON, chạy cổng `8100` bằng FastAPI CLI. Không dùng máy chủ ASGI riêng. Dữ liệu lưu trên ScyllaDB, truy cập kiểu ORM qua `cqlengine`.

Mục tiêu: rõ ràng theo bounded context, tuân thủ SOLID, dễ tách file khi chạm ngưỡng 350 dòng, mọi hành vi quan trọng đều có test ba lớp.

## 2. Nguyên tắc tổ chức

- Không có thư mục `src/`. Mỗi tính năng là một thư mục ở root (`auth/`, `users/`).
- `core/` chứa duy nhất phần dùng chung: cấu hình, kết nối DB, bảo mật, băm mật khẩu, ngoại lệ, wiring Depends.
- `main.py` chỉ tạo app, đăng ký middleware, router, lifespan, health check. Cấm nhét logic nghiệp vụ vào `main.py`.
- Mỗi tính năng gồm 6 file chuẩn:

| File | Trách nhiệm | Cấm |
|---|---|---|
| `model.py` | Khai báo bảng `cqlengine` | Cấm luật nghiệp vụ, JWT, hash |
| `schemas.py` | DTO Pydantic vào/ra | Cấm truy vấn DB |
| `repository.py` | Truy vấn persistence | Cấm luật nghiệp vụ |
| `service.py` | Luật nghiệp vụ | Cấm FastAPI, CQL thô |
| `router.py` | HTTP, mã trạng thái, Depends | Cấm gọi `cqlengine` trực tiếp |
| `interfaces.py` | ABC cho repository/service | Cấm cài đặt cụ thể |

Giao tiếp liên tính năng chỉ qua ABC + `core/dependencies.py`.

## 3. Runtime và cấu hình

- Lệnh chuẩn: `fastapi dev main.py --port 8100` (dev), `fastapi run main.py --port 8100` (prod).
- `app: FastAPI` khai báo ở `main.py`. `GET /health` luôn tồn tại.
- Cấu hình bằng `pydantic-settings` trong `core/config.py`. Biến môi trường tối thiểu: `SCYLLA_HOSTS`, `SCYLLA_KEYSPACE`, `JWT_SECRET`, `ENV`.
- Logging dùng `logging` chuẩn, gắn request-id, không log secret.

## 4. Dữ liệu và ScyllaDB

- Kết nối tập trung tại `core/database.py`: `connection.setup(...)` một lần, `sync_table(...)` chỉ lúc khởi động/migration.
- Mỗi bảng một `Model`, đặt `__table_name__` tường minh, khóa chính `columns.UUID(primary_key=True, default=uuid_utils.uuid7)`.
- Thiết kế bảng theo truy vấn, tránh `ALLOW FILTERING`, mặc định `LOCAL_QUORUM`, chỉ dùng LWT (`IF NOT EXISTS`) khi cần duy nhất (ví dụ email).
- Mọi `Model.objects(...)` nằm trong `repository.py`. Service nhận repository qua inject.
- Migration phải rõ ràng, review được, có test tích hợp trên keyspace `amigoact_test`.

Ví dụ bảng:

- `users`: `id (uuid PK)`, `email (text, index)`, `password_hash (text)`, `created_at`.
- `auth_refresh_tokens`: `token_hash (text PK)`, `user_id (uuid)`, `expires_at`, `revoked_at`, `rotated_from_jti`.

## 5. UUIDv7 và Argon2id

- UUIDv7 tạo ở application (`core/ids.py` bọc `uuid_utils.uuid7()` rồi chuẩn hóa sang `uuid.UUID` vì driver chỉ nhận stdlib), serialize JSON dạng chuỗi thường. Cấm `uuid4` cho PK, cấm số tự tăng.
- Argon2id tập trung ở `core/hashing.py` (`time_cost=3`, `memory_cost=65536`, `parallelism=4`, `hash_len=32`, `salt_len=16`). Lưu hash, verify bằng `ph.verify`, tự rehash khi cần. Policy tài khoản nằm ở schema: mật khẩu ≥ 8 ký tự gồm hoa, thường, số, ký tự đặc biệt; phone di động Việt Nam `^0(3|5|7|8|9)\d{8}$` và chặn số giả (toàn số giống nhau, chuỗi liên tiếp); `email` và `phone` đều duy nhất.

## 6. Xác thực hybrid

- Access: JWT 5–15 phút, header `Bearer`, claims `sub/iat/exp/jti/type=access/scopes`.
- Refresh: opaque 256-bit, cookie `HttpOnly; Secure; SameSite=Lax`, DB chỉ lưu SHA-256, so sánh bằng `hmac.compare_digest`, xoay vòng mỗi lần dùng, phát hiện tái sử dụng thì thu hồi cả họ token.
- Endpoint: `POST /auth/register` (`201`, thêm `account_type`: `individual` chỉ cần 4 trường cơ bản, `business` bắt buộc `tax_code`/`company_name`/`legal_rep_*`), `POST /auth/verify-email`, `POST /auth/resend-verification` (`202`), `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`/`logout-all` (`204`), `POST /auth/forgot-password` (`202`), `POST /auth/reset-password`, `POST /auth/change-password`, `GET /auth/me`. Riêng `dev` có thêm `POST /auth/dev/challenge-code`. Cửa chặn email chưa xác minh ở login (`EMAIL_NOT_VERIFIED`) đang tạm gỡ, bật lại sau.
- Xác minh email và reset mật khẩu dùng mã số 6 chữ số đơn lẻ (lưu SHA-256 ở `email_verifications`/`password_resets`), khác bảng refresh.
- Phân quyền thực hiện ở service theo bản ghi server, không tin claims một cách mù quáng.

## 7. Lỗi, phân trang, API

- Envelope lỗi duy nhất: `{"code": "...", "message": "..."}`. Domain exception mang `code`, handler tập trung map sang HTTP.
- Mã trạng thái chuẩn: `201` + `Location` khi tạo, `204` khi xóa/logout, `401/403/404/409/422` đúng ngữ nghĩa.
- Phân trang ưu tiên cursor (`limit` + `next_cursor`); JSON dùng UUID chuỗi thường, thời gian UTC ISO-8601.

## 8. Kiểm thử

- `tests/unit`: nhanh, mock I/O — service, validator, hash, JWT, UUID.
- `tests/integration`: app thật + ScyllaDB test — router→service→repository→DB, vòng đời login/refresh.
- `tests/regression`: khóa bug và hợp đồng — đặt tên theo case, phải đỏ trước fix và xanh sau fix.
- Lệnh: `uv run pytest -q`. Thiếu một loại test thì chưa xong.

## 9. Sơ đồ luồng

```text
Client -> router.py (HTTP/Depends)
       -> service.py (luật + quyền)
       -> repository.py (cqlengine Model)
       -> ScyllaDB
Lỗi domain -> core/exceptions.py -> HTTP envelope
Auth: get_current_user (JWT) -> load user -> kiểm tra quyền ở service
Refresh: cookie opaque -> hash SHA-256 -> đối chiếu DB -> xoay vòng -> cấp JWT mới
Orgs + media: xem `docs/ORGS.md` (CRUD, xóa mềm/cứng, `MediaStore` local qua `MEDIA_ROOT`, mở rộng cloud bằng port mới)
```
