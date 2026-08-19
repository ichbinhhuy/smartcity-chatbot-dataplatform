"""Unit test cho app/nlu/time_ambiguity.py — Nhóm 4/Y07 trong kế hoạch fix
Yellow case: cụm từ thời gian MƠ HỒ CÓ CHỦ Ý (vd "lúc trước"), khác với việc
câu hỏi không hề nhắc tới thời gian (case L, docs/04-ambiguous-question-handling.md
— hành vi đó GIỮ NGUYÊN, không đổi).
"""

from __future__ import annotations

import pytest

from app.nlu.time_ambiguity import build_vague_time_hint, check_vague_time_reference


class TestCheckVagueTimeReference:
    def test_y07_vague_phrase_triggers(self):
        assert check_vague_time_reference("Bãi đỗ xe ở Khu Căn hộ lúc trước như thế nào?") is True

    @pytest.mark.parametrize(
        "phrase",
        ["lúc trước", "trước đây", "gần đây", "dạo này", "hồi đó", "hồi trước", "vừa rồi", "mới đây"],
    )
    def test_each_vague_phrase_triggers(self, phrase):
        assert check_vague_time_reference(f"AQI ở Khu Căn hộ {phrase} thế nào?") is True

    def test_no_time_reference_does_not_trigger(self):
        """Case L: câu hỏi hoàn toàn không nhắc thời gian -> giữ nguyên hành
        vi default êm, KHÔNG coi là mơ hồ (khác với việc CÓ nhắc bằng cụm mơ hồ)."""
        assert check_vague_time_reference("AQI hôm nay thế nào?") is False
        assert check_vague_time_reference("Chỉ số đáng sống Livability trung bình của Khu biệt thự là bao nhiêu?") is False

    def test_concrete_date_overrides_vague_phrase(self):
        """Có mốc thời gian cụ thể đủ rõ -> ưu tiên mốc đó, không cần hỏi lại
        dù câu hỏi cũng chứa cụm mơ hồ."""
        assert check_vague_time_reference("AQI ngày 25/7 lúc trước có cao không?") is False

    def test_empty_question_does_not_raise(self):
        assert check_vague_time_reference("") is False
        assert check_vague_time_reference(None) is False

    @pytest.mark.parametrize(
        "question",
        [
            "Tốc độ giao thông trung bình ở Khu biệt thự ngày 25/7/2026 là bao nhiêu?",
            "Mức độ ô nhiễm tiếng ồn ở Khu biệt thự trong tuần 21-28/7",
            "Tổng số sự cố giao thông ghi nhận tại phân khu Căn hộ trong tuần từ 21/7 đến 27/7?",
        ],
    )
    def test_green_questions_with_concrete_dates_do_not_trigger(self, question):
        assert check_vague_time_reference(question) is False


class TestBuildVagueTimeHint:
    def test_empty_string_when_not_vague(self):
        assert build_vague_time_hint("AQI hôm nay thế nào?") == ""

    def test_hint_mentions_data_window_when_vague(self):
        hint = build_vague_time_hint("Bãi đỗ xe ở Khu Căn hộ lúc trước như thế nào?")
        assert hint != ""
        assert "21/7" in hint and "28/7" in hint
        assert "BẮT BUỘC hỏi lại" in hint
