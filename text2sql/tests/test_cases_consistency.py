"""Đối chiếu tests/cases.yaml với catalog thật — không gọi LLM.

Mọi measure/dimension/time_dimension nhắc tới trong cases.yaml phải tồn tại
thật trong catalog, nếu không bộ eval ở sprint sau sẽ test nhầm field ma.
"""

from __future__ import annotations

import yaml

from app.config import PROJECT_ROOT

CASES = yaml.safe_load((PROJECT_ROOT / "tests" / "cases.yaml").read_text(encoding="utf-8"))


def test_every_referenced_field_exists_in_catalog(catalog):
    measure_names = set(catalog.measure_names())
    dimension_names = set(catalog.dimension_names())
    time_dimension_names = set(catalog.time_dimension_names())

    for case in CASES:
        expect = case["expect"]
        for m in expect.get("measures", []):
            assert m in measure_names, f"{case['id']}: measure lạ '{m}'"
        for d in expect.get("dimensions", []) + expect.get("filters_fields", []):
            assert d in dimension_names, f"{case['id']}: dimension lạ '{d}'"
        for t in expect.get("time_dimensions", []):
            assert t in time_dimension_names, f"{case['id']}: time dimension lạ '{t}'"
