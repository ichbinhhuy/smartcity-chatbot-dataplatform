"""Test cho `OpenAICompatibleLLMClient` NLG payload/`finish_reason` — Bug 4
trong kế hoạch fix: provider không nhận `max_tokens` nên có thể generate quá
dài/lặp vô hạn, và `finish_reason` bị bỏ qua nên response bị cắt (`"length"`)
không được caller biết để cảnh báo người dùng.

Không gọi API thật — monkeypatch `httpx.post`/`httpx.stream`.
"""

from __future__ import annotations

import json

import httpx

from app.config import settings as app_settings
from app.llm.openai_compatible import OpenAICompatibleLLMClient


def _client() -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(api_key="test-key")


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def test_generate_answer_sends_nlg_max_tokens(monkeypatch):
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(
            {
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    _client().generate_answer("system prompt", [{"role": "user", "content": "hoi"}])

    assert captured["payload"]["max_tokens"] == app_settings.nlg_max_tokens


def test_generate_answer_propagates_length_finish_reason(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(
            {
                "choices": [{"message": {"content": "cau tra loi bi cat..."}, "finish_reason": "length"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1200},
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    res = _client().generate_answer("system prompt", [{"role": "user", "content": "hoi"}])

    assert res.finish_reason == "length"


def test_generate_answer_defaults_finish_reason_none_when_missing(monkeypatch):
    """Provider không trả `finish_reason` (hoặc bằng "stop") -> không nên bị
    hiểu nhầm là bị cắt."""

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(
            {
                "choices": [{"message": {"content": "OK"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    res = _client().generate_answer("system prompt", [{"role": "user", "content": "hoi"}])

    assert res.finish_reason is None
