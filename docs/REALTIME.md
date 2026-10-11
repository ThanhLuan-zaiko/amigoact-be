# Realtime — WebSocket (`realtime/` + `core/realtime.py`)

## 1. Tổng quan

Realtime dùng WebSocket ngay từ đầu (AGENTS.md §16). Không polling, không
SSE, không Socket.IO/Pusher/Ably. Transport là `WebSocket` của FastAPI;
package bổ sung duy nhất là `websockets` (FastAPI yêu cầu cho hỗ trợ WS).

Luồng xác thực (bắt buộc, §16.2): trình duyệt không gắn được header vào
handshake WebSocket nên JWT không bao giờ nằm trong URL. Client gọi
`POST /ws/tickets` bằng Bearer JWT để lấy ticket một lần, sau đó mở
`GET /ws?ticket=<ticket>`.

```text
POST /ws/tickets (Authorization: Bearer <jwt>)
    -> 201 {"ticket": "<opaque>", "expires_in": 60}
WS  /ws?ticket=<opaque>
    -> {"type": "ready.v1", "data": {"user_id", "channels", "heartbeat_seconds"}}
WS  /ws                  # khách, không ticket
    -> ready.v1 với user_id = null, channels = []
```

- Ticket là chuỗi opaque 256-bit (`secrets.token_urlsafe(32)`); chỉ lưu
  SHA-256 trong bảng `ws_tickets` (`default_time_to_live = 300`).
- Dùng một lần: consume bằng `DELETE ... IF EXISTS` (LWT). Hết hạn hoặc đã
  dùng đều đóng `4401`. Không bao giờ log ticket.
- **Socket ẩn danh**: thiếu ticket mở socket khách — `user_id` là `None`,
  server không tự join kênh nào, và `authorize()` chỉ cho phép các kênh
  public (§3). Ticket *có nhưng sai/hết hạn* vẫn `4401`: credential xấu
  không bao giờ bị hạ thầm lặng thành guest. Socket ẩn danh vẫn chịu mọi
  giới hạn frame/subscribe như socket thường.

## 2. Envelope và frame

Mọi frame là JSON `{"type": "<tên có version>", "data": {...}}`.

| Hướng | `type` | Ý nghĩa |
|---|---|---|
| server → client | `ready.v1` | Socket đã bind user; kèm `heartbeat_seconds` |
| server → client | `ping.v1` | Heartbeat mỗi `WS_HEARTBEAT_SECONDS` |
| server → client | `subscribed.v1` | Join kênh thành công (`channel`, `channels`) |
| server → client | `unsubscribed.v1` | Rời kênh thành công |
| server → client | `event.v1` | Dữ liệu live: `{"channel", "payload"}` |
| server → client | `error.v1` | Lỗi frame: `{"code", "message", "channel"?}` |
| client → server | `pong.v1` | Trả lời heartbeat trong `WS_PONG_TIMEOUT_SECONDS` |
| client → server | `ping.v1` | Probe liveness; server trả `pong.v1` |
| client → server | `subscribe.v1` | `data.channel = "kind:{uuid}"` |
| client → server | `unsubscribe.v1` | `data.channel = "kind:{uuid}"` |

`type` lạ được bỏ qua và ghi log, không bao giờ làm sập kết nối.

## 3. Kênh và phân quyền (§16.3)

| Kênh | Quyền |
|---|---|
| `notifications:{user_id}` | Chỉ chủ nhân (`subject == user_id`); server tự join sau handshake |
| `activities:{org_id}` | Phải là member của org (`members_by_user`) |
| `members:{org_id}` | Phải là member `active` của org; nhận `event.v1` mọi thay đổi roster |
| `attendance:{activity_id}` | Manager của org sở hữu activity — port `AttendanceAccess`: owner hoặc quyền `activity:manage` (khớp `GET /activities/{id}/attendance`) |
| `orgs:directory` | **Public** — mở cho mọi socket kể cả ẩn danh; subject cố định `directory` (không phải UUID) |

Đăng ký bị từ chối: server gửi `error.v1` `FORBIDDEN` rồi đóng `4403`.
Tên kênh sai cú pháp: `error.v1` `INVALID_CHANNEL`, kết nối vẫn sống.

## 4. Mã đóng kết nối

| Code | Nghĩa |
|---|---|
| `4400` | Bad frame: JSON hỏng hoặc payload sai (kèm `error.v1` `BAD_FRAME`) |
| `4401` | Ticket sai/hết hạn/đã dùng lúc handshake (thiếu ticket → socket ẩn danh, không đóng) |
| `4403` | Subscribe bị từ chối quyền (kèm `error.v1` `FORBIDDEN`) |
| `4408` | Client bỏ lỡ `pong.v1` quá `WS_PONG_TIMEOUT_SECONDS` |

## 5. Kiến trúc

- `core/realtime.py` (§16.6): codec envelope, parse kênh, `ConnectionManager`
  (registry socket trong RAM — ephemeral transport, không bao giờ là fact
  source §16.5), `heartbeat_loop`, hằng số close code.
- `realtime/` theo chuẩn 6 file: `model.py` (bảng `ws_tickets`),
  `repository.py` (`CqlWsTicketStore`, LWT consume), `interfaces.py`
  (`WsTicketStore`, `OrgMembership`, `AttendanceAccess`), `service.py`
  (`RealtimeService`: issue/consume ticket + `authorize`), `router.py`
  (REST ticket + `/ws` mỏng), `schemas.py` (`WsTicketResponse`).
- Wiring: `core/dependencies.py` (`get_realtime_service`,
  `get_connection_manager` — registry tạo ở lifespan/`app.state`).
- DB call đồng bộ (cqlengine) được bọc `asyncio.to_thread` trong handler
  async để không chặn event loop.
- Fan-out: `ConnectionManager.publish(channel, payload)` → `event.v1` tới
  mọi socket của kênh. Resume sau reconnect đọc lại từ ScyllaDB (không
  replay RAM).
- Publish từ code đồng bộ (service sync chạy trong endpoint async):
  `schedule_publish(channel, payload)` xếp task lên loop đang chạy, trả
  `False` nếu không có loop (unit test) — publish là best-effort, không
  bao giờ làm hỏng request.

### Sự kiện membership (orgs)

`MemberService` phát qua port `MemberEvents` sau mỗi mutation thành công:

| Kênh | `payload.action` | `payload` còn lại |
|---|---|---|
| `members:{org_id}` | `invited`/`accepted`/`declined`/`joined`/`promoted`/`demoted`/`suspended`/`reactivated`/`removed`/`left` | `user_id`, `actor_id` |
| `notifications:{user_id}` | cùng action | `scope: "membership"`, `org_id` |

Kênh `notifications` cho người được mời/bị đổi — họ chưa (hoặc không
còn) là member nên không subscribe được `members:{org_id}`. Client chỉ
invalidate TanStack Query khi nhận event; không tin payload làm sự thật.

### Sự kiện attendance (registrations)

`AttendanceService` phát qua port `AttendanceEvents` sau mỗi mutation
check-in/check-out thành công (kể cả `check_in_manual`, vì nó ủy quyền
cho `check_in`):

| Kênh | `payload.action` | `payload` còn lại |
|---|---|---|
| `attendance:{activity_id}` | `checked_in`/`checked_out` | `record_id`, `student_id`, `actor_id` |

Màn điểm danh của manager subscribe kênh này để danh sách tự cập nhật
khi staff khác quét vé. Client chỉ invalidate query, không tin payload.

### Sự kiện thư mục công khai (orgs)

`OrgService` phát qua port `OrgDirectoryEvents` sau khi mutation +
projection `organizations_public` commit; `AdminService` phát `updated`
sau `set_legal_status` (verify/reject). Adapter `WsOrgDirectoryEvents`
(`orgs/directory_events.py`) chỉ là `schedule_publish` mỏng — registry
chết cũng không làm hỏng request.

| Kênh | `payload.action` | `payload` còn lại |
|---|---|---|
| `orgs:directory` | `created`/`updated`/`restored`/`removed` | `org_id`, `slug` |

Phát sinh từ: `create_org` → `created`, `update_org` → `updated`,
`soft_delete_org` → `removed`, `restore_org` → `restored`,
`hard_delete_org` → `removed` (slug chụp trước khi xóa).

Payload chỉ chứa field vốn public — guest nào cũng nghe được nên không
được đưa dữ liệu riêng vào đây. Client coi event là gợi ý refetch và
gọi lại `GET /orgs` / `GET /orgs/{slug}`: REST mới là fact source nên
event giả hay cũ không thể "hồi sinh" org đã ẩn.

## 6. Cấu hình

| Biến | Mặc định | Mô tả |
|---|---|---|
| `WS_TICKET_TTL_SECONDS` | `60` | Tuổi thọ ticket một lần |
| `WS_HEARTBEAT_SECONDS` | `25` | Chu kỳ `ping.v1` của server |
| `WS_PONG_TIMEOUT_SECONDS` | `10` | Grace chờ `pong.v1` trước khi đóng `4408` |
