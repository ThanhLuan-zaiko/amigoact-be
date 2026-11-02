# Điểm danh và giờ tình nguyện

Tài liệu này mô tả phần điểm danh của backend. Code nằm trong [`src/attendance/`](../src/attendance).

## Phiên điểm danh

Ban quản trị mở một phiên cho một ca, hoặc cho cả hoạt động nếu không có ca. Mỗi lúc chỉ có một phiên mở cho mỗi ca. Phiên kéo dài từ 5 đến 1440 phút và tự đóng khi hết giờ. Khi hoạt động kết thúc hoặc bị hủy, mọi phiên đều đóng.

Hoạt động không có ca vẫn cần một dòng `activity_schedules`, vì `attendance_sessions.schedule_id` là bắt buộc. Dòng này không có `activity_slots` nên không hiện thành một ca.

## Ba cách điểm danh

| Cách | Mã | Kết quả | Vì sao |
| ---- | ---- | ---- | ---- |
| Quét QR | Chuỗi bí mật dài trong `qr_codes.code` | Tính ngay, `method = 'qr'` | Người quét phải nhìn thấy màn hình tại chỗ |
| Nhập mã | 6 ký tự trong `attendance_sessions.qr_code` | Chờ xác nhận, `method = 'manual'`, `verified_by` trống | Mã ngắn có thể bị truyền tay |
| Ban quản trị điểm danh hộ | Không cần | Tính ngay, `method = 'manual'`, có `verified_by` | Người không có điện thoại |

- Mã nhập tay không dùng các ký tự dễ nhầm `0`, `O`, `1`, `I`, `L`. Hệ thống nhận cả chữ thường và khoảng trắng thừa.
- Chỉ người có đăng ký `approved` hoặc `attended` đúng ca mới điểm danh được.
- Phiên đã đóng không trả lại mã nữa, và mã cũ không dùng được.
- Mỗi lần thử đều ghi vào `qr_scan_logs`, kể cả mã sai. Điểm danh giới hạn 30 lần mỗi 15 phút cho mỗi người.
- Trang QR của frontend vẫn yêu cầu bấm nút, nên xem trước đường link không tự điểm danh.

## Giờ tình nguyện

Khi kết thúc hoạt động, hệ thống ghi giờ cho mọi đăng ký có điểm danh hợp lệ và chuyển chúng sang `attended`. Người vắng mặt giữ nguyên `approved` và không có giờ.

| Tình huống | Số giờ gốc |
| ---- | ---- |
| Đăng ký theo ca | Độ dài của ca |
| Đăng ký cả hoạt động | `hours_awarded`. Thiếu giá trị này thì không kết thúc được (`hours_required`) |

Không kết thúc được khi còn mã nhập tay chưa xác nhận (`attendance_pending_review`).

### Quy tắc tính giờ

Mỗi tổ chức có một quy tắc gồm hệ số và giới hạn giờ mỗi kỳ cho mỗi người. Kỳ là nửa năm theo giờ Việt Nam, ví dụ `2026-H1`. Số giờ được tính bằng giờ gốc nhân hệ số, rồi cắt để tổng trong kỳ không vượt giới hạn. Đổi quy tắc chỉ áp dụng cho lần ghi sau.

### Sổ cái

`volunteer_hour_ledger` chỉ thêm dòng, không sửa. Điều chỉnh là một dòng `adjustment` có lý do, kèm một dòng trong `hour_adjustments`. Tổng giờ của một người ở một hoạt động không được âm. Bảng `hours_by_student` và các view bảng xếp hạng chưa dùng, vì tổng được tính trực tiếp từ sổ cái.

## Khiếu nại

Sau khi hoạt động bắt đầu, người có đăng ký được duyệt mà chưa có điểm danh hợp lệ có thể gửi khiếu nại kèm lý do. Mỗi người có tối đa một khiếu nại đang chờ cho mỗi hoạt động.

- Chấp nhận: tạo điểm danh đã xác nhận. Nếu hoạt động đã kết thúc thì ghi giờ luôn.
- Từ chối: không đổi gì.
- `attendance_appeals` không có cột đăng ký, nên khi người đó có nhiều ca chưa điểm danh, ban quản trị phải chọn ca bằng `registration_id`.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| POST, GET | `/activities/{id}/attendance-sessions` | Ban quản trị |
| POST | `/attendance-sessions/{id}/close` | Ban quản trị |
| GET | `/attendance-sessions/{id}/roster` | Ban quản trị |
| POST | `/attendance-sessions/{id}/records` | Ban quản trị |
| POST | `/attendance-records/{id}/verify` | Ban quản trị |
| DELETE | `/attendance-records/{id}` | Ban quản trị |
| POST | `/attendance/check-in` | Đã đăng nhập |
| POST | `/registrations/{id}/appeals` | Chủ đăng ký |
| GET | `/activities/{id}/appeals?status=` | Ban quản trị |
| POST | `/appeals/{id}/approve`, `/reject` | Ban quản trị |
| GET | `/hours/mine` | Đã đăng nhập |
| GET | `/activities/{id}/hours` | Ban quản trị |
| POST | `/activities/{id}/hour-adjustments` | Ban quản trị |
| GET, PUT | `/organizations/{slug}/hour-rule` | Ban quản trị |

Sau khi hoạt động kết thúc, không sửa được điểm danh nữa. Việc sửa đi qua khiếu nại và điều chỉnh giờ.

## Kiểm tra dữ liệu

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `token` | 20 đến 64 ký tự chữ, số, `_`, `-` | `string_pattern_mismatch` |
| `code` | 6 chữ hoặc số | `string_pattern_mismatch` |
| `token` và `code` | Gửi đúng một trong hai | `checkin_input_required` |
| `minutes` | Từ 5 đến 1440 | `greater_than_equal`, `less_than_equal` |
| `shift_id` | UUIDv7, bắt buộc khi hoạt động có ca | `uuid_invalid`, `shift_required` |
| `reason` | 5 đến 1000 ký tự, được xuống dòng | `string_too_short`, `string_too_long`, `text_invalid` |
| `delta_hours` | Khác 0, từ -1000 đến 1000, tối đa 2 số lẻ | `delta_zero`, `decimal_max_places` |
| `multiplier` | Từ 0.1 đến 10, tối đa 3 số lẻ | `greater_than_equal`, `less_than_equal` |
| `cap_hours` | Lớn hơn 0, tối đa 9999, tối đa 2 số lẻ | `greater_than`, `less_than_equal` |
| `user_id`, `registration_id`, `{id}` | Phải là UUIDv7 | `uuid_invalid` |

## Mã lỗi nghiệp vụ

| Mã | HTTP |
| ---- | ---- |
| `checkin_code_invalid`, `attendance_session_not_found`, `record_not_found`, `appeal_not_found`, `hours_not_found` | 404 |
| `not_registered_for_session` | 403 |
| `checkin_session_closed`, `session_already_open`, `already_checked_in` | 409 |
| `attendance_pending_review`, `hours_required`, `hours_would_go_negative` | 409 |
| `appeal_not_allowed`, `appeal_already_pending`, `appeal_not_pending` | 409 |

## Chưa có

Điểm danh ra về, quét mã QR cá nhân bằng `checkin_token`, bảng xếp hạng, và duyệt giờ nhập tay theo hàng đợi chưa làm.
