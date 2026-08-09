"""CLI demo cho module NLU.

    python -m app.main --inspect                             # gọi Cube Meta API thật, in prompt + tool schema
    python -m app.main --inspect --meta-file path/to/meta.json  # offline, không cần Cube Core chạy
    python -m app.main "Tổng tiêu thụ điện quận 1 tháng trước là bao nhiêu?"

Chạy câu hỏi thật cần một `LLMClient` cụ thể — provider LLM chưa chốt (xem
docs/02-cube-architecture.md), nên `main()` không có default để inject.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.catalog.cube_meta import fetch_catalog, parse_catalog
from app.catalog.models import Catalog
from app.config import settings
from app.nlu.prompt import build_system_prompt
from app.nlu.tool_schema import build_tools


def _load_catalog(meta_file: str | None) -> Catalog:
    if meta_file:
        payload = json.loads(Path(meta_file).read_text(encoding="utf-8"))
        return parse_catalog(payload)
    return fetch_catalog(settings.cube_api_url, settings.cube_api_token)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Text-to-SQL NLU demo (Cube Core backend)")
    parser.add_argument("question", nargs="?", help="Câu hỏi bằng ngôn ngữ tự nhiên")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="In system prompt và tool schema được sinh ra, không gọi LLM",
    )
    parser.add_argument(
        "--meta-file",
        help="Đọc catalog từ file JSON đã export (offline), thay vì gọi Cube Meta API",
    )
    args = parser.parse_args(argv)

    catalog = _load_catalog(args.meta_file)

    if args.inspect:
        print("=" * 70)
        print("SYSTEM PROMPT")
        print("=" * 70)
        print(build_system_prompt(catalog))
        print()
        print("=" * 70)
        print("TOOL SCHEMA")
        print("=" * 70)
        print(json.dumps(build_tools(catalog), indent=2, ensure_ascii=False))
        return 0

    if not args.question:
        parser.error("cần truyền câu hỏi, hoặc dùng --inspect")

    parser.error(
        "Chưa có LLM provider cụ thể được cấu hình (xem docs/02-cube-architecture.md — "
        "'LLM cụ thể chưa chốt'). Viết một class thoả app.llm.client.LLMClient rồi inject "
        "vào app.nlu.orchestrator.NLUOrchestrator để chạy câu hỏi thật."
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
