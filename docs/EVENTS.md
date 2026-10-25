# Sự kiện công khai (browse) — amigoact-be

Trang `/events` đọc từ `GET /activities/browse`. Endpoint này công khai, không phụ thuộc người xem, nên kết quả có thể dùng chung giữa mọi tài khoản.

## 1. Endpoint

`GET /activities/browse`

| Tham số | Mặc định | Ghi chú |
|---|---|---|
| `phase` | `upcoming` | `upcoming`, `ongoing`, `past` |
| `q` | — | Tối đa 100 ký tự. Không phân biệt hoa thường và dấu; khớp tiêu đề, địa điểm, thành phố, tên tổ chức, tên thẻ |
| `category_id` | — | UUID danh mục |
| `tag` | — | Slug thẻ, tối đa 60 ký tự |
| `city` | — | Không phân biệt dấu |
| `mode` | — | `online` hoặc `offline` |
| `starts_from`, `starts_to` | — | Khoảng `[from, to)` theo `start_at`. Datetime không múi giờ được hiểu là UTC |
| `registration_open` | `false` | Chỉ lấy sự kiện đang mở đăng ký |
| `sort` | `start` | `start` (sớm nhất trước; `past` thì mới nhất trước) hoặc `published` |
| `limit` | `12` | 1 đến 30 |
| `offset` | `0` | 0 đến 500 |

Phản hồi:

```
{ items: BrowseItem[], total, truncated,
  facets: { cities: [{city, count}], categories: [{category_id, name, count}], tags: [{slug, name, count}] } }
```

Mỗi facet đếm theo mọi bộ lọc **trừ bộ lọc của chính nó** (faceted search). Chọn một danh mục thì danh sách danh mục vẫn hiện các danh mục khác, còn danh sách thẻ chỉ phản ánh danh mục đã chọn. Cùng quy tắc với thành phố. `facets.categories` chỉ có các danh mục có sự kiện khớp, lấy tên từ catalog; `facets.tags` tối đa 50 thẻ dùng nhiều nhất trong kết quả. `truncated = true` nghĩa là một nguồn dữ liệu đã vượt cửa sổ quét (mục 3), nên danh sách có thể chưa đầy đủ.

Giá trị sai trả `422 VALIDATION_ERROR`.

Route được đăng ký trong `main.py` trước `activities_router`. Nếu đảo thứ tự, `/activities/browse` sẽ bị `/activities/{activity_id}` bắt và trả 422. Có regression test khóa thứ tự này.

## 2. Phân pha

Hàm thuần `classify_phase` trong `activities/browse_filters.py`:

- `completed` → `past`.
- `ongoing` → `ongoing`.
- `published`:
  - `start_at > now` → `upcoming`.
  - Ngược lại, nếu `end_at` (hoặc `start_at + 3 giờ` khi thiếu `end_at`) còn sau `now` → `ongoing`.
  - Còn lại → `past`.
- `draft`, `cancelled`, đã xóa mềm: không bao giờ xuất hiện.

Lý do có quy tắc thời gian: ban tổ chức thường không chuyển `published` sang `completed`, nên một sự kiện đã qua vẫn phải nằm ở tab "Đã qua".

## 3. Cửa sổ quét

Không dùng `ALLOW FILTERING`. Mỗi nguồn là một partition đọc theo khoảng của cột clustering `start_at`:

| Phase | Nguồn | Giới hạn |
|---|---|---|
| `upcoming` | `activities_by_status[published]`, `start_at > now`, tăng dần | 200 |
| `ongoing` | `activities_by_status[ongoing]` và `[published]`, `start_at <= now`, giảm dần | 200 và 100 |
| `past` | `activities_by_status[completed]` và `[published]`, `start_at <= now`, giảm dần | 200 và 100 |

Thẻ (`tag`) và danh mục (`category_id`) **không** thu hẹp lần đọc: chúng được lọc trong bộ nhớ sau khi hydrate. Lý do: nếu đọc theo thẻ thì facet không thấy các thẻ khác của những sự kiện đó, và danh sách gợi ý thẻ sẽ chỉ còn đúng thẻ đã chọn. Đánh đổi: với bộ lọc thẻ, sự kiện nằm ngoài cửa sổ 200 dòng không tới được, và `truncated` báo điều này.

Sự kiện được hydrate bằng `Activity.objects(id__in=...)`, mỗi lô 50 id, thay vì một truy vấn cho mỗi id.

## 4. Làm giàu (chỉ trang hiện tại)

Chỉ những dòng sống sót qua mọi bộ lọc và rơi vào trang đang xem mới được đọc thêm:

- **Tổ chức:** một lần đọc mỗi tổ chức cho mỗi request. Tổ chức đã xóa, hoặc không ở trạng thái `active`, làm ẩn sự kiện của họ.
- **Ảnh bìa:** ảnh có vai trò `cover` trước, rồi đến ảnh đầu tiên. Ảnh phải tồn tại, chưa xóa, upload `active`, có MIME ảnh. Ảnh của hoạt động thuộc sở hữu hoạt động, không phải tổ chức, nên không dùng `is_gallery_asset`.
- **Số chỗ:** chỉ khi có `max_participants`. Số chỗ đã dùng là số đăng ký `approved` cộng `attended` (`CqlRegistrationStore.count_active`), đúng con số `apply()` so với sức chứa. `seats_left = max(0, max_participants - registered_count)`.

## 5. Đăng ký

`registration_open = true` khi: trạng thái `published` hoặc `ongoing`, không có hạn hoặc hạn còn sau `now`, và phase không phải `past`.

Hết chỗ **không** đóng đăng ký. Khi đầy, `apply()` đưa người đăng ký vào danh sách chờ. Vì vậy `registration_open` chặt hơn `apply()` ở chỗ không cho đăng ký khi sự kiện đã qua, và không tính đến số chỗ.

## 6. Chi phí ước tính

Với `limit=12`, một request tốn tối đa:

- 2 đến 3 truy vấn range theo nguồn,
- khoảng 4 truy vấn `IN` để hydrate,
- 1 lần đọc mỗi tổ chức khác nhau,
- với mỗi mục trong trang: 1 lần đọc danh sách ảnh cộng 1 lần đọc asset cho mỗi ảnh, và 1 lần đếm đăng ký nếu có sức chứa.

Không có cache phía server trong phiên bản này. Cache dạng read-through sẽ đi ngược với realtime.

## 7. Sửa lỗi kèm theo: `GET /activities` cũ

`ActivityService.list_public` trước đây có hai lỗi:

- Nhánh `category_id` không lọc trạng thái công khai, nên bản nháp hiện ra. `activities_by_category` không có cột status.
- Nhánh `tag` bỏ qua tham số `status`.

Cả hai đã sửa: cả hai nhánh giờ lọc `row.status == status` và `deleted_at is None`. Hợp đồng `ActivitySummary` không đổi.

## 7b. Giới hạn đã biết

- Cửa sổ là 200 dòng mỗi nguồn. Sự kiện cũ hơn không phân trang tới được. Khi `truncated = true`, FE hiển thị gợi ý thu hẹp bộ lọc. Nếu quy mô tăng, cần cursor hoặc phi chuẩn hóa cột lọc kèm migration backfill.
- Số chỗ chỉ tính theo `max_participants`, chưa tính sức chứa theo slot.
- Sự kiện thiếu `end_at` được coi là kéo dài 3 giờ.
- Một sự kiện đặt trạng thái `ongoing` từ trước giờ bắt đầu sẽ không hiện ở tab "Đang diễn ra" khi lọc theo tag hoặc category, vì các partition đó đọc theo `start_at <= now`.

## 7c. Của tôi (đã đăng nhập)

`GET /activities/browse/mine` trả các sự kiện mà người gọi đã đăng ký, kể cả đã hủy. Bộ lọc gồm `q`, `category_id`, `tag`, `city`, `mode`, `my_status`, `limit`, `offset`. Không có `phase` và không có khoảng thời gian: mỗi mục có `phase` riêng.

- Thứ tự: sự kiện còn diễn ra (tăng dần), rồi đã qua (giảm dần), rồi đã hủy (cuối).
- Sự kiện đã hủy có `phase = "cancelled"`, tức là ban tổ chức đã hủy activity. Người đăng ký tự rút chỗ thì activity vẫn `upcoming`, còn `my_registration.status` là `cancelled`.
- `facets.my_status` đếm trước khi áp `my_status`, nên mọi chip vẫn bấm được.
- Mỗi mục có `my_registration` (`registration_id`, `status`, `registered_at`). Trường này chỉ có ở endpoint này. `GET /activities/browse` công khai không bao giờ chứa dữ liệu theo người xem, nên có thể cache dùng chung.

`GET /registrations/mine/brief` trả một dòng cho mỗi activity: trạng thái tốt nhất. Thứ tự ưu tiên: `attended` > `approved` > `pending` > `waitlisted` > `rejected` > `cancelled`; hòa thì lấy đăng ký mới nhất. Dữ liệu đọc từ partition `registrations_by_student` (tối đa 500 dòng), là nguồn mà `_sync_feeds` giữ trạng thái luôn đúng.

## 7d. Kênh `events:feed`

Kênh công khai, mở cho socket ẩn danh, chỉ mang `{action, activity_id, org_id}`. Chi tiết payload và các sự kiện nào phát ra xem `docs/REALTIME.md`.

- Lifecycle: `activity_changed` phát `updated` khi activity ở trạng thái công khai, phát `removed` khi bị hủy hoặc xóa. Bản nháp và thay đổi slot không phát.
- Đăng ký: `review` và `cancel` phát `seats`. `apply` không phát vì đăng ký mới luôn ở `pending` hoặc `waitlisted`, không làm đổi số chỗ đã giữ (approved cộng attended).
- Gợi ý là best-effort. FE gộp các gợi ý trong 800 ms rồi refetch, không bao giờ tin payload.

## 8. Kiểm thử

- `tests/unit/test_activity_browse.py`: quy tắc phân pha, đăng ký, tìm kiếm không dấu, pipeline service với fake.
- `tests/regression/test_activity_browse_regression.py`: thứ tự route, bộ key hợp đồng, hai lỗi `list_public`.
- `tests/integration/test_activity_browse_db.py`: chạy trên ScyllaDB thật, kiểm tra các tab, bộ lọc, facet, số chỗ và lỗi validation.
