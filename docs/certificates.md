# Chứng nhận

Tài liệu này mô tả phần chứng nhận của backend. Code nằm trong [`src/certificates/`](../src/certificates).

## Quy tắc nghiệp vụ

- Chỉ người có đăng ký `attended` mới được cấp chứng nhận, tức là đã có giờ được ghi sau khi điểm danh.
- Mỗi người có tối đa một chứng nhận cho mỗi hoạt động, theo ràng buộc `certificates_activity_student_uq`. Nhiều ca cùng tính vào một chứng nhận.
- Chỉ cấp được khi hoạt động đã kết thúc (`completed`). Lỗi trả về `activity_not_completed`.
- Cấp lại không tạo thêm gì với người đã có chứng nhận. Với người vừa được chấp nhận khiếu nại, lần cấp tiếp theo sẽ cấp cho họ.
- Số serial dạng `AMG-XXXX-XXXX-XXXX`, lấy ngẫu nhiên bằng `secrets` từ bảng ký tự điểm danh. Serial không liên quan tới ID, nên không thể liệt kê hay đoán. Ràng buộc `certificates_serial_uq` là lớp bảo vệ cuối.
- Thu hồi cần lý do (từ 5 ký tự trở lên) và ghi vào `certificate_revocations`. Trạng thái chỉ là `issued` hoặc `revoked`.
- Chứng nhận đã thu hồi vẫn tra được bằng serial, kèm trạng thái và thời điểm thu hồi.
- Hoàn tác thu hồi (`reinstate`) đưa trạng thái về `issued`. Bản ghi thu hồi cũ vẫn được giữ.
- Số giờ trên chứng nhận là tổng của sổ giờ có trạng thái `approved` cho đúng người và hoạt động đó. Không lưu thêm bản sao.

## Thông báo

Cấp và thu hồi đều tạo thông báo cho người nhận, xem [`notifications.md`](notifications.md). Hoàn tác thu hồi cũng tạo thông báo `certificate_issued`.

## Mẫu chứng nhận

Mỗi tổ chức có nhiều mẫu. Mẫu gồm tên, ảnh nền và vị trí của năm nội dung: tên người nhận, tên hoạt động, số giờ, ngày cấp và số serial. Vị trí tính theo phần trăm kích thước trang (`x` từ trái, `y` từ trên, 0 đến 100) và cỡ chữ (8 đến 72). Mặc định: tên ở giữa, số serial ở cuối trang.

- Ảnh nền là ảnh đã tải lên bởi chính người tạo mẫu. Khi gắn vào mẫu, ảnh chuyển thành công khai, vì người nhận cần xem được khi in. Xem [`media.md`](media.md).
- Mẫu không xóa được. Đặt `is_active` thành `false` để ẩn mẫu khỏi việc cấp chứng nhận. Mẫu không hoạt động vẫn xem và sửa được.
- Khi cấp, có thể truyền `template_id` để gắn mẫu vào mọi chứng nhận mới. Chứng nhận đã cấp giữ mẫu cũ. Không truyền thì không gắn mẫu.
- Mẫu chỉ dùng được cho hoạt động của chính tổ chức sở hữu mẫu.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| POST | `/activities/{id}/certificates` | Ban quản trị. Body tùy chọn: `{ "template_id": "<uuid>" }` |
| POST | `/organizations/{slug}/certificate-templates` | Ban quản trị |
| GET | `/organizations/{slug}/certificate-templates` | Ban quản trị, kèm mẫu không hoạt động |
| PATCH | `/certificate-templates/{id}` | Ban quản trị. Chỉ đổi trường được gửi |
| GET | `/activities/{id}/certificates` | Ban quản trị |
| GET | `/certificates/mine` | Đã đăng nhập |
| GET | `/certificates/verify/{serial}` | Công khai |
| POST | `/certificates/{id}/revoke` | Ban quản trị |
| POST | `/certificates/{id}/reinstate` | Ban quản trị |

- `POST /activities/{id}/certificates` trả về `{ "issued": n }`, là số chứng nhận mới được cấp.
- `GET /activities/{id}/certificates` trả về danh sách cùng `missing_count`, là số người đã tham gia nhưng chưa có chứng nhận. Danh sách không có email hay số điện thoại.
- `GET /certificates/mine` trả về chứng nhận của chính người gọi, kèm tên hoạt động và tên tổ chức.
- `GET /certificates/verify/{serial}` chỉ trả về những gì cần để chứng minh: tên người nhận, hoạt động, tổ chức, số giờ, ngày cấp, trạng thái và ngày thu hồi (nếu có). Không trả về lý do thu hồi hay thông tin liên hệ.
- `PATCH` nhận `name`, `background_asset_id` (gửi `null` để gỡ ảnh), `layout` và `is_active`. Gửi `null` cho `name`, `layout` hoặc `is_active` thì bị bỏ qua.
- Body của mẫu không nhận trường lạ. `layout` không nhận tên nội dung khác năm nội dung đã nêu.
- Đường dẫn `serial` không phân biệt hoa thường. Serial sai định dạng trả về `string_pattern_mismatch`.

## Kiểm tra dữ liệu

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `reason` khi thu hồi | Từ 5 đến 1000 ký tự, không chứa ký tự điều khiển | `string_too_short`, `string_too_long`, `validation_failure` |
| `serial` trên đường dẫn | 5 đến 40 ký tự chữ, số hoặc `-` | `string_pattern_mismatch` |

## Mã lỗi nghiệp vụ

| Mã | Ý nghĩa |
| ---- | ---- |
| `activity_not_completed` | Hoạt động chưa kết thúc |
| `certificate_not_found` | Không có chứng nhận với ID hoặc serial này |
| `certificate_template_not_found` | Không có mẫu này, hoặc mẫu thuộc tổ chức khác |
| `certificate_template_inactive` | Mẫu đang tắt, không cấp được chứng nhận với mẫu này |
| `certificate_not_issued` | Chỉ thu hồi được chứng nhận đang có hiệu lực |
| `certificate_not_revoked` | Chỉ hoàn tác được chứng nhận đã thu hồi |
| `conflict` | Không tạo được serial duy nhất sau vài lần thử |

## Chưa có

- File PDF của chứng nhận. Mẫu đã có, nhưng việc dựng PDF từ mẫu chưa làm. Hiện người dùng in từ trình duyệt.
- Trang xác minh trên giao diện và nút in từ trình duyệt.
- Giới hạn tần suất cho trang xác minh công khai.
