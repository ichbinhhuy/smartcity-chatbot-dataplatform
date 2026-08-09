"""
create_iceberg_bronze.py
========================
Đọc dữ liệu thô từ landing_zone/ và ghi vào MinIO S3 dưới dạng
Apache Iceberg Tables (Parquet format) thông qua PyIceberg + SqlCatalog.

Yêu cầu thư viện:
  pip install "pyiceberg[s3fs,sql-sqlite,pyarrow]" pyarrow s3fs
"""

import glob
import json
import csv
import xml.etree.ElementTree as ET
from datetime import datetime
import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema
from pyiceberg.types import (
    NestedField, StringType, IntegerType, DoubleType, BooleanType
)

# ============================================================
# PHẦN 1: KHỞI TẠO VÀ KẾT NỐI CATALOG (Quản lý Metadata con trỏ)
# ============================================================

# 1. Đọc cấu hình từ file .pyiceberg.yaml để kết nối catalog
# Catalog này trỏ tới một file SQLite cục bộ làm nơi lưu vết metadata
catalog = load_catalog("bronze_catalog")

# 2. Tạo namespace (Database lớn) tên là 'bronze_db' nếu chưa tồn tại
try:
    catalog.create_namespace("bronze_db")
    print("Created namespace: bronze_db")
except Exception:
    print("Namespace bronze_db already exists.")

# 3. Lấy thời gian hiện tại để ghi nhận cột ingestion_time (tracking)
NOW = datetime.now().isoformat()

# 4. Hàm bổ trợ: Xóa bảng cũ và tạo bảng mới hoàn toàn để làm sạch dữ liệu cũ
def recreate_table(name, schema):
    try:
        catalog.drop_table(name)
        print(f"Dropped existing table: {name}")
    except Exception:
        pass
    # Tạo bảng Iceberg mới với schema định nghĩa trước
    return catalog.create_table(name, schema=schema)


# ============================================================
# PHẦN 2: ĐỊNH NGHĨA SCHEMA (Iceberg Schema & PyArrow Schema)
# ============================================================

# ----------------- 1. BẢNG TRAFFIC (GIAO THÔNG) -----------------
# Schema của bảng SQL cuối cùng lưu trên MinIO (dành cho Query Engine)
SCHEMA_TRAFFIC = Schema(
    NestedField(1, "event_id",       StringType(),  required=False),
    NestedField(2, "device_id",      StringType(),  required=False),
    NestedField(3, "section_id",     StringType(),  required=False),
    NestedField(4, "event_time",     StringType(),  required=False),
    NestedField(5, "vehicle_count",  IntegerType(), required=False),
    NestedField(6, "avg_speed_kmh",  DoubleType(),  required=False),
    NestedField(7, "overspeed_flag", BooleanType(), required=False),
    NestedField(8, "ingestion_time", StringType(),  required=False),
)

# Schema ép kiểu trong bộ nhớ RAM của Python trước khi ghi đĩa
PA_SCHEMA_TRAFFIC = pa.schema([
    ("event_id", pa.string()),
    ("device_id", pa.string()),
    ("section_id", pa.string()),
    ("event_time", pa.string()),
    ("vehicle_count", pa.int32()),
    ("avg_speed_kmh", pa.float64()),
    ("overspeed_flag", pa.bool_()),
    ("ingestion_time", pa.string()),
])


# ----------------- 2. BẢNG PARKING (BÃI ĐỖ XE) -----------------
SCHEMA_PARKING = Schema(
    NestedField(1, "event_id",       StringType(),  required=False),
    NestedField(2, "gw_id",          StringType(),  required=False),
    NestedField(3, "section_id",     StringType(),  required=False),
    NestedField(4, "recorded_at",    StringType(),  required=False),
    NestedField(5, "slot_total",     IntegerType(), required=False),
    NestedField(6, "occupied_slots", IntegerType(), required=False),
    NestedField(7, "ingestion_time", StringType(),  required=False),
)

PA_SCHEMA_PARKING = pa.schema([
    ("event_id", pa.string()),
    ("gw_id", pa.string()),
    ("section_id", pa.string()),
    ("recorded_at", pa.string()),
    ("slot_total", pa.int32()),
    ("occupied_slots", pa.int32()),
    ("ingestion_time", pa.string()),
])


# ----------------- 3. BẢNG ENVIRONMENT (MÔI TRƯỜNG) -----------------
SCHEMA_ENVIRONMENT = Schema(
    NestedField(1, "event_id",       StringType(),  required=False),
    NestedField(2, "section_id",     StringType(),  required=False),
    NestedField(3, "recorded_at",    StringType(),  required=False),
    NestedField(4, "aqi",            IntegerType(), required=False),
    NestedField(5, "pm25",           DoubleType(),  required=False),
    NestedField(6, "noise_level_db", DoubleType(),  required=False),
    NestedField(7, "ingestion_time", StringType(),  required=False),
)

PA_SCHEMA_ENVIRONMENT = pa.schema([
    ("event_id", pa.string()),
    ("section_id", pa.string()),
    ("recorded_at", pa.string()),
    ("aqi", pa.int32()),
    ("pm25", pa.float64()),
    ("noise_level_db", pa.float64()),
    ("ingestion_time", pa.string()),
])


# ----------------- 4. BẢNG LIGHTING (HỆ THỐNG CHIẾU SÁNG SCADA) -----------------
SCHEMA_LIGHTING = Schema(
    NestedField(1, "event_id",       StringType(), required=False),
    NestedField(2, "section_id",     StringType(), required=False),
    NestedField(3, "pole_id",        StringType(), required=False),
    NestedField(4, "recorded_at",    StringType(), required=False),
    NestedField(5, "power_kwh",      DoubleType(), required=False),
    NestedField(6, "status",         StringType(), required=False),
    NestedField(7, "ingestion_time", StringType(), required=False),
)

PA_SCHEMA_LIGHTING = pa.schema([
    ("event_id", pa.string()),
    ("section_id", pa.string()),
    ("pole_id", pa.string()),
    ("recorded_at", pa.string()),
    ("power_kwh", pa.float64()),
    ("status", pa.string()),
    ("ingestion_time", pa.string()),
])


# ----------------- 5. BẢNG INCIDENT (SỰ CỐ GIAO THÔNG) -----------------
SCHEMA_INCIDENT = Schema(
    NestedField(1, "incident_id",    StringType(),  required=False),
    NestedField(2, "section_id",     StringType(),  required=False),
    NestedField(3, "incident_type",  StringType(),  required=False),
    NestedField(4, "timestamp_start", StringType(),  required=False),
    NestedField(5, "duration_min",   IntegerType(), required=False),
    NestedField(6, "ingestion_time", StringType(),  required=False),
)

PA_SCHEMA_INCIDENT = pa.schema([
    ("incident_id", pa.string()),
    ("section_id", pa.string()),
    ("incident_type", pa.string()),
    ("timestamp_start", pa.string()),
    ("duration_min", pa.int32()),
    ("ingestion_time", pa.string()),
])


# ============================================================
# PHẦN 3: CÁC HÀM XỬ LÝ NẠP DỮ LIỆU (Ingestion Logic)
# ============================================================

def ingest_traffic():
    """
    Nạp dữ liệu Traffic từ file JSON.
    Cấu trúc file JSON thô lồng nhau (nested), cần bóc tách phẳng ra.
    """
    print("\n[1/5] Ingesting Traffic JSON -> bronze_db.bronze_traffic ...")
    table = recreate_table("bronze_db.bronze_traffic", SCHEMA_TRAFFIC)
    records = []
    
    # Duyệt tìm toàn bộ file JSON trong thư mục traffic
    for fp in glob.glob("landing_zone/traffic/*.json"):
        rows = json.load(open(fp, encoding="utf-8"))
        for row in rows:
            try:
                # Làm phẳng dữ liệu JSON nested
                records.append({
                    "event_id":       row["analytics"]["summary"]["id"],
                    "device_id":      row["camera_meta"]["device_id"],
                    "section_id":     row["camera_meta"]["section_id"],
                    "event_time":     row["event_time"],
                    "vehicle_count":  row["analytics"]["summary"]["vehicle_count"],
                    "avg_speed_kmh":  float(row["analytics"]["summary"]["avg_speed_kmh"]),
                    "overspeed_flag": bool(row["analytics"]["summary"]["overspeed_flag"]),
                    "ingestion_time": NOW, # Thêm thời gian chạy script
                })
            except Exception as e:
                print(f"  Skip row in {fp}: {e}")
                
    if records:
        # Ép kiểu dữ liệu nghiêm ngặt bằng PyArrow Schema trước khi ghi
        arrow_table = pa.Table.from_pylist(records, schema=PA_SCHEMA_TRAFFIC)
        # Ghi file Parquet lên MinIO và commit vào Catalog
        table.append(arrow_table)
        print(f"  Done: {len(records)} rows -> bronze_traffic")
    else:
        print("  No records found for traffic.")


def ingest_parking():
    """
    Nạp dữ liệu bãi đỗ xe từ JSON.
    Làm phẳng và đổi tên cột thô (tot -> slot_total, occ -> occupied_slots).
    """
    print("\n[2/5] Ingesting Parking JSON -> bronze_db.bronze_parking ...")
    table = recreate_table("bronze_db.bronze_parking", SCHEMA_PARKING)
    records = []
    for fp in glob.glob("landing_zone/parking/*.json"):
        rows = json.load(open(fp, encoding="utf-8"))
        for row in rows:
            try:
                records.append({
                    "event_id":       row["id"],
                    "gw_id":          row["gw"],
                    "section_id":     row["section_id"],
                    "recorded_at":    row["recorded_at"],
                    "slot_total":     int(row["tot"]),
                    "occupied_slots": int(row["occ"]),
                    "ingestion_time": NOW,
                })
            except Exception as e:
                print(f"  Skip row in {fp}: {e}")
                
    if records:
        arrow_table = pa.Table.from_pylist(records, schema=PA_SCHEMA_PARKING)
        table.append(arrow_table)
        print(f"  Done: {len(records)} rows -> bronze_parking")
    else:
        print("  No records found for parking.")


def ingest_environment():
    """
    Nạp dữ liệu cảm biến môi trường từ JSON lồng nhau sâu (nested).
    Trích xuất aqi, pm25 và noise_level.
    """
    print("\n[3/5] Ingesting Environment JSON -> bronze_db.bronze_environment ...")
    table = recreate_table("bronze_db.bronze_environment", SCHEMA_ENVIRONMENT)
    records = []
    for fp in glob.glob("landing_zone/environment/*.json"):
        rows = json.load(open(fp, encoding="utf-8"))
        for row in rows:
            try:
                records.append({
                    "event_id":       row["data"]["id"],
                    "section_id":     row["section_id"],
                    "recorded_at":    row["timestamp"],
                    "aqi":            int(row["data"]["aqi"]),
                    "pm25":           float(row["data"]["iaqi"]["pm25"]),
                    "noise_level_db": float(row["data"]["noise"]["level_db"]),
                    "ingestion_time": NOW,
                })
            except Exception as e:
                print(f"  Skip row in {fp}: {e}")
                
    if records:
        arrow_table = pa.Table.from_pylist(records, schema=PA_SCHEMA_ENVIRONMENT)
        table.append(arrow_table)
        print(f"  Done: {len(records)} rows -> bronze_environment")
    else:
        print("  No records found for environment.")


def ingest_lighting():
    """
    Nạp dữ liệu chiếu sáng từ XML thô của hệ thống SCADA.
    Dùng ElementTree quét các tag <pole> lặp lại trong file XML.
    """
    print("\n[4/5] Ingesting Lighting XML -> bronze_db.bronze_lighting ...")
    table = recreate_table("bronze_db.bronze_lighting", SCHEMA_LIGHTING)
    records = []
    for fp in glob.glob("landing_zone/lighting/*.xml"):
        try:
            # Phân tích cây XML
            root = ET.parse(fp).getroot()
            for pole in root.findall(".//pole"):
                try:
                    power_el = pole.find("power_kwh")
                    if power_el is None or power_el.text is None or not power_el.text.strip():
                        pole_str = ET.tostring(pole, encoding="unicode")
                        push_to_quarantine("lighting", fp, pole_str, "MISSING_REQUIRED_FIELD: <power_kwh> is missing or empty")
                        continue
                    
                    power_kwh = float(power_el.text.strip())
                    records.append({
                        "event_id":       pole.find("id").text if pole.find("id") is not None else "",
                        "section_id":     pole.find("section_id").text if pole.find("section_id") is not None else "",
                        "pole_id":        pole.find("pole_id").text if pole.find("pole_id") is not None else "",
                        "recorded_at":    pole.find("recorded_at").text if pole.find("recorded_at") is not None else "",
                        "power_kwh":      power_kwh,
                        "status":         pole.find("status").text if pole.find("status") is not None else "",
                        "ingestion_time": NOW,
                    })
                except Exception as e:
                    push_to_quarantine("lighting", fp, ET.tostring(pole, encoding="unicode"), e)
        except Exception as e:
            print(f"  Error parsing {fp}: {e}")
            
    if records:
        arrow_table = pa.Table.from_pylist(records, schema=PA_SCHEMA_LIGHTING)
        table.append(arrow_table)
        print(f"  Done: {len(records)} rows -> bronze_lighting")
    else:
        print("  No records found for lighting.")


def ingest_incident():
    """
    Nạp dữ liệu sự cố giao thông từ file CSV phẳng.
    Dùng csv.DictReader đọc và chuyển đổi sang dạng bảng Iceberg.
    """
    print("\n[5/5] Ingesting Incident CSV -> bronze_db.bronze_incident ...")
    table = recreate_table("bronze_db.bronze_incident", SCHEMA_INCIDENT)
    records = []
    for fp in glob.glob("landing_zone/incident/*.csv"):
        with open(fp, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    records.append({
                        "incident_id":    row["incident_id"],
                        "section_id":     row["section_id"],
                        "incident_type":  row["incident_type"],
                        "timestamp_start":row["timestamp_start"],
                        "duration_min":   int(row["duration_min"]),
                        "ingestion_time": NOW,
                    })
                except Exception as e:
                    print(f"  Skip row in {fp}: {e}")
                    
    if records:
        arrow_table = pa.Table.from_pylist(records, schema=PA_SCHEMA_INCIDENT)
        table.append(arrow_table)
        print(f"  Done: {len(records)} rows -> bronze_incident")
    else:
        print("  No records found for incidents.")


# ============================================================
# PHẦN 4: KHỞI CHẠY (Main Execution)
# ============================================================
if __name__ == "__main__":
    # Lần lượt gọi 5 hàm nạp dữ liệu cho 5 domain
    ingest_traffic()
    ingest_parking()
    ingest_environment()
    ingest_lighting()
    ingest_incident()
    print("\nALL BRONZE ICEBERG TABLES CREATED SUCCESSFULLY ON MINIO!")
