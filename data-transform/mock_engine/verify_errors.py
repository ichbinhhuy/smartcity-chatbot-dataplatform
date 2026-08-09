import os
import sys
import json
import xml.etree.ElementTree as ET

# Force UTF-8 output encoding for Windows terminal compatibility
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LANDING_ZONE = os.path.join(os.path.dirname(BASE_DIR), "landing_zone")

def verify_injected_faults():
    print("================================================================================")
    print("         SMART CITY DATA LAKEHOUSE - FAULT INJECTION MANIFEST REPORT            ")
    print("================================================================================")

    # 1. Check Fault 1: Missing Required Field in Lighting XML
    lighting_dir = os.path.join(LANDING_ZONE, "lighting")
    xml_files = sorted([f for f in os.listdir(lighting_dir) if f.endswith(".xml")]) if os.path.exists(lighting_dir) else []
    
    missing_field_files = []
    for f_name in xml_files:
        f_path = os.path.join(lighting_dir, f_name)
        try:
            tree = ET.parse(f_path)
            root = tree.getroot()
            for pole in root.findall("pole"):
                p_id = pole.find("pole_id").text if pole.find("pole_id") is not None else ""
                power_tag = pole.find("power_kwh")
                if power_tag is None:
                    missing_field_files.append((f_name, p_id))
        except Exception as e:
            pass

    print(f"\n[FAULT 1] Missing Required Field (XML Schema Error -> NiFi DLQ Test)")
    print(f"   |-- Status: {'VERIFIED INJECTED' if len(missing_field_files) > 0 else 'NOT FOUND'}")
    print(f"   |-- Total Faulty Files Found: {len(missing_field_files)} files")
    for f_name, p_id in missing_field_files[:5]:
        print(f"   |-- Target File: landing_zone/lighting/{f_name} (Missing <power_kwh> in Pole: {p_id})")

    # 2. Check Fault 2: Business Rule Violation in Environment & Parking
    env_dir = os.path.join(LANDING_ZONE, "environment")
    park_dir = os.path.join(LANDING_ZONE, "parking")

    invalid_aqi_records = []
    if os.path.exists(env_dir):
        for f_name in sorted(os.listdir(env_dir)):
            if f_name.endswith(".json"):
                with open(os.path.join(env_dir, f_name), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        aqi_val = item.get("data", {}).get("aqi", 0)
                        if aqi_val < 0:
                            invalid_aqi_records.append((f_name, item.get("section_id"), aqi_val))

    invalid_park_records = []
    if os.path.exists(park_dir):
        for f_name in sorted(os.listdir(park_dir)):
            if f_name.endswith(".json"):
                with open(os.path.join(park_dir, f_name), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        tot = item.get("tot", 100)
                        occ = item.get("occ", 0)
                        if occ > tot or occ < 0:
                            invalid_park_records.append((f_name, item.get("gw"), occ, tot))

    print(f"\n[FAULT 2] Business Rule Violation (Data Quality Error -> dbt Silver Test)")
    print(f"   |-- Status: {'VERIFIED INJECTED' if (len(invalid_aqi_records) + len(invalid_park_records)) > 0 else 'NOT FOUND'}")
    print(f"   |-- Total AQI Violations (< 0): {len(invalid_aqi_records)} files")
    for f_name, sec, val in invalid_aqi_records:
        print(f"   |   +-- File: landing_zone/environment/{f_name} (Section: {sec} -> AQI: {val})")
    print(f"   |-- Total Parking Violations (occ > tot): {len(invalid_park_records)} files")
    for f_name, gw, occ, tot in invalid_park_records:
        print(f"   |   +-- File: landing_zone/parking/{f_name} (GW: {gw} -> occ: {occ}/{tot})")

    # 3. Check Fault 3: Duplicate Traffic Event IDs Across Files
    trf_dir = os.path.join(LANDING_ZONE, "traffic")
    seen_event_ids = {} # {event_id: first_file}
    duplicate_events = []

    if os.path.exists(trf_dir):
        for f_name in sorted(os.listdir(trf_dir)):
            if f_name.endswith(".json"):
                with open(os.path.join(trf_dir, f_name), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        evt_id = item.get("analytics", {}).get("summary", {}).get("id")
                        if evt_id:
                            if evt_id in seen_event_ids:
                                duplicate_events.append((evt_id, seen_event_ids[evt_id], f_name))
                            else:
                                seen_event_ids[evt_id] = f_name

    print(f"\n[FAULT 3] Duplicate Stream Event (At-least-once Retry -> dbt Dedup Test)")
    print(f"   |-- Status: {'VERIFIED INJECTED' if len(duplicate_events) > 0 else 'NOT FOUND'}")
    print(f"   |-- Total Duplicate Events Found: {len(duplicate_events)} pairs")
    for evt_id, f1, f2 in duplicate_events[:5]:
        print(f"   |   +-- Event ID '{evt_id}': Found in '{f1}' AND '{f2}'")

    print("\n================================================================================")

if __name__ == "__main__":
    verify_injected_faults()
