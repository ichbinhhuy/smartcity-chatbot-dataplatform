"""Test cho helper NLG dùng chung giữa `/api/chat` và `/api/chat/stream`
(`app/server.py::_relabel_and_cap_rows`/`_build_nlg_messages`) — Bug 4 trong
kế hoạch fix: dữ liệu Cube nhiều dòng dump thẳng vào prompt khiến model tự
bịa format/lặp vô hạn.
"""

from __future__ import annotations

import json

from app.nlu.types import CubeQuery, CubeTimeDimension
from app.server import _build_nlg_messages, _relabel_and_cap_rows


def _query_with_time_dimension(dim: str) -> CubeQuery:
    return CubeQuery(
        measures=["smart_lighting.total_power_kwh"],
        timeDimensions=[CubeTimeDimension(dimension=dim, dateRange="2026-07-24", granularity="hour")],
    )


def test_rows_under_cap_are_kept_as_is_no_note():
    data = [{"smart_lighting.recorded_at": "2026-07-24T00:00:00.000", "smart_lighting.total_power_kwh": 1.0}]
    query = _query_with_time_dimension("smart_lighting.recorded_at")

    rows, note = _relabel_and_cap_rows(data, query, max_rows=60)

    assert note is None
    assert len(rows) == 1
    # Key thời gian ISO dài dòng được đổi thành nhãn ngắn.
    assert rows[0] == {"thoi_diem": "2026-07-24T00:00:00.000", "smart_lighting.total_power_kwh": 1.0}


def test_rows_over_cap_are_truncated_with_min_max_avg_summary():
    data = [
        {"smart_lighting.recorded_at": f"2026-07-24T{h:02d}:00:00.000", "smart_lighting.total_power_kwh": float(h)}
        for h in range(24)
    ]
    query = _query_with_time_dimension("smart_lighting.recorded_at")

    rows, note = _relabel_and_cap_rows(data, query, max_rows=10)

    assert len(rows) == 10
    assert note is not None
    assert "24 dòng" in note
    assert "10 dòng đầu" in note
    # min/max/avg tính trên TOÀN BỘ 24 dòng (0..23), không phải chỉ 10 dòng bị cắt.
    summary_json = note.split(": ", 1)[1]
    summary = json.loads(summary_json)
    assert summary["smart_lighting.total_power_kwh"]["min"] == 0
    assert summary["smart_lighting.total_power_kwh"]["max"] == 23
    assert summary["smart_lighting.total_power_kwh"]["avg"] == sum(range(24)) / 24


def test_build_nlg_messages_embeds_truncation_note_when_over_cap():
    """100 dòng vượt `settings.nlg_max_rows_in_prompt` mặc định (60) — dùng
    trực tiếp app.config.settings (singleton thật `_build_nlg_messages` đọc),
    không qua fixture `settings` (instance riêng, không cùng object)."""
    from app.config import settings as real_settings

    data = [
        {"traffic_flow.recorded_at": f"2026-07-24T{h // 60:02d}:{h % 60:02d}:00.000", "traffic_flow.avg_speed": float(h)}
        for h in range(100)
    ]
    query = _query_with_time_dimension("traffic_flow.recorded_at")
    cube_data = {"data": data, "annotation": {}}

    messages = _build_nlg_messages("Tốc độ trung bình theo phút ngày 24/7", cube_data, query)

    assert len(messages) == 1
    content = messages[0]["content"]
    assert "Ghi chú hệ thống" in content
    # Payload nhét vào prompt chỉ chứa số dòng đã cắt, không phải nguyên 100 dòng.
    prompt_json_str = content.split("Kết quả JSON từ Cube:\n", 1)[1].split("\n\n[Ghi chú", 1)[0]
    prompt_payload = json.loads(prompt_json_str)
    assert len(prompt_payload["data"]) == real_settings.nlg_max_rows_in_prompt
    assert len(prompt_payload["data"]) < 100
