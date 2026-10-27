# Sự kiện công khai (browse) — amigoact-be

Trang `/events` đọc từ `GET /activities/browse`. Endpoint này công khai, không phụ thuộc người xem, nên kết quả có thể dùng chung giữa mọi tài khoản. Trang chi tiết lấy thêm `GET /activities/{id}/card`.

## 1. Endpoint

`GET /activities/browse`

| Tham số | Mặc định | Ghi chú |
|---|---|---|
| `phase` | `upcoming` | `upcoming`, `ongoing`, `past` |
| `q` | — | Tối đa 100 ký tự. Không phân biệt hoa thường và dấu; khớp tiêu đề, địa điểm, thành phố, tên tổ chức, tên thẻ |
| `category_id` | — | UUID danh mục |
| `tag` | — | Slug thẻ, tối đa 60 ký tự |
| `city` | — | Tối đa 80 ký tự. Không phân biệt dấu |
| `mode` | — | `online` hoặc `offline` |
| `starts_from`, `starts_to` | — | Khoảng `[from, to)` theo `start_at`. Datetime không múi giờ được hiểu là UTC. Khoảng này được đẩy xuống truy vấn (mục 3) |
| `registration_open` | `false` | Chỉ lấy sự kiện đang mở đăng ký |
| `org` | — | Slug tổ chức, tối đa 80 ký tự. Chỉ đọc feed của tổ chức đó. Slug không tồn tại hoặc tổ chức đã ẩn thì trả danh sách rỗng |
| `cursor` | — | Token của cửa sổ trước, tối đa 512 ký tự (mục 3b). Không hợp lệ hoặc thuộc truy vấn khác thì trả `422` |
| `sort` | `start` | `start` (sớm nhất trước; `past` thì mới nhất trước) hoặc `published` |
| `limit` | `12` | 1 đến 30 |
| `offset` | `0` | 0 đến 500 |

Phản hồi:

```
{ items: BrowseItem[], total, truncated, next_cursor,
  facets: { cities: [{city, count}], categories: [{category_id, name, count}], tags: [{slug, name, count}] } }
```

- `BrowseItem` có `quick_apply` (mục 5). Các khóa khác không đổi và được khóa bởi `test_browse_contract_keys_are_frozen`.
- `next_cursor` chỉ có khi `truncated = true`. Nếu không thì là `null`.
- `GET /activities/browse/mine` không có `next_cursor`. Contract của nó giữ nguyên.

Mỗi facet đếm theo mọi bộ lọc **trừ bộ lọc của chính nó** (faceted search). Chọn một danh mục thì danh sách danh mục vẫn hiện các danh mục khác, còn danh sách thẻ chỉ phản ánh danh mục đã chọn. Cùng quy tắc với thành phố. `facets.categories` chỉ có các danh mục có sự kiện khớp, lấy tên từ catalog; `facets.tags` tối đa 50 thẻ dùng nhiều nhất trong kết quả. Facet, `total` và `sort=published` chỉ tính trong cửa sổ hiện tại (mục 3b).

Giá trị sai trả `422 VALIDATION_ERROR`.

Route được đăng ký trong `main.py` trước `activities_router`. Nếu đảo thứ tự, `/activities/browse` sẽ bị `/activities/{activity_id}` bắt và trả 422. Có regression test khóa thứ tự này. Route `/activities/{id}/card` có ba đoạn nên không xung đột với route nào.

## 2. Phân pha

Hàm thuần `classify_phase` trong `core/event_phase.py` (đã re-export từ `activities/browse_filters.py`):

- `completed` → `past`.
- `ongoing` → `ongoing`.
- `published`:
  - `start_at > now` → `upcoming`.
  - Ngược lại, nếu `end_at` (hoặc `start_at + 3 giờ` khi thiếu `end_at`) còn sau `now` → `ongoing`.
  - Còn lại → `past`.
- `draft`, `cancelled`, đã xóa mềm: không bao giờ xuất hiện.

Lý do có quy tắc thời gian: ban tổ chức thường không chuyển `published` sang `completed`, nên một sự kiện đã qua vẫn phải nằm ở tab "Đã qua". Module nằm trong `core/` để `registrations` dùng cùng quy tắc mà không import feature `activities`.

## 3. Cửa sổ quét

Không dùng `ALLOW FILTERING`. Mỗi nguồn là một lần đọc partition theo khoảng của cột clustering `start_at`. Hàm thuần `public_scans` (trong `activities/browse_window.py`) quyết định khoảng cho từng nguồn:

| Phase | Nguồn | Giới hạn |
|---|---|---|
| `upcoming` | `activities_by_status[published]`, `start_at > now`, tăng dần | 200 |
| `ongoing` | `activities_by_status[ongoing]` và `[published]`, `start_at <= now`, giảm dần | 200 và 100 |
| `past` | `activities_by_status[completed]` và `[published]`, `start_at <= now`, giảm dần | 200 và 100 |
| `org` | `activities_by_org[org_id]`, giảm dần, không gắn phase | 300 |

`starts_from` và `starts_to` được ghép vào khoảng `start_at` của mọi nguồn. Vì vậy một khoảng ngày có thể tới sự kiện nằm xa hơn cửa sổ 200 dòng. Cận dưới lấy giá trị muộn hơn, và khi bằng nhau thì cận exclusive thắng.

Thẻ (`tag`) và danh mục (`category_id`) **không** thu hẹp lần đọc: chúng được lọc trong bộ nhớ sau khi hydrate. Lý do: nếu đọc theo thẻ thì facet không thấy các thẻ khác của những sự kiện đó, và danh sách gợi ý thẻ sẽ chỉ còn đúng thẻ đã chọn. Đánh đổi: với bộ lọc thẻ hoặc chữ, sự kiện nằm ngoài cửa sổ không tới được cho đến khi người dùng đi tiếp bằng `cursor` hoặc thu hẹp khoảng ngày.

Sự kiện được hydrate bằng `Activity.objects(id__in=...)`, mỗi lô 50 id, thay vì một truy vấn cho mỗi id. Chỉ các id có trạng thái công khai (`published`, `ongoing`, `completed`) được hydrate.

## 3b. Cursor và cửa sổ kế tiếp

Mỗi cửa sổ đọc `limit + 1` dòng mỗi nguồn để biết có tràn không. Nếu tràn, ranh giới `B` là `start_at` của dòng đầu tiên bị loại. Hàm thuần `cut_window` quyết định như sau:

- Cửa sổ giữ các dòng nằm **trước** `B` theo thứ tự quét.
- Cửa sổ kế tiếp bắt đầu **tại** `B` (gồm cả `B`). Nhờ vậy không dòng nào bị mất hay lặp lại.
- Ngoại lệ: nếu mọi dòng lấy về đều có cùng `B`, cửa sổ giữ chúng và cửa sổ kế tiếp bắt đầu **sau** `B`. Nhóm cùng giờ bắt đầu chỉ đầy đủ đến giới hạn quét. Với hơn 200 sự kiện cùng một thời điểm bắt đầu, phần vượt quá sẽ bị bỏ qua. Đây là giới hạn đã biết.

Cursor là chuỗi base64url không ký, chứa `phase`, `org_id` (hoặc rỗng), `boundary` (UTC) và cờ inclusive. Cursor chỉ thu hẹp cận của truy vấn công khai, không mở thêm dữ liệu. Cursor được gắn với `phase` và phạm vi tổ chức; đổi các thứ đó thì trả `422`.

`cursor` không đi kèm với `page` được hiểu như sau: `offset` vẫn áp trong cửa sổ đang xem. Muốn sang cửa sổ sau thì gửi `next_cursor` của phản hồi trước.

## 4. Làm giàu (chỉ trang hiện tại)

Chỉ những dòng sống sót qua mọi bộ lọc và rơi vào trang đang xem mới được đọc thêm:

- **Tổ chức:** một lần đọc mỗi tổ chức cho mỗi request. Tổ chức đã xóa, hoặc không ở trạng thái `active`, làm ẩn sự kiện của họ.
- **Ảnh bìa:** ảnh có vai trò `cover` trước, rồi đến ảnh đầu tiên. Ảnh phải tồn tại, chưa xóa, upload `active`, có MIME ảnh. Ảnh của hoạt động thuộc sở hữu hoạt động, không phải tổ chức, nên không dùng `is_gallery_asset`.
- **Số chỗ:** chỉ khi có `max_participants`. Số chỗ đã dùng là số đăng ký `approved` cộng `attended` (`CqlRegistrationStore.count_active`), đúng con số `apply()` so với sức chứa. `seats_left = max(0, max_participants - registered_count)`.
- **Quick apply:** chỉ với thẻ đang mở đăng ký (mục 5).

## 5. Đăng ký

`registration_open = true` khi: trạng thái `published` hoặc `ongoing`, không có hạn hoặc hạn còn sau `now`, và phase không phải `past`.

Hết chỗ **không** đóng đăng ký. Khi đầy, `apply()` đưa người đăng ký vào danh sách chờ.

`apply()` từ chối khi sự kiện đã kết thúc. Quy tắc phase dùng `classify_phase`: một sự kiện `published` đã qua giờ kết thúc (hoặc `start_at + 3 giờ` khi thiếu `end_at`) bị từ chối với `REGISTRATION_CLOSED`. `ongoing` vẫn nhận đăng ký đến hạn chót.

**`quick_apply`** (viewer-agnostic, nên feed công khai vẫn dùng chung được): `true` khi thẻ đang mở đăng ký và không cần thêm gì ngoài một cú bấm. Nghĩa là không có câu hỏi biểu mẫu (`RegistrationForm`) và không có ca (`ActivitySlot`). Chỉ các thẻ đang mở đăng ký trên trang hiện tại mới được hỏi, nên thẻ đóng không tốn truy vấn thêm. Một phần lý do cờ này tồn tại: `apply()` không bắt buộc chọn ca ngay cả khi sự kiện có ca, nên trang danh sách không được tự ý đăng ký thay người dùng.

## 6. Chi phí ước tính

Với `limit=12`, một request tốn tối đa:

- 2 đến 3 truy vấn range theo nguồn (1 cho org),
- khoảng 4 truy vấn `IN` để hydrate,
- 1 lần đọc mỗi tổ chức khác nhau,
- với mỗi mục trong trang: 1 lần đọc danh sách ảnh cộng 1 lần đọc asset cho mỗi ảnh, và 1 lần đếm đăng ký nếu có sức chứa,
- với mỗi thẻ đang mở đăng ký trên trang: 1 lần đọc biểu mẫu cộng 1 lần đọc ca, mỗi lịch trình có thêm 1 lần đọc nữa.

Không có cache phía server trong phiên bản này. Cache dạng read-through sẽ đi ngược với realtime. Cache-Control không được dùng: FE gửi `cache: "no-store"`, và một `max-age` dùng chung sẽ làm vô hiệu gợi ý realtime.

## 7. Sửa lỗi kèm theo: `GET /activities` cũ

`ActivityService.list_public` trước đây có hai lỗi:

- Nhánh `category_id` không lọc trạng thái công khai, nên bản nháp hiện ra. `activities_by_category` không có cột status.
- Nhánh `tag` bỏ qua tham số `status`.

Cả hai đã sửa: cả hai nhánh giờ lọc `row.status == status` và `deleted_at is None`. Hợp đồng `ActivitySummary` không đổi.

## 7b. Giới hạn đã biết

- Mỗi cửa sổ có tối đa 200 dòng mỗi nguồn (100 cho nguồn published gần đây, 300 cho một tổ chức). Sự kiện nằm ngoài cửa sổ chỉ tới được bằng `cursor` hoặc khoảng ngày.
- Text, tag, city và category chỉ lọc trong cửa sổ hiện tại. `total`, facet và `sort=published` cũng chỉ đúng trong cửa sổ.
- Nhóm sự kiện cùng giờ bắt đầu vượt giới hạn quét sẽ bị cắt (mục 3b).
- Số chỗ chỉ tính theo `max_participants`, chưa tính sức chứa theo slot.
- Sự kiện thiếu `end_at` được coi là kéo dài 3 giờ.
- Một sự kiện đặt trạng thái `ongoing` từ trước giờ bắt đầu không hiện ở tab "Đang diễn ra" khi lọc theo tag hoặc category, vì các nguồn `published` đọc theo `start_at <= now`.
- `quick_apply` có thể cũ tối đa 30 giây (staleTime FE). Đổi biểu mẫu hoặc ca không phát realtime. `apply()` vẫn là nguồn sự thật và trả lỗi nếu cần thêm thông tin.

## 7c. Của tôi (đã đăng nhập)

`GET /activities/browse/mine` trả các sự kiện mà người gọi đã đăng ký, kể cả đã hủy. Bộ lọc gồm `q`, `category_id`, `tag`, `city`, `mode`, `my_status`, `starts_from`, `starts_to`, `registration_open`, `limit`, `offset`. Không có `phase` và không có `org` hay `cursor`: mỗi mục có `phase` riêng, và danh sách không bị cắt cửa sổ.

- Thứ tự: sự kiện còn diễn ra (tăng dần), rồi đã qua (giảm dần), rồi đã hủy (cuối).
- Sự kiện đã hủy có `phase = "cancelled"`, tức là ban tổ chức đã hủy activity. Người đăng ký tự rút chỗ thì activity vẫn `upcoming`, còn `my_registration.status` là `cancelled`.
- `facets.my_status` đếm trước khi áp `my_status`, nên mọi chip vẫn bấm được.
- Mỗi mục có `my_registration` (`registration_id`, `status`, `registered_at`). Trường này chỉ có ở endpoint này. `GET /activities/browse` công khai không bao giờ chứa dữ liệu theo người xem.

`GET /registrations/mine/brief` trả một dòng cho mỗi activity: trạng thái tốt nhất. Thứ tự ưu tiên: `attended` > `approved` > `pending` > `waitlisted` > `rejected` > `cancelled`; hòa thì lấy đăng ký mới nhất. Dữ liệu đọc từ partition `registrations_by_student` (tối đa 500 dòng), là nguồn mà `_sync_feeds` giữ trạng thái luôn đúng.

## 7d. Kênh `events:feed`

Kênh công khai, mở cho socket ẩn danh, chỉ mang `{action, activity_id, org_id}`. Chi tiết payload và các sự kiện nào phát ra xem `docs/REALTIME.md`.

- Lifecycle: `activity_changed` phát `updated` khi activity ở trạng thái công khai, phát `removed` khi bị hủy hoặc xóa. Bản nháp và thay đổi slot không phát.
- Đăng ký: `review` và `cancel` phát `seats`. `apply` không phát vì đăng ký mới luôn ở `pending` hoặc `waitlisted`, không làm đổi số chỗ đã giữ (approved cộng attended).
- Gợi ý là best-effort. FE gộp các gợi ý trong 800 ms rồi refetch, không bao giờ tin payload.

## 7e. Thẻ chi tiết `GET /activities/{activity_id}/card`

Trả đúng `BrowseItem` của feed cho một hoạt động, để trang chi tiết có tổ chức, ảnh bìa, số chỗ và `registration_open`. Các endpoint chi tiết không có những trường này.

- Công khai, không cần đăng nhập.
- `404 NOT_FOUND` khi feed không phục vụ hoạt động đó: không tồn tại, bản nháp, đã hủy, đã xóa mềm, hoặc tổ chức bị ẩn.
- Dùng chung `_card` và `_quick_apply` với feed, nên một hoạt động luôn có cùng dữ liệu ở cả hai nơi.

## 8. Kiểm thử

- `tests/unit/test_browse_window.py`: phép cắt cửa sổ, ranh giới, nhóm cùng giờ bắt đầu, vòng lặp đi qua mọi cửa sổ (không mất, không lặp), cursor và token sai.
- `tests/unit/test_browse_scope.py`: org scope, cursor theo phạm vi, `card_for` (404 cho bản nháp, đã hủy, đã xóa, tổ chức ẩn), `quick_apply`, và khoảng ngày trong chế độ "Của tôi".
- `tests/unit/test_activity_browse.py`, `tests/unit/test_activity_browse_views.py`: quy tắc phân pha, đăng ký, tìm kiếm không dấu, pipeline service với fake.
- `tests/unit/test_registration_service.py`: `apply()` từ chối sự kiện đã kết thúc và chấp nhận sự kiện đang diễn ra.
- `tests/unit/test_activity_media.py`: gallery công khai cho `ongoing` và `completed`, bị ẩn với `draft` và `cancelled`.
- `tests/regression/test_activity_browse_regression.py`: thứ tự route, route `/card`, bộ key hợp đồng (có `next_cursor` và `quick_apply`), hai lỗi `list_public`.
- `tests/integration/test_activity_browse_db.py` và `tests/integration/test_activity_scope_db.py`: chạy trên ScyllaDB thật. Gồm tab, bộ lọc, facet, số chỗ, validation, card, org scope, cursor đi qua nhiều cửa sổ và `quick_apply` đổi khi có biểu mẫu.
