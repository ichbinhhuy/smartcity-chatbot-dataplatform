# Báo cáo điều tra root cause Y03/Y05 — 10/10 Yellow Case (2026-08-20)

> Tiếp nối [yellow_case_fix_2026-08-19.md](yellow_case_fix_2026-08-19.md) (8/10 Yellow pass,
> Y03/Y05 còn FAIL, ghi nhận là residual chưa fix).
> Đợt này theo yêu cầu người dùng: "Điều tra root cause Y03/Y05 luôn đi".
> Dữ liệu chi tiết: [yellow_case_fix_2026-08-20_raw.json](yellow_case_fix_2026-08-20_raw.json).

## Tóm tắt

| | Trước (2026-08-19) | Sau |
|---|:---:|:---:|
| **Yellow (10 case)** | 8/10 pass (Y03, Y05 FAIL) | **10/10 pass sạch 3/3** |
| **Green (15 case)** | 14/15 success | 14/15 success (không đổi thành phần) |
| **Red (5 case)** | 5/5 refusal | 5/5 refusal, không đổi |
| **Test suite** | 159 passed | **163 passed** (+4 test mới), 8 fail pre-existing không đổi |

## Root cause — 2 lỗi độc lập, không phải chỉnh ngưỡng

### 1. Y05 — lỗi tie-break RRF cấp CUBE (`top_cube` sai, không phải `field_ambiguity`)

`_retrieve_cube_first()` chọn `top_cube` bằng RRF (Reciprocal Rank Fusion) trên BM25-overlap +
dense-embedding cosine similarity ở cấp cube. Với câu hỏi *"Tình hình giao thông ở TTTM khung giờ
17h-19h ngày 25/7"*:

- BM25 cube-level: `traffic_flow` và `street_incidents` **TIE TUYỆT ĐỐI** (cùng khớp 3 token
  `giao`/`thông`/`tttm`) — vì `domain_alias_map` của CẢ 2 cube đều chứa "giao thông"
  (`street_incidents`: *"sự cố **giao thông** tai nạn ngập lụt..."*).
- RRF score (tổng nghịch đảo hạng dense+bm25) vì vậy CŨNG tie tuyệt đối (hoán đổi hạng cho nhau:
  `traffic_flow` dense_rank=1/bm25_rank=2, `street_incidents` dense_rank=2/bm25_rank=1 → tổng
  giống hệt).
- `rrf_scores.sort(key=lambda x: x[0], reverse=True)` — Python `sort` ổn định (stable), khi 2 phần
  tử tie tuyệt đối, giữ nguyên thứ tự XUẤT HIỆN trong `self.cube_documents` = thứ tự
  `catalog.cubes` (do Cube Meta API trả về, **hoàn toàn ngẫu nhiên, không phải tín hiệu liên
  quan**). `street_incidents` đứng trước `traffic_flow` trong danh sách này → thắng tie, dù dense
  embedding (semantic, đáng tin hơn BM25 token-overlap thô cho case đồng nghĩa/lân cận domain) đã
  phân biệt RÕ `traffic_flow` cao hơn hẳn (**0.3923 vs 0.3420**).

**Fix:** thêm `dense_rank` làm tie-break phụ trong `_retrieve_cube_first()`:
```python
rrf_scores.sort(
    key=lambda x: (x[0], -dense_rank_map.get(x[1]["cube_name"], 999)),
    reverse=True,
)
```
Khi RRF score bằng nhau tuyệt đối, ưu tiên cube có `dense_rank` thấp hơn (tốt hơn).

**Verify (diagnostic thật):** `top_cube` cho câu hỏi Y05 đổi từ `street_incidents` → `traffic_flow`
đúng như kỳ vọng, không đổi bất kỳ kết quả `top_cube`/`field_ambiguity` nào của 15 Green + 9 Yellow
case còn lại (sweep lại toàn bộ).

### 2. Y03 & Y05 — 1 field thắng áp đảo do trùng khớp NGUYÊN VĂN cụm mơ hồ

Sau khi `top_cube` đã đúng, `field_ambiguity` (case N) vẫn KHÔNG kích hoạt cho cả 2 câu — vì:

- Y03 dùng cụm "**mức độ ảnh hưởng**" — trước đây CHỈ `street_incidents.total_impact_hours` có
  nguyên cụm này trong vietnamese term (`"...mức độ ảnh hưởng gián đoạn"`), 2 field còn lại
  (`total_incidents`, `avg_duration_min`) không có → `total_impact_hours` thắng áp đảo
  (`gap_ratio=0.5`, "đủ tách biệt" → không mơ hồ).
- Y05 dùng cụm "**tình hình giao thông**" — trước đây CHỈ `traffic_flow.congestion_rate` có nguyên
  cụm này → thắng áp đảo tương tự (`gap_ratio=0.5`).

Đây CHÍNH LÀ cụm từ mơ hồ mà case N được thiết kế để bắt — nhưng vì nó chỉ được "lồng" vào 1 field
thay vì lặp lại đều ở TẤT CẢ field ứng viên hợp lệ (khác với 5 entry `city_health_index.avg_*_score`
của Y01 hay 3 entry `traffic_flow.*` mới sửa cho Y05, vốn đã cố ý lặp giống hệt nhau), field đó
biến thành "câu trả lời rõ ràng" thay vì 1 trong nhiều ứng viên ngang hàng.

**Fix:** lặp lại cụm mơ hồ GIỐNG HỆT ở tất cả field ứng viên hợp lệ:
- `street_incidents.total_incidents`/`avg_duration_min`/`total_impact_hours` — cả 3 đều có
  "mức độ ảnh hưởng".
- `traffic_flow.avg_speed`/`sum_vehicle_count`/`congestion_rate` — cả 3 đều có
  "tình hình giao thông".

**Tác dụng phụ phát hiện khi fix Y03:** thêm "mức độ ảnh hưởng" vào 3 measure đẩy doc_freq của
token "mức"/"độ" lên 4/5 pool doc (`street_incidents.severity` cũng có sẵn "mức độ nghiêm trọng") —
chạm đúng ngưỡng loại "token neo domain" (IDF filter, `doc_freq >= len(pool)-1`), khiến "mức"/"độ"
bị loại khỏi `discriminative_tokens`, hạ `top_score` xuống dưới sàn tối thiểu (0.286 < 0.3). Fix
kèm theo: bỏ "mức độ" khỏi `street_incidents.severity` (giữ "nghiêm trọng" làm từ đặc trưng riêng).

**Verify (diagnostic thật, sau cả 2 fix):**

| Case | `top_cube` | `field_ambiguity.candidates` |
|---|---|---|
| Y03 | `street_incidents` | `total_incidents`, `avg_duration_min`, `total_impact_hours` (đúng 100% kỳ vọng plan) |
| Y05 | `traffic_flow` | `avg_speed`, `sum_vehicle_count`, `congestion_rate` (đúng 100% kỳ vọng plan) |

## Kết quả benchmark thật (API, 3 lần/câu)

Cả **10/10 Yellow case** đều 3/3 `clarification` — Y03 và Y05 giờ hỏi đúng lựa chọn kỳ vọng. Green
14/15 (không đổi thành phần so với 2026-08-19), Red 5/5 (không đổi).

**Verify qua Chrome UI thật:** Y03 hỏi đúng "Tổng số sự cố giao thông / Thời gian xử lý trung bình
(phút) / Tổng số giờ ảnh hưởng giao thông"; Y05 hỏi đúng "Tổng số lượng xe lưu thông / Tốc độ lưu
thông trung bình (km/h) / Tỷ lệ ùn tắc giao thông (%)" — khớp 100% kết quả API.

## Phát hiện không liên quan — đã điều tra, xác nhận không phải bug

**G01 tái xuất hiện `refusal`** (`hallucination_forecast_request`, "Hệ thống chưa có dữ liệu cho
ngày 25/7/2026...") — tái hiện ổn định 6/6 lần recheck ban đầu. Đã điều tra thêm theo yêu cầu:

- Xác nhận **KHÔNG liên quan** tới fix Y03/Y05: `field_ambiguity` cho G01 vẫn `None` (không đổi),
  và `is_refusal` xảy ra ngay ở lượt gọi LLM ĐẦU TIÊN, trước cả khi tool call được xét tới — cơ chế
  field_ambiguity/hint hoàn toàn không tham gia vào quyết định này.
- Chạy lại **8/8 lần in-process** (bypass HTTP, code path thuần) → toàn bộ `success`. Chạy tiếp
  **8/8 lần qua HTTP API thật** (cùng phương pháp benchmark) → cũng toàn bộ `success`.
- **Kết luận: đây là dao động LLM thật, không phải lỗi tất định trong code.** Nhất quán với các
  pattern tương tự đã ghi nhận nhiều lần trong dự án (README.md: Y04/R02 dao động tương tự xuyên
  suốt Phase 1) — provider không tuyệt đối tất định dù `temperature=0`. Không có gì để vá thêm
  bằng code theo cùng cách đã dùng cho Y03/Y05 (những case đó là lỗi logic 100% tái hiện được, khác
  bản chất với dao động ngẫu nhiên này).

## File đã sửa

- `app/retrieval/retriever.py` — tie-break `dense_rank` trong `_retrieve_cube_first()`; sửa 3
  entry `traffic_flow.avg_speed`/`sum_vehicle_count`/`congestion_rate`; sửa 3 entry
  `street_incidents.total_incidents`/`avg_duration_min`/`severity`.
- `tests/test_retriever.py` — +3 test (`test_rrf_tie_break_prefers_dense_rank_on_exact_tie`,
  `test_y03_style_incident_impact_phrase_is_ambiguous`,
  `test_y05_style_traffic_situation_phrase_is_ambiguous`).

## Kết luận

10/10 Yellow case pass sạch tuyệt đối (từ baseline 0/10 → 8/10 → 10/10 qua 2 đợt fix). Cả 2 root
cause của Y03/Y05 đều là lỗi tất định trong cơ chế retrieval hiện có (tie-break thiếu robust + 1
field trùng khớp nguyên văn cụm mơ hồ thắng áp đảo) — không phải thiếu cơ chế mới, không cần
threshold mới. Full test suite 163 passed, đúng 8 fail pre-existing không đổi. 1 phát hiện ngoài
phạm vi (G01 refusal tái xuất hiện) đã ghi nhận rõ, chưa xử lý — chờ quyết định người dùng.
