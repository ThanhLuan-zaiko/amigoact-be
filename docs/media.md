# Tải tệp

Tài liệu này mô tả phần tải ảnh của backend. Code nằm trong [`src/media/`](../src/media) và bảng nằm trong [`src/models/media.py`](../src/models/media.py).

## Phạm vi

Nhận ảnh JPEG, PNG, WEBP tối đa 5 MB và video MP4, WEBM tối đa 50 MB. Video chỉ gắn được vào bộ sưu tập của tổ chức (xem [`organizations.md`](organizations.md)). Logo, ảnh đại diện, ảnh bìa, ảnh nền chứng nhận và ảnh bài viết từ chối video bằng `unsupported_media_type`. Ảnh được dùng cho:

- ảnh đại diện của người dùng,
- logo và ảnh bìa của tổ chức,
- ảnh bìa của hoạt động,
- ảnh nền của mẫu chứng nhận,
- ảnh trong bài bảng tin, với bài công khai (xem [`posts.md`](posts.md)).

Ảnh nền của mẫu chứng nhận cũng tải lên qua API này, xem [`certificates.md`](certificates.md).

## Quy tắc nghiệp vụ

- Loại tệp được xác định từ vài byte đầu, không dựa vào tên file hay `Content-Type` do trình duyệt gửi. Tệp không phải ảnh thì bị từ chối dù tên có đuôi `.png`.
- Tên gốc chỉ được lưu để hiển thị, không bao giờ dùng để đặt tên file. Ký tự điều khiển, kể cả NUL, bị bỏ đi. Tên dài hơn 255 ký tự bị cắt.
- File được lưu trên ổ đĩa của server, trong thư mục `MEDIA_DIR` (mặc định `media`, tính từ thư mục khởi động server). Tên file do server sinh từ UUID, không lấy từ tên người gửi, nên không thể đoán hay đưa đường dẫn ra ngoài thư mục này. Cách sắp xếp thư mục xem mục [Cây thư mục](#cây-thư-mục).
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

## Cây thư mục

Gốc là `MEDIA_DIR`. Thư mục đầu tiên là tài khoản đã tải file lên, nên nhìn cây là biết file của ai:

```
media/
  users/<user_id>/
    by-date/<yyyy>/<mm>/<dd>/<asset_id>.<đuôi>        file thật, lưu một lần
    avatar/<asset_id>.<đuôi>                          ảnh đại diện của người này
    organizations/<org_id>/logo/<asset_id>.<đuôi>
    organizations/<org_id>/cover/<asset_id>.<đuôi>
    organizations/<org_id>/gallery/<asset_id>.<đuôi>
    activities/<activity_id>/cover/<asset_id>.<đuôi>
```

- `by-date` chứa mọi file người này đã tải lên, theo ngày tải. Đây là bản duy nhất của file.
- Các thư mục khác chứa liên kết cứng (hard link) tới file trong `by-date`. Một file dùng ở nhiều chỗ thì có nhiều liên kết, mỗi chỗ một liên kết. Nếu hệ thống file không hỗ trợ liên kết cứng thì file được sao chép.
- Gỡ một chỗ dùng chỉ xóa liên kết của chỗ đó. File thật không bị xóa.
- Tên thư mục chỉ là chữ thường, dấu gạch ngang hoặc UUID. Mọi tên khác bị từ chối, nên không thể đưa đường dẫn ra ngoài cây.
- Liên kết chỉ là bản hiển thị theo thư mục. Nguồn sự thật vẫn là bảng trong database.

Đã nối liên kết cho: ảnh đại diện, logo, ảnh bìa và bộ sưu tập của tổ chức (kể cả lúc tạo), ảnh bìa hoạt động. Chưa nối: ảnh bài viết và ảnh nền mẫu chứng nhận. Các file này vẫn nằm trong `by-date`, chỉ chưa có liên kết.

Code: [`src/media/placement.py`](../src/media/placement.py) và [`src/media/storage.py`](../src/media/storage.py).

### Backfill

File tải lên trước khi có cây thư mục nằm phẳng trong `media/` và chưa có liên kết. Chạy script để chuyển chúng vào `by-date` và tạo lại các liên kết còn thiếu:

```bash
uv run python scripts/backfill_media_tree.py          # chỉ báo cáo, không đổi gì
uv run python scripts/backfill_media_tree.py --apply  # chuyển file và ghi liên kết
```

Script đọc `.env` như các script khác. Với `--apply`, mọi thay đổi trong database được ghi trong một transaction. Nếu commit lỗi, file đã chuyển được đưa về chỗ cũ. Chạy lại an toàn: liên kết đã có thì bỏ qua.

## Dọn tệp không còn dùng

Khi tổ chức bị xóa cứng trong database, hoặc một lần tải lên không bao giờ được gắn vào đâu, file vẫn nằm trên ổ đĩa. Script sau dọn các file đó:

```bash
uv run python scripts/cleanup_media.py                    # chỉ báo cáo, không đổi gì
uv run python scripts/cleanup_media.py --apply            # đánh dấu và xóa
uv run python scripts/cleanup_media.py --user <user_id>   # chỉ file của một tài khoản
uv run python scripts/cleanup_media.py --min-age-days 60  # giữ file mới hơn 60 ngày
```

Quy tắc:

- Một tệp còn dùng khi có khóa ngoại trỏ tới nó. Danh sách khóa ngoại được đọc từ `pg_constraint`, nên cả khóa không khai báo trong model, như `users.avatar_media_id`, cũng được tính. Tổ chức đã xóa mềm vẫn giữ logo và bộ sưu tập, nên ảnh của nó không bị dọn.
- Tải lên mới được giữ tối thiểu 30 ngày (mặc định). Tệp được ghi trước khi dòng trong database được commit, và người dùng có thể gắn ảnh sau khi tải lên, nên tuổi tính theo `created_at` của dòng.
- Tệp đã tải lên, quá hạn, và không có khóa ngoại nào trỏ tới: dòng chuyển sang `upload_status = 'deleted'`, ghi `deleted_at`, xóa `file_hash` để lần tải lại cùng nội dung tạo tệp mới. Mọi bản của tệp, gồm bản trong `by-date` và các liên kết, bị xóa.
- File không có dòng nào, hoặc có dòng đã `deleted`: xóa khi thời gian sửa đổi của file đã quá hạn.
- Thư mục rỗng sau khi xóa được gỡ, từ sâu lên nông.
- Chỉ đụng tới tên có dạng `<asset_id>.<đuôi>`. Tệp khác trong cây bị bỏ qua. Tệp phẳng cũ dưới gốc `MEDIA_DIR` cũng không bị đụng tới.
- Dry run không ghi gì. Có `--apply` thì DB được commit trước, rồi mới xóa file. Nếu file không xóa được, lỗi được in ra và script trả về mã 1. Lần chạy sau sẽ xóa nốt file đó, vì dòng của nó đã `deleted`.

Script khóa từng dòng trước khi kiểm tra lại, nên không xóa nhầm tệp vừa được gắn. Thứ tự là: kế hoạch được lập lúc chạy, sau đó mỗi tệp được khóa, kiểm tra lại khóa tham chiếu, rồi mới đánh dấu xóa. Việc gắn tệp (logo, ảnh bìa, bộ sưu tập, ảnh đại diện, ảnh bài viết, ảnh nền mẫu chứng nhận) cũng khóa đúng dòng đó cho đến khi commit, nên hai việc không thể xen vào nhau. Tệp đã gắn trong lúc chạy được giữ lại, và dòng kết quả của lần chạy có thể ít hơn kế hoạch in ra.

## Kiểm tra dữ liệu

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `file` | Không được rỗng | `file_empty` (400) |
| `file` | Tối đa 5 MB | `file_too_large` (413) |
| `file` | Video tối đa 50 MB | `video_too_large` (413) |
| `file` | Phải là JPEG, PNG, WEBP, MP4 hoặc WEBM | `unsupported_media_type` (415) |
| `asset_id` | UUIDv7 hoặc `null` | `uuid_invalid` |
| Body | Không nhận trường lạ | `extra_forbidden` |

## Dữ liệu

`media_assets` là bảng đăng ký tệp. Mỗi dòng có người tải lên, loại ảnh, kích thước, khóa lưu trữ, quyền xem và trạng thái. `backend` hiện luôn là `local`, để sau này thêm object storage mà không đổi bảng.

Cột `file_hash` có ràng buộc UNIQUE trong schema, nên chỉ bản đầu tiên của một nội dung mới có hash. Các bản sao của người khác được lưu với `file_hash` trống.

Khi script dọn tệp đánh dấu một dòng là `deleted`, dòng đó giữ lại để tra cứu, nhưng `file_hash` được xóa và tệp không còn truy cập được (`404 media_not_found`). Một tệp khác của cùng người vẫn có thể được gắn lại trong khi chạy: không bị chặn, vì hash đã được xóa.

Khi tổ chức bị xóa mềm, logo, ảnh bìa và bộ sưu tập của nó chuyển sang `private` nếu không còn chỗ nào khác dùng tệp đó, và được công khai lại khi khôi phục. Xem [`organizations.md`](organizations.md#xóa-tổ-chức).

## Cấu hình

| Biến trong `.env` | Ý nghĩa | Mặc định |
| ---- | ---- | ---- |
| `MEDIA_DIR` | Thư mục lưu file | `media` |

Thư mục `media/` nằm trong `.gitignore`. Tệp test dùng thư mục tạm, không ghi vào repo.

## Chưa có

- Đọc tệp lớn theo luồng. `POST /media` hiện đọc cả tệp vào bộ nhớ, nên mỗi video có thể chiếm tới 50 MB RAM trong lúc tải.
- Kiểm tra sâu nội dung video. Hiện chỉ nhận diện định dạng từ vài byte đầu.
- Kiểm duyệt ảnh (`media_moderation`). Sẽ làm cùng quản trị nền tảng ở giai đoạn 6.
- Xóa tệp qua API. Không có API nào xóa tệp. Tệp chỉ bị xóa bởi script dọn tệp, xem mục [Dọn tệp không còn dùng](#dọn-tệp-không-còn-dùng).
- Đọc kích thước ảnh (`width`, `height`) và tạo ảnh thu nhỏ (`thumb_url`).
- Trả về `avatar` trong response của người dùng và ảnh bìa trong response của hoạt động. Tổ chức đã trả về `logo_url` và `cover_url` (xem [`organizations.md`](organizations.md)), nhưng chưa có đường đọc ID ảnh cho hai phần còn lại.
- Object storage (S3 hoặc GCS).
