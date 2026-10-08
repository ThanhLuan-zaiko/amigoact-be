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

Một lệnh duy nhất vừa khởi động server, vừa kiểm tra kết nối ScyllaDB
theo `.env` (kết quả hiện trong log lúc khởi động):

```bash
# dev (khởi động + kiểm tra DB + tự reload khi sửa code)
uv run --with fastapi-cli fastapi dev main.py --port 8100

# prod
uv run --with fastapi-cli fastapi run main.py --port 8100
```

Khi khởi động, log sẽ hiện trạng thái DB và danh sách route:

```text
INFO amigoact: ScyllaDB connected: ... keyspace=amigoact tables=73
INFO amigoact: Route: GET /health
```

Xem và thử các phương thức `GET`/`POST`/`PUT`/`DELETE` tại Swagger UI:

- `http://localhost:8100/docs` — tài liệu tương tác đầy đủ theo từng route.
- `http://localhost:8100/openapi.json` — schema thô.
- `http://localhost:8100/ready` — kết quả kiểm tra DB lúc khởi động.

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
| `SCYLLA_PORT` | Cổng CQL ScyllaDB | `9042` |
| `SCYLLA_DATACENTER` | Datacenter ScyllaDB (khớp replication trong `schemas.cql`) | `datacenter1` |
| `SCYLLA_KEYSPACE` | Keyspace chính | `amigoact` |
| `JWT_SECRET` | Khóa ký JWT access | `dev-only-change-me` |
| `ENV` | Môi trường | `dev` / `test` / `prod` |

Không hard-code host, port, secret trong mã nguồn. Tài liệu biến mới phải cập nhật tại đây.

## Đặt lại cơ sở dữ liệu (môi trường dev)

Script `reset_db.py` nạp lại `schemas.cql` vào ScyllaDB: đọc `.env`
(`SCYLLA_HOSTS`, `SCYLLA_KEYSPACE`), chỉ xóa đúng keyspace đó nên không
ảnh hưởng keyspace của repo khác, tự dò ScyllaDB qua TCP/Docker/WSL2 rồi
chạy từng câu lệnh CQL (kèm xác nhận, trừ khi dùng `--yes`).

```bash
uv run python reset_db.py --dry-run   # chỉ phân tích, không chạm DB
uv run python reset_db.py --yes       # xóa keyspace rồi tạo lại 73 bảng
uv run python reset_db.py --keyspace amigoact_test --yes
```

Trên Windows không có Docker CLI, script tự dùng `wsl docker ps` để phát
hiện container `scylladb` chạy trong WSL2.

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
