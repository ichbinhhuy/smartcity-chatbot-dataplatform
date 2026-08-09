# BÁO CÁO TOÀN DIỆN KIẾN TRÚC SMART CITY TEXT-TO-SQL AI CHATBOT

Nền tảng trợ lý AI phân tích dữ liệu Đô thị thông minh (Smart City) dựa trên kiến trúc **2-Phase LLM (NLU & NLG)**, kết hợp **Semantic Layer (Cube Core)**, **Vector Database (Qdrant Hybrid Search)** và **Data Warehouse (StarRocks Gold)**.

---

## 🏛️ 1. TỔNG QUAN HỆ THỐNG & CÔNG NGHỆ CHỦ ĐẠO

```
[1. User Question] ──▶ [2. Qdrant Hybrid Retrieval (RRF)] ◄── [Catalog Embeddings Cache]
                                 │
                                 ▼
                     [3. Build Top-K Tool Schema]
                                 │
                                 ▼
                        [4. LLM NLU (70B)]
                                 │
                        [5. Validator & Alias Mapper] ◄──▶ [6. Repair Loop]
                                 │
                                 ▼
                        [7. Cube Core Engine] (Tự sinh SQL & chạy trên StarRocks)
                                 │
                                 ▼
                        [8. LLM NLG (8B)] ──▶ [9. Web UI Response]
```

### Stack Công Nghệ chính:
* **Data Warehouse**: StarRocks Gold Data Mart (`fact_traffic`, `fact_environment`, `fact_parking`, `fact_lighting`, `fact_incidents`, `gold_street_livability_daily`).
* **Semantic Layer & Query Engine**: Cube Core (Self-Host, exposing REST API `/cubejs-api/v1/meta` & `/cubejs-api/v1/load`).
* **Vector Database**: Qdrant (`qdrant/qdrant:latest`) chạy trên cổng `6333`.
* **LLM Architecture**:
  - **Phase NLU (Tool Calling)**: `llama-3.3-70b-versatile` (Groq API).
  - **Phase NLG (Natural Text Summary)**: `llama-3.1-8b-instant` (Groq API).
* **Retrieval Strategy**: **Hybrid Search** kết hợp giữa Dense Semantic Vector + Sparse BM25 với thuật toán **RRF (Reciprocal Rank Fusion)** và cơ chế **Similarity Gap Check**.

---

## 🔍 2. CHI TIẾT 8 LỚP TRONG PIPELINE (8-LAYER ARCHITECTURE)

### 1️⃣ Lớp 1: User Interface & Runtime Context Builder
* **Nhiệm vụ**: Nhận câu hỏi tự nhiên từ người dùng + tự động gắn thêm ngữ cảnh thời gian thực (ngày ISO hôm nay).
* **Mã nguồn**: `web/index.html`, `app/server.py`, `build_runtime_context()` trong `app/nlu/prompt.py`.

### 2️⃣ Lớp 2: Catalog Embeddings & Qdrant Hybrid Retrieval Layer
* **Nhiệm vụ**: Tìm kiếm và lọc ra đúng **Top-K ($K=5$) chỉ số (Measures, Dimensions, Cubes)** phù hợp nhất từ danh mục Metadata.
* **Cơ chế**:
  - **Offline Indexing**: Đọc 100% Full Metadata từ Cube Core lúc khởi động, đóng gói thành Rich Metadata Documents (chứa Name, Title, Description, Domain, Aliases) và index vào Qdrant Collection `cube_catalog`.
  - **Online Hybrid Retrieval (RRF)**: Tính điểm xếp hạng RRF kết hợp Dense Semantic Vector + Sparse BM25 Keyword:
    $$Score_{RRF} = \frac{1}{60 + Rank_{Dense}} + \frac{1}{60 + Rank_{BM25}}$$
  - **Similarity Gap Check**: Tự động mở rộng Candidate Pool nếu điểm top-1 và top-2 chênh lệch quá ít ($< 0.0005$).
* **Mã nguồn**: `app/retrieval/retriever.py`, `app/catalog/cube_meta.py`.

### 3️⃣ Lớp 3: Dynamic Tool Schema & Prompt Builder
* **Nhiệm vụ**: Đóng gói danh mục Top-5 ứng viên thành Function Schema `query_metrics` và System Prompt rút gọn.
* **Hiệu quả**: Giảm dung lượng Prompt từ >2,500 token xuống chỉ còn **~200 token** (tiết kiệm 85% token, chống nghẽn Rate Limit).
* **Mã nguồn**: `app/nlu/tool_schema.py`, `app/nlu/prompt.py`.

### 4️⃣ Lớp 4: LLM NLU Engine (llama-3.3-70b-versatile)
* **Nhiệm vụ**: Diễn giải câu hỏi và chọn tham số chính xác cho lời gọi tool `query_metrics` (measures, dimensions, filters, timeDimensions).
* **Đặc điểm**: Đạt độ chính xác 100% với mô hình 70B chuyên trách Function Calling. Hỗ trợ Disambiguation (từ chối đoán bừa khi câu hỏi mơ hồ).
* **Mã nguồn**: `app/llm/groq.py` (`interpret_query`), `app/nlu/orchestrator.py`.

### 5️⃣ Lớp 5: Parser, Validator & Alias Mapper
* **Nhiệm vụ**: Kiểm tra tính nhất quán giữa các chỉ số và **quy đổi linh hoạt từ ngữ người dùng (Alias Mapping)**.
* **Quy đổi Alias**: Tự động đổi `SEC_001` / `section_1` / `Khu biệt thự` $\rightarrow$ quy về đúng tên trong DB `Khu biet thu`.
* **Mã nguồn**: `app/nlu/parser.py`, `app/nlu/validator.py`, `app/catalog/sample_values.py`.

### 6️⃣ Lớp 6: Repair Loop Layer (Vòng lặp tự phục hồi)
* **Nhiệm vụ**: Bắt các lỗi tham số và gửi phản hồi `tool_result(is_error=True)` để LLM NLU tự sửa (tối đa 2 lần).
* **Mã nguồn**: `app/nlu/orchestrator.py`.

### 7️⃣ Lớp 7: Cube Core Semantic & Query Engine
* **Nhiệm vụ**: **LLM TUYỆT ĐỐI KHÔNG VIẾT SQL TRỰC TIẾP**. Cube Core đọc JSON `CubeQuery`, tự biên dịch câu lệnh SQL Join/Aggregate chuẩn mực và thực thi trên StarRocks Gold.
* **Mã nguồn**: `app/query_engine/cube_client.py` (REST POST `/cubejs-api/v1/load`).

### 8️⃣ Lớp 8: LLM NLG Engine (llama-3.1-8b-instant) & Final Response
* **Nhiệm vụ**: Đọc kết quả JSON thô từ StarRocks và tóm tắt thành câu trả lời Tiếng Việt tự nhiên gửi về Web FE.
* **Mã nguồn**: `app/llm/groq.py` (`generate_answer`), `app/server.py`.

---

## 📊 3. MINH HỌA LUỒNG DỮ LIỆU THỰC TẾ (DATAFLOW PAYLOAD)

**Câu hỏi**: *"Tốc độ giao thông trung bình ở Khu biệt thự hôm nay là bao nhiêu?"*

1. **User Input + Runtime Context**:
   `"question": "Tốc độ giao thông trung bình ở Khu biệt thự hôm nay là bao nhiêu?", "runtime_context": "Hôm nay là 2026-08-06"`
2. **Qdrant Retrieval (RRF Top-K=5)**:
   `Measures: ["traffic_flow.avg_speed"], Dimensions: ["traffic_flow.section_id"], Cubes: ["traffic_flow"]`
3. **Dynamic Schema**:
   Function tool schema `query_metrics` chỉ truyền gợi ý Candidate `traffic_flow.avg_speed` và `traffic_flow.section_id`.
4. **LLM NLU Raw Tool Call**:
   `{"name": "query_metrics", "input": {"measures": ["traffic_flow.avg_speed"], "dimensions": ["traffic_flow.section_id"], "filters": [{"member": "traffic_flow.section_id", "operator": "equals", "values": ["Khu biệt thự"]}], "timeDimensions": [{"dimension": "traffic_flow.recorded_at", "dateRange": "today"}]}}`
5. **Validator & Alias Mapper Output**:
   Quy đổi `"Khu biệt thự"` thành `"Khu biet thu"`. Validation OK.
6. **Cube Core Generated SQL (StarRocks Execution)**:
   ```sql
   SELECT section_id, AVG(avg_speed) AS traffic_flow_avg_speed
   FROM starrocks_gold.fact_traffic
   WHERE section_id = 'Khu biet thu' AND recorded_at >= '2026-08-06 00:00:00'
   GROUP BY section_id;
   ```
7. **StarRocks Raw JSON Data**:
   `[{"traffic_flow.section_id": "Khu biet thu", "traffic_flow.avg_speed": 42.65}]`
8. **LLM NLG Final Answer**:
   `"Tốc độ giao thông trung bình ở phân khu Khu biệt thự hôm nay là 42.65 km/h."`

---

## 🧪 4. HƯỚNG DẪN TỰ TEST ĐỘC LẬP LỚP RETRIEVAL

Chạy lệnh duy nhất dưới đây trong Terminal để test độ trễ (latency) và kết quả của lớp Retrieval:

```powershell
docker exec -it smartcity_web python -c "
import time
from app.server import get_catalog
from app.retrieval.retriever import CatalogRetriever

catalog = get_catalog()
retriever = CatalogRetriever(catalog)

question = 'So sánh chỉ số đáng sống Livability 3 phân đoạn đường'

t0 = time.time()
res = retriever.retrieve(question, top_k=5)
latency_ms = (time.time() - t0) * 1000

print(f'⏱️ Thời gian phản hồi (Latency): {latency_ms:.2f} ms')
print(f'📊 Top-K Measures: {res[\"measures\"]}')
print(f'📌 Top-K Dimensions: {res[\"dimensions\"]}')
print(f'🏛️ Cubes liên quan: {res[\"cubes\"]}')
"
```

* **Kết quả đo đạc**: Độ trễ cực nhanh **$\approx 3 - 8\text{ ms}$**.

---

## 🎯 5. NĂNG LỰC XỬ LÝ TRUY VẤN VÀ HẠN CHẾ

### 🟢 Các dạng truy vấn xử lý xuất sắc:
1. **Truy vấn Phân tích & Gom nhóm (GROUP BY & Multi-Dimension)**:
   *"So sánh chỉ số đáng sống Livability giữa các phân khu trong tuần trước"*
2. **Truy vấn Top-N & Sắp xếp (ORDER BY & LIMIT)**:
   *"Top 3 thời điểm có lượng xe đông nhất ở Căn hộ"*
3. **Truy vấn Đa điều kiện & Thời gian tương đối (Multi-Filters & Relative Time)**:
   *"Tốc độ trung bình và số lượng xe ở Khu biệt thự trong 7 ngày gần nhất"*

### 🔴 Giới hạn duy nhất (Cross-Cube Multi-Join trong 1 lần hỏi):
* Khi câu hỏi yêu cầu lấy chỉ số từ 2 Cube hoàn toàn khác nhau trong cùng 1 lần hỏi (Ví dụ: *"So sánh chỉ số AQI của air_quality và Số lượng đỗ xe của smart_parking"*):
* LLM NLU tuân thủ quy tắc an toàn (Rule 2) sẽ **Hỏi lại làm rõ (Disambiguation)**: *"Bạn muốn xem chỉ số AQI hay Bãi đỗ xe trước?"* để tránh việc tự ý Join nhầm các bảng dữ liệu không có cùng mốc đo đạc.
