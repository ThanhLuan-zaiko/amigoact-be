# Hoạt động và đăng ký

Tài liệu này mô tả phần hoạt động của backend. Code nằm trong [`src/activities/`](../src/activities).

## Vòng đời hoạt động

| Trạng thái | Ý nghĩa | Chuyển tiếp |
| ---- | ---- | ---- |
| `draft` | Chỉ ban quản trị thấy | Đăng, hoặc xóa mềm |
| `published` | Công khai, mở đăng ký đến hạn | Kết thúc sau giờ bắt đầu (ghi giờ tình nguyện), hoặc hủy |
| `completed` | Đã kết thúc | Không đổi được nữa |
| `cancelled` | Đã hủy. Mọi đăng ký còn hiệu lực chuyển thành `cancelled` | Không đổi được nữa |

Khi tạo, API bắt buộc có tên, mô tả, thành phố, giờ tình nguyện, giờ bắt đầu, giờ kết thúc, và địa điểm nếu không trực tuyến, giống form. Khi đăng, hoạt động phải có giờ bắt đầu ở tương lai, giờ kết thúc, mô tả, thành phố, giờ tình nguyện, và địa điểm nếu không trực tuyến. Việc đăng nằm trong `publishing.py`. Trạng thái `ongoing` trong schema chưa dùng: hoạt động đang diễn ra vẫn là `published`.

## Ca

- Hoạt động có thể không có ca, khi đó sức chứa là `max_participants` (bỏ trống là không giới hạn).
- Khi có ca, người đăng ký phải chọn ca, và sức chứa tính theo từng ca. `max_participants` không còn tác dụng.
- API coi một ca là một đơn vị. Trong database, mỗi ca gồm một dòng `activity_schedules` và một dòng `activity_slots`, để phần điểm danh sau này gắn vào buổi.
- Ca phải nằm trong thời gian của hoạt động. Một người không đăng ký được hai ca trùng giờ, nhưng hai ca nối tiếp nhau thì được.
- Ca đã có đăng ký thì không xóa được. Đã có người đăng ký cả hoạt động thì không thêm được ca.

## Đăng ký

Ai đã đăng nhập cũng đăng ký được, không cần là thành viên tổ chức hay sinh viên.

| Tình huống | Trạng thái |
| ---- | ---- |
| Còn chỗ, không cần duyệt | `approved` |
| Còn chỗ, cần duyệt | `pending`, đã giữ chỗ |
| Hết chỗ | `waitlisted` |
| Có chỗ trống khi còn người chờ | Người chờ lâu nhất được chuyển lên |
| Bị từ chối | `rejected`, không đăng ký lại được |
| Đã tự hủy rồi đăng ký lại | Dùng lại dòng cũ và xếp cuối hàng chờ |

- `pending`, `approved` và `attended` đều giữ chỗ, nên việc duyệt không bao giờ làm vượt sức chứa.
- Đăng ký đóng ở `registration_deadline`, hoặc ở giờ bắt đầu nếu không có hạn. Tự hủy được đến giờ bắt đầu.
- Chỉ dùng `registrations.status` cho hàng chờ. Bảng `waitlist_entries` chưa dùng, để không có hai nguồn dữ liệu.
- "Cần duyệt" lưu trong `requirements_json` với khóa `requires_approval`, nên không cần đổi schema.

### Đồng thời

Mọi thay đổi về chỗ đều khóa dòng hoạt động trước, bằng `load_activity(..., lock=True)`. Vì vậy hai request không thể cùng lấy chỗ cuối. Test `test_last_seat_cannot_be_taken_twice` khóa quy tắc này.

### Lịch sử

Mỗi lần đổi trạng thái đều thêm một dòng `registration_status_history`, gồm trạng thái cũ, trạng thái mới và người đổi.

### Mã check-in

`checkin_token` dùng UUIDv4 thay vì UUIDv7. Đây là mã bí mật cho QR ở giai đoạn sau, không phải khóa chính, nên cần hoàn toàn ngẫu nhiên và không lộ thời gian tạo. API chưa trả mã này. Mọi khóa chính vẫn là UUIDv7.

## Danh sách của tổ chức, bản nháp và thùng rác

- `GET /organizations/{slug}/activities` không trả bản nháp, kể cả cho ban quản trị, giống bảng tin bài viết. Code ở `src/activities/listing.py`.
- `status` chọn một tab: `upcoming` (đã đăng và chưa bắt đầu, sớm nhất trước), `completed`, `cancelled`, `draft`. Không gửi `status` thì trả mọi hoạt động không phải nháp, mới nhất trước. `draft` chỉ cho ban quản trị (người khác nhận 403 `organization_forbidden`). Giá trị khác bị từ chối (422).
- Xóa một bản nháp chỉ ghi `deleted_at`, nên nó vào thùng rác. Thùng rác giữ 30 ngày (`src/activities/trash_rules.py`). Hoạt động quá hạn bị xóa hẳn khi thùng rác được đọc. Code ở `src/activities/trash.py`.
- Chủ sở hữu và quản trị viên xem thùng rác và khôi phục. Hoạt động khôi phục quay lại là bản nháp. Chỉ chủ sở hữu xóa vĩnh viễn. Bản nháp chưa từng có đăng ký, nên xóa hẳn chỉ mất các ca của nó (theo `ON DELETE CASCADE`). Bài viết đang gắn với hoạt động đó giữ nguyên, chỉ mất liên kết.
- Người ngoài tổ chức gọi khôi phục hoặc xóa vĩnh viễn nhận 404, để không biết bản nháp đã xóa có tồn tại. Thành viên thường nhận 403. Hoạt động không nằm trong thùng rác trả 409 `activity_not_in_trash`. Hoạt động quá 30 ngày coi như đã mất (404).

## Thẻ

- Hoạt động có tối đa 5 thẻ, gửi qua `tags` khi tạo hoặc sửa. Khi sửa, gửi `tags` thì thay cả danh sách, không gửi thì giữ nguyên. Code ở `src/activities/tags.py`, bảng `activity_tags`.
- Thẻ dùng chung danh mục `tags` của tổ chức với bài viết, cùng quy tắc slug và mã lỗi (`tag_invalid`, `too_many_tags`). Nhờ vậy `#moi-truong` gom cả bài lẫn hoạt động. Tên hiện là tên được dùng lần đầu trong tổ chức, dù lần đầu đó là bài hay hoạt động.
- Mỗi hoạt động trả về `tags` (tên, xếp theo chữ cái). Danh sách lấy thẻ của cả trang trong một truy vấn.
- `GET /activities` và `GET /organizations/{slug}/activities` nhận `?tag=` (slug hoặc tên như gõ). Bộ lọc chỉ thu hẹp danh sách, không bao giờ lộ bản nháp. `tag` không có chữ hay số trả về danh sách rỗng; `tag` trống hoặc dài hơn 40 ký tự bị từ chối (422).
- `GET /organizations/{slug}/activity-tags?q=&limit=` gợi ý thẻ cho form hoạt động, xếp theo số hoạt động dùng nhiều nhất. Chỉ ban quản trị gọi được (403 với người khác). Mọi hoạt động chưa xóa đều được đếm, kể cả bản nháp, vì chỉ ban quản trị thấy gợi ý này.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| GET | `/activities?q=&city=&tag=&limit=&offset=` | Công khai: hoạt động sắp diễn ra, sớm nhất trước |
| GET | `/organizations/{slug}/activities?status=&tag=` | Công khai, không gồm bản nháp. `status=draft` chỉ ban quản trị |
| GET | `/organizations/{slug}/activity-tags?q=` | Ban quản trị |
| GET | `/organizations/{slug}/activity-trash?before=&limit=` | Chủ sở hữu, quản trị viên |
| POST | `/activities/{id}/restore` | Chủ sở hữu, quản trị viên |
| DELETE | `/activities/{id}/purge` | Chủ sở hữu |
| POST | `/organizations/{slug}/activities` | Ban quản trị |
| GET | `/activities/{id}` | Công khai. Bản nháp chỉ ban quản trị thấy |
| PATCH | `/activities/{id}` | Ban quản trị |
| DELETE | `/activities/{id}` | Ban quản trị, chỉ với bản nháp |
| POST | `/activities/{id}/publish`, `/complete`, `/cancel` | Ban quản trị |
| POST | `/activities/{id}/shifts` | Ban quản trị |
| PUT, DELETE | `/activities/{id}/shifts/{shift_id}` | Ban quản trị |
| POST | `/activities/{id}/registrations` | Đã đăng nhập |
| GET | `/activities/{id}/registrations?status=` | Ban quản trị |
| GET | `/registrations/mine` | Đã đăng nhập |
| DELETE | `/registrations/{id}` | Chủ đăng ký |
| POST | `/registrations/{id}/approve`, `/reject` | Ban quản trị |

Danh sách đăng ký không trả email hay số điện thoại. Tạo hoạt động giới hạn 30 lần mỗi giờ, đăng ký giới hạn 60 lần mỗi giờ cho mỗi người dùng.

## Kiểm tra dữ liệu

Lỗi trả về HTTP 422, mỗi lỗi có `loc` là tên trường và `type` là mã cố định.

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `title` | 3 đến 200 ký tự, một dòng, có chữ hoặc số | `string_too_short`, `string_too_long`, `text_invalid`, `title_invalid` |
| `description` | Tối đa 5000 ký tự, được xuống dòng | `string_too_long`, `text_invalid` |
| `location` | Tối đa 200 ký tự, một dòng | `string_too_long`, `text_invalid` |
| `address`, `city` | Như phần tổ chức | `string_too_long`, `text_invalid` |
| `start_at`, `end_at`, `registration_deadline` | Phải có múi giờ | `timezone_aware`, `datetime_from_date_parsing` |
| `end_at` | Sau `start_at` | `end_before_start` |
| `registration_deadline` | Không sau `start_at` | `deadline_after_start` |
| `start_at` khi đăng | Ở tương lai | `start_in_past` |
| `registration_deadline` khi đăng | Ở tương lai | `deadline_in_past` |
| `max_participants`, `capacity` | Số nguyên từ 1 đến 100000, không ít hơn số chỗ đã giữ | `greater_than_equal`, `less_than_equal`, `capacity_below_registered` |
| `hours_awarded` | Từ 0 đến 1000, tối đa 2 chữ số thập phân | `greater_than_equal`, `less_than_equal`, `decimal_max_places` |
| `shift_id` | UUIDv7, bắt buộc khi hoạt động có ca | `uuid_invalid`, `shift_required` |
| Thời gian của ca | Nằm trong hoạt động | `shift_outside_activity` |
| Thời gian hoạt động khi sửa | Vẫn chứa các ca đã tạo | `activity_time_excludes_shift` |
| `note` | Tối đa 1000 ký tự, được xuống dòng | `string_too_long`, `text_invalid` |
| Trường lạ, ví dụ `status` | Bị từ chối | `extra_forbidden` |
| `{id}` trên đường dẫn | Phải là UUIDv7 | `uuid_invalid` |

## Mã lỗi nghiệp vụ

| Mã | HTTP |
| ---- | ---- |
| `activity_not_found`, `shift_not_found`, `registration_not_found` | 404 |
| `activity_not_editable`, `activity_not_draft`, `activity_not_started` | 409 |
| `activity_not_open`, `registration_closed` | 409 |
| `already_registered`, `registration_rejected`, `shift_overlap` | 409 |
| `registration_not_active`, `registration_not_pending` | 409 |
| `shift_has_registrations`, `activity_has_registrations` | 409 |

## Chưa có

Danh mục hoạt động, câu hỏi khi đăng ký, ảnh bìa, thông báo cho người đăng ký, và tọa độ bản đồ chưa làm. Khóa `RESTRICT` của `registrations.slot_id` có thể chặn việc xóa cứng hoạt động có đăng ký theo ca, nên hệ thống chỉ xóa mềm.
