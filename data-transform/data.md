# Data Specification & Fault Injection Guide — Smart Urban Street Lakehouse

> **Dự án:** Hệ thống Data Lakehouse Quản lý & Phân tích Tuyến phố Khu Đô thị Thông minh  
> **Tài liệu:** Thông số Dữ liệu (Schemas, Data Formats, WorldState Rules) & Quy tắc Tiêm Lỗi Dữ liệu (Fault Injection Rules)

---

## 📦 1. Bảng Phương Thức Ingest & Định Dạng Theo Domain

| Domain | Định dạng dữ liệu | Phương thức Ingest trong NiFi | Thư mục Landing Zone | Mô phỏng nguồn thực tế ngoài đời |
|---|---|---|---|---|
| **1. Traffic** | Nested JSON (`.json`) | `ConsumeKafkaRecord` / `GetFile` ➔ `JoltTransformJSON` | `landing_zone/traffic/` | 9 Camera AI (NVIDIA Jetson) phát stream Nested JSON |
| **2. Parking** | JSON nhẹ qua MQTT (`.json`) | `ConsumeMQTT` / `GetFile` ➔ `ConvertRecord` | `landing_zone/parking/` | 3 LoRaWAN Gateway (300 ô đỗ) gửi payload nhẹ qua MQTT |
| **3. Environment** | Nested API JSON (`.json`) | `InvokeHTTP` / `GetFile` ➔ `JoltTransformJSON` | `landing_zone/environment/` | Crawl REST API thật từ AQICN / IQAir theo giờ |
| **4. Lighting** | XML (`.xml`) | `GetFile` ➔ `ConvertRecord` (XMLReader) | `landing_zone/lighting/` | Tủ điện SCADA / PLC điều khiển 30 cột đèn thông minh |
| **5. Incident** | CSV (`.csv`) | `GetFile` ➔ `ConvertRecord` (CSVReader) | `landing_zone/incident/` | Báo cáo ca trực xuất từ Excel của Cảnh sát GT |

---

## 🗄️ 2. Chi Tiết Các Bảng Dữ Liệu & Thư Mục Landing Zone (Schemas)

### 2.1 Bảng Chiều Dùng Chung (Dimension Table)

#### `dim_sections` (Chiều Phân Đoạn Đường)
| Trường (Field) | Kiểu dữ liệu | Loại | Ghi chú |
|---|---|---|---|
| `section_id` | VARCHAR(50) | PK | `section_1`, `section_2`, `section_3` |
| `section_name` | VARCHAR(100) | Dimension | Tên đoạn (`Cổng chính - TTTM`, `Khu Căn hộ`, `Khu Biệt thự`) |
| `max_speed_limit` | INT | Dimension | Tốc độ tối đa quy định (30 km/h) |
| `total_parking_slots` | INT | Dimension | Tổng ô đỗ xe quy hoạch (100 ô / section) |
| `created_at` | TIMESTAMP | Metadata | Ngày tạo bản ghi |

---

### 2.2 Chi Tiết Cấu Trúc Các Bảng Sự Kiện (Fact Tables & Landing Formats)

#### 🚗 Domain 1: Traffic (`fact_traffic`) — Nested JSON (`.json`)
* **Thư mục:** `landing_zone/traffic/traffic_YYYYMMDD_HHMMSS.json` (673 files / 7 ngày).
* **Cấu trúc Fields:**
  * `camera_meta.device_id`: Mã camera (`CAM_SECTION_1_01` ... `CAM_SECTION_3_03`).
  * `camera_meta.section_id`: Mã phân đoạn (`section_1`, `section_2`, `section_3`).
  * `event_time`: Thời gian ghi nhận ISO string (`YYYY-MM-DD HH:MM:SS`).
  * `analytics.summary.id`: ID duy nhất của sự kiện (`trf_{timestamp}_{cam_idx}_{random}`).
  * `analytics.summary.vehicle_count`: Số xe đếm được trong 15 phút.
  * `analytics.summary.avg_speed_kmh`: Tốc độ trung bình (km/h).
  * `analytics.summary.overspeed_flag`: Cờ báo quá tốc độ (`true`/`false`).
* **Metadata Fields:** `source_system` (`nvidia_jetson_edge_ai`), `batch_id`, `ingestion_time`.

---

#### 🅿️ Domain 2: Parking (`fact_parking`) — JSON nhẹ MQTT (`.json`)
* **Thư mục:** `landing_zone/parking/parking_YYYYMMDD_HHMMSS.json` (673 files / 7 ngày).
* **Cấu trúc Fields:**
  * `id`: ID sự kiện đỗ xe (`prk_{timestamp}_{random}`).
  * `gw`: Gateway LoRaWAN (`GW_PARK_SECTION_1` ... `GW_PARK_SECTION_3`).
  * `section_id`: Mã phân đoạn (`section_1`, `section_2`, `section_3`).
  * `recorded_at`: Thời gian ghi nhận (`YYYY-MM-DD HH:MM:SS`).
  * `tot`: Tổng ô đỗ quy hoạch (100 ô / section).
  * `occ`: Số ô đang có xe đỗ.
* **Metadata Fields:** `source_system` (`mqtt_lorawan_stream`), `batch_id`, `ingestion_time`.

---

#### 🌿 Domain 3: Environment (`fact_environment`) — Nested API JSON (`.json`)
* **Thư mục:** `landing_zone/environment/env_YYYYMMDD_HHMMSS.json` (169 files / 7 ngày).
* **Cấu trúc Fields:**
  * `status`: Trạng thái API (`"ok"`).
  * `section_id`: Mã phân đoạn.
  * `timestamp`: Thời gian ghi nhận API.
  * `data.id`: ID bản ghi (`env_{timestamp}_{random}`).
  * `data.aqi`: Chỉ số chất lượng không khí AQI.
  * `data.iaqi.pm25`: Nồng độ bụi mịn PM2.5 ($\mu\text{g/m}^3$).
  * `data.noise.level_db`: Độ ồn đo được (dB).
* **Metadata Fields:** `source_system` (`aqicn_api_nested`), `batch_id`, `ingestion_time`.

---

#### 💡 Domain 4: Smart Lighting (`fact_lighting`) — XML SCADA (`.xml`)
* **Thư mục:** `landing_zone/lighting/lighting_YYYYMMDD_HHMMSS.xml` (673 files / 7 ngày).
* **Cấu trúc Fields trong thẻ `<pole>`:**
  * `<id>`: ID bản ghi (`lgt_{timestamp}_{random}`).
  * `<section_id>`: Mã phân đoạn.
  * `<pole_id>`: Mã cột đèn (`pole_section_1_01` ... `pole_section_3_10`).
  * `<recorded_at>`: Thời gian ghi nhận.
  * `<power_kwh>`: Điện năng tiêu thụ trong 15 phút (kWh).
  * `<status>`: Trạng thái bóng đèn (`OK` / `FAULTY`).
* **Metadata Fields:** `source_system` (`scada_plc_xml`), `batch_id`, `ingestion_time`.

---

#### ⚠️ Domain 5: Incidents (`fact_incident`) — CSV Report (`.csv`)
* **Thư mục:** `landing_zone/incident/incident_YYYYMMDD_HHMMSS.csv` (File phát sinh khi có sự cố).
* **Cấu trúc Fields:**
  * `incident_id`: Mã sự cố (`inc_{timestamp}`).
  * `section_id`: Mã phân đoạn xảy ra sự cố.
  * `incident_type`: Loại sự cố (`accident`, `road_work`, `traffic_light_failure`).
  * `timestamp_start`: Thời điểm bắt đầu sự cố.
  * `duration_min`: Thời lượng sự cố ước tính (phút).
* **Metadata Fields:** `source_system` (`traffic_police_excel_export`), `batch_id`, `ingestion_time`.

---

## 🧠 3. Chi Tiết Công Thức Toán Học & Quy Luật Sinh Dữ Liệu (WorldState Engine)

Toàn bộ dữ liệu của 5 domain được điều phối bởi một đối tượng quản lý trạng thái tập trung (`WorldState` Engine) nhằm đảm bảo tính chân thực và nhất quán logic:

### 3.1 Động Cơ Quản Lý Trạng Thái (WorldState Objects)
* **`active_incidents`:** `{ section_id: { "end_time": datetime, "type": string } }` — Quản lý danh sách sự cố đang active.
* **`latest_traffic`:** `{ section_id: vehicle_count }` — Lưu mật độ xe mới nhất để làm tham số cho Domain Environment & Parking.
* **`faulty_lamps`:** `{ pole_id: faulty_until_datetime }` — Lưu danh sách bóng đèn đang hỏng và thời điểm sửa xong.

---

### 3.2 Quy Luật Sinh Dữ Liệu Theo Từng Domain

#### 🚗 Domain 1: Traffic & Access (`fact_traffic`)
1. **Công thức Sóng Gauss Kép Giờ Cao Điểm (Hour-of-Day Double Peak Curve):**
   $$\text{BaseTraffic}(h) = \left( 55 + 190 \cdot \left( e^{-\frac{(h-8)^2}{4}} + e^{-\frac{(h-18)^2}{6}} \right) \right) \times \text{LunchDip}(h) \times \text{WeekendFactor}(h)$$
   * **Đỉnh cao điểm (8h & 18h):** $180 - 280$ xe / 15-min / camera (Đỉnh 8h: ~222 xe, Đỉnh 18h: ~267 xe).
   * **Thấp điểm / Giờ trưa (11h - 13h):** $45 - 60$ xe / 15-min / camera (~53.7 - 55.2 xe/15p).
   * **Đêm khuya (1h - 4h sáng):** $15 - 20$ xe / 15-min / camera (~18.5 xe/15p).
   * **Cuối tuần (T7/CN):** Sáng giảm 30%, Chiều/Tối tăng 35%.
2. **Công thức Tác Động Khi Có Sự Cố (Incident Cross-Correlation):**
   $$\text{Nếu } \text{section\_id} \in \text{active\_incidents} \implies 
   \begin{cases} 
   \text{vehicle\_count} = \max(1, \lfloor \text{vehicle\_count} \times 0.4 \rfloor) \\
   \text{avg\_speed\_kmh} = \text{Uniform}(5.0, 10.0) \text{ (km/h)}
   \end{cases}$$

#### 🅿️ Domain 2: Smart Parking (`fact_parking`)
1. **Công thức Bước Đi Ngẫu Nhiên Có Ranh Giới (Bounded Random Walk):**
   $$\text{Occupied}_t = \max\left(15, \min\left(90, \text{Occupied}_{t-1} + \Delta + \text{Bias}_{\text{traffic}}\right)\right)$$
   * $\Delta \in [-3, -1, 0, 1, 3]$ ngẫu nhiên.
   * $\text{Bias}_{\text{traffic}} = +2$ nếu $\text{Traffic} > 80$; $\text{Bias}_{\text{traffic}} = -2$ nếu $\text{Traffic} < 30$.
   * Tổng ô đỗ $\text{tot} = 100$ ô/section.

#### 🌿 Domain 3: Environment (`fact_environment`)
1. **Công thức Tương Quan Độ Ồn Giao Thông (Traffic-to-Noise Linear Regression):**
   $$\text{Noise\_Level (dB)} = 40.0 + (0.15 \times \text{vehicle\_count}) + \mathcal{N}(\mu=0, \sigma=1.5)$$
2. **Real Crawl API:** Chỉ số `aqi` ($45 - 115$) và `pm25` ($15 - 50\,\mu\text{g/m}^3$) crawl trực tiếp từ API AQICN.

#### 💡 Domain 4: Smart Lighting (`fact_lighting`)
1. **Công thức Công Suất Theo Khung Giờ (SCADA Power Curve):**
   $$\text{Power\_kWh}(h) = 
   \begin{cases} 
   \text{Uniform}(2.4, 2.6) & \text{khi } 18 \le h \le 23 \text{ (100\% Bật)} \\
   \text{Uniform}(1.1, 1.3) & \text{khi } 1 \le h \le 5 \text{ (Dimming tiết kiệm 50\%)} \\
   0.0 & \text{ban ngày (Tắt)}
   \end{cases}$$
2. **Công thức Lưu Trạng Thái Hỏng Kéo Dài (State Persistence Expiration):**
   * $P(\text{FAULTY}) = 0.002$. Thời hạn hỏng: $T_{\text{faulty\_until}} = T_{\text{current}} + \text{Uniform}(3, 6) \text{ hours}$.

#### ⚠️ Domain 5: Incidents (`fact_incident`)
1. **Phân Nhánh Thời Lượng:** `road_work` ($2-6$ tiếng), `accident` ($30-90$ phút), `traffic_light_failure` ($15-45$ phút).
2. **Poisson Rare Event:** Xác suất $\sim 0.8\%$ per 15-min tick.

---

## 🏆 4. Chi Tiết Công Thức Chấm Điểm Composite Metric (`street_livability_index`)

Chỉ số **Văn minh & Đáng sống Tuyến phố** được tính toán tại dbt Gold Model theo công thức có trọng số công khai từ $0$ đến $100$:

$$\text{Livability Index} = 0.35 \times S_{\text{Traffic}} + 0.25 \times S_{\text{Env}} + 0.20 \times S_{\text{Parking}} + 0.10 \times S_{\text{Lighting}} + 0.10 \times S_{\text{Safety}}$$

### Công thức tính điểm thành phần (Component Scores):
1. **Điểm Giao Thông ($S_{\text{Traffic}}$):** $S_{\text{Traffic}} = \min\left(100, \frac{\text{avg\_speed\_kmh}}{30.0} \times 100\right)$
2. **Điểm Môi Trường ($S_{\text{Env}}$):** $S_{\text{Env}} = \max\left(0, 100 - \text{AQI}\right)$
3. **Điểm Đỗ Xe ($S_{\text{Parking}}$):** $S_{\text{Parking}} = \max\left(0, 100 - \left|\text{Occupancy Pct} - 70\%\right| \times 2\right)$
4. **Điểm Chiếu Sáng ($S_{\text{Lighting}}$):** $S_{\text{Lighting}} = \max\left(0, 100 - (\text{Faulty Lamp Pct} \times 100)\right)$
5. **Điểm An Toàn ($S_{\text{Safety}}$):** $S_{\text{Safety}} = 70$ nếu có sự cố active, $100$ nếu không có sự cố.

---

## 🛠️ 5. Quy Tắc Tiêm 3 Dạng Lỗi Dữ Liệu Có Kiểm Soát (Fault Injection Rules)

Để phục vụ kiểm thử và demo, bộ sinh dữ liệu `mock_engine/generator.py` tiêm 3 dạng lỗi phổ biến theo **chỉ số vị trí tương đối (`tick_index`)** từ khi generator bắt đầu chạy:

---

### 🔴 Lỗi 1: Missing Required Field (Lỗi Cấu Trúc Schema XML)

* **Domain tiêm lỗi:** `lighting` (XML SCADA)
* **Vị trí tiêm (Relative Offset):** Tại `tick_index = 100` và `tick_index = 400`.
* **Đối tượng bị lỗi:** Cột đèn `pole_section_1_05`.
* **Cách thức tiêm:** Bỏ hoàn toàn thẻ `<power_kwh>` khi sinh thẻ `<pole>`.

#### So sánh dữ liệu:
* **Dạng chuẩn (Standard):**
  ```xml
  <pole>
      <id>lgt_1784737800000_105</id>
      <section_id>section_1</section_id>
      <pole_id>pole_section_1_05</pole_id>
      <recorded_at>2026-07-21 21:00:00</recorded_at>
      <power_kwh>2.48</power_kwh>
      <status>OK</status>
  </pole>
  ```
* **Dạng lỗi (Fault Injected):**
  ```xml
  <pole>
      <id>lgt_1784737800000_105</id>
      <section_id>section_1</section_id>
      <pole_id>pole_section_1_05</pole_id>
      <recorded_at>2026-07-21 21:00:00</recorded_at>
      <!-- THIẾU THẺ <power_kwh> -->
      <status>OK</status>
  </pole>
  ```

---

### 🟡 Lỗi 2: Business Rule Violation (Lỗi Logic Nghiệp Vụ)

* **Domain tiêm lỗi:** `environment` (AQI âm) & `parking` (Quá tải sức chứa)
* **Vị trí tiêm (Relative Offset):**
  * **Lỗi AQI âm:** Tại `tick_index = 200` ở `section_2` (Domain `environment`).
  * **Lỗi Parking Over-capacity:** Tại `tick_index = 350` ở `GW_PARK_SECTION_1` (Domain `parking`).
* **Cách thức tiêm:**
  * Gán `aqi = -10` (Vi phạm quy luật vật lý AQI $\ge 0$).
  * Gán `occ = 125` trong khi `tot = 100` (Vi phạm quy luật $0 \le \text{occ} \le \text{tot}$).

#### So sánh dữ liệu:
* **Dạng chuẩn (Standard Parking):**
  ```json
  {
    "id": "prk_1784737800000_101",
    "gw": "GW_PARK_SECTION_1",
    "section_id": "section_1",
    "recorded_at": "2026-07-24 14:00:00",
    "tot": 100,
    "occ": 65
  }
  ```
* **Dạng lỗi (Fault Injected Parking):**
  ```json
  {
    "id": "prk_1784737800000_101",
    "gw": "GW_PARK_SECTION_1",
    "section_id": "section_1",
    "recorded_at": "2026-07-24 14:00:00",
    "tot": 100,
    "occ": 125 
  }
  ```

---

### 🔵 Lỗi 3: Duplicate Event Across Files (Lỗi Trùng Lặp Stream Retry)

* **Domain tiêm lỗi:** `traffic` (Nested JSON)
* **Vị trí tiêm (Relative Offset):** Tại `tick_index = 300` và `tick_index = 301`.
* **Cách thức tiêm:**
  * Chọn 1 bản ghi `camera_data` tại file mốc `tick_index = 300` (ví dụ `event_id = "trf_1784737800000_1_999"`).
  * Chèn **chính xác bản ghi trùng lặp này** vào file JSON của mốc tiếp theo `tick_index = 301`.

#### So sánh dữ liệu:
* **File 1 (`traffic_tick_300.json`):**
  ```json
  [
    {
      "camera_meta": {"device_id": "CAM_SECTION_1_01", "section_id": "section_1"},
      "analytics": {
        "summary": {
          "id": "trf_1784737800000_1_999",
          "vehicle_count": 45,
          "avg_speed_kmh": 26.5
        }
      }
    }
  ]
  ```
* **File 2 (`traffic_tick_301.json` — Trùng lặp `id`):**
  ```json
  [
    {
      "camera_meta": {"device_id": "CAM_SECTION_1_01", "section_id": "section_1"},
      "analytics": {
        "summary": {
          "id": "trf_1784737800000_1_999", 
          "vehicle_count": 45,
          "avg_speed_kmh": 26.5
        }
      }
    }
  ]
  ```

---

## 🔍 6. Công Cụ Kiểm Tra Đầu Vào Dữ Liệu (`verify_errors.py`)

Sau khi chạy bộ sinh dữ liệu `python mock_engine/generator.py`, chạy lệnh sau để xác nhận các lỗi thô đã được tiêm chính xác vào `landing_zone/`:

```bash
python mock_engine/verify_errors.py
```

Script sẽ kiểm tra và xuất báo cáo kiểm toán đầu vào:
* ✅ Xác nhận số lượng file thô đã tạo.
* 🔴 Thống kê vị trí & số lượng file XML bị thiếu thẻ `<power_kwh>`.
* 🟡 Thống kê các bản ghi JSON vi phạm `AQI < 0` hoặc `occupied_slots > total_slots`.
* 🔵 Thống kê các cặp `event_id` bị lặp lại ở 2 file nạp liên tiếp.

---

## 🔄 7. Chi Tiết Mapping & Biến Đổi Dữ Liệu Từ Bronze ➔ Silver (Bronze to Silver Specification)

### 7.1 Nguyên Tắc Xử Lý Tầng Silver (Trust Layer Principles)

Toàn bộ quy trình xử lý từ Bronze sang Silver và phục vụ Gold tuân theo 4 bước cốt lõi:

1. **Phát Hiện Lỗi (Quality Detection):**
   * Quét toàn bộ tất cả các trường theo Khung 4 Tầng tổng quát:
     - **NULL / Missing:** Trường khuyết dữ liệu (`event_id`, `power_kwh`, `timestamp`...).
     - **Category / Enum:** Mã không tồn tại (`section_id NOT IN ('section_1','section_2','section_3')`, `status NOT IN ('OK','FAULTY','OFF')`...).
     - **Range / Bounds:** Vi phạm giới hạn số học/lý hóa (`aqi < 0`, `occupied_slots > slot_total`, `vehicle_count < 0`...).
     - **Datetime Sanity:** Định dạng thời gian hỏng hoặc tương lai.

2. **Tránh Sập SQL (Fallback Value for Non-Null DDL):**
   * Chỉ gán giá trị an toàn tạm thời (VD: `COALESCE(power_kwh, 0.0)`) đối với các cột DDL bắt buộc `NOT NULL` để câu lệnh nạp `INSERT` không bị sập.

3. **Bảo Toàn Dữ Liệu Để Audit (Auditability & Traceability):**
   * Tuyệt đối KHÔNG xóa (`DELETE`) bản ghi lỗi.
   * Lưu nguyên giá trị thô vào Silver (`aqi = -10`, `occupied_slots_raw = 125`).
   * Đánh dấu `record_status = 'INVALID'` (hoặc `'WARNING'`) và ghi rõ lý do vào `primary_dq_flag` (VD: `'INVALID_AQI'`, `'OVERFLOW_PARKING'`, `'NULL_POWER'`).
   * Lưu trữ đầy đủ 3 mốc thời gian truy vết: `ingestion_time` (khi vào Bronze), `processed_at` (`NOW()`), `dbt_invocation_id` (`'{{ invocation_id }}'`).

4. **Tầng Gold Sạch 100% (Clean Gold Serving):**
   * Tầng Gold (Data Mart / BI) chỉ đọc dữ liệu Silver với điều kiện lọc duy nhất:
     ```sql
     WHERE record_status = 'VALID'
     ```
   * Toàn bộ các dòng dữ liệu bị lỗi sẽ bị tầng Gold tự động bỏ qua, giúp các báo cáo chỉ số KPI đạt độ chính xác $100\%$ sạch.

### 7.2 Bảng Mapping Chi Tiết Đầy Đủ Theo 5 Domain

#### 🚗 1. Domain Traffic (`bronze_traffic` ➔ `silver_traffic`)

| Trường Bronze gốc | Kiểu Bronze | Trường Silver tương ứng | Kiểu Silver | Nó làm gì / Mục đích nghiệp vụ? | Thực hiện như thế nào? (Công thức SQL) | Quy tắc kiểm tra hợp lệ (All Rules) |
|---|---|---|---|---|---|---|
| `event_id` | `VARCHAR` | `id` | `VARCHAR(100)` | **Primary Key**: Khóa chính duy nhất đại diện cho 1 sự kiện đếm xe. | `ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY ingestion_time DESC)` ➔ Lấy `rn = 1` để **loại bỏ 19 bản ghi trùng lặp do nạp lại**. | Must NOT BE NULL, Must BE Unique |
| `device_id` | `VARCHAR` | `device_id` | `VARCHAR(50)` | Định danh Camera AI phát hiện luồng giao thông. | Giữ nguyên gốc | Must NOT BE NULL, Must match `CAM_SECTION_[1-3]_[01-03]` |
| `section_id` | `VARCHAR` | `section_id` | `VARCHAR(50)` | Định danh phân đoạn đường (Khu vực). | Giữ nguyên gốc | Must IN (`'section_1'`, `'section_2'`, `'section_3'`) |
| `event_time` | `VARCHAR` ⚠️ | `recorded_at` | `DATETIME` | **Mốc thời gian chuẩn hóa**: Giúp StarRocks áp dụng Partition Pruning và Vectorized Execution, tăng tốc truy vấn 10x-100x. | `STR_TO_DATE(event_time, '%Y-%m-%d %H:%i:%s')` | Must NOT BE NULL, Must BE Valid Datetime |
| `vehicle_count` | `INT` | `vehicle_count` | `INT` | Số lượng xe đếm được trong khung giờ 15 phút. | Giữ nguyên gốc | **INVALID**: `< 0` (bất khả thi) \| **WARNING**: `> 200` (~800 xe/giờ, cực cao cho tuyến đô thị nhỏ) \| **VALID**: `0–200` |
| `avg_speed_kmh`| `DOUBLE` | `avg_speed_kmh` | `DOUBLE` | Tốc độ trung bình các xe chạy qua camera trong 15 phút. | Giữ nguyên gốc | **INVALID**: `< 0` hoặc `> 120` (giới hạn phần cứng camera) \| **WARNING**: `> 60` (gấp đôi giới hạn 30 km/h làm tốc độ **trung bình**, cực bất thường) \| **VALID**: `0–60` |
| `overspeed_flag`| `BOOLEAN` | `overspeed_flag`| `BOOLEAN` | Cờ báo có xe chạy quá tốc độ quy định hay không. | Giữ nguyên gốc | Must BE NOT NULL |
| `ingestion_time`| `DATETIME` | `ingestion_time`| `DATETIME` | **Audit Trail 1**: Mốc thời gian dữ liệu thô chạm vào Bronze từ nguồn IoT. | Giữ nguyên từ Bronze | Must BE NOT NULL |
| *(Tính mới)* | — | `record_status` | `VARCHAR(20)` | **Gatekeeper cho Gold** — 3 mức: `'VALID'` / `'WARNING'` (bất thường, cần alert riêng) / `'INVALID'` (lỗi cứng). Gold thống kê dùng `VALID`, Dashboard alert dùng `WARNING`. | `CASE WHEN (id IS NULL OR device_id IS NULL OR section_id NOT IN (...) OR recorded_at IS NULL OR vehicle_count < 0 OR avg_speed_kmh < 0 OR avg_speed_kmh > 120) THEN 'INVALID' WHEN vehicle_count > 200 OR avg_speed_kmh > 60 THEN 'WARNING' ELSE 'VALID' END` | Must IN (`'VALID'`, `'INVALID'`, `'WARNING'`) |
| *(Tính mới)* | — | `primary_dq_flag`| `VARCHAR(50)` | **Lý do lỗi / cảnh báo chi tiết**: Ghi nhận vi phạm đầu tiên. | `CASE WHEN ... THEN 'NULL_EVENT_ID' ... WHEN vehicle_count < 0 THEN 'NEGATIVE_VEHICLE_COUNT' WHEN avg_speed_kmh > 120 THEN 'HARDWARE_LIMIT_SPEED' WHEN vehicle_count > 200 THEN 'EXTREME_TRAFFIC_VOLUME' WHEN avg_speed_kmh > 60 THEN 'EXTREME_AVG_SPEED' ELSE 'OK' END` | Must BE NOT NULL |
| *(Tính mới)* | — | `processed_at` | `DATETIME` | **Audit Trail 2**: Mốc thời gian dbt thực hiện biến đổi dữ liệu sang Silver. | `NOW()` | Must BE NOT NULL |
| *(Tính mới)* | — | `dbt_invocation_id`| `VARCHAR(100)`| **Audit Trail 3**: Mã UUID duy nhất của lần chạy `dbt run` để trace vết khi có sự cố pipeline. | `'{{ invocation_id }}'` (Jinja variable) | Must BE NOT NULL |

---

#### 🅿️ 2. Domain Parking (`bronze_parking` ➔ `silver_parking`)

| Trường Bronze gốc | Kiểu Bronze | Trường Silver tương ứng | Kiểu Silver | Nó làm gì / Mục đích nghiệp vụ? | Thực hiện như thế nào? (Công thức SQL) | Quy tắc kiểm tra hợp lệ (All Rules) |
|---|---|---|---|---|---|---|
| `event_id` | `VARCHAR` | `id` | `VARCHAR(100)` | Primary Key — Lọc bỏ các bản ghi trùng lặp. | `ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY ingestion_time DESC)` ➔ Lấy `rn = 1`. | Must NOT BE NULL, Unique |
| `gw_id` | `VARCHAR` | `gw_id` | `VARCHAR(50)` | Mã Gateway LoRaWAN quản lý ô đỗ. | Giữ nguyên gốc | Must IN (`'GW_PARK_SECTION_1'`, `'GW_PARK_SECTION_2'`, `'GW_PARK_SECTION_3'`) |
| `section_id` | `VARCHAR` | `section_id` | `VARCHAR(50)` | Mã phân đoạn đường đỗ xe. | Giữ nguyên gốc | Must IN (`'section_1'`, `'section_2'`, `'section_3'`) |
| `recorded_at` | `VARCHAR` ⚠️ | `recorded_at` | `DATETIME` | Mốc thời gian chuẩn hóa. | `STR_TO_DATE(recorded_at, '%Y-%m-%d %H:%i:%s')` | Must NOT BE NULL |
| `slot_total` | `INT` | `slot_total` | `INT` | Sức chứa ô đỗ quy hoạch (Cố định = 100). | Giữ nguyên gốc | Must BE `> 0` |
| `occupied_slots`| `INT` ⚠️ | `occupied_slots_raw`| `INT` | **Dữ liệu gốc phục vụ Audit**: Giữ lại đúng con số cảm biến gửi (kể cả 125, 135, 150 quá tải) để kỹ thuật sửa cảm biến. | `occupied_slots` (Đổi tên cột thành `_raw`). | Giữ nguyên gốc không sửa |
| *(Tính mới)* | — | `occupied_slots_clean`| `INT` | **Dữ liệu sạch cho Gold**: Ép tối đa về `slot_total` (100) để Gold tính tỷ lệ không bị lố $100\%$. | `LEAST(occupied_slots, slot_total)` | Must BE `>= 0` AND `<= slot_total` |
| `ingestion_time`| `DATETIME` | `ingestion_time`| `DATETIME` | Audit Trail 1: Mốc nạp vào Bronze từ IoT. | Giữ nguyên gốc | Must NOT BE NULL |
| *(Tính mới)* | — | `record_status` | `VARCHAR(20)` | Gatekeeper cho Gold (`occupied_slots > slot_total` bị gắn `'INVALID'`). | `CASE WHEN (id IS NULL OR gw_id NOT IN ('GW_PARK_SECTION_1','GW_PARK_SECTION_2','GW_PARK_SECTION_3') OR section_id NOT IN ('section_1','section_2','section_3') OR recorded_at IS NULL OR slot_total <= 0 OR occupied_slots < 0 OR occupied_slots > slot_total) THEN 'INVALID' ELSE 'VALID' END` | Must IN (`'VALID'`, `'INVALID'`, `'WARNING'`) |
| *(Tính mới)* | — | `primary_dq_flag`| `VARCHAR(50)` | Lý do lỗi chi tiết. | `CASE WHEN gw_id NOT IN (...) THEN 'INVALID_GATEWAY' WHEN section_id NOT IN (...) THEN 'INVALID_SECTION' WHEN recorded_at IS NULL THEN 'NULL_TIMESTAMP' WHEN occupied_slots > slot_total THEN 'OVERFLOW_PARKING' WHEN occupied_slots < 0 THEN 'NEGATIVE_OCCUPIED' ELSE 'OK' END` | Must BE NOT NULL |
| *(Tính mới)* | — | `processed_at` | `DATETIME` | Audit Trail 2: Mốc dbt transform. | `NOW()` | Must BE NOT NULL |
| *(Tính mới)* | — | `dbt_invocation_id`| `VARCHAR(100)`| Audit Trail 3: Mã lần chạy dbt. | `'{{ invocation_id }}'` | Must BE NOT NULL |

---

#### 🌿 3. Domain Environment (`bronze_environment` ➔ `silver_environment`)

| Trường Bronze gốc | Kiểu Bronze | Trường Silver tương ứng | Kiểu Silver | Nó làm gì / Mục đích nghiệp vụ? | Thực hiện như thế nào? (Công thức SQL) | Quy tắc kiểm tra hợp lệ (All Rules) |
|---|---|---|---|---|---|---|
| `event_id` | `VARCHAR` | `id` | `VARCHAR(100)` | Primary Key — Lọc bỏ các bản ghi trùng lặp. | `ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY ingestion_time DESC)` ➔ Lấy `rn = 1`. | Must NOT BE NULL, Unique |
| `section_id` | `VARCHAR` | `section_id` | `VARCHAR(50)` | Mã phân đoạn đường. | Giữ nguyên gốc | Must IN (`'section_1'`, `'section_2'`, `'section_3'`) |
| `recorded_at` | `VARCHAR` ⚠️ | `timestamp` | `DATETIME` | Mốc thời gian chuẩn hóa (Đổi tên thành `timestamp`). | `STR_TO_DATE(recorded_at, '%Y-%m-%d %H:%i:%s')` | Must NOT BE NULL |
| `aqi` | `INT` ⚠️ | `aqi` | `INT` | Chỉ số không khí. **Giữ nguyên gốc kể cả giá trị âm** để audit phần cứng. | Giữ nguyên gốc | **INVALID**: `< 0` (bất khả thi) hoặc `> 500` (vượt thang AQI tối đa) \| **WARNING**: `> 200` (Very Unhealthy–Hazardous, hiếm ở khu dân cư) \| **VALID**: `0–200` |
| `pm25` | `DOUBLE` | `pm25` | `DOUBLE` | Nồng độ bụi mịn PM2.5 ($\mu\text{g/m}^3$). | Giữ nguyên gốc | **INVALID**: `< 0` (bất khả thi) \| **WARNING**: `> 150` (Hazardous zone WHO, possible khi sự cố ô nhiễm cục bộ) \| **VALID**: `0–150` |
| `noise_level_db`| `DOUBLE` | `noise_level_db`| `DOUBLE` | Độ ồn đo được (dB). | Giữ nguyên gốc | **INVALID**: `< 0` (bất khả thi) hoặc `> 200` (vượt giới hạn thiết bị đo) \| **WARNING**: `> 120` (ngang máy bay cất cánh, ~0.1% xác suất khi nổ/tai nạn lớn) \| **VALID**: `0–120` |
| `ingestion_time`| `DATETIME` | `ingestion_time`| `DATETIME` | Audit Trail 1: Mốc nạp vào Bronze từ IoT. | Giữ nguyên gốc | Must NOT BE NULL |
| *(Tính mới)* | — | `record_status` | `VARCHAR(20)` | **Gatekeeper cho Gold** — 3 mức. Gold thống kê dùng `VALID`, Alert Dashboard dùng `WARNING` (ô nhiễm/tiếng ồn cực hạn có thể là sự cố thật). | `CASE WHEN (aqi < 0 OR aqi > 500 OR pm25 < 0 OR noise_level_db < 0 OR noise_level_db > 200) THEN 'INVALID' WHEN (aqi > 200 OR pm25 > 150 OR noise_level_db > 120) THEN 'WARNING' ELSE 'VALID' END` | Must IN (`'VALID'`, `'INVALID'`, `'WARNING'`) |
| *(Tính mới)* | — | `primary_dq_flag`| `VARCHAR(50)` | Lý do lỗi/cảnh báo chi tiết. | `CASE WHEN aqi < 0 THEN 'NEGATIVE_AQI' WHEN aqi > 500 THEN 'HARDWARE_LIMIT_AQI' WHEN pm25 < 0 THEN 'NEGATIVE_PM25' WHEN noise_level_db < 0 THEN 'NEGATIVE_NOISE' WHEN noise_level_db > 200 THEN 'HARDWARE_LIMIT_NOISE' WHEN aqi > 200 THEN 'EXTREME_AQI' WHEN pm25 > 150 THEN 'EXTREME_PM25' WHEN noise_level_db > 120 THEN 'EXTREME_NOISE_OUTLIER' ELSE 'OK' END` | Must BE NOT NULL |
| *(Tính mới)* | — | `processed_at` | `DATETIME` | Audit Trail 2: Mốc dbt transform. | `NOW()` | Must BE NOT NULL |
| *(Tính mới)* | — | `dbt_invocation_id`| `VARCHAR(100)`| Audit Trail 3: Mã lần chạy dbt. | `'{{ invocation_id }}'` | Must BE NOT NULL |

---

#### 💡 4. Domain Lighting (`bronze_lighting` ➔ `silver_lighting`)

| Trường Bronze gốc | Kiểu Bronze | Trường Silver tương ứng | Kiểu Silver | Nó làm gì / Mục đích nghiệp vụ? | Thực hiện như thế nào? (Công thức SQL) | Quy tắc kiểm tra hợp lệ (All Rules) |
|---|---|---|---|---|---|---|
| `event_id` | `VARCHAR` | `id` | `VARCHAR(100)` | Primary Key — Lọc bỏ trùng lặp. | `ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY ingestion_time DESC)` ➟ Lấy `rn = 1`. | Must NOT BE NULL, Unique |
| `section_id` | `VARCHAR` | `section_id` | `VARCHAR(50)` | Mã phân đoạn đường. | Giữ nguyên gốc | Must IN (`'section_1'`, `'section_2'`, `'section_3'`) |
| `pole_id` | `VARCHAR` | `pole_id` | `VARCHAR(50)` | Định danh cột đèn (VD: `pole_section_1_05`). | Giữ nguyên gốc | Must NOT BE NULL |
| `recorded_at` | `VARCHAR` ⚠️ | `recorded_at` | `DATETIME` | Mốc thời gian chuẩn hóa. | `STR_TO_DATE(recorded_at, '%Y-%m-%d %H:%i:%s')` | Must NOT BE NULL |
| `power_kwh` | `DOUBLE` (NULL)⚠️ | `power_kwh` | `DOUBLE` | Điện năng tiêu thụ. DDL Silver `NOT NULL` ➔ `COALESCE(NULL, 0.0)` tránh sập INSERT. Check INVALID/WARNING từ `power_kwh_raw` trước COALESCE. | `COALESCE(power_kwh_raw, 0.0)` | **INVALID**: IS NULL hoặc `< 0` \| **WARNING**: `> 0.5 kWh/15min/cột` (~2000W, 5× mức LED bình thường, nghi ngắn mạch) \| **VALID**: `0–0.5` |
| `status` | `VARCHAR` | `status` | `VARCHAR(50)` | Trạng thái bóng đèn (`OK`, `FAULTY`, `OFF`). | Giữ nguyên gốc | Must IN (`'OK'`, `'FAULTY'`, `'OFF'`) — Enum cố định, không có vùng WARNING |
| `ingestion_time`| `DATETIME` | `ingestion_time`| `DATETIME` | Audit Trail 1: Mốc nạp vào Bronze từ SCADA. | `COALESCE(ingestion_time, NOW())` | Must NOT BE NULL |
| *(Tính mới)* | — | `record_status` | `VARCHAR(20)` | **Gatekeeper cho Gold** — 3 mức. **Bắt `power_kwh_raw IS NULL` từ trước khi COALESCE** để giữ cờ lỗi. | `CASE WHEN (power_kwh_raw IS NULL OR power_kwh_raw < 0 OR pole_id IS NULL OR status NOT IN ('OK','FAULTY','OFF') OR ...) THEN 'INVALID' WHEN power_kwh_raw > 0.5 THEN 'WARNING' ELSE 'VALID' END` | Must IN (`'VALID'`, `'INVALID'`, `'WARNING'`) |
| *(Tính mới)* | — | `primary_dq_flag`| `VARCHAR(50)` | Lý do lỗi/cảnh báo chi tiết. | `CASE WHEN power_kwh_raw IS NULL THEN 'NULL_POWER' WHEN power_kwh_raw < 0 THEN 'NEGATIVE_POWER' WHEN status NOT IN (...) THEN 'INVALID_STATUS' WHEN power_kwh_raw > 0.5 THEN 'EXTREME_POWER_CONSUMPTION' ELSE 'OK' END` | Must BE NOT NULL |
| *(Tính mới)* | — | `processed_at` | `DATETIME` | Audit Trail 2: Mốc dbt transform. | `NOW()` | Must BE NOT NULL |
| *(Tính mới)* | — | `dbt_invocation_id`| `VARCHAR(100)`| Audit Trail 3: Mã lần chạy dbt. | `'{{ invocation_id }}'` | Must BE NOT NULL |

---

#### ⚠️ 5. Domain Incident (`bronze_incident` ➔ `silver_incident`)

|---|---|---|---|---|---|---|
| `incident_id` | `VARCHAR` | `incident_id` | `VARCHAR(100)` | Primary Key — Lọc bỏ trùng lặp. | `ROW_NUMBER() OVER (PARTITION BY incident_id ORDER BY ingestion_time DESC)` ➔ Lấy `rn = 1`. | Must NOT BE NULL, Unique |
| `section_id` | `VARCHAR` | `section_id` | `VARCHAR(50)` | Mã phân đoạn đường xảy ra sự cố. | Giữ nguyên gốc | Must IN (`'section_1'`, `'section_2'`, `'section_3'`) |
| `incident_type`| `VARCHAR` | `incident_type`| `VARCHAR(50)` | Loại sự cố (`accident`, `road_work`, `traffic_light_failure`). | Giữ nguyên gốc | Must IN (`'accident'`, `'road_work'`, `'traffic_light_failure'`) |
| `timestamp_start`| `VARCHAR` ⚠️ | `timestamp_start`| `DATETIME` | Mốc thời gian bắt đầu sự cố. | `STR_TO_DATE(timestamp_start, '%Y-%m-%d %H:%i:%s')` | Must NOT BE NULL |
| `duration_min` | `INT` | `duration_min` | `INT` | Thời lượng sự cố kéo dài (phút). | Giữ nguyên gốc | **INVALID**: `<= 0` (bất khả thi) hoặc `> 10080` (> 7 ngày, vô lý) \| **WARNING**: `> 1440` (> 24h, bất thường nhưng có thể xảy ra với công trình đào đường lớn) \| **VALID**: `1–1440` |
| *(Mới)* | — | `timestamp_end` | `DATETIME` | **Thời điểm kết thúc sự cố**: Giúp Gold `JOIN` dữ liệu giao thông/môi trường trong đúng khoảng thời gian sự cố diễn ra (`recorded_at BETWEEN timestamp_start AND timestamp_end`). | `DATE_ADD(STR_TO_DATE(timestamp_start, '%Y-%m-%d %H:%i:%s'), INTERVAL duration_min MINUTE)` | Must BE `> timestamp_start` |
| `ingestion_time`| `DATETIME` | `ingestion_time`| `DATETIME` | Audit Trail 1: Mốc nạp vào Bronze. | Giữ nguyên gốc | Must NOT BE NULL |
| *(Mới)* | — | `record_status` | `VARCHAR(20)` | **Gatekeeper cho Gold** — 3 mức. | `CASE WHEN (incident_type NOT IN (...) OR duration_min <= 0 OR duration_min > 10080) THEN 'INVALID' WHEN duration_min > 1440 THEN 'WARNING' ELSE 'VALID' END` | Must IN (`'VALID'`, `'INVALID'`, `'WARNING'`) |
| *(Mới)* | — | `primary_dq_flag`| `VARCHAR(50)` | Lý do lỗi/cảnh báo chi tiết. | `CASE WHEN duration_min <= 0 THEN 'NEGATIVE_DURATION' WHEN duration_min > 10080 THEN 'DURATION_EXCEEDS_7DAYS' WHEN incident_type NOT IN (...) THEN 'INVALID_INCIDENT_TYPE' WHEN duration_min > 1440 THEN 'EXTENDED_INCIDENT_DURATION' ELSE 'OK' END` | Must NOT BE NULL |
| *(Mới)* | — | `processed_at` | `DATETIME` | Audit Trail 2: Mốc dbt transform. | `NOW()` | Must NOT BE NULL |
| *(Mới)* | — | `dbt_invocation_id`| `VARCHAR(100)`| Audit Trail 3: Mã lần chạy dbt. | `'{{ invocation_id }}'` | Must NOT BE NULL |

---

## 🏆 3. Chi Tiết Tầng Gold Datamarts & Semantic Layer (Cube.js)

### 3.1 Cấu Trúc Các Mô Hình Gold Datamarts (`starrocks_gold`)

#### 1. `gold_street_livability_daily` (Mart Chỉ số Đáng sống Tổng hợp theo Ngày)
* **Mục đích:** Thống kê chỉ số sức khỏe đô thị theo phân đoạn đường và từng ngày.
* **Công thức tổng hợp:**
  $$\text{Livability Index} = 0.35 \times S_{\text{Traffic}} + 0.25 \times S_{\text{Env}} + 0.20 \times S_{\text{Parking}} + 0.10 \times S_{\text{Lighting}} + 0.10 \times S_{\text{Safety}}$$
* **Fields:** `section_id`, `date_key`, `score_traffic`, `score_env`, `score_parking`, `score_lighting`, `score_safety`, `livability_index`.

#### 2. `fact_lighting` (Gold Mart Chiếu sáng SCADA)
* **Mục đích:** Phục vụ báo cáo tiêu thụ điện năng và quản lý hư hỏng thiết bị.
* **Điều kiện lọc dữ liệu hợp lệ (Data Quality):** `record_status IN ('VALID', 'WARNING')`.
* **Fields:** `id`, `section_id`, `pole_id`, `recorded_at`, `power_kwh`, `status`, `is_valid`, `data_quality_flag`.

#### 3. `fact_traffic`, `fact_parking`, `fact_environment`, `fact_incident`
* **Mục đích:** Gom nhóm dữ liệu đã làm sạch từ Silver Layer, chuyển hóa `record_status = 'VALID'` sang cờ boolean `is_valid = true` sẵn sàng cho BI Query.

---

### 🔮 3.2 Khai Báo Headless Semantic Layer (Cube.js Schemas)

* **Vị trí tệp:** `./model/cubes/`
* **Giao thức phục vụ:**
  - **REST API (Port 4000):** Tích hợp JWT Row-Level Security (`section_id`).
  - **Cube SQL API (Postgres Protocol - Port 15432):** Kết nối DirectQuery cho Power BI Desktop.
* **Quy tắc Aggregation & Interoperability:**
  - Các Measure trung bình (`avg_livability_index`, `avg_power_per_pole`, `avg_vehicle_count`...) được khai báo song song với chỉ số tổng tương ứng để hỗ trợ engine tự sinh SQL của Power BI.
  - Tên phân đoạn đường trong `dim_sections` được chuẩn hóa ký tự không dấu (`Central Gate`, `Apartment Zone`, `Villa Zone`) chống lỗi mã hóa font trên ODBC/Postgres Driver.

