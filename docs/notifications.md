# Thông báo

Tài liệu này mô tả phần thông báo của backend. Code nằm trong [`src/notifications/`](../src/notifications) và bảng nằm trong [`src/models/notifications.py`](../src/models/notifications.py).

## Cách hoạt động

Mỗi sự kiện gọi `notify` trong cùng giao dịch với thay đổi dữ liệu. Vì vậy:

- Hành động thất bại thì không có thông báo nào được ghi.
- Email chỉ được đưa vào hàng đợi và gửi sau khi giao dịch commit. Hành động thất bại thì không có email.
- Email gửi trong dependency `deliver_emails`, gắn vào các router, nên SMTP chậm không làm chậm phản hồi bình thường.

Thông báo trong ứng dụng luôn được ghi trừ khi người dùng tắt kênh này. Email mặc định tắt.

## Loại thông báo

| Mã | Khi nào | Người nhận |
| ---- | ---- | ---- |
| `registration_approved` | Ban quản trị duyệt đăng ký | Tình nguyện viên |
| `registration_rejected` | Ban quản trị từ chối đăng ký | Tình nguyện viên |
| `registration_promoted` | Được chuyển từ danh sách chờ lên | Tình nguyện viên |
| `activity_cancelled` | Hoạt động bị hủy | Mỗi người có đăng ký, một lần |
| `membership_requested` | Có người xin vào tổ chức cần duyệt | Chủ tổ chức và mọi quản trị viên. `data` có `organization_id`, `applicant_id`, `applicant_name`, `message` (lý do, có thể `null`). Bị xóa khi người đó rút yêu cầu |
| `membership_approved` | Yêu cầu vào tổ chức được duyệt | Người xin vào |
| `membership_rejected` | Yêu cầu vào tổ chức bị từ chối | Người xin vào |
| `member_left` | Một thành viên tự rời tổ chức | Chủ tổ chức và mọi quản trị viên, trừ chính người rời. `data` có `organization_id`, `member_id`, `member_name` |
| `membership_removed` | Ban quản trị xóa một thành viên | Người bị xóa |
| `hours_awarded` | Giờ được ghi khi kết thúc hoạt động | Tình nguyện viên, kèm số giờ |
| `appeal_approved` | Khiếu nại điểm danh được chấp nhận | Tình nguyện viên |
| `appeal_rejected` | Khiếu nại điểm danh bị từ chối | Tình nguyện viên |
| `certificate_issued` | Chứng nhận được cấp, hoặc được hoàn tác thu hồi | Người nhận chứng nhận |
| `certificate_revoked` | Chứng nhận bị thu hồi | Người nhận chứng nhận, kèm lý do |

Mã loại là cố định. Frontend dịch mã và `data` thành tiếng Việt. Dữ liệu chỉ gồm ID, tên hoạt động, tên tổ chức và các trường riêng của loại đó. Không có email hay số điện thoại.

Tổ chức mở (`join_policy = open`) cho vào ngay nên không gửi `membership_requested`. Người đã bị xóa khỏi tổ chức mở thì phải xin duyệt, nên vẫn có thông báo.

## Tùy chọn

- `inapp`: mặc định bật. Tắt thì không ghi thông báo trong ứng dụng.
- `email`: mặc định tắt. Chỉ gửi tới địa chỉ đã xác minh.
- `muted_types`: danh sách loại không nhận, lưu theo từng loại.

Mỗi người có một dòng `notification_preferences`, tạo khi họ lưu lần đầu. Chưa có dòng thì dùng mặc định.

## API

| Method | Đường dẫn | Ghi chú |
| ---- | ---- | ---- |
| GET | `/notifications` | Phân trang bằng `limit` và `offset`. Có `unread_only` và `unread_count` |
| GET | `/notifications/unread-count` | Số chưa đọc, dùng cho chuông trên header |
| POST | `/notifications/{id}/read` | Đánh dấu đã đọc. ID của người khác trả về 404 |
| POST | `/notifications/read-all` | Đánh dấu tất cả đã đọc |
| GET | `/notifications/preferences` | Cài đặt hiện tại |
| PUT | `/notifications/preferences` | Ghi toàn bộ cài đặt, không ghi một phần |

Danh sách sắp xếp mới nhất trước. `next_offset` là `null` ở trang cuối.

## Kiểm tra dữ liệu

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `muted_types` | Chỉ nhận mã loại trong bảng trên | `literal_error` |
| `inapp`, `email` | Kiểu boolean | `bool_type` |
| `limit` | Từ 1 đến 100 | `greater_than_equal`, `less_than_equal` |
| `offset` | Từ 0 đến 100000 | `greater_than_equal`, `less_than_equal` |

## Thời gian thực

Thông báo đi trên topic `user:<id>` của khung realtime chung, xem [realtime.md](realtime.md). Socket tự nghe topic này khi kết nối, kể cả nhiều tab.

- `notify` gọi `bus.emit` trong cùng giao dịch (`src/notifications/live.py`). Hành động thất bại không làm chuông kêu.
- Đánh dấu đã đọc cũng gửi sự kiện, để chuông ở các tab khác cập nhật.
- Người xin vào rút yêu cầu (`DELETE /organizations/{slug}/membership` khi đang chờ duyệt) thì mọi thông báo `membership_requested` của họ trong tổ chức đó bị xóa khỏi hộp thư của ban quản trị, kèm sự kiện `notification.deleted`. Thông báo cũ chưa có `organization_id` được khớp theo slug.
- Người dùng tắt `inapp` hoặc tắt loại đó thì không có sự kiện thông báo. Trang vẫn cập nhật nhờ các tín hiệu riêng như `membership.changed`, không phụ thuộc thông báo.

| Sự kiện | Nội dung |
| ---- | ---- |
| `notification.created` | `notification`: giống một mục của `GET /notifications` |
| `notification.read` | `id` của thông báo vừa đọc |
| `notification.read_all` | Không có trường thêm |
| `notification.deleted` | `notification`: thông báo vừa bị xóa, `read` cho biết nó đã được đọc chưa |

## Chưa có

- Thông báo đẩy khi trình duyệt đóng (Web Push).
- Thông báo chung từ tổ chức (`announcement`), sẽ làm cùng bảng tin.
- Gửi lại email khi lỗi SMTP. Lỗi gửi chỉ được ghi vào log của ứng dụng.
