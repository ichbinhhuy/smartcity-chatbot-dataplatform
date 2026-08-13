"""Mapping giá trị hiển thị <-> giá trị thật cho dimension — phần Cube không cung cấp.

Cube Meta API trả về *tên* dimension nhưng không trả về giá trị thật có trong
DB (Cube không có khái niệm "giá trị mẫu"). Đây là ngoại lệ có chủ ý với
nguyên tắc một nguồn, phạm vi hẹp — xem docs/02-cube-architecture.md mục 3.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import yaml

# Chênh lệch ratio tối thiểu giữa candidate #1 và #2 của difflib fuzzy-match
# để coi giá trị #1 là "đủ tin cậy". Dưới ngưỡng này -> 2 (hoặc nhiều) giá
# trị gần giống nhau tới mức không nên tự đoán -> trigger clarification thay
# vì silently chọn candidate đầu tiên. Xem docs/04-ambiguous-question-handling.md
# case G / FIX-04.
_AMBIGUITY_GAP = 0.05


class SampleValues:
    def __init__(self, values: dict[str, list[str]]) -> None:
        self._values = values

    @classmethod
    def load(cls, path: Path) -> SampleValues:
        if not path.exists():
            return cls({})
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(raw)

    def allowed(self, member: str) -> list[str] | None:
        return self._values.get(member)

    def resolve(self, member: str, value: str) -> tuple[str, bool, list[str] | None]:
        """Trả về (giá trị đã quy đổi, có thay đổi hay không, candidates mơ hồ).

        Phần tử thứ 3 khác `None` khi fuzzy-match tìm được ≥2 giá trị gần
        giống nhau (chênh lệch ratio < `_AMBIGUITY_GAP`) — trường hợp đó
        KHÔNG tự đoán (`value` trả về giữ nguyên bản gốc), để caller
        (`QueryValidator._resolve_filter_values`) đẩy thành lỗi validation
        và trigger repair loop/clarification thay vì âm thầm chọn sai.
        """
        val_lower = value.strip().lower()
        alias_map = {
            # Phân khu (Section IDs) - Căn hộ (Section 1)
            "section_1": "Can ho",
            "section 1": "Can ho",
            "section_001": "Can ho",
            "section 001": "Can ho",
            "sec_001": "Can ho",
            "sec 001": "Can ho",
            "sec_1": "Can ho",
            "sec 1": "Can ho",
            "s1": "Can ho",
            "s01": "Can ho",
            "s_1": "Can ho",
            "khu 1": "Can ho",
            "khu 01": "Can ho",
            "phân khu 1": "Can ho",
            "phan khu 1": "Can ho",
            "căn hộ": "Can ho",
            "can ho": "Can ho",
            "khu căn hộ": "Can ho",
            "khu can ho": "Can ho",
            "chung cư": "Can ho",
            "chung cu": "Can ho",

            # Phân khu (Section IDs) - Khu biệt thự (Section 2)
            "section_2": "Khu biet thu",
            "section 2": "Khu biet thu",
            "section_002": "Khu biet thu",
            "section 002": "Khu biet thu",
            "sec_002": "Khu biet thu",
            "sec 002": "Khu biet thu",
            "sec_2": "Khu biet thu",
            "sec 2": "Khu biet thu",
            "s2": "Khu biet thu",
            "s02": "Khu biet thu",
            "s_2": "Khu biet thu",
            "khu 2": "Khu biet thu",
            "khu 02": "Khu biet thu",
            "phân khu 2": "Khu biet thu",
            "phan khu 2": "Khu biet thu",
            "khu biệt thự": "Khu biet thu",
            "khu biet thu": "Khu biet thu",
            "biệt thự": "Khu biet thu",
            "biet thu": "Khu biet thu",

            # Phân khu (Section IDs) - TTTM (Section 3)
            "section_3": "TTTM",
            "section 3": "TTTM",
            "section_003": "TTTM",
            "section 003": "TTTM",
            "sec_003": "TTTM",
            "sec 003": "TTTM",
            "sec_3": "TTTM",
            "sec 3": "TTTM",
            "s3": "TTTM",
            "s03": "TTTM",
            "s_3": "TTTM",
            "khu 3": "TTTM",
            "khu 03": "TTTM",
            "phân khu 3": "TTTM",
            "phan khu 3": "TTTM",
            "tttm": "TTTM",
            "trung tâm thương mại": "TTTM",
            "trung tam thuong mai": "TTTM",
            "cổng chính": "TTTM",
            "cong chinh": "TTTM",
            "siêu thị": "TTTM",
            "sieu thi": "TTTM",
            "mall": "TTTM",

            # Trạng thái đèn đường (smart_lighting.lamp_status)
            "bị hỏng": "FAULTY",
            "bi hong": "FAULTY",
            "hỏng": "FAULTY",
            "hong": "FAULTY",
            "hỏng hóc": "FAULTY",
            "hong hoc": "FAULTY",
            "lỗi": "FAULTY",
            "loi": "FAULTY",
            "bình thường": "NORMAL",
            "binh thuong": "NORMAL",
            "giảm sáng": "DIMMED",
            "giam sang": "DIMMED",
            "mờ": "DIMMED",

            # Chế độ đèn (smart_lighting.operating_mode)
            "buổi tối": "EVENING_FULL",
            "buoi toi": "EVENING_FULL",
            "bật hết": "EVENING_FULL",
            "ban đêm": "NIGHT_DIMMING",
            "ban dem": "NIGHT_DIMMING",
            "tiết kiệm": "NIGHT_DIMMING",
            "ban ngày": "DAY_OFF",
            "ban ngay": "DAY_OFF",
            "tắt": "DAY_OFF",

            # Chất lượng không khí & Độ ồn (air_quality)
            "tốt": "GOOD",
            "tot": "GOOD",
            "sạch": "GOOD",
            "sach": "GOOD",
            "trung bình": "MODERATE",
            "trung binh": "MODERATE",
            "vừa": "MODERATE",
            "xấu": "UNHEALTHY",
            "xau": "UNHEALTHY",
            "kém": "UNHEALTHY",
            "ô nhiễm": "UNHEALTHY",
            "o nhiem": "UNHEALTHY",
            "độc hại": "UNHEALTHY",
            "yên tĩnh": "QUIET",
            "yen tinh": "QUIET",
            "vắng vẻ": "QUIET",
            "ồn ào": "NOISY",
            "on ao": "NOISY",
            "ồn": "NOISY",

            # Mức độ đỗ xe (smart_parking.occupancy_level)
            "thưa": "LOW",
            "thua": "LOW",
            "vắng": "LOW",
            "vua phai": "OPTIMAL",
            "vừa phải": "OPTIMAL",
            "quá tải": "CRITICAL",
            "qua tai": "CRITICAL",
            "đầy bãi": "CRITICAL",
            "day bai": "CRITICAL",
            "đầy": "CRITICAL",
            "kín chỗ": "CRITICAL",

            # Loại sự cố (street_incidents.incident_type)
            "tai nạn": "ACCIDENT",
            "tai nan": "ACCIDENT",
            "va chạm": "ACCIDENT",
            "va cham": "ACCIDENT",
            "công trình": "ROAD_WORK",
            "cong trinh": "ROAD_WORK",
            "sửa đường": "ROAD_WORK",
            "thi công": "ROAD_WORK",
            "ngập lụt": "FLOODING",
            "ngap lut": "FLOODING",
            "ngập": "FLOODING",
            "ngap": "FLOODING",
            "lụt": "FLOODING",
            "kẹt xe": "CONGESTION",
            "ket xe": "CONGESTION",
            "ùn tắc": "CONGESTION",
            "un tac": "CONGESTION",
            "tắc đường": "CONGESTION",

            # Mức độ sự cố (street_incidents.severity)
            "nhẹ": "MINOR",
            "nhe": "MINOR",
            "nhỏ": "MINOR",
            "nghiêm trọng": "CRITICAL",
            "nghiem trong": "CRITICAL",
            "nguy hiểm": "CRITICAL",

            # Cấp độ đáng sống (city_health_index.livability_grade)
            "xuất sắc": "EXCELLENT",
            "xuat sac": "EXCELLENT",
            "tuyệt vời": "EXCELLENT",
            "tệ": "POOR",
            "te": "POOR",
        }
        if val_lower in alias_map:
            return alias_map[val_lower], True, None

        allowed = self._values.get(member)
        if not allowed or value in allowed:
            return value, False, None

        # So khớp KHÔNG phân biệt hoa/thường — value LLM trả thường viết
        # thường (vd "evening_full") trong khi DB lưu enum viết hoa (vd
        # "EVENING_FULL"); so trực tiếp value.lower() với `allowed` gốc
        # (không lower) làm ratio gần như luôn = 0 vì lệch case ở mọi ký tự.
        lower_to_original = {a.lower(): a for a in allowed}
        close = difflib.get_close_matches(val_lower, list(lower_to_original.keys()), n=3, cutoff=0.6)
        if not close:
            return value, False, None

        if len(close) >= 2:
            top_ratio = difflib.SequenceMatcher(None, val_lower, close[0]).ratio()
            second_ratio = difflib.SequenceMatcher(None, val_lower, close[1]).ratio()
            if (top_ratio - second_ratio) < _AMBIGUITY_GAP:
                candidates = [lower_to_original[c] for c in close]
                return value, False, candidates

        return lower_to_original[close[0]], True, None
