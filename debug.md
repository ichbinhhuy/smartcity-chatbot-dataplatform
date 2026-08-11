# SmartCity Text2SQL — Debug & Issue Report

> Tổng hợp phân tích từ code audit toàn diện hệ thống.
> Phân loại theo mức độ ưu tiên và thành phần ảnh hưởng.

---

## Tổng quan

| Thành phần | Số vấn đề | Nghiêm trọng 🔴 | Trung bình 🟡 | Cải thiện 🔵 |
|---|---|---|---|---|
| Cube Schema (.yml) | 9 | 5 | 3 | 1 |
| Pipeline Green Case | 4 | 1 | 3 | 0 |
| Python Code (Retriever/Validator) | 5 | 1 | 3 | 1 |
| **Tổng** | **18** | **7** | **9** | **2** |

---

## PHẦN 1 — Cube Schema Semantic Bugs

### 🔴 Issue #1 — faulty_lamp_count đếm lượt log thay vì cột đèn vật lý

**File**: data-transform/model/cubes/lighting/smart_lighting.yml

**Root cause**: Bảng fact_lighting ghi log 15 phút/bản ghi (96 bản/ngày/cột đèn).
type: sum cộng dồn số dòng log có status=FAULTY, không phải số cột đèn vật lý.

**Hệ quả đã xảy ra**: "Có bao nhiêu cột đèn hỏng ngày 26/7?" -> Chatbot trả lời 51 thay vì 3.

Fix:
  - name: faulty_lamp_count -> type: count_distinct, sql: "CASE WHEN status = 'FAULTY' THEN pole_id ELSE NULL END"
  - Thêm: faulty_event_count (type: sum) để giữ lại raw event count nếu cần

---

### 🔴 Issue #2 — faulty_lamp_pct tính tỷ lệ % sai ngữ nghĩa

**File**: data-transform/model/cubes/lighting/smart_lighting.yml

**Root cause**: AVG(CASE WHEN FAULTY THEN 100.0 ELSE 0.0 END) trả về % thời gian hỏng theo log,
không phải % cột đèn hỏng.

**Ví dụ sai**: 1/10 cột đèn hỏng 6/24 giờ -> kết quả 25% thay vì 10%.

Fix: Đổi tên thành faulty_time_pct để phản ánh đúng ngữ nghĩa.

---

### 🔴 Issue #3 — unhealthy_air_hours thổi vồng gấp 4 lần

**File**: data-transform/model/cubes/environment/air_quality.yml

**Root cause**: Cảm biến gửi dữ liệu 15 phút/lần = 0.25 giờ/bản ghi.
SUM(1) trên mỗi dòng log = đếm số lần đo, không phải số giờ thực tế.

**Ví dụ sai**: AQI > 100 kéo dài 2 giờ = 8 dòng log -> trả về 8 "giờ" thay vì 2 giờ.

Fix: sql: "CASE WHEN aqi > 100 THEN 0.25 ELSE 0 END" (mỗi bản ghi = 0.25 giờ)

---

### 🔴 Issue #4 — sum_livability_index phi nghĩa nghiệp vụ

**File**: data-transform/model/cubes/composite/city_health_index.yml

**Root cause**: livability_index là thang điểm 0-100. Cộng dồn điểm qua nhiều ngày/khu = vô nghĩa.

Fix: Xóa sum_livability_index, thêm min_livability_index và max_livability_index.

---

### 🔴 Issue #5 — city_health_index.date khai báo type: string thay vì type: time

**File**: data-transform/model/cubes/composite/city_health_index.yml

**Root cause**: date_key trong DB là kiểu DATE nhưng Cube khai báo type: string.
Cube không nhận diện đây là Time Dimension.

**Hệ quả cascade**: Validator trả về None cho _single_time_dimension_for ->
không áp default time filter -> query trả về toàn bộ lịch sử.

Fix: Đổi type: string -> type: time

---

### 🟡 Issue #6 — sum_power_per_pole là duplicate hoàn toàn của total_power_kwh

**File**: data-transform/model/cubes/lighting/smart_lighting.yml

**Root cause**: Cả hai đều là sql: power_kwh, type: sum.

Fix: Xóa sum_power_per_pole, giữ total_power_kwh.

---

### 🟡 Issue #7 — smart_parking.total_slots tên "total" nhưng dùng type: avg

**File**: data-transform/model/cubes/parking/smart_parking.yml

**Root cause**: total_slots ngụ ý SUM nhưng thực tế là AVG.

Fix: Đổi tên thành avg_slot_capacity.

---

### 🟡 Issue #8 — traffic_flow.avg_speed là Mean of Means (thống kê sai)

**File**: data-transform/model/cubes/traffic/traffic_flow.yml

**Root cause**: avg_speed_kmh đã là tốc độ trung bình pre-aggregate. Cube tính AVG(avg_speed_kmh) = Mean of Means.

Không thể fix hoàn toàn ở tầng Cube. Bổ sung description cảnh báo giới hạn này.

---

### 🔵 Issue #9 — Toàn bộ 7 file Schema thiếu title và description tiếng Việt

**Files**: Tất cả 7 file .yml

**Root cause**: Cube Meta API trả về tên kỹ thuật không có mô tả ngữ nghĩa.

**Hệ quả kép**:
1. LLM dễ chọn nhầm measure.
2. Retriever dựng embedding với title=None, description=None -> chuỗi "(None - None)" ->
   embedding vô nghĩa -> BM25 phải gánh toàn bộ -> giảm chất lượng Retrieval.

Fix: Bổ sung title và description tiếng Việt đầy đủ cho tất cả 7 file.

---

## PHẦN 2 — Green Case Pipeline Issues

### 🟡 Issue #10 — Alias Mapping không được truyền sang Phase NLG

**File**: app/server.py

**Root cause**: Validator dịch SEC_001 -> "Can ho" thành công nhưng NLG không biết mapping này.
NLG nhận câu hỏi gốc ("SEC_001") + JSON thô ("Can ho") -> tưởng JSON sai khu vực.

Fix: Truyền alias_mappings từ nlu_result.message vào NLG Prompt.

---

### 🟡 Issue #11 — LLM NLG nhận raw JSON thô, không được pre-process

**File**: app/server.py

**Root cause**: JSON thô có key dài phức tạp, có thể > 50 bản ghi.
Mô hình 8B dễ hallucination, bỏ sót dòng, đọc nhầm số.

Fix: Pre-process JSON trước NLG - rút gọn key, format > 20 dòng thành Markdown table.

---

### 🟡 Issue #12 — Nguy cơ lệch Múi giờ TimeZone UTC vs +07:00

**File**: data-transform/docker-compose.yml

**Root cause**: CUBEJS_TIMEZONE chưa được thiết lập.
dateRange: "2026-07-22" sẽ quét từ 00:00:00 UTC = 07:00:00 +07 -> lệch 7 tiếng.

Fix: Thêm environment: CUBEJS_TIMEZONE=Asia/Ho_Chi_Minh vào service cube.

---

### 🟡 Issue #13 — top_k_cubes=2 cố định không đủ cho câu hỏi tổng quan đa lĩnh vực

**File**: app/retrieval/retriever.py (line 242)

**Root cause**: Câu hỏi tổng quan cần 3+ Cubes nhưng Retriever luôn chọn đúng 2.

Fix: Thêm intent detection - nếu câu hỏi chứa "tổng quan", "báo cáo", "tất cả" -> top_k_cubes=3.

---

## PHẦN 3 — Python Code Issues

### 🔴 Issue #14 — Embedding index vô nghĩa vì title=None, description=None

**File**: app/retrieval/retriever.py (line 154-155)

**Root cause**: Khi Schema chưa có title/description:
  m_descs = [f"{m.name} ({m.title} - {m.description})" for m in cube.measures]
  -> "faulty_lamp_count (None - None)"

**Hệ quả**: Embedding vô nghĩa -> Retriever phụ thuộc hoàn toàn vào BM25 keyword match
-> miss các câu hỏi dùng từ đồng nghĩa tiếng Việt.

Fix: Tự động fix sau khi sửa Issue #9. Restart container để rebuild embedding.

---

### 🟡 Issue #15 — top_k=5 truyền vào retrieve() bị bỏ qua hoàn toàn

**File**: app/retrieval/retriever.py (line 235-242)

**Root cause**:
  def retrieve(self, question: str, top_k: int = 5) -> dict:
      return self._retrieve_cube_first(question, top_k_cubes=2)  # top_k bị bỏ qua!

---

### 🟡 Issue #16 — vietnamese_measure_terms hardcode sẽ lỗi thời sau khi fix Schema

**File**: app/retrieval/retriever.py (line 130-148)

**Root cause**: Dict này chứa tham chiếu cứng đến sum_power_per_pole (sẽ bị xóa).

Fix: Cập nhật vietnamese_measure_terms song song khi fix Schema.

---

### 🟡 Issue #17 — Validator xóa dimension sai Cube nhưng không trigger Repair Loop

**File**: app/nlu/validator.py (line 89-91)

**Root cause**: Validator tự xóa dimension không hợp lệ và chỉ ghi vào notes.
Người dùng không biết query bị mất chiều dữ liệu quan trọng.

Fix: Với các dimension quan trọng (section_id, pole_id), nên trigger repair thay vì tự xóa.

---

### 🔵 Issue #18 — notes từ Validator không được hiển thị ra UI

**File**: app/server.py

**Root cause**: nlu_result.message chứa notes hữu ích (alias mapping, default time range)
nhưng không được trả về trong JSON response /api/chat.

Fix: Thêm field "notes" vào API response cho FE hiển thị (tooltip, footnote).

---

## Tóm tắt ưu tiên xử lý

### Ưu tiên 1 — Fix ngay

| # | Vấn đề | File |
|---|---------|------|
| 1 | faulty_lamp_count: sum -> count_distinct | smart_lighting.yml |
| 3 | unhealthy_air_hours: x4 lần | air_quality.yml |
| 5 | city_health_index.date: string -> time | city_health_index.yml |
| 9 | Thiếu title/description toàn bộ Schema | 7 file .yml |
| 12 | TimeZone chưa set | docker-compose.yml |

### Ưu tiên 2 — Fix sớm

| # | Vấn đề | File |
|---|---------|------|
| 2 | faulty_lamp_pct đổi tên | smart_lighting.yml |
| 4 | sum_livability_index xóa bỏ | city_health_index.yml |
| 6 | sum_power_per_pole xóa duplicate | smart_lighting.yml |
| 7 | total_slots đổi tên | smart_parking.yml |
| 10 | Alias context không truyền sang NLG | server.py |
| 16 | vietnamese_measure_terms sync | retriever.py |

### Ưu tiên 3 — Cải thiện

| # | Vấn đề | File |
|---|---------|------|
| 8 | avg_speed Mean of Means - thêm description | traffic_flow.yml |
| 11 | NLG nhận raw JSON - thêm pre-processor | server.py |
| 13 | top_k_cubes=2 cố định | retriever.py |
| 15 | top_k=5 bị bỏ qua | retriever.py |
| 17 | Validator xóa dimension không trigger repair | validator.py |
| 18 | notes không hiển thị ra UI | server.py |

---

## Verification Checklist sau khi fix

```bash
# 1. Restart Cube Core để reload Schema
docker restart smartcity_cube && Start-Sleep 30

# 2. Restart Web để rebuild embedding index
docker restart smartcity_web && Start-Sleep 10
```

| Câu hỏi test | Kết quả cũ (Sai) | Kỳ vọng (Đúng) |
|---|---|---|
| Có bao nhiêu cột đèn hỏng ở khu căn hộ ngày 26/7? | 51 cột | 3 cột đèn |
| AQI xấu kéo dài bao nhiêu giờ ngày 25/7 ở TTTM? | Gấp 4x thực | Số giờ chính xác |
| Chỉ số sống tốt tuần này ở TTTM? | Không lọc được theo ngày | Trả về đúng kỳ |
| Tốc độ giao thông trung bình ở SEC_001? | Câu trả lời ngớ ngẩn | Câu trả lời rõ ràng |
| Tổng sức chứa bãi xe khu biệt thự? | 100 (avg nhầm thành total) | Đúng ngữ nghĩa |
