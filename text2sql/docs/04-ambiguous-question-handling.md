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
| M | Một chủ đề rõ, nhiều measure độc lập (vd "hiệu suất") | 🟡 | Nhóm 2 - Dạng B (`prompt.py`) — thay thế bởi case N |
| N | Mơ hồ cấp field (measure/dimension) trong 1 cube | ✅ | `field_ambiguity` tất định (`retriever.py`) + hint tiêm theo câu hỏi |
| O | Cụm từ thời gian mơ hồ có chủ ý (khác case L, vd "lúc trước") | ✅ | `time_ambiguity.py::check_vague_time_reference()` + hint tiêm theo câu hỏi |

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

> **Mở rộng (kế hoạch fix Yellow case, Nhóm 2/Y06 — "khu trung tâm" không
> khớp danh mục):** phát hiện thêm 1 gap — nhánh "0 candidate đủ gần"
> (`if not close: return value, False, None`) trước đây xử lý GIỐNG "giá trị
> đã đúng" (im lặng pass-qua), khiến Cube query chạy với filter khớp 0 dòng
> mà không cảnh báo gì. Đã sửa: nhánh này giờ CŨNG trả về `ambiguous_candidates`
> (toàn bộ `allowed`) để đẩy vào repair loop, cùng cơ chế với nhánh tie. Kèm
> đăng ký `districts.id`/`districts.name` vào `sample_values.yaml` (trước đó
> chưa có, dù 6 cube nghiệp vụ khác đều có `section_id`). Có test:
> `test_unmatched_filter_value_with_no_close_candidate_is_rejected`
> (`tests/test_validator.py`). **Lưu ý:** đây là phòng thủ LỚP 2, không đảm
> bảo tái hiện đúng chính xác kịch bản Y06 gốc — log benchmark thật cho thấy
> LLM ở đó chưa từng gọi tool với filter sai (chọn nhầm hướng hỏi lại ở tầng
> routing trước đó) — xem case N/hint mới có thể cải thiện gián tiếp qua
> routing rõ hơn, đo lại bằng benchmark thật.

> **Cập nhật (Bước 7, benchmark LLM thật, 2026-08-19): residual đã đóng.**
> Y06 giờ pass 3/3 qua API thật, nội dung đúng ("Giá trị 'Khu trung tâm'
> không xác định được trong hệ thống. Hệ thống chỉ có các khu vực như Khu
> biệt thự, Căn hộ, và TTTM."). 2 phát hiện bổ sung để đạt được kết quả này
> (ngoài phạm vi kế hoạch gốc, xem
> [yellow_case_fix_2026-08-19.md](../tests/benchmark_results/yellow_case_fix_2026-08-19.md)):
> (1) `_field_ambiguity()` (case N) từng bị kích hoạt SAI NGỮ CẢNH cho chính
> câu hỏi Y06 — token "trung" (từ tên khu bịa "khu trung tâm") trùng ngẫu
> nhiên với "trung bình" trong mô tả `traffic_flow.avg_speed`, khiến hint gợi
> ý chọn metric thay vì để lỗi entity-mismatch này lộ ra — fix bằng cách nâng
> `FIELD_AMBIGUITY_MIN_SCORE` 0.25→0.3; (2) retry message của repair-loop
> (`orchestrator.py`) từng ép "phải gọi lại tool", khiến LLM không còn lựa
> chọn nào ngoài `refuse_request` khi giá trị filter không thể tự sửa — thêm
> lối thoát "trả lời bằng text thường" riêng cho đúng loại lỗi này.

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

✅ **Chấp nhận được theo thiết kế — không phải bug — CHỈ khi câu hỏi hoàn
toàn KHÔNG nhắc gì tới thời gian.** Rule 8 (`prompt.py`) cho phép để trống
`timeDimensions` trong trường hợp đó; validator tự áp mặc định `last 30 days`
(`validator.py:_validate_time_dimensions`, dòng 179-188) và ghi rõ trong
`notes` trả về cho người dùng biết hệ thống đã áp default gì. Đây là lựa
chọn UX có chủ ý (default hợp lý thay vì hỏi lại cho mọi câu hỏi thiếu mốc
thời gian) — không đổi.

⚠️ **Phân biệt với case O bên dưới** (kế hoạch fix Yellow case, theo yêu cầu
người dùng): câu hỏi CÓ nhắc thời gian nhưng bằng cụm từ mơ hồ CÓ CHỦ Ý (vd
"lúc trước", Y07) là 1 case KHÁC — người dùng rõ ràng có 1 mốc trong đầu
nhưng diễn đạt mơ hồ, không nên default êm như trường hợp không nhắc gì.

### M. Một chủ đề rõ, nhiều measure độc lập

Ví dụ: *"Hiệu suất hệ thống đèn đường ở Khu Căn hộ đêm 22/7"* (Y04) — chủ đề
"hệ thống đèn đường" rất rõ, nhưng từ "hiệu suất" ánh xạ được tới ≥2 measure
ĐỘC LẬP của cùng cube `smart_lighting` (tiêu thụ điện `total_power_kwh`, số
cột hỏng `faulty_lamp_count`, tỷ lệ thời gian hỏng `faulty_time_pct`) — khác
nhau về bản chất đo lường, không phải các thành phần cộng dồn thành 1 tổng.

✅ **Đã xử lý (Phase 1, prompt.py rewrite 2026-08-19).** Trước đây case này
lọt qua mọi rule: case A chỉ bắt "không nêu topic/entity nào cả" (ở đây có
nêu rõ "hệ thống đèn đường"), còn rule cũ (Rule 3) ra lệnh trích xuất *"được
đề cập hoặc hàm ý"* — chữ "hàm ý" chính là kẽ hở khiến model tự gộp cả 3
measure vào 1 lời gọi thay vì hỏi lại. Benchmark thực tế xác nhận: Y04 trả
`status: success` với 5 measures gộp chung (kể cả 2 measure ngoài kỳ vọng).

Prompt.py viết lại (Nhóm 2 - Dạng B) tách riêng case này khỏi case A: khi câu
hỏi có 1 chủ đề/đối tượng rõ ràng nhưng dùng 1 từ chung chung ("hiệu suất",
"tình hình", "chất lượng", "kết quả", "thế nào") ánh xạ tới ≥2 measure độc
lập trong CÙNG 1 cube, bắt buộc hỏi lại trắc nghiệm cụ thể thay vì tự gộp hết
hay tự chọn 1 measure. Rule 5 (Nhóm 3, cũ là Rule 3) đồng thời được sửa: bỏ
chữ "hàm ý", chỉ trích xuất measure được nêu TÊN RIÊNG BIỆT, và dẫn chiếu rõ
case dùng 1 từ chủ đề chung chung phải xử lý theo Nhóm 2 - Dạng B thay vì tự
đoán ở đây.

⚠️ **Cập nhật (kế hoạch fix Yellow case, 2026-08).** Benchmark thực tế sau
Phase 1+2 cho thấy chỉ dựa vào rule text tĩnh vẫn KHÔNG đủ nhất quán (model
function-calling thiên hướng ưu tiên gọi tool — xem `app/llm/openai_compatible.py`
`tool_choice: "auto"`). Root cause sâu hơn: `candidates['cubes']` trong thực
tế luôn có ≥3-4 phần tử (không bao giờ đúng 1), khiến `build_clarification_suggestions()`
gần như không bao giờ dùng nhánh gợi ý measure cụ thể. Xem case N bên dưới
cho cơ chế fix mới (tín hiệu `field_ambiguity` tính tất định ở retriever +
tiêm hint theo từng câu hỏi) — case N thay thế hoàn toàn cách tiếp cận thuần
rule-text của case M.

---

### N. Mơ hồ cấp field (measure/dimension) trong 1 cube — cơ chế thay thế case M

Gồm 2 nhóm case tưởng khác nhau nhưng dùng CHUNG 1 cơ chế: "N measure độc lập"
(case M cũ — Y01/Y02/Y03/Y04/Y05) VÀ "measure liên tục vs dimension phân
hạng của cùng khái niệm" (Y08 điểm Livability số vs xếp hạng EXCELLENT/GOOD/POOR,
Y09 tỷ lệ lấp đầy % vs mức LOW/OPTIMAL/CRITICAL, Y10 độ ồn dBA vs phân loại
QUIET/MODERATE/NOISY).

✅ **Đã xử lý (kế hoạch fix Yellow case).** `CatalogRetriever._field_ambiguity()`
(`app/retrieval/retriever.py`) tính tín hiệu mơ hồ TẤT ĐỊNH bằng BM25-overlap
(không phải 1 similarity score liên tục làm short-circuit chặn cứng — tránh
lặp lại sai lầm case E): pool ứng viên = measures ∪ dimension "phân
hạng/phân loại" (hậu tố `_grade`/`_level`/`_category`/`_status`/`_mode`/`_type`
hoặc `severity`) của `top_cube` (cube nghiệp vụ RRF cao nhất, tín hiệu HẸP,
không tính cube tham chiếu — khác `candidates['cubes']` vốn luôn rộng). Nếu
field top-1 và top-2 điểm gần nhau (`gap_ratio` dưới ngưỡng, mặc định 0.2,
`FIELD_AMBIGUITY_GAP_RATIO`) và field top-1 đạt ngưỡng sàn tối thiểu
(`FIELD_AMBIGUITY_MIN_SCORE`, tránh câu hỏi thực chất thuộc cube khác) →
`field_ambiguity` khác `None`.

Kết quả này được dùng theo 2 cách: (1) `build_field_ambiguity_hint()`
(`app/nlu/prompt.py`) tiêm hint CỤ THỂ-THEO-CÂU-HỎI vào lượt hỏi hiện tại
(không sửa `_RULES` tĩnh, không hard-block — LLM vẫn tự quyết định cuối); (2)
`build_clarification_suggestions()` dùng thẳng candidates thay vì suy qua
điều kiện chết `len(cubes) == 1`.

**Lưu ý về độ chính xác:** so khớp BM25-overlap thuần từ vựng không phân biệt
được MỌI cặp field khó (vd `avg_livability_index` vs `livability_grade` khi
câu hỏi chỉ khác nhau ở cách diễn đạt tinh tế như "...có tốt không?" so với
"...trung bình...là bao nhiêu?") — 2 phát hiện quan trọng trong lúc calibrate:
(a) chuẩn hoá điểm phải theo SỐ TOKEN CÂU HỎI (không phải độ dài text field),
nếu không field có mô tả ngắn bị đội điểm ảo; (b) phải loại "token neo domain"
(tên khái niệm chung xuất hiện ở HẦU HẾT field cùng cube, vd "livability")
khỏi phép so khớp — kiểu IDF đơn giản — nếu không mọi câu hỏi nhắc đúng tên
khái niệm sẽ tạo baseline overlap giả tạo giữa TẤT CẢ field. Ngoài ra, câu
hỏi có từ so sánh nhất ("đông nhất", "cao nhất"...) được loại trừ hẳn khỏi cơ
chế này, nhường cho Rule 10 (order+limit) đã xử lý sẵn — tránh chồng chéo 2
cơ chế trên cùng 1 loại câu hỏi.

⚠️ **Cập nhật (Bước 7, benchmark LLM thật lặp lại nhiều lần, 2026-08-19).**
Kết quả đầy đủ:
[yellow_case_fix_2026-08-19.md](../tests/benchmark_results/yellow_case_fix_2026-08-19.md).
8/10 Yellow case pass sạch 3/3 (từ baseline 0/10). 3 vấn đề chỉ lộ ra qua
benchmark thật lặp lại (không thấy được bằng diagnostic retrieval thuần hay
code review), đã vá:

1. **Từ vựng tiếng Việt quá chung chung gây nhiễu cube-level retrieval.**
   Việc thêm "giao thông" vào `city_health_index.avg_traffic_score`, "trung
   bình" vào `street_incidents.avg_duration_min`... (curate ở bước nền tảng
   của kế hoạch) vô tình khiến 2 câu hỏi Green thuần `traffic_flow` (G01) và
   `city_health_index` (G10) kéo thêm cube không liên quan vào top-3
   candidate, đủ nhiễu để LLM `refuse` sai dù có dữ liệu thật. Fix: trim các
   từ chung chung này khỏi 7 entry — chỉ giữ phần không trùng lặp domain
   khác, xác nhận không cần cho bất kỳ case Yellow nào đang test.
2. **G10/G11 residual (`avg_livability_index` vs `livability_grade`, xem
   ghi chú "Lưu ý về độ chính xác" ở trên) — 1 nửa đã đóng.** Câu G10 tự nêu
   rõ "trung bình" trong câu hỏi nhưng `avg_livability_index` lại thiếu đúng
   từ này trong vietnamese term — thêm vào, gap_ratio từ 0.167 (dưới ngưỡng,
   mơ hồ sai) lên 0.375 (rõ ràng). G11 (câu so sánh, không có "trung bình")
   vẫn còn mơ hồ — residual chấp nhận được vì hint không hard-block (LLM vẫn
   trả lời đúng phần lớn thời gian, xem file benchmark).
3. **Hint field-ambiguity thiếu câu cấm rõ ràng.** `build_field_ambiguity_hint()`
   trước đây chỉ ngụ ý "áp dụng Nhóm 2 - Dạng B" mà không cấm hẳn
   `refuse_request` — model đôi khi đọc "không chắc field nào" thành
   `external_data_unavailable` rồi từ chối thay vì hỏi lại bằng text (verify:
   Y02/Y04/Y09 dao động clarification/refusal giữa các lần chạy giống hệt
   nhau). Thêm câu cấm tường minh, xác nhận ổn định 6/6 lần sau fix.

⚠️ **Cập nhật (điều tra root cause Y03/Y05 theo yêu cầu người dùng,
2026-08-20).** Cả 2 residual trên đã đóng — **10/10 Yellow case giờ pass
sạch 3/3**. 2 root cause hoàn toàn khác nhau, không phải chỉnh ngưỡng:

1. **Y05 — lỗi tie-break RRF cấp CUBE (không phải field_ambiguity).**
   `top_cube` nhận nhầm `street_incidents` thay vì `traffic_flow` vì BM25
   cube-level cho câu hỏi này TIE TUYỆT ĐỐI giữa 2 cube (domain keyword của
   cả 2 đều chứa "giao thông", xem `domain_alias_map` trong
   `_build_rich_documents()`) — `rrf_scores.sort()` trước đây chỉ sort theo
   điểm RRF, nên khi tie tuyệt đối, `sort` ổn định (stable) giữ nguyên thứ
   tự xuất hiện trong `catalog.cubes` (thứ tự trả về từ Cube Meta API,
   HOÀN TOÀN không liên quan tới độ liên quan) — `street_incidents` thắng
   chỉ vì đứng trước trong danh sách, dù dense embedding (semantic, đáng
   tin hơn BM25 token-overlap thô cho case đồng nghĩa/lân cận domain) đã
   phân biệt rõ `traffic_flow` cao hơn hẳn (0.39 vs 0.34). Fix: thêm
   `dense_rank` làm tie-break phụ trong `_retrieve_cube_first()` khi RRF
   score bằng nhau tuyệt đối.
2. **Y03/Y05 — 1 field thắng áp đảo do trùng khớp NGUYÊN VĂN cụm mơ hồ.**
   Cả 2 câu đều dùng đúng 1 cụm từ mơ hồ ("mức độ ảnh hưởng" cho Y03, "tình
   hình giao thông" cho Y05) mà trước đây CHỈ 1 field trong pool ứng viên có
   nguyên cụm này trong vietnamese term (`total_impact_hours`/
   `congestion_rate`) — field đó thắng áp đảo (gap_ratio 0.5, "đủ tách biệt"
   → không mơ hồ) dù ý định thiết kế là CẢ pool ứng viên đều hợp lệ. Fix
   (cùng pattern case N gốc): lặp lại cụm mơ hồ GIỐNG HỆT ở tất cả field
   ứng viên hợp lệ thay vì chỉ 1 field, để chúng tie đều nhau. Kèm theo: bỏ
   "mức độ" khỏi `street_incidents.severity` — thêm cụm này vào 3 measure
   của Y03 vô tình đẩy doc_freq của "mức"/"độ" chạm ngưỡng loại token neo
   domain (IDF filter), hạ điểm xuống dưới sàn tối thiểu.

Chi tiết đầy đủ + verify (test mới, benchmark thật, Chrome UI):
[yellow_case_fix_2026-08-20.md](../tests/benchmark_results/yellow_case_fix_2026-08-20.md).

---

### O. Cụm từ thời gian mơ hồ có chủ ý (khác case L)

Ví dụ: *"Bãi đỗ xe ở Khu Căn hộ lúc trước như thế nào?"* (Y07) — câu hỏi CÓ
nhắc thời gian bằng cụm từ mơ hồ ("lúc trước") chứ không phải hoàn toàn không
nhắc gì (case L).

✅ **Đã xử lý (kế hoạch fix Yellow case, Nhóm 4 — theo quyết định người
dùng: đưa vào phạm vi fix dù trước đây coi là "đúng thiết kế" theo case L).**
`app/nlu/time_ambiguity.py::check_vague_time_reference()` — regex tất định
trên danh sách cụm từ mơ hồ cố định tiếng Việt ("lúc trước", "trước đây",
"gần đây", "dạo này", "hồi đó", "hồi trước", "vừa rồi", "mới đây"), loại trừ
khi câu hỏi ĐÃ có mốc thời gian cụ thể khác (dd/mm, "tuần/tháng này/trước/sau",
"hôm nay/qua", "ngày mai"). `build_vague_time_hint()` tiêm hint vào lượt hỏi
hiện tại (cùng cơ chế tiêm hint với case N, KHÔNG hard-block) yêu cầu hỏi lại
ngày cụ thể trong dải dữ liệu 21/7-28/7/2026 thay vì default `last 30 days`
êm như case L.

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
  Case M: `test_multi_measure_topic_triggers_clarification_suggestions`
  (`tests/test_orchestrator.py`) + entry `cases.yaml` (`y04_lighting_performance_ambiguous`,
  `y05_traffic_situation_ambiguous`) — 2 case này chỉ verify được hành vi
  model thật qua UI/eval harness (xem ghi chú mục 4), `cases.yaml` chỉ mô tả
  kỳ vọng.

## 4. Việc chưa làm (ngoài phạm vi implement lần này)

- **Calibrate ngưỡng** `COSINE_THRESHOLD` (case E) và `RAG_TOP_K_CUBES`
  (case F) bằng eval set thật — 2 giá trị default hiện tại (`0.3`, `3`) là
  lựa chọn hợp lý nhưng chưa được đo bằng bộ câu hỏi trong/ngoài-domain
  thật (phụ thuộc FIX-08 Recall@K eval set, chưa tồn tại).
- **Dynamic top-K expansion theo score gap** (case F) — nâng cấp từ số tĩnh
  hiện tại, để lại tới khi có eval set.
- **Case C** (cross-domain question) và phần còn lại của **case K** (input
  rỗng với backend `"hash"`) — chưa nằm trong 4 gap ưu tiên lần này.
