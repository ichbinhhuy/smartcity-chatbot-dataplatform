{{
    config(
        materialized='table',
        database='starrocks_silver',
        alias='silver_traffic'
    )
}}

WITH ranked AS (
    SELECT
        event_id                                                     AS id,
        device_id,
        section_id,
        STR_TO_DATE(event_time, '%Y-%m-%d %H:%i:%s')               AS recorded_at,
        vehicle_count,
        avg_speed_kmh,
        overspeed_flag,
        ingestion_time,
        ROW_NUMBER() OVER (
            PARTITION BY event_id
            ORDER BY ingestion_time DESC
        )                                                            AS rn
    FROM {{ source('bronze', 'bronze_traffic') }}
)

SELECT
    id,
    device_id,
    section_id,
    recorded_at,
    vehicle_count,
    avg_speed_kmh,
    overspeed_flag,

    -- ==========================================================
    -- RECORD STATUS — 3-tier: INVALID / WARNING / VALID
    -- INVALID : physically impossible or hardware error
    -- WARNING : technically possible but statistically anomalous
    -- VALID   : normal operational range
    -- ==========================================================
    CASE
        -- INVALID: hard errors (physically impossible / missing)
        WHEN id IS NULL OR id = ''                                           THEN 'INVALID'
        WHEN device_id IS NULL                                               THEN 'INVALID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3')      THEN 'INVALID'
        WHEN recorded_at IS NULL                                             THEN 'INVALID'
        WHEN vehicle_count IS NULL OR vehicle_count < 0                      THEN 'INVALID'
        WHEN avg_speed_kmh IS NULL OR avg_speed_kmh < 0 OR avg_speed_kmh > 120 THEN 'INVALID'
        WHEN overspeed_flag IS NULL                                          THEN 'INVALID'
        -- WARNING: anomalous but technically possible
        -- vehicle_count > 200 = ~800 vehicles/hour on a local urban road (extreme)
        WHEN vehicle_count > 200                                             THEN 'WARNING'
        -- avg_speed_kmh > 60 = 2x the 30 km/h limit as average, extremely anomalous
        WHEN avg_speed_kmh > 60                                              THEN 'WARNING'
        ELSE                                                                      'VALID'
    END                                                              AS record_status,

    -- ==========================================================
    -- PRIMARY DQ FLAG — first violated rule (most specific)
    -- ==========================================================
    CASE
        WHEN id IS NULL OR id = ''                                           THEN 'NULL_EVENT_ID'
        WHEN device_id IS NULL                                               THEN 'NULL_DEVICE_ID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3')      THEN 'INVALID_SECTION'
        WHEN recorded_at IS NULL                                             THEN 'NULL_TIMESTAMP'
        WHEN vehicle_count IS NULL                                           THEN 'NULL_VEHICLE_COUNT'
        WHEN vehicle_count < 0                                               THEN 'NEGATIVE_VEHICLE_COUNT'
        WHEN avg_speed_kmh IS NULL                                           THEN 'NULL_SPEED'
        WHEN avg_speed_kmh < 0                                               THEN 'NEGATIVE_SPEED'
        WHEN avg_speed_kmh > 120                                             THEN 'HARDWARE_LIMIT_SPEED'
        WHEN overspeed_flag IS NULL                                          THEN 'NULL_OVERSPEED_FLAG'
        WHEN vehicle_count > 200                                             THEN 'EXTREME_TRAFFIC_VOLUME'
        WHEN avg_speed_kmh > 60                                              THEN 'EXTREME_AVG_SPEED'
        ELSE                                                                      'OK'
    END                                                              AS primary_dq_flag,

    -- AUDIT TRAIL METADATA
    ingestion_time,
    NOW()                                                            AS processed_at,
    '{{ invocation_id }}'                                           AS dbt_invocation_id
FROM ranked
WHERE rn = 1
