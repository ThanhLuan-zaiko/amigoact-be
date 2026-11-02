# Lộ trình phát triển

Tài liệu này ghi kế hoạch theo giai đoạn của toàn bộ AmigoACT, gồm backend và frontend. Hai repo giữ cùng một bản, nên khi đổi lộ trình hãy cập nhật cả hai file `docs/roadmap.md`.

## Mục tiêu sản phẩm

AmigoACT giúp các tổ chức quản lý hoạt động tình nguyện và ghi nhận đóng góp của người tham gia. Vòng giá trị cốt lõi là:

**Tổ chức đăng hoạt động → tình nguyện viên đăng ký → điểm danh → cộng giờ → cấp chứng nhận.**

Tính năng nào không nằm trên vòng này thì làm sau. Mỗi giai đoạn làm trọn cả backend lẫn frontend, để có thứ dùng được thật.

## Quyết định sản phẩm

| Câu hỏi | Quyết định |
| ---- | ---- |
| Ai được tạo tổ chức? | Mọi người dùng đã đăng nhập, và trở thành chủ sở hữu. Không cần duyệt |
| Tình nguyện viên là ai? | Bất kỳ ai cùng chí hướng, không bắt buộc là sinh viên |
| Đăng ký hoạt động có cần vào tổ chức không? | Không |
| Điểm danh bằng cách nào? | Quét QR (tính ngay), hoặc nhập mã (chờ ban quản trị duyệt) |
| Khóa chính | UUIDv7 ở mọi bảng |
| Kiểm tra dữ liệu | Chi tiết theo từng trường, mỗi lỗi có mã cố định để dịch sang tiếng Việt |
| Giao diện | Phẳng, một màu nhấn teal, không đổ bóng và không nền tô khác màu, ưu tiên icon thay cho chữ |

## Tổng quan

| Giai đoạn | Nội dung | Trạng thái |
| ---- | ---- | ---- |
| Nền tảng | Tài khoản, phiên đăng nhập, CI | Xong |
| 1 | Tổ chức và thành viên | Xong |
| 2 | Hoạt động và đăng ký | Xong |
| 3 | Điểm danh và giờ tình nguyện | Xong |
| 4 | Chứng nhận và thông báo | Backend xong, chờ giao diện |
| 5 | Bảng tin, tải tệp, rồi chat | Đang làm |
| 6 | Báo cáo, đánh giá, quản trị nền tảng | Chưa làm |

## Đã xong

### Nền tảng

Đăng ký, đăng nhập, refresh token xoay vòng, quản lý phiên, đổi và đặt lại mật khẩu, xác minh email, hồ sơ cá nhân. Chi tiết trong `docs/authentication.md`.

### Giai đoạn 1: tổ chức và thành viên

- Tạo và sửa hồ sơ tổ chức, danh bạ có tìm kiếm.
- Tham gia ngay với tổ chức mở, gửi yêu cầu với tổ chức cần duyệt. Bị từ chối thì chờ 7 ngày mới gửi lại được.
- Ba vai trò: chủ sở hữu, quản trị viên, thành viên.
- Lớp kiểm tra dữ liệu dùng chung trong `src/validation.py` và kiểu `Uuid7` cho ID trên đường dẫn.
- Chi tiết trong `docs/organizations.md`.

Còn lại: xóa tổ chức, chuyển quyền sở hữu, mời thành viên, câu hỏi khi xin tham gia, logo tổ chức.

### Giai đoạn 2: hoạt động và đăng ký

- Vòng đời hoạt động: bản nháp, đăng, kết thúc, hủy.
- Ca với số chỗ riêng, chặn đăng ký hai ca trùng giờ.
- Sức chứa, danh sách chờ tự chuyển lên, duyệt hoặc từ chối, lịch sử mọi lần đổi trạng thái.
- Khóa dòng để hai người không thể cùng lấy chỗ cuối.
- Chi tiết trong `docs/activities.md`.

Còn lại: danh mục và thẻ, ảnh bìa, câu hỏi khi đăng ký, ô ghi chú và lý do trên giao diện.

### Giai đoạn 3: điểm danh và giờ tình nguyện

- Phiên điểm danh theo ca hoặc cả hoạt động, có mã QR và mã nhập tay.
- Ban quản trị xác nhận mã nhập tay hoặc điểm danh hộ. Mọi lần thử đều được ghi lại.
- Sổ giờ chỉ thêm, không sửa. Ghi giờ khi kết thúc hoạt động, có điều chỉnh kèm lý do.
- Quy tắc tính giờ của tổ chức: hệ số và giới hạn mỗi kỳ.
- Khiếu nại điểm danh.
- Chi tiết trong `docs/attendance.md`.

Còn lại: điểm danh ra về, quét QR cá nhân bằng `checkin_token`, bảng xếp hạng, nhập giờ thủ công ngoài hoạt động.

## Giai đoạn 4: chứng nhận và thông báo

Đây là bước cuối của vòng giá trị cốt lõi.

### Chứng nhận

Bảng: `certificates`, `certificate_revocations`, `certificate_templates`.

- Khi hoạt động kết thúc, ban quản trị cấp chứng nhận cho những người có đăng ký `attended`. Mỗi người có một chứng nhận cho mỗi hoạt động, theo ràng buộc của schema.
- Mỗi chứng nhận có một số serial duy nhất, không đoán được.
- Trang xác minh công khai theo serial, không cần đăng nhập. Trang chỉ hiện tên người nhận, hoạt động, tổ chức, số giờ, ngày cấp và trạng thái.
- Thu hồi cần lý do và được ghi vào `certificate_revocations`. Chứng nhận đã thu hồi vẫn tra được và hiện rõ trạng thái.
- Tình nguyện viên xem danh sách chứng nhận của mình và in từ trình duyệt ra PDF.
- Mẫu chứng nhận tùy biến và lưu file PDF cần phần tải tệp, nên để sang giai đoạn 5.

### Thông báo

Bảng: `notifications`, `notification_preferences`.

- Thông báo trong ứng dụng, có chuông trên header, số chưa đọc và trang danh sách.
- Các sự kiện cần báo: đăng ký được duyệt hoặc từ chối, được chuyển lên từ danh sách chờ, hoạt động bị hủy, yêu cầu vào tổ chức được duyệt hoặc từ chối, giờ được ghi, khiếu nại được xử lý, chứng nhận được cấp hoặc thu hồi.
- Thông báo gửi email qua `Mailer` đã có, nếu người dùng bật.
- Người dùng tắt được từng loại và từng kênh trong trang tài khoản.
- Thông báo được ghi cùng giao dịch với sự kiện, nên sự kiện thất bại thì không có thông báo. Email gửi sau khi giao dịch thành công.

### Hoàn thành khi

- Người có mặt nhận được chứng nhận, và ai có đường link đều xác minh được.
- Mỗi sự kiện trên đều tạo thông báo cho đúng người, và chuông hiện đúng số chưa đọc.
- Có đủ test unit, integration và regression cho mọi endpoint mới.

### Trạng thái

- Backend xong: cấp, thu hồi, hoàn tác thu hồi, trang xác minh công khai, chứng nhận của tôi, thông báo trong ứng dụng, tùy chọn theo kênh và theo loại, gửi email. Chi tiết trong `docs/certificates.md` và `docs/notifications.md`.
- Chưa làm: giao diện (trang xác minh, chuông, trang thông báo, cài đặt thông báo, danh sách chứng nhận). Mẫu chứng nhận đã làm ở bước 2 của giai đoạn 5.

## Giai đoạn 5: bảng tin, tải tệp, rồi chat

Làm theo thứ tự này, vì bảng tin và chat đều cần tải tệp.

1. **Tải tệp** (`media_assets`, `media_moderation`): ảnh đại diện, logo tổ chức, ảnh bìa hoạt động, file PDF chứng nhận. Backend đã có tải ảnh, đọc ảnh và gắn ảnh vào đại diện, logo, ảnh bìa, lưu trên ổ đĩa, xem [`media.md`](media.md). Còn lại: kiểm duyệt, xóa tệp, PDF chứng nhận, giao diện.
2. **Mẫu chứng nhận** (`certificate_templates`): phần còn lại của giai đoạn 4, vì cần ảnh nền. Backend đã có mẫu và gắn mẫu khi cấp chứng nhận, xem [`certificates.md`](certificates.md). Còn lại: dựng file PDF từ mẫu và giao diện chỉnh vị trí chữ.
3. **Bảng tin** (`org_posts`, `post_tags`, `org_post_media`, `org_post_comments`): bài đăng và bình luận của tổ chức, làm thật trang chủ và trang tạo bài đang là bản nháp giao diện. Mục "Thẻ phổ biến" trên rail lấy dữ liệu từ đây. Backend đã có bài đăng, nháp, ghim, bình luận, thẻ, ảnh và các danh sách, xem [`posts.md`](posts.md). Còn lại: khối nội dung, thùng rác, giao diện.
4. **Chat** (`org_room_messages`, `org_dm_pairs`, `org_chat_channels` và các bảng liên quan): cần WebSocket và `ws_tickets`, nên phức tạp nhất và làm cuối. Mục "Tin nhắn" đang trỏ tới trang chưa có. Backend đã có phòng chung, kênh, tin nhắn riêng, tin nhắn, phản ứng, ghim, đọc chưa đọc và WebSocket, xem [`chat.md`](chat.md). Nội dung tin được mã hóa AES-256-GCM bằng khóa trong `.env`. Còn lại: đính kèm tệp, chạy nhiều tiến trình, giao diện.

## Giai đoạn 6: báo cáo, đánh giá, quản trị nền tảng

- **Báo cáo và xuất file** (`report_snapshots`, `activity_daily_stats`, `org_monthly_stats`, `export_jobs`): thống kê của tổ chức, xuất danh sách ra CSV.
- **Bảng xếp hạng** (`hours_by_student`, view `leaderboard_by_term`): theo kỳ. Cần quyết định có hiển thị công khai không.
- **Đánh giá hoạt động** (`reviews`): tình nguyện viên đánh giá sau khi tham gia.
- **Quản trị nền tảng** (`platform_user_roles`, `access_audit_logs`): khóa tổ chức vi phạm, xác minh pháp lý của tổ chức, xem nhật ký.
- **Liên hệ người đăng ký**: quyết định ban quản trị có được thấy email và số điện thoại không. Hiện tại danh sách chỉ hiện họ tên.

## Quy tắc khi làm mỗi giai đoạn

- Mỗi endpoint có đủ test unit, integration và regression. Gate 13 kiểm tra mọi route đều có test nhắc tới.
- Mỗi file `.py` và `.ts` tối đa 350 dòng, mỗi file `.tsx` tối đa 260 dòng.
- Mỗi chủ đề có một file trong `docs/` ở cả hai repo, cập nhật cùng lúc với code.
- Chỉ dùng các bảng cần thiết trong `schema.sql`, không triển khai hết một lần.
- Chạy thử luồng chính trên trình duyệt trước khi báo xong, và nói rõ phần nào chưa kiểm tra.
