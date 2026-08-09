-- fact_traffic.sql (Gold Datamart)
{{
    config(
        materialized='table',
        database='starrocks_gold',
        alias='fact_traffic'
    )
}}

SELECT
    id,
    device_id,
    CASE section_id
        WHEN 'section_2' THEN 'Khu biet thu'
        WHEN 'section_1' THEN 'Can ho'
        WHEN 'section_3' THEN 'TTTM'
        ELSE section_id
    END AS section_id,
    recorded_at,
    vehicle_count,
    avg_speed_kmh,
    overspeed_flag,
    (record_status = 'VALID') AS is_valid,
    primary_dq_flag AS data_quality_flag
FROM {{ ref('silver_traffic') }}
