"""FastAPI Server cho SmartCity Data Platform Web UI."""

from __future__ import annotations

import json
import os
import uuid
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
from app.session.factory import get_session_store
import app.tracing as tracing

app = FastAPI(title="SmartCity Data Platform", version="1.0.0")

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
    session_id: str | None = None


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
                "color": "#EAB308",
                "nodes": [
                    {
                        "id": "fact_environment",
                        "name": "fact_environment",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã bản ghi Fact môi trường"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Tên phân khu (Can ho, Khu biet thu, TTTM)"},
                            {"name": "timestamp", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận cảm biến"},
                            {"name": "aqi", "type": "INT", "constraint": "NOT NULL", "desc": "Chỉ số AQI chuẩn"},
                            {"name": "pm25", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Nồng độ bụi mịn PM2.5"},
                            {"name": "noise_level_db", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Mức độ tiếng ồn (dB)"},
                            {"name": "is_valid", "type": "BOOLEAN", "constraint": "DEFAULT true", "desc": "Cờ đánh dấu dữ liệu hợp lệ"},
                            {"name": "data_quality_flag", "type": "VARCHAR(50)", "constraint": "VARCHAR", "desc": "Cờ chất lượng dữ liệu"}
                        ],
                        "rules": ["Chuẩn hóa section_id sang tiếng Việt", "Kế thừa dữ liệu sạch từ silver_environment"]
                    },
                    {
                        "id": "fact_incident",
                        "name": "fact_incident",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "incident_id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã sự cố đô thị"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Tên phân khu (Can ho, Khu biet thu, TTTM)"},
                            {"name": "incident_type", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Loại sự cố (ACCIDENT, FLOODING, ROAD_WORK)"},
                            {"name": "timestamp_start", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm bắt đầu sự cố"},
                            {"name": "duration_min", "type": "INT", "constraint": "NOT NULL", "desc": "Thời lượng sự cố (phút)"}
                        ],
                        "rules": ["Chỉ lấy các sự cố hợp lệ record_status = 'VALID'", "Chuẩn hóa tên phân khu"]
                    },
                    {
                        "id": "fact_lighting",
                        "name": "fact_lighting",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã bản ghi Fact chiếu sáng"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Tên phân khu (Can ho, Khu biet thu, TTTM)"},
                            {"name": "pole_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Mã cột đèn chiếu sáng"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận công tơ"},
                            {"name": "power_kwh", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Điện năng tiêu thụ (kWh)"},
                            {"name": "status", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Trạng thái cột đèn (NORMAL, FAULTY, DIMMED)"},
                            {"name": "is_valid", "type": "BOOLEAN", "constraint": "DEFAULT true", "desc": "Cờ dữ liệu hợp lệ"},
                            {"name": "data_quality_flag", "type": "VARCHAR(50)", "constraint": "VARCHAR", "desc": "Cờ chất lượng dữ liệu"}
                        ],
                        "rules": ["Chuẩn hóa section_id", "Lọc dữ liệu hợp lệ và cảnh báo"]
                    },
                    {
                        "id": "fact_parking",
                        "name": "fact_parking",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã bản ghi Fact bãi đỗ xe"},
                            {"name": "gw_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Gateway ID bãi xe"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Tên phân khu (Can ho, Khu biet thu, TTTM)"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "slot_total", "type": "INT", "constraint": "NOT NULL", "desc": "Tổng số chỗ đỗ thiết kế"},
                            {"name": "occupied_slots", "type": "INT", "constraint": "NOT NULL", "desc": "Số chỗ đỗ đang sử dụng"},
                            {"name": "is_valid", "type": "BOOLEAN", "constraint": "DEFAULT true", "desc": "Cờ dữ liệu hợp lệ"},
                            {"name": "data_quality_flag", "type": "VARCHAR(50)", "constraint": "VARCHAR", "desc": "Cờ chất lượng dữ liệu"}
                        ],
                        "rules": ["Chuẩn hóa section_id", "Đổi tên occupied_slots_clean thành occupied_slots"]
                    },
                    {
                        "id": "fact_traffic",
                        "name": "fact_traffic",
                        "type": "Fact Table (OLAP)",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "id", "type": "VARCHAR(100)", "constraint": "PRIMARY KEY", "desc": "Mã bản ghi Fact giao thông"},
                            {"name": "device_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Camera ID"},
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "NOT NULL", "desc": "Tên phân khu (Can ho, Khu biet thu, TTTM)"},
                            {"name": "recorded_at", "type": "DATETIME", "constraint": "NOT NULL", "desc": "Thời điểm ghi nhận"},
                            {"name": "vehicle_count", "type": "INT", "constraint": "NOT NULL", "desc": "Số xe đi qua"},
                            {"name": "avg_speed_kmh", "type": "DOUBLE", "constraint": "NOT NULL", "desc": "Tốc độ trung bình (km/h)"},
                            {"name": "overspeed_flag", "type": "BOOLEAN", "constraint": "NOT NULL", "desc": "Cờ vi phạm tốc độ"},
                            {"name": "is_valid", "type": "BOOLEAN", "constraint": "DEFAULT true", "desc": "Cờ dữ liệu hợp lệ"},
                            {"name": "data_quality_flag", "type": "VARCHAR(50)", "constraint": "VARCHAR", "desc": "Cờ chất lượng dữ liệu"}
                        ],
                        "rules": ["Chuẩn hóa section_id sang tên phân khu rõ ràng"]
                    },
                    {
                        "id": "dim_sections",
                        "name": "dim_sections",
                        "type": "Static Dimension Table",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "PRIMARY KEY / NOT NULL", "desc": "Mã phân đoạn đường / khu vực"},
                            {"name": "section_name", "type": "VARCHAR(100)", "constraint": "NOT NULL", "desc": "Tên chuẩn hóa khu vực (TTTM, Khu Căn hộ, Khu Biệt thự)"},
                            {"name": "max_speed_limit", "type": "INT", "constraint": "NOT NULL", "desc": "Tốc độ tối đa cho phép (km/h)"},
                            {"name": "total_parking_slots", "type": "INT", "constraint": "NOT NULL", "desc": "Tổng số chỗ đỗ xe thiết kế"},
                            {"name": "created_at", "type": "DATETIME", "constraint": "DEFAULT CURRENT_TIMESTAMP", "desc": "Thời điểm tạo bản ghi danh mục"}
                        ],
                        "rules": ["Bảng chiều danh mục tĩnh (Master Data) dùng để JOIN ngữ cảnh khu vực cho tất cả các bảng Fact trong Gold Data Mart"]
                    },
                    {
                        "id": "gold_street_livability_daily",
                        "name": "gold_street_livability_daily",
                        "type": "Composite KPI Mart",
                        "db": "starrocks_gold",
                        "columns": [
                            {"name": "section_id", "type": "VARCHAR(50)", "constraint": "PRIMARY KEY", "desc": "Tên phân khu (Can ho, Khu biet thu, TTTM)"},
                            {"name": "date_key", "type": "DATE", "constraint": "PRIMARY KEY", "desc": "Ngày đánh giá chỉ số"},
                            {"name": "score_traffic", "type": "DOUBLE", "constraint": "0 - 100", "desc": "Điểm giao thông (trọng số 35%)"},
                            {"name": "score_env", "type": "DOUBLE", "constraint": "0 - 100", "desc": "Điểm chất lượng môi trường (trọng số 25%)"},
                            {"name": "score_parking", "type": "DOUBLE", "constraint": "0 - 100", "desc": "Điểm tiện ích bãi đỗ xe (trọng số 20%)"},
                            {"name": "score_lighting", "type": "DOUBLE", "constraint": "0 - 100", "desc": "Điểm chiếu sáng thông minh (trọng số 10%)"},
                            {"name": "score_safety", "type": "DOUBLE", "constraint": "0 - 100", "desc": "Điểm an toàn giao thông (trọng số 10%)"},
                            {"name": "livability_index", "type": "DOUBLE", "constraint": "0 - 100", "desc": "Chỉ số Đáng sống Tổng hợp đô thị"}
                        ],
                        "rules": [
                            "Tính toán từ 5 bảng fact_*",
                            "Công thức trung bình gia quyền Livability Index theo ngày"
                        ]
                    }
                ]
            }
        ]
    }


_SAVE_STATUSES = {NLUStatus.QUERY, NLUStatus.CLARIFICATION, NLUStatus.INVALID}


def _resolve_session(req_session_id: str | None) -> tuple[str, list[dict[str, Any]]]:
    """Sinh session_id mới nếu client chưa có; nạp history hiện có ([] nếu mới/hết hạn)."""
    session_id = req_session_id or uuid.uuid4().hex
    return session_id, get_session_store().get(session_id)


def _truncate_history(messages: list[dict[str, Any]], max_messages: int) -> list[dict[str, Any]]:
    """Giữ N message gần nhất, nhưng không được để message đầu còn lại là
    role="tool" (mồ côi, thiếu assistant.tool_calls đứng trước nó) — API kiểu
    OpenAI-compat sẽ trả 400 nếu history bắt đầu bằng 1 "tool" message như vậy."""
    if len(messages) <= max_messages:
        return messages
    trimmed = messages[-max_messages:]
    while trimmed and trimmed[0].get("role") == "tool":
        trimmed = trimmed[1:]
    return trimmed


def _apply_clarification_cap(session_id: str, nlu_result, catalog: Catalog) -> None:
    """Chặn vòng lặp clarification vô hạn: đếm số lượt CLARIFICATION liên
    tiếp trong session; vượt `settings.max_clarification_streak` -> đổi
    chiến lược, ghi đè `nlu_result` bằng danh mục đầy đủ thay vì tiếp tục
    hỏi trắc nghiệm hẹp. Mutate `nlu_result` tại chỗ (pydantic model không
    frozen) — phải gọi TRƯỚC khi response/payload được dựng từ nó.

    QUERY/INVALID coi như đã thoát khỏi vòng hỏi lại -> reset streak. Cố ý
    KHÔNG đụng streak khi ERROR/REFUSAL, nhất quán với `_SAVE_STATUSES`
    (2 status đó không có lượt assistant tương ứng được lưu vào history).
    """
    store = get_session_store()
    streak = store.get_clarification_streak(session_id)

    if nlu_result.status == NLUStatus.CLARIFICATION:
        streak += 1
        if streak > settings.max_clarification_streak:
            nlu_result.message = (
                "Mình vẫn chưa xác định rõ được yêu cầu của bạn sau vài lần hỏi lại. "
                "Đây là toàn bộ nhóm dữ liệu hệ thống đang hỗ trợ, bạn có thể chọn 1 trong các mục sau:"
            )
            nlu_result.suggestions = [c.title for c in catalog.cubes]
            streak = 0  # đã escalate — tính lại từ đầu
        store.set_clarification_streak(session_id, streak, ttl_seconds=settings.session_ttl_seconds)
    elif nlu_result.status in (NLUStatus.QUERY, NLUStatus.INVALID):
        store.set_clarification_streak(session_id, 0, ttl_seconds=settings.session_ttl_seconds)
    # ERROR/REFUSAL: không chạm streak.


def _persist_turn(session_id: str, nlu_result) -> None:
    """Lưu history sau lượt NLU — bỏ qua ERROR/REFUSAL vì NLUOrchestrator.interpret()
    không append lượt assistant tương ứng cho 2 status đó (xem app/nlu/orchestrator.py);
    lưu lại sẽ tạo 2 lượt "user" liên tiếp trong history, làm hỏng lượt gọi kế tiếp."""
    if nlu_result.status not in _SAVE_STATUSES:
        return
    trimmed = _truncate_history(nlu_result.messages, settings.max_history_messages)
    get_session_store().save(session_id, trimmed, ttl_seconds=settings.session_ttl_seconds)


def _resolve_prior_query(session_id: str) -> dict[str, Any] | None:
    """Bug 2 (kế hoạch fix Phase 2): lấy `CubeQuery` (dạng dict) của lần QUERY
    thành công gần nhất trong session — dùng làm nguồn dự phòng tất định cho
    `timeDimensions` khi lượt hiện tại bỏ trống (xem
    app/nlu/validator.py::validate)."""
    return get_session_store().get_last_query_context(session_id)


def _persist_prior_query(session_id: str, nlu_result) -> None:
    """Lưu lại query của lượt này làm ngữ cảnh cho lượt SAU — chỉ khi status
    QUERY (có `nlu_result.query` hợp lệ); CLARIFICATION/REFUSAL/ERROR/INVALID
    không ghi đè, để lượt query thành công gần nhất trước đó vẫn còn hiệu lực
    (vd hỏi lại giữa chừng không được xoá mất ngữ cảnh thời gian đã có)."""
    if nlu_result.status != NLUStatus.QUERY or not nlu_result.query:
        return
    get_session_store().set_last_query_context(
        session_id,
        nlu_result.query.model_dump(mode="json"),
        ttl_seconds=settings.session_ttl_seconds,
    )


# --------------------------------------------------------------------------
# NLG prompt/message builder — dùng chung cho /api/chat và /api/chat/stream
# (trước đây 2 khối này lặp gần như y hệt nhau, xem Bug 4 trong kế hoạch fix).
# --------------------------------------------------------------------------

_NLG_SYSTEM_PROMPT = """\
Bạn là Chuyên viên Phân tích Dữ liệu Đô thị Thông minh.
Hãy dựa vào kết quả JSON từ hệ thống để tổng hợp câu trả lời theo phong cách báo cáo quản trị chuyên nghiệp, chính xác và ngắn gọn bằng tiếng Việt.

# Quy tắc định dạng báo cáo (Formatting Rules):
1. **Tuyệt đối KHÔNG dùng icon hay emoji** (không sử dụng bất kỳ biểu tượng cảm xúc hay icon đồ họa nào).
2. **Không dùng bảng markdown** (để tránh lỗi dính dòng trên giao diện). Hãy trình bày thông tin dưới dạng danh sách gạch đầu dòng rõ ràng, phân cấp mạch lạc và có xuống dòng đầy đủ.
3. **Cấu trúc báo cáo**:
   - **Tóm tắt tổng quan**: 1 câu trả lời trực tiếp nội dung chính.
   - **Số liệu chi tiết**: CHỈ trình bày số liệu của đúng khu vực/đối tượng được hỏi trong câu hỏi. TUYỆT ĐỐI KHÔNG tự ý thêm dữ liệu của các khu vực/đối tượng khác không được đề cập.
4. **Định dạng số**: Làm tròn các con số thập phân đến 2 chữ số (ví dụ: 65.63, 63.90).
5. **TUYỆT ĐỐI KHÔNG nhận xét cảm tính**: Không được đưa ra bất kỳ đánh giá chủ quan nào (như 'khá tốt', 'tương đối cao', 'đáng lo ngại'). Chỉ báo cáo số liệu thuần túy từ JSON. Nếu không có bảng tiêu chuẩn ngưỡng nào được cung cấp trong yêu cầu, BỎ HOÀN TOÀN phần nhận xét.
"""

_TRUNCATED_NOTE = "\n\n*(Lưu ý: câu trả lời có thể đã bị cắt do vượt giới hạn độ dài.)*"


def _relabel_and_cap_rows(
    data: list[dict[str, Any]],
    query,
    max_rows: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """Đổi key thời gian ISO dài dòng (vd `street_incidents.timestamp_start`)
    thành nhãn ngắn `thoi_diem`, và nếu số dòng vượt `max_rows` thì cắt bớt +
    tóm tắt min/max/avg cho các trường số thay vì dump nguyên mảng thô vào
    prompt — dữ liệu quá dài dễ khiến model tự bịa format từng dòng hoặc lặp
    vô hạn (Bug 4). Trả về (rows đã xử lý, ghi chú tóm tắt nếu có cắt bớt).
    """
    time_dim_names = {td.dimension for td in (getattr(query, "timeDimensions", None) or [])}

    def _relabel(row: dict[str, Any]) -> dict[str, Any]:
        return {("thoi_diem" if k in time_dim_names else k): v for k, v in row.items()}

    relabeled = [_relabel(r) for r in data]

    if len(relabeled) <= max_rows:
        return relabeled, None

    numeric_keys = [
        k
        for k, v in relabeled[0].items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    summary: dict[str, dict[str, float]] = {}
    for k in numeric_keys:
        values = [r[k] for r in relabeled if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)]
        if values:
            summary[k] = {"min": min(values), "max": max(values), "avg": round(sum(values) / len(values), 2)}

    note = (
        f"Dữ liệu gốc có {len(relabeled)} dòng — chỉ đính kèm {max_rows} dòng đầu tiên bên dưới để "
        f"tránh vượt giới hạn prompt. Số liệu tổng hợp min/max/avg trên TOÀN BỘ {len(relabeled)} dòng "
        f"(dùng số này khi câu hỏi cần giá trị tổng thể, KHÔNG suy ra từ {max_rows} dòng mẫu bên dưới): "
        f"{json.dumps(summary, ensure_ascii=False)}"
    )
    return relabeled[:max_rows], note


def _build_nlg_messages(question: str, cube_data: dict[str, Any], query) -> list[dict[str, Any]]:
    """Dựng `messages` cho lượt NLG — dùng chung cho `/api/chat` và `/api/chat/stream`."""
    rows, note = _relabel_and_cap_rows(cube_data.get("data", []), query, settings.nlg_max_rows_in_prompt)
    prompt_payload = dict(cube_data)
    prompt_payload["data"] = rows
    content = f"Câu hỏi: {question}\nKết quả JSON từ Cube:\n{json.dumps(prompt_payload, ensure_ascii=False)}"
    if note:
        content += f"\n\n[Ghi chú hệ thống - không phải dữ liệu từ Cube]: {note}"
    return [{"role": "user", "content": content}]


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    """Xử lý câu hỏi tự nhiên qua LLM (provider chọn qua LLM_PROVIDER) + Cube Core."""
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Câu hỏi không được để trống")

    session_id, history = _resolve_session(req.session_id)

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

    prior_query = _resolve_prior_query(session_id)
    nlu_result = orchestrator.interpret(
        req.question, history=history, langfuse_trace=lf_trace, prior_query=prior_query
    )
    _apply_clarification_cap(session_id, nlu_result, catalog)
    _persist_turn(session_id, nlu_result)
    _persist_prior_query(session_id, nlu_result)

    if nlu_result.status == NLUStatus.CLARIFICATION:
        res = {
            "status": "clarification",
            "answer": nlu_result.message,
            "query": None,
            "data": [],
            "session_id": session_id,
            "suggestions": nlu_result.suggestions,
        }
        lf_trace.end(output=res)
        return res

    if nlu_result.status == NLUStatus.REFUSAL:
        res = {
            "status": "refusal",
            "answer": nlu_result.message,
            "refusal_reason": nlu_result.refusal_reason,
            "query": None,
            "data": [],
            "session_id": session_id,
        }
        lf_trace.end(output=res)
        return res

    if nlu_result.status != NLUStatus.QUERY or not nlu_result.query:
        res = {
            "status": "error",
            "answer": f"Không thể tạo query: {nlu_result.message}",
            "errors": nlu_result.errors,
            "query": None,
            "data": [],
            "session_id": session_id,
        }
        lf_trace.end(output=res)
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
            "data": [],
            "session_id": session_id,
        }
        lf_trace.end(output=res)
        return res

    # NLG Phase
    nlg_prompt = _NLG_SYSTEM_PROMPT
    nlg_messages = _build_nlg_messages(req.question, cube_data, nlu_result.query)

    nlg_gen = tracing.start_generation(
        lf_trace,
        name="nlg_answer",
        model=getattr(llm, "nlg_model", ""),
        input={"prompt": nlg_prompt, "messages": nlg_messages},
    )
    try:
        nlg_res = llm.generate_answer(nlg_prompt, nlg_messages)
        final_answer = nlg_res.text
        if nlg_res.finish_reason == "length":
            final_answer += _TRUNCATED_NOTE
        nlg_gen.end(output={"text": final_answer, "finish_reason": nlg_res.finish_reason})
    except Exception as exc:
        final_answer = f"Đã có dữ liệu từ Cube Core nhưng lỗi tóm tắt NLG: {exc}"
        nlg_gen.end(output={"error": str(exc)}, level="ERROR")

    res = {
        "status": "success",
        "answer": final_answer,
        "query": query_payload,
        "data": cube_data.get("data", []),
        "annotation": cube_data.get("annotation", {}),
        "session_id": session_id,
    }
    lf_trace.end(output={"status": "success", "answer": final_answer})
    return res


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE Streaming Endpoint: Nhả token câu trả lời trực tiếp theo thời gian thực."""
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

    lf_trace = tracing.start_trace("smartcity_chat_stream", metadata={"endpoint": "/api/chat/stream", "question": req.question})

    orchestrator = NLUOrchestrator(
        catalog=catalog,
        llm_client=llm,
        sample_values=sample_values,
        settings=settings,
        retriever=retriever,
    )

    def event_generator():
        session_id, history = _resolve_session(req.session_id)
        prior_query = _resolve_prior_query(session_id)
        nlu_result = orchestrator.interpret(
            req.question, history=history, langfuse_trace=lf_trace, prior_query=prior_query
        )
        _apply_clarification_cap(session_id, nlu_result, catalog)
        _persist_turn(session_id, nlu_result)
        _persist_prior_query(session_id, nlu_result)

        if nlu_result.status == NLUStatus.CLARIFICATION:
            payload = {
                "type": "meta",
                "status": "clarification",
                "answer": nlu_result.message,
                "query": None,
                "session_id": session_id,
                "suggestions": nlu_result.suggestions,
            }
            lf_trace.end(output=payload)
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
            return

        if nlu_result.status == NLUStatus.REFUSAL:
            payload = {
                "type": "meta",
                "status": "refusal",
                "answer": nlu_result.message,
                "refusal_reason": nlu_result.refusal_reason,
                "query": None,
                "session_id": session_id,
            }
            lf_trace.end(output=payload)
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
            return

        if nlu_result.status != NLUStatus.QUERY or not nlu_result.query:
            payload = {
                "type": "meta",
                "status": "error",
                "answer": f"Không thể tạo query: {nlu_result.message}",
                "query": None,
                "session_id": session_id,
            }
            lf_trace.end(output=payload)
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
            payload = {
                "type": "meta",
                "status": "cube_error",
                "answer": f"Lỗi truy vấn Cube Core: {exc}",
                "query": query_payload,
                "session_id": session_id,
            }
            lf_trace.end(output=payload)
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
            return

        # Emit Metadata event first
        meta_payload = {
            "type": "meta",
            "status": "success",
            "query": query_payload,
            "data": cube_data.get("data", []),
            "annotation": cube_data.get("annotation", {}),
            "session_id": session_id,
        }
        yield f"data: {json.dumps(meta_payload, ensure_ascii=False)}\n\n"

        # Stream NLG text tokens
        nlg_prompt = _NLG_SYSTEM_PROMPT
        nlg_messages = _build_nlg_messages(req.question, cube_data, nlu_result.query)

        nlg_gen = tracing.start_generation(
            lf_trace,
            name="nlg_answer_stream",
            model=getattr(llm, "nlg_model", ""),
            input={"prompt": nlg_prompt, "messages": nlg_messages},
        )
        full_text = []
        finish_reason = None

        try:
            if hasattr(llm, "generate_answer_stream"):
                for chunk in llm.generate_answer_stream(nlg_prompt, nlg_messages):
                    full_text.append(chunk)
                    token_payload = {"type": "token", "content": chunk}
                    yield f"data: {json.dumps(token_payload, ensure_ascii=False)}\n\n"
                finish_reason = getattr(llm, "last_finish_reason", None)
            else:
                res = llm.generate_answer(nlg_prompt, nlg_messages)
                full_text.append(res.text)
                token_payload = {"type": "token", "content": res.text}
                yield f"data: {json.dumps(token_payload, ensure_ascii=False)}\n\n"
                finish_reason = res.finish_reason

            if finish_reason == "length":
                full_text.append(_TRUNCATED_NOTE)
                note_payload = {"type": "token", "content": _TRUNCATED_NOTE}
                yield f"data: {json.dumps(note_payload, ensure_ascii=False)}\n\n"

            final_ans = "".join(full_text)
            nlg_gen.end(output={"text": final_ans, "finish_reason": finish_reason})
            lf_trace.end(output={"status": "success", "answer": final_ans})
        except Exception as exc:
            nlg_gen.end(output={"error": str(exc)}, level="ERROR")
            lf_trace.end(output={"error": str(exc)}, level="ERROR")
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
    return HTMLResponse(content="<h1>SmartCity Data Platform Web UI</h1><p>Web UI index.html not found.</p>")


