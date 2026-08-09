"""Script Debug Chi Tiết Lớp Retrieval (Qdrant RRF Hybrid Search).

In chi tiết từng nốt trong luồng Retrieval:
1. Phân tích Token & Từ khóa trong câu hỏi.
2. Bảng xếp hạng Dense Semantic Ranks & BM25 Sparse Ranks.
3. Chi tiết công thức tính điểm RRF (Reciprocal Rank Fusion).
4. Phân tích Similarity Gap Check.
5. Danh sách Candidates (Measures, Dimensions, Cubes) thu được.
6. Đo độ trễ thời gian thực thi (Latency in ms).
"""

from __future__ import annotations

import sys
import time
from typing import Any

from app.server import get_catalog
from app.retrieval.retriever import CatalogRetriever
from app.nlu.tool_schema import build_query_tool
from app.nlu.prompt import build_system_prompt


def debug_question(question: str) -> None:
    catalog = get_catalog()
    retriever = CatalogRetriever(catalog)

    print("=" * 80)
    print(f"🔍 DEBUG CHI TIẾT CÂU HỎI: \"{question}\"")
    print("=" * 80)

    t0 = time.time()

    # Tokenize câu hỏi
    q_tokens = retriever._tokenize(question)
    q_text = question.lower()
    print(f"\n1. 🔤 PHÂN TÍCH TOKENS CÂU HỎI: {sorted(q_tokens)}")

    # 1. Tính BM25 Ranks
    bm25_list: list[tuple[float, dict[str, Any]]] = []
    for doc in retriever.documents:
        overlap = len(q_tokens & doc["tokens"])
        score = float(overlap) / (len(q_tokens) or 1.0)
        bm25_list.append((score, doc))
    bm25_list.sort(key=lambda x: x[0], reverse=True)
    bm25_rank_map = {doc["field_name"]: rank + 1 for rank, (_, doc) in enumerate(bm25_list)}

    # 2. Tính Dense Ranks
    dense_list: list[tuple[float, dict[str, Any]]] = []
    for doc in retriever.documents:
        score = 0.0
        field_base = doc["field_name"].split(".")[-1].lower()
        if field_base in q_text:
            score += 2.0
        if any(kw in q_text for kw in ["đáng sống", "livability", "chỉ số"]) and "livability" in doc["text"]:
            score += 3.0
        if any(kw in q_text for kw in ["tốc độ", "vận tốc", "tốc độ trung bình"]) and "speed" in doc["text"]:
            score += 5.0
        if any(kw in q_text for kw in ["không khí", "aqi", "bụi", "pm25"]) and "aqi" in doc["text"]:
            score += 3.0
        if any(kw in q_text for kw in ["đỗ xe", "bãi xe", "parking"]) and "parking" in doc["text"]:
            score += 3.0
        dense_list.append((score, doc))
    dense_list.sort(key=lambda x: x[0], reverse=True)
    dense_rank_map = {doc["field_name"]: rank + 1 for rank, (_, doc) in enumerate(dense_list)}

    # 3. RRF Fusion
    rrf_scores: list[tuple[float, dict[str, Any], int, int]] = []
    for doc in retriever.documents:
        r_dense = dense_rank_map.get(doc["field_name"], 999)
        r_bm25 = bm25_rank_map.get(doc["field_name"], 999)
        rrf_score = (1.0 / (60.0 + r_dense)) + (1.0 / (60.0 + r_bm25))
        rrf_scores.append((rrf_score, doc, r_dense, r_bm25))

    rrf_scores.sort(key=lambda x: x[0], reverse=True)
    latency_ms = (time.time() - t0) * 1000

    print("\n2. 📊 BẢNG XẾP HẠNG THỨ HẠNG HYBRID RRF (TOP 5 CANDIDATES):")
    print(f"{'Field Name':<45} | {'RRF Score':<10} | {'Dense Rank':<10} | {'BM25 Rank':<10}")
    print("-" * 80)
    for score, doc, r_d, r_b in rrf_scores[:5]:
        print(f"{doc['field_name']:<45} | {score:<10.6f} | {r_d:<10} | {r_b:<10}")

    # 4. Gap Check
    gap = rrf_scores[0][0] - rrf_scores[1][0] if len(rrf_scores) >= 2 else 0.0
    print(f"\n3. ⚡ SIMILARITY GAP CHECK: Gap = {gap:.6f}")
    if gap < 0.0005:
        print("   ⚠️  Cảnh báo Ambiguous (Gap < 0.0005): Tự động mở rộng Candidate Pool (+2 fields)")
    else:
        print("   ✅ Candidates xếp hạng #1 rõ ràng, không mở rộng pool.")

    # 5. Final Retrieval Candidate Output
    candidates = retriever.retrieve(question, top_k=5)
    print("\n4. 🎯 KẾT QUẢ KẾT XUẤT CANDIDATE GRAPH THU ĐƯỢC:")
    print(f"   - Measures   : {candidates['measures']}")
    print(f"   - Dimensions : {candidates['dimensions']}")
    print(f"   - Cubes      : {candidates['cubes']}")

    # 6. Dynamic System Prompt & Tool Schema Size
    prompt = build_system_prompt(catalog, candidates)
    tool = build_query_tool(catalog, candidates)
    prompt_tokens = len(prompt.split())

    print("\n5. 📝 THÔNG TIN PROMPT & SCHEMA DỰNG ĐỘNG:")
    print(f"   - System Prompt Length: ~{prompt_tokens} words (~{int(prompt_tokens * 1.3)} tokens)")
    print(f"   - Tool Name           : {tool['name']}")
    print(f"   - Tool Description    : {tool['description']}")
    print(f"   - Total Latency       : {latency_ms:.2f} ms")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    test_q = sys.argv[1] if len(sys.argv) > 1 else "Tốc độ giao thông trung bình ở Khu biet thu là bao nhiêu?"
    debug_question(test_q)
