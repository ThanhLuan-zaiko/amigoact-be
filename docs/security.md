# Bảo vệ API: khóa nội bộ và CORS

Backend chỉ phục vụ server Next.js. Trình duyệt không gọi API HTTP trực tiếp, trừ socket realtime.

## Khóa nội bộ (`INTERNAL_API_KEY`)

- Đặt trong `.env` của backend, ít nhất 32 ký tự (`openssl rand -hex 32`). Frontend đặt cùng giá trị trong `.env.local`.
- Thiếu hoặc ngắn hơn 32 ký tự thì backend không khởi động.
- Mọi request HTTP phải có header `X-Internal-Key` đúng giá trị. Sai hoặc thiếu thì trả `401` với `detail` là `internal_key_invalid`.
- Kiểm tra nằm trong `InternalKeyMiddleware` (`src/internal_key.py`), một middleware ASGI chạy trước định tuyến, xác thực và validation. Vì vậy người ngoài không nhận được lỗi `422`, không dò được các trường của request, và không xem được `/docs` hay `/openapi.json`.
- Validation vẫn chạy đầy đủ cho request có khóa. Khóa chỉ đứng trước validation, không thay thế nó.
- So sánh bằng `hmac.compare_digest`, nên thời gian phản hồi không làm lộ khóa.
- Token đăng nhập bị lộ cũng không đủ để gọi API, vì còn thiếu khóa.
- Ngoại lệ duy nhất là socket realtime `/ws` (bí danh `/ws/chat`): trình duyệt mở trực tiếp bằng vé dùng một lần. Server Next.js lấy vé đó qua `POST /realtime/tickets` có kèm khóa. Xem [realtime.md](realtime.md).
- Đổi khóa: sửa cả hai file `.env` rồi khởi động lại cả hai server.

## CORS (`CORS_ORIGINS`)

- Danh sách origin cách nhau bởi dấu phẩy, ví dụ `http://localhost:3000,https://amigoact.example`. Mỗi origin có dạng `scheme://host[:port]`, không có dấu `/` ở cuối, không có đường dẫn.
- Không chấp nhận `*`. Origin sai định dạng làm backend không khởi động.
- Để trống nghĩa là không cho origin nào, là lựa chọn chặt nhất.
- Danh sách điều khiển hai thứ:
  - Header CORS của HTTP (`CORSMiddleware`). Không bật `allow_credentials`, vì token đi trong header `Authorization`, không đi trong cookie.
  - Socket realtime. CORS không áp dụng cho WebSocket, nên `/ws` tự kiểm tra header `Origin`: có `Origin` mà không nằm trong danh sách thì đóng với mã `4403`, trước khi vé bị dùng. Không có `Origin` (không phải trình duyệt) thì vẫn cần vé hợp lệ.
- `CORSMiddleware` nằm ngoài `InternalKeyMiddleware`, nên preflight được trả lời mà không cần khóa.
- CORS chỉ là luật của trình duyệt. Nó không chặn curl hay Postman; khóa nội bộ làm việc đó.

## Triển khai

- Vẫn nên cho backend chỉ nghe ở mạng nội bộ, và chỉ mở `/ws/chat` qua reverse proxy. Khóa nội bộ là lớp bảo vệ thứ hai khi cổng bị lộ.
- Đặt `CORS_ORIGINS` bằng địa chỉ frontend thật ở production.
