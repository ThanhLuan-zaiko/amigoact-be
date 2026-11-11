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
| GET | `/certificate-templates/{id}` | Ban quản trị của tổ chức sở hữu mẫu |
| PATCH | `/certificate-templates/{id}` | Ban quản trị. Chỉ đổi trường được gửi |
| GET | `/activities/{id}/certificates` | Ban quản trị |
| GET | `/certificates/mine` | Đã đăng nhập |
| GET | `/certificates/verify/{serial}` | Công khai, giới hạn tần suất |
| GET | `/certificates/verify/{serial}/pdf` | Công khai, giới hạn tần suất |
| POST | `/certificates/{id}/revoke` | Ban quản trị |
| POST | `/certificates/{id}/reinstate` | Ban quản trị |

- `POST /activities/{id}/certificates` trả về `{ "issued": n }`, là số chứng nhận mới được cấp.
- `GET /activities/{id}/certificates` trả về danh sách cùng `missing_count`, là số người đã tham gia nhưng chưa có chứng nhận. Danh sách không có email hay số điện thoại.
- `GET /certificates/mine` trả về chứng nhận của chính người gọi, kèm tên hoạt động và tên tổ chức.
- `GET /certificates/verify/{serial}` chỉ trả về những gì cần để chứng minh: tên người nhận, hoạt động, tổ chức, số giờ, ngày cấp, trạng thái và ngày thu hồi (nếu có). Không trả về lý do thu hồi hay thông tin liên hệ.
- `GET /certificates/mine` và `GET /certificates/verify/{serial}` có thêm `design`: `{ "background_url": ..., "layout": {...} }` của mẫu đã gắn khi cấp, để giao diện in đúng mẫu. `design` là `null` khi cấp không dùng mẫu. Mẫu bị tắt sau đó vẫn trả về `design`, vì chứng nhận giữ mẫu lúc cấp. `design` không có tên hay ID của mẫu, vì trang xác minh là công khai. Ảnh nền đã công khai từ lúc gắn vào mẫu.
- `PATCH` nhận `name`, `background_asset_id` (gửi `null` để gỡ ảnh), `layout` và `is_active`. Gửi `null` cho `name`, `layout` hoặc `is_active` thì bị bỏ qua.
- Body của mẫu không nhận trường lạ. `layout` không nhận tên nội dung khác năm nội dung đã nêu.
- Đường dẫn `serial` không phân biệt hoa thường. Serial sai định dạng trả về `string_pattern_mismatch`.

## File PDF

`GET /certificates/verify/{serial}/pdf` trả về chứng nhận dạng PDF, một trang A4 ngang. Code nằm trong `src/certificates/pdf.py`.

- Vẽ theo `design` giống bản xem trước ở giao diện: vị trí là phần trăm khổ giấy tính từ góc trên bên trái, `x` là tâm của dòng chữ, `y` là giữa dòng chữ, cỡ chữ tính bằng point trên trang A4.
- Ảnh nền phủ kín trang và giữ tỉ lệ. Ảnh được giải mã hết trước khi vẽ và thu nhỏ còn tối đa 3508 × 2480 điểm ảnh (A4 ở 300 dpi). Lúc tải lên, ảnh chỉ được kiểm tra qua vài byte đầu, nên ảnh hỏng, ảnh đã xóa hoặc không còn công khai thì trang in không có nền thay vì lỗi.
- Dòng chữ quá dài được thu nhỏ để vừa 90% chiều ngang, nhỏ nhất 6 pt.
- Số giờ in dạng "4.5 giờ tình nguyện", ngày cấp dạng `dd/mm/yyyy` theo giờ Việt Nam.
- Chứng nhận đã thu hồi trả về `409 certificate_not_issued`, nên không in được bản trông như còn hiệu lực. Hoàn tác thu hồi thì in lại được. Phản hồi có `Cache-Control: no-store` vì lý do tương tự.
- Chữ dùng font Be Vietnam Pro (Regular và Bold) trong `assets/fonts/`, giấy phép SIL Open Font License ở `assets/fonts/OFL.txt`. Font được đóng gói cùng mã nguồn vì CI chạy Linux và font của Windows không được phép phân phối lại. Thư viện PDF là `reportlab`, kéo theo `pillow` để đọc ảnh PNG và WEBP.

## Giới hạn tần suất

Tra cứu công khai (trang xác minh và file PDF) dùng chung một giới hạn: 60 lần mỗi phút cho mỗi địa chỉ IP, bucket `certificate-verify:{ip}`. Vượt giới hạn thì trả về `429 rate_limited` kèm `Retry-After`.

Frontend gọi backend từ server của nó, nên backend chỉ thấy đúng IP người dùng khi uvicorn chạy với `--forwarded-allow-ips` là địa chỉ của server frontend. Nếu không, mọi khách truy cập dùng chung một bucket.

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

- Lưu sẵn file PDF. File được dựng lại ở mỗi lần tải, nên luôn theo đúng trạng thái và mẫu hiện tại.
- Phần giao diện (trang xác minh, nút in, nút tải PDF, chỉnh mẫu) nằm trong `amigoact-fe/docs/certificates.md`.
