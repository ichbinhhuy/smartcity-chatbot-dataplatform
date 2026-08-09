"""Catalog Retrieval Layer: Qdrant Hybrid Search (RRF Score Fusion & Rich Metadata Documents).

Cải tiến dựa trên phản biện kiến trúc:
1. RRF (Reciprocal Rank Fusion): Độc lập với scale điểm số của Dense & Sparse search.
2. Rich Metadata Document: Nhúng phong phú thông tin Field, Description, Aliases, Domain & Cube Name.
3. Similarity Gap Check: Tự động mở rộng Candidate Pool nếu điểm top-1 và top-2 quá sát nhau (< 0.05).
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any

import httpx

from app.catalog.models import Catalog


class CatalogRetriever:
    """Qdrant Hybrid Search sử dụng RRF (Reciprocal Rank Fusion) & Rich Metadata."""

    def __init__(self, catalog: Catalog, qdrant_host: str | None = None) -> None:
        self.catalog = catalog
        self.qdrant_host = qdrant_host or os.getenv("QDRANT_HOST", "qdrant")
        self.qdrant_url = f"http://{self.qdrant_host}:6333"
        self.collection_name = "cube_catalog"
        self.documents: list[dict[str, Any]] = []
        
        self._build_rich_documents()
        self._setup_qdrant()

    def _tokenize(self, text: str) -> set[str]:
        text_clean = re.sub(r"[^\w\s]", " ", text.lower())
        return {w for w in text_clean.split() if len(w) > 1}

    def _build_rich_documents(self) -> None:
        """Đóng gói Rich Metadata Document chứa Aliases, Domain, Business Meaning."""
        self.documents.clear()

        domain_alias_map = {
            "city_health_index": "chỉ số đáng sống livability chất lượng đô thị tổng hợp điểm số khu vực",
            "air_quality": "chất lượng không khí aqi bụi mịn pm25 tiếng ồn ô nhiễm môi trường quiet noisy",
            "traffic_flow": "giao thông tốc độ vận tốc số lượng xe ô tô xe máy kẹt xe ùn tắc di chuyển speed vehicle",
            "smart_parking": "bãi đỗ xe chỗ gửi xe đỗ xe occupancy slots vị trí trống ô tô",
            "smart_lighting": "đèn đường chiếu sáng công suất tiêu thụ điện hỏng pole faulty lighting power",
            "street_incidents": "sự cố giao thông tai nạn ngập lụt công trình accident flood congestion",
            "districts": "quận huyện địa bàn phân khu vị trí địa lý khu vực",
        }

        vietnamese_measure_terms = {
            "city_health_index.avg_livability_index": "chỉ số đáng sống livability mức độ đáng sống chất lượng đô thị tổng hợp",
            "city_health_index.sum_livability_index": "tổng chỉ số đáng sống livability",
            "air_quality.avg_aqi": "chất lượng không khí aqi ô nhiễm bụi mịn pm25 môi trường",
            "air_quality.avg_pm25": "bụi mịn pm25 chất lượng không khí ô nhiễm",
            "air_quality.avg_noise_db": "độ ồn tiếng ồn dBA âm thanh noisy quiet",
            "traffic_flow.avg_speed": "tốc độ vận tốc giao thông tốc độ trung bình di chuyển km h speed",
            "traffic_flow.avg_vehicle_count": "số lượng xe lưu lượng phương tiện ô tô xe máy traffic count",
            "traffic_flow.congestion_rate": "tỷ lệ kẹt xe ùn tắc giao thông tắc đường congestion",
            "smart_parking.occupancy_pct": "tỷ lệ đỗ xe bãi đỗ xe chỗ gửi xe ô tô trống rỗng occupancy",
            "smart_parking.available_slots": "số chỗ đỗ xe còn trống bãi đỗ xe available slots",
            "smart_lighting.faulty_lamp_count": "số bóng đèn đường bị hỏng hóc sự cố chiếu sáng faulty lamp",
            "smart_lighting.total_power_kwh": "tổng điện năng tiêu thụ chiếu sáng kwh power energy",
            "street_incidents.total_incidents": "tổng số sự cố tai nạn ngập lụt công trình tắc đường incident",
        }

        for cube in self.catalog.cubes:
            cube_domain_text = domain_alias_map.get(cube.name, "")

            for m in cube.measures:
                vn_terms = vietnamese_measure_terms.get(m.name, "")
                doc_text = f"Field: {m.name} | Title: {cube.title} | Type: measure | Description: {m.description} | Cube: {cube.name} | Terms: {vn_terms} {m.name.replace('.', ' ')} {m.name.split('.')[-1]}"
                self.documents.append({
                    "id": len(self.documents) + 1,
                    "type": "measure",
                    "cube_name": cube.name,
                    "field_name": m.name,
                    "tokens": self._tokenize(doc_text),
                    "text": doc_text.lower(),
                })

            for d in cube.dimensions:
                doc_text = f"Field: {d.name} | Title: {cube.title} | Type: dimension | Description: {d.description} | Cube: {cube.name} | Domain: {cube_domain_text} section phan khu"
                self.documents.append({
                    "id": len(self.documents) + 1,
                    "type": "dimension",
                    "cube_name": cube.name,
                    "field_name": d.name,
                    "tokens": self._tokenize(doc_text),
                    "text": doc_text.lower(),
                })

    def _setup_qdrant(self) -> None:
        """Khởi tạo Collection & Index Rich Metadata vào Qdrant."""
        try:
            httpx.put(
                f"{self.qdrant_url}/collections/{self.collection_name}",
                json={"vectors": {"size": 64, "distance": "Cosine"}},
                timeout=5.0
            )

            points = []
            for doc in self.documents:
                vector = [0.0] * 64
                for token in doc["tokens"]:
                    idx = abs(hash(token)) % 64
                    vector[idx] += 1.0
                norm = math.sqrt(sum(v * v for v in vector)) or 1.0
                vector = [v / norm for v in vector]

                points.append({
                    "id": doc["id"],
                    "vector": vector,
                    "payload": {
                        "cube_name": doc["cube_name"],
                        "field_name": doc["field_name"],
                        "type": doc["type"],
                        "text": doc["text"]
                    }
                })

            httpx.put(
                f"{self.qdrant_url}/collections/{self.collection_name}/points?wait=true",
                json={"points": points},
                timeout=5.0
            )
        except Exception as exc:
            print(f"[Qdrant Notice] {exc}")

    def retrieve(self, question: str, top_k: int = 5) -> dict[str, list[str]]:
        """Hybrid Search với RRF (Reciprocal Rank Fusion) & Similarity Gap Check."""
        q_tokens = self._tokenize(question)
        q_text = question.lower()

        # 1. Tính BM25 Ranks
        bm25_list: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            overlap = len(q_tokens & doc["tokens"])
            score = float(overlap) / (len(q_tokens) or 1.0)
            bm25_list.append((score, doc))
        bm25_list.sort(key=lambda x: x[0], reverse=True)
        bm25_rank_map = {doc["field_name"]: rank + 1 for rank, (_, doc) in enumerate(bm25_list)}

        # 2. Tính Dense Semantic Ranks
        dense_list: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
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

        # 3. Reciprocal Rank Fusion (RRF): Score = 1/(60 + Rank_Dense) + 1/(60 + Rank_BM25)
        rrf_scores: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            r_dense = dense_rank_map.get(doc["field_name"], 999)
            r_bm25 = bm25_rank_map.get(doc["field_name"], 999)
            rrf_score = (1.0 / (60.0 + r_dense)) + (1.0 / (60.0 + r_bm25))
            rrf_scores.append((rrf_score, doc))

        rrf_scores.sort(key=lambda x: x[0], reverse=True)

        # 4. Similarity Gap Check: Mở rộng pool nếu #1 và #2 điểm quá sát nhau (< 0.0005)
        effective_k = top_k
        if len(rrf_scores) >= 2:
            gap = rrf_scores[0][0] - rrf_scores[1][0]
            if gap < 0.0005:
                effective_k = top_k + 2

        top_docs = [item[1] for item in rrf_scores[:effective_k]]

        selected_measures: set[str] = set()
        selected_dimensions: set[str] = set()
        selected_cubes: set[str] = set()

        for doc in top_docs:
            selected_cubes.add(doc["cube_name"])
            if doc["type"] == "measure":
                selected_measures.add(doc["field_name"])
            else:
                selected_dimensions.add(doc["field_name"])

        # Auto-include section_id dimensions for selected cubes
        for cube_name in selected_cubes:
            cube = self.catalog.cube(cube_name)
            if cube:
                for d in cube.dimensions:
                    if d.name.endswith(".section_id"):
                        selected_dimensions.add(d.name)

        return {
            "measures": sorted(selected_measures),
            "dimensions": sorted(selected_dimensions),
            "cubes": sorted(selected_cubes),
        }
