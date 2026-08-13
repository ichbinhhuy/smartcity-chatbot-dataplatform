"""Lightweight Validator — chỉ bắt lỗi mà enum trong tool schema không bắt được.

Không kiểm tra ràng buộc liên-cube (measure/dimension có join hợp lệ không) —
đó là việc của Cube Core lúc thực thi, xem app/nlu/validator.py và
docs/02-cube-architecture.md mục 2.
"""

from __future__ import annotations

from app.catalog.sample_values import SampleValues
from app.nlu.validator import QueryValidator


def _validator(catalog, sample_values, settings):
    return QueryValidator(catalog, sample_values, settings)


def test_accepts_simple_query(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["air_quality.avg_aqi"],
            "dimensions": ["air_quality.aqi_category"],
            "timeDimensions": [{"dimension": "air_quality.recorded_at", "dateRange": "last month"}],
        }
    )
    assert result.ok, result.errors
    assert result.query.measures == ["air_quality.avg_aqi"]


def test_rejects_unknown_measure(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate({"measures": ["air_quality.tong_aqi"]})
    assert not result.ok
    assert "không tồn tại" in result.errors[0]


def test_rejects_unknown_dimension(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {"measures": ["air_quality.avg_aqi"], "dimensions": ["air_quality.khong_ton_tai"]}
    )
    assert not result.ok
    assert any("Dimension" in e and "không tồn tại" in e for e in result.errors)


def test_rejects_time_dimension_in_filters(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["air_quality.avg_aqi"],
            "filters": [{"member": "air_quality.recorded_at", "operator": "gt", "values": ["2026-01-01"]}],
        }
    )
    assert not result.ok
    assert any("timeDimensions" in e for e in result.errors)


def test_rejects_invalid_date_range(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["air_quality.avg_aqi"],
            "timeDimensions": [{"dimension": "air_quality.recorded_at", "dateRange": "hôm qua kìa"}],
        }
    )
    assert not result.ok
    assert any("dateRange" in e for e in result.errors)


def test_rejects_invalid_granularity(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["traffic_flow.avg_speed"],
            "timeDimensions": [
                {"dimension": "traffic_flow.recorded_at", "dateRange": "this week", "granularity": "century"}
            ],
        }
    )
    assert not result.ok
    assert any("granularity" in e for e in result.errors)


def test_rejects_order_outside_selection(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["air_quality.avg_aqi"],
            "order": [{"field": "air_quality.max_aqi", "direction": "desc"}],
        }
    )
    assert not result.ok
    assert any("order" in e for e in result.errors)


def test_applies_default_time_dimension(catalog, sample_values, settings):
    """Cube chỉ có đúng 1 time dimension -> tự điền, kèm note cho người dùng biết."""
    result = _validator(catalog, sample_values, settings).validate({"measures": ["traffic_flow.avg_speed"]})
    assert result.ok, result.errors
    assert result.query.timeDimensions[0].dimension == "traffic_flow.recorded_at"
    assert result.query.timeDimensions[0].dateRange == settings.default_relative_period
    assert any("mặc định" in n for n in result.notes)


def test_clamps_limit_to_guardrail(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {"measures": ["traffic_flow.avg_speed"], "limit": 999_999}
    )
    assert result.ok, result.errors
    assert result.query.limit == settings.max_row_limit


def test_fuzzy_matches_filter_value(catalog, sample_values, settings):
    """Fuzzy-match phải không phân biệt hoa/thường — DB lưu enum viết hoa
    (EVENING_FULL) trong khi LLM có thể trả giá trị viết thường."""
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["smart_lighting.total_power_kwh"],
            "filters": [{"member": "smart_lighting.operating_mode", "operator": "equals", "values": ["evening_full"]}],
        }
    )
    assert result.ok, result.errors
    assert result.query.filters[0].values == ["EVENING_FULL"]


def test_ambiguous_filter_value_is_rejected(catalog, settings):
    """Khi ≥2 giá trị allowed gần giống nhau tới mức không đủ tin cậy để tự
    đoán, validator phải trả lỗi (đẩy vào repair loop) thay vì âm thầm chọn
    candidate đầu tiên — xem docs/04-ambiguous-question-handling.md case G."""
    ambiguous_sample_values = SampleValues(
        {"smart_lighting.operating_mode": ["EVENING_FULL_ZONE_A", "EVENING_FULL_ZONE_B"]}
    )
    result = _validator(catalog, ambiguous_sample_values, settings).validate(
        {
            "measures": ["smart_lighting.total_power_kwh"],
            "filters": [
                {"member": "smart_lighting.operating_mode", "operator": "equals", "values": ["evening_full_zone"]}
            ],
        }
    )
    assert not result.ok
    assert any(
        "EVENING_FULL_ZONE_A" in e and "EVENING_FULL_ZONE_B" in e for e in result.errors
    ), result.errors
