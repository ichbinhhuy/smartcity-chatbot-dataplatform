"""Client gọi Cube Core REST API — thay cho Semantic Engine tự viết SQL compiler.

Cube Core tự sinh SQL, xử lý join/pre-aggregation và thực thi trên data
warehouse — xem docs/02-cube-architecture.md mục 1-2. Module này chỉ lo giao
tiếp HTTP, không chứa logic nghiệp vụ.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, settings as default_settings
from app.nlu.types import CubeQuery


class CubeQueryError(RuntimeError):
    """Lỗi khi gọi Cube Core — khác bản chất với lỗi validation cấu trúc ở QueryValidator.

    QueryValidator bắt lỗi mà LLM có thể tự sửa (chọn sai field, order_by sai...).
    Lỗi ở đây xảy ra LÚC THỰC THI, khi Cube đã nhận query hợp lệ về cấu trúc
    nhưng phát hiện vấn đề mà chỉ nó mới biết (không có join path, DB lỗi...) —
    đây là nhánh "lỗi runtime" trong diagram ở docs/02-cube-architecture.md mục 2,
    KHÔNG feed ngược qua tool_result như lỗi validation.
    """


class CubeValidationError(CubeQueryError):
    """Cube từ chối query vì lý do ngữ nghĩa (không có join path, sai kiểu operator...)."""


class CubeExecutionError(CubeQueryError):
    """Lỗi lúc thực thi SQL thật trên data warehouse (timeout, permission, DB down, network)."""


class CubeClient:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or default_settings
        self._client = client or httpx.Client(timeout=30.0)

    def load(self, query: CubeQuery) -> dict[str, Any]:
        """Gửi query tới Cube REST API `/load`, trả JSON kết quả thô."""
        headers = {"Authorization": self.settings.cube_api_token} if self.settings.cube_api_token else {}
        try:
            response = self._client.post(
                f"{self.settings.cube_api_url}/load",
                json={"query": query.to_cube_payload()},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise CubeExecutionError(f"Không gọi được Cube Core: {exc}") from exc

        if response.status_code == 400:
            raise CubeValidationError(_extract_error(response))
        if response.status_code >= 500:
            raise CubeExecutionError(_extract_error(response))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise CubeExecutionError(_extract_error(response)) from exc
        return response.json()

    def _post_load(self, query_payload: dict[str, Any]) -> dict[str, Any]:
        """Gửi raw dict query tới Cube REST API `/load`."""
        headers = {"Authorization": self.settings.cube_api_token} if self.settings.cube_api_token else {}
        try:
            response = self._client.post(
                f"{self.settings.cube_api_url}/load",
                json={"query": query_payload},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise CubeExecutionError(f"Lỗi truy vấn Cube Core: {exc}") from exc



def _extract_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        return payload.get("error") or payload.get("message") or response.text
    except ValueError:
        return response.text
