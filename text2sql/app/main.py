"""CLI demo cho module Text2SQL NLU + Cube Core (đa LLM provider — xem app/llm/factory.py).

Usage:
    python -m app.main --inspect                             # Gọi Cube Meta API thật, in prompt + tool schema
    python -m app.main --inspect --meta-file path/to/meta.json  # Offline, không cần Cube Core chạy
    python -m app.main "Tốc độ lưu thông trung bình tuần này thế nào?"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.catalog.cube_meta import fetch_catalog, parse_catalog
from app.catalog.models import Catalog
from app.catalog.sample_values import SampleValues
from app.config import settings
from app.llm.factory import get_llm_client
from app.nlu.orchestrator import NLUOrchestrator
from app.nlu.prompt import build_system_prompt
from app.nlu.tool_schema import build_tools
from app.nlu.types import NLUStatus
from app.query_engine.cube_client import CubeClient, CubeQueryError


def _load_catalog(meta_file: str | None) -> Catalog:
    if meta_file:
        payload = json.loads(Path(meta_file).read_text(encoding="utf-8"))
        return parse_catalog(payload)
    return fetch_catalog(settings.cube_api_url, settings.cube_api_token)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Text-to-SQL SmartCity Agent (đa LLM provider + Cube Core backend)")
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
        parser.error("Cần truyền câu hỏi, hoặc dùng --inspect")

    # Load LLM Client (provider chọn qua LLM_PROVIDER trong .env) & Orchestrator
    try:
        llm = get_llm_client()
    except Exception as exc:
        print(f"Lỗi khởi tạo LLM Client (provider={settings.llm_provider}): {exc}")
        return 1

    sample_values = SampleValues.load(settings.sample_values_path)
    orchestrator = NLUOrchestrator(
        catalog=catalog,
        llm_client=llm,
        sample_values=sample_values,
        settings=settings,
    )

    print(f"\n❓ Câu hỏi: {args.question}\n")
    print(f"⏳ Đang xử lý NLU (provider={settings.llm_provider})...")

    nlu_result = orchestrator.interpret(args.question)

    if nlu_result.status == NLUStatus.CLARIFICATION:
        print("\n💬 Yêu cầu làm rõ:")
        print(nlu_result.message)
        return 0

    if nlu_result.status != NLUStatus.QUERY or not nlu_result.query:
        print(f"\n❌ Lỗi NLU ({nlu_result.status.value}): {nlu_result.message}")
        if nlu_result.errors:
            for err in nlu_result.errors:
                print(f"  - {err}")
        return 1

    print("\n✅ Structured Query sinh ra cho Cube Core:")
    query_payload = nlu_result.query.to_cube_payload()
    print(json.dumps(query_payload, indent=2, ensure_ascii=False))

    print("\n⏳ Đang thực thi query tại Cube Core (port 4000)...")
    cube_client = CubeClient(settings=settings)

    try:
        cube_data = cube_client.load(nlu_result.query)
    except CubeQueryError as exc:
        print(f"\n❌ Lỗi từ Cube Core: {exc}")
        return 1

    print("\n📊 Kết quả thô từ Cube Core:")
    print(json.dumps(cube_data, indent=2, ensure_ascii=False))

    print("\n⏳ Đang tóm tắt câu trả lời (NLG)...")
    nlg_prompt = "Bạn là trợ lý dữ liệu Smart City. Hãy dựa vào kết quả JSON dưới đây để trả lời câu hỏi của người dùng một cách tự nhiên, ngắn gọn và chính xác."
    nlg_messages = [
        {"role": "user", "content": f"Câu hỏi: {args.question}\nKết quả JSON từ Cube:\n{json.dumps(cube_data, ensure_ascii=False)}"}
    ]

    nlg_response = llm.generate_answer(nlg_prompt, nlg_messages)
    print("\n🤖 Trợ lý Smart City trả lời:")
    print(nlg_response.text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
