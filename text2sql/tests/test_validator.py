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


def test_resolves_incident_type_alias_to_real_lowercase_value(catalog, sample_values, settings):
    """Bug 6: alias_map từng ánh xạ 'công trình' -> 'ROAD_WORK' (bịa, viết
    hoa) trong khi giá trị thật trong DB là 'road_work' (chữ thường) — xem
    data-transform/mock_engine/generator.py:98. Filter sai giá trị khớp 0
    dòng dù câu hỏi hợp lệ."""
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["street_incidents.avg_duration_min"],
            "filters": [{"member": "street_incidents.incident_type", "operator": "equals", "values": ["công trình"]}],
        }
    )
    assert result.ok, result.errors
    assert result.query.filters[0].values == ["road_work"]


def test_prior_query_carries_forward_time_dimension_when_current_omits_it(catalog, sample_values, settings):
    """Bug 2: lượt hiện tại không nêu mốc thời gian, nhưng session có
    `prior_query` cùng cube -> giữ nguyên dateRange/granularity của lượt
    trước thay vì rơi về `settings.default_relative_period`."""
    prior_query = {
        "measures": ["air_quality.avg_aqi"],
        "timeDimensions": [
            {"dimension": "air_quality.recorded_at", "dateRange": ["2026-07-21", "2026-07-28"], "granularity": "day"}
        ],
    }
    result = _validator(catalog, sample_values, settings).validate(
        {"measures": ["air_quality.avg_pm25"]},  # cùng cube air_quality, không nêu timeDimensions
        prior_query=prior_query,
    )
    assert result.ok, result.errors
    assert result.query.timeDimensions[0].dimension == "air_quality.recorded_at"
    assert result.query.timeDimensions[0].dateRange == ["2026-07-21", "2026-07-28"]
    assert result.query.timeDimensions[0].granularity == "day"
    assert any("giữ nguyên khung thời gian" in n for n in result.notes)


def test_prior_query_from_different_cube_is_ignored(catalog, sample_values, settings):
    """prior_query thuộc cube KHÁC -> không áp dụng, vẫn rơi về default global
    như hành vi cũ (timeDimension của cube khác không có ý nghĩa gì ở đây)."""
    prior_query = {
        "measures": ["traffic_flow.avg_speed"],
        "timeDimensions": [{"dimension": "traffic_flow.recorded_at", "dateRange": "2026-07-21"}],
    }
    result = _validator(catalog, sample_values, settings).validate(
        {"measures": ["air_quality.avg_aqi"]},
        prior_query=prior_query,
    )
    assert result.ok, result.errors
    assert result.query.timeDimensions[0].dateRange == settings.default_relative_period
    assert any("mặc định" in n for n in result.notes)


def test_prior_query_absent_falls_back_to_default(catalog, sample_values, settings):
    """Không truyền prior_query (vd lượt đầu tiên trong session) -> hành vi
    y hệt trước khi có Bug 2 fix."""
    result = _validator(catalog, sample_values, settings).validate({"measures": ["air_quality.avg_aqi"]})
    assert result.ok, result.errors
    assert result.query.timeDimensions[0].dateRange == settings.default_relative_period


def test_prior_query_overrides_when_model_self_fills_global_default(catalog, sample_values, settings):
    """Bug 2 (mở rộng sau khi verify qua UI thật, xem README.md Y01): trên
    thực tế model KHÔNG luôn để `timeDimensions` rỗng như Rule 8(b) kỳ vọng —
    nó thường TỰ ĐIỀN đúng giá trị mặc định toàn cục (vd 'last 30 days') thay
    vì để trống. Trùng khớp tuyệt đối với default toàn cục là tín hiệu đáng
    ngờ -> vẫn ưu tiên carry-forward prior_query có giá trị khác/cụ thể hơn."""
    prior_query = {
        "measures": ["air_quality.avg_aqi"],
        "timeDimensions": [
            {"dimension": "air_quality.recorded_at", "dateRange": "2026-07-21 to 2026-07-28", "granularity": "day"}
        ],
    }
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["air_quality.avg_pm25"],
            "timeDimensions": [
                {"dimension": "air_quality.recorded_at", "dateRange": settings.default_relative_period}
            ],
        },
        prior_query=prior_query,
    )
    assert result.ok, result.errors
    assert result.query.timeDimensions[0].dateRange == "2026-07-21 to 2026-07-28"
    assert result.query.timeDimensions[0].granularity == "day"
    assert any("model tự điền" in n for n in result.notes)


def test_prior_query_does_not_override_when_model_gives_specific_non_default_range(catalog, sample_values, settings):
    """Model đưa 1 dateRange CỤ THỂ khác với default toàn cục -> phải tôn
    trọng, không ghi đè bằng prior_query dù có sẵn."""
    prior_query = {
        "measures": ["air_quality.avg_aqi"],
        "timeDimensions": [{"dimension": "air_quality.recorded_at", "dateRange": "2026-07-21 to 2026-07-28"}],
    }
    result = _validator(catalog, sample_values, settings).validate(
        {
            "measures": ["air_quality.avg_pm25"],
            "timeDimensions": [{"dimension": "air_quality.recorded_at", "dateRange": "2026-08-01"}],
        },
        prior_query=prior_query,
    )
    assert result.ok, result.errors
    assert result.query.timeDimensions[0].dateRange == "2026-08-01"


def test_malformed_prior_query_is_ignored_not_raised(catalog, sample_values, settings):
    """prior_query hỏng/lỗi thời (vd schema cũ) -> bỏ qua êm, không chặn lượt
    hiện tại (degrade-êm, cùng nguyên tắc với session store)."""
    result = _validator(catalog, sample_values, settings).validate(
        {"measures": ["air_quality.avg_aqi"]},
        prior_query={"khong": "phai", "cube": "query"},
    )
    assert result.ok, result.errors
    assert result.query.timeDimensions[0].dateRange == settings.default_relative_period


def test_dimension_only_query_is_accepted(catalog, sample_values, settings):
    """Cube `districts` không có measure nào — câu hỏi kiểu 'có bao nhiêu khu
    vực' phải build được query chỉ-dimension thay vì bị chặn vì thiếu
    measure. Xem docs/04-ambiguous-question-handling.md."""
    result = _validator(catalog, sample_values, settings).validate(
        {"dimensions": ["districts.name"]}
    )
    assert result.ok, result.errors
    assert result.query.measures == []
    assert result.query.dimensions == ["districts.name"]


def test_dimension_only_query_still_enforces_cross_cube_guard(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate(
        {"dimensions": ["districts.name", "traffic_flow.camera_id"]}
    )
    assert not result.ok
    assert any("thuộc Cube khác" in e for e in result.errors)


def test_rejects_query_with_no_measures_and_no_dimensions(catalog, sample_values, settings):
    result = _validator(catalog, sample_values, settings).validate({})
    assert not result.ok
    assert any("measure" in e.lower() and "dimension" in e.lower() for e in result.errors)


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


def test_unmatched_filter_value_with_no_close_candidate_is_rejected(catalog, settings):
    """Nhóm 2/Y06 (kế hoạch fix Yellow case): giá trị filter KHÔNG khớp bất
    kỳ candidate nào trong domain hữu hạn đã biết (khác nhánh "≥2 candidate
    tie" ở trên) — trước đây `SampleValues.resolve()` âm thầm pass-qua giá
    trị này (`if not close: return value, False, None`), khiến Cube query
    chạy với filter khớp 0 dòng mà không cảnh báo gì (vd "khu trung tâm"
    không gần giống bất kỳ tên phân khu thật nào — ratio cao nhất chỉ 0.560,
    dưới cutoff 0.6, verify bằng diagnostic thật). Giờ phải báo lỗi, đẩy vào
    repair loop, cùng cơ chế với nhánh tie."""
    district_sample_values = SampleValues({"districts.name": ["Khu biet thu", "Can ho", "TTTM"]})
    result = _validator(catalog, district_sample_values, settings).validate(
        {
            "dimensions": ["districts.max_speed_limit"],
            "filters": [{"member": "districts.name", "operator": "equals", "values": ["khu trung tâm"]}],
        }
    )
    assert not result.ok
    assert any(
        "Khu biet thu" in e and "Can ho" in e and "TTTM" in e for e in result.errors
    ), result.errors
