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

from app.catalog.models import Catalog, CatalogCube, CatalogField
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

    def test_reference_cube_own_measures_are_kept_not_dropped(self, catalog):
        """Bug 5: `districts` giờ có measure riêng (`total_sections`) —
        force-include theo `is_reference` (KHÔNG còn dựa vào heuristic "không
        có measure") vẫn phải giữ measure riêng đó, không được âm thầm bỏ đi.
        Trước đây test này giả định `districts` không có measure nào — giả
        định đó đã lỗi thời từ khi thêm `districts.total_sections` (xem
        cube_meta.py::_REFERENCE_CUBE_NAMES + CatalogCube.is_reference)."""
        retriever = CatalogRetriever(catalog, top_k_cubes=1)
        result = retriever.retrieve("tốc độ trung bình xe cộ")
        assert "districts.total_sections" in result["measures"]

    def test_reference_cube_with_measures_still_force_included(self, catalog):
        """Hồi quy Bug 5: cube có `is_reference=True` VÀ có measures riêng
        (khác điều kiện cũ `not cube.measures`) vẫn phải luôn được
        force-include — không chỉ khi cube "trống" measures."""
        districts = catalog.cube("districts")
        assert districts is not None and districts.is_reference is True
        assert len(districts.measures) >= 1  # có measure thật -> case cần bug fix bảo vệ

        retriever = CatalogRetriever(catalog, top_k_cubes=1)
        result = retriever.retrieve("tốc độ trung bình xe cộ")
        assert "districts" in result["cubes"]

    def test_safety_net_still_catches_measureless_cube_missing_is_reference_flag(self, catalog, capsys):
        """Lưới an toàn dự phòng (`or not cube.measures`, Bug 5 Phase 2): một
        cube không có measure nào nhưng LỠ CHƯA được gắn `is_reference=True`
        (vd quên thêm tên vào `_REFERENCE_CUBE_NAMES` khi thêm cube mới) vẫn
        phải được force-include như trước — kèm log cảnh báo để phát hiện
        thiếu sót đó thay vì âm thầm."""
        orphan_cube = CatalogCube(
            name="orphan_reference",
            title="Orphan Reference",
            measures=[],
            dimensions=[CatalogField(name="orphan_reference.name", title="name", type="string")],
            time_dimensions=[],
            is_reference=False,  # cố ý: mô phỏng cube quên gắn is_reference
        )
        synthetic_catalog = Catalog(cubes=[*catalog.cubes, orphan_cube])

        retriever = CatalogRetriever(synthetic_catalog, top_k_cubes=1)
        result = retriever.retrieve("tốc độ trung bình xe cộ")

        assert "orphan_reference" in result["cubes"]
        assert "thiếu trong cube_meta.py" in capsys.readouterr().out


class TestTopCubeSignal:
    """`top_cube` (kế hoạch fix Yellow case, Bước 1) — tín hiệu HẸP, cube
    nghiệp vụ RRF cao nhất, không tính cube tham chiếu (`is_reference`) và
    không bị pha loãng bởi việc union với `top_k_cubes` + cube tham chiếu
    trong `result["cubes"]` (luôn có ≥3-4 phần tử trong thực tế)."""

    def test_top_cube_narrows_to_single_business_cube(self, catalog):
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Hiệu suất hệ thống đèn đường ở Khu Căn hộ đêm 22/7")
        assert result["top_cube"] == "smart_lighting"
        assert len(result["cubes"]) >= 3  # candidates rộng vẫn giữ nguyên như cũ

    def test_top_cube_can_be_none_for_generic_question(self, catalog):
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("có bao nhiêu khu vực trong smartcity")
        # Không raise dù không có cube nghiệp vụ nào match rõ ràng.
        assert result["top_cube"] is None or isinstance(result["top_cube"], str)

    def test_rrf_tie_break_prefers_dense_rank_on_exact_tie(self, catalog):
        """Fix root cause Y05 (điều tra sau khi user yêu cầu, 2026-08-20):
        `traffic_flow` và `street_incidents` có domain keyword đều chứa
        "giao thông" -> BM25 cube-level TIE TUYỆT ĐỐI cho câu hỏi này (cùng
        overlap 3 token). Trước fix, `sort` ổn định giữ nguyên thứ tự xuất
        hiện trong `catalog.cubes` (Cube Meta API trả `street_incidents`
        TRƯỚC `traffic_flow`) — hoàn toàn ngẫu nhiên, không phải tín hiệu
        liên quan — khiến `street_incidents` thắng dù dense embedding (đáng
        tin hơn cho case đồng nghĩa/lân cận domain) đã phân biệt rõ
        `traffic_flow` cao hơn hẳn (0.39 vs 0.34, verify bằng diagnostic
        thật). Fix: thêm dense_rank làm tie-break phụ khi RRF score bằng
        nhau tuyệt đối."""
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Tình hình giao thông ở TTTM khung giờ 17h-19h ngày 25/7")
        assert result["top_cube"] == "traffic_flow"


class TestFieldAmbiguitySignal:
    """`field_ambiguity` (kế hoạch fix Yellow case, Bước 2) — mơ hồ cấp
    measure/dimension trong `top_cube`, tất định (BM25-overlap + gap_ratio +
    ngưỡng sàn tuyệt đối), KHÔNG dùng similarity liên tục làm short-circuit
    chặn cứng (bài học case E, docs/04-ambiguous-question-handling.md).
    Dùng retriever THẬT + fixture catalog thật — không mock, để tránh lặp
    lại lỗi "test xanh nhưng code chết" (`test_orchestrator.py` cũ)."""

    def test_y04_style_lighting_efficiency_is_ambiguous(self, catalog):
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Hiệu suất hệ thống đèn đường ở Khu Căn hộ đêm 22/7")
        fa = result["field_ambiguity"]
        assert fa is not None
        assert fa["cube"] == "smart_lighting"
        candidate_names = {name for name, _ in fa["candidates"]}
        assert candidate_names & {
            "smart_lighting.faulty_time_pct",
            "smart_lighting.total_power_kwh",
            "smart_lighting.faulty_lamp_count",
        }

    def test_y08_style_livability_score_vs_grade_is_ambiguous(self, catalog):
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Chỉ số đáng sống Livability ở Khu biệt thự ngày 25/7 có tốt không?")
        fa = result["field_ambiguity"]
        assert fa is not None
        assert fa["cube"] == "city_health_index"
        candidate_names = {name for name, _ in fa["candidates"]}
        assert "city_health_index.avg_livability_index" in candidate_names
        assert "city_health_index.livability_grade" in candidate_names

    def test_y09_style_parking_occupancy_vs_level_is_ambiguous(self, catalog):
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Bãi đỗ xe ở TTTM ngày 27/7 có bị quá tải không?")
        fa = result["field_ambiguity"]
        assert fa is not None
        assert fa["cube"] == "smart_parking"
        candidate_names = {name for name, _ in fa["candidates"]}
        assert "smart_parking.occupancy_pct" in candidate_names
        assert "smart_parking.occupancy_level" in candidate_names

    def test_y10_style_noise_value_vs_category_is_ambiguous(self, catalog):
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Mức độ ô nhiễm tiếng ồn ở Khu biệt thự trong tuần 21-28/7")
        fa = result["field_ambiguity"]
        assert fa is not None
        assert fa["cube"] == "air_quality"
        candidate_names = {name for name, _ in fa["candidates"]}
        assert "air_quality.avg_noise_db" in candidate_names
        assert "air_quality.noise_category" in candidate_names

    def test_y03_style_incident_impact_phrase_is_ambiguous(self, catalog):
        """Fix root cause Y03 (điều tra sau khi user yêu cầu, 2026-08-20):
        cụm mơ hồ "mức độ ảnh hưởng" trước đây chỉ khớp verbatim với
        `total_impact_hours` (thắng áp đảo, gap_ratio=0.5 -> không mơ hồ) vì
        đây là field DUY NHẤT có nguyên cụm này trong vietnamese term — sửa
        bằng cách lặp lại cụm này GIỐNG HỆT ở cả 3 field ứng viên hợp lệ
        (cùng pattern Y01/Y05), đồng thời bỏ "mức độ" khỏi
        `street_incidents.severity` (đẩy doc_freq của "mức"/"độ" chạm ngưỡng
        loại token neo domain, hạ top_score dưới sàn tối thiểu)."""
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Mức độ ảnh hưởng của sự cố tại TTTM ngày 28/7")
        fa = result["field_ambiguity"]
        assert fa is not None
        assert fa["cube"] == "street_incidents"
        candidate_names = {name for name, _ in fa["candidates"]}
        assert candidate_names == {
            "street_incidents.total_incidents",
            "street_incidents.avg_duration_min",
            "street_incidents.total_impact_hours",
        }

    def test_y05_style_traffic_situation_phrase_is_ambiguous(self, catalog):
        """Fix root cause Y05 (điều tra sau khi user yêu cầu, 2026-08-20):
        2 lớp lỗi chồng lên nhau. (1) `top_cube` từng nhận nhầm
        `street_incidents` thay vì `traffic_flow` — BM25 cube-level cho 2
        cube này TIE TUYỆT ĐỐI (cả 2 domain keyword đều có "giao thông"), và
        sort ổn định phá tie theo thứ tự `catalog.cubes` (ngẫu nhiên, không
        phải tín hiệu thật) thay vì theo dense embedding (đã phân biệt đúng
        `traffic_flow` cao hơn hẳn) — xem
        `TestTopCubeSignal::test_rrf_tie_break_prefers_dense_rank_on_exact_tie`.
        (2) Cụm mơ hồ "tình hình giao thông" trước đây chỉ khớp verbatim với
        `congestion_rate` (thắng áp đảo, gap_ratio=0.5) — sửa bằng cách lặp
        lại GIỐNG HỆT ở cả 3 field ứng viên hợp lệ, cùng pattern case N."""
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Tình hình giao thông ở TTTM khung giờ 17h-19h ngày 25/7")
        assert result["top_cube"] == "traffic_flow"
        fa = result["field_ambiguity"]
        assert fa is not None
        assert fa["cube"] == "traffic_flow"
        candidate_names = {name for name, _ in fa["candidates"]}
        assert candidate_names == {
            "traffic_flow.avg_speed",
            "traffic_flow.sum_vehicle_count",
            "traffic_flow.congestion_rate",
        }

    def test_g07_two_explicitly_named_measures_is_not_ambiguous(self, catalog):
        """Chống regression quan trọng nhất: câu hỏi nêu tên RIÊNG BIỆT 2
        measure (Rule 5) không được coi là mơ hồ — measure top-1
        (`overspeed_count`) và top-2 (`congestion_rate`) tách biệt đủ rõ
        (gap_ratio 0.5, xem kế hoạch fix Yellow case root cause #6)."""
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve(
            "Cho tôi biết số lần vi phạm quá tốc độ và tỷ lệ kẹt xe ở TTTM trong ngày 23/7/2026?"
        )
        assert result["field_ambiguity"] is None

    def test_simple_green_question_is_not_ambiguous(self, catalog):
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Tốc độ giao thông trung bình ở Khu biệt thự ngày 25/7/2026 là bao nhiêu?")
        assert result["field_ambiguity"] is None

    def test_superlative_question_is_excluded_from_field_ambiguity(self, catalog):
        """Câu hỏi có từ so sánh nhất ("đông nhất") đã có Rule 10 xử lý riêng
        (order+limit) — nhường hẳn, không chồng chéo với field_ambiguity."""
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Vào khung giờ nào trong ngày 24/7/2026 thì lưu lượng xe ở TTTM đông nhất?")
        assert result["field_ambiguity"] is None

    def test_gap_ratio_configurable_via_constructor(self, catalog):
        # `gap_ratio` là NGƯỠNG TỐI THIỂU để coi 2 field top là "đủ tách
        # biệt" (`if gap_ratio_thực_tế >= threshold: return None`) — ngưỡng
        # CÀNG CAO càng KHÓ đạt "đủ tách biệt" -> càng DỄ bị coi là mơ hồ
        # (ngược trực giác "cao = strict/khó trigger" nên đặt tên rõ theo
        # ngưỡng, không theo "strict/lenient"). Câu hỏi Y04-style cho
        # gap_ratio THỰC TẾ đúng bằng 0.0 (3-way tie tuyệt đối giữa
        # faulty_time_pct/lamp_status/operating_mode, verify bằng diagnostic
        # thật) — dùng ngưỡng 0.0 (khớp đúng biên `>=`) và 0.5 để cho kết
        # quả khác nhau tất định, tránh phụ thuộc so sánh float gần-bằng-0.
        threshold_0 = CatalogRetriever(catalog, field_ambiguity_gap_ratio=0.0)
        threshold_half = CatalogRetriever(catalog, field_ambiguity_gap_ratio=0.5)
        q = "Hiệu suất hệ thống đèn đường ở Khu Căn hộ đêm 22/7"
        assert threshold_0.retrieve(q)["field_ambiguity"] is None
        assert threshold_half.retrieve(q)["field_ambiguity"] is not None

    def test_gap_ratio_configurable_via_env_var(self, catalog, monkeypatch):
        monkeypatch.setenv("FIELD_AMBIGUITY_GAP_RATIO", "0.9")
        retriever = CatalogRetriever(catalog)
        assert retriever.field_ambiguity_gap_ratio == 0.9

    def test_y06_style_nonexistent_district_is_not_field_ambiguous(self, catalog):
        """Regression cho fix Bước 7 (benchmark LLM thật): 'khu trung tâm'
        không tồn tại trong danh mục khu vực thật — nhưng token 'trung' lại
        trùng ngẫu nhiên với 'trung bình' (average) trong mô tả `avg_speed`,
        đẩy top_score lên đúng bằng ngưỡng sàn cũ 0.25 (tie tuyệt đối với
        `overspeed_count`, gap_ratio=0.0). Verify log thật: hint field-ambiguity
        (gợi ý chọn metric) bị tiêm SAI NGỮ CẢNH khiến LLM refuse thay vì để
        Nhóm 2 (`SampleValues`/case G) hỏi lại đúng về tên khu vực. Ngưỡng
        sàn nâng lên 0.3 để loại case này (Y01/Y04/Y08/Y09/Y10 vẫn bắt đúng,
        đều có top_score ≥0.36 — xem sweep diagnostic thật)."""
        retriever = CatalogRetriever(catalog)
        result = retriever.retrieve("Tốc độ tối đa cho phép ở khu trung tâm là bao nhiêu?")
        assert result["field_ambiguity"] is None

    def test_min_score_configurable_via_constructor(self, catalog):
        # top_score thực tế của case "khu trung tâm" đúng bằng 0.25 (verify
        # diagnostic thật) — dùng ngưỡng 0.1 (dưới 0.25, sàn không chặn) và
        # 0.5 (trên 0.25, sàn chặn) để kết quả khác nhau tất định.
        low_floor = CatalogRetriever(catalog, field_ambiguity_min_score=0.1)
        high_floor = CatalogRetriever(catalog, field_ambiguity_min_score=0.5)
        q = "Tốc độ tối đa cho phép ở khu trung tâm là bao nhiêu?"
        assert low_floor.retrieve(q)["field_ambiguity"] is not None
        assert high_floor.retrieve(q)["field_ambiguity"] is None

    def test_min_score_configurable_via_env_var(self, catalog, monkeypatch):
        monkeypatch.setenv("FIELD_AMBIGUITY_MIN_SCORE", "0.9")
        retriever = CatalogRetriever(catalog)
        assert retriever.field_ambiguity_min_score == 0.9
