"""Pipeline NLU: câu hỏi tự nhiên -> Cube query đã được validate.

    question ──▶ build context ──▶ LLM (tool use) ──▶ parse ──▶ validate ──▶ CubeQuery
                                        ▲                             │
                                        └──── tool_result(is_error) ──┘  (repair, tối đa N lần)

Không có bước dịch nào ở đây: `CubeQuery` gửi thẳng cho Cube Core
(app/query_engine/cube_client.py) — deterministic, không qua LLM.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.catalog.models import Catalog
from app.catalog.sample_values import SampleValues
from app.config import Settings, settings as default_settings
from app.llm.client import LLMClient
from app.llm.types import LLMError
from app.nlu.parser import parse_response
from app.nlu.prompt import build_runtime_context, build_system_prompt
from app.nlu.tool_schema import build_tools
from app.nlu.types import NLUResult, NLUStatus
from app.nlu.validator import QueryValidator


class NLUOrchestrator:
    def __init__(
        self,
        catalog: Catalog,
        llm_client: LLMClient,
        sample_values: SampleValues | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.catalog = catalog
        self.settings = settings or default_settings
        self.llm = llm_client
        self.validator = QueryValidator(catalog, sample_values, self.settings)

        # Sinh một lần lúc khởi tạo: prompt và tool schema là hàm thuần của catalog.
        self.system_prompt = build_system_prompt(catalog)
        self.tools = build_tools(catalog)

    def interpret(
        self,
        question: str,
        history: list[dict[str, Any]] | None = None,
        today: date | None = None,
    ) -> NLUResult:
        messages = list(history or [])
        messages.extend(self._build_user_turn(question, today))

        usage_total: dict[str, int] = {}
        attempts = self.settings.max_repair_attempts + 1
        last_errors: list[str] = []
        last_raw: dict[str, Any] | None = None

        for attempt in range(attempts):
            try:
                response = self.llm.interpret_query(self.system_prompt, messages, self.tools)
            except LLMError as exc:
                return NLUResult(
                    status=NLUStatus.ERROR,
                    message=str(exc),
                    errors=[str(exc)],
                    messages=messages,
                    usage=usage_total,
                )

            _accumulate(usage_total, response.usage)
            parsed = parse_response(response)

            if parsed.is_refusal:
                return NLUResult(
                    status=NLUStatus.REFUSAL,
                    message=parsed.text,
                    errors=[f"refusal: {parsed.refusal_reason}" if parsed.refusal_reason else "refusal"],
                    messages=messages,
                    usage=usage_total,
                )

            # Model trả lời bằng text thay vì gọi tool = nó không chắc.
            # Đây là cơ chế disambiguation, không phải lỗi.
            if not parsed.has_tool_call:
                messages.append({"role": "assistant", "content": parsed.raw_assistant_content})
                return NLUResult(
                    status=NLUStatus.CLARIFICATION,
                    message=parsed.text or "Bạn có thể nói rõ hơn về chỉ số bạn muốn xem không?",
                    messages=messages,
                    usage=usage_total,
                )

            last_raw = parsed.tool_input
            result = self.validator.validate(parsed.tool_input or {})

            if result.ok and result.query is not None:
                return NLUResult(
                    status=NLUStatus.QUERY,
                    query=result.query,
                    message="\n".join(result.notes) or None,
                    raw_tool_input=last_raw,
                    messages=messages,
                    usage=usage_total,
                )

            last_errors = result.errors
            if attempt == attempts - 1:
                break

            # Đưa lỗi validation ngược lại cho model dưới dạng tool_result lỗi
            # để nó tự sửa tham số. Echo lại assistant content nguyên bản trước,
            # đúng yêu cầu của hầu hết provider (Claude yêu cầu điều này, ví dụ).
            messages.append({"role": "assistant", "content": parsed.raw_assistant_content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": parsed.tool_call_id,
                            "is_error": True,
                            "content": (
                                "Tham số không hợp lệ:\n- "
                                + "\n- ".join(result.errors)
                                + "\nHãy gọi lại tool với tham số đã sửa, "
                                "hoặc hỏi lại người dùng nếu vẫn chưa rõ."
                            ),
                        }
                    ],
                }
            )

        return NLUResult(
            status=NLUStatus.INVALID,
            message="Chưa dựng được truy vấn hợp lệ từ câu hỏi này.",
            errors=last_errors,
            raw_tool_input=last_raw,
            messages=messages,
            usage=usage_total,
        )

    # ----------------------------------------------------------------- private

    def _build_user_turn(self, question: str, today: date | None) -> list[dict[str, Any]]:
        """Đặt runtime context SAU câu hỏi để không phá prompt cache của system prompt.

        Không có cơ chế đặc thù provider nào ở đây (vd kênh "system" giữa hội
        thoại của Claude) — LLM cụ thể chưa chốt, nên giữ format message chung
        nhất (role/content) và để implementation của LLMClient tối ưu thêm nếu cần.
        """
        context = build_runtime_context(today, self.settings.default_relative_period)
        return [{"role": "user", "content": f"{question}\n\n{context}"}]


def _accumulate(total: dict[str, int], delta: dict[str, int]) -> None:
    for key, value in delta.items():
        total[key] = total.get(key, 0) + value
