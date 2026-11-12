# Thời gian thực

Tài liệu này mô tả khung realtime chung của backend. Code nằm trong [`src/realtime/`](../src/realtime). Mọi tính năng mới cần cập nhật trực tiếp đều đi qua khung này, không tự mở socket hay hub riêng.

## Ý tưởng

- **Một socket** cho mỗi tab: `/ws`. Trình duyệt mở bằng vé dùng một lần, như chat trước đây.
- **Topic** là đơn vị nghe. Mỗi loại topic có đúng một hàm kiểm tra quyền (`src/realtime/access.py`), chạy mỗi lần `subscribe`.
- **Sự kiện là tín hiệu nhỏ**, ví dụ `members.changed` kèm `org_id`. Trang nhận tín hiệu rồi tự gọi API lấy dữ liệu, nên quyền được kiểm tra lại ở API. Riêng tin nhắn chat và thông báo mang sẵn nội dung, vì chúng chỉ tới người có quyền xem.
- **Gửi sau khi commit.** Hành động thất bại không gửi gì.
- **Chạy được nhiều worker** nhờ PostgreSQL `LISTEN/NOTIFY`.

## Topic

| Topic | Ai nghe được | Sự kiện |
| ---- | ---- | ---- |
| `user:<id>` | Chính người đó. Tự vào khi kết nối, không cần `subscribe` | `notification.*`, `membership.changed`, `rooms.changed` (tin nhắn riêng mới, được thêm vào kênh) |
| `org:<id>` | Thành viên đang hoạt động của tổ chức còn hoạt động | `members.changed`, `rooms.changed` |
| `org-managers:<id>` | Chủ tổ chức và quản trị viên | `applications.changed` |
| `room:<id>` | Người đọc được phòng chat (`readable_by`) | `message.created`, `message.updated`, `message.deleted` |

Topic không có quyền và topic không tồn tại trả cùng một lỗi `topic_not_found`. Topic sai định dạng trả `topic_invalid`.

## Giao thức

1. `POST /realtime/tickets` (cần đăng nhập) trả vé hạn 5 phút, dùng một lần.
2. Mở `WebSocket /ws?ticket=<vé>`. Vé sai hoặc đã dùng: đóng với mã `4401`. `Origin` không nằm trong `CORS_ORIGINS`: đóng với mã `4403`, trước khi vé bị dùng.
3. Khung gửi lên:
   - `{"op": "subscribe", "topic": "org:<id>"}` → `{"op": "subscribed", "topic": ...}` hoặc `{"op": "error", "code": "topic_not_found"}`
   - `{"op": "unsubscribe", "topic": ...}` → `{"op": "unsubscribed", "topic": ...}`
   - `{"op": "ping"}` → `{"op": "pong"}`
4. Khung nhận về:
   - Sự kiện: `{"type": "...", "topic": "...", ...}`
   - Thu hồi: `{"op": "revoked", "topic": "..."}`. Topic phòng có thêm `room_id`.
   - `{"type": "resync", "was": "..."}`: sự kiện quá lớn để chuyển giữa các worker (giới hạn của `NOTIFY` là 8000 byte). Trang cần tải lại dữ liệu của topic đó.
5. Mỗi kết nối sống tối đa 30 phút, sau đó đóng với mã `4408`. Trình duyệt lấy vé mới và nối lại.

`POST /chat/tickets`, `/ws/chat`, và khung `{"op": "subscribe", "room_id": "..."}` vẫn chạy như bí danh, trả lời theo dạng cũ (`room_id`, `room_not_found`).

## Gửi sự kiện từ code

```python
from src.realtime import bus
from src.realtime.names import org_topic

bus.emit(db, org_topic(org.id), {"type": "members.changed", "org_id": str(org.id)})
db.commit()
```

| Hàm | Khi nào |
| ---- | ---- |
| `bus.emit(db, topic, body)` | Trước `commit`. Gửi khi giao dịch commit, bỏ khi rollback |
| `bus.revoke(db, user_id, topics)` | Trước `commit`, khi một người mất quyền. Socket của họ rời các topic đó và nhận `revoked` |
| `bus.publish(topic, body)` | Sau khi đã commit (ví dụ service tự commit) |
| `bus.revoke_committed(user_id, topics)` | Như `revoke`, sau khi đã commit |

Sự kiện của tổ chức gom trong `src/organizations/signals.py`: `members_changed`, `applications_changed`, `membership_changed`, `lose_membership`, `lose_manager_role`.

## Mất quyền giữa chừng

Socket chỉ kiểm tra quyền lúc `subscribe`, nên mọi thay đổi làm mất quyền phải gọi `revoke`:

| Thay đổi | Topic bị cắt |
| ---- | ---- |
| Tự rời hoặc bị xóa khỏi tổ chức | `org:`, `org-managers:`, phòng chung, mọi kênh, tin nhắn riêng của người đó trong tổ chức |
| Bị hạ từ quản trị xuống thành viên | `org-managers:` và các kênh giới hạn họ không phải thành viên |
| Bị xóa khỏi kênh giới hạn | Phòng của kênh đó |

## Nhiều worker

- `emit` và `revoke` chạy `pg_notify('amigo_realtime', ...)` trong cùng giao dịch, nên PostgreSQL chỉ gửi khi commit.
- Mỗi tiến trình có một luồng `Listener` (`src/realtime/listener.py`) giữ một kết nối riêng ở chế độ `LISTEN`. Nó chuyển sự kiện tới socket của tiến trình mình, và bỏ qua sự kiện do chính tiến trình mình gửi (tiến trình đó đã gửi ngay sau commit).
- Mất kết nối thì luồng thử lại sau 2 giây. Sự kiện lúc mất kết nối bị lỡ; trình duyệt tải lại khi nối lại.

## Sổ đăng ký route

`src/realtime/coverage.py` liệt kê mọi route `POST`, `PUT`, `PATCH`, `DELETE`, mỗi route ghi một trong ba:

- `emits:` sự kiện và topic nó gửi
- `none:` vì sao không ai cần biết ngay
- `pending:` đợt triển khai sẽ làm

`tests/unit/test_realtime_coverage.py` hỏng khi có route thiếu hoặc thừa trong sổ, nên route mới phải tự khai.

## Các đợt triển khai

| Đợt | Nội dung | Trạng thái |
| ---- | ---- | ---- |
| 1 | Khung, thông báo, chat, thành viên và yêu cầu tham gia | Xong |
| 2 | Hoạt động: số chỗ, đăng ký, danh sách chờ | Chưa |
| 3 | Bài viết, bình luận, điểm danh, khiếu nại | Chưa |
| 4 | Hồ sơ tổ chức, chứng nhận, giờ tình nguyện | Chưa |
