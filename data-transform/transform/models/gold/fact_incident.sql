-- fact_incident.sql (Gold Datamart)
{{
    config(
        materialized='table',
        database='starrocks_gold',
        alias='fact_incident'
    )
}}

SELECT
    incident_id,
    section_id,
    incident_type,
    timestamp_start,
    duration_min
FROM {{ ref('silver_incident') }}
WHERE record_status = 'VALID'
