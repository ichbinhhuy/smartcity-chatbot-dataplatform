# 📘 PHÂN TÍCH CHUYÊN SÂU HAPPY CASE & CƠ CHẾ "TÌM RA" VS "ĐIỀN VÀO"

Tài liệu này tổng hợp bản chất của kịch bản lý tưởng (**Happy Case**), 4 mảnh ghép bắt buộc trong JSON `CubeQuery`, và bảng phân công trách nhiệm: **Thành phần nào TÌM RA (Discovery)** và **Thành phần nào ĐIỀN VÀO (Population/Format)** trong pipeline Text-to-SQL Smart City.

---

## 🌟 1. BẢN CHẤT CỦA HAPPY CASE

Trong bài toán Text-to-SQL Smart City, một câu hỏi thuộc kịch bản **Happy Case** (Single Intent - Đơn ý định) có các đặc điểm:
1. Câu hỏi tự nhiên của người dùng rõ ràng, chứa đầy đủ **3 trụ cột dữ liệu**: Chỉ số (Measure) + Địa danh (Filter/Dimension) + Thời gian (Time).
2. Toàn bộ Pipeline xử lý trôi chảy $100\%$ ngay từ lần thử đầu tiên (**Attempt 1**).
3. **Không** phát sinh lỗi cú pháp, **không** kích hoạt vòng lặp tự sửa lỗi (Repair Loop), **không** bị trượt RAG, và **không** cần phải hỏi lại người dùng.

---

## 🧩 2. CẤU TRÚC JSON CUBEQUERY TRONG HAPPY CASE

Để Cube Core (`/cubejs-api/v1/load`) có thể biên dịch ra câu SQL an toàn và thực thi trên Data Warehouse StarRocks, JSON `CubeQuery` bắt buộc phải có đầy đủ 4 mảnh ghép:

```json
{
  "measures": [
    "traffic_flow.avg_speed"
  ],
  "dimensions": [
    "traffic_flow.section_id"
  ],
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

---

## 📊 3. MA TRẬN TRÁCH NHIỆM: "CÁI GÌ TÌM RA" VS "CÁI GÌ ĐIỀN VÀO"

| Trường JSON `CubeQuery` | 🔍 Cái gì TÌM RA? (Search & Discovery) | ✍️ Cái gì ĐIỀN VÀO & CHUẨN HÓA? (Fill & Format) |
| :--- | :--- | :--- |
| **1. `measures`**<br>`"traffic_flow.avg_speed"` | **RAG Hybrid Search (Lớp 2)**<br>Quét Vector Qdrant + BM25 từ câu hỏi tiếng Việt (*"tốc độ trung bình"*) để tìm ra tên field chuẩn `traffic_flow.avg_speed`. | **LLM NLU 70B (Lớp 4)**<br>Đọc Top-K từ RAG truyền sang và điền `measures: ["traffic_flow.avg_speed"]` vào Tool Call Arguments. |
| **2. `dimensions`**<br>`"traffic_flow.section_id"` | **RAG Search (Lớp 2)** + **Code Auto-include**<br>RAG quét từ khóa địa danh. Nếu RAG bị sót, code `retriever.py` có rule **Auto-include** tự động nạp chiều `section_id` cho Cube được chọn. | **LLM NLU 70B (Lớp 4)**<br>Điền `dimensions: ["traffic_flow.section_id"]` để tạo ra lệnh `GROUP BY` phân khu trong SQL. |
| **3. `filters`**<br>`values: ["Khu biet thu"]` | **LLM NLU 70B (Lớp 4)**<br>Trích xuất trực tiếp từ câu hỏi tự nhiên của người dùng (lấy ra chuỗi Tiếng Việt có dấu `"Khu biệt thự"`). | **Alias Mapper & Validator (Lớp 5)**<br>Tra cứu `sample_values.py` bằng `difflib.get_close_matches`, quy đổi `"Khu biệt thự"` $\rightarrow$ **Điền chuỗi chuẩn DB `"Khu biet thu"`**. |
| **4. `timeDimensions`**<br>`dateRange: "today"` | **Runtime Context Builder (Lớp 1)**<br>Lấy mốc thời gian thực ISO 8601 tại thời điểm gọi API (Ví dụ: `2026-08-09T18:55:52+07:00`). | **LLM NLU 70B (Lớp 4)**<br>Đọc từ *"hôm nay"* + Runtime Context $\rightarrow$ **Điền `dateRange: "today"`** (hoặc dải ngày ISO cụ thể). |

---

## 🔄 4. TÓM TẮT LUỒNG CHUYỂN GIAO "TÌM RA" ──▶ "ĐIỀN VÀO"

```
[1. Context Builder] ──▶ "Đồng hồ" (Tạo ISO Timestamp: 2026-08-09)
         │
         ▼
[2. RAG Hybrid Search] ──▶ "Trinh thám" (Tìm tên Cột: avg_speed, section_id)
         │
         ▼
[3. LLM NLU 70B Engine] ──▶ "Thư ký" (Ghép tin từ Trinh thám + Đồng hồ để ĐIỀN VÀO JSON)
         │
         ▼
[4. Alias Mapper / Validator] ──▶ "Biên dịch viên DB" (Sửa "Khu biệt thự" -> "Khu biet thu")
         │
         ▼
[5. Cube Core REST API] ──▶ "Bộ dịch SQL" (Biên dịch JSON -> Câu SQL StarRocks)
```

---

## ⚡ 5. CƠ CHẾ CACHE ĐÁP ỨNG TỐC ĐỘ SIÊU NGHỎ (< 15ms)

Để Happy Case tập hợp đủ 4 mảnh ghép mà không gây trễ, hệ thống duy trì **3 tầng Cache**:

1. **In-Memory Catalog Cache (Lấy Mảnh 1 & 3)**:
   - Khi khởi động server, hệ thống nạp Full Catalog vào RAM + Qdrant Vector Store **1 lần duy nhất**.
   - Tốc độ trích xuất metadata: **$0\text{ ms}$**.
2. **Cube Pre-aggregations Cache (Lấy Mảnh 2)**:
   - Cube Core tính toán sẵn và lưu cache các kết quả gom nhóm chỉ số theo khung ngày/giờ.
   - Khi gọi API `/v1/load`, trúng Cache sẽ trả kết quả con số trong **$2 - 5\text{ ms}$** mà không cần quét lại bảng Fact thô trong StarRocks.
3. **Anchor Timestamp Cache (Lấy Mảnh 4)**:
   - Mốc thời gian ISO được tạo và lưu trong RAM request: **$0\text{ ms}$**.

---

## 📝 6. MINH HỌA ĐẦU VÀO / ĐẦU RA KẾT QUẢ HAPPY CASE

* **Câu hỏi đầu vào**: *"Tốc độ giao thông trung bình ở Khu biệt thự hôm nay là bao nhiêu?"*

* **Câu SQL do Cube Core tự biên dịch**:
  ```sql
  SELECT 
    section_id AS traffic_flow_section_id, 
    AVG(avg_speed_kmh) AS traffic_flow_avg_speed
  FROM starrocks_gold.fact_traffic
  WHERE section_id = 'Khu biet thu' 
    AND recorded_at >= '2026-08-09 00:00:00' 
    AND recorded_at <= '2026-08-09 23:59:59'
  GROUP BY 1;
  ```

* **Phản hồi hoàn chỉnh trên Web UI (LLM NLG 8B Output)**:
  > *"Tốc độ giao thông trung bình tại phân khu **Khu biệt thự** hôm nay (09/08/2026) là **45.82 km/h** (Giao thông thông thoáng, di chuyển thuận lợi)."*
