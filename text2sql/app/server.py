"""FastAPI Server cho SmartCity AI & BI Platform Web UI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.catalog.cube_meta import fetch_catalog, parse_catalog
from app.catalog.models import Catalog
from app.catalog.sample_values import SampleValues
from app.config import settings
from app.llm.factory import get_llm_client
from app.nlu.orchestrator import NLUOrchestrator
from app.nlu.types import NLUStatus
from app.query_engine.cube_client import CubeClient, CubeQueryError
from app.retrieval.retriever import CatalogRetriever
import app.tracing as tracing

app = FastAPI(title="SmartCity AI Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = settings.sample_values_path.parent.parent / "web"


class ChatRequest(BaseModel):
    question: str


_catalog_cache: Catalog | None = None
_sample_values_cache: SampleValues | None = None
_retriever_cache: CatalogRetriever | None = None


def get_catalog() -> Catalog:
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache

    # 1. Ưu tiên lấy live catalog từ Cube Core API
    try:
        live_cat = fetch_catalog(settings.cube_api_url, settings.cube_api_token)
        if live_cat and live_cat.cubes:
            _catalog_cache = live_cat
            return _catalog_cache
    except Exception:
        pass

    # 2. Fallback sang file fixture JSON tĩnh nếu Cube Core chưa sẵn sàng
    meta_fixture = settings.sample_values_path.parent.parent / "tests" / "fixtures" / "cube_meta.json"
    if meta_fixture.exists():
        try:
            payload = json.loads(meta_fixture.read_text(encoding="utf-8"))
            _catalog_cache = parse_catalog(payload)
            return _catalog_cache
        except Exception:
            pass

    return Catalog(cubes=[])


def get_sample_values() -> SampleValues:
    global _sample_values_cache
    if _sample_values_cache is None:
        _sample_values_cache = SampleValues.load(settings.sample_values_path)
    return _sample_values_cache


def get_retriever(catalog: Catalog) -> CatalogRetriever:
    global _retriever_cache
    if _retriever_cache is None:
        _retriever_cache = CatalogRetriever(catalog)
    return _retriever_cache


@app.on_event("startup")
def warmup_services():
    """Pre-warm catalog, retriever and SentenceTransformer model into RAM at startup."""
    try:
        print("[WARMUP] Dang pre-warm Catalog & RAG Engine va RAM...")
        cat = get_catalog()
        get_sample_values()
        get_retriever(cat)
        print("[WARMUP] Pre-warm hoan tat! Fast-Reject RAG Engine va RAM san sang <0.001s!")
    except Exception as exc:
        print(f"[WARMUP WARNING] Pre-warm error: {exc}")


@app.on_event("shutdown")
def shutdown_tracing():
    """Flush pending Langfuse traces on server shutdown."""
    print("[Langfuse] Flushing traces...")
    tracing.flush()


@app.get("/api/catalog")
def api_catalog():
    """Trả về danh mục Data Dictionary cho Tab 3."""
    catalog = get_catalog()
    cubes_data = []
    for c in catalog.cubes:
        measures = [{"name": m.name, "title": m.title, "type": m.type, "description": m.description} for m in c.measures]
        dimensions = [{"name": d.name, "title": d.title, "type": d.type, "description": d.description} for d in c.dimensions]
        time_dims = [{"name": t.name, "title": t.title, "type": t.type, "description": t.description} for t in c.time_dimensions]
        cubes_data.append({
            "name": c.name,
            "title": c.title,
            "measures": measures,
            "dimensions": dimensions,
            "time_dimensions": time_dims,
        })
    return {"cubes": cubes_data}


@app.get("/api/superset_config")
def api_superset_config():
    """Expose Apache Superset iframe URL for BI Dashboard embedding."""
    return {"embed_url": settings.superset_embed_url.strip()}


@app.get("/api/powerbi_config")
def api_powerbi_config():
    """Alias for backwards compatibility, returning Apache Superset embed URL."""
    return api_superset_config()



@app.get("/api/dashboard_metrics")
def api_dashboard_metrics():
    """Lấy dữ liệu THẬT từ Cube Core (Port 4000) & StarRocks DW để render BI Dashboard."""
    with httpx.Client(timeout=10.0) as http_c:
        cube_client = CubeClient(settings=settings, client=http_c)
        
        # 1. AQI by District
        try:
            aqi_res = cube_client._post_load({
                "measures": ["air_quality.avg_aqi", "air_quality.avg_pm25"],
                "dimensions": ["districts.name"]
            })
            aqi_data = aqi_res.get("data", [])
        except Exception as e:
            print(f"Error loading AQI: {e}")
            aqi_data = []

        # 2. Traffic Flow & Speed
        try:
            traffic_res = cube_client._post_load({
                "measures": ["traffic_flow.avg_speed", "traffic_flow.sum_vehicle_count"],
                "dimensions": ["traffic_flow.camera_id"]
            })
            traffic_data = traffic_res.get("data", [])
        except Exception as e:
            print(f"Error loading Traffic: {e}")
            traffic_data = []

        # 3. Parking Occupancy
        try:
            parking_res = cube_client._post_load({
                "measures": ["smart_parking.avg_occupied_slots", "smart_parking.available_slots", "smart_parking.occupancy_pct"]
            })
            parking_data = parking_res.get("data", [])
        except Exception as e:
            print(f"Error loading Parking: {e}")
            parking_data = []

        # 4. Faulty Lamps & Lighting Power
        try:
            lighting_res = cube_client._post_load({
                "measures": ["smart_lighting.faulty_lamp_count", "smart_lighting.total_power_kwh"],
                "dimensions": ["smart_lighting.pole_id"]
            })
            lighting_data = lighting_res.get("data", [])
        except Exception as e:
            print(f"Error loading Lighting: {e}")
            lighting_data = []

        return {
            "aqi": aqi_data,
            "traffic": traffic_data,
            "parking": parking_data,
            "lighting": lighting_data
        }



@app.get("/api/lineage_graph")
def api_lineage_graph():
    """Trả về sơ đồ Lineage chi tiết cho từng bảng Bronze -> Silver -> Gold -> Cube -> LLM."""
    return {
        "columns": [
            {
                "layer": "Bronze (Raw Layer)",
                "color": "#84CC16",
                "nodes": [
                    {
                        "id": "bronze_environment",
                        "name": "bronze.bronze_environment",
                        "type": "Duplicated Log Table",
                        "db": "starrocks_bronze",
                        "columns": [
                            {"name": "event_id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY / NOT NULL", "desc": "Mã sự kiện cảm biến thô"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực/quận"},
                            {"name": "recorded_at", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận thô"},
                            {"name": "aqi", "type": "INT", "constraint": "NOT NULL", "desc": "Chỉ số AQI thô (0-500)"},
                            {"name": "pm25", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Nồng độ bụi mịn PM2.5"},
                            {"name": "noise_level_db", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Mức độ tiếng ồn (dB)"},
                            {"name": "ingestion_time", "type": "DATETIME", "constraint": "DEFAULT CURRENT_TIMESTAMP", "desc": "Thời gian nạp dữ liệu"}
                        ],
                        "rules": ["Cho phép trùng lặp log", "Chưa áp dụng làm sạch"]
                    },
                    {
                        "id": "bronze_parking",
                        "name": "bronze.bronze_parking",
                        "type": "Duplicated Log Table",
                        "db": "starrocks_bronze",
                        "columns": [
                            {"name": "event_id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY / NOT NULL", "desc": "Mã sự kiện bãi xe"},
                            {"name": "gw_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã Gateway bãi xe"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực/quận"},
                            {"name": "recorded_at", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận thô"},
                            {"name": "slot_total", "type": "INT", "constraint": "NOT NULL", "desc": "Tổng số chỗ đỗ xe"},
                            {"name": "occupied_slots", "type": "INT", "constraint": "NOT NULL", "desc": "Số chỗ đỗ đang occupied"},
                            {"name": "ingestion_time", "type": "DATETIME", "constraint": "DEFAULT CURRENT_TIMESTAMP", "desc": "Thời gian nạp dữ liệu"}
                        ],
                        "rules": ["Log sự kiện IoT từ Gateway"]
                    },
                    {
                        "id": "bronze_incident",
                        "name": "bronze.bronze_incident",
                        "type": "Duplicated Log Table",
                        "db": "starrocks_bronze",
                        "columns": [
                            {"name": "event_id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY / NOT NULL", "desc": "Mã sự cố thô"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực/quận"},
                            {"name": "incident_type", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Loại sự cố (ACCIDENT/FLOODING...)"},
                            {"name": "timestamp_start", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Thời điểm bắt đầu sự cố"},
                            {"name": "duration_min", "type": "INT", "constraint": "NOT NULL", "desc": "Thời gian kéo dài (phút)"}
                        ],
                        "rules": ["Thu thập từ tổng đài và camera"]
                    },
                    {
                        "id": "bronze_lighting",
                        "name": "bronze.bronze_lighting",
                        "type": "Duplicated Log Table",
                        "db": "starrocks_bronze",
                        "columns": [
                            {"name": "event_id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY / NOT NULL", "desc": "Mã log cột đèn thô"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực/quận"},
                            {"name": "pole_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã cột đèn chiếu sáng"},
                            {"name": "recorded_at", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận thô"},
                            {"name": "power_kwh", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điện năng tiêu thụ (kWh)"},
                            {"name": "status", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Trạng thái cột đèn (NORMAL/FAULTY)"}
                        ],
                        "rules": ["Ghi nhận chỉ số công tơ điện thông minh"]
                    },
                    {
                        "id": "bronze_traffic",
                        "name": "bronze.bronze_traffic",
                        "type": "Duplicated Log Table",
                        "db": "starrocks_bronze",
                        "columns": [
                            {"name": "event_id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY / NOT NULL", "desc": "Mã log camera giao thông"},
                            {"name": "device_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã thiết bị camera"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực/quận"},
                            {"name": "event_time", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận thô"},
                            {"name": "vehicle_count", "type": "INT", "constraint": "NOT NULL", "desc": "Số lượng xe đi qua"},
                            {"name": "avg_speed_kmh", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Tốc độ trung bình (km/h)"},
                            {"name": "overspeed_flag", "type": "BOOLEAN", "constraint": "NOT NULL", "desc": "Cờ báo vi phạm tốc độ"}
                        ],
                        "rules": ["Stream từ hệ thống Camera AI giao thông"]
                    }
                ]
            },
            {
                "layer": "Silver (Cleaned & Standardized)",
                "color": "#06B6D4",
                "nodes": [
                    {
                        "id": "silver_environment",
                        "name": "silver_environment",
                        "type": "Cleaned Table",
                        "db": "starrocks_silver",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY / UNIQUE", "desc": "ID chuẩn hóa"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm đã ép kiểu DATETIME"},
                            {"name": "aqi", "type": "INT", "constraint": "CHECK (aqi >= 0 AND aqi <= 500)", "desc": "Chỉ số AQI chuẩn"},
                            {"name": "pm25", "type": "DOUBLE", "constraint": "CHECK (pm25 >= 0)", "desc": "Bụi mịn PM2.5"},
                            {"name": "noise_level_db", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Độ ồn (dB)"},
                            {"name": "is_valid", "type": "BOOLEAN", "constraint": "DEFAULT true", "desc": "Đánh dấu dữ liệu hợp lệ"},
                            {"name": "data_quality_flag", "type": "VARCHAR(50)", "constraint": "ENUM ('PASSED', 'INVALID_RANGE')", "desc": "Kết quả Quality Check"}
                        ],
                        "rules": ["Khử trùng lặp theo event_id", "Lọc loại bỏ các bản ghi AQI âm hoặc rác"]
                    },
                    {
                        "id": "silver_parking",
                        "name": "silver_parking",
                        "type": "Cleaned Table",
                        "db": "starrocks_silver",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "ID chuẩn hóa"},
                            {"name": "gw_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Gateway bãi xe"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "slot_total", "type": "INT", "constraint": "CHECK (slot_total > 0)", "desc": "Tổng chỗ đỗ"},
                            {"name": "occupied_slots", "type": "INT", "constraint": "CHECK (occupied_slots <= slot_total)", "desc": "Chỗ đã sử dụng"},
                            {"name": "is_valid", "type": "BOOLEAN", "constraint": "DEFAULT true", "desc": "Đánh dấu hợp lệ"}
                        ],
                        "rules": ["Kiểm tra ràng buộc occupied_slots <= slot_total"]
                    },
                    {
                        "id": "silver_incident",
                        "name": "silver_incident",
                        "type": "Cleaned Table",
                        "db": "starrocks_silver",
                        "columns": [
                            {"name": "incident_id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã sự cố chuẩn"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực"},
                            {"name": "incident_type", "type": "VARCHAR(50)", "constraint": "ENUM ('ACCIDENT', 'FLOODING', 'ROAD_WORK')", "desc": "Phân loại sự cố"},
                            {"name": "timestamp_start", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời gian bắt đầu"},
                            {"name": "duration_min", "type": "INT", "constraint": "NOT NULL", "desc": "Thời lượng sự cố (phút)"}
                        ],
                        "rules": ["Chuẩn hóa phân loại sự cố"]
                    },
                    {
                        "id": "silver_lighting",
                        "name": "silver_lighting",
                        "type": "Cleaned Table",
                        "db": "starrocks_silver",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "ID chuẩn hóa"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực"},
                            {"name": "pole_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã cột đèn"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "power_kwh", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điện năng kWh"},
                            {"name": "status", "type": "VARCHAR(50)", "constraint": "ENUM ('NORMAL', 'FAULTY', 'DIMMED')", "desc": "Trạng thái cột đèn"}
                        ],
                        "rules": ["Lọc bản ghi đo điện bất thường"]
                    },
                    {
                        "id": "silver_traffic",
                        "name": "silver_traffic",
                        "type": "Cleaned Table",
                        "db": "starrocks_silver",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "ID chuẩn hóa"},
                            {"name": "device_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Camera ID"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã khu vực"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "vehicle_count", "type": "INT", "constraint": "NOT NULL", "desc": "Số xe đi qua"},
                            {"name": "avg_speed_kmh", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Tốc độ (km/h)"},
                            {"name": "overspeed_flag", "type": "BOOLEAN", "constraint": "NOT NULL", "desc": "Vi phạm tốc độ"}
                        ],
                        "rules": ["Tạo cờ overspeed_flag dựa trên max_speed_limit"]
                    }
                ]
            },
            {
                "layer": "Gold (Business Data Warehouse)",
                "color": "#3B82F6",
                "nodes": [
                    {
                        "id": "fact_environment",
                        "name": "fact_environment",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY / NOT NULL", "desc": "Mã bản ghi Fact môi trường"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "FOREIGN KEY ➔ dim_sections.id", "desc": "Khóa ngoại trỏ đến danh mục Quận/Huyện"},
                            {"name": "timestamp", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "aqi", "type": "INT", "constraint": "NOT NULL", "desc": "Chỉ số chất lượng không khí AQI"},
                            {"name": "pm25", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Nồng độ bụi mịn PM2.5 (µg/m³)"},
                            {"name": "noise_level_db", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Độ ồn đô thị (dB)"},
                            {"name": "is_valid", "type": "BOOLEAN", "constraint": "DEFAULT true", "desc": "Chỉ lấy các bản ghi hợp lệ trong Data Mart"}
                        ],
                        "rules": ["Tích hợp đường liên kết JOIN với dim_sections qua section_id"]
                    },
                    {
                        "id": "fact_parking",
                        "name": "fact_parking",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY / NOT NULL", "desc": "Mã bản ghi Fact bãi đỗ xe"},
                            {"name": "gw_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Gateway ID"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "FOREIGN KEY ➔ dim_sections.id", "desc": "Khóa ngoại trỏ đến Quận/Huyện"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "slot_total", "type": "INT", "constraint": "NOT NULL", "desc": "Tổng dung lượng bãi xe"},
                            {"name": "occupied_slots", "type": "INT", "constraint": "NOT NULL", "desc": "Số chỗ xe đang đỗ"},
                            {"name": "is_valid", "type": "BOOLEAN", "constraint": "DEFAULT true", "desc": "Bản ghi hợp lệ"}
                        ],
                        "rules": ["Tính toán các measures occupancy_pct và available_slots"]
                    },
                    {
                        "id": "gold_street_livability_daily",
                        "name": "gold_street_livability_daily",
                        "type": "Composite Aggregation Table",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "PRIMARY KEY (COMPOSITE)", "desc": "Mã quận/huyện"},
                            {"name": "date_key", "type": "DATE", "constraint": "PRIMARY KEY (COMPOSITE)", "desc": "Ngày tính toán"},
                            {"name": "score_traffic", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điểm số giao thông"},
                            {"name": "score_env", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điểm số môi trường"},
                            {"name": "score_parking", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điểm số bãi đỗ xe"},
                            {"name": "score_lighting", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điểm số chiếu sáng"},
                            {"name": "score_safety", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điểm số an toàn giao thông"},
                            {"name": "livability_index", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Chỉ số sống tốt đô thị (0-100)"}
                        ],
                        "rules": ["Tính toán tổng hợp daily từ 5 bảng Silver/Gold"]
                    },
                    {
                        "id": "fact_incident",
                        "name": "fact_incident",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "incident_id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã sự cố"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "FOREIGN KEY ➔ dim_sections.id", "desc": "Mã quận/huyện"},
                            {"name": "incident_type", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Loại sự cố"},
                            {"name": "timestamp_start", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm bắt đầu"},
                            {"name": "duration_min", "type": "INT", "constraint": "NOT NULL", "desc": "Thời lượng kéo dài (phút)"}
                        ],
                        "rules": ["Tự động tính severity level (MINOR/MAJOR/CRITICAL)"]
                    },
                    {
                        "id": "fact_lighting",
                        "name": "fact_lighting",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã bản ghi Fact chiếu sáng"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "FOREIGN KEY ➔ dim_sections.id", "desc": "Mã quận/huyện"},
                            {"name": "pole_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã cột đèn"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "power_kwh", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điện năng tiêu thụ (kWh)"},
                            {"name": "status", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Trạng thái đèm"}
                        ],
                        "rules": ["Tính toán faulty_lamp_count và faulty_lamp_pct"]
                    },
                    {
                        "id": "fact_traffic",
                        "name": "fact_traffic",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã bản ghi Fact giao thông"},
                            {"name": "device_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Camera ID"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "FOREIGN KEY ➔ dim_sections.id", "desc": "Mã quận/huyện"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "vehicle_count", "type": "INT", "constraint": "NOT NULL", "desc": "Số xe đi qua"},
                            {"name": "avg_speed_kmh", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Tốc độ trung bình (km/h)"},
                            {"name": "overspeed_flag", "type": "BOOLEAN", "constraint": "NOT NULL", "desc": "Vi phạm tốc độ"}
                        ],
                        "rules": ["Tính toán congestion_rate khi tốc độ < 15.0 km/h"]
                    }
                ]
            }
        ]
    }


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    """Xử lý câu hỏi tự nhiên qua LLM (provider chọn qua LLM_PROVIDER) + Cube Core."""
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống")

    catalog = get_catalog()
    sample_values = get_sample_values()
    retriever = get_retriever(catalog)

    try:
        llm = get_llm_client()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Lỗi khởi tạo LLM Client (provider={settings.llm_provider}): {exc}",
        )

    lf_trace = tracing.start_trace("smartcity_chat", metadata={"endpoint": "/api/chat", "question": req.question})

    orchestrator = NLUOrchestrator(
        catalog=catalog,
        llm_client=llm,
        sample_values=sample_values,
        settings=settings,
        retriever=retriever,
    )

    nlu_result = orchestrator.interpret(req.question, langfuse_trace=lf_trace)

    if nlu_result.status == NLUStatus.CLARIFICATION:
        res = {
            "status": "clarification",
            "answer": nlu_result.message,
            "query": None,
            "data": []
        }
        lf_trace.update(output=res)
        return res

    if nlu_result.status != NLUStatus.QUERY or not nlu_result.query:
        res = {
            "status": "error",
            "answer": f"Không thể tạo query: {nlu_result.message}",
            "errors": nlu_result.errors,
            "query": None,
            "data": []
        }
        lf_trace.update(output=res)
        return res

    query_payload = nlu_result.query.to_cube_payload()
    cube_client = CubeClient(settings=settings)

    cube_span = tracing.start_span(lf_trace, "cube_query", input=query_payload)
    try:
        cube_data = cube_client.load(nlu_result.query)
        cube_span.end(output={"rows": len(cube_data.get("data", []))})
    except CubeQueryError as exc:
        cube_span.end(output={"error": str(exc)}, level="ERROR")
        res = {
            "status": "cube_error",
            "answer": f"Lỗi truy vấn Cube Core: {exc}",
            "query": query_payload,
            "data": []
        }
        lf_trace.update(output=res)
        return res

    # NLG Phase
    nlg_prompt = """\
Bạn là Chuyên viên Phân tích Dữ liệu Đô thị Thông minh.
Hãy dựa vào kết quả JSON từ hệ thống để tổng hợp câu trả lời theo phong cách báo cáo quản trị chuyên nghiệp, chính xác và ngắn gọn bằng tiếng Việt.

# Quy tắc định dạng báo cáo (Formatting Rules):
1. **Tuyệt đối KHÔNG dùng icon hay emoji** (không sử dụng bất kỳ biểu tượng cảm xúc hay icon đồ họa nào).
2. **Không dùng bảng markdown** (để tránh lỗi dính dòng trên giao diện). Hãy trình bày thông tin dưới dạng danh sách gạch đầu dòng rõ ràng, phân cấp mạch lạc và có xuống dòng đầy đủ.
3. **Cấu trúc báo cáo**:
   - **Tóm tắt tổng quan**: 1 câu trả lời trực tiếp nội dung chính.
   - **Số liệu chi tiết**: Trình bày từng khu vực/hạng mục theo danh sách gạch đầu dòng, các chỉ số quan trọng được in đậm.
   - **Nhận xét chính**: 1 câu đánh giá tổng kết về điểm cao nhất, thấp nhất hoặc xu hướng chính.
4. **Định dạng số**: Làm tròn các con số thập phân đến 2 chữ số (ví dụ: 65.63, 63.90).
"""
    nlg_messages = [
        {"role": "user", "content": f"Câu hỏi: {req.question}\nKết quả JSON từ Cube:\n{json.dumps(cube_data, ensure_ascii=False)}"}
    ]

    nlg_gen = tracing.start_generation(
        lf_trace,
        name="nlg_answer",
        model=getattr(llm, "nlg_model", ""),
        input={"prompt": nlg_prompt, "messages": nlg_messages},
    )
    try:
        nlg_res = llm.generate_answer(nlg_prompt, nlg_messages)
        final_answer = nlg_res.text
        nlg_gen.end(output={"text": final_answer})
    except Exception as exc:
        final_answer = f"Đã có dữ liệu từ Cube Core nhưng lỗi tóm tắt NLG: {exc}"
        nlg_gen.end(output={"error": str(exc)}, level="ERROR")

    res = {
        "status": "success",
        "answer": final_answer,
        "query": query_payload,
        "data": cube_data.get("data", []),
        "annotation": cube_data.get("annotation", {})
    }
    lf_trace.update(output={"status": "success", "answer": final_answer})
    return res


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE Streaming Endpoint: Nhả token câu trả lời trực tiếp theo thời gian thực."""
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống")

    catalog = get_catalog()
    sample_values = get_sample_values()
    retriever = get_retriever(catalog)
    llm = get_llm_client()

    lf_trace = tracing.start_trace("smartcity_chat_stream", metadata={"endpoint": "/api/chat/stream", "question": req.question})

    orchestrator = NLUOrchestrator(
        catalog=catalog,
        llm_client=llm,
        sample_values=sample_values,
        settings=settings,
        retriever=retriever,
    )

    def event_generator():
        nlu_result = orchestrator.interpret(req.question, langfuse_trace=lf_trace)

        if nlu_result.status == NLUStatus.CLARIFICATION:
            payload = {"type": "meta", "status": "clarification", "answer": nlu_result.message, "query": None}
            lf_trace.update(output=payload)
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
            return

        if nlu_result.status != NLUStatus.QUERY or not nlu_result.query:
            payload = {"type": "meta", "status": "error", "answer": f"Không thể tạo query: {nlu_result.message}", "query": None}
            lf_trace.update(output=payload)
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
            return

        query_payload = nlu_result.query.to_cube_payload()
        cube_client = CubeClient(settings=settings)

        cube_span = tracing.start_span(lf_trace, "cube_query", input=query_payload)
        try:
            cube_data = cube_client.load(nlu_result.query)
            cube_span.end(output={"rows": len(cube_data.get("data", []))})
        except CubeQueryError as exc:
            cube_span.end(output={"error": str(exc)}, level="ERROR")
            payload = {"type": "meta", "status": "cube_error", "answer": f"Lỗi truy vấn Cube Core: {exc}", "query": query_payload}
            lf_trace.update(output=payload)
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
            return

        # Emit Metadata event first
        meta_payload = {
            "type": "meta",
            "status": "success",
            "query": query_payload,
            "data": cube_data.get("data", []),
            "annotation": cube_data.get("annotation", {})
        }
        yield f"data: {json.dumps(meta_payload, ensure_ascii=False)}\n\n"

        # Stream NLG text tokens
        nlg_prompt = """\
Bạn là Chuyên viên Phân tích Dữ liệu Đô thị Thông minh.
Hãy dựa vào kết quả JSON từ hệ thống để tổng hợp câu trả lời theo phong cách báo cáo quản trị chuyên nghiệp, chính xác và ngắn gọn bằng tiếng Việt.

# Quy tắc định dạng báo cáo (Formatting Rules):
1. **Tuyệt đối KHÔNG dùng icon hay emoji** (không sử dụng bất kỳ biểu tượng cảm xúc hay icon đồ họa nào).
2. **Không dùng bảng markdown** (để tránh lỗi dính dòng trên giao diện). Hãy trình bày thông tin dưới dạng danh sách gạch đầu dòng rõ ràng, phân cấp mạch lạc và có xuống dòng đầy đủ.
3. **Cấu trúc báo cáo**:
   - **Tóm tắt tổng quan**: 1 câu trả lời trực tiếp nội dung chính.
   - **Số liệu chi tiết**: Trình bày từng khu vực/hạng mục theo danh sách gạch đầu dòng, các chỉ số quan trọng được in đậm.
   - **Nhận xét chính**: 1 câu đánh giá tổng kết về điểm cao nhất, thấp nhất hoặc xu hướng chính.
4. **Định dạng số**: Làm tròn các con số thập phân đến 2 chữ số (ví dụ: 65.63, 63.90).
"""
        nlg_messages = [
            {"role": "user", "content": f"Câu hỏi: {req.question}\nKết quả JSON từ Cube:\n{json.dumps(cube_data, ensure_ascii=False)}"}
        ]

        nlg_gen = tracing.start_generation(
            lf_trace,
            name="nlg_answer_stream",
            model=getattr(llm, "nlg_model", ""),
            input={"prompt": nlg_prompt, "messages": nlg_messages},
        )
        full_text = []

        try:
            if hasattr(llm, "generate_answer_stream"):
                for chunk in llm.generate_answer_stream(nlg_prompt, nlg_messages):
                    full_text.append(chunk)
                    token_payload = {"type": "token", "content": chunk}
                    yield f"data: {json.dumps(token_payload, ensure_ascii=False)}\n\n"
            else:
                res = llm.generate_answer(nlg_prompt, nlg_messages)
                full_text.append(res.text)
                token_payload = {"type": "token", "content": res.text}
                yield f"data: {json.dumps(token_payload, ensure_ascii=False)}\n\n"

            final_ans = "".join(full_text)
            nlg_gen.end(output={"text": final_ans})
            lf_trace.update(output={"status": "success", "answer": final_ans})
        except Exception as exc:
            nlg_gen.end(output={"error": str(exc)}, level="ERROR")
            err_payload = {"type": "token", "content": f"\nLỗi Stream NLG: {exc}"}
            yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Mount Static Files and Root HTML
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
@app.get("/promax", response_class=HTMLResponse)
def index():
    html_path = WEB_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>SmartCity AI Platform Web UI</h1><p>Web UI index.html not found.</p>")


