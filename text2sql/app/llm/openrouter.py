"""OpenRouter API client cho LLMClient protocol.

OpenRouter proxy nhiều vendor (Meta, Mistral, Google, Anthropic, ...) qua đúng
một endpoint tương thích OpenAI Chat Completions, model chọn theo dạng
`"<vendor>/<model>"` — xem https://openrouter.ai/docs.

Kích hoạt bằng cách đặt `LLM_PROVIDER=openrouter` và `OPENROUTER_API_KEY` trong
`.env` — xem `app/llm/factory.py`.
"""

from __future__ import annotations

import os

from app.config import settings
from app.llm.openai_compatible import OpenAICompatibleLLMClient


class OpenRouterLLMClient(OpenAICompatibleLLMClient):
    """Tích hợp với OpenRouter cho cả lượt NLU và NLG."""

    provider_name = "OpenRouter"
    api_key_env = "OPENROUTER_API_KEY"
    default_base_url = "https://openrouter.ai/api/v1"
    default_nlu_model = "meta-llama/llama-3.3-70b-instruct"
    default_nlg_model = "meta-llama/llama-3.1-8b-instruct"

    def __init__(
        self,
        api_key: str | None = None,
        nlu_model: str | None = None,
        nlg_model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        resolved_key = api_key or getattr(settings, "openrouter_api_key", None) or os.getenv("OPENROUTER_API_KEY")
        super().__init__(
            api_key=resolved_key,
            nlu_model=nlu_model or os.getenv("OPENROUTER_NLU_MODEL"),
            nlg_model=nlg_model or os.getenv("OPENROUTER_NLG_MODEL"),
            base_url=base_url or os.getenv("OPENROUTER_BASE_URL"),
            timeout=timeout,
        )
