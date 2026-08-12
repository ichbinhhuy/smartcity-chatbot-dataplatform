"""Cấu hình runtime, đọc từ biến môi trường."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_env_file()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    # Cube Core self-host — semantic + query engine, xem docs/02-cube-architecture.md.
    cube_api_url: str = field(
        default_factory=lambda: os.getenv("CUBE_API_URL", "http://localhost:4000/cubejs-api/v1")
    )
    cube_api_token: str | None = field(default_factory=lambda: os.getenv("CUBE_API_TOKEN"))

    sample_values_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("SAMPLE_VALUES_PATH", str(PROJECT_ROOT / "semantic" / "sample_values.yaml"))
        )
    )

    # Apache Superset embed URL
    superset_embed_url: str = field(
        default_factory=lambda: os.getenv("SUPERSET_EMBED_URL", "http://localhost:8088")
    )

    # Chọn LLM provider — đổi giá trị này trong .env để đổi provider, không cần
    # sửa code. Giá trị hỗ trợ: openai (mặc định) | groq | google | openrouter.
    # Xem app/llm/factory.py.
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))

    # API key cho từng provider — chỉ cần điền key của provider đang chọn ở
    # LLM_PROVIDER, các key còn lại có thể để trống.
    groq_api_key: str | None = field(default_factory=lambda: os.getenv("GROQ_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    google_api_key: str | None = field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    )
    openrouter_api_key: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY"))

    # Tên model — mặc định riêng theo từng provider (xem app/llm/<provider>.py).
    # NLU_MODEL/NLG_MODEL "chung" này chỉ áp dụng khi LLM_PROVIDER=groq (tương
    # thích ngược); các provider khác dùng <PROVIDER>_NLU_MODEL/<PROVIDER>_NLG_MODEL.
    nlu_model: str | None = field(default_factory=lambda: os.getenv("NLU_MODEL"))
    nlg_model: str | None = field(default_factory=lambda: os.getenv("NLG_MODEL"))

    # Số lần cho LLM sửa lại tool call khi validation thất bại.
    max_repair_attempts: int = field(default_factory=lambda: _env_int("MAX_REPAIR_ATTEMPTS", 1))

    # Guardrail sơ khai (mở rộng ở sprint sau).
    max_row_limit: int = field(default_factory=lambda: _env_int("MAX_ROW_LIMIT", 1000))
    default_relative_period: str = field(
        default_factory=lambda: os.getenv("DEFAULT_RELATIVE_PERIOD", "last 30 days")
    )
    # Ngưỡng điểm Cosine Similarity tối thiểu để xác định câu hỏi có thuộc phạm vi catalog hay không.
    cosine_threshold: float = field(
        default_factory=lambda: float(os.getenv("COSINE_THRESHOLD", "0.3"))
    )


settings = Settings()
