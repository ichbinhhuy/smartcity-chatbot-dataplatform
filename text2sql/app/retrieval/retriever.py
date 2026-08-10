"""Catalog Retrieval Layer: Semantic Multilingual Embedding Search & RRF Score Fusion.

Cải tiến với AI Real Embeddings:
1. SentenceTransformer Multilingual Embedding Model (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`).
2. Reciprocal Rank Fusion (RRF): Kết hợp Dense Semantic Cosine Similarity và BM25 Lexical Overlap.
3. Co-occurrence Cube Expansion: Nạp toàn bộ Measures & Dimensions cho Cube được chọn.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any

import httpx
import numpy as np

from app.catalog.models import Catalog

MULTILINGUAL_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class AIEmbeddingEngine:
    """Mô hình AI Embedding đa ngôn ngữ hỗ trợ SentenceTransformer, FastEmbed và Hash Fallback."""

    def __init__(self, model_name: str = MULTILINGUAL_MODEL_NAME) -> None:
        self.backend = "sentence_transformers"
        try:
            from sentence_transformers import SentenceTransformer
            print(f"[RAG Engine] Nạp SentenceTransformer ({model_name})...")
            self.model = SentenceTransformer(model_name)
        except Exception:
            try:
                from fastembed import TextEmbedding
                print(f"[RAG Engine] Nạp FastEmbed ({model_name})...")
                self.backend = "fastembed"
                self.model = TextEmbedding(model_name=model_name)
            except Exception:
                print("[RAG Engine Notice] Dùng Hash Vector Fallback...")
                self.backend = "hash"
                self.model = None

    def _hash_vector(self, text: str) -> np.ndarray:
        tokens = re.sub(r"[^\w\s]", " ", text.lower()).split()
        v = np.zeros(64, dtype=np.float32)
        for token in tokens:
            idx = abs(hash(token)) % 64
            v[idx] += 1.0
        norm = np.linalg.norm(v) or 1.0
        return v / norm

    def encode_single(self, text: str) -> np.ndarray:
        if self.backend == "sentence_transformers":
            vec = self.model.encode(text, normalize_embeddings=True)
            return np.array(vec, dtype=np.float32)
        elif self.backend == "fastembed":
            vecs = list(self.model.embed([text]))
            v = np.array(vecs[0], dtype=np.float32)
            norm = np.linalg.norm(v) or 1.0
            return v / norm
        else:
            return self._hash_vector(text)

    def encode_batch(self, texts: list[str]) -> list[np.ndarray]:
        if not texts:
            return []
        if self.backend == "sentence_transformers":
            vecs = self.model.encode(texts, normalize_embeddings=True)
            return [np.array(v, dtype=np.float32) for v in vecs]
        elif self.backend == "fastembed":
            vecs = list(self.model.embed(texts))
            res = []
            for v in vecs:
                v_arr = np.array(v, dtype=np.float32)
                norm = np.linalg.norm(v_arr) or 1.0
                res.append(v_arr / norm)
            return res
        else:
            return [self._hash_vector(t) for t in texts]


class CatalogRetriever:
    """Hybrid Search với Multilingual AI Embeddings, BM25 và RRF Score Fusion."""

    def __init__(self, catalog: Catalog, qdrant_host: str | None = None) -> None:
        self.catalog = catalog
        self.qdrant_host = qdrant_host or os.getenv("QDRANT_HOST", "qdrant")
        self.qdrant_url = f"http://{self.qdrant_host}:6333"
        self.collection_name = "cube_catalog"
        self.documents: list[dict[str, Any]] = []

        self.embedding_engine = AIEmbeddingEngine(MULTILINGUAL_MODEL_NAME)
        self._build_rich_documents()
        self._setup_qdrant()

    def _tokenize(self, text: str) -> set[str]:
        text_clean = re.sub(r"[^\w\s]", " ", text.lower())
        return {w for w in text_clean.split() if len(w) > 1}

    def _build_rich_documents(self) -> None:
        """Đóng gói Rich Metadata Document và tính toán AI Embedding Vector."""
        self.documents.clear()

        domain_alias_map = {
            "city_health_index": "chỉ số đáng sống livability chất lượng đô thị tổng hợp điểm số khu vực",
            "air_quality": "chất lượng không khí aqi bụi mịn pm25 tiếng ồn ô nhiễm môi trường quiet noisy",
            "traffic_flow": "giao thông tốc độ vận tốc số lượng xe ô tô xe máy kẹt xe ùn tắc di chuyển speed vehicle",
            "smart_parking": "bãi đỗ xe chỗ gửi xe đỗ xe occupancy slots vị trí trống ô tô",
            "smart_lighting.operating_mode": "buổi tối ban đêm ban ngày tiết kiệm điện day off night dimming",
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
            "traffic_flow.avg_vehicle_count": "trung bình số lượng xe lưu lượng phương tiện ô tô xe máy traffic count",
            "traffic_flow.sum_vehicle_count": "tổng số lượng xe đông nhất lưu thông phương tiện xe cộ total vehicle count",
            "traffic_flow.max_vehicle_count": "số lượng xe nhiều nhất đông nhất đỉnh điểm max vehicle count",
            "traffic_flow.congestion_rate": "tỷ lệ kẹt xe ùn tắc giao thông tắc đường congestion",
            "smart_parking.occupancy_pct": "tỷ lệ đỗ xe bãi đỗ xe chỗ gửi xe ô tô trống rỗng occupancy",
            "smart_parking.available_slots": "số chỗ đỗ xe còn trống bãi đỗ xe available slots",
            "smart_lighting.faulty_lamp_count": "số bóng đèn đường bị hỏng hóc sự cố chiếu sáng faulty lamp",
            "smart_lighting.total_power_kwh": "tổng điện năng tiêu thụ chiếu sáng kwh power energy",
            "smart_lighting.sum_power_per_pole": "tổng điện năng tiêu thụ cột đèn kwh power",
            "smart_lighting.avg_power_per_pole": "trung bình điện năng tiêu thụ cột đèn kwh power",
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

        # Calculate Real Embeddings for all catalog metadata documents once at startup
        texts = [doc["text"] for doc in self.documents]
        embeddings = self.embedding_engine.encode_batch(texts)
        for doc, emb in zip(self.documents, embeddings):
            doc["embedding"] = emb

    def _setup_qdrant(self) -> None:
        """Khởi tạo Collection & Index Rich Metadata vào Qdrant."""
        try:
            vector_size = len(self.documents[0]["embedding"]) if self.documents else 384
            httpx.put(
                f"{self.qdrant_url}/collections/{self.collection_name}",
                json={"vectors": {"size": vector_size, "distance": "Cosine"}},
                timeout=5.0
            )

            points = []
            for doc in self.documents:
                points.append({
                    "id": doc["id"],
                    "vector": doc["embedding"].tolist(),
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
        """Hybrid Search với AI Embeddings Cosine Similarity & RRF (Reciprocal Rank Fusion)."""
        q_tokens = self._tokenize(question)

        # 1. Tính BM25 Lexical Overlap Ranks
        bm25_list: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            overlap = len(q_tokens & doc["tokens"])
            score = float(overlap) / (len(q_tokens) or 1.0)
            bm25_list.append((score, doc))
        bm25_list.sort(key=lambda x: x[0], reverse=True)
        bm25_rank_map = {doc["field_name"]: rank + 1 for rank, (_, doc) in enumerate(bm25_list)}

        # 2. Tính Dense AI Embedding Cosine Similarity Ranks
        q_emb = self.embedding_engine.encode_single(question)
        dense_list: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            cosine_sim = float(np.dot(q_emb, doc["embedding"]))
            dense_list.append((cosine_sim, doc))
        dense_list.sort(key=lambda x: x[0], reverse=True)
        dense_rank_map = {doc["field_name"]: rank + 1 for rank, (_, doc) in enumerate(dense_list)}

        # 3. Reciprocal Rank Fusion (RRF)
        rrf_scores: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            r_dense = dense_rank_map.get(doc["field_name"], 999)
            r_bm25 = bm25_rank_map.get(doc["field_name"], 999)
            rrf_score = (1.0 / (60.0 + r_dense)) + (1.0 / (60.0 + r_bm25))
            rrf_scores.append((rrf_score, doc))

        rrf_scores.sort(key=lambda x: x[0], reverse=True)

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

        # Co-occurrence Cube Expansion: Auto-include ALL measures & dimensions of the selected cubes
        for cube_name in selected_cubes:
            cube = self.catalog.cube(cube_name)
            if cube:
                for m in cube.measures:
                    selected_measures.add(m.name)
                for d in cube.dimensions:
                    selected_dimensions.add(d.name)

        return {
            "measures": sorted(selected_measures),
            "dimensions": sorted(selected_dimensions),
            "cubes": sorted(selected_cubes),
        }
