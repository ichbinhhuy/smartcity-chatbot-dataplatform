-- ============================================================
-- StarRocks Database Initialization Script for Smart Urban Street Lakehouse
-- Medallion Architecture: Bronze -> Silver -> Gold
-- ============================================================

-- ------------------------------------------------------------
-- CREATE DATABASES
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS starrocks_bronze;
CREATE DATABASE IF NOT EXISTS starrocks_silver;
CREATE DATABASE IF NOT EXISTS starrocks_gold;

-- ------------------------------------------------------------
-- 1. BRONZE LAYER (RAW DATA AUDIT - KEEP ALL DUPLICATES & ERRORS)
-- ------------------------------------------------------------
USE starrocks_bronze;

CREATE TABLE IF NOT EXISTS bronze_traffic (
  event_id VARCHAR(100) NOT NULL,
  device_id VARCHAR(50) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  event_time VARCHAR(50) NOT NULL,
  vehicle_count INT NOT NULL,
  avg_speed_kmh DOUBLE NOT NULL,
  overspeed_flag BOOLEAN NOT NULL,
  ingestion_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=OLAP
DUPLICATE KEY(event_id)
DISTRIBUTED BY HASH(event_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

CREATE TABLE IF NOT EXISTS bronze_parking (
  event_id VARCHAR(100) NOT NULL,
  gw_id VARCHAR(50) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  recorded_at VARCHAR(50) NOT NULL,
  slot_total INT NOT NULL,
  occupied_slots INT NOT NULL,
  ingestion_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=OLAP
DUPLICATE KEY(event_id)
DISTRIBUTED BY HASH(event_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

CREATE TABLE IF NOT EXISTS bronze_environment (
  event_id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  recorded_at VARCHAR(50) NOT NULL,
  aqi INT NOT NULL,
  pm25 DOUBLE NOT NULL,
  noise_level_db DOUBLE NOT NULL,
  ingestion_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=OLAP
DUPLICATE KEY(event_id)
DISTRIBUTED BY HASH(event_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

CREATE TABLE IF NOT EXISTS bronze_lighting (
  event_id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  pole_id VARCHAR(50) NOT NULL,
  recorded_at VARCHAR(50) NOT NULL,
  power_kwh DOUBLE, -- power_kwh can be null (Fault 1)
  status VARCHAR(50) NOT NULL,
  ingestion_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=OLAP
DUPLICATE KEY(event_id)
DISTRIBUTED BY HASH(event_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

CREATE TABLE IF NOT EXISTS bronze_incident (
  incident_id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  incident_type VARCHAR(50) NOT NULL,
  timestamp_start VARCHAR(50) NOT NULL,
  duration_min INT NOT NULL,
  ingestion_time DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=OLAP
DUPLICATE KEY(incident_id)
DISTRIBUTED BY HASH(incident_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- ------------------------------------------------------------
-- 2. SILVER LAYER (CLEANSED, VALIDATED, DEDUPLICATED)
-- ------------------------------------------------------------
USE starrocks_silver;

CREATE TABLE IF NOT EXISTS silver_traffic (
  id VARCHAR(100) NOT NULL,
  device_id VARCHAR(50) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  recorded_at DATETIME NOT NULL,
  vehicle_count INT NOT NULL,
  avg_speed_kmh DOUBLE NOT NULL,
  overspeed_flag BOOLEAN NOT NULL,
  is_valid BOOLEAN NOT NULL,
  data_quality_flag VARCHAR(50) NOT NULL
) ENGINE=OLAP
PRIMARY KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

CREATE TABLE IF NOT EXISTS silver_parking (
  id VARCHAR(100) NOT NULL,
  gw_id VARCHAR(50) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  recorded_at DATETIME NOT NULL,
  slot_total INT NOT NULL,
  occupied_slots INT NOT NULL,
  is_valid BOOLEAN NOT NULL,
  data_quality_flag VARCHAR(50) NOT NULL
) ENGINE=OLAP
PRIMARY KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

CREATE TABLE IF NOT EXISTS silver_environment (
  id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  timestamp DATETIME NOT NULL,
  aqi INT NOT NULL,
  pm25 DOUBLE NOT NULL,
  noise_level_db DOUBLE NOT NULL,
  is_valid BOOLEAN NOT NULL,
  data_quality_flag VARCHAR(50) NOT NULL
) ENGINE=OLAP
PRIMARY KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

CREATE TABLE IF NOT EXISTS silver_lighting (
  id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  pole_id VARCHAR(50) NOT NULL,
  recorded_at DATETIME NOT NULL,
  power_kwh DOUBLE NOT NULL,
  status VARCHAR(50) NOT NULL,
  is_valid BOOLEAN NOT NULL,
  data_quality_flag VARCHAR(50) NOT NULL
) ENGINE=OLAP
PRIMARY KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

CREATE TABLE IF NOT EXISTS silver_incident (
  incident_id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  incident_type VARCHAR(50) NOT NULL,
  timestamp_start DATETIME NOT NULL,
  duration_min INT NOT NULL
) ENGINE=OLAP
PRIMARY KEY(incident_id)
DISTRIBUTED BY HASH(incident_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- ------------------------------------------------------------
-- 3. GOLD LAYER (DATAMARTS - READ BY CUBE.JS)
-- ------------------------------------------------------------
USE starrocks_gold;

-- Static Dimension: dim_sections (Chiều Phân Đoạn Đường)
CREATE TABLE IF NOT EXISTS dim_sections (
  section_id VARCHAR(50) NOT NULL,
  section_name VARCHAR(100) NOT NULL,
  max_speed_limit INT NOT NULL,
  total_parking_slots INT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=OLAP
PRIMARY KEY(section_id)
DISTRIBUTED BY HASH(section_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- Insert Static Dimension Data
TRUNCATE TABLE dim_sections;
INSERT INTO dim_sections (section_id, section_name, max_speed_limit, total_parking_slots) VALUES
  ('section_1', 'Cổng chính - TTTM', 30, 100),
  ('section_2', 'Khu Căn hộ', 30, 100),
  ('section_3', 'Khu Biệt thự', 30, 100);

-- Fact Traffic
CREATE TABLE IF NOT EXISTS fact_traffic (
  id VARCHAR(100) NOT NULL,
  device_id VARCHAR(50) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  recorded_at DATETIME NOT NULL,
  vehicle_count INT NOT NULL,
  avg_speed_kmh DOUBLE NOT NULL,
  overspeed_flag BOOLEAN NOT NULL,
  is_valid BOOLEAN NOT NULL,
  data_quality_flag VARCHAR(50) NOT NULL
) ENGINE=OLAP
PRIMARY KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- Fact Parking
CREATE TABLE IF NOT EXISTS fact_parking (
  id VARCHAR(100) NOT NULL,
  gw_id VARCHAR(50) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  recorded_at DATETIME NOT NULL,
  slot_total INT NOT NULL,
  occupied_slots INT NOT NULL,
  is_valid BOOLEAN NOT NULL,
  data_quality_flag VARCHAR(50) NOT NULL
) ENGINE=OLAP
PRIMARY KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- Fact Environment
CREATE TABLE IF NOT EXISTS fact_environment (
  id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  timestamp DATETIME NOT NULL,
  aqi INT NOT NULL,
  pm25 DOUBLE NOT NULL,
  noise_level_db DOUBLE NOT NULL,
  is_valid BOOLEAN NOT NULL,
  data_quality_flag VARCHAR(50) NOT NULL
) ENGINE=OLAP
PRIMARY KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- Fact Lighting
CREATE TABLE IF NOT EXISTS fact_lighting (
  id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  pole_id VARCHAR(50) NOT NULL,
  recorded_at DATETIME NOT NULL,
  power_kwh DOUBLE NOT NULL,
  status VARCHAR(50) NOT NULL,
  is_valid BOOLEAN NOT NULL,
  data_quality_flag VARCHAR(50) NOT NULL
) ENGINE=OLAP
PRIMARY KEY(id)
DISTRIBUTED BY HASH(id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- Fact Incident
CREATE TABLE IF NOT EXISTS fact_incident (
  incident_id VARCHAR(100) NOT NULL,
  section_id VARCHAR(50) NOT NULL,
  incident_type VARCHAR(50) NOT NULL,
  timestamp_start DATETIME NOT NULL,
  duration_min INT NOT NULL
) ENGINE=OLAP
PRIMARY KEY(incident_id)
DISTRIBUTED BY HASH(incident_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");

-- gold_street_livability_daily
CREATE TABLE IF NOT EXISTS gold_street_livability_daily (
  section_id VARCHAR(50) NOT NULL,
  date_key DATE NOT NULL,
  score_traffic DOUBLE NOT NULL,
  score_env DOUBLE NOT NULL,
  score_parking DOUBLE NOT NULL,
  score_lighting DOUBLE NOT NULL,
  score_safety DOUBLE NOT NULL,
  livability_index DOUBLE NOT NULL
) ENGINE=OLAP
PRIMARY KEY(section_id, date_key)
DISTRIBUTED BY HASH(section_id) BUCKETS 4
PROPERTIES ("replication_num" = "1");
