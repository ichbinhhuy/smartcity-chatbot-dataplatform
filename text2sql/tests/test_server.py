"""Test cho `/api/chat` qua FastAPI TestClient — tập trung vào wiring
session_id / multi-turn (xem app/server.py `_resolve_session`/`_persist_turn`).

Dùng FakeLLMClient (xem tests/conftest.py) + FakeCubeClient để không cần Cube
Core/StarRocks/LLM provider thật chạy nền. `get_retriever()` KHÔNG bị
monkeypatch — dùng CatalogRetriever thật (giống cách test_orchestrator.py đã
làm từ trước, xem NLUOrchestrator(..., retriever=None) mặc định), degrade êm
nếu không có Qdrant/model embedding thật (xem app/retrieval/retriever.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.server as server_module
from app.session.factory import reset_session_store_cache
from tests.conftest import FakeLLMClient, text_response, tool_call_response


class FakeCubeClient:
    """Thay CubeClient thật — không gọi Cube Core/StarRocks."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def load(self, query):
        return {"data": [{"traffic_flow.avg_speed": 42}], "annotation": {}}


@pytest.fixture(autouse=True)
def _reset_session_store():
    """SessionStore là singleton cache ở module-level (xem app/session/factory.py)
    — reset giữa các test để test sau không kế thừa session của test trước."""
    reset_session_store_cache()
    yield
    reset_session_store_cache()


@pytest.fixture
def client(catalog, sample_values, monkeypatch):
    monkeypatch.setattr(server_module, "get_catalog", lambda: catalog)
    monkeypatch.setattr(server_module, "get_sample_values", lambda: sample_values)
    monkeypatch.setattr(server_module, "CubeClient", FakeCubeClient)
    with TestClient(server_module.app) as c:
        yield c


def _set_llm(monkeypatch, fake_llm: FakeLLMClient) -> None:
    monkeypatch.setattr(server_module, "get_llm_client", lambda: fake_llm)


def test_generates_session_id_when_none_supplied(client, monkeypatch):
    fake_llm = FakeLLMClient([tool_call_response({"measures": ["traffic_flow.avg_speed"]})])
    _set_llm(monkeypatch, fake_llm)

    res = client.post("/api/chat", json={"question": "Tốc độ trung bình?"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["session_id"]


def test_clarification_then_followup_reuses_session_id(client, monkeypatch):
    clarify_text = "Bạn muốn xem tốc độ hay lưu lượng xe?"
    fake_llm = FakeLLMClient(
        [
            text_response(
                clarify_text,
                raw_assistant_content={"role": "assistant", "content": clarify_text},
            ),
            tool_call_response({"measures": ["traffic_flow.avg_speed"]}),
        ]
    )
    _set_llm(monkeypatch, fake_llm)

    res1 = client.post("/api/chat", json={"question": "Cho tôi xem giao thông"})
    body1 = res1.json()
    assert body1["status"] == "clarification"
    session_id = body1["session_id"]
    assert session_id

    res2 = client.post("/api/chat", json={"question": "Tốc độ", "session_id": session_id})
    body2 = res2.json()
    assert body2["status"] == "success"
    assert body2["session_id"] == session_id
    assert body2["query"]["measures"] == ["traffic_flow.avg_speed"]


def test_repeated_clarification_escalates_to_full_catalog_listing(client, monkeypatch):
    """Sau `settings.max_clarification_streak` (mặc định 2) lượt CLARIFICATION
    liên tiếp cùng 1 session, hệ thống phải đổi chiến lược — liệt kê toàn bộ
    danh mục thay vì tiếp tục hỏi trắc nghiệm hẹp. Xem app/server.py
    `_apply_clarification_cap` và docs/04-ambiguous-question-handling.md case I."""
    fake_llm = FakeLLMClient(
        [
            text_response("Bạn muốn xem chỉ số nào: điện hay giao thông?"),
            text_response("Vẫn chưa rõ, bạn muốn xem gì cụ thể?"),
            text_response("Mình chưa hiểu, bạn có thể nói rõ hơn không?"),
        ]
    )
    _set_llm(monkeypatch, fake_llm)

    session_id = None
    bodies = []
    for _ in range(3):
        payload = {"question": "cho tôi xem số liệu"}
        if session_id:
            payload["session_id"] = session_id
        res = client.post("/api/chat", json=payload)
        body = res.json()
        bodies.append(body)
        session_id = body["session_id"]

    assert [b["status"] for b in bodies] == ["clarification"] * 3
    # 2 lượt đầu vẫn là message gốc từ LLM (chưa vượt streak).
    assert bodies[0]["answer"] == "Bạn muốn xem chỉ số nào: điện hay giao thông?"
    assert bodies[1]["answer"] == "Vẫn chưa rõ, bạn muốn xem gì cụ thể?"
    # Lượt thứ 3 vượt max_clarification_streak -> bị escalate, không còn là
    # message gốc từ LLM nữa, và suggestions liệt kê toàn bộ cube.
    assert bodies[2]["answer"] != "Mình chưa hiểu, bạn có thể nói rõ hơn không?"
    assert bodies[2]["suggestions"]


def test_unknown_session_id_starts_fresh_history(client, monkeypatch):
    fake_llm = FakeLLMClient([tool_call_response({"measures": ["traffic_flow.avg_speed"]})])
    _set_llm(monkeypatch, fake_llm)

    res = client.post(
        "/api/chat",
        json={"question": "Tốc độ trung bình?", "session_id": "chua-tung-thay-bao-gio"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"


def test_empty_question_returns_400(client, monkeypatch):
    fake_llm = FakeLLMClient([])
    _set_llm(monkeypatch, fake_llm)

    res = client.post("/api/chat", json={"question": "   "})
    assert res.status_code == 400
