"""Pipeline NLU: câu hỏi tự nhiên -> Cube query đã được validate.

    question ──▶ build context ──▶ LLM (tool use) ──▶ parse ──▶ validate ──▶ CubeQuery
                                        ▲                             │
                                        └──── tool_result(is_error) ──┘  (repair, tối đa N lần)

Không có bước dịch nào ở đây: `CubeQuery` gửi thẳng cho Cube Core
(app/query_engine/cube_client.py) — deterministic, không qua LLM.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.catalog.models import Catalog
from app.catalog.sample_values import SampleValues
from app.config import Settings, settings as default_settings
from app.llm.client import LLMClient
from app.llm.types import LLMError
from app.nlu.guardrails import check_deterministic_refusal, refusal_message
from app.nlu.parser import parse_response
from app.nlu.prompt import (
    build_clarification_suggestions,
    build_field_ambiguity_hint,
    build_runtime_context,
    build_system_prompt,
)
from app.nlu.time_ambiguity import build_vague_time_hint
from app.nlu.tool_schema import build_tools
from app.nlu.types import NLUResult, NLUStatus
from app.nlu.validator import QueryValidator
from app.retrieval.retriever import CatalogRetriever
import app.tracing as tracing


class NLUOrchestrator:
    def __init__(
        self,
        catalog: Catalog,
        llm_client: LLMClient,
        sample_values: SampleValues | None = None,
        settings: Settings | None = None,
        retriever: CatalogRetriever | None = None,
    ) -> None:
        self.catalog = catalog
        self.settings = settings or default_settings
        self.llm = llm_client
        self.validator = QueryValidator(catalog, sample_values, self.settings)
        self.retriever = retriever or CatalogRetriever(catalog)

    def interpret(
        self,
        question: str,
        history: list[dict[str, Any]] | None = None,
        today: date | None = None,
        langfuse_trace: Any = None,
        prior_query: Any = None,
    ) -> NLUResult:
        """`prior_query` (Bug 2, kế hoạch fix Phase 2): `CubeQuery`/dict của
        lần QUERY thành công gần nhất trong session — truyền thẳng xuống
        `QueryValidator.validate()` làm nguồn dự phòng tất định cho
        `timeDimensions` bị bỏ trống. Caller (`app/server.py`) chịu trách
        nhiệm đọc/ghi giá trị này từ session store; orchestrator không tự
        quản lý session."""
        messages = list(history or [])
        messages.extend(self._build_user_turn(question, today))

        # 0. Guardrail tất định (Bug 3, kế hoạch fix Phase 2) — chặn NGAY,
        # trước cả RAG/LLM, cho 2 loại yêu cầu không nên phó mặc LLM tự phán
        # đoán: phá hoại dữ liệu, rò rỉ credential/prompt injection. Benchmark
        # thực tế (R04/R05) cho thấy tool `refuse_request` (Phase 1, dựa vào
        # LLM) không đủ ổn định cho 2 loại này — xem app/nlu/guardrails.py.
        deterministic_reason = check_deterministic_refusal(question)
        if deterministic_reason is not None:
            msg = refusal_message(deterministic_reason)
            _append_assistant_message(messages, {"role": "assistant", "content": msg})
            return NLUResult(
                status=NLUStatus.REFUSAL,
                message=msg,
                refusal_reason=deterministic_reason,
                errors=[f"deterministic_refusal: {deterministic_reason}"],
                messages=messages,
            )

        # 1. Retrieval Layer: Semantic Search Top-K candidates (K=5)
        rag_span = tracing.start_span(langfuse_trace, "rag_retrieval", input={"question": question})
        candidates = self.retriever.retrieve(question, top_k=5)
        max_cosine = float(candidates.get("max_cosine_score", 0.0))
        is_ood = bool(candidates.get("is_out_of_domain", False))

        rag_span.end(output={
            "cubes": candidates.get("cubes", []),
            "max_cosine_score": max_cosine,
            "is_out_of_domain": is_ood,
        })

        # 1.5. Check Cosine Similarity Out-of-Domain Guardrail (< threshold -> Trả văn mẫu)
        if is_ood:
            out_of_domain_msg = (
                "Câu hỏi không liên quan hoặc nằm ngoài phạm vi dữ liệu hỗ trợ của hệ thống Đô thị Thông minh. "
                "Vui lòng thử lại với các câu hỏi liên quan đến chỉ số đáng sống, chất lượng không khí, giao thông, bãi đỗ xe, chiếu sáng hoặc sự cố đường phố."
            )
            _append_assistant_message(messages, {"role": "assistant", "content": out_of_domain_msg})
            return NLUResult(
                status=NLUStatus.CLARIFICATION,
                message=out_of_domain_msg,
                errors=[f"Out of domain query: Max Cosine score ({max_cosine:.4f}) < threshold ({self.retriever.cosine_threshold})"],
                messages=messages,
                suggestions=[c.title for c in self.catalog.cubes],
            )

        # 1.6. Tiêm hint mơ hồ CỤ THỂ-THEO-CÂU-HỎI (kế hoạch fix Yellow case,
        # Bước 3+6) — KHÔNG sửa `_RULES` tĩnh, không hard-block, chỉ bổ trợ
        # ngữ cảnh cho lượt hỏi hiện tại. `field_ambiguity` (mơ hồ cấp
        # measure/dimension trong 1 cube, tính tất định ở retriever) và
        # `vague_time_hint` (cụm từ thời gian mơ hồ có chủ ý, vd "lúc
        # trước") độc lập nhau, có thể cùng xuất hiện hoặc riêng lẻ.
        field_ambiguity = candidates.get("field_ambiguity")
        hint_parts = [build_field_ambiguity_hint(field_ambiguity), build_vague_time_hint(question)]
        hint = "\n\n".join(p for p in hint_parts if p)
        if hint:
            messages[-1]["content"] = f"{messages[-1]['content']}\n\n{hint}"

        # 2. Dynamic Tool Schema & System Prompt based on Top-K candidates
        system_prompt = build_system_prompt(self.catalog, candidates)
        tools = build_tools(self.catalog, candidates)

        usage_total: dict[str, int] = {}
        attempts = self.settings.max_repair_attempts + 1
        last_errors: list[str] = []
        last_raw: dict[str, Any] | None = None

        for attempt in range(attempts):
            nlu_gen = tracing.start_generation(
                langfuse_trace,
                name=f"nlu_llm_attempt_{attempt + 1}",
                model=getattr(self.llm, "nlu_model", ""),
                input={"system": system_prompt[:500] + "...", "messages": messages, "tools": tools},
                metadata={"attempt": attempt + 1, "top_cubes": candidates.get("cubes", [])},
            )
            try:
                response = self.llm.interpret_query(system_prompt, messages, tools)
            except LLMError as exc:
                nlu_gen.end(output={"error": str(exc)}, level="ERROR")
                return NLUResult(
                    status=NLUStatus.ERROR,
                    message=str(exc),
                    errors=[str(exc)],
                    messages=messages,
                    usage=usage_total,
                )

            _accumulate(usage_total, response.usage)
            parsed = parse_response(response)
            nlu_gen.end(
                output={
                    "tool_call": parsed.tool_input if parsed.has_tool_call else None,
                    "text": parsed.text,
                    "usage": response.usage,
                },
                usage={"input": response.usage.get("prompt_tokens", 0),
                       "output": response.usage.get("completion_tokens", 0)},
            )

            if parsed.is_refusal:
                return NLUResult(
                    status=NLUStatus.REFUSAL,
                    message=parsed.text,
                    refusal_reason=parsed.refusal_reason,
                    errors=[f"refusal: {parsed.refusal_reason}" if parsed.refusal_reason else "refusal"],
                    messages=messages,
                    usage=usage_total,
                )

            # Model trả lời bằng text thay vì gọi tool = tự do hội thoại hoặc làm rõ
            if not parsed.has_tool_call:
                _append_assistant_message(messages, parsed.raw_assistant_content)
                return NLUResult(
                    status=NLUStatus.CLARIFICATION,
                    message=parsed.text or "Bạn có thể nói rõ hơn về chỉ số bạn muốn xem không?",
                    messages=messages,
                    suggestions=build_clarification_suggestions(
                        self.catalog, candidates, field_ambiguity=field_ambiguity
                    ),
                    usage=usage_total,
                )

            last_raw = parsed.tool_input
            result = self.validator.validate(parsed.tool_input or {}, prior_query=prior_query)

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
            # đúng yêu cầu của hầu hết provider (Groq/OpenAI yêu cầu điều này).
            #
            # Groq (OpenAI-compat) format:
            #   assistant: {role, content (str|null→""), tool_calls: [...]}
            #   tool:      {role:"tool", tool_call_id, content (str)}
            #
            # Nếu lỗi là "giá trị filter không xác định được trong hệ thống"
            # (`SampleValues.resolve()` — 0 match hoặc ≥2 candidate tie, xem
            # `validator.py::_resolve_filter_values`) thì KHÔNG có tham số nào
            # để "tự sửa" — chỉ người dùng mới biết ý đúng. Chỉ thị mặc định
            # "Hãy gọi lại duy nhất 1 tool call" ép model PHẢI gọi tool lần
            # nữa, khiến nó không còn lựa chọn nào khác ngoài `refuse_request`
            # (tool duy nhất còn lại) — sai design, vì `build_refuse_tool()`
            # nói rõ KHÔNG dùng tool đó "chỉ để hỏi lại làm rõ 1 chi tiết còn
            # thiếu". Verify bằng benchmark LLM thật (Bước 7, Y06 "khu trung
            # tâm"): trước fix này, model trả `status=refusal` dù nội dung
            # message đã đúng 100% (liệt kê đúng 3 khu vực hợp lệ) — chỉ SAI
            # Ở CHỖ chọn nhầm tool, khiến history không được lưu (REFUSAL
            # không nằm trong `_SAVE_STATUSES`, xem `server.py`) và không thể
            # tiếp tục hội thoại nhiều lượt cho case này. Mở thêm lối thoát
            # "trả lời bằng text thường" CHỈ khi lỗi này xuất hiện — các lỗi
            # tham số khác (sai định dạng ngày, tên field...) vẫn ép retry
            # tool như cũ vì thực sự có thể tự sửa được.
            unresolved_filter_value = any(
                "không xác định được chính xác trong hệ thống" in e for e in result.errors
            )
            retry_instruction = (
                "\nGiá trị filter không xác định được trong hệ thống và KHÔNG có tham số nào có thể "
                "tự sửa đúng (không phải lỗi định dạng) — CHỈ người dùng mới biết ý đúng. TRẢ LỜI "
                "BẰNG TEXT THƯỜNG (không gọi tool) để hỏi lại người dùng, liệt kê rõ các giá trị hợp "
                "lệ đã nêu ở trên. KHÔNG dùng tool refuse_request cho trường hợp này."
                if unresolved_filter_value
                else "\nHãy gọi lại duy nhất 1 tool call với tham số đã sửa."
            )
            raw = parsed.raw_assistant_content
            tool_call_id = parsed.tool_call_id or "call_1"
            if isinstance(raw, dict) and raw.get("tool_calls"):
                assistant_msg = _append_assistant_message(messages, raw)
                for tc in assistant_msg["tool_calls"]:
                    tc_id = tc.get("id", tool_call_id)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": (
                            "Tham số không hợp lệ:\n- "
                            + "\n- ".join(result.errors)
                            + retry_instruction
                        ),
                    })
            else:
                messages.append({
                    "role": "assistant",
                    "content": parsed.text or "",
                    "tool_calls": [{
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": "query_metrics",
                            "arguments": json.dumps(parsed.tool_input or {}, ensure_ascii=False)
                        }
                    }]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": (
                        "Tham số không hợp lệ:\n- "
                        + "\n- ".join(result.errors)
                        + retry_instruction
                    ),
                })

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


def _append_assistant_message(messages: list[dict[str, Any]], raw: Any) -> dict[str, Any]:
    """Chuẩn hoá & append 1 lượt assistant, dùng chung cho nhánh clarification
    (không tool call) và nhánh repair-loop (tool call lỗi).

    `raw` (=`parsed.raw_assistant_content`) ĐÃ LÀ một dict {role, content,
    tool_calls} hoàn chỉnh cho mọi provider hiện có (mọi subclass
    OpenAICompatibleLLMClient — xem app/llm/openai_compatible.py,
    `raw_assistant_content=message`). KHÔNG được bọc thêm 1 lớp
    {"role": "assistant", "content": raw} — double-nesting biến `content`
    thành dict thay vì str/None, gây HTTP 400 ở lượt gọi kế tiếp nếu
    `messages` này được dùng làm `history` cho 1 lượt `interpret()` sau.
    """
    if isinstance(raw, dict):
        assistant_msg = dict(raw)
        if assistant_msg.get("content") is None:
            assistant_msg["content"] = ""
    else:
        assistant_msg = {"role": "assistant", "content": raw or ""}
    messages.append(assistant_msg)
    return assistant_msg
