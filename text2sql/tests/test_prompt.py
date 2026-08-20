"""Unit test cho app/nlu/prompt.py — `build_field_ambiguity_hint()` (kế
hoạch fix Yellow case, Bước 3). Test thuần, không cần LLM/retriever thật.
"""

from __future__ import annotations

from app.nlu.prompt import build_field_ambiguity_hint


def test_returns_empty_string_when_no_ambiguity():
    assert build_field_ambiguity_hint(None) == ""


def test_returns_empty_string_when_no_candidates():
    assert build_field_ambiguity_hint({"cube": "smart_lighting", "candidates": []}) == ""


def test_hint_contains_field_names_and_titles():
    field_ambiguity = {
        "cube": "smart_lighting",
        "candidates": [
            ("smart_lighting.total_power_kwh", "Tổng điện năng tiêu thụ (kWh)"),
            ("smart_lighting.faulty_lamp_count", "Số cột đèn bị hỏng"),
        ],
    }
    hint = build_field_ambiguity_hint(field_ambiguity)
    assert hint != ""
    assert "smart_lighting" in hint
    assert "smart_lighting.total_power_kwh" in hint
    assert "Tổng điện năng tiêu thụ (kWh)" in hint
    assert "smart_lighting.faulty_lamp_count" in hint
    assert "Số cột đèn bị hỏng" in hint
    # Không hard-block — chỉ là hint tiêm vào lượt hỏi, không phải lệnh chặn cứng.
    assert "Nhóm 2" in hint


def test_hint_forbids_refuse_request_tool():
    """Fix Bước 7 (benchmark thật): Y02/Y04/Y09 dao động clarification/refusal
    giữa các lần chạy giống hệt nhau vì model đôi khi đọc "không chắc field
    nào" thành `external_data_unavailable` rồi gọi `refuse_request` thay vì
    hỏi lại bằng text — hint phải cấm rõ ràng, không chỉ ngụ ý qua "Nhóm 2"."""
    field_ambiguity = {
        "cube": "smart_lighting",
        "candidates": [("smart_lighting.total_power_kwh", "Tổng điện năng tiêu thụ (kWh)")],
    }
    hint = build_field_ambiguity_hint(field_ambiguity)
    assert "refuse_request" in hint
    assert "KHÔNG" in hint
