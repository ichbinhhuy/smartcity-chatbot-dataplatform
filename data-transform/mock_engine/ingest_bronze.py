"""
ingest_bronze.py
================
Script nạp toàn bộ 2.193 file thô từ landing_zone/ trực tiếp vào 
StarRocks Internal OLAP Tables (starrocks_bronze) thông qua Stream Load HTTP API.

Tích hợp tự động Dead Letter Queue (DLQ / Quarantine) đẩy các bản ghi hỏng 
vào s3://landing-zone/quarantine/<domain>/ theo đúng architecture.md.
"""

import os
import glob
import json
import requests
import base64
import urllib.parse
from datetime import datetime
import xml.etree.ElementTree as ET
import boto3

STARROCKS_HOST = os.getenv("STARROCKS_HOST", "http://starrocks:8030")
DB = "starrocks_bronze"
AUTH_HEADER = "Basic " + base64.b64encode(b"root:").decode("utf-8")

# Khởi tạo Boto3 S3 Client cho DLQ Quarantine
s3_client = boto3.client(
    's3',
    endpoint_url=os.getenv("MINIO_HOST", "http://minio:9000"),
    aws_access_key_id='minioadmin',
    aws_secret_access_key='minioadmin',
    region_name='us-east-1'
)

def push_to_quarantine(domain, file_path, raw_payload, error_msg):
    """
    Đẩy bản ghi bị lỗi cấu trúc (Lỗi 1) vào thư mục Quarantine trên MinIO S3.
    Đường dẫn S3: s3://landing-zone/quarantine/<domain>/dlq_<timestamp>.json
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    key = f"quarantine/{domain}/dlq_{ts}.json"
    dlq_payload = {
        "source_file": str(file_path),
        "domain": domain,
        "error_reason": str(error_msg),
        "raw_payload": str(raw_payload),
        "quarantined_at": datetime.now().isoformat()
    }
    try:
        s3_client.put_object(
            Bucket="landing-zone",
            Key=key,
            Body=json.dumps(dlq_payload, ensure_ascii=False, indent=2).encode("utf-8")
        )
        print(f"  [DLQ TRIGGERED] Pushed bad record from {file_path} -> s3://landing-zone/{key}")
    except Exception as e:
        print(f"  [DLQ ERROR] Failed to push to quarantine: {e}")

def do_stream_load(url, headers, data):
    headers["Authorization"] = AUTH_HEADER
    res = requests.put(url, headers=headers, data=data, allow_redirects=False)
    if res.status_code in (307, 302, 301):
        redirect_url = res.headers.get("Location")
        if redirect_url:
            parsed = urllib.parse.urlparse(redirect_url)
            be_host = os.getenv("STARROCKS_BE_HOST", "starrocks")
            target_url = f"http://{be_host}:8040{parsed.path}"
            if parsed.query:
                target_url += f"?{parsed.query}"
            res = requests.put(target_url, headers=headers, data=data, allow_redirects=False)
    return res

def load_traffic():
    print("Ingesting Traffic JSON files...")
    files = glob.glob("landing_zone/traffic/*.json")
    total_files = len(files)
    count = 0
    for file_path in files:
        url = f"{STARROCKS_HOST}/api/{DB}/bronze_traffic/_stream_load"
        headers = {
            "Expect": "100-continue",
            "format": "json",
            "strip_outer_array": "true",
            "jsonpaths": '["$.analytics.summary.id", "$.camera_meta.device_id", "$.camera_meta.section_id", "$.event_time", "$.analytics.summary.vehicle_count", "$.analytics.summary.avg_speed_kmh", "$.analytics.summary.overspeed_flag"]',
            "columns": "event_id, device_id, section_id, event_time, vehicle_count, avg_speed_kmh, overspeed_flag"
        }
        try:
            with open(file_path, "rb") as f:
                res = do_stream_load(url, headers, f)
                if res.status_code == 200 and res.json().get("Status") == "Success":
                    count += 1
                else:
                    push_to_quarantine("traffic", file_path, "STREAM_LOAD_REJECTED", res.text)
        except Exception as e:
            push_to_quarantine("traffic", file_path, "UNREADABLE_FILE", e)
    print(f"Traffic Ingestion Complete: {count}/{total_files} files loaded successfully.")

def load_parking():
    print("Ingesting Parking JSON files...")
    files = glob.glob("landing_zone/parking/*.json")
    total_files = len(files)
    count = 0
    for file_path in files:
        url = f"{STARROCKS_HOST}/api/{DB}/bronze_parking/_stream_load"
        headers = {
            "Expect": "100-continue",
            "format": "json",
            "strip_outer_array": "true",
            "jsonpaths": '["$.id", "$.gw", "$.section_id", "$.recorded_at", "$.tot", "$.occ"]',
            "columns": "event_id, gw_id, section_id, recorded_at, slot_total, occupied_slots"
        }
        try:
            with open(file_path, "rb") as f:
                res = do_stream_load(url, headers, f)
                if res.status_code == 200 and res.json().get("Status") == "Success":
                    count += 1
                else:
                    push_to_quarantine("parking", file_path, "STREAM_LOAD_REJECTED", res.text)
        except Exception as e:
            push_to_quarantine("parking", file_path, "UNREADABLE_FILE", e)
    print(f"Parking Ingestion Complete: {count}/{total_files} files loaded successfully.")

def load_environment():
    print("Ingesting Environment JSON files...")
    files = glob.glob("landing_zone/environment/*.json")
    total_files = len(files)
    count = 0
    for file_path in files:
        url = f"{STARROCKS_HOST}/api/{DB}/bronze_environment/_stream_load"
        headers = {
            "Expect": "100-continue",
            "format": "json",
            "strip_outer_array": "true",
            "jsonpaths": '["$.data.id", "$.section_id", "$.timestamp", "$.data.aqi", "$.data.iaqi.pm25", "$.data.noise.level_db"]',
            "columns": "event_id, section_id, recorded_at, aqi, pm25, noise_level_db"
        }
        try:
            with open(file_path, "rb") as f:
                res = do_stream_load(url, headers, f)
                if res.status_code == 200 and res.json().get("Status") == "Success":
                    count += 1
                else:
                    push_to_quarantine("environment", file_path, "STREAM_LOAD_REJECTED", res.text)
        except Exception as e:
            push_to_quarantine("environment", file_path, "UNREADABLE_FILE", e)
    print(f"Environment Ingestion Complete: {count}/{total_files} files loaded successfully.")

def load_lighting():
    print("Ingesting Lighting XML files...")
    files = glob.glob("landing_zone/lighting/*.xml")
    total_files = len(files)
    count = 0
    for file_path in files:
        url = f"{STARROCKS_HOST}/api/{DB}/bronze_lighting/_stream_load"
        headers = {
            "Expect": "100-continue",
            "format": "json",
            "strip_outer_array": "true"
        }
        try:
            root = ET.parse(file_path).getroot()
            poles = []
            for pole in root.findall(".//pole"):
                power_el = pole.find("power_kwh")
                if power_el is None or power_el.text is None or not power_el.text.strip():
                    pole_str = ET.tostring(pole, encoding="unicode")
                    push_to_quarantine("lighting", file_path, pole_str, "MISSING_REQUIRED_FIELD: <power_kwh> is missing or empty")
                    continue
                
                power_kwh = float(power_el.text.strip())
                poles.append({
                    "event_id": pole.find("id").text if pole.find("id") is not None else "",
                    "section_id": pole.find("section_id").text if pole.find("section_id") is not None else "",
                    "pole_id": pole.find("pole_id").text if pole.find("pole_id") is not None else "",
                    "recorded_at": pole.find("recorded_at").text if pole.find("recorded_at") is not None else "",
                    "power_kwh": power_kwh,
                    "status": pole.find("status").text if pole.find("status") is not None else ""
                })
            json_bytes = json.dumps(poles).encode("utf-8")
            res = do_stream_load(url, headers, json_bytes)
            if res.status_code == 200 and res.json().get("Status") == "Success":
                count += 1
            else:
                push_to_quarantine("lighting", file_path, "STREAM_LOAD_REJECTED", res.text)
        except Exception as e:
            push_to_quarantine("lighting", file_path, "INVALID_XML_SYNTAX", e)
    print(f"Lighting Ingestion Complete: {count}/{total_files} files loaded successfully.")

def load_incident():
    print("Ingesting Incident CSV files...")
    files = glob.glob("landing_zone/incident/*.csv")
    total_files = len(files)
    count = 0
    for file_path in files:
        url = f"{STARROCKS_HOST}/api/{DB}/bronze_incident/_stream_load"
        headers = {
            "Expect": "100-continue",
            "format": "csv",
            "column_separator": ",",
            "skip_header": "1",
            "columns": "incident_id, section_id, incident_type, timestamp_start, duration_min, temp_dummy"
        }
        try:
            with open(file_path, "rb") as f:
                res = do_stream_load(url, headers, f)
                if res.status_code == 200 and res.json().get("Status") == "Success":
                    count += 1
                else:
                    push_to_quarantine("incident", file_path, "STREAM_LOAD_REJECTED", res.text)
        except Exception as e:
            push_to_quarantine("incident", file_path, "UNREADABLE_FILE", e)
    print(f"Incident Ingestion Complete: {count}/{total_files} files loaded successfully.")

if __name__ == "__main__":
    load_traffic()
    load_parking()
    load_environment()
    load_lighting()
    load_incident()
    print("ALL BRONZE STREAM LOAD INGESTION COMPLETED WITH DLQ SUPPORT!")
