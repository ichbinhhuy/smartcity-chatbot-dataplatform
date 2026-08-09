import os, glob, requests, base64

STARROCKS_HOST = os.getenv("STARROCKS_HOST", "http://starrocks:8030")
DB = "starrocks_bronze"
AUTH_HEADER = "Basic " + base64.b64encode(b"root:").decode("utf-8")

def test_load(domain, filepath, headers):
    headers["Authorization"] = AUTH_HEADER
    headers["Expect"] = "100-continue"
    url = f"{STARROCKS_HOST}/api/{DB}/bronze_{domain}/_stream_load"
    with open(filepath, "rb") as f:
        res = requests.put(url, headers=headers, data=f, allow_redirects=True)
        print(f"=== Domain [{domain}] ===")
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text}\n")

if __name__ == "__main__":
    p_files = glob.glob("/opt/airflow/landing_zone/parking/*.json")
    if p_files:
        test_load("parking", p_files[0], {
            "format": "json",
            "strip_outer_array": "true",
            "jsonpaths": '["$.id", "$.gw", "$.section_id", "$.recorded_at", "$.tot", "$.occ"]',
            "columns": "event_id, gw_id, section_id, recorded_at, slot_total, occupied_slots"
        })

    e_files = glob.glob("/opt/airflow/landing_zone/environment/*.json")
    if e_files:
        test_load("environment", e_files[0], {
            "format": "json",
            "strip_outer_array": "true",
            "jsonpaths": '["$.data.id", "$.section_id", "$.timestamp", "$.data.aqi", "$.data.iaqi.pm25", "$.data.noise.level_db"]',
            "columns": "event_id, section_id, recorded_at, aqi, pm25, noise_level_db"
        })

    i_files = glob.glob("/opt/airflow/landing_zone/incident/*.csv")
    if i_files:
        test_load("incident", i_files[0], {
            "format": "csv",
            "column_separator": ",",
            "skip_header": "1",
            "columns": "incident_id, section_id, incident_type, timestamp_start, duration_min, temp_source"
        })
