{{
    config(
        materialized='table',
        database='starrocks_silver',
        alias='silver_incident'
    )
}}

WITH ranked AS (
    SELECT
        incident_id,
        section_id,
        incident_type,
        STR_TO_DATE(timestamp_start, '%Y-%m-%d %H:%i:%s')           AS timestamp_start,
        duration_min,
        ingestion_time,
        ROW_NUMBER() OVER (
            PARTITION BY incident_id
            ORDER BY ingestion_time DESC
        )                                                            AS rn
    FROM {{ source('bronze', 'bronze_incident') }}
)

SELECT
    incident_id,
    section_id,
    incident_type,
    timestamp_start,
    duration_min,

    -- DERIVED FIELD: timestamp_end for Gold time-range JOINs
    -- Gold usage: recorded_at BETWEEN timestamp_start AND timestamp_end
    DATE_ADD(timestamp_start, INTERVAL duration_min MINUTE)          AS timestamp_end,

    -- ==========================================================
    -- RECORD STATUS — 3-tier: INVALID / WARNING / VALID
    -- INVALID : impossible values (negative duration, > 7 days, wrong enum)
    -- WARNING : duration > 1440 min (> 24 hours, unusual but possible for major roadworks)
    -- VALID   : 1–1440 min, correct enum values
    -- ==========================================================
    CASE
        -- INVALID: hard errors
        WHEN incident_id IS NULL OR incident_id = ''                         THEN 'INVALID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3')      THEN 'INVALID'
        WHEN incident_type NOT IN ('accident', 'road_work', 'traffic_light_failure') THEN 'INVALID'
        WHEN timestamp_start IS NULL                                         THEN 'INVALID'
        WHEN duration_min IS NULL OR duration_min <= 0 OR duration_min > 10080 THEN 'INVALID'
        -- WARNING: incident lasting > 24h, unusual but possible for major infrastructure works
        WHEN duration_min > 1440                                             THEN 'WARNING'
        ELSE                                                                      'VALID'
    END                                                              AS record_status,

    -- ==========================================================
    -- PRIMARY DQ FLAG — first violated rule (most specific)
    -- ==========================================================
    CASE
        WHEN incident_id IS NULL OR incident_id = ''                         THEN 'NULL_INCIDENT_ID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3')      THEN 'INVALID_SECTION'
        WHEN incident_type NOT IN ('accident', 'road_work', 'traffic_light_failure') THEN 'INVALID_INCIDENT_TYPE'
        WHEN timestamp_start IS NULL                                         THEN 'NULL_TIMESTAMP'
        WHEN duration_min IS NULL                                            THEN 'NULL_DURATION'
        WHEN duration_min <= 0                                               THEN 'NEGATIVE_DURATION'
        WHEN duration_min > 10080                                            THEN 'DURATION_EXCEEDS_7DAYS'
        WHEN duration_min > 1440                                             THEN 'EXTENDED_INCIDENT_DURATION'
        ELSE                                                                      'OK'
    END                                                              AS primary_dq_flag,

    -- AUDIT TRAIL METADATA
    ingestion_time,
    NOW()                                                            AS processed_at,
    '{{ invocation_id }}'                                           AS dbt_invocation_id
FROM ranked
WHERE rn = 1
