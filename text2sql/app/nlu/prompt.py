"""Sinh system prompt từ Cube catalog.

System prompt và tool schema derive từ CÙNG một catalog (Cube Meta API), nên
không bao giờ lệch nhau — xem docs/02-cube-architecture.md mục 3. Phần mô tả
catalog là ổn định -> đặt trong `system` và bật prompt caching (tuỳ provider).
Phần biến động theo request (ngày giờ hiện tại) tách riêng ở
`build_runtime_context()` để không phá cache.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

VN_TZ = timezone(timedelta(hours=7))

_RULES = """\
# Role
Smart City NLU Assistant. Convert natural language questions into precise `query_metrics` tool calls.

# Rules
1. Only use measures, dimensions, and timeDimensions present in the catalog below.
2. All measures in a single tool call MUST belong to the SAME cube.
3. Time filtering MUST use `timeDimensions` (e.g., `air_quality.recorded_at`, `traffic_flow.recorded_at`, `city_health_index.date`, `smart_parking.recorded_at`, `smart_lighting.recorded_at`, `street_incidents.timestamp_start`).
4. If no time range is specified, leave `timeDimensions` empty (system applies default).
5. Preserve filter value names as written by user; system auto-maps section aliases (`Khu biet thu`, `Can ho`, `TTTM`).
6. If a date or month is mentioned without a year (e.g., '27.7', 'ngày 25 tháng 7'), ALWAYS default the year to current year (2026).
"""


def build_catalog_markdown(catalog: Catalog, candidates: dict[str, list[str]] | None = None) -> str:
    """Mô tả catalog rút gọn tối ưu token cho LLM, hỗ trợ lọc theo Top-K candidates."""
    lines: list[str] = ["# Catalog (Top-K Selected)"]
    cand_measures = set(candidates.get("measures", [])) if candidates else None
    cand_dimensions = set(candidates.get("dimensions", [])) if candidates else None
    cand_cubes = set(candidates.get("cubes", [])) if candidates else None

    for c in catalog.cubes:
        if cand_cubes and c.name not in cand_cubes:
            continue

        m_list = [m.name for m in c.measures if cand_measures is None or m.name in cand_measures]
        d_list = [d.name for d in c.dimensions if cand_dimensions is None or d.name in cand_dimensions]
        t_list = [t.name for t in c.time_dimensions]

        if not m_list and not d_list:
            continue

        lines.append(f"Cube `{c.name}` ({c.title}):")
        if m_list: lines.append(f"  Measures: {', '.join(m_list)}")
        if d_list: lines.append(f"  Dimensions: {', '.join(d_list)}")
        if t_list: lines.append(f"  TimeDimensions: {', '.join(t_list)}")
    return "\n".join(lines)


def build_system_prompt(catalog: Catalog, candidates: dict[str, list[str]] | None = None) -> str:
    return f"{_RULES}\n{build_catalog_markdown(catalog, candidates)}"


def build_runtime_context(
    today: date | None = None,
    default_time_range_label: str = "30 ngày gần nhất",
) -> str:
    """Phần biến động theo từng request — luôn đặt SAU câu hỏi để không phá cache."""
    today = today or datetime.now(VN_TZ).date()
    return (
        f"<runtime_context>\n"
        f"Hôm nay là {today.isoformat()} (Năm {today.year}).\n"
        f"Nếu người dùng nêu ngày/tháng mà không ghi năm (ví dụ: '27.7', 'ngày 25/7'), BẮT BUỘC lấy năm mặc định là {today.year}.\n"
        f"Nếu câu hỏi không nêu mốc thời gian, hệ thống sẽ mặc định lấy {default_time_range_label}.\n"
        f"</runtime_context>"
    )
