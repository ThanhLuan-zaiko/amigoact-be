# Bảng tin

Tài liệu này mô tả bảng tin của tổ chức: bài đăng, bình luận, thẻ và các danh sách trên trang chủ. Code nằm trong [`src/posts/`](../src/posts), bảng nằm trong [`src/models/posts.py`](../src/models/posts.py) và [`src/models/tags.py`](../src/models/tags.py).

## Hai loại bài

| Loại | Ai đăng | Mặc định xem được |
| ---- | ---- | ---- |
| `announcement` (thông báo) | Quản trị viên của tổ chức | Công khai |
| `discussion` (thảo luận) | Mọi thành viên đang hoạt động | Chỉ thành viên |

Người đăng có thể chọn `visibility` khác mặc định khi tạo hoặc sửa bài.

## Quyền xem

- Bài công khai: ai cũng xem được, kể cả khách chưa đăng nhập.
- Bài chỉ thành viên: thành viên đang hoạt động của tổ chức xem được. Người ngoài nhận 404, không phải 403, để không lộ bài tồn tại.
- Bản nháp: chỉ tác giả xem được. Người khác nhận 404.
- Bài đã xóa và bài của tổ chức bị tạm ngưng: không xem được ở bất kỳ danh sách nào.

## Vòng đời bài

- **Nháp**: `draft: true` khi tạo. Không hiện trong bảng tin, không bình luận được, không ghim được. Tác giả xem qua `post-drafts`.
- **Đăng**: `POST /posts/{id}/publish` chuyển nháp thành bài đăng và ghi `published_at`. Đăng lại bài đã đăng trả về 409 `post_not_draft`.
- **Sửa**: chỉ tác giả. Ghi `edited_at`. Không đổi loại bài. Gửi `tags` hoặc `media_ids` thì thay thế danh sách cũ.
- **Ghim**: chỉ quản trị viên, và chỉ với bài đã đăng. Bỏ ghim bằng `unpin`.
- **Xóa bản nháp**: chỉ tác giả. **Xóa cứng** ngay, vì bản nháp chưa từng có ai khác nhìn thấy.
- **Xóa bài đã đăng**: tác giả hoặc quản trị viên. **Xóa mềm**: ghi `deleted_at` và `deleted_by`, bỏ ghim. Bài biến mất khỏi mọi danh sách và `GET /posts/{id}` trả 404.

## Thùng rác, khôi phục và xóa vĩnh viễn

| Việc | Ai làm | Điều kiện | Lỗi |
| ---- | ---- | ---- | ---- |
| Xem thùng rác `GET /organizations/{slug}/post-trash` | Chủ sở hữu, quản trị viên | Thành viên đang hoạt động | 401, 403 `post_forbidden` |
| Khôi phục `POST /posts/{id}/restore` | Chủ sở hữu, quản trị viên | Bài đang trong thùng rác và chưa quá 30 ngày | 409 `post_not_in_trash`, 404 với người ngoài |
| Xóa vĩnh viễn `DELETE /posts/{id}/purge` | Chỉ chủ sở hữu | Bài đang trong thùng rác | 409 `post_not_in_trash`, 403 với quản trị viên, 404 với người ngoài |

- Bài nằm trong thùng rác **30 ngày** (`TRASH_DAYS` trong `src/posts/rules.py`). Mỗi lần mở thùng rác, bài quá hạn của tổ chức đó bị xóa hẳn trước khi liệt kê, nên không cần tác vụ chạy định kỳ. Bài quá hạn mà chưa bị dọn cũng không khôi phục được (404).
- Mỗi dòng thùng rác có `deleted_at`, `purge_at` (thời điểm tự xóa), `deleted_by_name` và `can_purge`. Thân bài không được trả về.
- Xóa vĩnh viễn xóa dòng `org_posts`. Thẻ, liên kết ảnh và bình luận đi theo nhờ `ON DELETE CASCADE`. Tệp ảnh không còn ai dùng sẽ được script dọn tệp xóa sau (xem [`media.md`](media.md)).
- Người không phải thành viên luôn nhận 404, để không lộ việc bài đã xóa có tồn tại.
- Code nằm trong [`src/posts/trash.py`](../src/posts/trash.py) và [`src/posts/trash_router.py`](../src/posts/trash_router.py).

## Bình luận

- Chỉ thành viên đang hoạt động bình luận được, và chỉ trên bài đã đăng. Khách chỉ đọc được bình luận của bài họ xem được.
- Bình luận phẳng, sắp theo thời gian tăng dần. Trang đi tiếp bằng `after`.
- **Sửa** (`PATCH /comments/{id}`): chỉ người viết, khi còn là thành viên, trong **15 phút** sau khi viết (`COMMENT_EDIT_MINUTES`). Quá hạn trả 409 `comment_edit_expired`. Ghi `edited_at`.
- **Xóa mềm** (`DELETE /comments/{id}`): người viết hoặc quản trị viên. Bình luận giữ chỗ trong luồng, trả về với `deleted: true` và `body` rỗng, nội dung cũ không bao giờ rời server. Xóa lần hai trả 404.
- **Khôi phục** (`POST /comments/{id}/restore`): chủ sở hữu hoặc quản trị viên. Bình luận chưa bị xóa trả 409 `comment_not_deleted`.
- **Xóa cứng**: đi cùng bài khi bài bị xóa vĩnh viễn.
- Mỗi bình luận trả về `can_edit`, `can_delete`, `can_restore`, `edited_at`. `comment_count` của bài không đếm bình luận đã xóa.
- Bình luận hiện tên người viết (`author_name`). Bài không hiện tên tác giả, chỉ hiện tên tổ chức.

## Thẻ

- Mỗi bài có tối đa 3 thẻ. Thẻ thuộc một tổ chức, được tạo khi có người dùng lần đầu.
- Thẻ được chuẩn hóa thành slug không dấu, chữ thường, nối bằng dấu gạch ngang. `Môi trường` và `moi truong` là cùng một thẻ. Tên không có chữ hoặc số nào thì bị từ chối (`tag_invalid`).
- `GET /feed/popular-tags` đếm số bài đã đăng, nhìn thấy được với người xem, trong 30 ngày gần nhất. Trả về tối đa 10 thẻ.

## Ảnh và video trong bài

- Ảnh và video (MP4, WEBM) phải do chính tác giả tải lên, qua [`/media`](media.md). Tệp của người khác nhận 404. Ảnh tối đa 20 MB, video tối đa 50 MB. Ảnh và video dùng chung danh sách `media_ids`, giữ đúng thứ tự gửi.
- Bản nháp: ảnh và video vẫn riêng tư. Khi bài được đăng, các tệp thành công khai.
- Bài công khai có ảnh: ảnh công khai ngay khi đăng.
- Bài chỉ thành viên không được có ảnh (`members_post_has_no_media`). Lý do: quyền xem ảnh theo nhóm chưa có. Bài công khai có ảnh thì không đổi được sang chỉ thành viên, cho đến khi gỡ ảnh.
- Tối đa 10 tệp (ảnh và video cộng lại) mỗi bài.

## Danh sách

- Bảng tin tổ chức: sắp theo mã bài, mới nhất trước. Lọc theo loại (`kind`) và chỉ bài ghim (`pinned_only`).
- Trang tiếp theo dùng `before` là mã bài cuối của trang trước. Trả về `next_before` là `null` ở trang cuối.
- Thứ tự theo thời điểm tạo, không theo thời điểm đăng. Bản nháp đăng sau có thể nằm xa vị trí tương ứng với thời điểm đăng.
- `GET /feed`: bài của mọi tổ chức bạn là thành viên. Đây là tab "Dành cho bạn".
- `GET /feed/public`: bài công khai của mọi tổ chức, giống nhau cho khách và thành viên.

## API

| Method | Đường dẫn | Quyền |
| ---- | ---- | ---- |
| POST | `/organizations/{slug}/posts` | Thành viên (thảo luận) hoặc quản trị viên (thông báo) |
| GET | `/organizations/{slug}/posts` | Ai cũng xem, theo quyền xem |
| GET | `/organizations/{slug}/post-drafts` | Đã đăng nhập, chỉ bản nháp của chính mình |
| GET | `/posts/{id}` | Ai cũng xem, theo quyền xem |
| PATCH | `/posts/{id}` | Tác giả |
| POST | `/posts/{id}/publish` | Tác giả |
| POST | `/posts/{id}/pin`, `/posts/{id}/unpin` | Quản trị viên |
| DELETE | `/posts/{id}` | Tác giả hoặc quản trị viên. Nháp: xóa cứng. Bài đã đăng: vào thùng rác |
| GET | `/organizations/{slug}/post-trash` | Chủ sở hữu, quản trị viên |
| POST | `/posts/{id}/restore` | Chủ sở hữu, quản trị viên |
| DELETE | `/posts/{id}/purge` | Chủ sở hữu |
| GET | `/posts/{id}/comments` | Ai cũng xem, theo quyền xem |
| POST | `/posts/{id}/comments` | Thành viên đang hoạt động |
| PATCH | `/comments/{id}` | Người viết, trong 15 phút |
| DELETE | `/comments/{id}` | Người viết hoặc quản trị viên (xóa mềm) |
| POST | `/comments/{id}/restore` | Chủ sở hữu, quản trị viên |
| GET | `/feed` | Đã đăng nhập |
| GET | `/feed/public` | Ai cũng xem |
| GET | `/feed/popular-tags` | Ai cũng xem, theo quyền xem |

Mỗi bài trả về `viewer` với bốn cờ: `can_edit`, `can_delete`, `can_pin`, `can_comment`. Khách chưa đăng nhập nhận bốn cờ đều `false`.

## Kiểm tra dữ liệu

| Trường | Quy tắc | Mã lỗi |
| ---- | ---- | ---- |
| `kind` | `announcement` hoặc `discussion` | `literal_error` |
| `title` | 1 đến 160 ký tự, một dòng, không ký tự điều khiển, có ít nhất một chữ cái | `string_too_short`, `string_too_long`, `text_invalid`, `text_needs_letter` |
| `body` | 1 đến 5000 ký tự, cho phép xuống dòng | `string_too_short`, `string_too_long` |
| `tags` | Tối đa 3, mỗi tên 1 đến 40 ký tự | `too_long`, `tag_invalid` |
| `media_ids` | Tối đa 10 mã UUIDv7 | `too_long`, `uuid_invalid` |
| `draft` | Chỉ `true` hoặc `false`. `"true"` hay `1` bị từ chối | `bool_type` |
| `comment body` | 1 đến 1000 ký tự, phải là chuỗi | `string_too_short`, `string_too_long`, `string_type` |
| Body | Không nhận trường lạ | `extra_forbidden` |
| Mã trên đường dẫn | UUIDv7 | `uuid_invalid` |

## Mã lỗi nghiệp vụ

| Mã | Ý nghĩa |
| ---- | ---- |
| `post_not_found` | Bài không tồn tại, đã xóa, không xem được, hoặc là bản nháp của người khác |
| `post_forbidden` | Không đủ quyền với bài: không phải thành viên, không phải quản trị, hoặc không phải tác giả |
| `post_not_draft` | Bài không còn là bản nháp |
| `post_not_published` | Bài là bản nháp, không bình luận hay ghim được |
| `post_not_in_trash` | Bài không nằm trong thùng rác, nên không khôi phục hay xóa vĩnh viễn được |
| `comment_edit_expired` | Đã quá 15 phút, không sửa bình luận được nữa |
| `comment_not_deleted` | Bình luận chưa bị xóa |
| `comment_forbidden` | Chỉ thành viên đang hoạt động bình luận được. Chỉ người viết hoặc quản trị viên xóa được |
| `comment_not_found` | Bình luận không tồn tại |
| `media_not_found` | Ảnh không tồn tại hoặc không phải của tác giả |
| `members_post_has_no_media` | Bài chỉ thành viên không được có ảnh |

## Giới hạn

- Tạo bài: 30 lần mỗi giờ cho mỗi người.
- Bình luận: 120 lần mỗi giờ cho mỗi người.

## Chưa có

- Khối nội dung (đoạn, tiêu đề phụ, danh sách, trích dẫn). Hiện bài chỉ có tiêu đề và đoạn văn thuần.
- Ảnh bìa bài viết (`cover_media_id`).
- Ảnh trong bài chỉ thành viên. Cần quyền xem ảnh theo nhóm trước.
- Bản nháp chỉnh sửa cho bài đã đăng. Hiện sửa trực tiếp.
- Tab "Đang theo dõi" và việc theo dõi tổ chức.
- Thông báo khi có bài mới hoặc bình luận.
- Báo cáo nội dung và kiểm duyệt. Sẽ làm cùng quản trị nền tảng ở giai đoạn 6.
