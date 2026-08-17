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
import pytest

from app.retrieval.retriever import CatalogRetriever


class TestOutOfDomainGuardrail:
    def test_disabled_for_hash_backend(self, catalog, monkeypatch):
        """Hash-trick vector không mang ngữ nghĩa semantic -> guardrail phải
        luôn tắt cho backend này, kể cả khi threshold rất cao."""
        retriever = CatalogRetriever(catalog, cosine_threshold=0.99)
        monkeypatch.setattr(retriever.embedding_engine, "backend", "hash")

        result = retriever.retrieve("một câu hỏi bất kỳ")

        assert result["is_out_of_domain"] is False

    def test_disabled_even_for_non_hash_backend(self, catalog, monkeypatch):
        """TẠM THỜI TẮT LẠI (2026-08-13, xem retriever.py) — test tay trên UI
        thật (embedding thật) phát hiện false positive: câu hỏi rất cụ thể,
        đúng domain traffic_flow vẫn bị chặn nhầm vì cosine_threshold=0.3
        chưa được calibrate bằng eval set thật. `is_out_of_domain` giờ luôn
        `False` bất kể backend/threshold, cho tới khi được bật lại."""
        retriever = CatalogRetriever(catalog, cosine_threshold=0.99)
        self._patch_non_hash_zero_cosine(retriever, monkeypatch)

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

    @pytest.mark.skip(
        reason="OOD guardrail tạm tắt (retriever.py, 2026-08-13) do false "
        "positive phát hiện qua UI thật — bật lại cùng lúc với logic threshold "
        "trong retriever.py sau khi calibrate ngưỡng bằng dữ liệu thật."
    )
    def test_triggers_for_non_hash_backend_below_threshold(self, catalog, monkeypatch):
        retriever = CatalogRetriever(catalog, cosine_threshold=0.99)
        self._patch_non_hash_zero_cosine(retriever, monkeypatch)

        result = retriever.retrieve("một câu hỏi ngẫu nhiên không liên quan tới đô thị")

        # cosine = 0.0 (vector rỗng) < threshold 0.99.
        assert result["is_out_of_domain"] is True

    @pytest.mark.skip(
        reason="OOD guardrail tạm tắt (retriever.py, 2026-08-13) — xem lý do ở "
        "test_triggers_for_non_hash_backend_below_threshold."
    )
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
        # top_k_cubes chỉ giới hạn phần chọn theo RRF — cube reference/
        # dimension-only (vd `districts`, không có measure) luôn được bổ
        # sung thêm bất kể top_k_cubes, xem TestAlwaysIncludeReferenceCubes.
        rrf_selected = [c for c in result["cubes"] if c != "districts"]
        assert len(rrf_selected) <= 1

    def test_env_var_override(self, catalog, monkeypatch):
        monkeypatch.setenv("RAG_TOP_K_CUBES", "5")
        retriever = CatalogRetriever(catalog)
        assert retriever.top_k_cubes == 5


class TestAlwaysIncludeReferenceCubes:
    """Cube không có measure nào (reference/dimension-only, vd `districts`)
    phải luôn có mặt trong candidates bất kể RAG xếp hạng thế nào — macro-
    document của các cube này vốn "mỏng" (không có measures để mô tả) nên
    thiệt thòi có hệ thống trong RRF scoring. Xem
    docs/04-ambiguous-question-handling.md (bug "list các khu trong
    smartcity" dùng nhầm `air_quality.section_id` thay vì `districts`)."""

    def test_districts_always_present_for_unrelated_question(self, catalog):
        retriever = CatalogRetriever(catalog, top_k_cubes=2)
        result = retriever.retrieve("Chất lượng không khí AQI hôm nay thế nào?")
        assert "districts" in result["cubes"]
        assert "districts.name" in result["dimensions"]
        assert "districts.id" in result["dimensions"]

    def test_districts_dimensions_present_for_generic_area_question(self, catalog):
        retriever = CatalogRetriever(catalog, top_k_cubes=1)
        result = retriever.retrieve("list các khu trong smartcity")
        assert "districts" in result["cubes"]
        assert "districts.name" in result["dimensions"]

    def test_reference_cube_never_contributes_measures(self, catalog):
        """districts không có measure nào -> bổ sung cube này không được
        phép "vô tình" thêm measure lạ vào candidates."""
        retriever = CatalogRetriever(catalog, top_k_cubes=1)
        result = retriever.retrieve("tốc độ trung bình xe cộ")
        districts_measures = [m for m in result["measures"] if m.startswith("districts.")]
        assert districts_measures == []
