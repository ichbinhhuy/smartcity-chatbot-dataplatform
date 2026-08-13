"""Unit test cho app/retrieval/retriever.py — OOD guardrail (case E) và
top_k_cubes configurable (case F / FIX-09). Xem
docs/04-ambiguous-question-handling.md.

`embedding_engine.backend` được monkeypatch tường minh trong từng test thay
vì dựa vào việc môi trường chạy test có cài sentence-transformers/fastembed
hay không — 2 giá trị "hash" và không-"hash" đều phải test được bất kể
backend nào thực sự load được lúc CatalogRetriever() khởi tạo.
"""

from __future__ import annotations

import numpy as np

from app.retrieval.retriever import CatalogRetriever


class TestOutOfDomainGuardrail:
    def test_disabled_for_hash_backend(self, catalog, monkeypatch):
        """Hash-trick vector không mang ngữ nghĩa semantic -> guardrail phải
        luôn tắt cho backend này, kể cả khi threshold rất cao."""
        retriever = CatalogRetriever(catalog, cosine_threshold=0.99)
        monkeypatch.setattr(retriever.embedding_engine, "backend", "hash")

        result = retriever.retrieve("một câu hỏi bất kỳ")

        assert result["is_out_of_domain"] is False

    def _patch_non_hash_zero_cosine(self, retriever, monkeypatch):
        """Ép backend != "hash" (bật nhánh guardrail) và trả về vector 0 cho
        MỌI câu hỏi -> cosine similarity với bất kỳ cube doc nào cũng = 0.0,
        không phụ thuộc model thật load được hay không (host/CI có thể không
        có sẵn sentence-transformers/fastembed — self.model vẫn None nếu chỉ
        đổi `backend` mà không đổi luôn `encode_single`)."""
        monkeypatch.setattr(retriever.embedding_engine, "backend", "sentence_transformers")
        dim = len(retriever.cube_documents[0]["embedding"])
        zero_vec = np.zeros(dim, dtype=np.float32)
        monkeypatch.setattr(retriever.embedding_engine, "encode_single", lambda text: zero_vec)

    def test_triggers_for_non_hash_backend_below_threshold(self, catalog, monkeypatch):
        retriever = CatalogRetriever(catalog, cosine_threshold=0.99)
        self._patch_non_hash_zero_cosine(retriever, monkeypatch)

        result = retriever.retrieve("một câu hỏi ngẫu nhiên không liên quan tới đô thị")

        # cosine = 0.0 (vector rỗng) < threshold 0.99.
        assert result["is_out_of_domain"] is True

    def test_not_triggered_when_threshold_is_zero(self, catalog, monkeypatch):
        retriever = CatalogRetriever(catalog, cosine_threshold=0.0)
        self._patch_non_hash_zero_cosine(retriever, monkeypatch)

        result = retriever.retrieve("chất lượng không khí AQI hôm nay")

        # cosine = 0.0, KHÔNG < threshold 0.0.
        assert result["is_out_of_domain"] is False


class TestTopKCubesConfigurable:
    def test_default_is_three(self, catalog):
        retriever = CatalogRetriever(catalog)
        assert retriever.top_k_cubes == 3

    def test_constructor_override(self, catalog):
        retriever = CatalogRetriever(catalog, top_k_cubes=1)
        result = retriever.retrieve("tốc độ trung bình xe cộ")
        assert len(result["cubes"]) <= 1

    def test_env_var_override(self, catalog, monkeypatch):
        monkeypatch.setenv("RAG_TOP_K_CUBES", "5")
        retriever = CatalogRetriever(catalog)
        assert retriever.top_k_cubes == 5
