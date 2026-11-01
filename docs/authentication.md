# Xác thực và tài khoản

Tài liệu này mô tả phần tài khoản của backend. Code nằm trong [`src/auth/`](../src/auth).

## Cơ chế

| Thành phần | Cách làm |
| ---- | ---- |
| Khóa chính | UUIDv7, sinh bằng `uuid.uuid7()` |
| Băm mật khẩu | Argon2id, theo cấu hình mặc định của `argon2-cffi` (hồ sơ RFC 9106 dùng ít bộ nhớ) |
| Access token | JWT ký HS256 bằng `JWT_SECRET`, sống 15 phút |
| Refresh token | Chuỗi ngẫu nhiên sống 30 ngày, chỉ lưu bản băm SHA-256 |
| Thư xác nhận | Token dùng một lần, chỉ lưu bản băm SHA-256 |

### Phiên đăng nhập

- Mỗi lần đăng nhập tạo một dòng trong `auth_sessions`.
- `auth_sessions.session_id` bằng `auth_refresh_tokens.family_id`, nên một phiên sở hữu một họ refresh token.
- JWT mang `sid`. Mỗi request đều kiểm tra phiên, nên đăng xuất có hiệu lực ngay mà không phải chờ token hết hạn.

### Đổi refresh token

- Mỗi lần gọi `POST /auth/refresh`, token cũ bị thu hồi và token mới được cấp.
- Nếu token cũ được dùng lại trong vòng 10 giây, hệ thống coi đó là các request song song và vẫn cấp token mới.
- Nếu token cũ được dùng lại sau 10 giây, hệ thống coi đó là token bị lộ và thu hồi cả phiên.

## API

Lỗi nghiệp vụ trả về `detail` là một mã cố định, ví dụ `email_taken`. Frontend tự dịch mã này sang tiếng Việt.

| Phương thức và đường dẫn | Cần token | Chức năng |
| ---- | ---- | ---- |
| `POST /auth/register` | Không | Đăng ký, trả về thông tin người dùng và token |
| `POST /auth/login` | Không | Đăng nhập |
| `POST /auth/refresh` | Không | Đổi refresh token lấy cặp token mới |
| `POST /auth/logout` | Có | Đăng xuất phiên hiện tại |
| `POST /auth/logout-all` | Có | Đăng xuất mọi phiên |
| `GET /auth/sessions` | Có | Xem các phiên đang hoạt động |
| `DELETE /auth/sessions/{session_id}` | Có | Thu hồi một phiên |
| `POST /auth/password/forgot` | Không | Gửi liên kết đặt lại mật khẩu, luôn trả 202 dù email có tồn tại hay không |
| `POST /auth/password/reset` | Không | Đặt lại mật khẩu và đăng xuất mọi phiên |
| `POST /auth/password/change` | Có | Đổi mật khẩu và đăng xuất các phiên khác |
| `POST /auth/email/verify` | Không | Xác minh email |
| `POST /auth/email/resend` | Có | Gửi lại liên kết xác minh |
| `GET /account/me` | Có | Xem thông tin tài khoản |
| `PATCH /account/me` | Có | Sửa thông tin. Chỉ các trường có trong body mới thay đổi |
| `POST /account/me/email` | Có | Đổi email, chỉ có hiệu lực sau khi xác nhận ở email mới |
| `DELETE /account/me` | Có | Xóa tài khoản, cần mật khẩu |

Xóa tài khoản giữ lại bản ghi để không gãy khóa ngoại, nhưng xóa thông tin cá nhân. Tài khoản đang sở hữu tổ chức sẽ bị từ chối xóa với mã `owns_organizations`.

## Quy tắc dữ liệu

Các quy tắc nằm trong [`validators.py`](../src/auth/validators.py) và [`schemas.py`](../src/auth/schemas.py).

| Trường | Quy tắc | Lưu trong database |
| ---- | ---- | ---- |
| Email | Đúng định dạng, không trùng, không phân biệt hoa thường | Như đã nhập |
| Mật khẩu mới | Xem mục bên dưới | Bản băm Argon2id |
| Họ và tên | 1–120 ký tự | Đã bỏ khoảng trắng hai đầu |
| Số điện thoại | Số Việt Nam dạng `0...`, `84...`, `+84...`, hoặc số quốc tế dạng `+...` | Dạng chuẩn, ví dụ `+84912345678` |
| Mã số thuế | 10 chữ số, hoặc 13 chữ số với chi nhánh | `0101234567` hoặc `0101234567-001` |
| Giấy tờ người đại diện | CCCD 12 số, CMND 9 số, hoặc số hộ chiếu 6–20 ký tự có chữ cái | Viết hoa |
| Ngày sinh | Trong quá khứ, từ năm 1900 trở đi | Như đã nhập |
| Giới tính | `male`, `female`, `other`, `unspecified` | Như đã nhập |
| Địa chỉ | Tối đa 500 ký tự | Đã bỏ khoảng trắng hai đầu |

Khoảng trắng, dấu chấm, gạch ngang và ngoặc trong số điện thoại được bỏ qua. Vì vậy `0912.345.678` và `+84912345678` được coi là cùng một số và không thể đăng ký hai lần.

### Mật khẩu

Mật khẩu mới phải có đủ:

- ít nhất 8 và tối đa 128 ký tự
- một chữ hoa
- một chữ thường
- một chữ số
- một ký tự đặc biệt (mọi ký tự không phải chữ hoặc số, kể cả khoảng trắng)

Mật khẩu cũng bị từ chối nếu:

- quá phổ biến, ví dụ `Password123!` hoặc `Matkhau123!`
- là dãy liên tiếp hoặc lặp lại một mẫu ngắn
- chứa phần tên trong email hoặc họ tên của người dùng

Các quy tắc này chỉ áp dụng khi đặt mật khẩu mới. Đăng nhập không kiểm tra lại, nên tài khoản có mật khẩu cũ vẫn đăng nhập được.

### Định dạng lỗi

Dữ liệu sai định dạng trả về 422 với danh sách lỗi theo từng trường. Phản hồi không chứa giá trị đã gửi lên, để mật khẩu không bị trả lại.

```json
{
  "detail": [
    {
      "type": "phone_invalid",
      "loc": ["body", "phone"],
      "msg": "Phone number is not valid"
    }
  ]
}
```

| Mã `type` | Ý nghĩa |
| ---- | ---- |
| `required` | Thiếu trường bắt buộc |
| `phone_invalid` | Số điện thoại không hợp lệ |
| `tax_code_invalid` | Mã số thuế không hợp lệ |
| `legal_id_invalid` | Số giấy tờ không hợp lệ |
| `birth_date_invalid` | Ngày sinh không hợp lệ |
| `password_too_weak` | Mật khẩu thiếu chữ hoa, chữ thường, số hoặc ký tự đặc biệt |
| `password_common` | Mật khẩu quá phổ biến |
| `password_personal` | Mật khẩu chứa thông tin cá nhân |

## Giới hạn số lần thử

| Thao tác | Giới hạn |
| ---- | ---- |
| Đăng nhập | 10 lần mỗi email và 50 lần mỗi IP trong 15 phút |
| Đăng ký | 20 lần mỗi IP trong 1 giờ |
| Quên mật khẩu | 3 lần mỗi email và 20 lần mỗi IP trong 1 giờ |
| Nhập mật khẩu để xác nhận | 10 lần mỗi tài khoản trong 15 phút |
| Gửi email xác minh | 5 lần mỗi tài khoản trong 1 giờ |

Vượt giới hạn trả về 429 với mã `rate_limited` và header `Retry-After`.

## Cấu hình

Các giá trị đọc từ `.env`:

| Biến | Bắt buộc | Mặc định | Ý nghĩa |
| ---- | ---- | ---- | ---- |
| `JWT_SECRET` | Có | | Chuỗi ngẫu nhiên, ít nhất 32 ký tự |
| `ACCESS_TOKEN_MINUTES` | Không | 15 | Thời hạn access token |
| `REFRESH_TOKEN_DAYS` | Không | 30 | Thời hạn refresh token |
| `PASSWORD_RESET_MINUTES` | Không | 60 | Thời hạn liên kết đặt lại mật khẩu |
| `EMAIL_VERIFICATION_HOURS` | Không | 24 | Thời hạn liên kết xác minh email |
| `FRONTEND_URL` | Không | `http://localhost:3000` | Địa chỉ dùng trong liên kết của email |
| `SMTP_HOST` | Với production | | Máy chủ gửi email |
| `SMTP_PORT` | Không | 587 | Cổng SMTP, dùng STARTTLS |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Không | | Tài khoản SMTP |
| `SMTP_FROM` | Không | `no-reply@amigoact.local` | Địa chỉ người gửi |

## Triển khai

- **Email:** nếu chưa đặt `SMTP_HOST`, email cùng liên kết bí mật được ghi vào log. Chỉ dùng cách này khi phát triển.
- **Proxy:** giới hạn theo IP dùng địa chỉ uvicorn nhận được. Nếu chạy sau proxy, đặt `--forwarded-allow-ips` bằng địa chỉ proxy để `X-Forwarded-For` chỉ được tin từ đó.
- **Đổi `JWT_SECRET`:** mọi access token hiện có mất hiệu lực. Người dùng vẫn giữ phiên nhờ refresh token.

## Kiểm thử

Test nằm trong `tests/unit`, `tests/integration` và `tests/regression`. Test tích hợp dùng database trong `.env` và chỉ xóa các dòng do chính test tạo ra.

```bash
uv run pytest
```
