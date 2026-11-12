# AmigoACT - Backend

Backend API cho hệ thống quản lý đăng ký và ghi nhận thành tích tình nguyện của Đoàn trường hoặc các tổ chức. Dự án đang ở giai đoạn đầu: hiện đã có kết nối PostgreSQL và các chức năng tài khoản dùng JWT.

## Yêu cầu

- [Python 3.14](https://www.python.org/downloads/) (phiên bản được ghim trong `.python-version`)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) để quản lý môi trường và thư viện
- PostgreSQL 14 trở lên, vì schema dùng các extension `citext` và `pg_trgm`

## Cài đặt

```bash
uv sync
cp .env.example .env
```

Mở file `.env` và điền `DATABASE_URL` theo định dạng chuỗi kết nối của SQLAlchemy với driver `psycopg`, cùng `JWT_SECRET` là một chuỗi ngẫu nhiên dài ít nhất 32 ký tự, và `CHAT_ENCRYPTION_KEY` là 32 byte ngẫu nhiên mã hóa base64 (tạo bằng `openssl rand -base64 32`). Mất `CHAT_ENCRYPTION_KEY` thì tin nhắn đã lưu không đọc được nữa. Ứng dụng chỉ đọc các giá trị này từ `.env`, không đọc từ biến môi trường của hệ điều hành. File `.env` đã được đưa vào `.gitignore`, không được commit.

Nếu chưa đặt `SMTP_HOST`, email tài khoản (kèm liên kết bí mật) sẽ được ghi vào log để tiện phát triển. Môi trường production bắt buộc phải đặt `SMTP_HOST`.

## Chạy ứng dụng

```bash
uv run uvicorn src.app:app --reload --port 8100
```

Khi khởi động, log sẽ cho biết kết nối cơ sở dữ liệu có thành công hay không:

- `Database connected: ...` nghĩa là kết nối thành công. Mật khẩu được che trong log.
- `Database connection failed: ...` nghĩa là không kết nối được. Hãy kiểm tra `DATABASE_URL` trong `.env` và xem PostgreSQL đã chạy chưa.

## Cơ sở dữ liệu

Schema nằm trong [`schema.sql`](schema.sql). Dự án dùng một database riêng (`amigoact`), không dùng chung với ứng dụng khác, vì reset sẽ xóa toàn bộ schema `public` của database trong `.env`. Để xem database đích và danh sách bảng hiện có, chạy:

```bash
uv run python scripts/reset_database.py
```

Lệnh này chỉ đọc và không thay đổi gì. Nếu server chưa có database trong `.env`, dry run chỉ báo là chưa có.

Để xóa toàn bộ dữ liệu và nạp lại schema, chạy với `--apply`. Nếu database chưa tồn tại, `--apply` sẽ tạo nó trước, rồi nạp schema. Script luôn yêu cầu gõ lại tên database để xác nhận. Thao tác này chỉ tác động tới database trong `.env` và không thể hoàn tác. Script cần user có quyền tạo database (`CREATEDB`) khi database chưa có.

## Tài liệu

Tài liệu chi tiết nằm trong thư mục [`docs/`](docs):

- [Lộ trình phát triển](docs/roadmap.md): kế hoạch theo giai đoạn và các quyết định sản phẩm.
- [Xác thực và tài khoản](docs/authentication.md): API, quy tắc dữ liệu, cấu hình và triển khai.
- [Bảo vệ API](docs/security.md): khóa nội bộ `INTERNAL_API_KEY` và `CORS_ORIGINS`.
- [Tổ chức và thành viên](docs/organizations.md): quy tắc nghiệp vụ, API và kiểm tra dữ liệu.
- [Hoạt động và đăng ký](docs/activities.md): vòng đời hoạt động, ca, danh sách chờ, API và kiểm tra dữ liệu.
- [Điểm danh và giờ tình nguyện](docs/attendance.md): phiên điểm danh, QR, nhập mã, sổ giờ và khiếu nại.
- [Chứng nhận](docs/certificates.md): cấp, thu hồi, xác minh công khai theo serial.
- [Thông báo](docs/notifications.md): loại thông báo, tùy chọn kênh, API và email.
- [Tải tệp](docs/media.md): tải ảnh, quyền xem, gắn ảnh vào đại diện, logo và ảnh bìa.
- [Bảng tin](docs/posts.md): bài đăng, bình luận, thẻ, ghim và các danh sách trên trang chủ.
- [Chat](docs/chat.md): phòng chung, kênh, tin nhắn riêng, và kết nối thời gian thực.
- [Thời gian thực](docs/realtime.md): socket chung, topic, gửi sự kiện, nhiều worker.

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
uv run mypy src scripts tests main.py
uv lock --check
```

Mỗi push và pull request đều chạy 13 gate CI trong `.github/workflows/ci.yml`, gồm: kiểm tra lockfile, lint, format, type check, test, giới hạn số dòng của file `.py`, kiểm tra tiếng Anh trong code, không có file rác, quét secret, và kiểm tra workflow.

## Cấu trúc thư mục

```
amigoact-be/
├── src/             code của ứng dụng: config.py, database.py, app.py, reset.py
├── docs/            tài liệu chi tiết
├── scripts/         script tiện ích, ví dụ reset_database.py
├── tests/           unit, integration, regression
├── .github/         CI và các mẫu issue, pull request
├── schema.sql       schema PostgreSQL
├── main.py          điểm vào đơn giản
└── pyproject.toml   cấu hình dự án và thư viện
```

Code của ứng dụng nằm trong thư mục `src/`. Quy tắc phát triển chi tiết nằm trong [AGENTS.md](AGENTS.md).

## Đóng góp

Xem [CONTRIBUTING.md](.github/CONTRIBUTING.md) để biết cách tạo nhánh, commit và mở pull request. Báo lỗi bảo mật theo hướng dẫn trong [SECURITY.md](.github/SECURITY.md), không mở issue công khai.

## Giấy phép

Dự án được phát hành theo giấy phép MIT. Xem [LICENSE](LICENSE).
