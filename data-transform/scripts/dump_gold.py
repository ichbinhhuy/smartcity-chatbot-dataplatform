#!/usr/bin/env python3
"""Script dump starrocks_gold thành file SQL có thể import lại."""

import subprocess
import sys

HOST = "127.0.0.1"
PORT = "9030"
DB = "starrocks_gold"
USER = "root"

TABLES = [
    "dim_sections",
    "fact_traffic",
    "fact_environment",
    "fact_incident",
    "fact_lighting",
    "fact_parking",
    "gold_street_livability_daily",
]

DDL_MAP = {
    "dim_sections": """CREATE TABLE IF NOT EXISTS `dim_sections` (
  `section_id` varchar(50) NOT NULL,
  `section_name` varchar(100) NOT NULL,
  `max_speed_limit` int(11) NOT NULL,
  `total_parking_slots` int(11) NOT NULL,
  `created_at` datetime NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=OLAP
PRIMARY KEY(`section_id`)
DISTRIBUTED BY HASH(`section_id`) BUCKETS 4
PROPERTIES ("replication_num" = "1", "enable_persistent_index" = "true", "compression" = "LZ4");""",

    "fact_traffic": """CREATE TABLE IF NOT EXISTS `fact_traffic` (
  `id` varchar(100) NULL,
  `device_id` varchar(50) NULL,
  `section_id` varchar(50) NULL,
  `recorded_at` datetime NULL,
  `vehicle_count` int(11) NULL,
  `avg_speed_kmh` decimal(38, 9) NULL,
  `overspeed_flag` boolean NULL,
  `is_valid` boolean NULL,
  `data_quality_flag` varchar(65533) NULL
) ENGINE=OLAP
DUPLICATE KEY(`id`)
DISTRIBUTED BY RANDOM
PROPERTIES ("replication_num" = "1", "compression" = "LZ4");""",

    "fact_environment": """CREATE TABLE IF NOT EXISTS `fact_environment` (
  `id` varchar(100) NULL,
  `section_id` varchar(50) NULL,
  `timestamp` datetime NULL,
  `aqi` int(11) NULL,
  `pm25` decimal(38, 9) NULL,
  `noise_level_db` decimal(38, 9) NULL,
  `is_valid` boolean NULL,
  `data_quality_flag` varchar(65533) NULL
) ENGINE=OLAP
DUPLICATE KEY(`id`)
DISTRIBUTED BY RANDOM
PROPERTIES ("replication_num" = "1", "compression" = "LZ4");""",

    "fact_incident": """CREATE TABLE IF NOT EXISTS `fact_incident` (
  `incident_id` varchar(100) NULL,
  `section_id` varchar(50) NULL,
  `incident_type` varchar(50) NULL,
  `timestamp_start` datetime NULL,
  `duration_min` int(11) NULL
) ENGINE=OLAP
DUPLICATE KEY(`incident_id`)
DISTRIBUTED BY RANDOM
PROPERTIES ("replication_num" = "1", "compression" = "LZ4");""",

    "fact_lighting": """CREATE TABLE IF NOT EXISTS `fact_lighting` (
  `id` varchar(100) NULL,
  `section_id` varchar(50) NULL,
  `pole_id` varchar(50) NULL,
  `recorded_at` datetime NULL,
  `power_kwh` decimal(38, 9) NULL,
  `status` varchar(50) NULL,
  `is_valid` boolean NULL,
  `data_quality_flag` varchar(65533) NULL
) ENGINE=OLAP
DUPLICATE KEY(`id`)
DISTRIBUTED BY RANDOM
PROPERTIES ("replication_num" = "1", "compression" = "LZ4");""",

    "fact_parking": """CREATE TABLE IF NOT EXISTS `fact_parking` (
  `id` varchar(100) NULL,
  `gw_id` varchar(50) NULL,
  `section_id` varchar(50) NULL,
  `recorded_at` datetime NULL,
  `slot_total` int(11) NULL,
  `occupied_slots` int(11) NULL,
  `is_valid` boolean NULL,
  `data_quality_flag` varchar(65533) NULL
) ENGINE=OLAP
DUPLICATE KEY(`id`)
DISTRIBUTED BY RANDOM
PROPERTIES ("replication_num" = "1", "compression" = "LZ4");""",

    "gold_street_livability_daily": """CREATE TABLE IF NOT EXISTS `gold_street_livability_daily` (
  `section_id` varchar(50) NULL,
  `date_key` date NULL,
  `score_traffic` decimal(38, 13) NULL,
  `score_env` decimal(38, 9) NULL,
  `score_parking` decimal(38, 13) NULL,
  `score_lighting` decimal(38, 8) NULL,
  `score_safety` decimal(4, 1) NULL,
  `livability_index` decimal(38, 9) NULL
) ENGINE=OLAP
DUPLICATE KEY(`section_id`)
DISTRIBUTED BY RANDOM
PROPERTIES ("replication_num" = "1", "compression" = "LZ4");""",
}

COLUMNS_MAP = {
    "dim_sections":                  ["section_id","section_name","max_speed_limit","total_parking_slots","created_at"],
    "fact_traffic":                  ["id","device_id","section_id","recorded_at","vehicle_count","avg_speed_kmh","overspeed_flag","is_valid","data_quality_flag"],
    "fact_environment":              ["id","section_id","timestamp","aqi","pm25","noise_level_db","is_valid","data_quality_flag"],
    "fact_incident":                 ["incident_id","section_id","incident_type","timestamp_start","duration_min"],
    "fact_lighting":                 ["id","section_id","pole_id","recorded_at","power_kwh","status","is_valid","data_quality_flag"],
    "fact_parking":                  ["id","gw_id","section_id","recorded_at","slot_total","occupied_slots","is_valid","data_quality_flag"],
    "gold_street_livability_daily":  ["section_id","date_key","score_traffic","score_env","score_parking","score_lighting","score_safety","livability_index"],
}

def q(val):
    """Quote a tab-separated value for SQL INSERT."""
    if val == "NULL" or val == "\\N":
        return "NULL"
    # Escape single quotes
    escaped = val.replace("'", "\\'")
    return f"'{escaped}'"

def mysql_cmd(sql):
    result = subprocess.run(
        ["mysql", "-uroot", f"-h{HOST}", f"-P{PORT}", DB,
         "--batch", "--skip-column-names", "-e", sql],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def export_table(table, out):
    cols = COLUMNS_MAP[table]
    col_list = ", ".join(f"`{c}`" for c in cols)
    
    # Fetch all rows
    raw = mysql_cmd(f"SELECT * FROM {table};")
    if not raw:
        out.write(f"-- Table {table}: EMPTY\n\n")
        return
    
    rows = raw.split("\n")
    batch_size = 500
    batch = []
    count = 0
    
    for line in rows:
        if not line.strip():
            continue
        values = line.split("\t")
        quoted = ", ".join(q(v) for v in values)
        batch.append(f"({quoted})")
        count += 1
        
        if len(batch) >= batch_size:
            out.write(f"INSERT INTO `{table}` ({col_list}) VALUES\n")
            out.write(",\n".join(batch))
            out.write(";\n\n")
            batch = []
    
    if batch:
        out.write(f"INSERT INTO `{table}` ({col_list}) VALUES\n")
        out.write(",\n".join(batch))
        out.write(";\n\n")
    
    print(f"  [{table}] exported {count} rows")

def main():
    out_path = "/tmp/starrocks_gold_dump.sql"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("-- ============================================================\n")
        f.write("-- StarRocks Gold Layer - Full Dump\n")
        f.write("-- Generated for SmartCity Data Platform\n")
        f.write("-- ============================================================\n\n")
        f.write("CREATE DATABASE IF NOT EXISTS starrocks_gold;\n")
        f.write("USE starrocks_gold;\n\n")
        
        for table in TABLES:
            f.write(f"-- ------------------------------------------------------------\n")
            f.write(f"-- Table: {table}\n")
            f.write(f"-- ------------------------------------------------------------\n")
            f.write(DDL_MAP[table])
            f.write("\n\n")
            print(f"Exporting {table}...")
            export_table(table, f)
    
    print(f"\nDone! Saved to {out_path}")

if __name__ == "__main__":
    main()
