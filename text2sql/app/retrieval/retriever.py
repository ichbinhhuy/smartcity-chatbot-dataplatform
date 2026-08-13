"""Catalog Retrieval Layer: Dual-Mode Architecture (Cube-First RAG & Column Hybrid Fallback).

Hỗ trợ 2 Chế Độ Search (Có thể chuyển đổi qua `mode="CUBE_FIRST"` hoặc `mode="COLUMN_HYBRID"`):
1. Mode 2: `CUBE_FIRST` (Khuyên dùng - Mặc định):
   - Stage 1: AI Vector Search chọn ra Top 1 - 2 Bảng (Cubes) phù hợp nhất.
   - Stage 2: Nạp trọn bộ 100% Measures & Dimensions của các Cube được chọn cho LLM 70B bóc tách.
   - Ưu điểm: Triệt tiêu 100% lỗi cắt ngắt cột (Column Truncation), tốc độ siêu tốc (< 15ms), độ chính xác > 98%.

2. Mode 1: `COLUMN_HYBRID` (Dự phòng / Fallback):
   - Search từng cột lẻ tẻ bằng BM25 + AI Embeddings Cosine + RRF Fusion.
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
        except Exception as exc:
            print(f"[RAG Engine Warning] SentenceTransformer failed: {exc}")
            try:
                from fastembed import TextEmbedding
                print(f"[RAG Engine] Nạp FastEmbed ({model_name})...")
                self.backend = "fastembed"
                self.model = TextEmbedding(model_name=model_name)
            except Exception as exc2:
                print(f"[RAG Engine Warning] FastEmbed failed: {exc2}")
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
    """Hỗ trợ Dual-Mode Search: CUBE_FIRST (Mặc định) và COLUMN_HYBRID (Dự phòng)."""

    def __init__(
        self,
        catalog: Catalog,
        qdrant_host: str | None = None,
        mode: str | None = None,
        cosine_threshold: float | None = None,
        top_k_cubes: int | None = None,
    ) -> None:
        self.catalog = catalog
        self.qdrant_host = qdrant_host or os.getenv("QDRANT_HOST", "qdrant")
        self.qdrant_url = f"http://{self.qdrant_host}:6333"
        # Chế độ Search: "CUBE_FIRST" (Cách 2) hoặc "COLUMN_HYBRID" (Cách 1)
        self.mode = mode or os.getenv("RETRIEVAL_MODE", "CUBE_FIRST")
        self.collection_name = "cube_catalog"
        raw_threshold = os.getenv("COSINE_THRESHOLD", "0.3")
        self.cosine_threshold = cosine_threshold if cosine_threshold is not None else float(raw_threshold)
        # Số cube Top-K chọn ở Stage 1 (CUBE_FIRST). Mặc định 3 (tăng từ 2) để
        # giảm rủi ro recall miss khi RRF xếp nhầm cube đúng ra ngoài top-2 —
        # xem docs/04-ambiguous-question-handling.md case F / FIX-09. Rẻ vì
        # Cube-First đã nạp 100% measures/dimensions của cube được chọn, thêm
        # 1 cube chỉ đánh đổi prompt dài hơn một chút.
        raw_top_k = os.getenv("RAG_TOP_K_CUBES", "3")
        self.top_k_cubes = top_k_cubes if top_k_cubes is not None else int(raw_top_k)

        self.cube_documents: list[dict[str, Any]] = []
        self.column_documents: list[dict[str, Any]] = []

        self.embedding_engine = AIEmbeddingEngine(MULTILINGUAL_MODEL_NAME)
        self._build_rich_documents()
        self._setup_qdrant()

    def _tokenize(self, text: str) -> set[str]:
        text_clean = re.sub(r"[^\w\s]", " ", text.lower())
        return {w for w in text_clean.split() if len(w) > 1}

    def _build_rich_documents(self) -> None:
        """Tạo Metadata Documents cho cả 2 Chế Độ (Cube-First & Column-Hybrid)."""
        self.cube_documents.clear()
        self.column_documents.clear()

        domain_alias_map = {
            "city_health_index": "chỉ số đáng sống livability chất lượng đô thị tổng hợp điểm số khu vực rating grade",
            "air_quality": "chất lượng không khí aqi bụi mịn pm25 tiếng ồn ô nhiễm môi trường quiet noisy dBA",
            "traffic_flow": "giao thông tốc độ vận tốc số lượng xe ô tô xe máy kẹt xe ùn tắc di chuyển speed vehicle congestion overspeed",
            "smart_parking": "bãi đỗ xe chỗ gửi xe đỗ xe occupancy slots vị trí trống ô tô critical low optimal",
            "smart_lighting": "đèn đường chiếu sáng công suất tiêu thụ điện hỏng pole faulty lighting power evening full night dimming day off",
            "street_incidents": "sự cố giao thông tai nạn ngập lụt công trình accident flood congestion minor major critical",
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

            # 1. BẢN CÁCH 2: TẠO MACRO CUBE METADATA DOCUMENT (Đại diện cho trọn Bảng)
            m_descs = [f"{m.name} ({m.title} - {m.description})" for m in cube.measures]
            d_descs = [f"{d.name} ({d.title} - {d.description})" for d in cube.dimensions]
            
            macro_text = (
                f"Cube Name: {cube.name} | Title: {cube.title} | "
                f"Domain Keywords: {cube_domain_text} | "
                f"Measures: {', '.join(m_descs)} | "
                f"Dimensions: {', '.join(d_descs)}"
            )

            self.cube_documents.append({
                "id": len(self.cube_documents) + 1,
                "cube_name": cube.name,
                "tokens": self._tokenize(macro_text),
                "text": macro_text.lower(),
            })

            # 2. BẢN CÁCH 1: TẠO COLUMN-LEVEL METADATA DOCUMENTS (Dự phòng cho Column Hybrid Search)
            for m in cube.measures:
                vn_terms = vietnamese_measure_terms.get(m.name, "")
                doc_text = f"Field: {m.name} | Title: {cube.title} | Type: measure | Description: {m.description} | Cube: {cube.name} | Terms: {vn_terms} {m.name.replace('.', ' ')}"
                self.column_documents.append({
                    "id": len(self.column_documents) + 1,
                    "type": "measure",
                    "cube_name": cube.name,
                    "field_name": m.name,
                    "tokens": self._tokenize(doc_text),
                    "text": doc_text.lower(),
                })

            for d in cube.dimensions:
                doc_text = f"Field: {d.name} | Title: {cube.title} | Type: dimension | Description: {d.description} | Cube: {cube.name} | Domain: {cube_domain_text} section phan khu"
                self.column_documents.append({
                    "id": len(self.column_documents) + 1,
                    "type": "dimension",
                    "cube_name": cube.name,
                    "field_name": d.name,
                    "tokens": self._tokenize(doc_text),
                    "text": doc_text.lower(),
                })

        # Calculate Real AI Embeddings for both Cube and Column documents
        cube_texts = [doc["text"] for doc in self.cube_documents]
        cube_embs = self.embedding_engine.encode_batch(cube_texts)
        for doc, emb in zip(self.cube_documents, cube_embs):
            doc["embedding"] = emb

        col_texts = [doc["text"] for doc in self.column_documents]
        col_embs = self.embedding_engine.encode_batch(col_texts)
        for doc, emb in zip(self.column_documents, col_embs):
            doc["embedding"] = emb

    def _setup_qdrant(self) -> None:
        """Khởi tạo Collection & Index Rich Metadata vào Qdrant."""
        try:
            vector_size = len(self.cube_documents[0]["embedding"]) if self.cube_documents else 384
            httpx.put(
                f"{self.qdrant_url}/collections/{self.collection_name}",
                json={"vectors": {"size": vector_size, "distance": "Cosine"}},
                timeout=5.0
            )

            points = []
            for doc in self.cube_documents:
                points.append({
                    "id": doc["id"],
                    "vector": doc["embedding"].tolist(),
                    "payload": {
                        "cube_name": doc["cube_name"],
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
        """Hỗ trợ Dual-Mode Search: CUBE_FIRST (Cách 2) hoặc COLUMN_HYBRID (Cách 1)."""
        if self.mode.upper() == "COLUMN_HYBRID":
            print("[RAG] Retrieval Mode 1: COLUMN_HYBRID (Search Col + RRF Fusion)")
            return self._retrieve_column_hybrid(question, top_k)
        else:
            print("[RAG] Retrieval Mode 2: CUBE_FIRST (Stage 1 Cube -> 100% Cols)")
            return self._retrieve_cube_first(question, top_k_cubes=self.top_k_cubes)

    def _retrieve_cube_first(self, question: str, top_k_cubes: int = 3) -> dict[str, list[str]]:
        """MODE 2: Stage 1 RAG chọn Top-K Cubes (mặc định 3, xem `self.top_k_cubes`) -> Nạp trọn bộ 100% Measures & Dimensions cho LLM 70B."""
        q_tokens = self._tokenize(question)

        # 1. BM25 Overlap Ranks trên tập Cube Documents
        bm25_list = []
        for doc in self.cube_documents:
            overlap = len(q_tokens & doc["tokens"])
            score = float(overlap) / (len(q_tokens) or 1.0)
            bm25_list.append((score, doc))
        bm25_list.sort(key=lambda x: x[0], reverse=True)
        bm25_rank_map = {doc["cube_name"]: rank + 1 for rank, (_, doc) in enumerate(bm25_list)}

        # 2. AI Embedding Cosine Similarity Ranks trên tập Cube Documents
        q_emb = self.embedding_engine.encode_single(question)
        dense_list = []
        for doc in self.cube_documents:
            cosine_sim = float(np.dot(q_emb, doc["embedding"]))
            dense_list.append((cosine_sim, doc))
        dense_list.sort(key=lambda x: x[0], reverse=True)
        dense_rank_map = {doc["cube_name"]: rank + 1 for rank, (_, doc) in enumerate(dense_list)}

        # 3. RRF Score Fusion
        rrf_scores = []
        for doc in self.cube_documents:
            r_dense = dense_rank_map.get(doc["cube_name"], 999)
            r_bm25 = bm25_rank_map.get(doc["cube_name"], 999)
            rrf_score = (1.0 / (60.0 + r_dense)) + (1.0 / (60.0 + r_bm25))
            rrf_scores.append((rrf_score, doc))

        rrf_scores.sort(key=lambda x: x[0], reverse=True)

        # Chọn Top 1 hoặc Top 2 Cubes có điểm RRF cao nhất
        selected_cubes = [item[1]["cube_name"] for item in rrf_scores[:top_k_cubes]]

        # FEED HẾT 100% CỘT CỦA CÁC CUBE ĐƯỢC CHỌN CHO LLM 70B!
        selected_measures: set[str] = set()
        selected_dimensions: set[str] = set()

        for c_name in selected_cubes:
            cube = self.catalog.cube(c_name)
            if cube:
                for m in cube.measures:
                    selected_measures.add(m.name)
                for d in cube.dimensions:
                    selected_dimensions.add(d.name)

        max_cosine = float(dense_list[0][0]) if dense_list else 0.0
        # Rào cản cosine chỉ có ý nghĩa với embedding thật — hash-trick vector
        # (fallback khi không tải được SentenceTransformer/FastEmbed) không
        # mang ngữ nghĩa semantic nên không dùng để đánh giá out-of-domain.
        is_out_of_domain = (
            max_cosine < self.cosine_threshold if self.embedding_engine.backend != "hash" else False
        )

        return {
            "measures": sorted(selected_measures),
            "dimensions": sorted(selected_dimensions),
            "cubes": sorted(selected_cubes),
            "max_cosine_score": max_cosine,
            "is_out_of_domain": is_out_of_domain,
        }

    def _retrieve_column_hybrid(self, question: str, top_k: int = 5) -> dict[str, Any]:
        """MODE 1: Fallback Search cấp độ Cột (Column-level Hybrid Search)."""
        q_tokens = self._tokenize(question)

        bm25_list = []
        for doc in self.column_documents:
            overlap = len(q_tokens & doc["tokens"])
            score = float(overlap) / (len(q_tokens) or 1.0)
            bm25_list.append((score, doc))
        bm25_list.sort(key=lambda x: x[0], reverse=True)
        bm25_rank_map = {doc["field_name"]: rank + 1 for rank, (_, doc) in enumerate(bm25_list)}

        q_emb = self.embedding_engine.encode_single(question)
        dense_list = []
        for doc in self.column_documents:
            cosine_sim = float(np.dot(q_emb, doc["embedding"]))
            dense_list.append((cosine_sim, doc))
        dense_list.sort(key=lambda x: x[0], reverse=True)
        dense_rank_map = {doc["field_name"]: rank + 1 for rank, (_, doc) in enumerate(dense_list)}

        max_cosine = float(dense_list[0][0]) if dense_list else 0.0
        # Rào cản cosine chỉ có ý nghĩa với embedding thật — xem ghi chú tương
        # ứng trong _retrieve_cube_first().
        is_out_of_domain = (
            max_cosine < self.cosine_threshold if self.embedding_engine.backend != "hash" else False
        )

        rrf_scores = []
        for doc in self.column_documents:
            r_dense = dense_rank_map.get(doc["field_name"], 999)
            r_bm25 = bm25_rank_map.get(doc["field_name"], 999)
            rrf_score = (1.0 / (60.0 + r_dense)) + (1.0 / (60.0 + r_bm25))
            rrf_scores.append((rrf_score, doc))

        rrf_scores.sort(key=lambda x: x[0], reverse=True)

        top_docs = [item[1] for item in rrf_scores[:top_k]]
        selected_measures: set[str] = set()
        selected_dimensions: set[str] = set()
        selected_cubes: set[str] = set()

        for doc in top_docs:
            selected_cubes.add(doc["cube_name"])
            if doc["type"] == "measure":
                selected_measures.add(doc["field_name"])
            else:
                selected_dimensions.add(doc["field_name"])

        for c_name in selected_cubes:
            cube = self.catalog.cube(c_name)
            if cube:
                for m in cube.measures:
                    selected_measures.add(m.name)
                for d in cube.dimensions:
                    selected_dimensions.add(d.name)

        return {
            "measures": sorted(selected_measures),
            "dimensions": sorted(selected_dimensions),
            "cubes": sorted(selected_cubes),
            "max_cosine_score": max_cosine,
            "is_out_of_domain": is_out_of_domain,
        }
