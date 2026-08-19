"""Phát hiện cụm từ thời gian MƠ HỒ CÓ CHỦ Ý trong câu hỏi (vd "lúc trước",
"gần đây") — khác với việc câu hỏi KHÔNG nhắc gì tới thời gian (case L,
docs/04-ambiguous-question-handling.md — hành vi đó GIỮ NGUYÊN, default
`last 30 days` êm, không hỏi lại, đã là quyết định thiết kế có chủ ý).

Bối cảnh (kế hoạch fix Yellow case, Nhóm 4/Y07): người dùng dùng 1 cụm từ
tương đối rõ ràng CÓ Ý ĐỊNH chỉ 1 mốc thời gian cụ thể trong đầu, nhưng diễn
đạt mơ hồ — khác về bản chất với việc không hề nhắc gì tới thời gian. Case
này cần hỏi lại ngày cụ thể (dữ liệu chỉ có trong dải 21/7-28/7), không nên
default êm như case L.

Regex tất định, pattern rời rạc — cùng style `app/nlu/guardrails.py`, tránh
lặp lại sai lầm ngưỡng similarity liên tục chưa calibrate (case E). Đây chỉ
sinh HINT tiêm vào prompt của lượt hỏi đó (không hard-block như guardrails.py)
— để LLM tự đọc toàn bộ câu hỏi rồi quyết định cuối cùng.
"""

from __future__ import annotations

import re

_VAGUE_TIME_PATTERN = re.compile(
    r"(lúc\s*trước|trước\s*đây|gần\s*đây|dạo\s*này|hồi\s*đó|hồi\s*trước|vừa\s*rồi|mới\s*đây)",
    re.IGNORECASE,
)

# Mốc thời gian CỤ THỂ — có mặt thì câu hỏi đã đủ rõ, cụm từ mơ hồ (nếu có)
# không còn ý nghĩa quyết định (vd "AQI ngày 25/7 lúc trước có cao không?" —
# đã có ngày cụ thể, ưu tiên ngày đó).
_CONCRETE_TIME_PATTERN = re.compile(
    r"(\d{1,2}\s*[/\.]\s*\d{1,2}(\s*[/\.]\s*\d{2,4})?"  # dd/mm hoặc dd/mm/yyyy
    r"|ngày\s*\d{1,2}"
    r"|tháng\s*\d{1,2}"
    r"|tuần\s*(này|trước|sau)"
    r"|tháng\s*(này|trước|sau)"
    r"|hôm\s*nay|hôm\s*qua|ngày\s*mai)",
    re.IGNORECASE,
)


def check_vague_time_reference(question: str) -> bool:
    """`True` nếu câu hỏi dùng cụm từ thời gian mơ hồ có chủ ý VÀ không có
    mốc thời gian cụ thể nào khác đủ rõ để ưu tiên."""
    if not question:
        return False
    if not _VAGUE_TIME_PATTERN.search(question):
        return False
    return not _CONCRETE_TIME_PATTERN.search(question)


def build_vague_time_hint(question: str) -> str:
    """Sinh hint tiêm vào lượt hỏi hiện tại khi phát hiện cụm từ thời gian mơ
    hồ có chủ ý. Trả `""` nếu không có tín hiệu — KHÔNG áp dụng cho câu hỏi
    hoàn toàn không nhắc thời gian (case L vẫn giữ nguyên hành vi default êm)."""
    if not check_vague_time_reference(question):
        return ""
    return (
        "<vague_time_hint>\n"
        "Câu hỏi dùng cụm từ thời gian mơ hồ có chủ ý (vd \"lúc trước\", \"gần đây\") — khác với việc "
        "không hề nhắc tới thời gian. BẮT BUỘC hỏi lại ngày/khoảng thời gian cụ thể (dữ liệu hệ thống "
        "chỉ có trong dải 21/7/2026-28/7/2026), KHÔNG tự áp mặc định 30 ngày gần nhất và KHÔNG gọi "
        "`query_metrics` cho tới khi có mốc thời gian cụ thể.\n"
        "</vague_time_hint>"
    )
