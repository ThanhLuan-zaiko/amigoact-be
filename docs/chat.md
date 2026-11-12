# Chat

Tài liệu này mô tả chat của tổ chức: phòng, tin nhắn, và kết nối thời gian thực. Code nằm trong [`src/chat/`](../src/chat), bảng nằm trong [`src/models/chat.py`](../src/models/chat.py).

## Phòng

Mỗi phòng có một mã (`room_id`). Có ba loại:

| Loại | Mã phòng | Ai vào được |
| ---- | ---- | ---- |
| Phòng chung của tổ chức | Mã tổ chức | Mọi thành viên đang hoạt động |
| Kênh mở | Mã kênh | Mọi thành viên đang hoạt động |
| Kênh giới hạn | Mã kênh | Quản trị viên và những người được thêm vào kênh |
| Tin nhắn riêng | Mã cặp | Hai người trong cặp, và vẫn phải là thành viên của tổ chức |

- Phòng của tổ chức đã bị tạm ngưng hoặc xóa thì không truy cập được.
- Người không thấy phòng nhận 404 `room_not_found`, không phải 403. Riêng danh sách kênh và tin nhắn riêng của tổ chức trả 403 khi không phải thành viên.
- Kênh lưu trữ vẫn đọc được, nhưng không gửi, sửa hay phản ứng thêm được (`channel_archived`).
- Hoạt động chưa có phòng chat.

## Tin nhắn

- Nội dung tối đa 2000 ký tự, cho phép xuống dòng, không có ký tự điều khiển. Tin không có ảnh hay video cần ít nhất 1 ký tự.
- Tác giả sửa được tin của mình. Tin đã sửa có `edited_at`.
- Tác giả xóa được tin của mình. Quản trị viên xóa được tin trong phòng chung và kênh. Trong tin nhắn riêng, chỉ tác giả xóa được: người kia ghim được nhưng không xóa được, và quyền quản trị tổ chức không có tác dụng ở đây (`can_delete` trong `src/chat/rooms.py`). Xóa là xóa hẳn, kèm ghim và phản ứng.
- Trả lời một tin trong cùng phòng. Bản trả lời lưu sẵn tên và 200 ký tự đầu của tin gốc, nên vẫn hiển thị được khi tin gốc bị xóa.
- Phản ứng bằng emoji tối đa 16 ký tự. Mỗi người chỉ có một lần cho mỗi emoji trên một tin.
- Ghim: quản trị viên ghim trong phòng của tổ chức, hai người trong cặp ghim trong tin nhắn riêng.
- Vị trí đã đọc chỉ tiến lên. Đánh dấu một tin cũ không làm tăng số chưa đọc. Số chưa đọc đếm tin của người khác sau vị trí đó.
- Trang lịch sử đi từ mới đến cũ bằng `before`. Mã tin là UUIDv7 nên vừa là thứ tự vừa là con trỏ.
- Gửi tối đa 300 tin mỗi giờ cho mỗi người.

## Ảnh và video

- Tải tệp lên bằng `POST /media` trước (xem [media.md](media.md)), rồi gửi mã tệp trong `attachment_ids` của `POST /rooms/{id}/messages`. Tối đa 10 tệp mỗi tin, thứ tự trong danh sách là thứ tự trong album. Nhận ảnh JPEG, PNG, WEBP và video MP4, WEBM.
- Tin có tệp thì `body` được để trống. Tin không có tệp vẫn cần ít nhất 1 ký tự (`string_too_short`). Sửa tin có tệp được xóa hết chú thích, tin chỉ có chữ thì không.
- Chỉ người tải lên mới gửi được tệp của mình (`media_not_found`). Mỗi tệp chỉ thuộc một tin: bảng `chat_attachment_claims` có khóa chính là mã tệp, gửi lại tệp đã gửi trả `attachment_in_use`.
- `org_room_media` giữ thứ tự, loại (`image` hoặc `video`), mime, tên và kích thước của từng tệp. Bảng này cũng là chỉ mục cho tab "tệp đã chia sẻ" sau này.
- Tệp vẫn là `private` trong `media_assets`. `GET /media/{id}/file` mở cho mọi người vào được phòng chứa tin, và trả 404 cho người khác như tệp không tồn tại. Rời tổ chức hay bị xóa khỏi kênh giới hạn thì mất quyền xem ngay.
- Xóa tin thì claim và dòng `org_room_media` đi theo. Tệp còn lại không ai dùng và lượt dọn tệp xóa nó sau thời gian chờ.
- Tin trả về có `attachments`: danh sách `{id, url, kind, mime, size_bytes, name}`. Trả lời một tin chỉ có tệp thì bản trích dẫn có `body` rỗng.

## Hộp thư và danh bạ

- `GET /chat/inbox` trả mọi phòng người xem vào được, ở mọi tổ chức đang hoạt động mà người đó là thành viên: phòng chung, kênh chưa lưu trữ, tin nhắn riêng. Mỗi phòng có `kind`, `name`, `topic`, `restricted`, `org` (`id`, `slug`, `name`, `logo_url`), `avatar_url` (logo tổ chức, hoặc ảnh đại diện người kia), `peer_id`, `can_manage`, `unread` và `last_message`.
- `last_message` có `preview` (120 ký tự đầu trên một dòng), `attachment_kind` (`image`, `video`, `mixed` hoặc null) và `attachment_count`.
- Phòng có tin xếp trước, tin mới nhất trên cùng. Phòng chưa có tin xếp sau theo tên.
- Tin cuối và số chưa đọc của cả danh sách đọc bằng một số câu truy vấn cố định (`DISTINCT ON` theo phòng, một câu đếm gộp).
- `GET /chat/contacts` trả thành viên đang hoạt động của các tổ chức người xem tham gia, mỗi tổ chức một dòng, tối đa 1000 dòng. `room_id` có giá trị khi hai người đã có tin nhắn riêng trong tổ chức đó.

## Mã hóa nội dung

- Nội dung tin và bản trích dẫn trong trả lời được mã hóa AES-256-GCM trước khi lưu. Chuỗi lưu có tiền tố `v1gcm:`, theo sau là base64 của 12 byte nonce ngẫu nhiên và bản mã.
- Khóa là 32 byte, đặt trong `.env` ở biến `CHAT_ENCRYPTION_KEY` dưới dạng base64. Tạo bằng `openssl rand -base64 32`. Thiếu hoặc sai độ dài thì ứng dụng không khởi động.
- Mã tin được gắn vào phép mã hóa như dữ liệu xác thực. Bản mã copy sang tin khác sẽ không mở được.
- Mất khóa thì mọi tin đã lưu không đọc được. Đổi khóa khi đang dùng cũng làm vậy, vì chưa có cơ chế xoay khóa.
- Dòng lưu không có tiền tố, hoặc bị sửa, làm đọc danh sách lỗi 500. Lỗi này được giữ nguyên để không im lặng che dữ liệu hỏng.

## Đang nhập

- Socket gửi `{"op": "typing", "topic": "room:<id>"}` lên phòng nó đã `subscribe`. Việc `subscribe` đã kiểm tra quyền, nên bước này chỉ cần kiểm tra socket có đang nghe phòng đó không; bị `revoke` thì hết gửi được ngay.
- Server phát `{"type": "typing", "room_id", "user_id", "name", "topic"}` tới mọi socket nghe phòng, trừ các socket của chính người gõ. Tên đọc từ database một lần cho mỗi socket.
- Mỗi socket gửi tối đa một tín hiệu cho mỗi phòng trong 2 giây (`TYPING_GAP`); tín hiệu dày hơn bị bỏ qua, không báo lỗi.
- Không ghi gì vào database. Code ở `src/realtime/typing_signal.py`.

## Kết nối thời gian thực

Chat dùng khung realtime chung, xem [realtime.md](realtime.md). Mỗi phòng là topic `room:<mã phòng>`.

- Sự kiện: `message.created`, `message.updated`, `message.deleted`, với `room_id` và nội dung tin.
- Danh sách phòng đổi (tạo kênh, lưu trữ kênh, thêm người vào kênh, mở tin nhắn riêng) gửi `rooms.changed` trên `org:<id>`, hoặc trên `user:<id>` của người được thêm hay người nhận tin nhắn riêng.
- `revoked`: người nhận không còn được nghe phòng đó, ví dụ bị xóa khỏi kênh giới hạn, rời hoặc bị xóa khỏi tổ chức.
- Khung cũ `{"op": "subscribe", "room_id": "..."}` và đường dẫn `/ws/chat` vẫn chạy.

Sự kiện không kèm cờ `mine` của từng người xem. Mọi người nhận cùng một bản.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| POST | `/realtime/tickets`, `/chat/tickets` | Đã đăng nhập. Xem [realtime.md](realtime.md) |
| WebSocket | `/ws`, `/ws/chat` | Vé hợp lệ |
| GET | `/organizations/{slug}/chat/channels` | Thành viên |
| POST | `/organizations/{slug}/chat/channels` | Quản trị viên |
| POST | `/chat/channels/{id}/archive` | Quản trị viên |
| POST | `/chat/channels/{id}/members` | Quản trị viên, chỉ kênh giới hạn |
| DELETE | `/chat/channels/{id}/members/{user_id}` | Quản trị viên |
| GET | `/organizations/{slug}/chat/dms` | Thành viên |
| POST | `/organizations/{slug}/chat/dms` | Thành viên |
| GET | `/organizations/{slug}/chat/unread` | Thành viên |
| GET | `/chat/inbox` | Đã đăng nhập. Chỉ các phòng người gọi vào được |
| GET | `/chat/contacts` | Đã đăng nhập |
| GET | `/rooms/{id}/messages` | Người có quyền vào phòng |
| POST | `/rooms/{id}/messages` | Người có quyền vào phòng |
| PATCH | `/messages/{id}` | Tác giả |
| DELETE | `/messages/{id}` | Tác giả. Quản trị viên trong phòng chung và kênh. Trong tin nhắn riêng chỉ tác giả |
| POST | `/messages/{id}/reactions` | Người có quyền vào phòng |
| DELETE | `/messages/{id}/reactions/{emoji}` | Người đã phản ứng |
| GET | `/rooms/{id}/pins` | Người có quyền vào phòng |
| POST, DELETE | `/rooms/{id}/pins/{message_id}` | Quản trị viên trong phòng chung và kênh. Cả hai người trong tin nhắn riêng |
| POST | `/rooms/{id}/read` | Người có quyền vào phòng |

Phòng chung của tổ chức có mã trùng với mã tổ chức (`id` trong chi tiết tổ chức).

## Kiểm tra dữ liệu

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `body` | Tối đa 2000 ký tự, cho phép xuống dòng. Chỉ được trống khi tin có tệp | `string_too_short`, `string_too_long`, `text_invalid` |
| `attachment_ids` | Tối đa 10 mã UUIDv7, không trùng nhau. Tệp của chính người gửi, chưa gửi lần nào | `too_long`, `attachment_duplicate`, `attachment_in_use` (422), `media_not_found` (404) |
| `reply_to_id` | Tin phải nằm trong cùng phòng | `not_in_room` (422) |
| `name` của kênh | 1 đến 40 ký tự, một dòng | `string_too_long`, `text_invalid` |
| `topic` | Tối đa 200 ký tự, một dòng | `string_too_long`, `text_invalid` |
| `visibility` | `open` hoặc `restricted` | `literal_error` |
| `member_ids` | Chỉ kênh giới hạn. Mỗi người phải là thành viên đang hoạt động | `needs_restricted_channel`, `not_a_member` (422) |
| `emoji` | 1 đến 16 ký tự | `string_too_short`, `string_too_long` |
| Body | Không nhận trường lạ | `extra_forbidden` |

## Mã lỗi nghiệp vụ

| Mã | Ý nghĩa |
| ---- | ---- |
| `room_not_found` | Phòng không tồn tại hoặc người gọi không được vào |
| `channel_name_taken` | Đã có kênh cùng tên, không phân biệt hoa thường |
| `channel_archived` | Kênh đã lưu trữ, không ghi thêm được |
| `channel_not_restricted` | Chỉ thêm người được vào kênh giới hạn |
| `channel_member_not_found` | Người này không nằm trong kênh giới hạn |
| `message_not_found` | Tin không có trong phòng này |
| `message_forbidden` | Không phải tác giả, hoặc không có quyền xóa hay ghim trong phòng này |

## Giới hạn

- Gửi tin: 300 lần mỗi giờ cho mỗi người.
- Mỗi kết nối: 30 phút, sau đó phải lấy vé mới.

## Chưa có

- Tệp không phải ảnh hay video (PDF, tài liệu), và tab tệp đã chia sẻ của phòng.
- Chạy nhiều tiến trình: sự kiện chỉ đến các kết nối trong cùng tiến trình. Cần kênh phát sóng chung (Redis hoặc Postgres LISTEN) trước khi chạy nhiều bản.
- Người bị xóa khỏi tổ chức vẫn nhận sự kiện của phòng trong tối đa 30 phút. Chỉ việc xóa khỏi kênh giới hạn mới ngắt ngay.
- Thời gian chờ (`org_chat_timeouts`), tắt thông báo (`org_room_mutes`), kênh con, phòng hoạt động, nhắc tên, tìm kiếm, thông báo đẩy.
- Thành viên tự rời kênh giới hạn.
