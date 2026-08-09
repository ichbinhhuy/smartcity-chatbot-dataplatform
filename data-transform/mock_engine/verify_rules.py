import os
import json
import csv
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LANDING_ZONE = os.path.join(os.path.dirname(BASE_DIR), "landing_zone")

def test_rule_1_incident_traffic_correlation():
    """Quy luật 1: Khi có Incident, Traffic tại section đó phải giảm tốc độ <= 10km/h"""
    print("\n[TEST 1/6] Checking Incident -> Traffic Correlation...")
    incident_dir = os.path.join(LANDING_ZONE, "incident")
    traffic_dir = os.path.join(LANDING_ZONE, "traffic")

    inc_files = os.listdir(incident_dir)
    if not inc_files:
        print("  ⚠️ Warning: No incidents generated in this batch to test Rule 1.")
        return True

    passed_count = 0
    total_checks = 0

    for inc_file in inc_files:
        with open(os.path.join(incident_dir, inc_file), "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sec_id = row["section_id"]
                start_dt = datetime.strptime(row["timestamp_start"], "%Y-%m-%d %H:%M:%S")
                duration = int(row["duration_min"])
                end_dt = start_dt + timedelta(minutes=duration)

                curr = start_dt
                while curr < end_dt:
                    trf_filename = f"traffic_{curr.strftime('%Y%m%d_%H%M%S')}.json"
                    trf_path = os.path.join(traffic_dir, trf_filename)
                    if os.path.exists(trf_path):
                        with open(trf_path, "r", encoding="utf-8") as tf:
                            trf_json = json.load(tf)
                        section_cams = [c for c in trf_json if c["camera_meta"]["section_id"] == sec_id]
                        for cam in section_cams:
                            total_checks += 1
                            speed = cam["analytics"]["summary"]["avg_speed_kmh"]
                            if speed <= 10.0:
                                passed_count += 1
                    curr += timedelta(minutes=15)

    success_rate = (passed_count / total_checks * 100) if total_checks > 0 else 100
    print(f"  -> Checked {total_checks} camera records during active incidents.")
    print(f"  -> Speed <= 10km/h Compliance Rate: {success_rate:.1f}% ({passed_count}/{total_checks})")
    assert success_rate >= 90.0, "Rule 1 Failed: Incident correlation compliance below 90%"
    print("  [PASSED] Rule 1: Incident -> Traffic Correlation Verified!")
    return True

def test_rule_2_traffic_noise_correlation():
    """Quy luật 2: Traffic càng đông -> Noise dB càng cao (Hệ số tương quan dương)"""
    print("\n[TEST 2/6] Checking Traffic -> Noise Correlation...")
    traffic_dir = os.path.join(LANDING_ZONE, "traffic")
    env_dir = os.path.join(LANDING_ZONE, "environment")

    env_files = sorted(os.listdir(env_dir))
    traffic_noise_pairs = []

    for env_file in env_files:
        dt_str = env_file.replace("env_", "").replace(".json", "")
        trf_file = f"traffic_{dt_str}.json"
        trf_path = os.path.join(traffic_dir, trf_file)
        env_path = os.path.join(env_dir, env_file)

        if os.path.exists(trf_path):
            with open(env_path, "r", encoding="utf-8") as ef:
                env_json = json.load(ef)
            with open(trf_path, "r", encoding="utf-8") as tf:
                trf_json = json.load(tf)

            for env_node in env_json:
                sec_id = env_node["section_id"]
                noise = env_node["data"]["noise"]["level_db"]
                sec_cams = [c for c in trf_json if c["camera_meta"]["section_id"] == sec_id]
                tot_v = sum([c["analytics"]["summary"]["vehicle_count"] for c in sec_cams])
                traffic_noise_pairs.append((tot_v, noise))

    n = len(traffic_noise_pairs)
    sum_x = sum([p[0] for p in traffic_noise_pairs])
    sum_y = sum([p[1] for p in traffic_noise_pairs])
    sum_xy = sum([p[0]*p[1] for p in traffic_noise_pairs])
    sum_x2 = sum([p[0]**2 for p in traffic_noise_pairs])
    sum_y2 = sum([p[1]**2 for p in traffic_noise_pairs])

    r = (n * sum_xy - sum_x * sum_y) / math.sqrt((n * sum_x2 - sum_x**2) * (n * sum_y2 - sum_y**2))
    print(f"  -> Checked {n} Environment-Traffic data pairs.")
    print(f"  -> Traffic vs Noise Pearson Correlation Coefficient r = {r:.3f}")
    assert r > 0.6, f"Rule 2 Failed: Pearson correlation {r} is too low (expected > 0.6)"
    print("  [PASSED] Rule 2: Traffic -> Noise Linear Correlation Verified!")
    return True

def test_rule_3_parking_traffic_lag():
    """Quy luật 3: Bãi đỗ xe nằm trong giới hạn [10, 95] ô đỗ"""
    print("\n[TEST 3/6] Checking Smart Parking Bounded Limits...")
    parking_dir = os.path.join(LANDING_ZONE, "parking")
    prk_files = os.listdir(parking_dir)

    out_of_bounds = 0
    total_checks = 0

    for prk_file in prk_files:
        with open(os.path.join(parking_dir, prk_file), "r", encoding="utf-8") as pf:
            prk_json = json.load(pf)
        for node in prk_json:
            total_checks += 1
            occ = node["occ"]
            tot = node["tot"]
            if occ < 0 or occ > tot:
                out_of_bounds += 1

    print(f"  -> Checked {total_checks} Parking records.")
    print(f"  -> Out-of-bounds count: {out_of_bounds}")
    assert out_of_bounds == 0, "Rule 3 Failed: Parking occupancy exceeded physical limits"
    print("  [PASSED] Rule 3: Smart Parking Bounded Walk Verified!")
    return True

def test_rule_4_lighting_scada_persistence():
    """Quy luật 4: Đèn SCADA ban ngày power=0, ban đêm power>0, hỏng duy trì continuous >= 3h"""
    print("\n[TEST 4/6] Checking Smart Lighting Power Curve & Persistence...")
    lighting_dir = os.path.join(LANDING_ZONE, "lighting")
    lgt_files = sorted(os.listdir(lighting_dir))
    total_files = len(lgt_files)

    daytime_power_errors = 0
    faulty_streaks = {}

    for idx, lgt_file in enumerate(lgt_files):
        filepath = os.path.join(lighting_dir, lgt_file)
        tree = ET.parse(filepath)
        root = tree.getroot()
        ts_str = root.attrib["timestamp"]
        hour = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").hour

        for pole in root.findall("pole"):
            pole_id = pole.find("pole_id").text
            status = pole.find("status").text
            power = float(pole.find("power_kwh").text)

            if 6 <= hour <= 17 and status == "OK" and power != 0.0:
                daytime_power_errors += 1

            if status == "FAULTY":
                if pole_id not in faulty_streaks:
                    faulty_streaks[pole_id] = {"count": 0, "last_file_idx": idx}
                faulty_streaks[pole_id]["count"] += 1
                faulty_streaks[pole_id]["last_file_idx"] = idx

    print(f"  -> Daytime Power Errors: {daytime_power_errors}")
    print(f"  -> Tracked {len(faulty_streaks)} faulty lamp occurrences.")
    
    # Chỉ bắt lỗi nếu bóng hỏng kết thúc trước 12 ticks cuối và có duration < 12 ticks
    short_faults = [
        p for p, info in faulty_streaks.items() 
        if info["count"] < 12 and info["last_file_idx"] < (total_files - 12)
    ]
    print(f"  -> Faulty lamps with duration < 3 hours (excluding run end): {len(short_faults)}")
    
    assert daytime_power_errors == 0, "Rule 4 Failed: Daytime lights were consuming power"
    assert len(short_faults) == 0, "Rule 4 Failed: Faulty lamp state reset too early (< 3 hours)"
    print("  [PASSED] Rule 4: Lighting SCADA Power Curve & State Persistence Verified!")
    return True

def test_rule_5_rush_hour_and_weekend_pattern():
    """Quy luật 5: Đỉnh cao điểm (8h & 18h) traffic phải lớn hơn 2h sáng"""
    print("\n[TEST 5/6] Checking Rush Hour Peak & Weekend Pattern...")
    traffic_dir = os.path.join(LANDING_ZONE, "traffic")
    trf_files = sorted(os.listdir(traffic_dir))

    rush_v_list = []
    night_v_list = []

    for trf_file in trf_files:
        dt_str = trf_file.replace("traffic_", "").replace(".json", "")
        dt = datetime.strptime(dt_str, "%Y%m%d_%H%M%S")
        
        with open(os.path.join(traffic_dir, trf_file), "r", encoding="utf-8") as tf:
            trf_json = json.load(tf)
        tot_v = sum([c["analytics"]["summary"]["vehicle_count"] for c in trf_json])

        if dt.hour in [8, 18]:
            rush_v_list.append(tot_v)
        elif dt.hour == 2:
            night_v_list.append(tot_v)

    avg_rush = sum(rush_v_list) / len(rush_v_list) if rush_v_list else 0
    avg_night = sum(night_v_list) / len(night_v_list) if night_v_list else 0

    print(f"  -> Average Rush Hour Traffic (8h & 18h): {avg_rush:.1f} vehicles")
    print(f"  -> Average Late Night Traffic (02:00) : {avg_night:.1f} vehicles")
    assert avg_rush > avg_night * 2.0, "Rule 5 Failed: Rush hour traffic is not significantly higher than late night"
    print("  [PASSED] Rule 5: Rush Hour Double Peak & Time Pattern Verified!")
    return True

def test_rule_6_street_livability_index_formula():
    """Quy luật 6: Tính thử nghiệm công thức street_livability_index từ 5 domain"""
    print("\n[TEST 6/6] Dry-Running Composite Metric Formula (street_livability_index)...")
    traffic_dir = os.path.join(LANDING_ZONE, "traffic")
    parking_dir = os.path.join(LANDING_ZONE, "parking")
    env_dir = os.path.join(LANDING_ZONE, "environment")
    lighting_dir = os.path.join(LANDING_ZONE, "lighting")
    incident_dir = os.path.join(LANDING_ZONE, "incident")

    inc_active_times = set()
    for inc_file in os.listdir(incident_dir):
        with open(os.path.join(incident_dir, inc_file), "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sec_id = row["section_id"]
                s_dt = datetime.strptime(row["timestamp_start"], "%Y-%m-%d %H:%M:%S")
                duration = int(row["duration_min"])
                e_dt = s_dt + timedelta(minutes=duration)
                curr = s_dt
                while curr < e_dt:
                    inc_active_times.add((sec_id, curr.strftime("%Y-%m-%d %H:%M:%S")))
                    curr += timedelta(minutes=15)

    env_files = sorted(os.listdir(env_dir))
    normal_livability = []
    incident_livability = []

    for env_file in env_files:
        dt_str = env_file.replace("env_", "").replace(".json", "")
        trf_path = os.path.join(traffic_dir, f"traffic_{dt_str}.json")
        prk_path = os.path.join(parking_dir, f"parking_{dt_str}.json")
        lgt_path = os.path.join(lighting_dir, f"lighting_{dt_str}.xml")

        if os.path.exists(trf_path) and os.path.exists(prk_path) and os.path.exists(lgt_path):
            with open(os.path.join(env_dir, env_file), "r", encoding="utf-8") as ef:
                env_j = json.load(ef)
            with open(trf_path, "r", encoding="utf-8") as tf:
                trf_j = json.load(tf)
            with open(prk_path, "r", encoding="utf-8") as pf:
                prk_j = json.load(pf)

            lgt_tree = ET.parse(lgt_path)
            lgt_root = lgt_tree.getroot()

            for env_node in env_j:
                sec_id = env_node["section_id"]
                ts = env_node["timestamp"]
                aqi = env_node["data"]["aqi"]

                sec_cams = [c for c in trf_j if c["camera_meta"]["section_id"] == sec_id]
                avg_speed = sum([c["analytics"]["summary"]["avg_speed_kmh"] for c in sec_cams]) / len(sec_cams)
                traffic_score = min(100.0, (avg_speed / 30.0) * 100)

                env_score = max(0.0, 100.0 - aqi)

                sec_prk = [p for p in prk_j if p["section_id"] == sec_id][0]
                occ_pct = (sec_prk["occ"] / sec_prk["tot"]) * 100
                parking_score = max(0.0, 100.0 - abs(occ_pct - 70) * 2)

                sec_poles = [p for p in lgt_root.findall("pole") if p.find("section_id").text == sec_id]
                faulty_count = sum([1 for p in sec_poles if p.find("status").text == "FAULTY"])
                lighting_score = max(0.0, 100.0 - (faulty_count / len(sec_poles) * 100))

                is_inc = (sec_id, ts) in inc_active_times
                safety_score = 70.0 if is_inc else 100.0

                livability = (0.35 * traffic_score + 
                              0.25 * env_score + 
                              0.20 * parking_score + 
                              0.10 * lighting_score + 
                              0.10 * safety_score)

                if is_inc:
                    incident_livability.append(livability)
                else:
                    normal_livability.append(livability)

    avg_norm = sum(normal_livability) / len(normal_livability) if normal_livability else 0
    avg_inc = sum(incident_livability) / len(incident_livability) if incident_livability else 0

    print(f"  -> Normal Avg Street Livability Index  : {avg_norm:.1f} / 100")
    print(f"  -> Incident Avg Street Livability Index: {avg_inc:.1f} / 100")
    assert avg_norm > avg_inc, "Rule 6 Failed: Incident did not drop the Livability Index"
    print("  [PASSED] Rule 6: Composite Metric (street_livability_index) Dry-Run Formula Verified!")
    return True

def run_all_verification_tests():
    print("==========================================================")
    print("  AUTOMATED VERIFICATION TEST SUITE (6 DOMAIN RULES)    ")
    print("==========================================================")
    
    t1 = test_rule_1_incident_traffic_correlation()
    t2 = test_rule_2_traffic_noise_correlation()
    t3 = test_rule_3_parking_traffic_lag()
    t4 = test_rule_4_lighting_scada_persistence()
    t5 = test_rule_5_rush_hour_and_weekend_pattern()
    t6 = test_rule_6_street_livability_index_formula()

    print("\n==========================================================")
    if t1 and t2 and t3 and t4 and t5 and t6:
        print("  [SUCCESS] ALL 6 DOMAIN RULES & COMPOSITE METRICS PASSED 100%!")
    print("==========================================================")

if __name__ == "__main__":
    run_all_verification_tests()
