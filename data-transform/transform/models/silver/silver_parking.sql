{{
    config(
        materialized='table',
        database='starrocks_silver',
        alias='silver_parking'
    )
}}

WITH ranked AS (
    SELECT
        event_id                                                     AS id,
        gw_id,
        section_id,
        STR_TO_DATE(recorded_at, '%Y-%m-%d %H:%i:%s')               AS recorded_at,
        slot_total,
        occupied_slots,
        ingestion_time,
        ROW_NUMBER() OVER (
            PARTITION BY event_id
            ORDER BY ingestion_time DESC
        )                                                            AS rn
    FROM {{ source('bronze', 'bronze_parking') }}
)

SELECT
    id,
    gw_id,
    section_id,
    recorded_at,
    slot_total,
    
    -- RAW VALUE (AUDIT)
    occupied_slots                                                   AS occupied_slots_raw,
    
    -- CLEAN VALUE (GOLD SERVING)
    LEAST(occupied_slots, slot_total)                                AS occupied_slots_clean,

    -- RECORD STATUS (GATEKEEPER FOR GOLD)
    CASE
        WHEN id IS NULL OR id = ''                                    THEN 'INVALID'
        WHEN gw_id NOT IN ('GW_PARK_SECTION_1', 'GW_PARK_SECTION_2', 'GW_PARK_SECTION_3') THEN 'INVALID'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3') THEN 'INVALID'
        WHEN recorded_at IS NULL                                     THEN 'INVALID'
        WHEN slot_total IS NULL OR slot_total <= 0                   THEN 'INVALID'
        WHEN occupied_slots IS NULL OR occupied_slots < 0 OR occupied_slots > slot_total THEN 'INVALID'
        ELSE 'VALID'
    END                                                              AS record_status,

    -- PRIMARY DQ FLAG (DETAILED REASON)
    CASE
        WHEN id IS NULL OR id = ''                                    THEN 'NULL_EVENT_ID'
        WHEN gw_id NOT IN ('GW_PARK_SECTION_1', 'GW_PARK_SECTION_2', 'GW_PARK_SECTION_3') THEN 'INVALID_GATEWAY'
        WHEN section_id NOT IN ('section_1', 'section_2', 'section_3') THEN 'INVALID_SECTION'
        WHEN recorded_at IS NULL                                     THEN 'NULL_TIMESTAMP'
        WHEN slot_total IS NULL OR slot_total <= 0                   THEN 'INVALID_SLOT_TOTAL'
        WHEN occupied_slots IS NULL                                  THEN 'NULL_OCCUPIED_SLOTS'
        WHEN occupied_slots > slot_total                             THEN 'OVERFLOW_PARKING'
        WHEN occupied_slots < 0                                      THEN 'NEGATIVE_OCCUPIED'
        ELSE 'OK'
    END                                                              AS primary_dq_flag,

    -- AUDIT TRAIL METADATA
    ingestion_time,
    NOW()                                                            AS processed_at,
    '{{ invocation_id }}'                                           AS dbt_invocation_id
FROM ranked
WHERE rn = 1
