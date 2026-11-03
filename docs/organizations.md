# Tổ chức và thành viên

Tài liệu này mô tả phần tổ chức của backend. Code nằm trong [`src/organizations/`](../src/organizations).

## Quy tắc nghiệp vụ

- Mọi người dùng đã đăng nhập đều tạo được tổ chức và trở thành chủ sở hữu. Không cần là sinh viên, cũng không cần duyệt.
- Mỗi tổ chức có một `slug` sinh từ tên, ví dụ `Đoàn trường` thành `doan-truong`. Trùng tên thì thêm hậu tố ngẫu nhiên. Slug không đổi sau khi tạo.
- `mine` và `new` là slug dành riêng, vì chúng là đường dẫn cố định.
- Tổ chức bị tạm ngưng hoặc đã xóa mềm được coi như không tồn tại.

### Vai trò

| Vai trò | Xác định bằng | Được làm |
| ---- | ---- | ---- |
| Chủ sở hữu | `organizations.owner_id` | Mọi việc của quản trị viên, thêm việc cấp và bỏ quyền quản trị, xóa quản trị viên |
| Quản trị viên | Role `admin` của tổ chức trong `user_roles` | Sửa hồ sơ, duyệt yêu cầu, xóa thành viên thường |
| Thành viên | `organization_members.status = 'active'` | Xem danh sách thành viên |

Role `admin` được tạo cùng tổ chức, nên không cần dữ liệu khởi tạo trong `schema.sql`. Chỉ thành viên đang `active` mới có vai trò, kể cả khi còn dòng cũ trong `user_roles`.

### Tham gia

| Tình huống | Kết quả |
| ---- | ---- |
| Tổ chức `open` | Thành viên ngay |
| Tổ chức `invite` | Trạng thái `applied`, chờ duyệt |
| Người đã rời tổ chức `open` | Thành viên ngay |
| Người đã bị xóa | Luôn phải chờ duyệt, kể cả tổ chức `open` |
| Bị từ chối | Chờ 7 ngày mới gửi lại được (`application_cooldown`) |

Chủ sở hữu không rời được tổ chức và không bị xóa. Hiện chưa có chức năng chuyển quyền sở hữu và xóa tổ chức.

### Thông tin pháp lý và ảnh

- Thông tin pháp lý không bắt buộc: tên pháp lý (`legal_name`), mã số thuế (`tax_code`), số giấy phép hoặc quyết định thành lập (`license_number`), người đại diện pháp luật (`legal_rep_name`) và chức vụ (`legal_rep_position`). Người tạo và quản trị viên điền được cả khi tạo lẫn khi sửa.
- Số giấy tờ tùy thân của người đại diện không thu thập ở tổ chức. Nó chỉ có ở hồ sơ tài khoản.
- `legal_status` chỉ đọc, gồm `none`, `pending`, `verified`. Mới tạo luôn là `none`. Gửi `legal_status` trong body bị từ chối bằng `extra_forbidden`, nên người dùng không tự xác nhận được. Quy trình xác minh của quản trị nền tảng chưa có.
- Logo và ảnh bìa gửi bằng `logo_asset_id` và `cover_asset_id`, là ID của ảnh đã tải lên qua `POST /media`. Chỉ người tải lên mới gắn được ảnh của mình. Ảnh không tồn tại, ảnh riêng của người khác, hoặc ảnh chưa tải xong đều trả về 404 `media_not_found`. Khi tạo, nếu ảnh không hợp lệ thì tổ chức không được tạo.
- Gắn ảnh làm ảnh thành `public`. Gửi `null` để gỡ ảnh. Khi không gửi trường ảnh, ảnh giữ nguyên.
- Phản hồi chi tiết trả về `logo_url` và `cover_url` dạng `/media/{id}/file`, hoặc `null`. Danh sách không có hai trường này, để không phải truy vấn thêm cho mỗi dòng.
- Thông tin pháp lý và ảnh công khai với mọi người, vì `GET /organizations/{slug}` không cần đăng nhập.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| POST | `/organizations` | Đã đăng nhập |
| GET | `/organizations?q=&limit=&offset=` | Công khai |
| GET | `/organizations/mine` | Đã đăng nhập |
| GET | `/organizations/{slug}` | Công khai |
| PATCH | `/organizations/{slug}` | Quản trị viên |
| POST | `/organizations/{slug}/join` | Đã đăng nhập |
| DELETE | `/organizations/{slug}/membership` | Đã đăng nhập: rời hoặc rút yêu cầu |
| GET | `/organizations/{slug}/members` | Thành viên |
| PATCH | `/organizations/{slug}/members/{user_id}` | Chủ sở hữu |
| DELETE | `/organizations/{slug}/members/{user_id}` | Quản trị viên |
| GET | `/organizations/{slug}/applications` | Quản trị viên |
| POST | `/organizations/{slug}/applications/{user_id}/approve` | Quản trị viên |
| POST | `/organizations/{slug}/applications/{user_id}/reject` | Quản trị viên |

Danh sách thành viên và danh sách yêu cầu không trả email hay số điện thoại. Danh sách phân trang trả `next_offset`, bằng `null` ở trang cuối. Tạo tổ chức giới hạn 10 lần mỗi giờ, tham gia giới hạn 30 lần mỗi giờ cho mỗi người dùng.

## Kiểm tra dữ liệu

Bộ kiểm tra dùng chung nằm trong [`src/validation.py`](../src/validation.py). Lỗi trả về HTTP 422, mỗi lỗi có `loc` là tên trường và `type` là mã cố định.

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `name` | 2 đến 120 ký tự, một dòng, có chữ hoặc số | `string_too_short`, `string_too_long`, `text_invalid`, `organization_name_invalid` |
| `description` | Tối đa 2000 ký tự, được xuống dòng | `string_too_long`, `text_invalid` |
| `org_type` | `organization`, `club`, `group`, `business` | `literal_error` |
| `join_policy` | `open`, `invite` | `literal_error` |
| `email` | Email hợp lệ | `value_error` |
| `phone` | Theo quy tắc số điện thoại của tài khoản | `phone_invalid` |
| `website` | `http` hoặc `https`, có tên miền, không chứa tài khoản hay khoảng trắng, tối đa 300 ký tự | `website_invalid`, `string_too_long` |
| `address` | Tối đa 500 ký tự, một dòng | `string_too_long`, `text_invalid` |
| `city` | Tối đa 120 ký tự, một dòng | `string_too_long`, `text_invalid` |
| `legal_name`, `license_number`, `legal_rep_name`, `legal_rep_position` | Tối đa 200 ký tự, một dòng, không được để trống | `string_too_long`, `text_invalid` |
| `tax_code` | 10 chữ số, hoặc 13 chữ số với chi nhánh, lưu dạng `NNNNNNNNNN-NNN` | `tax_code_invalid` |
| `logo_asset_id`, `cover_asset_id` | UUIDv7 của ảnh đã tải lên, hoặc `null` | `uuid_invalid`, `media_not_found` (404) |
| `legal_status` | Chỉ đọc, không gửi được | `extra_forbidden` |
| `message` | Tối đa 1000 ký tự, được xuống dòng | `string_too_long`, `text_invalid` |
| `role` | `admin`, `member` | `literal_error` |
| Trường lạ, ví dụ `owner_id` | Bị từ chối | `extra_forbidden` |
| `{slug}` | Chữ, số, dấu gạch ngang, tối đa 80 ký tự | `string_pattern_mismatch` |
| `{user_id}`, `{session_id}` | Phải là UUIDv7 | `uuid_invalid` |
| `q` | Tối đa 100 ký tự, không có ký tự điều khiển | `string_too_long`, `string_pattern_mismatch` |
| `limit`, `offset` | `limit` từ 1 đến 100, `offset` từ 0 đến 100000 | `greater_than_equal`, `less_than_equal` |

Ký tự điều khiển bị từ chối ở mọi trường văn bản, kể cả họ tên và địa chỉ của tài khoản. Nếu không chặn, ký tự NUL sẽ làm PostgreSQL báo lỗi và API trả về 500.

## Khóa chính

Mọi khóa chính đều là UUIDv7, sinh bằng `uuid.uuid7()`. Test `test_new_ids_are_uuid7` khóa quy tắc này cho người dùng, tổ chức và vai trò.

## Mã lỗi nghiệp vụ

| Mã | HTTP |
| ---- | ---- |
| `organization_not_found` | 404 |
| `organization_forbidden` | 403 |
| `already_member`, `already_applied` | 409 |
| `application_cooldown` | 409 |
| `membership_suspended` | 403 |
| `owner_cannot_leave`, `owner_role_locked`, `owner_cannot_be_removed`, `cannot_remove_self` | 409 |
| `not_a_member`, `member_not_found`, `application_not_found` | 404 |
