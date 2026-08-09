from __future__ import annotations

import json
from typing import Any

import pytest

from app.catalog.cube_meta import parse_catalog
from app.catalog.models import Catalog
from app.catalog.sample_values import SampleValues
from app.config import PROJECT_ROOT, Settings
from app.llm.types import LLMResponse, LLMToolCall

FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
SAMPLE_VALUES_PATH = PROJECT_ROOT / "semantic" / "sample_values.yaml"


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    payload = json.loads((FIXTURES_DIR / "cube_meta.json").read_text(encoding="utf-8"))
    return parse_catalog(payload)


@pytest.fixture(scope="session")
def sample_values() -> SampleValues:
    return SampleValues.load(SAMPLE_VALUES_PATH)


@pytest.fixture
def settings() -> Settings:
    return Settings()


# --------------------------------------------------------------------------
# Test double cho LLMClient — trả về LLMResponse đã dựng sẵn, ghi lại request
# để assert. Không phụ thuộc SDK của provider nào (xem app/llm/client.py).
# --------------------------------------------------------------------------


class FakeLLMClient:
    """Trả về lần lượt các `LLMResponse` đã dựng sẵn, và ghi lại request để assert."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def interpret_query(self, system_prompt, messages, tools):
        self.calls.append(
            {"system": system_prompt, "messages": [dict(m) for m in messages], "tools": tools}
        )
        if not self.responses:
            raise AssertionError("FakeLLMClient hết response nhưng vẫn bị gọi thêm")
        return self.responses.pop(0)

    def generate_answer(self, system_prompt, messages):
        raise NotImplementedError("Chưa dùng tới trong test NLU hiện tại")


def tool_call_response(input: dict[str, Any], **kwargs: Any) -> LLMResponse:
    """Tiện ích dựng nhanh một LLMResponse có tool call `query_metrics`."""
    return LLMResponse(
        tool_calls=[LLMToolCall(id="call_test_1", name="query_metrics", input=input)],
        usage={"input_tokens": 100, "output_tokens": 50},
        **kwargs,
    )


def text_response(text: str, **kwargs: Any) -> LLMResponse:
    return LLMResponse(text=text, usage={"input_tokens": 100, "output_tokens": 50}, **kwargs)


def refusal_response(reason: str = "cyber") -> LLMResponse:
    return LLMResponse(
        is_refusal=True,
        refusal_reason=reason,
        text="Yêu cầu bị từ chối vì lý do an toàn.",
        usage={"input_tokens": 100, "output_tokens": 0},
    )
