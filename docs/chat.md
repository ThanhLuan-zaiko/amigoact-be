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

- Nội dung từ 1 đến 2000 ký tự, cho phép xuống dòng, không có ký tự điều khiển.
- Tác giả sửa được tin của mình. Tin đã sửa có `edited_at`.
- Tác giả xóa được tin của mình. Quản trị viên xóa được tin trong phòng của tổ chức. Trong tin nhắn riêng, chỉ tác giả xóa được. Xóa là xóa hẳn, kèm ghim và phản ứng.
- Trả lời một tin trong cùng phòng. Bản trả lời lưu sẵn tên và 200 ký tự đầu của tin gốc, nên vẫn hiển thị được khi tin gốc bị xóa.
- Phản ứng bằng emoji tối đa 16 ký tự. Mỗi người chỉ có một lần cho mỗi emoji trên một tin.
- Ghim: quản trị viên ghim trong phòng của tổ chức, hai người trong cặp ghim trong tin nhắn riêng.
- Vị trí đã đọc chỉ tiến lên. Đánh dấu một tin cũ không làm tăng số chưa đọc. Số chưa đọc đếm tin của người khác sau vị trí đó.
- Trang lịch sử đi từ mới đến cũ bằng `before`. Mã tin là UUIDv7 nên vừa là thứ tự vừa là con trỏ.
- Gửi tối đa 300 tin mỗi giờ cho mỗi người.

## Mã hóa nội dung

- Nội dung tin và bản trích dẫn trong trả lời được mã hóa AES-256-GCM trước khi lưu. Chuỗi lưu có tiền tố `v1gcm:`, theo sau là base64 của 12 byte nonce ngẫu nhiên và bản mã.
- Khóa là 32 byte, đặt trong `.env` ở biến `CHAT_ENCRYPTION_KEY` dưới dạng base64. Tạo bằng `openssl rand -base64 32`. Thiếu hoặc sai độ dài thì ứng dụng không khởi động.
- Mã tin được gắn vào phép mã hóa như dữ liệu xác thực. Bản mã copy sang tin khác sẽ không mở được.
- Mất khóa thì mọi tin đã lưu không đọc được. Đổi khóa khi đang dùng cũng làm vậy, vì chưa có cơ chế xoay khóa.
- Dòng lưu không có tiền tố, hoặc bị sửa, làm đọc danh sách lỗi 500. Lỗi này được giữ nguyên để không im lặng che dữ liệu hỏng.

## Kết nối thời gian thực

1. Gọi `POST /chat/tickets` (cần đăng nhập). Nhận một vé, hạn 5 phút, dùng được một lần.
2. Mở `WebSocket /ws/chat?ticket=<vé>`. Vé sai, đã dùng, hoặc đã hết hạn thì kết nối bị đóng với mã 4401.
3. Gửi các khung JSON:
   - `{"op": "subscribe", "room_id": "..."}`: nhận `subscribed`, hoặc `error` với `room_not_found`. Quyền được kiểm tra mỗi lần đăng ký.
   - `{"op": "unsubscribe", "room_id": "..."}`
   - `{"op": "ping"}`: nhận `pong`.
4. Nhận sự kiện:
   - `message.created`, `message.updated`, `message.deleted`, với `room_id` và nội dung tin.
   - `revoked`: người nhận không còn được nghe phòng đó, ví dụ bị xóa khỏi kênh giới hạn.

Mỗi kết nối tồn tại tối đa 30 phút. Hết thời gian thì bị đóng với mã 4408, và cần vé mới để kết nối lại. Nhờ vậy quyền truy cập được kiểm tra lại định kỳ.

Sự kiện không kèm cờ `mine` của từng người xem. Mọi người nhận cùng một bản.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| POST | `/chat/tickets` | Đã đăng nhập |
| WebSocket | `/ws/chat` | Vé hợp lệ |
| GET | `/organizations/{slug}/chat/channels` | Thành viên |
| POST | `/organizations/{slug}/chat/channels` | Quản trị viên |
| POST | `/chat/channels/{id}/archive` | Quản trị viên |
| POST | `/chat/channels/{id}/members` | Quản trị viên, chỉ kênh giới hạn |
| DELETE | `/chat/channels/{id}/members/{user_id}` | Quản trị viên |
| GET | `/organizations/{slug}/chat/dms` | Thành viên |
| POST | `/organizations/{slug}/chat/dms` | Thành viên |
| GET | `/organizations/{slug}/chat/unread` | Thành viên |
| GET | `/rooms/{id}/messages` | Người có quyền vào phòng |
| POST | `/rooms/{id}/messages` | Người có quyền vào phòng |
| PATCH | `/messages/{id}` | Tác giả |
| DELETE | `/messages/{id}` | Tác giả hoặc người có quyền kiểm duyệt |
| POST | `/messages/{id}/reactions` | Người có quyền vào phòng |
| DELETE | `/messages/{id}/reactions/{emoji}` | Người đã phản ứng |
| GET | `/rooms/{id}/pins` | Người có quyền vào phòng |
| POST, DELETE | `/rooms/{id}/pins/{message_id}` | Người có quyền kiểm duyệt |
| POST | `/rooms/{id}/read` | Người có quyền vào phòng |

Phòng chung của tổ chức có mã trùng với mã tổ chức (`id` trong chi tiết tổ chức).

## Kiểm tra dữ liệu

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `body` | 1 đến 2000 ký tự, cho phép xuống dòng | `string_too_short`, `string_too_long`, `text_invalid` |
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
| `message_forbidden` | Không phải tác giả, hoặc không có quyền kiểm duyệt |

## Giới hạn

- Gửi tin: 300 lần mỗi giờ cho mỗi người.
- Mỗi kết nối: 30 phút, sau đó phải lấy vé mới.

## Chưa có

- Tệp đính kèm trong chat. Cần quyền xem tệp theo phòng, như bài đăng chỉ thành viên, trước khi làm.
- Chạy nhiều tiến trình: sự kiện chỉ đến các kết nối trong cùng tiến trình. Cần kênh phát sóng chung (Redis hoặc Postgres LISTEN) trước khi chạy nhiều bản.
- Người bị xóa khỏi tổ chức vẫn nhận sự kiện của phòng trong tối đa 30 phút. Chỉ việc xóa khỏi kênh giới hạn mới ngắt ngay.
- Thời gian chờ (`org_chat_timeouts`), tắt thông báo (`org_room_mutes`), kênh con, phòng hoạt động, nhắc tên, tìm kiếm, thông báo đẩy.
- Thành viên tự rời kênh giới hạn.
