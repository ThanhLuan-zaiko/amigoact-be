# Chính sách bảo mật — amigoact-be

## Phiên bản được hỗ trợ

| Nhánh | Trạng thái |
|---|---|
| `main` | Được hỗ trợ, vá bảo mật ưu tiên |
| Nhánh tính năng/PR | Chỉ hỗ trợ trong thời gian review |

## Phạm vi nhạy cảm

- Băm mật khẩu Argon2id (`argon2-cffi`), tham số công khai trong `core/hashing.py`.
- JWT access ngắn hạn (5–15 phút) + refresh token opaque (lưu hash SHA-256, cookie `HttpOnly; Secure; SameSite=Lax`, xoay vòng, phát hiện tái sử dụng).
- Khóa chính UUIDv7, không dùng tính sắp xếp theo thời gian của UUIDv7 để phân quyền thay cho kiểm tra quyền tường minh.
- ScyllaDB: xác thực keyspace, không hard-code credential, log không chứa mật khẩu/token/hash/secret.

## Cách báo cáo lỗ hổng

1. Không tạo issue công khai cho lỗ hổng chưa vá.
2. Gửi cho maintainer: mô tả, mức độ ảnh hưởng, bước tái hiện, log đã che secret, đề xuất khắc phục (nếu có).
3. Không khai thác vượt mức cần thiết để chứng minh, không truy xuất dữ liệu người khác.

## Cam kết xử lý

- Xác nhận tiếp nhận trong 48 giờ.
- Đánh giá và vá theo mức độ: nghiêm trọng trong 7 ngày, trung bình trong 30 ngày.
- Thông báo bản vá và ghi nhận người báo cáo (nếu đồng ý).

## Quy tắc cho người đóng góp

- Không commit secret, file `.env`, hash mật khẩu thật, token thật, host production.
- Thông điệp lỗi auth chung chung (`Invalid credentials`), không lộ user tồn tại hay lý do chi tiết.
- Mọi thay đổi auth/hash/token phải kèm kiểm thử đơn vị + tích hợp + hồi quy.
