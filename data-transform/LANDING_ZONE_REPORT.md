# Báo Cáo Kiểm Tra & Thống Kê Dữ Liệu Thô (Landing Zone Report)

> **Dự án:** Smart Urban Street Lakehouse  
> **Thời gian sinh data:** 7 ngày lịch sử (từ `2026-07-20 17:15:00` đến `2026-07-27 17:15:00`)  
> **Trạng thái:** ✅ Đã xóa data cũ & kiểm tra chính xác 100%

---

## 📊 1. Thống Kê Số Lượng File Thực Tế Trong Thư Mục `landing_zone/`

| Thư mục Domain | Định dạng File | Số lượng File thực tế | Tần suất Ingest | Mô phỏng nguồn thực tế |
|---|---|---|---|---|
| **`landing_zone/traffic/`** | `.json` (Nested JSON) | **673 files** | 15 phút / lần | 9 Camera AI (NVIDIA Jetson) phát stream JSON |
| **`landing_zone/parking/`** | `.json` (MQTT JSON) | **673 files** | 15 phút / lần | 3 Gateway LoRaWAN (300 ô đỗ) qua MQTT |
| **`landing_zone/environment/`**| `.json` (API JSON) | **169 files** | 1 giờ / lần | Crawl REST API thật từ AQICN / IQAir |
| **`landing_zone/lighting/`** | `.xml` (XML SCADA) | **673 files** | 15 phút / lần | Tủ điện SCADA / PLC điều khiển 30 cột đèn |
| **`landing_zone/incident/`** | `.csv` (CSV Report) | **6 files** | Ngẫu nhiên hiếm | Báo cáo ca trực xuất từ Excel của Cảnh sát GT |
| **TỔNG CỘNG** | — | **2.194 files** | — | **Dung lượng tổng: ~6.2 MB** |

---

## 🏷️ 2. Quy Tắc Đặt Tên & Danh Mục Hạ Tầng Thiết Bị

### 2.1 Quy tắc đặt tên tổng quát (Naming Convention)
$$\text{[LOẠI\_THIẾT\_BỊ]} \_ \text{[SECTION]} \_ \text{[SỐ\_THỨ\_TỰ]}$$

---

### 2.2 Danh mục chi tiết các thiết bị trong bộ data:

#### 📷 1. Camera AI Giao thông (9 Camera AI)
* **Section 1 (Cổng chính - TTTM):** `CAM_SECTION_1_01`, `CAM_SECTION_1_02`, `CAM_SECTION_1_03`
* **Section 2 (Khu Căn hộ):** `CAM_SECTION_2_01`, `CAM_SECTION_2_02`, `CAM_SECTION_2_03`
* **Section 3 (Khu Biệt thự):** `CAM_SECTION_3_01`, `CAM_SECTION_3_02`, `CAM_SECTION_3_03`

#### 🅿️ 2. Smart Parking Gateways (3 Gateways / 300 Cảm biến đỗ xe)
* `GW_PARK_SECTION_1` (Quản lý 100 ô đỗ ven đường Section 1)
* `GW_PARK_SECTION_2` (Quản lý 100 ô đỗ ven đường Section 2)
* `GW_PARK_SECTION_3` (Quản lý 100 ô đỗ ven đường Section 3)

#### 🌿 3. Trạm Quan trắc Môi trường (3 Trạm sensor AQI)
* Trạm Môi trường `section_1`
* Trạm Môi trường `section_2`
* Trạm Môi trường `section_3`

#### 💡 4. Cột Đèn đường Thông minh (30 Cột đèn LED SCADA)
* **Section 1 (10 cột):** `pole_section_1_01` ➔ `pole_section_1_10`
* **Section 2 (10 cột):** `pole_section_2_01` ➔ `pole_section_2_10`
* **Section 3 (10 cột):** `pole_section_3_01` ➔ `pole_section_3_10`

#### ⚠️ 5. Trạm Báo cáo Cảnh sát Giao thông
* `traffic_police_excel_export` (Xuất file CSV báo cáo các vụ `accident`, `road_work`, `traffic_light_failure`).

---

## 🔍 3. Xác Nhận Kiểm Tra Tính Nhất Quán Logic (Verification Check)

1. ✅ **WorldState Engine:** Các sự cố trong `incident/` khi diễn ra đã ép `traffic/` cùng mốc thời gian sụt giảm $60\%$ lưu lượng và tốc độ hạ xuống $5-10\text{ km/h}$.
2. ✅ **Traffic-to-Noise:** Độ ồn `noise_level_db` trong `environment/` được tính toán trực tiếp từ `vehicle_count` của `traffic/`.
3. ✅ **Faulty Lamp Persistence:** Các bóng đèn bị hỏng trong `lighting/` duy trì trạng thái `FAULTY` liên tục $3 - 6$ tiếng mới khôi phục về `OK`.
4. ✅ **Weekend Pattern:** Lưu lượng giao thông và đỗ xe ngày Thứ 7 & CN biến thiên khác biệt so với ngày tuần.

---

📌 **Kết luận:** Bộ dữ liệu thô trong `landing_zone/` hoàn toàn sạch sẽ, đạt chuẩn quy mô và sẵn sàng cho các tầng Ingestion & Transformation của Data Lakehouse!
