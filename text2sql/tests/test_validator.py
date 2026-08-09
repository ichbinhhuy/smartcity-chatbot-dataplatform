"""Lightweight Validator — chỉ bắt lỗi mà enum trong tool schema không bắt được.

Không kiểm tra ràng buộc liên-cube (measure/dimension có join hợp lệ không) —
đó là việc của Cube Core lúc thực thi, xem app/nlu/validator.py và
docs/02-cube-architecture.md mục 2.
"""

from __future__ import annotations

from app.nlu.validator import QueryValidator


def _validator(catalog, sample_values, settings):
    return QueryValidator(catalog, sample_values, settings)


def test_accepts_simple_query(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["energy.total_consumption"],
            "dimensions": ["energy.district_name"],
            "timeDimensions": [{"dimension": "energy.recorded_at", "dateRange": "last month"}],
        }
    )
    assert result.ok, result.errors
    assert result.query.measures == ["energy.total_consumption"]


def test_rejects_unknown_measure(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate({"measures": ["energy.tong_dien"]})
    assert not result.ok
    assert "không tồn tại" in result.errors[0]


def test_rejects_unknown_dimension(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {"measures": ["energy.total_consumption"], "dimensions": ["energy.khong_ton_tai"]}
    )
    assert not result.ok
    assert any("Dimension" in e and "không tồn tại" in e for e in result.errors)


def test_rejects_time_dimension_in_filters(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["energy.total_consumption"],
            "filters": [{"member": "energy.recorded_at", "operator": "gt", "values": ["2026-01-01"]}],
        }
    )
    assert not result.ok
    assert any("timeDimensions" in e for e in result.errors)


def test_rejects_invalid_date_range(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["energy.total_consumption"],
            "timeDimensions": [{"dimension": "energy.recorded_at", "dateRange": "hôm qua kìa"}],
        }
    )
    assert not result.ok
    assert any("dateRange" in e for e in result.errors)


def test_rejects_invalid_granularity(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["traffic.avg_speed"],
            "timeDimensions": [
                {"dimension": "traffic.recorded_at", "dateRange": "this week", "granularity": "century"}
            ],
        }
    )
    assert not result.ok
    assert any("granularity" in e for e in result.errors)


def test_rejects_order_outside_selection(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["energy.total_consumption"],
            "order": [{"field": "energy.avg_consumption", "direction": "desc"}],
        }
    )
    assert not result.ok
    assert any("order" in e for e in result.errors)


def test_applies_default_time_dimension(catalog, sample_values, settings):
    """Cube chỉ có đúng 1 time dimension -> tự điền, kèm note cho người dùng biết."""
    result = _validator(catalog, sample_values, settings).validate({"measures": ["traffic.avg_speed"]})
    assert result.ok, result.errors
    assert result.query.timeDimensions[0].dimension == "traffic.recorded_at"
    assert result.query.timeDimensions[0].dateRange == settings.default_relative_period
    assert any("mặc định" in n for n in result.notes)


def test_clamps_limit_to_guardrail(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {"measures": ["traffic.avg_speed"], "limit": 999_999}
    )
    assert result.ok, result.errors
    assert result.query.limit == settings.max_row_limit


def test_fuzzy_matches_filter_value(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["energy.total_consumption"],
            "filters": [{"member": "energy.sector", "operator": "equals", "values": ["Residential"]}],
        }
    )
    assert result.ok, result.errors
    assert result.query.filters[0].values == ["residential"]
