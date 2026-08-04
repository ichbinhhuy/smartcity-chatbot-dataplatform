"""CubeClient — chỉ lo giao tiếp HTTP với Cube Core, dùng httpx.MockTransport để test
không cần Cube Core chạy thật.
"""

from __future__ import annotations

import httpx
import pytest

from app.query_engine.cube_client import CubeClient, CubeExecutionError, CubeValidationError
from app.nlu.types import CubeQuery


def _client(handler, settings) -> CubeClient:
    transport = httpx.MockTransport(handler)
    return CubeClient(settings=settings, client=httpx.Client(transport=transport))


def _query() -> CubeQuery:
    return CubeQuery(measures=["energy.total_consumption"])


def test_load_returns_json_on_success(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/load")
        body = request.read()
        assert b"energy.total_consumption" in body
        return httpx.Response(200, json={"data": [{"energy.total_consumption": 123}]})

    result = _client(handler, settings).load(_query())
    assert result["data"][0]["energy.total_consumption"] == 123


def test_load_raises_validation_error_on_400(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "Can't find join path"})

    with pytest.raises(CubeValidationError, match="join path"):
        _client(handler, settings).load(_query())


def test_load_raises_execution_error_on_500(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "Database connection timeout"})

    with pytest.raises(CubeExecutionError, match="timeout"):
        _client(handler, settings).load(_query())


def test_load_raises_execution_error_on_network_failure(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(CubeExecutionError, match="Không gọi được Cube Core"):
        _client(handler, settings).load(_query())


def test_to_cube_payload_serializes_order_as_object():
    query = CubeQuery(
        measures=["energy.total_consumption"],
        order=[{"field": "energy.total_consumption", "direction": "desc"}],
    )
    payload = query.to_cube_payload()
    assert payload["order"] == {"energy.total_consumption": "desc"}
