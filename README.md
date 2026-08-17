# BÁO CÁO ĐỀ TÀI THỰC TẬP
# XÂY DỰNG TEXT-TO-SQL LLM AGENT CÙNG SEMANTIC LAYER CHO NỀN TẢNG DỮ LIỆU SMART CITY

**Người thực hiện:** Nguyễn Bình Huy, Vũ Đình Phượng

**Đơn vị thực tập:** VSF-BĐC-SC-DLAI  

Chương trình AI thực chiến, Batch 02  

---

## 📑 MỤC LỤC
1. [Tổng quan đề tài](#1-tổng-quan-đề-tài)
   - [1.1 Chi tiết đề tài và kế hoạch sprint](#11-chi-tiết-đề-tài-và-kế-hoạch-sprint)
   - [1.2 Mục tiêu đề tài](#12-mục-tiêu-đề-tài)
2. [Bối cảnh nghiệp vụ và đề xuất giải pháp](#2-bối-cảnh-nghiệp-vụ-và-đề-xuất-giải-pháp)
   - [2.1 Làm rõ bài toán và dữ liệu](#21-làm-rõ-bài-toán-và-dữ-liệu)
   - [2.2 Đề xuất giải pháp kiến trúc](#22-đề-xuất-giải-pháp-kiến-trúc)
3. [Thiết kế và triển khai hệ thống](#3-thiết-kế-và-triển-khai-hệ-thống)
   - [3.1 Tổng quan Tech Stack và môi trường công nghệ](#31-tổng-quan-tech-stack-và-môi-trường-công-nghệ)
   - [3.2 Data Transformation](#32-data-transformation)
   - [3.3 Text-to-SQL Semantic Chatbot](#33-text-to-sql-semantic-chatbot)
4. [Kết quả đạt được](#4-kết-quả-đạt-được)
   - [4.1 Tiêu chí và Phương pháp đánh giá (Evaluation Framework)](#41-tiêu-chí-và-phương-pháp-đánh-giá-evaluation-framework)
   - [4.2 Định hướng thiết kế Bộ dữ liệu Kiểm thử (Traffic Light Model)](#42-định-hướng-thiết-kế-bộ-dữ-liệu-kiểm-thử-traffic-light-model)
5. [Kết luận và hướng phát triển](#5-kết-luận-và-hướng-phát-triển)

---

## 1. TỔNG QUAN ĐỀ TÀI

### 1.1 Chi tiết đề tài và kế hoạch sprint
* **Tên project:** Xây dựng Text-to-SQL LLM Agent cùng Semantic Layer cho nền tảng dữ liệu Smart City

| Sprint | Các nhiệm vụ trọng tâm |
|---|---|
| **Sprint 1** | • Setup data warehouse mẫu + ERD<br>• Thiết kế & xây semantic layer v1 (metrics, dimensions, relationships)<br>• Xây engine convert semantic query → SQL<br>• Thiết kế kiến trúc LLM function-calling (Nature Language → structured query)<br>• Setup chat UI khung + backend API<br>• Viết prompt v1 + test map câu hỏi đơn giản |
| **Sprint 2** | • Mở rộng semantic model (derived metrics, time comparison, join phức tạp)<br>• Validation layer + caching + test suite cho SQL generation<br>• Xử lý câu hỏi ambiguous + multi-turn conversation<br>• Hoàn thiện UI (chart, hiển thị SQL) + error handling |
| **Sprint 3** | • Guardrails an toàn (giới hạn query, security cơ bản), tối ưu performance<br>• Viết docs kỹ thuật<br>• Xây eval framework, đo accuracy/success rate<br>• Feedback mechanism, polish UX, user guide |

### 1.2 Mục tiêu đề tài
* **Tìm hiểu nghiệp vụ và kiến trúc nền tảng:** Nắm bắt cách vận hành của các tầng dữ liệu hiện đại như Near-Realtime OLAP, Data Warehouse, Semantic Layer và các công cụ tương đương.
* **Đề xuất giải pháp Text-to-SQL bằng LLM Agent kết hợp Semantic Layer cho Smart City:** Xây dựng chatbot AI giúp người dùng truy vấn dữ liệu bằng ngôn ngữ tự nhiên an toàn và chính xác.
* **Đánh giá kết quả thực nghiệm và đề xuất hướng tối ưu:** Đo lường độ chính xác của các câu truy vấn được sinh ra, đưa ra nhận xét đề xuất giải pháp cải tiến/ mở rộng hệ thống trong tương lai.

---

## 2. BỐI CẢNH NGHIỆP VỤ VÀ ĐỀ XUẤT GIẢI PHÁP

### 2.1 Làm rõ bài toán và dữ liệu 
Để dễ hình dung hơn, bài toán được định nghĩa chi tiết như sau:
* Xây dựng **data pipeline** và **chatbot** cho một tuyến đô thị gồm 3 đoạn đường:
  - **Đoạn 1 (`section_1`):** Cổng chính & TTTM
  - **Đoạn 2 (`section_2`):** Khu Căn hộ
  - **Đoạn 3 (`section_3`):** Khu Biệt thự

Mỗi đoạn đường được trang bị hệ thống hạ tầng IoT và thu thập các nguồn dữ liệu như sau:

| STT | Tên dữ liệu | Nguồn thu thập | Định dạng dữ liệu | Tần suất & Mô tả dữ liệu |
|---|---|---|---|---|
| 1 | **Lưu lượng giao thông** (`traffic`) | 3 camera/ đoạn | Nested JSON (`.json`) | 15 phút/lần: Đo lưu lượng xe, vận tốc trung bình (km/h), số lần vi phạm quá tốc độ. |
| 2 | **Bãi đỗ xe thông minh** (`parking`) | 1 trạm gateway lorawan/ đoạn | JSON nhẹ qua MQTT (`.json`) | 15 phút/lần: Cập nhật tổng số ô đỗ và số ô hiện đang có xe đỗ. |
| 3 | **Chất lượng môi trường** (`environment`) | 1 trạm quan trắc môi trường/ đoạn | Nested API JSON (`.json`) | 1 giờ/lần: Đo chỉ số không khí AQI, nồng độ bụi mịn PM2.5 ($\mu\text{g/m}^3$), độ ồn (dBA). |
| 4 | **Chiếu sáng thông minh** (`lighting`) | 10 cột đèn/ đoạn | XML (`.xml`) | 15 phút/lần: Đo điện năng tiêu thụ (kWh), trạng thái bóng đèn (`OK` / `FAULTY`). |
| 5 | **Sự cố** (`incidents`) | Nhật ký ca trực Cảnh sát giao thông | CSV (`.csv`) | Hàng tuần: Ghi nhận sự cố trên đoạn đường. |

> **Quy cách nạp dữ liệu:** Toàn bộ dữ liệu được nạp dưới dạng **batch streaming** định kỳ theo tuần. Tập dữ liệu chuẩn hiện tại được giả định thu thập trong 7 ngày từ **21/07/2026 đến 28/07/2026**.
>
>Dữ liệu thô ban đầu được mô phỏng có chủ đích 3 dạng dữ liệu "bẩn" phổ biến thực tế: **(1) Lỗi cấu trúc** (thiếu thẻ/trường bắt buộc), **(2) Lỗi vi phạm nghiệp vụ** (giá trị âm, vượt ngưỡng) và **(3) Lỗi trùng lặp bản ghi**.

---

### 2.2 Đề xuất giải pháp kiến trúc

Với mục tiêu giải quyết bài toán chatbot hỏi đáp dữ liệu đô thị thông minh chính xác, an toàn và tối ưu hiệu năng, nhóm đề xuất kiến trúc **Text-to-Semantic-to-SQL**, kết hợp LLM Agent và tầng Semantic Layer trung gian qua Cube Core.

Việc xây dựng Semantic Layer thay vì cho LLM viết SQL trực tiếp nhằm ép LLM chỉ được đóng vai trò trích xuất tham số vào một cấu trúc JSON đã được định nghĩa sẵn. Việc dịch ra câu lệnh SQL đúng 100% được giao hoàn toàn cho Semantic Engine tất định xử lý, tránh việc LLM bị ảo giác (hallucination) tự bịa tên bảng, cột hoặc công thức tính toán, dẫn đến kết quả truy vấn không chính xác và thiếu đồng nhất.

Để giải quyết bài toán Text-to-SQL, hiện có 3 hướng tiếp cận công nghệ chính:
* **Direct Text-to-SQL (Vanna.ai, LangChain SQL):** Đưa trực tiếp cấu trúc DB vào prompt để LLM tự viết SQL. Cách này làm nhanh nhưng rủi ro cao vì LLM dễ bị ảo giác cú pháp, sai lệch công thức.
* **Giải pháp đóng gói sẵn All-in-One (như Wren AI):** Tích hợp sẵn toàn bộ từ giao diện Chat, AI Agent đến tầng Semantic. Ưu điểm là dùng được ngay và dễ thao tác với non-tech, nhưng nhược điểm là hệ thống khép kín, rất khó tùy chỉnh thuật toán AI xử lý tiếng Việt riêng hoặc tái sử dụng dữ liệu cho các hệ thống khác.
* **Tầng Semantic độc lập (như Cube Core):** Tách rời hoàn toàn phần xử lý dữ liệu ngữ nghĩa khỏi giao diện. Giải pháp này cho phép hệ thống làm chủ toàn bộ tầng AI Agent phía trên, đồng thời cung cấp API chuẩn cho cả Chatbot và các công cụ BI truyền thống (Tableau, Superset, Power BI…). Cube hỗ trợ tối ưu truy vấn lớn với cơ chế pre-aggregations, cùng với hệ sinh thái lớn sẽ giúp dễ tùy chỉnh và tránh bị vendor lock-in. **Đây là giải pháp được lựa chọn cho hệ thống hiện tại.**

---

## 3. THIẾT KẾ VÀ TRIỂN KHAI HỆ THỐNG

### 3.1 Tổng quan Tech Stack và môi trường công nghệ

| Phân tầng kiến trúc | Thành phần chức năng | Công nghệ sử dụng | Vai trò trong hệ thống |
|---|---|---|---|
| **Application Layer** | **Giao diện & API Server** | HTML, CSS, JavaScript, FastAPI | Cung cấp giao diện chat, vẽ biểu đồ và xử lý luồng gọi API |
| **Semantic & Chatbot Layer** | **Mô hình ngôn ngữ lớn (LLM)** | OpenAI GPT-4o-mini | Đảm nhiệm các tác vụ NLU (hiểu ý định câu hỏi) và NLG (tổng hợp câu trả lời) |
| | **Semantic Layer** | Cube Core | Định nghĩa chỉ số nghiệp vụ và tự động chuyển đổi sang câu lệnh SQL |
| | **Tìm kiếm ngữ nghĩa (Semantic Search)** | Qdrant (BM25 + `paraphrase-multilingual-MiniLM-L12-v2`) | Đánh chỉ mục và tìm kiếm nhanh bảng dữ liệu phù hợp với câu hỏi |
| | **Quản lý phiên hội thoại** | Redis / InMemory | Lưu lịch sử tương tác và hỗ trợ hỏi đáp nhiều lượt (Multi-turn) |
| **Data & Storage Layer** | **NRT OLAP** | StarRocks | Lưu trữ dữ liệu sạch và thực thi truy vấn báo cáo tốc độ cao |
| | **Bảng dữ liệu Lakehouse** | Iceberg + Nessie | Định dạng bảng dữ liệu mở, hỗ trợ quản lý lịch sử dữ liệu |
| | **Object Storage** | MinIO S3 | Nơi chứa các tệp dữ liệu thô ban đầu và dữ liệu tầng Bronze |
| | **Làm sạch & Chuẩn hóa dữ liệu** | dbt | Khử trùng lặp, chuẩn hóa định dạng và kiểm tra chất lượng dữ liệu |
| | **Thu thập dữ liệu thô (Ingestion)** | NiFi | Đẩy dữ liệu vào hệ thống và tự động phân loại tệp lỗi |
| | **Điều phối quy trình (Orchestration)** | Apache Airflow | Lập lịch tự động chạy các luồng xử lý dữ liệu định kỳ |
| **Evaluation & Observability Layer** | **Kiểm thử & Đánh giá chất lượng** | DeepEval, Langfuse | Đo lường độ chính xác câu trả lời và theo dõi, giám sát luồng chạy LLM |

---

### 3.2 Data Transformation
* **Input:** Dữ liệu thô thu thập từ 5 nguồn ngoại vi (Camera AI giao thông, Cảm biến bãi đỗ xe LoRaWAN, Trạm quan trắc môi trường, Hệ thống chiếu sáng SCADA, Nhật ký sự cố CSGT) dưới các định dạng JSON, XML, CSV.
* **Output:** Dữ liệu sạch, chuẩn hóa và đã được tiền tính toán chỉ số (Pre-computed / Roll-up) theo mô hình Star Schema (1 Dim + 6 Fact Marts) lưu trữ trên StarRocks Gold sẵn sàng phục vụ Semantic Layer.

Xây dựng pipeline xử lý dữ liệu theo kiến trúc Medallion (Data Lakehouse) nhằm làm sạch và chuẩn hóa dữ liệu đa nguồn từ Landing Zone đến kho dữ liệu phân tích:
* **Điều phối quy trình (Apache Airflow):** Đóng vai trò là trung tâm điều phối (Orchestration), tự động hóa toàn bộ chu trình xử lý dữ liệu theo lịch trình định kỳ (tuần), kích hoạt lần lượt các task từ thu thập dữ liệu đến khi hoàn tất nạp tầng Gold.
* **Thu thập & Phân loại (Apache NiFi):** Tiếp nhận dữ liệu ngoại vi đa nguồn (JSON, XML, CSV), kiểm tra tính hợp lệ về cấu trúc và tự động chuyển hướng các tệp lỗi sang Dead Letter Queue (DLQ tại `quarantine/`).
* **Landing Zone (MinIO S3):** Lưu trữ tập trung các tệp dữ liệu thô hợp lệ vừa được đẩy về hệ thống tại `s3://landing-zone/`.
* **Bronze Layer (Raw Storage):** Nạp toàn bộ dữ liệu thô vào các bảng **Apache Iceberg** (định dạng Parquet nén) quản lý bởi **Nessie Catalog**, kết hợp **StarRocks** để bảo toàn 100% lịch sử phục vụ kiểm toán (Audit Trail).
* **Silver Layer (Clean & Trusted Data):** Ứng dụng **dbt (Chặng 1)** thực hiện các nhiệm vụ làm sạch cốt lõi:
  - Chuẩn hóa định dạng thời gian sang kiểu chuẩn `DATETIME`.
  - Khử trùng lặp dữ liệu do mạng retry bằng `ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY ingestion_time DESC) = 1`.
  - Chạy bộ kiểm định chất lượng (dbt Data Quality Tests) để phát hiện vi phạm nghiệp vụ (giá trị âm, vượt ngưỡng) và gắn cờ trạng thái `record_status: VALID / INVALID`.
* **Gold Layer (OLAP Data Marts):** Ứng dụng **dbt (Chặng 2)** lọc dữ liệu sạch (`WHERE record_status = 'VALID'`), thực hiện các tác vụ tiền tính toán và mô hình hóa thành kho dữ liệu **Star Schema** trong StarRocks gồm **6 bảng Fact** và **1 bảng Dimension**:
  - **1 Bảng Dimension chung:** `dim_section` (thông tin 3 phân đoạn tuyến đường).
  - **6 Bảng Fact chuyên biệt:** `fact_traffic` (Giao thông), `fact_parking` (Bãi đỗ), `fact_environment` (Môi trường), `fact_lighting` (Chiếu sáng), `fact_incident` (Sự cố) và `fact_street_livability_daily` (Chỉ số tổng hợp composite hàng ngày).
  - **Tiền tính toán & Tổng hợp sẵn (Pre-computation / Roll-up):** `dbt` tính toán sẵn chỉ số phức hợp hàng ngày từ 5 nguồn dữ liệu và tổng hợp số liệu theo các khung thời gian (15 phút, 1 giờ, 1 ngày), giúp giảm tải tính toán cho kho dữ liệu và tối ưu tốc độ phản hồi cho Semantic Layer (Cube Core).

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        DATA PIPELINE ARCHITECTURE (MEDALLION FLOW)                     │
└────────────────────────────────────────────────────────────────────────────────────────┘

 [1. NGUỒN DỮ LIỆU THÔ]           [2. INGESTION ENGINE]            [3. MINIO S3 LAKEHOUSE]
 ┌──────────────────────┐         ┌──────────────────────┐         ┌──────────────────────┐
 │ • Traffic (JSON)     │ ──────► │ • Apache NiFi        │ ──────► │ • s3://landing-zone/ │
 │ • Parking (MQTT)     │ (Batch) │ • Dead Letter Queue  │ (Valid) │ • s3://bronze/       │
 │ • Environment (API)  │         │   (quarantine/ lỗi)  │         │   (Iceberg + Nessie) │
 │ • Lighting (XML)     │         └──────────────────────┘         └──────────┬───────────┘
 │ • Incidents (CSV)    │                                                     │
 └──────────────────────┘                                                     │ dbt run (Chặng 1)
                                                                              ▼
 [6. CUBE CORE SEMANTIC]          [5. GOLD LAYER (OLAP)]           [4. SILVER LAYER (DQ)]
 ┌──────────────────────┐         ┌──────────────────────┐         ┌──────────────────────┐
 │ • Cube.js Semantic   │ ◄────── │ • starrocks_gold     │ ◄────── │ • starrocks_silver   │
 │ • Unified Metrics    │  (SQL   │ • 1 Dim + 6 Fact     │ (Filter │ • Dedup (rn=1)       │
 │ • Sub-second Query   │  Query) │ • Pre-computed KPIs  │  VALID) │ • Cast Datetime & DQ │
 └──────────────────────┘         └──────────────────────┘         └──────────────────────┘
```

---

### 3.3 Text-to-SQL Semantic Chatbot
* **Input:** Câu hỏi ngôn ngữ tự nhiên (tiếng Việt) từ người dùng về các chỉ số đô thị thông minh (ví dụ: *"Hôm nay đoạn 1 có bao nhiêu xe vi phạm quá tốc độ?"*).
* **Output:** Văn bản phân tích số liệu súc tích, giải đáp chính xác câu hỏi dựa trên dữ liệu truy vấn từ StarRocks Gold.

```
 [PRE-BUILT RAG BASE]
 ┌──────────────────────┐
 │ • Ingestion & Chunk  │
 │ • Dense Embedding    │
 │ • BM25 Indexing      │
 └──────────┬───────────┘
            │
            ▼ (Knowledge Data)
 ┌────────────────────────────────────────────────────────┐
 │ 1. CONTEXT BUILDER: Gắn mốc ngày ISO vào câu hỏi       │
 └──────────────────────────┬─────────────────────────────┘
                            │ (User Query + ISO Date)
                            ▼
 ┌────────────────────────────────────────────────────────┐
 │ 2. HYBRID RAG RETRIEVAL: Lọc Top-K Cube & Check OOD    │
 └──────────────────────────┬─────────────────────────────┘
                            │ (Top-K Cubes Metadata)
                            ▼
 ┌────────────────────────────────────────────────────────┐
 │ 3. DYNAMIC TOOL GENERATION: Sinh Tool Schema rút gọn   │
 └──────────────────────────┬─────────────────────────────┘
                            │ (Tool Schema query_metrics)
                            ▼
            ┌───────────────► ┌─────────────────────────────────────────┐
            │                 │ 4. LLM NLU ENGINE (GPT-4o-mini)         │
            │                 │    Diễn giải ý định -> Function Call    │
            │                 └────────────────────┬────────────────────┘
            │                                      │ (Function Call JSON)
 (Repair    │                                      ▼
  max 2x)   │                 ┌─────────────────────────────────────────┐
            │                 │ 5. VALIDATOR & ALIAS MAPPER             │
            │                 │    Cross-Cube Check & Chuẩn hóa thực thể│
            │                 └──────────┬──────────────────┬───────────┘
            │                            │                  │
            │ (Lỗi tham số is_error)     │                  │ (JSON Query hợp lệ)
            └────────────────────────────┘                  │
            ┌─────────────────────────────────────────┐     │
            │ 6. SELF-CORRECTION REPAIR LOOP          │     │
            │    Bắt lỗi và gửi phản hồi để LLM sửa   │     │
            └─────────────────────────────────────────┘     │
                                                            ▼
 ┌────────────────────────────────────────────────────────┐
 │ 7. CUBE CORE SEMANTIC ENGINE: Kiểm tra Cache & Sinh SQL│
 └──────────────────────────┬─────────────────────────────┘
                            │ Push-down SQL ──► ┌─────────────────────────┐
                            │                   │ 8. STARROCKS GOLD DW    │
                            │ ◄── Data Records ─│    Thực thi SQL OLAP    │
                            ▼                   └─────────────────────────┘
 ┌────────────────────────────────────────────────────────┐
 │ 9. LLM NLG ENGINE: Tổng hợp văn bản phân tích trả lời  │
 └────────────────────────────────────────────────────────┘
```

#### 🔍 Chi tiết các bước xử lý:

1. **Context Builder:** Gắn mốc thời gian thực tế (ISO Date, ví dụ: `2026-08-14`) vào câu hỏi người dùng nhằm giúp LLM xác định chính xác ngữ cảnh thời gian tương đối (*"hôm nay"*, *"tuần này"*), tránh nhầm lẫn mốc dữ liệu thực tế.
2. **Hybrid RAG Retrieval:** Kết hợp tìm kiếm vector dày (Dense Vector `paraphrase-multilingual-MiniLM-L12-v2`) và vector thưa (Sparse BM25 trên Qdrant) để trích xuất Top-K Cube phù hợp, đồng thời kiểm tra ngưỡng Cosine Similarity nhằm lọc chính xác bảng dữ liệu liên quan và tự động từ chối câu hỏi ngoài phạm vi (*Out-of-domain Guardrail*).
3. **Dynamic Tool Generation:** Tự động sinh Function Calling Tool Schema `query_metrics` thu gọn chỉ chứa danh mục measures/dimensions của Top-K Cube, giúp tối ưu hóa kích thước Prompt, tiết kiệm token và tránh việc LLM bị quá tải thông tin.
4. **LLM NLU Engine (GPT-4o-mini):** Diễn giải ý định câu hỏi của người dùng thành tham số gọi hàm có cấu trúc JSON (`measures`, `dimensions`, `filters`, `timeDimensions`) nhằm chuyển đổi ngôn ngữ tự nhiên thành cấu trúc máy hiểu được mà không cần sinh SQL tự do.
5. **Validator & Alias Mapper:** 
   - Kiểm tra tính hợp lệ nghiệp vụ và ràng buộc một Cube duy nhất (*Cross-Cube Guard*).
   - Tự động chuẩn hóa thực thể người dùng nhập (Ví dụ: *"khu biệt thự"* $\rightarrow$ `"Khu biet thu"`, *"đèn hỏng"* $\rightarrow$ `"FAULTY"`).
   - Tự động gán mặc định thời gian `last 30 days` nếu câu hỏi thiếu mốc lọc.
   Toàn bộ quá trình này bảo đảm câu truy vấn an toàn, đúng cú pháp nghiệp vụ và khớp tuyệt đối với giá trị thực trong cơ sở dữ liệu.
6. **Self-Correction Repair Loop:** Bắt các lỗi sai tên trường/sai kiểu dữ liệu từ Validator và gửi phản hồi `tool_result(is_error=True)` để LLM tự động sửa lại (tối đa 2 lần), giúp hệ thống tự sửa lỗi linh hoạt và giảm thiểu tối đa tỷ lệ truy vấn thất bại.
7. **Cube Core Semantic Engine:** Nhận JSON Structured Query hợp lệ, kiểm tra bộ nhớ đệm tiền tính toán (*Pre-aggregations Cache*) và tự động biên dịch sang câu lệnh SQL tối ưu theo chuẩn StarRocks, đóng vai trò là nguồn chân lý duy nhất (*Single Source of Truth*) giúp sinh SQL chuẩn xác và tăng tốc độ truy vấn.
8. **StarRocks Gold Data Marts:** Thực thi câu lệnh SQL vừa biên dịch trực tiếp trên các bảng Fact/Dimension sạch ở tầng Gold và trả về tập bản ghi dữ liệu (*Data Records*), cho phép tính toán và quét số liệu phân tích với tốc độ cực cao (sub-second).
9. **LLM NLG Engine (GPT-4o-mini):** Tiếp nhận dữ liệu số liệu JSON từ Data Warehouse và tổng hợp thành câu trả lời phân tích bằng văn bản tiếng Việt tự nhiên, giúp diễn đạt kết quả số liệu kỹ thuật thành thông tin giải đáp trực quan, súc tích và dễ hiểu cho người dùng cuối.

---

## 4. KẾT QUẢ ĐẠT ĐƯỢC

### 4.1 Tiêu chí và Phương pháp đánh giá (Evaluation Framework)

Để đánh giá toàn diện hệ thống Text-to-Semantic-to-SQL Chatbot một cách khách quan, chính xác và bám sát thực tế nghiệp vụ, nhóm xây dựng khung đánh giá tập trung vào **4 chỉ số cốt lõi**, bao quát từ tầng hiểu ý định (NLU), tầng sinh câu trả lời (NLG), tầng an toàn/định tuyến (Guardrail/Clarification) cho đến hiệu năng vận hành (Performance):

| # | Chỉ số đánh giá | Tầng đo lường | Công cụ sử dụng | Mục tiêu đo lường | Ngưỡng kỳ vọng (Target) |
| :-: | :--- | :--- | :--- | :--- | :-: |
| **1** | **Semantic Exact Match** | NLU Layer | Python + Ground Truth | Đánh giá độ chính xác của JSON tham số (`measures`, `dimensions`, `filters`, `timeDimensions`) do LLM sinh ra so với nhãn chuẩn. | **$\ge 90\%$** |
| **2** | **Faithfulness (Độ trung thực)** | NLG Layer | DeepEval `FaithfulnessMetric` | Đánh giá câu trả lời văn bản của LLM có trung thực $100\%$ với dữ liệu số liệu trả về từ Data Warehouse hay không, phát hiện và triệt tiêu ảo giác bịa số. | **$\ge 95\%$** |
| **3** | **Routing & Clarification Precision** | Safety & Ambiguity Layer | Python Script | Đánh giá khả năng phát hiện câu hỏi mơ hồ để hỏi lại (Clarification) và câu hỏi ngoài phạm vi/phá hoại để từ chối an toàn (Refusal). | **$\ge 90\%$** |
| **4** | **P95 End-to-End Latency** | Performance Layer | Langfuse Tracing | Thời gian phản hồi thực tế của toàn bộ pipeline ở phân vị thứ 95 (đảm bảo 95% request hoàn thành nhanh chóng). | **$\le 2.5\text{s}$** |

#### 🎯 Lý do lựa chọn bộ chỉ số trên:
* **Tính đại diện cho kiến trúc Semantic Layer (Chỉ số 1):** Vì hệ thống không để LLM viết SQL trực tiếp mà ép qua cấu trúc JSON của Cube Core, nên *Semantic Exact Match* là minh chứng sống còn khẳng định LLM đã hiểu đúng và trích xuất đúng tham số vào khuôn mẫu định sẵn.
* **Đảm bảo tính toàn vẹn số liệu và tự động hóa 100% (Chỉ số 2):** Thay vì tốn công viết câu trả lời mẫu thủ công, *Faithfulness* sử dụng trực tiếp kết quả JSON truy vấn từ StarRocks làm ngữ cảnh đối chiếu. Chỉ số này bảo đảm LLM NLG chỉ đóng vai trò tóm tắt trung thực, không bịa đặt hoặc làm sai lệch con số thực tế.
* **Đảm bảo tính an toàn và trải nghiệm người dùng (Chỉ số 3):** Đo lường năng lực phân loại thông minh của hệ thống trước các câu hỏi mơ hồ (Yellow Cases) và các cuộc tấn công Prompt Injection / ngoài phạm vi (Red Cases).
* **Đo lường độ trễ thực tế (Chỉ số 4):** Việc đo P95 Latency qua Langfuse phản ánh chính xác trải nghiệm người dùng cuối thay vì chỉ tính trung bình cộng (Average).

---

### 4.2 Định hướng thiết kế Bộ dữ liệu Kiểm thử (Traffic Light Model)

Để phục vụ đo lường và đánh giá các chỉ số trên, tập dữ liệu kiểm thử được định hướng thiết kế gồm **30 kịch bản câu hỏi tiêu chuẩn** phân bổ theo mô hình 3 nhóm màu đèn giao thông (**Traffic Light Model**), bao phủ toàn bộ 6 Data Marts nghiệp vụ (`traffic_flow`, `air_quality`, `smart_parking`, `smart_lighting`, `street_incidents`, `city_health_index`) và 3 phân khu đô thị (`Can ho`, `Khu biet thu`, `TTTM`):

```
                     ┌─────────────────────────────────────────┐
                     │    KHUNG KIỂM THỬ BENCHMARK (30 CASES)  │
                     └────────────────────┬────────────────────┘
                                          │
         ┌────────────────────────────────┼────────────────────────────────┐
         ▼                                ▼                                ▼
 🟢 15 GREEN CASES                🟡 10 YELLOW CASES                🔴 5 RED CASES
 (Happy Path - Đơn ý định)        (Ambiguous - Cần làm rõ)         (Out-of-Domain & An toàn)
```

* **🟢 Nhóm 1: 15 Green Cases (Happy Path – Đơn ý định hoàn chỉnh):**
  - Bao gồm các câu hỏi có đầy đủ 3 trụ cột dữ liệu: *Chỉ số (Measure)* + *Địa danh (Filter/Section)* + *Thời gian (Time)*.
  - Phân bổ đều trên cả 6 Data Marts (Lưu lượng xe, AQI, Bãi đỗ xe, Chiếu sáng, Sự cố, Livability).
  - Dùng để đo lường: **Semantic Exact Match**, **Response Semantic Correctness** và **P95 Latency**.

* **🟡 Nhóm 2: 10 Yellow Cases (Ambiguous – Nhận diện mơ hồ & Làm rõ):**
  - Bao gồm các câu hỏi thiếu thông tin, hỏi quá chung chung (*"cho tôi xem số liệu"*), đa domain (nhắc 2 Cube cùng lúc), hoặc tên phân khu chưa rõ ràng.
  - Kỳ vọng hệ thống kích hoạt **Clarification Flow** kèm các chip gợi ý trắc nghiệm thay vì suy diễn bừa bãi.
  - Dùng để đo lường: **Routing & Clarification Precision**.

* **🔴 Nhóm 3: 5 Red Cases (Out-of-Domain & Safety Guardrail – Từ chối an toàn):**
  - Bao gồm các câu hỏi ngoài phạm vi dữ liệu đô thị (*"giá vàng", "thời tiết Tokyo"*), sử dụng sai mục đích (*"làm thơ"*), hoặc tấn công bảo mật (*SQL Injection `DROP TABLE`, Prompt Injection / Jailbreak*).
  - Kỳ vọng hệ thống kích hoạt **Refusal** từ chối lịch sự và bảo vệ an toàn cơ sở dữ liệu.
  - Dùng để đo lường: **Routing & Clarification Precision**.

---

## 5. KẾT LUẬN VÀ HƯỚNG PHÁT TRIỂN

