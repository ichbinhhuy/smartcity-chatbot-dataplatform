"""Groq API client implementation cho LLMClient protocol."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from app.config import settings
from app.llm.types import LLMError, LLMResponse, LLMToolCall


class GroqLLMClient:
    """Tích hợp trực tiếp với Groq API cho cả lượt NLU và NLG."""

    def __init__(
        self,
        api_key: str | None = None,
        nlu_model: str | None = None,
        nlg_model: str | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or getattr(settings, "groq_api_key", None) or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise LLMError("Thiếu GROQ_API_KEY. Vui lòng cấu hình trong file .env hoặc biến môi trường.")
        self.nlu_model = nlu_model or settings.nlu_model or "llama-3.3-70b-versatile"
        self.nlg_model = nlg_model or settings.nlg_model or "llama-3.3-70b-versatile"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def interpret_query(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        """NLU Phase: Chuyển câu hỏi -> Lời gọi tool query_metrics hoặc text làm rõ."""
        formatted_messages = [{"role": "system", "content": system_prompt}] + messages

        formatted_tools = []
        for t in tools:
            if "type" in t and t["type"] == "function":
                formatted_tools.append(t)
            else:
                formatted_tools.append({
                    "type": "function",
                    "function": {
                        "name": t.get("name"),
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters") or t.get("input_schema", {}),
                    },
                })

        payload = {
            "model": self.nlu_model,
            "messages": formatted_messages,
            "tools": formatted_tools,
            "tool_choice": "auto",
            "temperature": 0.1,
        }

        try:
            return self._call_api(payload)
        except LLMError as exc:
            err_str = str(exc).lower()
            if any(k in err_str for k in ["tool call validation failed", "failed to call a function", "failed_generation", "400"]):
                # Fallback: Relax nested enums in tool schema to allow model output through to Python validator
                relaxed_tools = json.loads(json.dumps(formatted_tools))
                self._relax_schema_enums(relaxed_tools)
                payload["tools"] = relaxed_tools
                return self._call_api(payload)
            raise

    def _relax_schema_enums(self, obj: Any) -> None:
        """Loại bỏ các ràng buộc quá khắt khe để Groq API gateway không reject payload của 8B model."""
        if isinstance(obj, dict):
            for k in list(obj.keys()):
                if k in ["enum", "additionalProperties", "minItems", "minimum", "maximum"]:
                    del obj[k]
                else:
                    self._relax_schema_enums(obj[k])
        elif isinstance(obj, list):
            for item in obj:
                self._relax_schema_enums(item)

    def generate_answer(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> LLMResponse:
        """NLG Phase: Tóm tắt kết quả từ Cube Core thành câu trả lời tự nhiên."""
        formatted_messages = [{"role": "system", "content": system_prompt}] + messages
        payload = {
            "model": self.nlg_model,
            "messages": formatted_messages,
            "temperature": 0.3,
        }
        return self._call_api(payload)

    def _call_api(self, payload: dict[str, Any]) -> LLMResponse:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            res = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            if res.status_code != 200:
                error_detail = res.text
                try:
                    err_json = res.json()
                    error_detail = err_json.get("error", {}).get("message") or res.text
                except Exception:
                    pass
                raise LLMError(f"Groq API trả về lỗi HTTP {res.status_code}: {error_detail}")
            data = res.json()
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"Gọi Groq API thất bại: {exc}") from exc

        try:
            choice = data["choices"][0]
            message = choice["message"]
            text_content = message.get("content") or ""
            raw_tool_calls = message.get("tool_calls") or []

            tool_calls = []
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                args_raw = func.get("arguments", "{}")
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                tool_calls.append(
                    LLMToolCall(
                        id=tc.get("id", "call_1"),
                        name=func.get("name", "query_metrics"),
                        input=args,
                    )
                )

            usage = data.get("usage", {})
            return LLMResponse(
                text=text_content,
                tool_calls=tool_calls,
                raw_assistant_content=message,
                usage={
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                },
            )
        except Exception as exc:
            raise LLMError(f"Không parse được response từ Groq API: {exc}") from exc
