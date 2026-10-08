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
| `JWT_SECRET` | Khóa ký JWT access (production tối thiểu 32 byte) | `dev-only-change-me` |
| `JWT_ACCESS_TTL_SECONDS` | Tuổi thọ JWT access (giây) | `900` |
| `REFRESH_TOKEN_TTL_DAYS` | Tuổi thọ refresh token (ngày) | `14` |
| `VERIFICATION_CODE_TTL_MINUTES` | Tuổi thọ mã xác minh email (phút) | `15` |
| `RESET_CODE_TTL_MINUTES` | Tuổi thọ mã đặt lại mật khẩu (phút) | `15` |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_WINDOW_SECONDS` | Giới hạn đăng nhập sai | `5` / `60` |
| `CODE_MAX_ATTEMPTS` / `CODE_WINDOW_SECONDS` | Giới hạn nhập mã sai | `5` / `300` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `MAIL_FROM` | Gửi email mã xác minh (bỏ trống `SMTP_HOST` thì không gửi, xem endpoint dev bên dưới) | `""` / `587` / `""` / `""` / `no-reply@amigoact.local` |
| `FRONTEND_URLS` | Danh sách origin frontend cho CORS (phân tách dấu phẩy, bắt buộc liệt kê rõ vì cookie cần `credentials`) | `http://localhost:5173` |
| `ENV` | Môi trường | `dev` / `test` / `prod` |

Không hard-code host, port, secret trong mã nguồn. Tài liệu biến mới phải cập nhật tại đây.

## Xác thực (`auth/`)

- Đăng ký: `POST /auth/register` (`201`) với `email`, `phone` (di động Việt Nam), `password` (≥ 8 ký tự gồm hoa, thường, số, ký tự đặc biệt), `full_name`. `email` và `phone` đều duy nhất.
- Xác minh email hiện tạm gỡ khỏi luồng (đăng ký không gửi mã, đăng nhập không chặn). Các endpoint `POST /auth/verify-email`, `POST /auth/resend-verification` vẫn hoạt động để bật lại sau, cùng mã 6 số hết hạn sau `VERIFICATION_CODE_TTL_MINUTES`.
- Đăng nhập: `POST /auth/login` trả JWT access (`Authorization: Bearer`) và cookie refresh `HttpOnly`. Xoay vòng tại `POST /auth/refresh`; dùng lại token cũ sẽ thu hồi cả họ token. Thoát: `POST /auth/logout` (`204`), `POST /auth/logout-all` (`204`). Phiên hiện tại: `GET /auth/me`.
- Quên mật khẩu: `POST /auth/forgot-password` (luôn `202`), `POST /auth/reset-password` (đổi mật khẩu và thu hồi mọi phiên). Đổi mật khẩu khi đã login: `POST /auth/change-password`.
- Mọi lỗi tuân envelope `{"code": "EMAIL_TAKEN", "message": "..."}` (`code` tiếng Anh, frontend dịch sang tiếng Việt).
- Môi trường `dev` có thêm `POST /auth/dev/challenge-code` trả mã plaintext để thử tay khi chưa cấu hình SMTP (route này `404` ở mọi môi trường khác).

## Đặt lại cơ sở dữ liệu (môi trường dev)

Script `reset_db.py` nạp lại `schemas.cql` vào ScyllaDB: đọc `.env`
(`SCYLLA_HOSTS`, `SCYLLA_KEYSPACE`), chỉ xóa đúng keyspace đó nên không
ảnh hưởng keyspace của repo khác, tự dò ScyllaDB qua TCP/Docker/WSL2 rồi
chạy từng câu lệnh CQL (kèm xác nhận, trừ khi dùng `--yes`).

```bash
uv run python reset_db.py --dry-run   # chỉ phân tích, không chạm DB
uv run python reset_db.py --yes       # xóa keyspace rồi tạo lại 76 bảng
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
