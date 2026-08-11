"""Base client dùng chung cho các provider tương thích chuẩn OpenAI Chat Completions.

Groq, OpenAI, Google Gemini (qua compatibility layer) và OpenRouter đều expose
đúng một wire format: `POST {base_url}/chat/completions`, header
`Authorization: Bearer <key>`, tool schema dạng `{"type": "function", "function": {...}}`.
Vì vậy chỉ cần đổi `base_url` / API key / model mặc định là dùng lại được toàn bộ
logic gọi API, parse response và retry — xem `GroqLLMClient`, `OpenAILLMClient`,
`GeminiLLMClient`, `OpenRouterLLMClient`.

Muốn thêm một provider OpenAI-compatible khác (Together, Fireworks, DeepSeek,
Ollama, Azure OpenAI, ...) chỉ cần subclass `OpenAICompatibleLLMClient` và set
`provider_name` / `default_base_url` / `default_nlu_model` / `default_nlg_model`
— không cần lặp lại logic gọi API.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.llm.types import LLMError, LLMResponse, LLMToolCall


class OpenAICompatibleLLMClient:
    """LLMClient implementation cho provider expose REST API kiểu OpenAI Chat Completions."""

    # Subclass ghi đè các attribute này để cấu hình provider cụ thể.
    provider_name: str = "OpenAI-compatible"
    default_base_url: str = "https://api.openai.com/v1"
    default_nlu_model: str = "gpt-4o-mini"
    default_nlg_model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"

    def __init__(
        self,
        api_key: str | None = None,
        nlu_model: str | None = None,
        nlg_model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise LLMError(
                f"Thiếu API key cho provider {self.provider_name}. "
                f"Vui lòng cấu hình biến môi trường {self.api_key_env} trong file .env."
            )
        self.api_key = api_key
        self.nlu_model = nlu_model or self.default_nlu_model
        self.nlg_model = nlg_model or self.default_nlg_model
        self.base_url = (base_url or self.default_base_url).rstrip("/")
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
                # Fallback: nới lỏng ràng buộc lồng nhau trong tool schema để
                # gateway (Groq, hoặc provider khác strict tương tự) không
                # reject payload, để validator phía Python tự bắt lỗi thay.
                relaxed_tools = json.loads(json.dumps(formatted_tools))
                self._relax_schema_enums(relaxed_tools)
                payload["tools"] = relaxed_tools
                return self._call_api(payload)
            raise

    def _relax_schema_enums(self, obj: Any) -> None:
        """Loại bỏ các ràng buộc quá khắt khe để API gateway không reject payload."""
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

    def generate_answer_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ):
        """NLG Phase: Stream tokens as they are generated by LLM via Server-Sent Events."""
        formatted_messages = [{"role": "system", "content": system_prompt}] + messages
        payload = {
            "model": self.nlg_model,
            "messages": formatted_messages,
            "temperature": 0.3,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=self.timeout) as res:
                for line in res.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_json = json.loads(data_str)
                        delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield content
                    except Exception:
                        pass
        except Exception as exc:
            yield f"\n[Lỗi Stream NLG: {exc}]"

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
                raise LLMError(f"{self.provider_name} API trả về lỗi HTTP {res.status_code}: {error_detail}")
            data = res.json()
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"Gọi {self.provider_name} API thất bại: {exc}") from exc

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
            raise LLMError(f"Không parse được response từ {self.provider_name} API: {exc}") from exc
