"""Catalog (từ Cube Meta API) là nguồn duy nhất cho tool schema + system prompt.

Khoá bất biến: enum trong tool schema và catalog markdown trong system prompt
phải luôn khớp catalog — nếu không, "một nguồn sự thật" (docs/02-cube-architecture.md
mục 3) bị vi phạm.
"""

from __future__ import annotations

from app.nlu.prompt import build_system_prompt
from app.nlu.tool_schema import build_query_tool


def test_parse_catalog_splits_time_dimensions(catalog):
    energy = catalog.cube("energy")
    assert energy is not None
    assert {d.name for d in energy.dimensions} == {
        "energy.district_name",
        "energy.region",
        "energy.sector",
    }
    assert [t.name for t in energy.time_dimensions] == ["energy.recorded_at"]


def test_catalog_counts(catalog):
    assert {c.name for c in catalog.cubes} == {"energy", "traffic", "air_quality", "public_transport"}
    assert len(catalog.measure_names()) == 4 + 3 + 4 + 3
    assert len(catalog.dimension_names()) == 3 * 4
    assert len(catalog.time_dimension_names()) == 4


def test_tool_schema_enums_match_catalog(catalog):
    tool = build_query_tool(catalog)
    props = tool["input_schema"]["properties"]

    assert set(props["measures"]["items"]["enum"]) == set(catalog.measure_names())
    assert set(props["dimensions"]["items"]["enum"]) == set(catalog.dimension_names())
    assert set(props["timeDimensions"]["items"]["properties"]["dimension"]["enum"]) == set(
        catalog.time_dimension_names()
    )


def test_system_prompt_mentions_every_measure(catalog):
    prompt = build_system_prompt(catalog)
    for name in catalog.measure_names():
        assert f"`{name}`" in prompt
