# 📋 ĐỀ XUẤT CẢI THIỆN PIPELINE TEXT-TO-SQL SMARTCITY

> Tổng hợp từ: Phân tích source code thực tế + Peer review từ LLM bên ngoài.
> Ngày: 2026-08-10

---

## 🔴 NHÓM 1 — FIX NGAY (Ảnh hưởng trực tiếp đến độ chính xác Happy Case)

---

### [FIX-01] Xóa `dimensions` khỏi CubeQuery benchmark trong `usecase.md`

**Vấn đề:**
`usecase.md` hiện đặt `dimensions: ["traffic_flow.section_id"]` trong Happy Case CubeQuery, nhưng câu hỏi *"Tốc độ giao thông trung bình ở Khu biệt thự hôm nay?"* yêu cầu **1 con số scalar**, không phải **bảng GROUP BY**.

Khi có đồng thời `dimensions` + `filters` trỏ cùng `section_id`, Cube Core sinh:
```sql
SELECT section_id, AVG(avg_speed_kmh)
FROM fact_traffic
WHERE section_id = 'Khu biet thu'
GROUP BY section_id   -- ← dư thừa về ngữ nghĩa
```

**CubeQuery chuẩn cho Happy Case (không cần `dimensions`):**
```json
{
  "measures": ["traffic_flow.avg_speed"],
  "filters": [
    {
      "member": "traffic_flow.section_id",
      "operator": "equals",
      "values": ["Khu biet thu"]
    }
  ],
  "timeDimensions": [
    {
      "dimension": "traffic_flow.recorded_at",
      "dateRange": "today"
    }
  ]
}
```

**Ghi chú:** `dimensions` chỉ cần khi câu hỏi yêu cầu so sánh nhiều phân khu (ví dụ: *"Tốc độ từng khu vực hôm nay?"*).

**File cần sửa:** `usecase.md`, Mục 2 & Mục 6 (SQL minh họa).

---

### [FIX-02] Bổ sung `traffic_flow.section_id` vào `sample_values.yaml`

**Vấn đề:**
File `semantic/sample_values.yaml` hiện **không có key `traffic_flow.section_id`**. Cơ chế resolve trong `sample_values.py` hoạt động 2 bước:
1. Tra hardcode `alias_map` → Thành công với *"khu biệt thự"* đúng từ khóa.
2. Nếu không khớp → Tra `sample_values.yaml` bằng `difflib` → **TRỐNG** → giá trị raw của LLM đi thẳng vào Cube → **StarRocks trả về empty result, không báo lỗi**.

**Fix:** Thêm vào `semantic/sample_values.yaml`:
```yaml
traffic_flow.section_id:
  - "Khu biet thu"
  - "Can ho"
  - "TTTM"
```

**File cần sửa:** `text2sql/semantic/sample_values.yaml`

---

### [FIX-03] Sửa `date.today()` để lấy đúng timezone UTC+7

**Vấn đề:**
`prompt.py` dùng `date.today()` — lấy ngày theo timezone của container Docker (UTC). Sau **23:00 giờ Việt Nam (UTC+7)** = 16:00 UTC, `date.today()` trả về ngày hôm trước → câu hỏi "hôm nay" bị lệch 1 ngày.

**Fix gợi ý** trong `text2sql/app/nlu/prompt.py`:
```python
# Trước:
from datetime import date
today = today or date.today()

# Sau:
from datetime import datetime, timezone, timedelta
VN_TZ = timezone(timedelta(hours=7))
today = today or datetime.now(VN_TZ).date()
```

**File cần sửa:** `text2sql/app/nlu/prompt.py`

---

## 🟡 NHÓM 2 — FIX TRƯỚC BẢO VỆ (Ảnh hưởng đến chất lượng kỹ thuật khi trình bày)

---

### [FIX-04] Thêm confidence threshold cho difflib fuzzy match

**Vấn đề:**
`difflib.get_close_matches(cutoff=0.6)` không trả về confidence score. Nếu có 2 candidate điểm gần nhau (ví dụ *"Khu biệt thự A"* và *"Khu biệt thự B"*), hệ thống **âm thầm chọn cái đầu tiên** mà không cảnh báo người dùng.

**Quy trình chuẩn nên là:**
```
User input
    ↓
1. Unicode normalize (NFD, strip dấu) + exact match
    ↓
2. alias_map hardcode lookup
    ↓
3. difflib fuzzy fallback
    ↓
confidence >= threshold?
    ├── YES + unique → normalize & log
    └── NO hoặc ambiguous → trigger clarification
```

**File cần sửa:** `text2sql/app/catalog/sample_values.py`

---

### [FIX-05] Làm rõ behavior của Repair Loop trong tài liệu

**Vấn đề:**
`usecase.md` đề cập "Repair Loop tối đa N lần" nhưng không nêu rõ:
- N = bao nhiêu? (Thực tế: `MAX_REPAIR_ATTEMPTS=1` mặc định, tức là tối đa **2 attempts**)
- Sau khi hết N lần vẫn lỗi, hệ thống làm gì? (Thực tế: trả `NLUStatus.INVALID`, UI hiển thị *"Chưa dựng được truy vấn hợp lệ"*)

**Fix:** Cập nhật `usecase.md` Mục 1 và thêm bảng mô tả trạng thái kết thúc:

| Trạng thái kết thúc | Điều kiện | Phản hồi người dùng |
|---|---|---|
| `QUERY` (Happy Case) | Validate thành công | Câu trả lời NLG |
| `CLARIFICATION` | LLM trả text thay vì tool call | Yêu cầu làm rõ |
| `INVALID` | Hết N lần repair vẫn lỗi schema | Thông báo lỗi kỹ thuật |
| `REFUSAL` | LLM từ chối trả lời | Thông báo từ chối |
| `ERROR` | LLM API lỗi | Thông báo lỗi kết nối |

---

### [FIX-06] Cập nhật tuyên bố về "Cache < 15ms" — thêm benchmark thực tế

**Vấn đề:**
`usecase.md` trình bày `2-5ms` như đặc tính chung, nhưng:
- Pre-aggregation **chưa được khai báo** trong bất kỳ file `model/cubes/*.yml` nào.
- `CUBEJS_CACHE_AND_QUEUE_DRIVER=memory` là queue driver, **không phải pre-agg cache**.
- Cold path (query mới, time range mới) → quét trực tiếp StarRocks fact table → latency thực tế **vài trăm ms đến vài giây**.

**Fix đề xuất:**
1. Thêm `pre_aggregations:` block vào `traffic_flow.yml` cho daily rollup.
2. Đo và ghi benchmark thực tế: `p50 / p95` cho cả **cache-hit** và **cache-miss**.
3. Sửa tài liệu: thay "< 15ms" thành "2-5ms (cache hit) / ~Xms (cache miss)".

**File cần sửa:** `data-transform/model/cubes/traffic/traffic_flow.yml`, `usecase.md`

---

## 🔵 NHÓM 3 — DÀI HẠN (Cải thiện kiến trúc, không cấp bách)

---

### [FIX-07] Thay Hash-trick vector bằng Real Embedding cho Qdrant

**Vấn đề:**
Vector trong Qdrant hiện được tạo bằng **hash token vào 64 bucket** — đây là BOW hash trick, không phải semantic embedding thực sự. Hai từ đồng nghĩa không cùng token sẽ cho vector hoàn toàn khác nhau.

**Hướng nâng cấp:**
- Dùng `sentence-transformers` (ví dụ: `paraphrase-multilingual-MiniLM-L12-v2`) để sinh embedding thực sự.
- Kích thước vector: 384 thay vì 64.
- Cho phép tìm kiếm semantic thực sự (vd: *"vận tốc"* ↔ *"tốc độ"*).

---

### [FIX-08] Đo Recall@K của Retriever như một eval riêng

**Vấn đề:**
RAG là bước lọc lossy — nếu miss measure đúng ở Top-K, toàn bộ pipeline sau không cứu được. Hiện chưa có eval set.

**Đề xuất:**
- Tạo tập test `retriever_eval.json`: 20-30 câu hỏi tiếng Việt + expected field name.
- Đo `Recall@5` (field đúng có xuất hiện trong Top-5 không?).
- Đặt ngưỡng tối thiểu: Recall@5 ≥ 95%.

---

### [FIX-09] Xây dựng fallback khi RAG confidence thấp

**Đề xuất:**
Nếu RRF score của kết quả Top-1 dưới ngưỡng (ví dụ < 0.01), thay vì tiếp tục pipeline với schema bị cắt hẹp, hệ thống nên:
- Mở rộng K (từ 5 → toàn bộ catalog), hoặc
- Trả `CLARIFICATION` ngay từ retriever layer.

---

### [FIX-10] Dense Score không nên hardcode keyword thủ công

**Vấn đề:**
Trong `retriever.py`, dense semantic score = chuỗi `if/elif` thủ công cho từng domain keyword. Không scale khi thêm domain mới.

**Hướng giải quyết:**
- Tích hợp embedding thực (FIX-07), bỏ hoàn toàn dense score thủ công.
- Hoặc ngắn hạn: đưa keyword list ra file config YAML để dễ bảo trì hơn.

---

## 📊 BẢNG ƯU TIÊN TỔNG HỢP

| # | Fix | Nhóm | Effort | Impact |
|---|---|---|---|---|
| FIX-01 | Xóa `dimensions` khỏi Happy Case benchmark | 🔴 Ngay | Thấp | Cao |
| FIX-02 | Thêm `traffic_flow.section_id` vào YAML | 🔴 Ngay | Thấp | Cao |
| FIX-03 | Sửa timezone UTC → UTC+7 | 🔴 Ngay | Thấp | Trung bình |
| FIX-04 | Thêm confidence threshold difflib | 🟡 Trước BV | Trung bình | Cao |
| FIX-05 | Làm rõ Repair Loop behavior trong docs | 🟡 Trước BV | Thấp | Trung bình |
| FIX-06 | Benchmark cache + thêm pre-aggregation | 🟡 Trước BV | Cao | Cao |
| FIX-07 | Real Embedding thay hash trick | 🔵 Dài hạn | Cao | Rất cao |
| FIX-08 | Eval set Recall@K cho Retriever | 🔵 Dài hạn | Trung bình | Rất cao |
| FIX-09 | Fallback khi RAG confidence thấp | 🔵 Dài hạn | Trung bình | Cao |
| FIX-10 | Bỏ hardcode dense keyword | 🔵 Dài hạn | Thấp | Trung bình |
