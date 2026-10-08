# Hướng dẫn đóng góp — amigoact-be

Tài liệu này viết bằng tiếng Việt. Luật kỹ thuật bắt buộc nằm ở `AGENTS.md` (tiếng Anh). Nếu có mâu thuẫn, `AGENTS.md` được ưu tiên.

## 1. Chuẩn bị

```bash
cd amigoact-be
uv sync
```

Đọc trước: `README.md`, `docs/ARCHITECTURE.md`, `AGENTS.md` mục 3, 4, 9, 10.

## 2. Tạo tính năng mới

1. Tạo một thư mục ở root theo tên bounded context, ví dụ `posts/`.
2. Tạo đủ 6 file: `model.py`, `schemas.py`, `repository.py`, `service.py`, `router.py`, `interfaces.py`.
3. Không tạo thư mục `src/`. Không nhét code tính năng vào `core/` hay tính năng khác.
4. Mỗi file `.py` không quá 350 dòng. Gần chạm ngưỡng thì tách theo trách nhiệm, không tách cơ học theo số dòng.

## 3. Quy tắc kỹ thuật tóm tắt

- FastAPI duy nhất, chạy `fastapi dev main.py --port 8100`. Cấm `import uvicorn`.
- ScyllaDB chỉ qua `cqlengine` trong `repository.py`. Cấm CQL nối chuỗi, tránh `ALLOW FILTERING`.
- Khóa chính UUIDv7 (`uuid_utils.uuid7()`), cấm `uuid4`/số tự tăng cho PK.
- Mật khẩu chỉ Argon2id trong `core/hashing.py`. Cấm bcrypt, sha, md5.
- Auth hybrid: JWT access qua header `Bearer`, refresh opaque qua cookie `HttpOnly; Secure; SameSite=Lax`, lưu hash SHA-256 trong DB, xoay vòng mỗi lần dùng.
- SOLID nghiêm ngặt: router mỏng, service chứa luật nghiệp vụ, repository chứa persistence, giao tiếp qua ABC trong `interfaces.py` + `core/dependencies.py`.
- Type hint đầy đủ, không dùng `print`, không log secret/token/hash.

## 4. Kiểm thử bắt buộc

Mỗi tính năng/sửa lỗi phải có đủ:

- `tests/unit/test_*.py`: logic thuần, mock I/O.
- `tests/integration/test_*_db.py`: chạy với keyspace test `amigoact_test`.
- `tests/regression/test_*_regression.py`: khóa lỗi đã sửa và hợp đồng API.

Chạy:

```bash
uv run pytest -q
```

## 5. Quy trình pull request

1. Đặt tên nhánh rõ ràng: `feat/auth-login`, `fix/refresh-reuse`.
2. Tự kiểm tra: số dòng file, cấm `uvicorn`/`bcrypt`/`uuid4` PK, `pytest` xanh.
3. Cập nhật tài liệu tiếng Việt liên quan (`README.md`, `docs/ARCHITECTURE.md`, biến môi trường).
4. Mô tả PR gồm: mục tiêu, thiết kế bảng/truy vấn, ảnh hưởng auth/bảo mật, danh sách test đã thêm.
5. Không merge khi thiếu test, sai cấu trúc thư mục, hoặc vi phạm SOLID.

## 6. Báo lỗi

Ghi rõ: bước tái hiện, kết quả mong đợi/thực tế, log đã che secret, phiên bản Python/ScyllaDB, test hồi quy đề xuất.
