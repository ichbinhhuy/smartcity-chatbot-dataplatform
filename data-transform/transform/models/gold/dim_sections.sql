-- dim_sections.sql (Gold Master Data Dimension)
{{
    config(
        materialized='table',
        database='starrocks_gold',
        alias='dim_sections'
    )
}}

SELECT
    section_id,
    section_name,
    max_speed_limit,
    total_parking_slots,
    created_at
FROM (
    SELECT 'section_1' AS section_id, 'Cổng chính - TTTM' AS section_name, 30 AS max_speed_limit, 100 AS total_parking_slots, CURRENT_TIMESTAMP AS created_at
    UNION ALL
    SELECT 'section_2', 'Khu Căn hộ', 30, 100, CURRENT_TIMESTAMP
    UNION ALL
    SELECT 'section_3', 'Khu Biệt thự', 30, 100, CURRENT_TIMESTAMP
) AS master_sections
