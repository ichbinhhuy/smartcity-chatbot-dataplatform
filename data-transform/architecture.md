# Pipeline Architecture & Fault Handling Specification — Smart Urban Street Lakehouse

> **Dự án:** Hệ thống Modern Data Lakehouse Quản lý & Phân tích Tuyến phố Khu Đô thị Thông minh  
> **Tài liệu:** Kiến trúc Hệ thống Pipeline (Architecture), Phân tầng Trách nhiệm (Separation of Concerns), Định danh Mở rộng (Scaling Rationale) & Quy trình Xử lý Lỗi (Fault Handling Matrix)

---

## 📌 1. Tổng Quan Bài Toán & Định Hướng Định Khung (Architect's Disclaimer)

### 1.1 Business Context
Hệ thống quản lý thông minh cho **1 Tuyến đường chính trong Khu đô thị** (Đại lộ trung tâm khu đô thị), gom nhóm dữ liệu đa nguồn từ cảm biến IoT, camera AI, trạm thu phí/bãi đỗ và API thời tiết thực tế để tính toán chỉ số **Chỉ số Văn minh & Đáng sống Tuyến phố (`street_livability_index`)**.

### 1.2 Enterprise Scaling Rationale & Framing
> [!NOTE]
> **Định khung Kiến trúc (Architecture Framing):**  
> Bộ dữ liệu 7 ngày lịch sử (~2.194 file thô, ~6.2 MB) đóng vai trò là **Bộ dữ liệu diễn tập (Reference Benchmark Dataset)**. Toàn bộ hạ tầng bao gồm **Apache Iceberg**, **Nessie REST Catalog**, **StarRocks 3.2**, **dbt**, **Airflow**, và **Cube.js** được thiết kế dưới dạng **Enterprise Reference Architecture (Chuẩn thiết kế mở rộng)**.  
> Mô hình này bảo đảm khả năng mở rộng tuyến tính (Scale-out) khi lưu lượng tăng từ hàng nghìn file lên hàng chục triệu stream events/ngày mà **không phải thay đổi bất kỳ thành phần core nào trong pipeline**.

---

## 🏗️ 2. Bức Tranh Kiến Trúc Pipeline Tổng Quan (Modern Data Lakehouse Architecture)

Hệ thống tuân thủ mô hình **Medallion Architecture** (Bronze ➔ Silver ➔ Gold) trên nền tảng **Modern Data Stack (MDS)**:

```
[ NGUỒN DỮ LIỆU ĐA ĐỊNH DẠNG (LANDING ZONE) ]
 ├─ Traffic (Nested JSON AI)  ──► File Batch (15 phút/lần)
 ├─ Parking (JSON nhẹ MQTT)  ──► File Batch (15 phút/lần)
 ├─ Environment (Nested API) ──► File Batch (1 giờ/lần)
 ├─ Lighting (XML SCADA)     ──► File Batch (15 phút/lần)
 └─ Incident (CSV Excel)     ──► File Batch (Ngẫu nhiên)
         │
         ▼
[ TẦNG INGESTION — APACHE NIFI / MOCK ENGINE ]
 ├─ Deliver Raw Files ──────► MinIO S3 (landing-zone bucket)
 └─ Malformed Payload ──────► Quarantine / DLQ (landing_zone/quarantine/)
         │
         ▼
[ TẦNG BRONZE — MINIO S3 + NESSIE REST CATALOG + STARROCKS FILES() ]
 ├─ MinIO S3 Object Storage (Bucket: bronze/ - Iceberg Parquet Format)
 ├─ Nessie REST Catalog (Quản lý Iceberg Metadata & Versioning)
 └─ StarRocks SQL Engine (Dùng hàm FILES() nạp dữ liệu từ landing-zone ➔ Bronze Iceberg)
         │
         ▼
[ TẦNG COMPUTATION & TRANSFORMATION — STARROCKS 3.2 + DBT + AIRFLOW ]
 ├─ Airflow Orchestration (Sensor checks, Retry Policies, Webhook Alerting, DAG Isolation)
 ├─ Bronze Layer (Iceberg Tables): Raw Audit Data, Retention 100%, Partitioned by days(recorded_at)
 ├─ Silver Layer (dbt Models): Clean, Deduplicate (ROW_NUMBER), Parse Datetime ➔ Silver Iceberg Tables
 └─ Gold Layer (dbt Models): Business Aggregation, KPIs ➔ StarRocks Internal OLAP Tables
         │
         ▼
[ TẦNG NGỮ NGHĨA & HIỂN THỊ — CUBE.JS HEADLESS BI & VISUALIZATION ]
 ├─ Cube.js Headless Semantic Layer (Nằm trên StarRocks Gold):
 │   ├─ Single Source of Truth cho Metrics (Định nghĩa công thức KPI tập trung)
 │   ├─ Dynamic Row-Level Security (RLS) dựa trên JWT queryRewrite (lọc theo section_id)
 │   └─ Multi-interface Serving:
 │       ├─ REST / GraphQL API ──► Cổng thông tin đô thị / Mobile App cư dân
 │       └─ Cube SQL API (Postgres Protocol) ──► Power BI Desktop / Metabase BI Dashboard
```

---

## 🛡️ 3. Phân Tầng Trách Nhiệm Xử Lý (Separation of Concerns)

```
 ┌────────────────────────────────────────────────────────────────────────────────────────┐
 │ 1. Ingestion (NiFi/Engine)     ──► Gom dữ liệu thô ➔ MinIO landing-zone bucket          │
 │ 2. Storage & Catalog (MinIO/Nessie) ──► Lưu file Parquet & Quản lý Iceberg Metadata    │
 │ 3. Technical Ingest (StarRocks)──► Dùng hàm FILES() nạp S3 ➔ Bronze Iceberg Tables      │
 │ 4. Business Transform (dbt)    ──► Transform Silver Iceberg ➔ Gold StarRocks OLAP       │
 │ 5. Orchestration (Airflow)     ──► Điều phối DAG, Sensor check, Retry & Alert Webhook   │
 │ 6. Headless Semantic (Cube.js) ──► Thống nhất Metrics KPI & Phân quyền RLS qua JWT      │
 │ 7. Visualization (Power BI)    ──► Kết nối Cube SQL API / StarRocks vẽ Dashboard KPI    │
 └────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## ❄️ 4. Tối Ưu Hóa Tầng Lưu Trữ (Apache Iceberg Partitioning Strategy)

Để khai thác tối đa sức mạnh của **Apache Iceberg**, hệ thống áp dụng chiến lược **Hidden Partitioning**:

* **Bronze & Silver Tables Partitioning:**
  ```sql
  -- DDL khởi tạo bảng Bronze Traffic tích hợp Iceberg qua Nessie Catalog
  CREATE TABLE nessie_catalog.bronze_db.bronze_traffic (
      event_id VARCHAR(100),
      device_id VARCHAR(50),
      section_id VARCHAR(50),
      recorded_at DATETIME,
      vehicle_count INT,
      avg_speed_kmh DOUBLE,
      ingestion_time DATETIME
  ) 
  PARTITION BY (days(recorded_at), section_id);
  ```
* **Lợi ích thực tế:**
  1. **Data Skipping / Partition Pruning:** StarRocks Engine khi query báo cáo theo mốc thời gian hoặc khu vực chỉ scan chính xác các file Parquet chứa dữ liệu đó, loại bỏ $90\%$ dung lượng I/O không cần thiết.
  2. **Hidden Partitioning:** Người dùng khi viết SQL truy vấn không cần biết chi tiết cấu trúc thư mục S3, Iceberg tự động ánh xạ điều kiện `WHERE recorded_at >= '2026-07-24'` vào đúng partition.

---

## 🔑 5. Vai Trò Của Cube.js Headless Semantic Layer

Cube.js đóng vai trò hạt nhân trong tầng **Data Serving & Metric Governance**:

1. **Centralized Metric Governance (Thống nhất công thức KPI):**
   * Định nghĩa công thức `street_livability_index` duy nhất tại tập tin Data Schema của Cube.js.
   * Đảm bảo tính đồng nhất tuyệt đối số liệu giữa Power BI, Metabase và Web Portal.
2. **Dynamic Row-Level Security (RLS via JWT):**
   * Sử dụng hàm `queryRewrite` kiểm tra `securityContext.section_id` từ JWT token của người dùng:
   ```javascript
   queryRewrite: (query, { securityContext }) => {
     if (securityContext && securityContext.section_id) {
       query.filters = query.filters || [];
       query.filters.push({
         member: 'Livability.sectionId',
         operator: 'equals',
         values: [securityContext.section_id],
       });
     }
     return query;
   }
   ```
   * **Kết quả:** Quản lý `section_1` đăng nhập ứng dụng chỉ nhìn thấy dữ liệu phân đoạn 1 mà không cần can thiệp DDL ở Database layer.

---

## 📋 6. Ma Trận Xử Lý Lỗi Chi Tiết (Fault Handling Matrix)

Dưới đây là cơ chế xử lý tương ứng cho 3 dạng lỗi dữ liệu trong hệ thống:

---

### 🔴 Lỗi 1: Missing Required Field (Lỗi Cấu Trúc Payload XML)

* **Tầng đảm nhiệm:** `Ingestion Layer (Apache NiFi / Ingestion Engine)`
* **Bản chất kỹ thuật:** Dữ liệu vi phạm Schema Integrity (thiếu thuộc tính bắt buộc `<power_kwh>`).
* **Cơ chế xử lý:**
  1. Processor `ValidateRecord` trong NiFi dùng XML Schema Validator kiểm tra cấu trúc từng bản ghi.
  2. Bản ghi hợp lệ được ghi vào MinIO `landing-zone` Bucket.
  3. Bản ghi thiếu trường bắt buộc bị đẩy qua relationship `invalid` vào **Dead Letter Queue (DLQ)** tại `landing_zone/quarantine/lighting/` và bắn thông báo cảnh báo.

---

### 🟡 Lỗi 2: Business Rule Violation (Lỗi Vi Phạm Quy Luật Nghiệp Vụ)

* **Tầng đảm nhiệm:** `Silver Layer (dbt Transformation & Batch Data Quality)`
* **Bản chất kỹ thuật:** Kiểu dữ liệu hợp lệ (`AQI = -10` hoặc `occupied_slots = 125`), nhưng vi phạm quy luật thực tế ($AQI \ge 0$, $\text{occ} \le \text{tot}$).
* **Cơ chế xử lý:**
  1. **Tầng Bronze Iceberg:** Lưu trữ 100% dữ liệu thô phục vụ đối soát kiểm toán (Auditability).
  2. **Tầng Silver (dbt Test & Quality Flagging):**
     dbt model đánh cờ phân loại:
     ```sql
     SELECT 
         id,
         section_id,
         recorded_at,
         tot AS total_slots,
         occ AS occupied_slots,
         CASE 
             WHEN occ < 0 OR occ > tot THEN FALSE
             ELSE TRUE 
         END AS is_valid,
         CASE 
             WHEN occ < 0 OR occ > tot THEN 'BUSINESS_RULE_VIOLATION'
             ELSE 'CLEAN'
         END AS data_quality_flag
     FROM {{ ref('bronze_parking') }}
     ```
  3. **Tầng Gold:** Chỉ tổng hợp các bản ghi `WHERE is_valid = TRUE` để tính chỉ số `street_livability_index`.

---

### 🔵 Lỗi 3: Duplicate Stream Event Across Files (Lỗi Trùng Lặp Retry)

* **Tầng đảm nhiệm:** `Silver Layer (dbt Deduplication)`
* **Bản chất kỹ thuật:** Cơ chế **At-least-once delivery** có thể khiến một `event_id` bị ghi trùng ở 2 file batch.
* **Cơ chế xử lý:**
  1. **Tầng Bronze Iceberg:** Chấp nhận lưu giữ cả 2 bản ghi trùng lặp.
  2. **Tầng Silver (dbt Deduplication Logic):**
     Sử dụng Window Function để khử trùng lặp theo `ingestion_time` đảm bảo tính **Idempotency**:
     ```sql
     WITH ranked_events AS (
         SELECT 
             *,
             ROW_NUMBER() OVER (
                 PARTITION BY event_id 
                 ORDER BY ingestion_time DESC
             ) AS row_num
         FROM {{ ref('bronze_traffic') }}
     )
     SELECT * EXCEPT(row_num)
     FROM ranked_events
     WHERE row_num = 1;
     ```

---

## 🚀 7. Airflow Orchestration & Resilience Strategy

Đảm bảo pipeline không dừng đột ngột hoặc gây sai lệch dữ liệu:

1. **Sensor Dependency Check:** Sử dụng `S3KeySensor` để đảm bảo file thô trong `landing-zone` đã được nạp hoàn tất trước khi kích hoạt job nạp Bronze.
2. **Retry Policy:** Cấu hình mặc định cho các task:
   ```python
   default_args = {
       'owner': 'lakehouse_admin',
       'retries': 3,
       'retry_delay': timedelta(minutes=5),
       'on_failure_callback': notify_telegram_webhook,
   }
   ```
3. **DAG Isolation & Circuit Breaker:** Nếu bước `dbt test` tầng Silver thất bại, Airflow sẽ lập tức ngắt DAG (Circuit Break), chặn không cho chạy tầng Gold để bảo vệ dữ liệu trên Dashboard không bị sai lệch.

---

## 📊 8. Bảng Theo Dõi Tiến Độ Triển Khai Kiến Trúc (Architecture Progress Tracker)

| Thành phần Kiến trúc | Mục tiêu Kỹ thuật | Trạng thái Triển khai | Bằng chứng Thực thi |
|---|---|---|---|
| **1. Landing Zone** | Nạp & Lưu giữ 2.193 file thô nguyên bản trên MinIO S3 (`landing-zone/`). | ✅ **HOÀN THÀNH 100%** | 2.193 files (JSON, XML, CSV) sẵn sàng tại `s3://landing-zone/`. |
| **2. DLQ Quarantine (Lỗi 1)** | Bắt lỗi cấu trúc/khuyết trường bắt buộc và đẩy vào DLQ S3. | ✅ **HOÀN THÀNH 100%** | Bắt giữ & đẩy file lỗi vào `s3://landing-zone/quarantine/lighting/`. |
| **3. Bronze Storage (Iceberg)** | Ghi 25 file Apache Iceberg Parquet nén + Metadata lên MinIO. | ✅ **HOÀN THÀNH 100%** | 25 files Iceberg Parquet chuẩn tại `s3://bronze/warehouse/bronze_db.db/`. |
| **4. Bronze Engine (StarRocks)** | Nạp 28.783 dòng dữ liệu thô vào `starrocks_bronze` sẵn sàng cho dbt. | ✅ **HOÀN THÀNH 100%** | 28.783 rows trong 5 bảng SQL `starrocks_bronze`. |
| **5. Silver Layer (dbt)** | Khử trùng lặp (`ROW_NUMBER`), đánh cờ `is_valid` làm sạch dữ liệu. | ✅ **HOÀN THÀNH 100%** | Populate 28,449 rows, vượt qua 37/37 dbt tests. |
| **6. Gold Layer (dbt)** | Tính toán chỉ số KPI `street_livability_index` theo Star Schema. | ✅ **HOÀN THÀNH 100%** | 6 Gold models trong `starrocks_gold` (Livability Index = 65.33). |
| **7. Airflow Pipeline** | Tự động hóa Orchestration 4 bước (`Bronze` ➔ `Silver` ➔ `Gold` ➔ `DQ Test`). | ✅ **HOÀN THÀNH 100%** | Airflow DAG `smartcity_lakehouse_pipeline` hoạt động tại port 8082. |
| **8. Serving Layer (Cube.js + BI)** | Headless Semantic Layer (JWT RLS) + Power BI DirectQuery Integration. | ✅ **HOÀN THÀNH 100%** | Cube REST API (port 4000) & Cube SQL Protocol (port 15432) kết nối Power BI. |

