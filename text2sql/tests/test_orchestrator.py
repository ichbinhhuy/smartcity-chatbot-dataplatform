"""Pipeline NLU chạy với LLM giả — kiểm tra luồng điều khiển, không kiểm tra model."""

from __future__ import annotations

from app.nlu.orchestrator import NLUOrchestrator
from app.nlu.types import NLUStatus
from tests.conftest import FakeLLMClient, refusal_response, text_response, tool_call_response


def _orchestrator(catalog, sample_values, settings, responses):
    return NLUOrchestrator(
        catalog,
        llm_client=FakeLLMClient(responses),
        sample_values=sample_values,
        settings=settings,
    )


def test_valid_tool_call_becomes_cube_query(catalog, sample_values, settings):
    orch = _orchestrator(
        catalog,
        sample_values,
        settings,
        [
            tool_call_response(
                {
                    "measures": ["energy.total_consumption"],
                    "dimensions": ["energy.district_name"],
                    "timeDimensions": [{"dimension": "energy.recorded_at", "dateRange": "last month"}],
                }
            )
        ],
    )
    result = orch.interpret("Tiêu thụ điện theo quận tháng trước")

    assert result.status is NLUStatus.QUERY
    assert result.query.measures == ["energy.total_consumption"]
    assert result.usage["input_tokens"] == 100


def test_text_only_response_is_treated_as_clarification(catalog, sample_values, settings):
    """Model trả lời bằng text = nó không chắc. Đây là tính năng, không phải lỗi."""
    orch = _orchestrator(
        catalog,
        sample_values,
        settings,
        [text_response("Bạn muốn xem chỉ số nào: điện hay giao thông?")],
    )
    result = orch.interpret("Cho tôi xem số liệu quận 1")

    assert result.status is NLUStatus.CLARIFICATION
    assert "điện hay giao thông" in result.message


def test_refusal_is_detected_before_reading_tool_calls(catalog, sample_values, settings):
    orch = _orchestrator(catalog, sample_values, settings, [refusal_response("cyber")])
    result = orch.interpret("...")

    assert result.status is NLUStatus.REFUSAL
    assert "cyber" in result.errors[0]


def test_invalid_tool_call_triggers_repair_round_trip(catalog, sample_values, settings):
    """Lỗi validation được đưa ngược lại cho model dưới dạng tool_result lỗi."""
    orch = _orchestrator(
        catalog,
        sample_values,
        settings,
        [
            tool_call_response({"measures": ["energy.khong_ton_tai"]}),  # measure sai
            tool_call_response({"measures": ["energy.total_consumption"]}),
        ],
    )
    result = orch.interpret("Tổng tiêu thụ điện")

    assert result.status is NLUStatus.QUERY
    assert result.query.measures == ["energy.total_consumption"]

    # Lượt thứ hai phải chứa tool_result báo lỗi cho model.
    second_call = orch.llm.calls[1]
    tool_results = [
        block
        for msg in second_call["messages"]
        if isinstance(msg["content"], list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert tool_results and tool_results[0]["is_error"] is True


def test_gives_up_after_max_repair_attempts(catalog, sample_values, settings):
    bad = tool_call_response({"measures": ["khong.ton_tai"]})
    orch = _orchestrator(catalog, sample_values, settings, [bad, bad])
    result = orch.interpret("???")

    assert result.status is NLUStatus.INVALID
    assert result.errors
    assert len(orch.llm.calls) == settings.max_repair_attempts + 1


def test_runtime_context_goes_after_the_question(catalog, sample_values, settings):
    """System prompt phải giữ nguyên byte để prompt cache (nếu provider hỗ trợ) còn tác dụng."""
    orch = _orchestrator(
        catalog,
        sample_values,
        settings,
        [tool_call_response({"measures": ["traffic.avg_speed"]})],
    )
    orch.interpret("Tốc độ trung bình?")

    messages = orch.llm.calls[0]["messages"]
    assert "runtime_context" not in orch.llm.calls[0]["system"]
    assert "runtime_context" in str(messages[0]["content"])
    assert messages[0]["content"].startswith("Tốc độ trung bình?")
