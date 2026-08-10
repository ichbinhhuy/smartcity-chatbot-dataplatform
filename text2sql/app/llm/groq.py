"""Groq API client — provider mặc định của project (dùng ngay từ bản đầu).

Đổi sang provider khác: đặt `LLM_PROVIDER` trong `.env`, không cần sửa code
— xem `app/llm/factory.py`.
"""

from __future__ import annotations

import os

from app.config import settings
from app.llm.openai_compatible import OpenAICompatibleLLMClient


class GroqLLMClient(OpenAICompatibleLLMClient):
    """Tích hợp trực tiếp với Groq API (OpenAI-compatible) cho cả lượt NLU và NLG."""

    provider_name = "Groq"
    api_key_env = "GROQ_API_KEY"
    default_base_url = "https://api.groq.com/openai/v1"
    default_nlu_model = "llama-3.3-70b-versatile"
    default_nlg_model = "llama-3.1-8b-instant"

    def __init__(
        self,
        api_key: str | None = None,
        nlu_model: str | None = None,
        nlg_model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        resolved_key = api_key or getattr(settings, "groq_api_key", None) or os.getenv("GROQ_API_KEY")
        super().__init__(
            api_key=resolved_key,
            # NLU_MODEL/NLG_MODEL "chung" trước đây chỉ có nghĩa cho Groq — giữ
            # lại fallback này để không phá cấu hình .env của người dùng cũ.
            nlu_model=nlu_model or os.getenv("GROQ_NLU_MODEL") or settings.nlu_model,
            nlg_model=nlg_model or os.getenv("GROQ_NLG_MODEL") or settings.nlg_model,
            base_url=base_url or os.getenv("GROQ_BASE_URL"),
            timeout=timeout,
        )
