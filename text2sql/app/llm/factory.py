"""Factory chọn LLM provider dựa theo biến môi trường `LLM_PROVIDER` — xem `text2sql/.env`.

Đổi provider = đổi `.env`, KHÔNG cần sửa code:

    LLM_PROVIDER=openai      (mặc định)   -> cần OPENAI_API_KEY
    LLM_PROVIDER=groq                      -> cần GROQ_API_KEY
    LLM_PROVIDER=google                    -> cần GOOGLE_API_KEY (hoặc GEMINI_API_KEY)
    LLM_PROVIDER=openrouter                -> cần OPENROUTER_API_KEY

Mỗi provider có model mặc định riêng phù hợp (xem class tương ứng trong
`app/llm/`), override được qua `<PROVIDER>_NLU_MODEL` / `<PROVIDER>_NLG_MODEL`
(vd `OPENAI_NLU_MODEL`) — hoặc qua `NLU_MODEL`/`NLG_MODEL` chung nếu đang dùng
Groq (giữ tương thích ngược với cấu hình cũ).
"""

from __future__ import annotations

from app.config import Settings
from app.config import settings as default_settings
from app.llm.client import LLMClient
from app.llm.gemini import GeminiLLMClient
from app.llm.groq import GroqLLMClient
from app.llm.openai_client import OpenAILLMClient
from app.llm.openrouter import OpenRouterLLMClient
from app.llm.types import LLMError

_PROVIDERS: dict[str, type] = {
    "groq": GroqLLMClient,
    "openai": OpenAILLMClient,
    "google": GeminiLLMClient,
    "gemini": GeminiLLMClient,
    "openrouter": OpenRouterLLMClient,
}


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    """Khởi tạo LLM client theo `settings.llm_provider` (biến môi trường `LLM_PROVIDER`)."""
    settings = settings or default_settings
    provider = (settings.llm_provider or "openai").strip().lower()

    client_cls = _PROVIDERS.get(provider)
    if client_cls is None:
        supported = ", ".join(sorted({"groq", "openai", "google", "openrouter"}))
        raise LLMError(
            f"LLM_PROVIDER='{provider}' không hợp lệ. Các giá trị được hỗ trợ: {supported}."
        )
    return client_cls()
