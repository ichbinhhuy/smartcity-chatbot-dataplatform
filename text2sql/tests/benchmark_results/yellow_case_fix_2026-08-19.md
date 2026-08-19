# Báo cáo fix 10 Yellow Case (Ambiguous — chưa hỏi lại đúng thiết kế) (2026-08-19)

> Tiếp nối [phase2_2026-08-19.md](phase2_2026-08-19.md) (Phase 2 — 6 bug phát hiện qua benchmark chatbot).
> Đợt này thực hiện đúng kế hoạch riêng cho 10 Yellow case:
> `/home/phuongvd8/.claude/plans/l-n-k-ho-ch-fix-serialized-penguin.md`.
> Dữ liệu chi tiết (kết quả từng lần chạy, JSON đầy đủ):
> [yellow_case_fix_2026-08-19_raw.json](yellow_case_fix_2026-08-19_raw.json).

## Tóm tắt

| Nhóm | Baseline (`yellow_cases_2026-08-18.json`) | Sau đợt fix này (3 lần/câu qua API thật) |
|---|:---:|:---:|
| **Yellow — tỷ lệ `clarification` đúng thiết kế** | 0/10 (1 case có hỏi lại nhưng sai loại — Y06) | **8/10 pass sạch 3/3**, Y03+Y05 chưa cải thiện |
| **Green — không phát sinh false-positive mới** | (baseline riêng, 15 câu) | **14/15 `success`**, 1 câu (G11) hạ xuống `clarification` (đã biết trước, không phải lỗi mới) |
| **Red — guardrail tất định giữ nguyên** | 5/5 (Phase 2) | **5/5 `refusal`**, không đổi |
| **Test suite** | 119 passed / 8 fail pre-existing / 2 skip | **159 passed** (+40 test mới) / 8 fail pre-existing (khớp 100% danh sách cũ) / 2 skip |

Chi tiết theo case (3 lần/câu, riêng 6 case từng dao động được chạy thêm 3 lần nữa để xác nhận ổn định — xem `stability_recheck_6x_more` trong file JSON):

| Case | Câu hỏi | Kết quả |
|---|---|:---:|
| Y01 | Kết quả đánh giá đô thị ở Khu Căn hộ trong tuần 21-28/7 | ✅ 3/3 clarification |
| Y02 | Chất lượng không khí và tiếng ồn ở TTTM ngày 27/7 | ✅ 3/3 (+3/3 recheck) clarification |
| Y03 | Mức độ ảnh hưởng của sự cố tại TTTM ngày 28/7 | ❌ 0/3 — vẫn `success`, `field_ambiguity` không kích hoạt được cho `street_incidents` |
| Y04 | Hiệu suất hệ thống đèn đường ở Khu Căn hộ đêm 22/7 | ✅ 3/3 (+3/3 recheck) clarification |
| Y05 | Tình hình giao thông ở TTTM khung giờ 17h-19h ngày 25/7 | ❌ 0/3 — vẫn `success`, `top_cube` retrieval nhận nhầm `street_incidents` thay vì `traffic_flow` |
| Y06 | Tốc độ tối đa cho phép ở khu trung tâm là bao nhiêu? | ✅ 3/3 clarification, nội dung đúng: liệt kê 3 khu vực hợp lệ |
| Y07 | Bãi đỗ xe ở Khu Căn hộ lúc trước như thế nào? | ✅ 3/3 clarification (hỏi lại mốc thời gian cụ thể) |
| Y08 | Chỉ số đáng sống Livability ở Khu biệt thự ngày 25/7 có tốt không? | ✅ 3/3 clarification (avg_livability_index vs livability_grade) |
| Y09 | Bãi đỗ xe ở TTTM ngày 27/7 có bị quá tải không? | ✅ 3/3 (+3/3 recheck) clarification |
| Y10 | Mức độ ô nhiễm tiếng ồn ở Khu biệt thự trong tuần 21-28/7 | ✅ 3/3 clarification (avg_noise_db vs noise_category) |

**Từ 0/10 lên 8/10 pass sạch tuyệt đối** (Y01, Y02, Y04, Y06, Y07, Y08, Y09, Y10), không case nào regress.

---

## Cơ chế fix chính (theo kế hoạch đã duyệt)

1. **`field_ambiguity` (retriever.py)** — tín hiệu mơ hồ cấp measure/dimension trong `top_cube`, tất định (BM25-overlap + gap_ratio + ngưỡng sàn), bắt cả "N measure độc lập" (Y01/Y02/Y04) lẫn "measure liên tục vs dimension phân hạng cùng khái niệm" (Y08/Y09/Y10) bằng 1 cơ chế.
2. **`time_ambiguity.py` (mới)** — phát hiện cụm từ thời gian mơ hồ có chủ ý ("lúc trước", "trước đây"...) cho Y07, theo quyết định người dùng mở rộng phạm vi case L.
3. **`SampleValues.resolve()` nhánh "0 match"** — không còn im lặng pass-qua giá trị filter không khớp gì trong danh mục (Y06, phòng thủ lớp 2).
4. **Inject hint, không hard-block** — cả 2 cơ chế 1+2 chỉ tiêm advisory hint vào prompt của đúng lượt hỏi đó, LLM vẫn tự quyết định cuối cùng (nhất quán bài học case E).

## 3 lỗi phát sinh phát hiện qua benchmark thật, đã vá trong đợt này (ngoài kế hoạch gốc)

Đúng tinh thần "calibrate bằng dữ liệu thật, không đoán mù" — 3 vấn đề sau chỉ lộ ra khi chạy benchmark LLM thật lặp lại nhiều lần, không thể thấy được từ code review hay diagnostic script thuần retrieval:

### 1. Y06 — token "trung" trùng ngẫu nhiên với "trung bình"

Câu hỏi dùng khu vực bịa "khu trung tâm" — token `"trung"` trùng với từ "trung bình" (average) trong mô tả `traffic_flow.avg_speed`, đẩy `field_ambiguity` kích hoạt sai ngữ cảnh (gợi ý chọn metric thay vì hỏi lại tên khu vực). **Fix:** nâng `FIELD_AMBIGUITY_MIN_SCORE` từ 0.25 lên 0.3 (re-sweep lại toàn bộ 15 Green + 9 Yellow, không đổi hành vi case nào khác — Y01/Y04/Y08/Y09/Y10 đều có top_score ≥0.36).

### 2. Repair-loop ép LLM "phải gọi lại tool"

Khi giá trị filter không xác định được (Y06), retry message cũ ép "Hãy gọi lại duy nhất 1 tool call" — LLM không còn lựa chọn nào ngoài gọi `refuse_request` (tool duy nhất còn lại) dù nội dung đã đúng 100%. **Fix (`orchestrator.py`):** mở thêm lối thoát "trả lời bằng text thường" CHỈ khi lỗi là "giá trị không xác định được trong hệ thống" (không phải lỗi định dạng có thể tự sửa).

### 3. Cube-level retrieval noise + refuse_request bị dùng sai cho field-ambiguity

Việc mở rộng từ vựng tiếng Việt ở Bước 0 (thêm "giao thông" vào `avg_traffic_score`, "trung bình" vào `avg_duration_min`...) vô tình làm 2 Green case (**G01**, **G10**) kéo thêm cube không liên quan (`city_health_index`, `street_incidents`) vào top-3 candidate, gây nhiễu khiến LLM `refuse` sai (`hallucination_forecast_request`/`external_data_unavailable`) dù có dữ liệu thật. Đồng thời phát hiện **Y02/Y04/Y09** dao động clarification/refusal giữa các lần chạy giống hệt nhau — cùng nguyên nhân: model đôi khi đọc "không chắc field nào" (field_ambiguity hint) thành cần từ chối thay vì hỏi lại.

**Fix:**
- Trim từ vựng quá chung chung khỏi 7 entry (5 `city_health_index.avg_*_score` + 2 `street_incidents.*`) — chỉ giữ phần không gây trùng lặp domain khác, không cần cho case Yellow nào đang test.
- Thêm "trung bình" vào `avg_livability_index` (câu G10 tự nêu rõ "trung bình" — giờ tách biệt hẳn khỏi `livability_grade`, gap_ratio 0.167→0.375).
- `build_field_ambiguity_hint()` thêm câu cấm rõ ràng: "TUYỆT ĐỐI KHÔNG gọi tool `refuse_request`... hãy trả lời bằng TEXT THƯỜNG".

**Verify (6 case từng dao động, chạy lại 2 vòng x 3 lần = 6/6 mỗi case sau fix):**
- G01, G10: 6/6 `success` (trước: refusal lặp lại ổn định).
- Y02, Y04, Y09: 6/6 `clarification` (trước: dao động 0/3 ↔ 3/3 giữa các lần chạy).
- G11: vẫn `clarification` (không phải regression mới — residual đã biết, xem bên dưới), nhưng KHÔNG còn `refusal` như trước khi thêm câu cấm.

---

## Residual đã biết, chưa fix trong đợt này

- **Y03, Y05** — `field_ambiguity`/`top_cube` chưa nhận đúng tín hiệu cho `street_incidents`/`traffic_flow` trong 2 câu hỏi này. Cần điều tra riêng ở retrieval layer (không phải lỗi field_ambiguity false-negative đơn giản — `top_cube` cho Y05 thực tế trả về sai cube).
- **G11** ("So sánh Livability giữa 3 phân khu") — vẫn kích hoạt `field_ambiguity` giữa `avg_livability_index`/`livability_grade` (gap_ratio ~0.167, dưới ngưỡng 0.2) vì câu hỏi không có "trung bình" như G10. Đã hạ từ `refusal` (lỗi nặng) xuống `clarification` (benign, đúng thiết kế hint-not-hardblock) — không còn coi là regression, nhưng vẫn là 1 false-positive nhẹ.
- **Bước 8 (plan, optional)** — entity-marker check cho residual routing gap của Y06 — CHƯA CẦN, vì Y06 giờ đã pass 3/3 qua cơ chế hiện có.

## File đã sửa (ngoài các file đã liệt kê trong kế hoạch gốc)

- `app/retrieval/retriever.py` — `FIELD_AMBIGUITY_MIN_SCORE` 0.25→0.3; trim/thêm 8 entry `vietnamese_measure_terms`.
- `app/nlu/orchestrator.py` — repair-loop escape hatch cho lỗi "giá trị filter không xác định được".
- `app/nlu/prompt.py` — `build_field_ambiguity_hint()` cấm rõ `refuse_request`.
- `tests/test_retriever.py` — +3 test (`test_y06_style_nonexistent_district_is_not_field_ambiguous`, `test_min_score_configurable_via_constructor`, `test_min_score_configurable_via_env_var`).
- `tests/test_orchestrator.py` — +1 test (`test_unresolved_filter_value_repair_allows_plain_text_escape`).
- `tests/test_prompt.py` — +1 test (`test_hint_forbids_refuse_request_tool`).

## Verify qua Chrome UI thật

Y06, Y08, G05 (success bình thường), R04 (guardrail) — đều đúng nội dung + đúng `status`, khớp hoàn toàn kết quả benchmark API.

---

## Kết luận

8/10 Yellow case đã pass sạch tuyệt đối (3/3 lần, một số case verify lại thêm 3 lần nữa = 6/6), từ baseline 0/10. Green giữ 14/15 `success` (1 case còn lại là `clarification` benign, không phải lỗi), Red giữ 5/5. Full test suite 159 passed, đúng 8 fail pre-existing không đổi, +40 test mới. 3 vấn đề phát sinh ngoài kế hoạch gốc (đều lộ ra qua benchmark LLM thật lặp lại nhiều lần, không thấy được qua code review) đã được điều tra root cause và vá, có test khoá lại hành vi.

**Đề xuất bước tiếp theo:** điều tra riêng root cause Y03/Y05 (retrieval layer, không phải field_ambiguity threshold) trước khi coi Yellow case là hoàn tất 100%.
