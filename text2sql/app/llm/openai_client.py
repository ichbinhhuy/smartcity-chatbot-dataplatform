"""OpenAI API client (ChatGPT) cho LLMClient protocol.

Kích hoạt bằng cách đặt `LLM_PROVIDER=openai` và `OPENAI_API_KEY` trong `.env`
— xem `app/llm/factory.py`.
"""

from __future__ import annotations

import os

from app.config import settings
from app.llm.openai_compatible import OpenAICompatibleLLMClient


class OpenAILLMClient(OpenAICompatibleLLMClient):
    """Tích hợp trực tiếp với OpenAI Chat Completions API cho cả lượt NLU và NLG."""

    provider_name = "OpenAI"
    api_key_env = "OPENAI_API_KEY"
    default_base_url = "https://api.openai.com/v1"
    default_nlu_model = "gpt-4o-mini"
    default_nlg_model = "gpt-4o-mini"

    def __init__(
        self,
        api_key: str | None = None,
        nlu_model: str | None = None,
        nlg_model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        resolved_key = api_key or getattr(settings, "openai_api_key", None) or os.getenv("OPENAI_API_KEY")
        super().__init__(
            api_key=resolved_key,
            nlu_model=nlu_model or os.getenv("OPENAI_NLU_MODEL"),
            nlg_model=nlg_model or os.getenv("OPENAI_NLG_MODEL"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            timeout=timeout,
        )
