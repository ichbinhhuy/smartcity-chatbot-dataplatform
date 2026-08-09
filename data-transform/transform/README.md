# Smart City Lakehouse — dbt Transform Project

## Mô tả
dbt project thực hiện tầng **Bronze → Silver → Gold** transformation cho hệ thống Smart Urban Street Lakehouse.

- **Adapter:** `dbt-starrocks`
- **Database Engine:** StarRocks 3.2 (cổng 9030)
- **Source DB:** `starrocks_bronze` (5 bảng raw)
- **Target DBs:** `starrocks_silver`, `starrocks_gold`

## Cấu trúc thư mục

```
transform/
├── dbt_project.yml         ← Cấu hình project
├── profiles.yml            ← Kết nối StarRocks (host, port, user)
└── models/
    ├── silver/             ← 5 Silver models (Cleanse, Dedup, DQ Flag)
    │   ├── silver_traffic.sql
    │   ├── silver_parking.sql
    │   ├── silver_environment.sql
    │   ├── silver_lighting.sql
    │   ├── silver_incident.sql
    │   ├── schema.yml      ← dbt auto tests (unique, not_null, accepted_values)
    │   └── sources.yml     ← Khai báo Bronze tables làm source
    └── gold/               ← (Sẽ tạo sau Silver hoàn thành)
```

## Chạy lệnh

```bash
cd transform

# 1. Kiểm tra kết nối StarRocks
dbt debug --profiles-dir .

# 2. Chạy toàn bộ Silver models
dbt run --profiles-dir . --select silver

# 3. Chạy auto tests (unique, not_null, accepted_values)
dbt test --profiles-dir . --select silver
```

## Silver Transformation Logic

| Bảng Silver | Dedup | Parse Datetime | DQ Flag |
|---|---|---|---|
| `silver_traffic` | ✅ ROW_NUMBER by event_id | `event_time` VARCHAR → DATETIME | NEGATIVE_SPEED, NEGATIVE_COUNT |
| `silver_parking` | ✅ ROW_NUMBER by event_id | `recorded_at` VARCHAR → DATETIME | OVERFLOW_PARKING (clamp LEAST) |
| `silver_environment` | ✅ ROW_NUMBER by event_id | `recorded_at` VARCHAR → DATETIME | INVALID_AQI, INVALID_PM25 |
| `silver_lighting` | ✅ ROW_NUMBER by event_id | `recorded_at` VARCHAR → DATETIME | NULL_POWER (COALESCE → 0.0) |
| `silver_incident` | ✅ ROW_NUMBER by incident_id | `timestamp_start` VARCHAR → DATETIME | + Derive `timestamp_end` |
