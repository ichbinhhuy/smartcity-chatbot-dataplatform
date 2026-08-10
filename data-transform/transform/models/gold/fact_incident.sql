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
    CASE section_id
        WHEN 'section_2' THEN 'Khu biet thu'
        WHEN 'section_1' THEN 'Can ho'
        WHEN 'section_3' THEN 'TTTM'
        ELSE section_id
    END AS section_id,
    incident_type,
    timestamp_start,
    duration_min
FROM {{ ref('silver_incident') }}
WHERE record_status = 'VALID'
