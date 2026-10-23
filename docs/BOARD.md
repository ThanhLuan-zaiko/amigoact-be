# Bảng tin bài viết — `posts/`

## 1. Tổng quan

Bảng tin tổ chức là không gian viết bài dạng báo/blog: nội dung là danh sách
`blocks` có kiểu (đoạn văn, tiêu đề phụ, trích dẫn, danh sách, ảnh, video,
đường kẻ), kèm `title`, `cover_media_id`, `kind` (`discussion` mặc định,
`announcement` cần `post:announce`) và `visibility` (`public` | `members` —
phạm vi độc giả, tách hẳn `kind`; `public` cũng cần `post:announce`).

Vòng đời bài viết giống CRUD tổ chức: tạo/sửa/đăng, gỡ xuống, xóa mềm
vào thùng rác, khôi phục, xóa cứng. Ba trục trạng thái độc lập cộng một
liên kết nháp song song:

- `visibility`: `public` (khách đọc được — trang tổ chức, timeline,
  public read) ↔ `members` (chỉ thành viên trên board). `NULL` trên row cũ
  derive theo `kind` (`announcement` → `public`). Đổi audience trên bài đã
  đăng được phép và đồng bộ luôn projection + timeline; trên revision thì
  bị khóa theo bài gốc (revision kế thừa audience của bài gốc).
- `status`: `draft` (nháp riêng tư của tác giả) ↔ `active` (đã đăng; API trả
  `published`).
- `deleted_at`: khác `None` nghĩa là đang ở thùng rác — trùng được với cả hai
  trạng thái trên và khôi phục sẽ trả về đúng trạng thái cũ.
- `revision_of`: trên một `draft`, trỏ về `post_id` của bài đang live. Đây là
  "nháp chờ đăng": tác giả sửa riêng, bài gốc vẫn hiển thị; `publish` trên
  revision gộp nội dung ngược vào bài gốc (giữ `post_id`, comment, ghim) rồi
  xóa row revision thay vì tạo bài mới. `kind` của revision bị khóa theo bài
  gốc. `unpublish` (gỡ xuống) hấp thụ revision mới nhất vào bài rồi mới chuyển
  draft; `soft_delete`/`hard_delete` trên bài gốc cascade sang mọi revision;
  xóa cứng revision lẻ giữ lại asset mà bài gốc đang dùng chung.

Bảng canonical `org_posts` cộng ba projection: `org_posts_feed` (đã đăng,
mới nhất trước), `org_posts_pinned` (rail ghim), `org_post_drafts`
(nháp của từng tác giả), `org_posts_trash` (toàn org). Media đính kèm ở
`org_post_media`; comment ở `org_post_comments` + `org_post_comment_counts`.

## 2. Khối nội dung (`posts/blocks.py`)

| `type` | Trường bắt buộc | Ghi chú |
|---|---|---|
| `paragraph` | `text` | Đoạn văn thường |
| `heading` | `text`, `level` ∈ {2,3} | Tiêu đề phụ trong bài |
| `quote` | `text`, `cite` | Trích dẫn + nguồn (có thể rỗng) |
| `list` | `ordered`, `items[]` | Danh sách gạch đầu dòng/đánh số |
| `image` | `asset_id`, `caption` | asset phải là media của org |
| `video` | `asset_id`, `caption` | asset phải là media của org |
| `divider` | — | Đường kẻ ngang |

Khối media chỉ giữ `asset_id`; URL file phân giải lúc đọc qua `media[]` của
response (`owner_type` `post`, không vào gallery; editor upload qua `POST /orgs/{org_id}/posts/media`). Tương thích ngược: bài cũ
`body` + `media_ids` vẫn hợp lệ — `blocks` rỗng thì client render `body` và
dải ảnh như trước. Giới hạn: tối đa `MAX_BLOCKS` khối, media block ≤ 4.

## 3. API

Route tĩnh `/posts/drafts`, `/posts/trash` khai trước `/{post_id}` để không
bị shadow. Phân trang số trang `limit` + `page` (mặc định 1), response kèm
`total`; trang đầu của feed kèm `pinned[]` và `viewer_permissions`. Comment
vẫn phân trang cursor `next_cursor`.

| Thao tác | Endpoint | Quyền / trạng thái |
|---|---|---|
| Feed đã đăng | `GET /orgs/{id}/posts?kind=&tag=&page=` | member; `tag` đọc `post_tags_by_org` |
| Nháp của tôi | `GET /orgs/{id}/posts/drafts` | member (chỉ bài mình) |
| Thùng rác | `GET /orgs/{id}/posts/trash` | member thấy bài mình; manager thấy hết |
| Chi tiết | `GET /orgs/{id}/posts/{post}` | member; nháp chỉ tác giả đọc |
| Tạo | `POST /orgs/{id}/posts` | member; `status=draft` cho nháp; `visibility=public` cần `post:announce` |
| Sửa | `PATCH /orgs/{id}/posts/{post}` | chỉ tác giả; `kind` đổi được khi còn nháp độc lập; `visibility` flip được trên bài đã đăng (lên public cần `post:announce`, xuống members thì tự do) |
| Nháp chờ đăng | `POST .../posts/{post}/revisions` | tác giả của bài đang live; idempotent — trả revision đang mở nếu có |
| Đăng nháp | `POST .../publish` | tác giả (announcement cần `post:announce`); revision gộp vào bài gốc |
| Gỡ xuống | `POST .../unpublish` | tác giả; hấp thụ revision đang mở trước khi chuyển draft |
| Ghim/bỏ ghim | `POST .../pin` `POST .../unpin` | manager |
| Xóa mềm | `DELETE .../posts/{post}` | tác giả hoặc manager → `204` |
| Khôi phục | `POST .../restore` | tác giả hoặc manager |
| Xóa cứng | `DELETE .../posts/{post}?hard=true` | tác giả hoặc manager → `204`, xóa luôn comment + media link |
| Comment | `GET/POST/DELETE .../comments` | member; xóa bởi tác giả comment hoặc manager |

Bài viết dùng chung danh mục `tags_by_org` với hoạt động. `tags` trên create/update là tối đa 3 tên (tên dài hơn 40 ký tự hoặc danh sách dài hơn 3 phần tử trả `422`). Tên mới được claim lúc lưu dưới quyền bài viết, không cần `tag:manage`. Ô thẻ trên bài lấy từ danh mục cá nhân `GET /me/tags` (thẻ không thuộc tổ chức). Tạo thẻ ở `/manage/tags` chỉ lưu cái tên; gắn thẻ xảy ra khi lưu bài, tối đa 3. Gõ tên mới trên ô thẻ cũng được nhận vào danh mục đó. Rail phải của `/manage/tags` liệt kê bài đang dùng thẻ đang chọn. `GET /me/tags` đã kèm `posts` (mỗi bài có `cover_url` là ảnh bìa hoặc ảnh đầu tiên) để đổi thẻ không phải chờ thêm một truy vấn; `GET /me/tags/{slug}/posts` vẫn trả cùng danh sách đó. Bỏ `tags` khi `PATCH` giữ nguyên thẻ cũ. Slug đang ở thùng rác trả `TAG_DELETED` (`410`) và không ghi bài. `post_count` trên catalog chỉ đếm bài đã đăng, không nháp, không revision, không nằm trong thùng rác. Đổi tên, gộp, xóa mềm, khôi phục và xóa cứng cập nhật cả hoạt động lẫn bài viết. Migration cộng: `uv run python -m migrate.post_tags` và `uv run python -m migrate.user_tags` (chạy `--dry-run` trước). `user_tags` chép thẻ đang sống của từng tổ chức sang chủ sở hữu và ghi bài còn dùng thẻ đó; dòng `tags_by_org` giữ nguyên.

## 3.1. Cổng public

Chỉ bài `visibility='public'` đã đăng (không nháp, không revision, không
thùng rác) là public — `kind` không còn quyết định phạm vi độc giả nữa:
`announcement` members-only và `discussion` public đều hợp lệ; bài members
và mọi nội dung khác ở lại board nội bộ.

- Teaser (`title`, `excerpt`, `cover_url`, `author_name`, `published_at`,
  `comment_count`) nhúng trong `GET /orgs/{slug}` qua field `announcements`
  + `announcement_count` — `PublicOrgService` gọi port `PostDirectory`
  (`orgs/interfaces.py`) do `posts/public_service.py` cài đặt.
- Đọc bài đầy đủ: `GET /orgs/{slug}/announcements/{post_id}` → `PostResponse`
  (shape y hệt API nội bộ). Segment `announcements` cố ý để không đụng route
  member `/orgs/{id}/posts/{post_id}` cùng shape. `404` khi org chết/xóa,
  bài không public, hoặc bài thuộc org khác.
- Media đầy đủ của một bài: `GET /orgs/{slug}/announcements/{post_id}/media`
  → `PublicOrgMediaPage` (`items[{url,kind,mime}]`, cover dẫn đầu) — phục vụ
  lightbox trên feed khi teaser chỉ mang 6 tile preview. Cùng ranh giới
  `404` với endpoint đọc bài.
- Danh sách đầy đủ: `GET /orgs/{slug}/announcements?limit&page` →
  `PublicAnnouncementPage` (`items` teaser + `total` chính xác; `limit` 1–30
  mặc định 9, `page` ≥ 1 mặc định 1). Trang vượt tổng trả `items` rỗng.
- Timeline toàn cục: `GET /announcements?limit&cursor` →
  `PublicTimelinePage` (`items` teaser kèm `author_avatar_url` (avatar người
  đăng, resolve từ `avatar_media_id` qua media), `org{id,name,slug,logo_url}`,
  preview `media[]`/`media_count` — tối đa 6 attachment `{url,kind,mime}`
  cover-dẫn-đầu để card feed render mosaic như card tổ chức,
  `tags[{name,slug}]` hydrate từ `org_posts.tag_names` (không lưu trên
  projection) +
  `next_cursor`; `limit` 1–30 mặc định 12; `cursor` là `post_id` cuối trang
  trước, cursor rác bị bỏ qua). Đọc từ projection `announcements_feed`
  (partition `bucket='all'`, cluster `post_id` DESC) — một read bounded phục
  vụ mọi guest; row có post/org đã chết bị skip lười và cursor vẫn tiến qua
  chúng nên không kẹt pager. Mọi bài public mới đăng/ghép trang/đổi audience
  đều ghi row này trong `_place`/`set_visibility` của `CqlPostStore`;
  keyspace đã deploy chạy
  `uv run python -m migrate.announcements_feed` (`--dry-run` để xem
  trước) — script tạo bảng nếu thiếu rồi backfill từ `org_posts_feed` nơi
  `kind='announcement'`, upsert nên chạy lại bao nhiêu lần cũng an toàn,
  không đụng dữ liệu khác. Kèm `uv run python -m migrate.post_visibility`
  để ALTER cột `visibility` cho `org_posts` + `org_posts_feed` và backfill
  audience cũ theo `kind` (row NULL vẫn đọc đúng nhờ fallback, nên chạy
  script nào trước cũng an toàn). Migration mới thêm file
  `migrate/<chủ_đề>.py`.

Lỗi riêng: `INVALID_POST_STATE` (đăng bài đã đăng, khôi phục bài không ở thùng
rác…), `POST_CONTENT_REQUIRED`, `POST_TITLE_REQUIRED` (announcement đăng cần
tiêu đề). Validate nội dung: đã đăng bắt buộc có nội dung; nháp chỉ cần
không rỗng hoàn toàn (title/cover/khối bất kỳ).

## 4. Realtime

Mọi thay đổi bảng tin phát lên kênh `posts:{org_id}` với `action` ∈
`post.created | post.updated | post.deleted | post.pinned | post.unpinned |
post.unpublished | post.restored | post.purged` kèm `post_id`, `actor_id`
(`detail` = kind khi tạo/đăng). Client invalidate query, không mutate cache.

Song song đó, mọi thao tác đổi độ hiển thị guest của một **bài public đã
đăng** (created/updated/unpublished/trashed/restored/purged, cả flip
audience lẫn comment ±) phát
thêm hint `{action, post_id, org_id}` lên kênh public `announcements:feed`
(guest subscribe được) qua port `AnnouncementFeedEvents` — action gộp về
`created | updated | removed` đủ cho việc refetch timeline; flip
public→members phát `removed`, members→public phát `created`.
