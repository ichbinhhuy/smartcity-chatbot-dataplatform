# Kiến trúc LLM Function-Calling (NL → Structured Query)

Sprint 1 · Text-to-SQL Agent cho nền tảng Smart City

> **Đã superseded bởi [02-cube-architecture.md](02-cube-architecture.md).** Dự án chuyển hướng
> dùng Cube Core (self-host) làm semantic layer + query engine thay vì tự viết. Các phần sau
> **không còn áp dụng**: mục 2 (semantic model tự viết `smart_city.yaml`), `app/semantic/models.py`
> / `loader.py` / `engine.py` trong bảng module ở mục 3, và mục 4.3/4.4 (đặc thù Claude, giờ chỉ
> áp dụng nếu chọn Claude làm LLM). Các phần **vẫn còn giá trị tham khảo**: mục 1 (lý do không
> để LLM viết SQL trực tiếp), mục 4.1 (`tool_choice=auto` để disambiguation), mục 4.2 (nguyên lý
> validation + repair loop), và toàn bộ `app/nlu/*` (vẫn giữ, chỉ đổi nguồn catalog).

---

## 1. Vấn đề và lựa chọn kiến trúc

Cách làm ngây thơ là đưa schema DB + câu hỏi cho LLM và bảo nó viết SQL. Cách đó lỗi
nhiều vì LLM phải đồng thời: nhớ chính xác tên bảng/cột, tự suy ra join đúng, và sinh
SQL đúng cú pháp — ba việc nó không đảm bảo được.

Kiến trúc này tách làm hai, **LLM không bao giờ chạm tới SQL**:

```
       ┌──────────────── NLU (không xác định) ─────────────────┐  ┌── Deterministic ──┐

Câu hỏi ──▶ Context ──▶ Claude ──▶ Parser ──▶ Validator ──▶ StructuredQuery ──▶ Semantic ──▶ SQL ──▶ DW
            Builder    (tool use)     │           │                              Engine
                                      │           │
                                 text-only    lỗi ràng buộc
                                      │           │
                                      ▼           ▼
                              Câu hỏi làm rõ   tool_result(is_error) ──┐
                                                                       │
                                      └────────── repair loop ─────────┘
```

| Vấn đề | Text-to-SQL thuần | Kiến trúc này |
|---|---|---|
| Nhớ tên bảng/cột chính xác | LLM phải nhớ, dễ hallucinate | Chọn từ `enum` sinh từ semantic model |
| Suy ra join đúng | LLM tự suy, dễ sai | Định nghĩa cứng trong `relationships` |
| Validate trước khi chạm DB | Phải parse SQL | Validate object có cấu trúc |
| Chặn `DROP` / `UPDATE` | Phải regex/parse SQL | Không cần — LLM không sinh SQL |

---

## 2. Nguyên tắc cốt lõi: một nguồn sự thật

`semantic/smart_city.yaml` là nguồn duy nhất. Tool schema, system prompt và validation
layer **đều được generate từ nó**, không cái nào viết tay:

```
semantic/smart_city.yaml
        │
        ├──▶ tool_schema.build_query_tool()   → enum metrics/dimensions cho LLM
        ├──▶ prompt.build_system_prompt()      → mô tả ngữ nghĩa cho LLM
        └──▶ validator.QueryValidator          → ràng buộc liên trường
```

Thêm một metric mới = sửa YAML. Không sửa code, và ba thứ trên không thể lệch nhau.
`tests/test_semantic_layer.py::test_tool_schema_enums_match_semantic_model` khoá bất biến này.

---

## 3. Các module

| File | Vai trò |
|---|---|
| [app/semantic/models.py](app/semantic/models.py) | Schema Pydantic của semantic layer (models / relationships / cubes) |
| [app/semantic/loader.py](app/semantic/loader.py) | Load YAML + kiểm tra nhất quán, lỗi nổ lúc khởi động |
| [app/nlu/tool_schema.py](app/nlu/tool_schema.py) | Sinh tool schema cho function-calling |
| [app/nlu/prompt.py](app/nlu/prompt.py) | Sinh system prompt + runtime context |
| [app/nlu/client.py](app/nlu/client.py) | Wrapper Anthropic SDK, không chứa logic nghiệp vụ |
| [app/nlu/parser.py](app/nlu/parser.py) | Phân loại response: tool call / text / refusal |
| [app/nlu/validator.py](app/nlu/validator.py) | Ràng buộc liên trường + resolve giá trị filter |
| [app/nlu/orchestrator.py](app/nlu/orchestrator.py) | Ghép pipeline + repair loop |
| [app/nlu/types.py](app/nlu/types.py) | `StructuredQuery` — hợp đồng với Semantic Engine |
| [app/semantic/engine.py](app/semantic/engine.py) | Biên giới sang phần sinh SQL (sprint 1, hạng mục riêng) |

---

## 4. Bốn quyết định thiết kế đáng chú ý

### 4.1 `tool_choice: auto` — model phải có quyền KHÔNG gọi tool

Đây là cơ chế disambiguation, không phải thiếu sót. Khi model trả lời bằng text thay vì
gọi tool, nghĩa là nó không tìm được metric phù hợp hoặc câu hỏi mơ hồ — backend bắt case
này và trả nguyên văn về cho người dùng làm câu hỏi làm rõ
([orchestrator.py](app/nlu/orchestrator.py), nhánh `not parsed.has_tool_call`).

Nếu dùng structured output ép buộc (`output_config.format`), model bị buộc phải điền field
dù không chắc → tăng hallucination. Đó là lý do chọn **tool use** chứ không phải JSON mode.

Câu quan trọng nhất trong system prompt là quy tắc số 5: *"Nếu câu hỏi mơ hồ… ĐỪNG gọi tool"*.

### 4.2 Validation layer bắt thứ `enum` không bắt được

`enum` chặn được tên không tồn tại, nhưng không biết ràng buộc **liên trường**:

- `energy.total_consumption` + `traffic.congestion_level` — cả hai đều hợp lệ riêng lẻ,
  nhưng khác cube nên không dùng chung được.
- Filter đặt lên cột thời gian (đáng lẽ dùng `time_range`).
- `order_by` trỏ tới field không nằm trong `metrics`/`dimensions` đã chọn.
- `limit` vượt guardrail.
- Giá trị filter LLM tự bịa ("Residential") không khớp giá trị thật ("residential")
  → fuzzy-match rồi ghi note cho người dùng biết đã hiểu thành gì.

Khi validate fail, lỗi được đưa **ngược lại cho model** dưới dạng `tool_result` với
`is_error: true` để nó tự sửa (tối đa `MAX_REPAIR_ATTEMPTS` lần, mặc định 1).

### 4.3 Prompt caching: tách phần ổn định khỏi phần biến động

Semantic model là ổn định → đặt trong `system` với `cache_control`.
Ngày hiện tại là biến động → đặt **sau** câu hỏi trong `messages`.

Nếu nhét `date.today()` vào system prompt, prefix đổi mỗi ngày và cache mất tác dụng.
Với Claude Opus 5, runtime context được gửi bằng `{"role": "system"}` giữa hội thoại —
kênh operator không thể bị giả mạo bởi nội dung người dùng nhập vào. Model không hỗ trợ
thì tự động fallback về việc nhét vào lượt user
([config.py](app/config.py) `MID_CONVERSATION_SYSTEM_MODELS`).

### 4.4 KHÔNG tắt thinking

Trên Claude Opus 5 thinking bật mặc định. Nếu tắt (`thinking: {"type": "disabled"}`),
model thỉnh thoảng viết lời gọi tool ra **dạng text** thay vì emit `tool_use` block:
lượt đó trả về thành công, không có lỗi, nhưng tool không bao giờ chạy — đúng thứ sẽ phá
vỡ pipeline này một cách âm thầm.

Muốn giảm chi phí/độ trễ thì hạ `effort` (mặc định ở đây là `low` cho bước NLU), đừng tắt thinking.

---

## 5. Chọn model

| Bước | Yêu cầu | Cấu hình |
|---|---|---|
| NLU (câu hỏi → structured query) | Chính xác cao, độ trễ vừa | `NLU_MODEL`, `NLU_EFFORT=low` |
| NLG (kết quả → câu trả lời) | Bài toán dễ hơn (tóm tắt số liệu) | `NLG_MODEL` |

Cả hai mặc định `claude-opus-5`. Hạ NLG xuống model nhẹ hơn (ví dụ `claude-haiku-4-5`) là
cách giảm chi phí rõ nhất, nhưng đó là quyết định của bạn nên mặc định không tự hạ.
Điểm kiến trúc là `llm_client.py` cấu hình model **theo từng bước**, không hard-code một
model xuyên suốt.

---

## 6. Chạy thử

```bash
# 1. Cài dependency (môi trường hiện tại chưa có pip/venv — xem mục 8)
sudo apt install -y python3-pip python3-venv
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2. Xem prompt + tool schema được sinh ra (không gọi API, không tốn tiền)
.venv/bin/python -m app.main --inspect

# 3. Test offline (LLM giả — kiểm tra luồng điều khiển)
.venv/bin/python -m pytest tests/ -v --ignore=tests/test_nlu_live.py

# 4. Test thật với Claude API
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python -m app.main "Tổng tiêu thụ điện quận 1 tháng trước là bao nhiêu?"
.venv/bin/python -m pytest tests/test_nlu_live.py -v
```

`tests/cases.yaml` so khớp **theo từng field**, không exact-match — LLM có thể trả về cấu
trúc tương đương khác thứ tự. Đây là nền cho eval framework của sprint 3: mỗi lần sửa
prompt hoặc đổi model, chạy lại bộ này trước khi merge.

---

## 7. Phần chưa làm (có chủ ý)

| Hạng mục | Sprint |
|---|---|
| Semantic Engine sinh SQL thật | 1 (hạng mục riêng) — biên giới đã định nghĩa ở [engine.py](app/semantic/engine.py) |
| Chat UI + backend API | 1 (hạng mục riêng) — `NLUOrchestrator.interpret()` đã là interface sẵn sàng |
| Join nhiều cube, derived metrics, time comparison | 2 — validator hiện chặn multi-cube với thông báo rõ ràng |
| Lookup giá trị dimension thật từ DW | 2 — hook đã có ở `_resolve_filter_value`, hiện chỉ fuzzy-match `sample_values` |
| Multi-turn đầy đủ | 2 — `NLUResult.messages` đã trả về history để truyền vào lượt sau |
| Caching structured query | 2 |
| Guardrail đầy đủ, RLS | 3 — hiện mới có `MAX_ROW_LIMIT` |

---

## 8. Trạng thái kiểm chứng

Máy hiện tại **không có `pip` và `python3-venv`**, nên `pydantic` / `pytest` / `anthropic`
chưa cài được và bộ test chưa chạy. Những gì đã kiểm chứng thật:

- Toàn bộ 12 module Python compile sạch (`py_compile`).
- `semantic/smart_city.yaml` hợp lệ và nhất quán: 7 models, 7 relationships, 4 cubes,
  14 metrics, 12 dimensions, 4 time dimensions — không có base_object treo, không tên trùng,
  không tên chứa dấu chấm.
- Mọi metric/dimension trong `tests/cases.yaml` đều tồn tại thật trong semantic model.

Chạy `sudo apt install -y python3-pip python3-venv` rồi làm theo mục 6 để chạy test.
