# Các trường hợp câu hỏi ambiguous cần xử lý

> **Phạm vi:** Tổng hợp toàn bộ dạng câu hỏi mơ hồ mà pipeline NLU
> (`app/nlu/`, `app/retrieval/retriever.py`, `app/catalog/sample_values.py`)
> có thể gặp, trạng thái xử lý hiện tại của từng dạng, và root cause + hướng
> đề xuất cho các gap còn tồn tại. Đọc kèm
> [01-nlu-architecture.md](01-nlu-architecture.md) và
> [03-rag-to-nlu-deep-dive.md](03-rag-to-nlu-deep-dive.md) để hiểu pipeline
> tổng thể trước khi đọc tài liệu này.
>
> Bối cảnh: clarification flow multi-turn (Redis session) vừa được hoàn
> thiện ở commit `4804117` + `680f8e7`. Bản đầu tiên của tài liệu này chốt
> bức tranh đầy đủ; 4 gap ưu tiên (E, F, G, I) sau đó đã được implement —
> xem chi tiết ở từng mục bên dưới.

---

## 1. Bảng tổng hợp

| # | Dạng câu hỏi mơ hồ | Trạng thái | Cơ chế xử lý / Code ref |
|---|---|---|---|
| A | Quá chung chung, không nêu metric/topic/entity | ✅ | Rule 13 (`prompt.py`) + `temperature=0` |
| B | Model tự thấy không đủ tin cậy để gọi tool | ✅ | `orchestrator.py` nhánh `not parsed.has_tool_call` |
| C | Cross-domain / nhắc nhiều cube cùng lúc | 🟡 | Rule 2 ép cùng-cube, nhưng không ép hỏi lại |
| D | Top-2 cube RAG gần điểm nhau | ✅ | Rule 12 + `build_clarification_suggestions()` |
| E | Ngoài phạm vi domain (out-of-domain) | 🟡 | Implement rồi nhưng TẠM TẮT — false positive thật phát hiện qua UI, chờ calibrate |
| F | RAG recall miss / RRF score thấp | ✅ | `top_k_cubes` 2→3, configurable qua `RAG_TOP_K_CUBES` (FIX-09) |
| G | Giá trị filter mơ hồ (entity resolution) | ✅ | `sample_values.py` phát hiện candidate gần điểm nhau → error (FIX-04) |
| H | Follow-up ngắn dựa vào lịch sử hội thoại | ✅ | Session store Redis/InMemory + fixed message shape |
| I | Vòng lặp clarification không điểm dừng | ✅ | `max_clarification_streak` + `_apply_clarification_cap()` |
| J | Refusal (safety) bị nhầm với clarification | ✅ | `parsed.is_refusal` check trước, tách status riêng |
| K | Input rỗng / whitespace / ký tự đặc biệt | ❓ | Bị chặn "hên xui" qua Rule 13 — OOD guardrail (E) đang tạm tắt |
| L | Mốc thời gian mơ hồ (vd "gần đây") | ✅ | Default `last 30 days`, không cần hỏi lại |

✅ đã xử lý · 🟡 một phần · ❌ chưa xử lý · ❓ hên xui, chưa có cơ chế minh bạch

---

## 2. Chi tiết từng case

### A. Câu hỏi quá chung chung, không nêu metric/topic/entity cụ thể

Ví dụ: *"cho tôi xem số liệu"*, *"xem dữ liệu đi"*, *"cho tôi biết thông tin"*.

✅ **Đã xử lý.** Rule 13 (`app/nlu/prompt.py`) ép model luôn phải hỏi lại nếu
câu hỏi không nhắc tới bất kỳ tên chỉ số/chủ đề/đối tượng cụ thể nào — kể cả
khi RAG chỉ gợi ý 1-2 cube (tránh model suy diễn ý người dùng). `temperature`
của NLU call đã hạ về `0` (`app/llm/openai_compatible.py`, commit
`680f8e7`) để quyết định tool-call-vs-clarification deterministic, tránh
tình trạng cùng 1 câu hỏi lúc trả lời trực tiếp lúc hỏi lại.

### B. Model tự đánh giá không đủ tin cậy để gọi tool

Model trả về text thuần thay vì gọi `query_metrics`.

✅ **Đã xử lý.** `orchestrator.py` nhánh `if not parsed.has_tool_call` trả
`NLUStatus.CLARIFICATION`, kèm `build_clarification_suggestions()` rút 1-3
gợi ý cụ thể từ RAG candidates. Có test:
`test_text_only_response_is_treated_as_clarification`
(`tests/test_orchestrator.py`).

### C. Câu hỏi cross-domain / nhắc nhiều cube cùng lúc

Ví dụ: *"So sánh chất lượng không khí và tình hình giao thông ở khu A"* —
hai domain (`air_quality`, `traffic_flow`) trong cùng 1 câu hỏi.

🟡 **Một phần.** Rule 2 (`prompt.py`) bắt buộc mọi `measures` trong 1 tool
call phải cùng 1 Cube, nên model buộc phải chọn 1 trong 2 domain — nhưng
KHÔNG có rule riêng ép model *hỏi lại* khi phát hiện câu hỏi đa domain; hành
vi phụ thuộc hoàn toàn vào việc model tự áp Rule 12 (làm rõ khi không đủ tin
cậy). Chưa có test case nào phủ tình huống này. Rủi ro: model âm thầm chọn 1
cube và bỏ rơi phần còn lại của câu hỏi thay vì thông báo cho người dùng.

### D. Top-2 cube RAG gần điểm nhau, câu hỏi chưa rõ nên dùng cube nào

✅ **Đã xử lý một phần.** Rule 12 (`prompt.py`) yêu cầu hỏi trắc nghiệm 2-3
lựa chọn cụ thể; `build_clarification_suggestions()` lấy tối đa 3 tên cube
từ `candidates["cubes"]` (nguồn dữ liệu giống hệt catalog model đang thấy,
nên luôn nhất quán) làm quick-reply chip cho FE.

### E. Câu hỏi ngoài phạm vi domain (out-of-domain)

Ví dụ: *"Hôm nay thời tiết thế nào"*, *"Giá vàng bao nhiêu"*.

🟡 **Implement rồi nhưng TẠM THỜI TẮT LẠI (2026-08-13).** `is_out_of_domain`
(`retriever.py`, cả 2 nhánh retrieval) có logic tính thật:
`max_cosine < cosine_threshold` khi backend embedding không phải `"hash"`
(hash-trick vector không mang ngữ nghĩa semantic nên không dùng để đánh
giá), và `orchestrator.py` nhánh `if is_ood:` (vẫn còn nguyên, không xoá)
trả `NLUStatus.CLARIFICATION` kèm message hướng dẫn + `suggestions` liệt kê
toàn bộ tên cube đang hỗ trợ. **Nhưng** ngay khi test tay trên UI thật
(embedding thật, không phải hash-fallback trong sandbox), phát hiện
**false positive thật**: câu hỏi rất cụ thể, đúng domain `traffic_flow`
(*"Số lần vượt tốc độ và tốc độ trung bình ở khu TTTM từ ngày 21-27/7 hôm
qua là bao nhiêu?"*) vẫn bị chặn nhầm — `cosine_threshold=0.3` chưa được
calibrate bằng eval set thật, và macro-document dạng "keyword soup" của mỗi
cube (tên field + mô tả nối chuỗi) có thể khiến cosine tuyệt đối với câu hỏi
tự nhiên thấp hơn 0.3 dù RRF (rank-based) vẫn xếp hạng đúng cube.

→ Đã revert `is_out_of_domain` về hardcode `False` ở cả 2 nhánh retrieval
(logic thật giữ nguyên dạng comment, dễ bật lại), test tương ứng
(`test_triggers_for_non_hash_backend_below_threshold`,
`test_not_triggered_when_threshold_is_zero` trong `tests/test_retriever.py`)
đánh dấu `@pytest.mark.skip` kèm lý do. **Cần** bộ câu hỏi eval trong/ngoài
domain + đo phân bố `max_cosine_score` thật (qua Langfuse hoặc script riêng)
trước khi bật lại — không đoán ngưỡng mới khi chưa có dữ liệu. Có test:
`test_out_of_domain_question_triggers_clarification_without_calling_llm`
(`tests/test_orchestrator.py`, dùng fake retriever nên không phụ thuộc trạng
thái bật/tắt ở trên — vẫn xác nhận đúng orchestrator xử lý `is_ood=True`
nếu retriever báo về), `TestOutOfDomainGuardrail`
(`tests/test_retriever.py`).

### F. RAG recall miss / RRF score thấp khiến catalog bị cắt hẹp sai

Tương ứng **FIX-09** trong `improvement_proposals.md`.

✅ **Đã xử lý (mức MVP tĩnh).** `CatalogRetriever.top_k_cubes` tăng default
từ 2 → 3 (configurable qua `RAG_TOP_K_CUBES` hoặc constructor param) — rẻ vì
Cube-First đã nạp 100% measures/dimensions của cube được chọn, nên thêm 1
cube chỉ đánh đổi prompt dài hơn một chút để giảm rõ rệt rủi ro recall miss.
Có test: `TestTopKCubesConfigurable` (`tests/test_retriever.py`).

**Chưa làm (cố ý để lại):** heuristic "mở rộng K động theo score gap giữa
rank K và K+1" — dữ liệu để tune ngưỡng đó chưa có (phụ thuộc FIX-08
Recall@K eval set, chưa tồn tại), nên số tĩnh config-được là lựa chọn an
toàn nhất ở bước này; nâng cấp lên dynamic expansion để lại cho sau khi có
eval set.

### G. Giá trị filter mơ hồ / entity resolution

Tương ứng **FIX-04** trong `improvement_proposals.md`.

Ví dụ: nhiều giá trị gần giống nhau trong `sample_values.yaml` (vd *"Khu
biệt thự A"* vs *"Khu biệt thự B"*), hoặc alias map/difflib match nhầm.

✅ **Đã xử lý.** `SampleValues.resolve()` giờ trả 3-tuple
`(value, changed, ambiguous_candidates)`: `alias_map` vẫn ưu tiên tuyệt đối
(curated, không tính ambiguity); fallback fuzzy giờ so khớp **không phân
biệt hoa/thường** (bug fix — xem box bên dưới) và nếu `difflib.get_close_matches(n=3, cutoff=0.6)`
trả ≥2 candidate với `SequenceMatcher.ratio()` chênh lệch < `_AMBIGUITY_GAP`
(0.05) → coi là mơ hồ, KHÔNG đoán, trả `ambiguous_candidates` thay vì
best-match. `validator.py::_resolve_filter_values` đẩy candidate list này
thành lỗi validation, tự động chảy vào repair loop có sẵn ở
`orchestrator.py` (`tool_result is_error=True`) — tái dùng nguyên cơ chế
hiện có, không cần pipeline riêng. Có test:
`test_ambiguous_filter_value_is_rejected` (`tests/test_validator.py`).

> **Bug đi kèm được phát hiện & fix trong lúc implement:** fuzzy-match
> trước đây case-sensitive — `difflib.get_close_matches(value.lower(), allowed, ...)`
> so `value.lower()` với `allowed` KHÔNG lower, nên "evening_full" vs
> "EVENING_FULL" chỉ overlap ký tự `_` (ratio ~0.08, dưới cutoff 0.6) và
> không match được — `resolve()` trả về nguyên giá trị input, không đổi.
> Test `test_fuzzy_matches_filter_value` từng fail vì lý do này (xác nhận
> bằng cách chạy trực tiếp `SampleValues.resolve()`, không qua pytest, vì
> host không có sẵn dependency). Đã fix bằng cách so khớp trên
> `{a.lower(): a for a in allowed}` rồi map ngược lại giá trị gốc.

### H. Follow-up ngắn dựa vào lịch sử hội thoại (anaphora / short-answer)

Ví dụ: hệ thống hỏi *"Bạn muốn xem tốc độ hay lưu lượng xe?"*, người dùng
trả lời *"Tốc độ"*.

✅ **Đã xử lý.** Session store (`app/session/` — `SessionStore` Protocol,
`InMemorySessionStore`, `RedisSessionStore`, chọn qua
`SESSION_STORE_BACKEND`) lưu và nạp lại `history` per-request qua
`session_id`. Bug double-nesting message (content bị bọc thành dict thay vì
str, gây HTTP 400 ở lượt gọi kế tiếp) đã được fix bằng helper dùng chung
`_append_assistant_message()` (`orchestrator.py:227`). Có test round-trip:
`test_clarification_history_feeds_into_second_turn`
(`tests/test_orchestrator.py`), assert trực tiếp cả 2 vế: shape message
đúng VÀ lượt 2 resolve đúng dựa trên history.

### I. Vòng lặp clarification không có điểm dừng

✅ **Đã xử lý.** `SessionStore` Protocol (`app/session/store.py`) mở rộng
thêm `get_clarification_streak()`/`set_clarification_streak()` (implement ở
cả `InMemorySessionStore` và `RedisSessionStore`, degrade-êm khi Redis lỗi
giống `get()`/`save()`) — đếm riêng, tách khỏi `messages` (history không
mang metadata trạng thái theo từng lượt nên không suy ra streak đáng tin
cậy từ nội dung message được). `server.py::_apply_clarification_cap()` gọi
ngay sau `orchestrator.interpret()` ở cả 2 endpoint: `CLARIFICATION` liên
tiếp tăng streak, vượt `settings.max_clarification_streak` (mặc định 2, qua
`MAX_CLARIFICATION_STREAK`) → ghi đè message + suggestions bằng toàn bộ
danh mục cube, reset streak về 0; `QUERY`/`INVALID` reset streak; `ERROR`/
`REFUSAL` không đụng (nhất quán với `_SAVE_STATUSES`). Có test:
`test_repeated_clarification_escalates_to_full_catalog_listing`
(`tests/test_server.py`), round-trip streak trong `tests/test_session_store.py`.

### J. Refusal (safety) bị nhầm với clarification

✅ **Đã xử lý riêng biệt.** `parsed.is_refusal` được check TRƯỚC nhánh
clarification trong `orchestrator.py` → trả `NLUStatus.REFUSAL`, tách biệt
hoàn toàn khỏi `NLUStatus.CLARIFICATION` cả về status lẫn message. Có test:
`test_refusal_is_detected_before_reading_tool_calls`.

### K. Input rỗng / whitespace / chỉ ký tự đặc biệt

❓ **Vẫn hên xui — chưa cải thiện.** `_tokenize()` (`retriever.py`) trả về
set rỗng cho input rỗng/toàn ký tự đặc biệt; BM25 score có bảo vệ chia 0
(`len(q_tokens) or 1.0`). OOD guardrail (case E) từng được bật lại nhưng đã
**tạm tắt** do false positive thật (xem case E) — nên input rỗng/nhiễu vẫn
"vô tình" phụ thuộc vào việc Rule 13 chặn được, không có cơ chế minh bạch
qua ngưỡng cosine như dự tính ban đầu. Sẽ tự động cải thiện khi case E được
bật lại sau khi calibrate.

### L. Mốc thời gian mơ hồ (vd "gần đây", không nêu thời gian)

✅ **Chấp nhận được theo thiết kế — không phải bug.** Rule 8 (`prompt.py`)
cho phép để trống `timeDimensions` khi câu hỏi không nêu mốc thời gian;
validator tự áp mặc định `last 30 days`
(`validator.py:_validate_time_dimensions`, dòng 179-188) và ghi rõ trong
`notes` trả về cho người dùng biết hệ thống đã áp default gì. Đây là lựa
chọn UX có chủ ý (default hợp lý thay vì hỏi lại cho mọi câu hỏi thiếu mốc
thời gian) — không cần xử lý thêm.

---

## 3. Liên kết chéo

- **FIX-04** (ambiguous filter value) và **FIX-09** (RAG low-confidence
  fallback) trong [`improvement_proposals.md`](../../improvement_proposals.md)
  — case G và F ở trên là bản mô tả đầy đủ hơn, dùng làm căn cứ implement.
- [`03-rag-to-nlu-deep-dive.md`](03-rag-to-nlu-deep-dive.md) mục 3
  (Retrieval: BM25 + Cosine + RRF Fusion) — cơ chế nền cho case D/E/F.
- [`tests/test_orchestrator.py`](../tests/test_orchestrator.py),
  [`tests/test_retriever.py`](../tests/test_retriever.py),
  [`tests/test_validator.py`](../tests/test_validator.py),
  [`tests/test_session_store.py`](../tests/test_session_store.py),
  [`tests/test_server.py`](../tests/test_server.py) — test cho các case đã
  xử lý (A, B, F, G, H, I, J) + case E (skip 2 test threshold, xem case E).

## 4. Việc chưa làm (ngoài phạm vi implement lần này)

- **Calibrate ngưỡng** `COSINE_THRESHOLD` (case E) và `RAG_TOP_K_CUBES`
  (case F) bằng eval set thật — 2 giá trị default hiện tại (`0.3`, `3`) là
  lựa chọn hợp lý nhưng chưa được đo bằng bộ câu hỏi trong/ngoài-domain
  thật (phụ thuộc FIX-08 Recall@K eval set, chưa tồn tại).
- **Dynamic top-K expansion theo score gap** (case F) — nâng cấp từ số tĩnh
  hiện tại, để lại tới khi có eval set.
- **Case C** (cross-domain question) và phần còn lại của **case K** (input
  rỗng với backend `"hash"`) — chưa nằm trong 4 gap ưu tiên lần này.
