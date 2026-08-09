{{
    config(
        materialized='table',
        database='starrocks_silver',
        alias='silver_lighting'
    )
}}

WITH ranked AS (
    SELECT
        event_id                                                     AS id,
        section_id,
        pole_id,
        STR_TO_DATE(recorded_at, '%Y-%m-%d %H:%i:%s')               AS recorded_at,
        power_kwh                                                    AS power_kwh_raw,
        status,
        COALESCE(ingestion_time, NOW())                              AS ingestion_time,
        ROW_NUMBER() OVER (
            PARTITION BY event_id
            ORDER BY ingestion_time DESC
        )                                                            AS rn
    FROM {{ source('bronze', 'bronze_lighting') }}
)

SELECT
    id,
    section_id,
    pole_id,
    recorded_at,

    -- FALLBACK FOR NOT NULL DDL CONSTRAINT
    -- record_status is computed from power_kwh_raw (before COALESCE) to preserve NULL detection
    COALESCE(power_kwh_raw, 0.0)                                     AS power_kwh,
    status,

    -- ==========================================================
    -- RECORD STATUS — 3-tier: INVALID / WARNING / VALID
    -- INVALID : missing (NULL) or negative power (physically impossible)
    -- WARNING : power > 0.5 kWh/pole/15min = ~2000W, 5x normal LED (possible short circuit)
    -- VALID   : 0–0.5 kWh — normal LED street light consumption range
    -- ==========================================================
    CASE
        -- INVALID: hard errors — check power_kwh_raw BEFORE COALESCE
        WHEN id IS NULL OR id = ''                                           THEN 'INVALID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3')      THEN 'INVALID'
        WHEN pole_id IS NULL OR pole_id = ''                                 THEN 'INVALID'
        WHEN recorded_at IS NULL                                             THEN 'INVALID'
        WHEN power_kwh_raw IS NULL OR power_kwh_raw < 0                      THEN 'INVALID'
        WHEN status NOT IN ('OK', 'FAULTY', 'OFF')                           THEN 'INVALID'
        -- WARNING: anomalous consumption — possible short circuit or meter malfunction
        -- LED streetlight: 30–150W → 0.0075–0.0375 kWh/15min. > 0.5 kWh = ~2000W, 5x normal
        WHEN power_kwh_raw > 0.5                                             THEN 'WARNING'
        ELSE                                                                      'VALID'
    END                                                              AS record_status,

    -- ==========================================================
    -- PRIMARY DQ FLAG — first violated rule (most specific)
    -- ==========================================================
    CASE
        WHEN id IS NULL OR id = ''                                           THEN 'NULL_EVENT_ID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3')      THEN 'INVALID_SECTION'
        WHEN pole_id IS NULL OR pole_id = ''                                 THEN 'NULL_POLE_ID'
        WHEN recorded_at IS NULL                                             THEN 'NULL_TIMESTAMP'
        WHEN power_kwh_raw IS NULL                                           THEN 'NULL_POWER'
        WHEN power_kwh_raw < 0                                               THEN 'NEGATIVE_POWER'
        WHEN status NOT IN ('OK', 'FAULTY', 'OFF')                           THEN 'INVALID_STATUS'
        WHEN power_kwh_raw > 0.5                                             THEN 'EXTREME_POWER_CONSUMPTION'
        ELSE                                                                      'OK'
    END                                                              AS primary_dq_flag,

    -- AUDIT TRAIL METADATA
    ingestion_time,
    NOW()                                                            AS processed_at,
    '{{ invocation_id }}'                                           AS dbt_invocation_id
FROM ranked
WHERE rn = 1
