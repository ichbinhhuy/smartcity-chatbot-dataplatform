"""Google Gemini API client cho LLMClient protocol.

Gemini expose thẳng endpoint tương thích OpenAI Chat Completions
(`/v1beta/openai/chat/completions`, xem https://ai.google.dev/gemini-api/docs/openai)
nên tái sử dụng toàn bộ logic của `OpenAICompatibleLLMClient`, không cần SDK riêng.

Kích hoạt bằng cách đặt `LLM_PROVIDER=google` và `GOOGLE_API_KEY` (hoặc
`GEMINI_API_KEY`) trong `.env` — xem `app/llm/factory.py`.
"""

from __future__ import annotations

import os

from app.config import settings
from app.llm.openai_compatible import OpenAICompatibleLLMClient


class GeminiLLMClient(OpenAICompatibleLLMClient):
    """Tích hợp với Google Gemini (qua compatibility layer) cho cả lượt NLU và NLG."""

    provider_name = "Google Gemini"
    api_key_env = "GOOGLE_API_KEY (hoặc GEMINI_API_KEY)"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    default_nlu_model = "gemini-2.0-flash"
    default_nlg_model = "gemini-2.0-flash"

    def __init__(
        self,
        api_key: str | None = None,
        nlu_model: str | None = None,
        nlg_model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        resolved_key = (
            api_key
            or getattr(settings, "google_api_key", None)
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        super().__init__(
            api_key=resolved_key,
            nlu_model=nlu_model or os.getenv("GOOGLE_NLU_MODEL"),
            nlg_model=nlg_model or os.getenv("GOOGLE_NLG_MODEL"),
            base_url=base_url or os.getenv("GOOGLE_BASE_URL"),
            timeout=timeout,
        )
