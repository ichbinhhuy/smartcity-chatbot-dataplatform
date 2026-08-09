-- fact_lighting.sql (Gold Datamart)
{{
    config(
        materialized='table',
        database='starrocks_gold',
        alias='fact_lighting'
    )
}}

SELECT
    id,
    section_id,
    pole_id,
    recorded_at,
    power_kwh,
    status,
    (record_status IN ('VALID', 'WARNING')) AS is_valid,
    primary_dq_flag AS data_quality_flag
FROM {{ ref('silver_lighting') }}
