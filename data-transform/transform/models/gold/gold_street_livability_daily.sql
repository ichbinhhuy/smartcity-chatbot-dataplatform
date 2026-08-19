-- gold_street_livability_daily.sql
-- dbt model tổng hợp KPI và điểm số livability index theo ngày và phân đoạn đường
-- Refactored: đọc từ 5 bảng fact_* (Gold) thay vì silver_* để đúng chuẩn Medallion Architecture

{{
    config(
        materialized='table',
        database='starrocks_gold',
        alias='gold_street_livability_daily'
    )
}}

WITH daily_traffic AS (
    SELECT
        section_id,
        DATE(recorded_at) AS date_key,
        AVG(avg_speed_kmh) AS avg_speed
    FROM {{ ref('fact_traffic') }}
    WHERE is_valid
    GROUP BY section_id, DATE(recorded_at)
),

daily_env AS (
    SELECT
        section_id,
        DATE(timestamp) AS date_key,
        AVG(aqi) AS avg_aqi
    FROM {{ ref('fact_environment') }}
    WHERE is_valid
    GROUP BY section_id, DATE(timestamp)
),

daily_parking AS (
    SELECT
        section_id,
        DATE(recorded_at) AS date_key,
        AVG(occupied_slots * 100.0 / slot_total) AS occ_pct
    FROM {{ ref('fact_parking') }}
    WHERE is_valid
    GROUP BY section_id, DATE(recorded_at)
),

daily_lighting AS (
    SELECT
        section_id,
        DATE(recorded_at) AS date_key,
        SUM(CASE WHEN status = 'FAULTY' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS faulty_pct
    FROM {{ ref('fact_lighting') }}
    WHERE is_valid AND status != 'WARNING'
    GROUP BY section_id, DATE(recorded_at)
),

daily_incident AS (
    SELECT
        section_id,
        DATE(timestamp_start) AS date_key,
        COUNT(*) AS incident_count
    FROM {{ ref('fact_incident') }}
    GROUP BY section_id, DATE(timestamp_start)
),

all_keys AS (
    SELECT section_id, date_key FROM daily_traffic
    UNION
    SELECT section_id, date_key FROM daily_env
    UNION
    SELECT section_id, date_key FROM daily_parking
    UNION
    SELECT section_id, date_key FROM daily_lighting
    UNION
    SELECT section_id, date_key FROM daily_incident
)

SELECT
    k.section_id,
    k.date_key,

    -- 1. Score Traffic (max 100, target 30 km/h)
    LEAST(100.0, COALESCE(t.avg_speed, 30.0) / 30.0 * 100.0) AS score_traffic,

    -- 2. Score Env (100 - AQI, min 0)
    GREATEST(0.0, 100.0 - COALESCE(e.avg_aqi, 50.0)) AS score_env,

    -- 3. Score Parking (100 - |occ_pct - 70| * 2, min 0)
    GREATEST(0.0, 100.0 - ABS(COALESCE(p.occ_pct, 70.0) - 70.0) * 2.0) AS score_parking,

    -- 4. Score Lighting (100 - faulty_pct * 100, min 0)
    GREATEST(0.0, 100.0 - (COALESCE(l.faulty_pct, 0.0) * 100.0)) AS score_lighting,

    -- 5. Score Safety (70 if incident exists, else 100)
    CASE WHEN COALESCE(i.incident_count, 0) > 0 THEN 70.0 ELSE 100.0 END AS score_safety,

    -- Composite Livability Index
    (
        0.35 * LEAST(100.0, COALESCE(t.avg_speed, 30.0) / 30.0 * 100.0) +
        0.25 * GREATEST(0.0, 100.0 - COALESCE(e.avg_aqi, 50.0)) +
        0.20 * GREATEST(0.0, 100.0 - ABS(COALESCE(p.occ_pct, 70.0) - 70.0) * 2.0) +
        0.10 * GREATEST(0.0, 100.0 - (COALESCE(l.faulty_pct, 0.0) * 100.0)) +
        0.10 * (CASE WHEN COALESCE(i.incident_count, 0) > 0 THEN 70.0 ELSE 100.0 END)
    ) AS livability_index

FROM all_keys k
LEFT JOIN daily_traffic t ON k.section_id = t.section_id AND k.date_key = t.date_key
LEFT JOIN daily_env e ON k.section_id = e.section_id AND k.date_key = e.date_key
LEFT JOIN daily_parking p ON k.section_id = p.section_id AND k.date_key = p.date_key
LEFT JOIN daily_lighting l ON k.section_id = l.section_id AND k.date_key = l.date_key
LEFT JOIN daily_incident i ON k.section_id = i.section_id AND k.date_key = i.date_key
