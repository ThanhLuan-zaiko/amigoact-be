# amigoact-be

Backend của dự án AmigoACT.

## Giới thiệu

- Framework duy nhất: **FastAPI**, chạy bằng **FastAPI CLI** trên cổng **8100**.
- Không dùng `uvicorn`, `gunicorn`, `hypercorn` dưới mọi hình thức.
- Cơ sở dữ liệu: **ScyllaDB**, truy cập kiểu ORM qua **`cassandra-driver` + `cqlengine`**.
- Khóa chính: **UUIDv7** (lưu dạng CQL `uuid`).
- Băm mật khẩu: **Argon2id** (`argon2-cffi`).
- Xác thực: **hybrid** — JWT access ngắn hạn + refresh token opaque lưu hash trong ScyllaDB.
- Kiến trúc: SOLID + OOP, mỗi thư mục chức năng nằm ở **root**, cấm thư mục `src/`.
- Mỗi file `.py` tối đa **350 dòng**, vượt thì tách theo trách nhiệm.
- Mỗi tính năng bắt buộc có kiểm thử **đơn vị + tích hợp + hồi quy**.

Chi tiết bắt buộc tuân thủ xem tại `AGENTS.md` (file tiếng Anh duy nhất) và `docs/ARCHITECTURE.md`.

## Yêu cầu môi trường

- Python `>= 3.14`
- `uv`
- ScyllaDB chạy local hoặc remote (keyspace dev: `amigoact`, test: `amigoact_test`)

## Cài đặt

```bash
cd amigoact-be
uv sync
uv add fastapi cassandra-driver argon2-cffi uuid-utils pyjwt cryptography pydantic-settings
uv add --dev pytest pytest-asyncio httpx
```

## Chạy

```bash
# dev
fastapi dev main.py --port 8100

# prod
fastapi run main.py --port 8100
```

Kiểm tra sức khỏe:

```bash
curl http://localhost:8100/health
# {"status": "ok"}
```

## Cấu hình

Mọi cấu hình nằm trong `core/config.py` (dùng `pydantic-settings`), đọc từ biến môi trường:

| Biến | Mô tả | Ví dụ |
|---|---|---|
| `SCYLLA_HOSTS` | Danh sách host ScyllaDB | `127.0.0.1` |
| `SCYLLA_KEYSPACE` | Keyspace chính | `amigoact` |
| `JWT_SECRET` | Khóa ký JWT access | `dev-only-change-me` |
| `ENV` | Môi trường | `dev` / `test` / `prod` |

Không hard-code host, port, secret trong mã nguồn. Tài liệu biến mới phải cập nhật tại đây.

## Cấu trúc thư mục

```text
amigoact-be/
  main.py            # tạo app FastAPI, khai báo router, lifespan
  core/              # config, database, security, hashing, dependencies, exceptions
  auth/              # model, schemas, repository, service, router, interfaces
  users/             # tương tự auth
  <feature>/         # mỗi tính năng một thư mục ở root
  tests/
    unit/
    integration/
    regression/
  docs/
    ARCHITECTURE.md
```

Cấm tạo thư mục `src/`. Quy tắc chi tiết xem `AGENTS.md` mục 3.

## Kiểm thử

```bash
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run pytest tests/regression -q
uv run pytest -q
```

Không merge khi thiếu một trong ba loại kiểm thử.

## Tài liệu liên quan

- `AGENTS.md`: luật dành cho agent (tiếng Anh).
- `docs/ARCHITECTURE.md`: kiến trúc backend (tiếng Việt).
- `CONTRIBUTING.md`: quy trình đóng góp.
- `CODE_OF_CONDUCT.md`: quy tắc ứng xử.
- `SECURITY.md`: chính sách bảo mật.
- `LICENSE`: Apache-2.0.
