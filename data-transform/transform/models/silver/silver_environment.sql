{{
    config(
        materialized='table',
        database='starrocks_silver',
        alias='silver_environment'
    )
}}

WITH ranked AS (
    SELECT
        event_id                                                     AS id,
        section_id,
        STR_TO_DATE(recorded_at, '%Y-%m-%d %H:%i:%s')               AS timestamp,
        aqi,
        pm25,
        noise_level_db,
        ingestion_time,
        ROW_NUMBER() OVER (
            PARTITION BY event_id
            ORDER BY ingestion_time DESC
        )                                                            AS rn
    FROM {{ source('bronze', 'bronze_environment') }}
)

SELECT
    id,
    section_id,
    timestamp,

    -- RAW VALUES KEPT AS-IS (INCLUDING INVALID NEGATIVES — for audit)
    aqi,
    pm25,
    noise_level_db,

    -- ==========================================================
    -- RECORD STATUS — 3-tier: INVALID / WARNING / VALID
    -- INVALID : physically impossible (negative) or above instrument ceiling
    -- WARNING : technically valid measurement but extreme in urban context
    -- VALID   : normal operational range for urban residential area
    -- ==========================================================
    CASE
        -- INVALID: hard errors
        WHEN id IS NULL OR id = ''                                           THEN 'INVALID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3')      THEN 'INVALID'
        WHEN timestamp IS NULL                                               THEN 'INVALID'
        WHEN aqi IS NULL OR aqi < 0 OR aqi > 500                            THEN 'INVALID'
        WHEN pm25 IS NULL OR pm25 < 0                                        THEN 'INVALID'
        WHEN noise_level_db IS NULL OR noise_level_db < 0 OR noise_level_db > 200 THEN 'INVALID'
        -- WARNING: anomalous but physically possible
        -- aqi > 200 = Very Unhealthy to Hazardous (WHO scale), rare in residential area
        WHEN aqi > 200                                                       THEN 'WARNING'
        -- pm25 > 150 = Hazardous zone (WHO), possible during local pollution event
        WHEN pm25 > 150                                                      THEN 'WARNING'
        -- noise_level_db > 120 = jet takeoff level, ~0.1% probability (explosion, major accident)
        WHEN noise_level_db > 120                                            THEN 'WARNING'
        ELSE                                                                      'VALID'
    END                                                              AS record_status,

    -- ==========================================================
    -- PRIMARY DQ FLAG — first violated rule (most specific)
    -- ==========================================================
    CASE
        WHEN id IS NULL OR id = ''                                           THEN 'NULL_EVENT_ID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3')      THEN 'INVALID_SECTION'
        WHEN timestamp IS NULL                                               THEN 'NULL_TIMESTAMP'
        WHEN aqi IS NULL                                                     THEN 'NULL_AQI'
        WHEN aqi < 0                                                         THEN 'NEGATIVE_AQI'
        WHEN aqi > 500                                                       THEN 'HARDWARE_LIMIT_AQI'
        WHEN pm25 IS NULL                                                    THEN 'NULL_PM25'
        WHEN pm25 < 0                                                        THEN 'NEGATIVE_PM25'
        WHEN noise_level_db IS NULL                                          THEN 'NULL_NOISE'
        WHEN noise_level_db < 0                                              THEN 'NEGATIVE_NOISE'
        WHEN noise_level_db > 200                                            THEN 'HARDWARE_LIMIT_NOISE'
        WHEN aqi > 200                                                       THEN 'EXTREME_AQI'
        WHEN pm25 > 150                                                      THEN 'EXTREME_PM25'
        WHEN noise_level_db > 120                                            THEN 'EXTREME_NOISE_OUTLIER'
        ELSE                                                                      'VALID'
    END                                                              AS primary_dq_flag,

    -- AUDIT TRAIL METADATA
    ingestion_time,
    NOW()                                                            AS processed_at,
    '{{ invocation_id }}'                                           AS dbt_invocation_id
FROM ranked
WHERE rn = 1
