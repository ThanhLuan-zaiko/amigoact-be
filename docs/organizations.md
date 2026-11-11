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

Chủ sở hữu không rời được tổ chức và không bị gỡ khỏi tổ chức. Chủ sở hữu có thể xóa mềm tổ chức, xem mục [Xóa tổ chức](#xóa-tổ-chức). Chưa có chức năng chuyển quyền sở hữu và khôi phục tổ chức đã xóa.

### Thông tin pháp lý và ảnh

- Thông tin pháp lý không bắt buộc: tên pháp lý (`legal_name`), mã số thuế (`tax_code`), số giấy phép hoặc quyết định thành lập (`license_number`), người đại diện pháp luật (`legal_rep_name`) và chức vụ (`legal_rep_position`). Người tạo và quản trị viên điền được cả khi tạo lẫn khi sửa.
- Số giấy tờ tùy thân của người đại diện không thu thập ở tổ chức. Nó chỉ có ở hồ sơ tài khoản.
- `legal_status` chỉ đọc, gồm `none`, `pending`, `verified`. Mới tạo luôn là `none`. Gửi `legal_status` trong body bị từ chối bằng `extra_forbidden`, nên người dùng không tự xác nhận được. Quy trình xác minh của quản trị nền tảng chưa có.
- Logo và ảnh bìa gửi bằng `logo_asset_id` và `cover_asset_id`, là ID của ảnh đã tải lên qua `POST /media`. Chỉ người tải lên mới gắn được ảnh của mình. Ảnh không tồn tại, ảnh riêng của người khác, hoặc ảnh chưa tải xong đều trả về 404 `media_not_found`. Khi tạo, nếu ảnh không hợp lệ thì tổ chức không được tạo.
- Gắn ảnh làm ảnh thành `public`. Gửi `null` để gỡ ảnh. Khi không gửi trường ảnh, ảnh giữ nguyên.
- Phản hồi chi tiết trả về `logo_url` và `cover_url` dạng `/media/{id}/file`, hoặc `null`. Mọi danh sách tổ chức cũng có hai trường này. Chúng lấy từ dòng tổ chức đã được đọc sẵn, nên không tốn truy vấn thêm.
- Thông tin pháp lý và ảnh công khai với mọi người, vì `GET /organizations/{slug}` không cần đăng nhập.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| POST | `/organizations` | Đã đăng nhập |
| GET | `/organizations?q=&limit=&offset=&exclude_owned=` | Công khai. `exclude_owned=true` bỏ tổ chức người đang đăng nhập sở hữu ngay trong truy vấn, nên mỗi trang vẫn đủ số dòng. Khách không đăng nhập thì tham số này không có tác dụng |
| GET | `/organizations/mine` | Đã đăng nhập |
| GET | `/organizations/{slug}` | Công khai |
| PATCH | `/organizations/{slug}` | Quản trị viên |
| DELETE | `/organizations/{slug}` | Chủ sở hữu: xóa mềm, trả về 204 |
| GET | `/organizations/mine/deleted` | Đã đăng nhập: thùng rác của chính mình |
| POST | `/organizations/mine/deleted/{org_id}/restore` | Chủ sở hữu: khôi phục từ thùng rác |
| POST | `/organizations/{slug}/join` | Đã đăng nhập |
| DELETE | `/organizations/{slug}/membership` | Đã đăng nhập: rời hoặc rút yêu cầu |
| GET | `/organizations/{slug}/members` | Thành viên |
| PATCH | `/organizations/{slug}/members/{user_id}` | Chủ sở hữu |
| DELETE | `/organizations/{slug}/members/{user_id}` | Quản trị viên |
| GET | `/organizations/{slug}/applications` | Quản trị viên |
| POST | `/organizations/{slug}/applications/{user_id}/approve` | Quản trị viên |
| POST | `/organizations/{slug}/applications/{user_id}/reject` | Quản trị viên |

`GET /organizations/mine` trả thêm `logo_url` và `cover_url`, cùng dạng với chi tiết tổ chức, để thẻ "Tổ chức của tôi" hiện ảnh. Hai trường này lấy từ dòng tổ chức, không tốn truy vấn thêm.

Danh sách thành viên và danh sách yêu cầu không trả email hay số điện thoại. Danh sách phân trang trả `next_offset`, bằng `null` ở trang cuối. Tham gia giới hạn 30 lần mỗi giờ cho mỗi người dùng.

Mỗi danh sách trả thêm `total` là tổng số dòng khớp, để giao diện đánh số trang. Thành viên, yêu cầu, hoạt động và đăng ký cũng có trường này.

## Bộ sưu tập

Mỗi tổ chức có tối đa 10 ảnh hoặc video, lưu trong bảng `organization_media`. Code nằm trong `src/organizations/gallery.py`.

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| GET | `/organizations/{slug}/gallery` | Công khai |
| POST | `/organizations/{slug}/gallery` | Ban quản trị, chỉ gắn tệp của chính mình, body `{ "asset_id": "<uuid>" }` |
| DELETE | `/organizations/{slug}/gallery/{asset_id}` | Ban quản trị |

Quá 10 tệp trả về 409 `gallery_full`. Gắn lại cùng một tệp không tạo dòng mới. Gắn vào bộ sưu tập làm tệp thành công khai. Gỡ khỏi bộ sưu tập không xóa tệp.

Khi tạo tổ chức, có thể gửi `gallery_asset_ids` là danh sách tối đa 10 ID ảnh hoặc video đã tải lên qua `POST /media`. Mỗi ID trùng lặp chỉ tạo một tệp, và thứ tự giữ như lúc gửi. Nếu một tệp không hợp lệ hoặc không phải của người tạo, trả về 404 `media_not_found` và tổ chức không được tạo. Danh sách rỗng hoặc không gửi trường này thì không có gì được thêm vào bộ sưu tập.

Database đã có sẵn cần tạo bảng này bằng câu `CREATE TABLE IF NOT EXISTS organization_media` trong `schema.sql`. Không cần reset.

## Trường bắt buộc

Khi tạo phải có `name`, `description`, `email`, `phone`, `city`. Khi sửa, không gửi trường nào thì trường đó giữ nguyên, nhưng gửi `null` cho các trường này bị từ chối bằng `required`. Tổ chức tạo trước đây có thể thiếu các trường này cho đến lần sửa tiếp theo.

Giới hạn khi tạo tổ chức. Hiện chưa kiểm tra email đã xác minh, vì chức năng xác minh email chưa làm xong:

| Quy tắc | Lỗi |
| ------- | --- |
| Tối đa 3 lần thử mỗi ngày (tính theo ngày UTC, kể cả lần thất bại) | 429 `rate_limited` |
| Sở hữu tối đa 5 tổ chức chưa xóa, kể cả tổ chức bị tạm ngưng | 409 `organization_limit_reached` |

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

### Chữ ra chữ, số ra số

Các body mới và các body có số dùng kiểu chặt trong `src/validation.py`, để giá trị sai kiểu bị từ chối thay vì bị đoán:

| Kiểu | Nhận | Từ chối | Mã lỗi |
| ---- | ---- | ---- | ---- |
| `StrictInt` (số chỗ, số phút, cỡ chữ) | Số nguyên JSON | `"5"`, `5.0`, `true` | `int_type` |
| `StrictFloat` (vị trí trên mẫu chứng nhận) | Số JSON | Chuỗi, `true`, `NaN`, vô cực | `float_type`, `finite_number` |
| `StrictDecimal` (giờ, hệ số, giới hạn giờ) | Số JSON, hoặc chuỗi số thường như `"2.5"`, `"-1"` | `"1e3"`, `" 2"`, `".5"`, `"NaN"`, `"Infinity"`, `true` | `number_invalid` |
| `StrictBool` (cờ như `draft`, `is_remote`) | `true`, `false` | `"true"`, `1`, `"on"` | `bool_type` |
| Chuỗi | Chuỗi JSON | Số, danh sách | `string_type` |

- `has_letter` từ chối tiêu đề không có chữ cái nào, ví dụ `"2024"` hay `"!!!"`, với mã `text_needs_letter`. Áp dụng cho tiêu đề bài viết và tên hoạt động.
- Số thập phân nhận cả chuỗi vì frontend gửi đúng số người dùng gõ, giữ độ chính xác. Chuỗi phải đúng dạng `-?[0-9]+(\.[0-9]+)?`.

## Khóa chính

Mọi khóa chính đều là UUIDv7, sinh bằng `uuid.uuid7()`. Test `test_new_ids_are_uuid7` khóa quy tắc này cho người dùng, tổ chức và vai trò.

## Xóa tổ chức

Chỉ chủ sở hữu được xóa hoặc khôi phục. Quản trị viên, thành viên và người ngoài nhận 403 `organization_forbidden`. Xóa lần hai, hoặc xóa tổ chức đã bị xóa, trả về 404 `organization_not_found`.

Xóa là xóa mềm. Code nằm trong [`src/organizations/deletion.py`](../src/organizations/deletion.py).

### Chặn khi còn hoạt động đang mở

Một hoạt động ở trạng thái `published` là đang mở, cho đến khi được hoàn thành hoặc hủy. Khi tổ chức còn hoạt động như vậy, xóa trả về 409 `organization_has_open_activities`. Hoạt động nháp không chặn việc xóa. Muốn xóa, chủ sở hữu hủy các hoạt động đang mở trước. Chi tiết tổ chức trả về `open_activity_count` để giao diện hiện con số này trước khi bấm xóa. Đăng ký còn hiệu lực sẽ chuyển thành `cancelled` và người đăng ký được báo.

Việc đăng hoạt động cũng khóa tổ chức, giống như xóa, và kiểm tra lại tổ chức còn hoạt động. Nhờ vậy một hoạt động không mở ra trong tổ chức vừa bị xóa.

### Điều xảy ra khi xóa

- `deleted_at` được đặt thời điểm xóa. Mọi đường đọc của tổ chức, bài đăng, chat và hoạt động đều lọc theo `deleted_at`, nên tổ chức biến mất với mọi người: trang chi tiết, danh sách, "Tổ chức của tôi", tham gia, danh sách thành viên, đơn, bộ sưu tập, hoạt động và bài đăng.
- Slug được nhả. Slug cũ chuyển sang cột `previous_slug`, còn `slug` nhận một giá trị dạng `deleted-<hex>` mà không ai nhập được. Người khác có thể tạo tổ chức mới với đúng tên cũ và nhận lại slug cũ.
- Không xóa gì khác: thành viên, vai trò, hoạt động, bài đăng, giờ tình nguyện và các tệp đều giữ nguyên.
- Logo, ảnh bìa và ảnh bộ sưu tập chuyển sang `private`, nên người khác không tải được qua `/media/{id}/file`. Ngoại lệ: ảnh còn được dùng ở chỗ khác, ví dụ làm ảnh đại diện của chính chủ sở hữu, thì vẫn công khai. Chủ sở hữu luôn xem được ảnh của mình.
- Tổ chức đã xóa không còn được tính trong giới hạn 5 tổ chức, nên xóa mềm trả lại một chỗ cho chủ sở hữu.
- Chứng nhận đã cấp vẫn hiện tên tổ chức và vẫn xác minh được, vì đó là lịch sử của sinh viên. Xóa vĩnh viễn thì không làm được khi còn chứng nhận, xem bên dưới.

### Thùng rác và khôi phục

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| GET | `/organizations/mine/deleted` | Đã đăng nhập: chỉ liệt kê tổ chức của chính mình đã xóa |
| POST | `/organizations/mine/deleted/{org_id}/restore` | Chủ sở hữu, chỉ với tổ chức đang ở thùng rác |
| DELETE | `/organizations/mine/deleted/{org_id}` | Chủ sở hữu, chỉ với tổ chức đang ở thùng rác. Xóa vĩnh viễn, xem bên dưới |

Khôi phục trả về 200 với chi tiết tổ chức. Khi khôi phục:

- Slug cũ phải còn trống, nếu không trả về 409 `slug_taken`. Tổ chức vẫn ở thùng rác.
- Chủ sở hữu phải còn dưới giới hạn 5 tổ chức đang hoạt động, nếu không trả về 409 `organization_limit_reached`.
- Logo, ảnh bìa và bộ sưu tập được công khai lại.

Thùng rác không tự xóa. Tệp không còn được dùng sau khi xóa sẽ được dọn bằng script, xem [`media.md`](media.md#dọn-tệp-không-còn-dùng).

### Xóa vĩnh viễn

`DELETE /organizations/mine/deleted/{org_id}` xóa hẳn tổ chức khỏi thùng rác. Chỉ chủ sở hữu, và chỉ khi tổ chức đang ở thùng rác. Tổ chức đang hoạt động trả về 404 `organization_not_found`, và người khác cũng nhận 404. Thành công trả về 204. Code nằm trong [`src/organizations/purge.py`](../src/organizations/purge.py).

Việc xóa là một lệnh xóa dòng trong `organizations`, để cơ sở dữ liệu tự cascade. Những gì mất theo:

- Hoạt động của tổ chức, kèm đăng ký, điểm danh, đơn, bài đăng, chat và thành viên.
- Bộ sưu tập và liên kết ảnh. Các tệp ảnh vẫn còn ở trạng thái `private`, và script dọn tệp sẽ xóa những tệp không còn được dùng.

Ba loại bản ghi chặn việc xóa vĩnh viễn, và backend trả về 409 khi gặp:

| Mã | Lý do |
| ---- | ---- |
| `organization_has_open_activities` | Còn hoạt động ở trạng thái `published`. Soft delete đã chặn từ trước, đây là kiểm tra lại |
| `organization_has_certificates` | Đã cấp chứng nhận cho hoạt động của tổ chức. Chứng nhận là bằng chứng của sinh viên, nên không được xóa theo hoạt động |
| `organization_has_pending_hours` | Còn giờ tình nguyện đang chờ duyệt của tổ chức. Sau khi xóa không ai duyệt được |

Giờ tình nguyện đã duyệt không bị xóa. `volunteer_hour_ledger` là append-only, nên các dòng này được giữ lại, và `org_id` cùng `activity_id` của chúng về `NULL` theo khóa ngoại `ON DELETE SET NULL`. Sinh viên vẫn thấy tổng giờ, chỉ không còn liên kết tới tổ chức.

## Mã lỗi nghiệp vụ

| Mã | HTTP |
| ---- | ---- |
| `organization_not_found` | 404 |
| `organization_forbidden` | 403 |
| `organization_has_certificates` | 409 |
| `organization_has_pending_hours` | 409 |
| `already_member`, `already_applied` | 409 |
| `application_cooldown` | 409 |
| `membership_suspended` | 403 |
| `owner_cannot_leave`, `owner_role_locked`, `owner_cannot_be_removed`, `cannot_remove_self` | 409 |
| `not_a_member`, `member_not_found`, `application_not_found` | 404 |
| `organization_has_open_activities`, `slug_taken` | 409 |
