import os
import json
import csv
import random
import time
import math
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LANDING_ZONE = os.path.join(os.path.dirname(BASE_DIR), "landing_zone")

SECTIONS = ["section_1", "section_2", "section_3"]

# ==============================================================================
# FAULT INJECTION REGISTRY (BẢNG CẤU HÌNH TIÊM LỖI TẬP TRUNG — 5 FILES MỖI LOẠI)
# ==============================================================================
FAULT_CONFIG = {
    # 🔴 Lỗi 1: Missing Required Field (5 files SCADA Lighting XML thiếu <power_kwh>)
    "missing_field_lighting": {
        "enabled": True,
        "target_ticks": [80, 200, 340, 480, 600],
        "target_pole_id": "pole_section_1_05",
        "missing_tag": "power_kwh"
    },

    # 🟡 Lỗi 2: Business Rule Violation (5 files: 2 AQI âm + 3 Parking occupied_slots > slot_total)
    "business_rule_violation": {
        "enabled": True,
        "aqi_errors": [
            {"tick": 120, "section_id": "section_2", "invalid_val": -10},
            {"tick": 440, "section_id": "section_1", "invalid_val": -50}
        ],
        "parking_errors": [
            {"tick": 160, "gw_id": "GW_PARK_SECTION_1", "invalid_occ": 125},
            {"tick": 320, "gw_id": "GW_PARK_SECTION_2", "invalid_occ": 135},
            {"tick": 560, "gw_id": "GW_PARK_SECTION_3", "invalid_occ": 150}
        ]
    },

    # 🔵 Lỗi 3: Duplicate Stream Event Across Files (5 cặp files Traffic JSON trùng event_id)
    "duplicate_event_traffic": {
        "enabled": True,
        "target_pairs": [
            (100, 101),
            (220, 221),
            (350, 351),
            (490, 491),
            (620, 621)
        ]
    }
}

# ------------------------------------------------------------
# WORLD STATE ENGINE (Quản lý trạng thái chung liên domain)
# ------------------------------------------------------------
class WorldState:
    def __init__(self):
        self.active_incidents = {}
        self.latest_traffic = {s: 20 for s in SECTIONS}
        self.latest_parking = {s: 50 for s in SECTIONS}
        self.faulty_lamps = {}
        self.traffic_duplicates_queue = {} # {target_tick: record_to_inject}

    def clean_expired_states(self, current_dt):
        expired_incidents = [s for s, data in self.active_incidents.items() if data["end_time"] <= current_dt]
        for s in expired_incidents:
            del self.active_incidents[s]

        expired_lamps = [p for p, end_time in self.faulty_lamps.items() if end_time <= current_dt]
        for p in expired_lamps:
            del self.faulty_lamps[p]

state = WorldState()

def ensure_directories_and_clean():
    """Xóa dữ liệu cũ và tạo lại các thư mục landing_zone cho 5 domain"""
    domains = ["traffic", "parking", "environment", "lighting", "incident"]
    for d in domains:
        path = os.path.join(LANDING_ZONE, d)
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)
    print("[Clean] Cleared all old files in landing_zone!")

def generate_incident_data(current_dt, tick_index):
    """Domain 5: Incident -> CSV (.csv)"""
    if random.random() > 0.008:
        return

    timestamp_str = current_dt.strftime("%Y-%m-%d %H:%M:%S")
    section_id = random.choice(SECTIONS)
    
    if section_id in state.active_incidents:
        return

    inc_type = random.choices(["accident", "road_work", "traffic_light_failure"], weights=[5, 3, 2])[0]
    if inc_type == "road_work":
        duration_min = random.choice([120, 180, 240, 360])
    elif inc_type == "accident":
        duration_min = random.choice([30, 45, 60, 90])
    else:
        duration_min = random.choice([15, 30, 45])

    state.active_incidents[section_id] = {
        "end_time": current_dt + timedelta(minutes=duration_min),
        "type": inc_type
    }

    filename = f"incident_{current_dt.strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = os.path.join(LANDING_ZONE, "incident", filename)
    fieldnames = ["incident_id", "section_id", "incident_type", "timestamp_start", "duration_min", "source_system"]

    rows = [{
        "incident_id": f"inc_{int(current_dt.timestamp()*1000)}",
        "section_id": section_id,
        "incident_type": inc_type,
        "timestamp_start": timestamp_str,
        "duration_min": duration_min,
        "source_system": "traffic_police_excel_export"
    }]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def generate_traffic_data(current_dt, tick_index):
    """Domain 1: Traffic (9 Camera AI) -> Nested JSON AI (.json)"""
    timestamp_str = current_dt.strftime("%Y-%m-%d %H:%M:%S")
    hour = current_dt.hour
    is_weekend = current_dt.weekday() >= 5

    rush_1 = math.exp(-((hour - 8)**2) / 4)
    rush_2 = math.exp(-((hour - 18)**2) / 6)
    lunch_dip = 0.85 if 11 <= hour <= 13 else 1.0

    base_traffic = (55 + 190 * (rush_1 + rush_2)) * lunch_dip
    if 1 <= hour <= 4:
        base_traffic = 20.0
    if is_weekend:
        base_traffic *= 0.7 if hour < 12 else 1.35

    records = []
    first_record_copy = None

    for section_id in SECTIONS:
        incident_active = section_id in state.active_incidents
        
        section_total_v = 0
        for cam_idx in range(1, 4):
            cam_id = f"CAM_{section_id.upper()}_{cam_idx:02d}"
            v_count = max(10, int(random.gauss(base_traffic, 8)))
            avg_speed = max(5.0, round(random.gauss(25.0, 4.0), 1))

            if incident_active:
                v_count = max(1, int(v_count * 0.4))
                avg_speed = round(random.uniform(5.0, 10.0), 1)

            section_total_v += v_count

            camera_data = {
                "camera_meta": {
                    "device_id": cam_id,
                    "section_id": section_id,
                    "firmware_ver": "v2.4.1_edge"
                },
                "event_time": timestamp_str,
                "analytics": {
                    "frame_info": {"fps": 30, "resolution": "1080p"},
                    "summary": {
                        "id": f"trf_{int(current_dt.timestamp()*1000)}_{cam_idx}_{random.randint(100,999)}",
                        "vehicle_count": v_count,
                        "avg_speed_kmh": avg_speed,
                        "overspeed_flag": (avg_speed > 30.0) and (random.random() < 0.05)
                    },
                    "sample_detections": [
                        {
                            "vehicle_type": random.choices(["motorbike", "car", "bicycle"], weights=[6, 3, 1])[0],
                            "speed": max(5.0, round(random.gauss(avg_speed, 2.0), 1))
                        }
                        for _ in range(min(v_count, 3))
                    ]
                },
                "source_system": "nvidia_jetson_edge_ai"
            }
            records.append(camera_data)
            if first_record_copy is None:
                first_record_copy = json.loads(json.dumps(camera_data)) # Deep copy
        
        state.latest_traffic[section_id] = section_total_v

    # 🔵 FAULT 3 INJECTION: Duplicate Stream Event Across Files
    dup_cfg = FAULT_CONFIG["duplicate_event_traffic"]
    if dup_cfg["enabled"]:
        for src_t, tgt_t in dup_cfg["target_pairs"]:
            if tick_index == src_t and first_record_copy:
                state.traffic_duplicates_queue[tgt_t] = first_record_copy
            elif tick_index == tgt_t and tick_index in state.traffic_duplicates_queue:
                # Chèn record duplicate từ src_t vào file của tgt_t
                dup_rec = state.traffic_duplicates_queue.pop(tick_index)
                records.append(dup_rec)

    filename = f"traffic_{current_dt.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(LANDING_ZONE, "traffic", filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def generate_parking_data(current_dt, tick_index):
    """Domain 2: Smart Parking (3 Gateways / tot = 100 ô/section)"""
    timestamp_str = current_dt.strftime("%Y-%m-%d %H:%M:%S")
    records = []

    # 🟡 FAULT 2 CHECK: Parking Over-Capacity
    br_cfg = FAULT_CONFIG["business_rule_violation"]
    fault_park_map = {}
    if br_cfg["enabled"]:
        for p_err in br_cfg["parking_errors"]:
            if p_err["tick"] == tick_index:
                fault_park_map[p_err["gw_id"]] = p_err["invalid_occ"]

    for section_id in SECTIONS:
        gw_id = f"GW_PARK_{section_id.upper()}"
        curr_occ = state.latest_parking[section_id]
        recent_traffic = state.latest_traffic[section_id]
        
        bias = 2 if recent_traffic > 80 else (-2 if recent_traffic < 30 else 0)
        delta = random.choice([-3, -1, 0, 1, 3]) + bias
        new_occ = max(15, min(90, curr_occ + delta))

        # Nếu tick này bị tiêm lỗi, đè giá trị invalid
        if gw_id in fault_park_map:
            new_occ = fault_park_map[gw_id]

        state.latest_parking[section_id] = min(new_occ, 100) # WorldState giữ mức hợp lệ cho simulation

        records.append({
            "id": f"prk_{int(current_dt.timestamp()*1000)}_{random.randint(100,999)}",
            "gw": gw_id,
            "section_id": section_id,
            "recorded_at": timestamp_str,
            "tot": 100,
            "occ": new_occ, # Giá trị nạp vào file thô
            "source_system": "mqtt_lorawan_stream"
        })

    filename = f"parking_{current_dt.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(LANDING_ZONE, "parking", filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def generate_environment_data(current_dt, tick_index, is_hourly_tick=False):
    """Domain 3: Environment (3 Trạm quan trắc Môi trường) -> Hourly Batch"""
    if not is_hourly_tick:
        return

    timestamp_str = current_dt.strftime("%Y-%m-%d %H:%M:%S")
    records = []

    # 🟡 FAULT 2 CHECK: Negative AQI
    br_cfg = FAULT_CONFIG["business_rule_violation"]
    fault_aqi_map = {}
    if br_cfg["enabled"]:
        for a_err in br_cfg["aqi_errors"]:
            if a_err["tick"] == tick_index:
                fault_aqi_map[a_err["section_id"]] = a_err["invalid_val"]

    for section_id in SECTIONS:
        v_count = state.latest_traffic[section_id]
        calculated_noise = round(40.0 + (0.15 * v_count) + random.gauss(0, 1.5), 1)

        val_aqi = random.randint(45, 115)
        if section_id in fault_aqi_map:
            val_aqi = fault_aqi_map[section_id] # Tiêm AQI âm

        data = {
            "status": "ok",
            "section_id": section_id,
            "timestamp": timestamp_str,
            "data": {
                "id": f"env_{int(current_dt.timestamp()*1000)}_{random.randint(100,999)}",
                "aqi": val_aqi,
                "iaqi": {
                    "pm25": round(random.uniform(15.0, 50.0), 1)
                },
                "noise": {
                    "level_db": calculated_noise
                }
            },
            "source_system": "aqicn_api_nested"
        }
        records.append(data)

    filename = f"env_{current_dt.strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(LANDING_ZONE, "environment", filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

def generate_lighting_data(current_dt, tick_index):
    """Domain 4: Smart Lighting (30 Cột đèn đường) -> XML SCADA (.xml)"""
    timestamp_str = current_dt.strftime("%Y-%m-%d %H:%M:%S")
    root = ET.Element("lighting_batch")
    root.set("timestamp", timestamp_str)
    root.set("source_system", "scada_plc_xml")

    hour = current_dt.hour
    if 18 <= hour <= 23:
        base_power = 2.5
    elif 1 <= hour <= 5:
        base_power = 1.2
    else:
        base_power = 0.0

    # 🔴 FAULT 1 CHECK: Missing Required Field
    lgt_cfg = FAULT_CONFIG["missing_field_lighting"]
    is_missing_field_tick = (
        lgt_cfg["enabled"] and (tick_index in lgt_cfg["target_ticks"])
    )
    target_fault_pole = lgt_cfg["target_pole_id"]

    for section_id in SECTIONS:
        for pole_idx in range(1, 11):
            pole_id = f"pole_{section_id}_{pole_idx:02d}"
            
            if pole_id not in state.faulty_lamps:
                if random.random() < 0.002:
                    fault_duration_hours = random.randint(3, 6)
                    state.faulty_lamps[pole_id] = current_dt + timedelta(hours=fault_duration_hours)

            status_str = "FAULTY" if pole_id in state.faulty_lamps else "OK"
            current_power = 0.0 if status_str == "FAULTY" else (round(base_power + random.uniform(-0.1, 0.1), 2) if base_power > 0 else 0.0)

            pole_elem = ET.SubElement(root, "pole")
            ET.SubElement(pole_elem, "id").text = f"lgt_{int(current_dt.timestamp()*1000)}_{random.randint(100,999)}"
            ET.SubElement(pole_elem, "section_id").text = section_id
            ET.SubElement(pole_elem, "pole_id").text = pole_id
            ET.SubElement(pole_elem, "recorded_at").text = timestamp_str
            
            # Tiêm lỗi: Bỏ qua không ghi thẻ <power_kwh> nếu đúng tick & đúng pole_id
            if is_missing_field_tick and pole_id == target_fault_pole:
                pass # Skip <power_kwh>
            else:
                ET.SubElement(pole_elem, "power_kwh").text = str(current_power)

            ET.SubElement(pole_elem, "status").text = status_str

    tree = ET.ElementTree(root)
    filename = f"lighting_{current_dt.strftime('%Y%m%d_%H%M%S')}.xml"
    filepath = os.path.join(LANDING_ZONE, "lighting", filename)
    tree.write(filepath, encoding="utf-8", xml_declaration=True)

def generate_7_days_historical_batch():
    """Sinh bộ dữ liệu 7 ngày lịch sử kèm 5 file lỗi mỗi loại (Fresher MVP Generator)"""
    ensure_directories_and_clean()
    
    now = datetime.now()
    end_dt = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=7)
    step = timedelta(minutes=15)
    
    current_dt = start_dt
    total_ticks = int((end_dt - start_dt).total_seconds() / 900)
    
    print(f"=== FRESHER MVP MOCK GENERATOR (7 DAYS BATCH WITH FAULT INJECTION) ===")
    print(f"Scale: 9 AI Cameras, 300 Parking Sensors, 30 Smart Lighting Poles, 3 Env Nodes")
    print(f"Time Range: {start_dt} ---> {end_dt} ({total_ticks} ticks)")
    print(f"[Fault Injection] Ingesting 5 SCADA XML Missing Field, 5 Business Rule Violations, 5 Duplicate Stream Events...")

    ticks_count = 0
    while current_dt <= end_dt:
        state.clean_expired_states(current_dt)
        generate_incident_data(current_dt, ticks_count)
        generate_traffic_data(current_dt, ticks_count)
        generate_parking_data(current_dt, ticks_count)
        
        is_hourly = (ticks_count % 4 == 0)
        generate_environment_data(current_dt, ticks_count, is_hourly_tick=is_hourly)
        
        generate_lighting_data(current_dt, ticks_count)
        
        current_dt += step
        ticks_count += 1
        if ticks_count % 100 == 0:
            print(f"Progress: {ticks_count}/{total_ticks} ticks processed...")

    print("=== MOCK GENERATION COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    generate_7_days_historical_batch()
