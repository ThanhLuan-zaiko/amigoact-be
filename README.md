# AmigoACT - Backend

Backend API cho hệ thống quản lý đăng ký và ghi nhận thành tích tình nguyện của Đoàn trường hoặc các tổ chức. Dự án đang ở giai đoạn đầu: hiện mới có phần kết nối cơ sở dữ liệu PostgreSQL.

## Yêu cầu

- [Python 3.14](https://www.python.org/downloads/) (phiên bản được ghim trong `.python-version`)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) để quản lý môi trường và thư viện
- PostgreSQL 14 trở lên, vì schema dùng các extension `citext` và `pg_trgm`

## Cài đặt

```bash
uv sync
cp .env.example .env
```

Mở file `.env` và điền `DATABASE_URL` theo định dạng chuỗi kết nối của SQLAlchemy với driver `psycopg`. Ứng dụng chỉ đọc giá trị này từ `.env`, không đọc từ biến môi trường của hệ điều hành. File `.env` đã được đưa vào `.gitignore`, không được commit.

## Chạy ứng dụng

```bash
uv run uvicorn connector.app:app --reload --port 8100
```

Khi khởi động, log sẽ cho biết kết nối cơ sở dữ liệu có thành công hay không:

- `Database connected: ...` nghĩa là kết nối thành công. Mật khẩu được che trong log.
- `Database connection failed: ...` nghĩa là không kết nối được. Hãy kiểm tra `DATABASE_URL` trong `.env` và xem PostgreSQL đã chạy chưa.

## Cơ sở dữ liệu

Schema nằm trong [`schema.sql`](schema.sql). Dự án dùng một database riêng (`amigoact`), không dùng chung với ứng dụng khác, vì reset sẽ xóa toàn bộ schema `public` của database trong `.env`. Để xem database đích và danh sách bảng hiện có, chạy:

```bash
uv run python scripts/reset_database.py
```

Lệnh này chỉ đọc và không thay đổi gì. Để xóa toàn bộ dữ liệu và nạp lại schema, chạy với `--apply`. Script sẽ yêu cầu gõ lại tên database để xác nhận. Thao tác này chỉ tác động tới database trong `.env` và không thể hoàn tác.

## Kiểm thử

```bash
uv run pytest
```

Test được chia thành ba nhóm trong `tests/`:

- `unit/`: kiểm thử logic không cần cơ sở dữ liệu.
- `integration/`: kiểm thử kết nối tới cơ sở dữ liệu trong `.env`.
- `regression/`: khóa lại các hành vi đã sửa hoặc không được thay đổi.

Các test tích hợp cần PostgreSQL đang chạy và `.env` hợp lệ.

## Kiểm tra chất lượng

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy connector scripts tests main.py
uv lock --check
```

Mỗi push và pull request đều chạy 13 gate CI trong `.github/workflows/ci.yml`, gồm: kiểm tra lockfile, lint, format, type check, test, giới hạn số dòng của file `.py`, kiểm tra tiếng Anh trong code, không có file rác, quét secret, và kiểm tra workflow.

## Cấu trúc thư mục

```
amigoact-be/
├── connector/       code của ứng dụng: config.py, database.py, app.py, reset.py
├── scripts/         script tiện ích, ví dụ reset_database.py
├── tests/           unit, integration, regression
├── .github/         CI và các mẫu issue, pull request
├── schema.sql       schema PostgreSQL
├── main.py          điểm vào đơn giản
└── pyproject.toml   cấu hình dự án và thư viện
```

Không đặt code trong thư mục `src/`. Quy tắc phát triển chi tiết nằm trong [AGENTS.md](AGENTS.md).

## Đóng góp

Xem [CONTRIBUTING.md](.github/CONTRIBUTING.md) để biết cách tạo nhánh, commit và mở pull request. Báo lỗi bảo mật theo hướng dẫn trong [SECURITY.md](.github/SECURITY.md), không mở issue công khai.

## Giấy phép

Dự án được phát hành theo giấy phép MIT. Xem [LICENSE](LICENSE).
