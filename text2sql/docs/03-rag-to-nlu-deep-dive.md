# Deep-dive: RAG Chunk → NLU Prompt → Tool Calling → Validation

> **Phạm vi:** Mô tả chi tiết toàn bộ pipeline xử lý một câu hỏi tự nhiên trong hệ thống SmartCity Text2SQL, từ lúc Cube `/meta` API được gọi cho đến khi `CubeQuery` được tạo ra và thực thi.
>
> **Câu hỏi mẫu xuyên suốt tài liệu này:** *"Chất lượng không khí AQI ở khu căn hộ ngày 26/7 thế nào?"*

---

## 1. Giai đoạn Khởi Động: Cube `/meta` API → Catalog

### 1.1 Khi nào `/meta` được gọi?

**Lazy init** — được gọi lần đầu khi request đến, rồi cache vào RAM suốt vòng đời process. Warmup startup event gọi `get_catalog()` sớm để warm cache, nhưng logic thực tế trong `get_catalog()` là:

```python
# server.py — get_catalog() với fallback
def get_catalog() -> Catalog:
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache  # cache hit, không gọi lại

    # Ưu tiên 1: Lấy live catalog từ Cube Core API
    try:
        live_cat = fetch_catalog(settings.cube_api_url, settings.cube_api_token)
        if live_cat and live_cat.cubes:
            _catalog_cache = live_cat
            return _catalog_cache
    except Exception:
        pass

    # Fallback: Đọc fixture JSON tĩnh nếu Cube Core chưa sẵn sàng
    meta_fixture = Path(".../tests/fixtures/cube_meta.json")
    if meta_fixture.exists():
        _catalog_cache = parse_catalog(json.loads(meta_fixture.read_text()))
        return _catalog_cache

    return Catalog(cubes=[])  # empty catalog nếu cả hai đều fail
```

### 1.2 Response từ Cube `/meta` (ví dụ cho cube `air_quality`)

```json
{
  "cubes": [
    {
      "name": "air_quality",
      "title": "Air Quality",
      "measures": [
        {
          "name": "air_quality.avg_aqi",
          "title": "Air Quality Chi so chat luong khong khi trung binh (AQI)",
          "shortTitle": "Chi so chat luong khong khi trung binh (AQI)",
          "description": "Chi so AQI trung binh. <50: Tot, 51-100: Trung binh, >100: Xau cho suc khoe",
          "type": "number",
          "aggType": "avg"
        },
        {
          "name": "air_quality.max_aqi",
          "title": "Air Quality Chi so AQI cao nhat",
          "description": "Gia tri AQI cao nhat ghi nhan duoc trong ky xem xet",
          "type": "number",
          "aggType": "max"
        }
      ],
      "dimensions": [
        {
          "name": "air_quality.section_id",
          "title": "Air Quality Ma khu vuc",
          "description": "Ma dinh danh phan khu (Can ho, Khu biet thu, TTTM)",
          "type": "string"
        },
        { "name": "air_quality.aqi_category",   "type": "string", "description": "..." },
        { "name": "air_quality.noise_category", "type": "string", "description": "..." },
        { "name": "air_quality.recorded_at",    "type": "time",   "description": "..." }
      ]
    }
  ]
}
```

> `parse_catalog()` đọc `description`, `title`, `type` từ response. Riêng `time` dimensions được tách ra thành `time_dimensions` trong `CatalogCube`.

`parse_catalog()` đọc response này và tạo object `Catalog` gồm các `CatalogCube` và `CatalogField` — nguồn sự thật duy nhất cho mọi bước sau.

---

## 2. RAG Layer: Tạo Chunk và Index vào Qdrant

### 2.1 Tạo Cube-level Macro Document (Mode CUBE_FIRST)

Với mỗi Cube trong Catalog, hệ thống tạo ra **một macro document** ("chunk") đại diện cho toàn bộ Cube:

#### Ví dụ chunk RAG của Cube `air_quality`

```
Cube Name: air_quality | Title: Air Quality |
Domain Keywords: chất lượng không khí aqi bụi mịn pm25 tiếng ồn ô nhiễm môi trường quiet noisy dBA |
Measures:
  air_quality.avg_aqi (Air Quality Chi so chat luong khong khi trung binh (AQI) - Chi so AQI trung binh. <50: Tot, 51-100: Trung binh, >100: Xau cho suc khoe),
  air_quality.max_aqi (Chi so AQI cao nhat - Gia tri AQI cao nhat ghi nhan duoc trong ky xem xet),
  air_quality.avg_pm25 (Nong do bui min PM2.5 trung binh (ug/m3) - Nong do hat bui min PM2.5 trung binh trong khong khi),
  air_quality.avg_noise_db (Do on trung binh (dBA) - Muc do tieng on trung binh do bang dBA. <50: Yen tinh, >70: On ao),
  air_quality.unhealthy_air_hours (So gio khong khi xau - Tong so gio co AQI > 100 (nguong Unhealthy). Moi ban ghi = 15 phut = 0.25 gio) |
Dimensions:
  air_quality.section_id (Ma khu vuc - Ma dinh danh phan khu (Can ho, Khu biet thu, TTTM)),
  air_quality.aqi_category (Phan loai chat luong khong khi - Phan loai AQI: GOOD (<=50), MODERATE (51-100), UNHEALTHY (>100)),
  air_quality.noise_category (Phan loai muc do on - Phan loai tieng on: QUIET (<50 dBA), MODERATE (50-70 dBA), NOISY (>70 dBA))
```

Code sinh ra chunk này (`retriever.py → _build_rich_documents()`):
```python
macro_text = (
    f"Cube Name: {cube.name} | Title: {cube.title} | "
    f"Domain Keywords: {cube_domain_text} | "
    f"Measures: {', '.join(m_descs)} | "
    f"Dimensions: {', '.join(d_descs)}"
)
```

Tổng cộng: **7 chunks** (1 per cube).

#### Ví dụ chunk RAG của Cube `traffic_flow` (để so sánh)

```
Cube Name: traffic_flow | Title: Traffic Flow |
Domain Keywords: giao thông tốc độ vận tốc số lượng xe ô tô xe máy kẹt xe ùn tắc di chuyển speed vehicle congestion overspeed |
Measures:
  traffic_flow.avg_speed (Toc do xe trung binh (km/h) - Toc do di chuyen trung binh cua cac phuong tien qua diem do),
  traffic_flow.avg_vehicle_count (Luong phuong tien trung binh - So phuong tien di qua diem do moi 5 phut),
  traffic_flow.congestion_rate (Ti le ket xe - Ti le % thoi gian co tinh trang ket xe (toc do < 20km/h)),
  traffic_flow.overspeed_count (So luong vuot toc do - Tong so lan phuong tien vuot toc do toi da cho phep) |
Dimensions:
  traffic_flow.section_id (Ma khu vuc - Ma dinh danh phan khu do luong),
  traffic_flow.camera_id (Ma camera - Ma dinh danh camera giao thong),
  traffic_flow.overspeed_flag (Co vuot toc do - True neu phuong tien di qua co toc do vuot gioi han)
```

### 2.2 Embedding chunk

```python
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
# Encode toàn bộ 7 chunks → 7 vector 384 chiều (float32)
cube_embs = embedding_engine.encode_batch([doc["text"] for doc in cube_documents])
```

### 2.3 Index vào Qdrant (2 HTTP calls — chỉ lúc startup)

```http
# Tạo (hoặc reset) collection — PUT ghi đè nếu đã tồn tại
PUT http://qdrant:6333/collections/cube_catalog
Body: {"vectors": {"size": 384, "distance": "Cosine"}}

# Upsert 7 points (1 per cube)
PUT http://qdrant:6333/collections/cube_catalog/points?wait=true
Body: {
  "points": [
    {
      "id": 1,
      "vector": [0.023, -0.112, 0.045, ...],  // 384 chiều
      "payload": {
        "cube_name": "air_quality",
        "text": "cube name: air_quality | title: air quality | ..."
      }
    },
    // ... 6 points còn lại
  ]
}
```

> **QUAN TRỌNG:** Qdrant **chỉ được dùng để index** lúc startup. Khi xử lý từng request, cosine similarity được tính **hoàn toàn in-memory** trên `self.cube_documents` — không có HTTP call nào đến Qdrant. BM25 cũng tính in-memory (token overlap). Qdrant hiện đóng vai trò **lưu trữ bền vững** cho vector, không phải query engine per-request.

---

## 3. Retrieval: Tìm Top-2 Cubes cho câu hỏi

Câu hỏi: *"Chất lượng không khí AQI ở khu căn hộ ngày 26/7 thế nào?"*

**Bước 1: BM25 Token Overlap**

```python
q_tokens = {"chất", "lượng", "không", "khí", "aqi", "khu", "căn", "hộ", ...}

# overlap với chunk air_quality:  6 tokens → BM25 score = 6/13 = 0.46  → rank #1
# overlap với chunk traffic_flow: 1 token  → BM25 score = 1/13 = 0.08  → rank #5
```

**Bước 2: Cosine Similarity (AI Embedding)**

```python
q_emb = encode_single("Chất lượng không khí AQI ở khu căn hộ ngày 26/7 thế nào?")

cosine(q_emb, air_quality_emb)        = 0.812  # rank 1
cosine(q_emb, city_health_index_emb)  = 0.423  # rank 2
cosine(q_emb, traffic_flow_emb)       = 0.198  # rank 3
```

**Bước 3: RRF Fusion (in-memory, không query Qdrant)**

```python
# RRF(d) = 1/(60 + rank_dense) + 1/(60 + rank_bm25)
# Tất cả tính trên self.cube_documents trong RAM — 0 HTTP call

air_quality:        1/(60+1) + 1/(60+1) = 0.03279  ← #1 WINNER
city_health_index:  1/(60+2) + 1/(60+3) = 0.03200  ← #2
traffic_flow:       1/(60+3) + 1/(60+5) = 0.03125  ← #3
```

**Kết quả:** Top-2 Cubes = `["air_quality", "city_health_index"]`

**Bước 4:** Feed **100% measures + dimensions** của 2 cubes này sang bước xây dựng prompt.

---

## 4. Hình Thành System Prompt NLU

`build_system_prompt(catalog, candidates)` ghép 2 phần:

### Phần 1: Rules (cố định)

```
# Vai trò (Role)
Trợ lý NLU Đô thị Thông minh. Nhiệm vụ: chuyển câu hỏi tự nhiên thành lời gọi hàm query_metrics.

# Quy tắc cốt lõi
1. CHỈ sử dụng measures/dimensions/timeDimensions có trong Catalog bên dưới.
2. Tất cả measures trong 1 lời gọi tool BẮT BUỘC thuộc về CÙNG một Cube.
3. TRÍCH XUẤT ĐỦ CHỈ SỐ: đưa TẤT CẢ chỉ số được đề cập vào measures.
4. CHỈ gán granularity="hour" khi câu hỏi hỏi rõ về giờ.
5. KHÔNG gán granularity khi hỏi tổng thể theo ngày/tháng.
6. Lọc thời gian BẮT BUỘC dùng timeDimensions, không dùng filters.
...
```

### Phần 2: Catalog Markdown (chỉ 2 cubes được RAG lọc ra)

```markdown
# Catalog (Danh mục chỉ số & chiều dữ liệu)

## Cube `air_quality` (Air Quality):
  * Measures (Chỉ số đo lường):
    - `air_quality.avg_aqi` (Air Quality Chi so chat luong khong khi trung binh (AQI)) - Chi so AQI trung binh. <50: Tot, 51-100: Trung binh, >100: Xau cho suc khoe
    - `air_quality.max_aqi` (Air Quality Chi so AQI cao nhat) - Gia tri AQI cao nhat ghi nhan duoc trong ky xem xet
    - `air_quality.avg_pm25` (Nong do bui min PM2.5 trung binh (ug/m3)) - Nong do hat bui min PM2.5...
    - `air_quality.avg_noise_db` (Do on trung binh (dBA)) - Muc do tieng on trung binh...
    - `air_quality.unhealthy_air_hours` (So gio khong khi xau) - Tong so gio co AQI > 100...
  * Dimensions (Chiều phân tích):
    - `air_quality.section_id` (Ma khu vuc) - Ma dinh danh phan khu (Can ho, Khu biet thu, TTTM)
    - `air_quality.aqi_category` (Phan loai chat luong khong khi) - Phan loai AQI: GOOD, MODERATE, UNHEALTHY
    - `air_quality.noise_category` (Phan loai muc do on) - Phan loai tieng on: QUIET, MODERATE, NOISY
  * TimeDimensions (Thời gian):
    - `air_quality.recorded_at` (Thoi diem ghi nhan) - Thoi diem ghi nhan do cam bien...

## Cube `city_health_index` (City Health Index):
  * Measures (Chỉ số đo lường):
    - `city_health_index.avg_livability_index` (Chi so dang song trung binh) - ...
    - ...
```

> `build_catalog_markdown()` (trong `prompt.py`) render: `` `{m.name}` ({m.title}){desc_str} `` trong đó `desc_str = f" - {m.description}"` nếu description không rỗng — nên description đầy đủ từ Cube YAML được đưa vào system prompt.

### User Message

```
[System]: {rules} + {catalog_2_cubes_markdown}

[User]:
Chất lượng không khí AQI ở khu căn hộ ngày 26/7 thế nào?

<runtime_context>
Hôm nay là 2026-08-12 (Năm 2026).
Nếu người dùng nêu ngày/tháng mà không ghi năm, BẮT BUỘC lấy năm 2026.
Nếu câu hỏi không nêu mốc thời gian, hệ thống sẽ mặc định lấy last 30 days.
</runtime_context>
```

---

## 5. Tool Calling

### Tool Schema gửi kèm

```json
{
  "type": "function",
  "function": {
    "name": "query_metrics",
    "description": "Truy vấn dữ liệu Smart City qua Cube. measures/dimensions phải lấy từ Catalog — không được bịa tên mới.",
    "parameters": {
      "type": "object",
      "properties": {
        "measures":       { "type": "array", "description": "... Gợi ý: air_quality.avg_aqi, air_quality.avg_pm25, ..." },
        "dimensions":     { "type": "array", "description": "... Gợi ý: air_quality.section_id, ..." },
        "filters":        { "type": "array", "items": { "properties": { "member": {}, "operator": { "enum": ["equals","notEquals","contains","gt","gte","lt","lte","set","notSet"] }, "values": {} } } },
        "timeDimensions": { "type": "array", "items": { "properties": { "dimension": { "description": "Một trong: air_quality.recorded_at, traffic_flow.recorded_at, ..." }, "dateRange": {}, "granularity": {} } } },
        "order":          { "type": "array" },
        "limit":          { "type": "integer", "minimum": 1, "maximum": 1000 }
      },
      "required": ["measures"]
    }
  }
}
```

### LLM Response (Tool Call Arguments)

```json
{
  "name": "query_metrics",
  "arguments": {
    "measures": ["air_quality.avg_aqi"],
    "dimensions": ["air_quality.section_id"],
    "filters": [
      {
        "member": "air_quality.section_id",
        "operator": "equals",
        "values": ["Khu căn hộ"]
      }
    ],
    "timeDimensions": [
      {
        "dimension": "air_quality.recorded_at",
        "dateRange": "2026-07-26"
      }
    ]
  }
}
```

---

## 6. Validation Pipeline (6 bước)

### Bước 1: Pydantic Schema Check

```python
query = CubeQuery.model_validate(raw)
# Kiểm tra kiểu dữ liệu: measures=list[str], limit=int, ...
```

### Bước 2: Validate Measures

```python
# "air_quality.avg_aqi" có trong catalog không? → OK ✅
```

### Bước 3: Validate Dimensions + Cross-Cube Guard

```python
target_cube = "air_quality"  # từ measures[0]

# Nếu LLM điền "traffic_flow.section_id":
# → ERROR: "Dimension 'traffic_flow.section_id' thuộc Cube khác với 'air_quality'.
#           Hãy dùng 'air_quality.section_id'."
```

### Bước 4: Validate Filters + Value Resolution

```python
# filter: member="air_quality.section_id", values=["Khu căn hộ"]

# _resolve_filter_values() chạy 2 lớp theo thứ tự:

# LỚP 1 — Alias Map (hardcoded trong sample_values.py, ưu tiên trước):
#   val_lower = "khu căn hộ"
#   alias_map["khu căn hộ"] = "Can ho"  ← HIT TRỰC TIẾP
#   → return ("Can ho", True)  # không cần chạy difflib

# LỚP 2 — difflib fuzzy-match trên sample_values.yaml (chỉ chạy nếu alias_map miss):
#   difflib.get_close_matches(value, allowed_values, n=1, cutoff=0.6)
#   Ví dụ: "Can hoo" → gần "Can ho" → match

# Kết quả:
#   → notes: "Đã hiểu giá trị 'Khu căn hộ' của 'air_quality.section_id' là 'Can ho'."
#   → f.values = ["Can ho"]  ← chuẩn hóa về giá trị thật trong DB
```

### Bước 5: Validate TimeDimensions + Auto-correction

```python
# dateRange = "2026-07-26" → không phải relative string chuẩn
# → notes: "dateRange '2026-07-26' không phải chuỗi chuẩn — Cube Core sẽ cố parse."

# Nếu LLM không điền timeDimensions:
# → auto-add: [{dimension: "air_quality.recorded_at", dateRange: "last 30 days"}]

# Nếu LLM điền nhầm cube khác (vd: "traffic_flow.recorded_at"):
# → auto-fix thành "air_quality.recorded_at"
```

### Bước 6: Validate Order + Limit Guard

```python
# order.field phải là measure/dimension đã chọn
# limit > 1000 → clamp về 1000
```

### Output sau Validation

```python
ValidationResult(
  ok=True,
  query=CubeQuery(
    measures=["air_quality.avg_aqi"],
    dimensions=["air_quality.section_id"],
    filters=[CubeFilter(member="air_quality.section_id", operator="equals", values=["Can ho"])],
    timeDimensions=[CubeTimeDimension(dimension="air_quality.recorded_at", dateRange="2026-07-26")]
  ),
  notes=["Đã hiểu giá trị 'Khu căn hộ' của 'air_quality.section_id' là 'Can ho'."]
)
```

---

## 7. Repair Loop (Nếu Validation Thất Bại)

Nếu `ok=False`, lỗi được đưa ngược lại cho LLM dưới dạng `tool_result`:

```
[user]      "Chất lượng không khí AQI ở khu căn hộ ngày 26/7 thế nào?"
[assistant] tool_call: query_metrics({measures: ["air_quality.avg_aqi"], dimensions: ["traffic_flow.section_id"], ...})
[tool]      "Tham số không hợp lệ:
             - Dimension 'traffic_flow.section_id' thuộc Cube khác với 'air_quality'...
             Hãy gọi lại duy nhất 1 tool call với tham số đã sửa."
[assistant] tool_call: query_metrics({measures: ["air_quality.avg_aqi"], dimensions: ["air_quality.section_id"], ...})
```

Tối đa `max_repair_attempts + 1 = 2` lần tổng.

---

## 8. Tóm Tắt Toàn Pipeline

```
╔══════════════════════ STARTUP (1 lần) ══════════════════════════════╗
║                                                                      ║
║  Cube /meta API (GET /cubejs-api/v1/meta)                           ║
║    │  Fallback: tests/fixtures/cube_meta.json nếu API fail          ║
║    ▼                                                                 ║
║  parse_catalog() → Catalog (7 Cubes, cached RAM)                    ║
║    │                                                                 ║
║    ▼                                                                 ║
║  _build_rich_documents()                                             ║
║  → 7 macro chunks (text = cube name + domain keywords +             ║
║                          measures(title+desc) + dimensions(title+desc))║
║    │                                                                 ║
║    ▼                                                                 ║
║  encode_batch() → 7 vectors 384 chiều (SentenceTransformer)        ║
║    │                                                                 ║
║    ▼                                                                 ║
║  Qdrant PUT /collections/cube_catalog/points (lưu bền vững)        ║
║  (Qdrant chỉ dùng để INDEX — không query lúc runtime)              ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝

╔══════════════════════ PER-REQUEST ══════════════════════════════════╗
║                                                                      ║
║  retrieve(question)  [hoàn toàn in-memory, 0 HTTP call]            ║
║  → BM25 token overlap ─┐                                            ║
║  → Cosine similarity   ├─ RRF Fusion → Top-2 Cubes                 ║
║    (trên self.cube_documents trong RAM)                              ║
║    │                                                                 ║
║    ▼                                                                 ║
║  build_system_prompt(catalog, top2_candidates)                      ║
║  = Rules (11 quy tắc) + Catalog Markdown (chỉ 2 cubes, có desc)    ║
║    │                                                                 ║
║    ▼                                                                 ║
║  LLM NLU 70B (tool_choice="auto")                                   ║
║  → tool_call: query_metrics({measures, dimensions, filters, ...})   ║
║    │                                                                 ║
║    ▼                                                                 ║
║  QueryValidator.validate()                                           ║
║  → Pydantic schema check                                            ║
║  → measure existence check                                          ║
║  → dimension cross-cube guard                                       ║
║  → filter: alias_map lookup → difflib fuzzy-match (fallback)        ║
║  → timeDimension: auto-correct cube + auto-default dateRange        ║
║  → order field check + limit guard (max 1000)                       ║
║    │                                                                 ║
║    ├── ok=False → Repair Loop (đưa lỗi về LLM, retry tối đa 2 lần)║
║    │                                                                 ║
║    └── ok=True → CubeQuery → CubeClient                            ║
║                → Cube Core REST API → SQL → StarRocks → Data       ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
```
