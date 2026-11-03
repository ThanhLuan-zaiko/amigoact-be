# Tải tệp

Tài liệu này mô tả phần tải ảnh của backend. Code nằm trong [`src/media/`](../src/media) và bảng nằm trong [`src/models/media.py`](../src/models/media.py).

## Phạm vi

Hiện chỉ nhận ảnh JPEG, PNG và WEBP, tối đa 5 MB mỗi tệp. Ảnh được dùng cho:

- ảnh đại diện của người dùng,
- logo và ảnh bìa của tổ chức,
- ảnh bìa của hoạt động,
- ảnh nền của mẫu chứng nhận,
- ảnh trong bài bảng tin, với bài công khai (xem [`posts.md`](posts.md)).

Ảnh nền của mẫu chứng nhận cũng tải lên qua API này, xem [`certificates.md`](certificates.md).

## Quy tắc nghiệp vụ

- Loại tệp được xác định từ vài byte đầu, không dựa vào tên file hay `Content-Type` do trình duyệt gửi. Tệp không phải ảnh thì bị từ chối dù tên có đuôi `.png`.
- Tên gốc chỉ được lưu để hiển thị, không bao giờ dùng để đặt tên file. Ký tự điều khiển, kể cả NUL, bị bỏ đi. Tên dài hơn 255 ký tự bị cắt.
- File được lưu trên ổ đĩa của server, trong thư mục `MEDIA_DIR` (mặc định `media`, tính từ thư mục khởi động server). Tên file là `<uuid>.<đuôi>` do server sinh, nên không thể đoán hay đưa đường dẫn ra ngoài thư mục này.
- Mỗi tệp mới có quyền `private`. Chỉ người tải lên mới xem được.
- Gắn ảnh vào đại diện, logo, ảnh bìa tổ chức hoặc ảnh bìa hoạt động thì ảnh chuyển thành `public`. Ai có đường link cũng xem được. Gỡ ảnh khỏi chỗ đó không đổi lại thành `private`.
- Chỉ người tải lên mới được gắn tệp của mình. Gắn vào tổ chức hoặc hoạt động còn cần quyền quản lý.
- Cùng một người tải lên cùng một nội dung hai lần thì nhận lại đúng tệp cũ. Người khác tải cùng nội dung thì được một bản riêng, không chia sẻ bản của người trước, vì quyền xem thuộc về người tải lên.
- Mỗi người tối đa 60 lần tải lên trong một giờ.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| POST | `/media` | Đã đăng nhập, gửi multipart với trường `file` |
| GET | `/media/{id}/file` | Ảnh công khai: ai cũng xem. Ảnh riêng: chỉ người tải lên |
| PUT | `/account/me/avatar` | Đã đăng nhập |
| PUT | `/organizations/{slug}/logo` | Ban quản trị tổ chức |
| PUT | `/organizations/{slug}/cover` | Ban quản trị tổ chức |
| PUT | `/activities/{id}/cover` | Ban quản trị hoạt động |

- `POST /media` trả về 201 với `id`, `url` (dạng `/media/{id}/file`), `mime`, `size_bytes`, `visibility` và `created_at`.
- Các đường dẫn gắn ảnh nhận `{ "asset_id": "<uuid>" }`. Gửi `null` để gỡ ảnh hiện tại. Trả về 204.
- Tạo và sửa tổ chức cũng nhận `logo_asset_id` và `cover_asset_id` trong body, nên ảnh có thể gắn ngay lúc tạo mà không cần gọi thêm.
- `GET /media/{id}/file` trả về nội dung ảnh, kèm `X-Content-Type-Options: nosniff`. Ảnh công khai có `Cache-Control: public`, ảnh riêng có `private`.
- Tệp riêng của người khác, tệp chưa tải xong và tệp không tồn tại đều trả về 404 `media_not_found`. Không phân biệt các trường hợp để khỏi lộ tệp nào đang tồn tại.

## Kiểm tra dữ liệu

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `file` | Không được rỗng | `file_empty` (400) |
| `file` | Tối đa 5 MB | `file_too_large` (413) |
| `file` | Phải là JPEG, PNG hoặc WEBP | `unsupported_media_type` (415) |
| `asset_id` | UUIDv7 hoặc `null` | `uuid_invalid` |
| Body | Không nhận trường lạ | `extra_forbidden` |

## Dữ liệu

`media_assets` là bảng đăng ký tệp. Mỗi dòng có người tải lên, loại ảnh, kích thước, khóa lưu trữ, quyền xem và trạng thái. `backend` hiện luôn là `local`, để sau này thêm object storage mà không đổi bảng.

Cột `file_hash` có ràng buộc UNIQUE trong schema, nên chỉ bản đầu tiên của một nội dung mới có hash. Các bản sao của người khác được lưu với `file_hash` trống.

## Cấu hình

| Biến trong `.env` | Ý nghĩa | Mặc định |
| ---- | ---- | ---- |
| `MEDIA_DIR` | Thư mục lưu file | `media` |

Thư mục `media/` nằm trong `.gitignore`. Tệp test dùng thư mục tạm, không ghi vào repo.

## Chưa có

- Kiểm duyệt ảnh (`media_moderation`). Sẽ làm cùng quản trị nền tảng ở giai đoạn 6.
- Xóa tệp và dọn tệp không được gắn vào đâu. Hiện tệp chỉ được thêm, không xóa. Mỗi tệp đã lưu thì tồn tại mãi.
- Đọc kích thước ảnh (`width`, `height`) và tạo ảnh thu nhỏ (`thumb_url`).
- Trả về `avatar` trong response của người dùng và ảnh bìa trong response của hoạt động. Tổ chức đã trả về `logo_url` và `cover_url` (xem [`organizations.md`](organizations.md)), nhưng chưa có đường đọc ID ảnh cho hai phần còn lại.
- Object storage (S3 hoặc GCS).
