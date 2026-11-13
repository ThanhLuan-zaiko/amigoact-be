# Vai trò và quyền trong tổ chức

Cơ chế phân quyền giống Discord. Chủ sở hữu tổ chức có quyền cao nhất và tự tạo các vai trò (nhóm nhỏ), mỗi vai trò là một gói quyền kèm vị trí. Code nằm trong [`src/organizations/`](../src/organizations): `permissions.py`, `access.py`, `roles.py`, `role_router.py`, `role_schemas.py`.

## Nguyên tắc

- **Chủ sở hữu** (`organizations.owner_id`) có mọi quyền và đứng trên mọi vai trò. Không ai đổi được vai trò của chủ sở hữu (409 `owner_role_locked`).
- **Vai trò** thuộc về một tổ chức, có `name`, `color` (`#rrggbb` hoặc rỗng), `position` và một tập quyền. Một thành viên giữ được nhiều vai trò (tối đa 10). Quyền của thành viên là hợp của các vai trò đang giữ.
- **Vị trí**: số lớn hơn thì cao hơn. Vai trò mới nằm dưới cùng, mọi vai trò khác dịch lên một bậc.
- **Thành viên thường** là người `active` không giữ quyền nào.
- Vai trò "gộp" `role` mà giao diện cũ dùng vẫn còn: `owner`, `admin` (giữ ít nhất một quyền), `member`. Quyền cụ thể nằm trong `viewer.permissions`.

## Quyền

Mã quyền có dạng `mục.hành động`, nên một vai trò có thể tạo mà không xóa được. Mỗi mã chỉ mở đúng các thao tác ghi trong cột "Cho phép". Đọc dữ liệu công khai hoặc dành cho thành viên không cần quyền.

| Mã | Cho phép |
| ---- | ---- |
| `administrator` | Mọi quyền bên dưới, kể cả quyền thêm sau này |
| `organization.update` | Sửa hồ sơ, ảnh, bộ sưu tập, hiển thị công khai |
| `roles.create` | Tạo vai trò thấp hơn mình |
| `roles.update` | Sửa tên, màu, quyền và sắp xếp vai trò thấp hơn mình |
| `roles.delete` | Xóa vai trò thấp hơn mình |
| `roles.assign` | Gán hoặc gỡ vai trò cho thành viên |
| `members.remove` | Xóa thành viên |
| `applications.review` | Xem và duyệt yêu cầu tham gia, nhận thông báo yêu cầu mới |
| `activities.create` | Tạo hoạt động |
| `activities.update` | Sửa, đăng, kết thúc, hủy hoạt động; thêm, sửa ca; đổi ảnh bìa |
| `activities.delete` | Xóa hoạt động và ca, xem và khôi phục thùng rác |
| `activities.registrations` | Xem và duyệt đăng ký |
| `attendance.checkin` | Mở phiên, đánh dấu và xác nhận điểm danh |
| `attendance.hours` | Xem và điều chỉnh giờ, quy tắc tính giờ |
| `attendance.appeals` | Xem và quyết định khiếu nại |
| `certificates.templates` | Tạo, sửa, xem mẫu chứng nhận |
| `certificates.issue` | Cấp, thu hồi, khôi phục chứng nhận |
| `posts.announce` | Đăng bài thông báo |
| `posts.pin` | Ghim và bỏ ghim bài |
| `posts.moderate` | Ẩn, xóa, khôi phục bài và bình luận của người khác, xem bài ẩn và thùng rác |
| `channels.create` | Tạo kênh chat |
| `channels.manage` | Lưu trữ kênh, quản lý thành viên kênh |
| `channels.read_restricted` | Đọc kênh hạn chế mà không cần được thêm vào |

Người giữ bất kỳ quyền nào của một mục (`access.has_any("activities")`) được xem bản nháp hoạt động của mục đó.

Danh sách mã nằm ở `permissions.py` và được gieo vào bảng `permissions` bởi `schema.sql`. Một test đơn vị giữ hai nơi này khớp nhau. Thêm quyền mới thì sửa cả hai nơi, rồi thêm vào `PermissionCode` trong `role_schemas.py`.

## Thứ bậc

Người không phải chủ sở hữu chỉ làm được các việc sau, và mỗi việc cần đúng quyền `roles.*` của nó:

- Sửa, xóa, sắp xếp lại vai trò **thấp hơn** vai trò cao nhất của mình (403 `role_hierarchy` nếu không).
- Chỉ giao hoặc bỏ quyền mà **chính mình đang giữ** (403 `permission_not_held`). `administrator` chỉ giao được khi mình giữ nó.
- Chỉ gán hoặc gỡ vai trò thấp hơn vai trò cao nhất của mình, cho thành viên có vai trò cao nhất **thấp hơn** mình. Không tự đổi vai trò của mình.
- Xóa thành viên (`members.remove`) cũng theo quy tắc này: không xóa được người có vai trò cao hơn hoặc bằng.

## Vai trò mẫu `admin`

Mỗi tổ chức mới có sẵn vai trò **Admin** (`code = admin`, vị trí 100) với mọi quyền trừ `administrator` và `roles.*`. Đây chỉ là mẫu: chủ sở hữu sửa hoặc xóa được như vai trò khác.

Tổ chức tạo trước khi có phân quyền: `schema.sql` xóa các mã `manage_*` cũ rồi gán quyền cho vai trò `admin` nào chưa có quyền nào (mọi quyền trừ `administrator` và `roles.*`), nên người đang là admin giữ nguyên khả năng. Các câu `INSERT ... ON CONFLICT DO NOTHING` an toàn khi chạy lại, không cần reset.

`PATCH /organizations/{slug}/members/{user_id}` với `{"role": "admin"}` vẫn dùng được như lối tắt của chủ sở hữu: gán vai trò `admin`, còn `member` gỡ hết vai trò. Nếu đã xóa vai trò `admin`, trả về 404 `role_not_found`.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| GET | `/organizations/{slug}/roles` | Thành viên: danh sách vai trò kèm `catalog` và cờ `below_you` (vai trò nằm dưới vai trò cao nhất của người gọi) |
| POST | `/organizations/{slug}/roles` | `roles.create`: body `name`, `color`, `permissions` |
| PATCH | `/organizations/{slug}/roles/{role_id}` | `roles.update`: `name`, `color`, `permissions`, trường nào không gửi thì giữ nguyên |
| DELETE | `/organizations/{slug}/roles/{role_id}` | `roles.delete`: 204 |
| PUT | `/organizations/{slug}/roles/order` | `roles.update`: `role_ids` từ cao xuống thấp, đúng tập vai trò người gọi được phép di chuyển |
| PUT | `/organizations/{slug}/members/{user_id}/roles` | `roles.assign`: `role_ids` là toàn bộ vai trò mới của thành viên |

`GET /organizations/{slug}/members` trả thêm `roles` (id, tên, màu, từ cao xuống thấp). `viewer` của chi tiết tổ chức trả thêm `permissions`.

## Giới hạn và kiểm tra

| Quy tắc | Lỗi |
| ---- | ---- |
| Tối đa 25 vai trò mỗi tổ chức | 409 `role_limit_reached` |
| Tên vai trò duy nhất, không phân biệt hoa thường | 409 `role_name_taken` |
| Tên 1 đến 50 ký tự, một dòng, có chữ | `string_too_short`, `string_too_long`, `text_invalid`, `text_needs_letter` |
| Màu `#rrggbb` hoặc rỗng | `string_pattern_mismatch` |
| Mã quyền phải có trong danh mục, không lặp | `literal_error`, `duplicate_items` |
| Thứ tự phải gồm đúng các vai trò được phép di chuyển | 422 `role_order_invalid` |
| Vai trò không thuộc tổ chức này | 404 `role_not_found` |
| Trường lạ như `position` | `extra_forbidden` |

## Trực tiếp

Mọi thay đổi gửi `roles.changed` và `members.changed` lên `org:<id>`, và `membership.changed` lên `user:<id>` của từng người bị ảnh hưởng. Người không còn quyền nào bị cắt khỏi `org-managers:<id>` và các phòng hạn chế. Xem [`realtime.md`](realtime.md).
