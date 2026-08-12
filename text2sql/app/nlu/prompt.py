"""Sinh system prompt từ Cube catalog.

System prompt và tool schema derive từ CÙNG một catalog (Cube Meta API), nên
không bao giờ lệch nhau — xem docs/02-cube-architecture.md mục 3. Phần mô tả
catalog là ổn định -> đặt trong `system` và bật prompt caching (tuỳ provider).
Phần biến động theo request (ngày giờ hiện tại) tách riêng ở
`build_runtime_context()` để không phá cache.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

VN_TZ = timezone(timedelta(hours=7))

_RULES = """\
# Vai trò (Role)
Trợ lý NLU Đô thị Thông minh (Smart City NLU Assistant). Nhiệm vụ của bạn là chuyển đổi câu hỏi tự nhiên của người dùng thành lời gọi hàm `query_metrics` chính xác.

# Quy tắc cốt lõi (Rules)
1. CHỈ sử dụng các chỉ số (measures), chiều (dimensions) và chiều thời gian (timeDimensions) có mặt trong Catalog bên dưới.
2. Tất cả các measures trong 1 lời gọi tool BẮT BUỘC phải thuộc về CÙNG một Cube.
3. QUAN TRỌNG - TRÍCH XUẤT ĐỦ CHỈ SỐ (MULTI-METRIC EXTRACTION): Bạn BẮT BUỘC phải trích xuất TẤT CẢ các chỉ số được đề cập hoặc hàm ý trong câu hỏi vào danh sách `measures`. TUYỆT ĐỐI KHÔNG bỏ rơi bất kỳ chỉ số nào được hỏi (Ví dụ: nếu người dùng hỏi cả 'số lần vi phạm' và 'tốc độ trung bình', phải đưa CẢ 2 measures vào danh sách).
4. QUAN TRỌNG - NHẬN DIỆN KHUNG GIỜ (TIME GRANULARITY EXTRACTION): CHỈ gán `"granularity": "hour"` khi câu hỏi CÓ TỪ HỎI RÕ VỀ GIỜ (như 'mấy giờ', 'lúc mấy giờ', 'khung giờ nào', 'giờ cao điểm', 'vào giờ nào', 'theo từng giờ').
5. QUAN TRỌNG - ĐIỀU KHIỂN GRANULARITY CHUNG: Khi câu hỏi hỏi tổng thể theo ngày/tuần/tháng (như 'hôm 25/7', 'ngày 25/7', 'tháng 7', 'tuần qua') MÀ KHÔNG hỏi mốc giờ, TUYỆT ĐỐI KHÔNG gán `granularity` (để `granularity` rỗng hoặc null) để hệ thống tính tổng tích lũy cho cả khoảng thời gian đó.
6. QUAN TRỌNG - TRÍCH XUẤT DIMENSION KHI HỎI ĐỐI TƯỢNG (ENTITY QUESTION DIMENSIONS): Khi câu hỏi dạng 'X nào' (như 'đèn nào', 'cột đèn nào', 'camera nào', 'khu vực nào', 'sự cố nào'), bạn BẮT BUỘC phải đưa chiều định danh đối tượng tương ứng (như `smart_lighting.pole_id`, `traffic_flow.camera_id`, `section_id`) vào danh sách `dimensions` để hệ thống gom nhóm theo từng đối tượng.
7. Lọc thời gian BẮT BUỘC sử dụng `timeDimensions` (vd: `air_quality.recorded_at`, `traffic_flow.recorded_at`, `city_health_index.date`, `smart_parking.recorded_at`, `smart_lighting.recorded_at`, `street_incidents.timestamp_start`).
8. Nếu câu hỏi không nêu mốc thời gian, hãy để `timeDimensions` rỗng (hệ thống sẽ áp dụng thời gian mặc định).
9. Giữ nguyên tên giá trị bộ lọc như người dùng viết; hệ thống tự động ánh xạ các tên gọi phân khu (`Khu biet thu`, `Can ho`, `TTTM`).
10. Nếu ngày/tháng được nêu mà không có năm (vd: '27.7', 'ngày 25 tháng 7'), BẮT BUỘC lấy năm mặc định là năm hiện tại (2026).
11. QUAN TRỌNG - SẮP XẾP HẠNG TOP/PEAK: Khi câu hỏi có từ so sánh nhất (như 'nhiều nhất', 'cao nhất', 'lớn nhất', 'ít nhất', 'thấp nhất', 'đông nhất'), bạn BẮT BUỘC phải gán `order` theo measure đó (`"direction": "desc"` hoặc `"asc"`) và gán `"limit": 1` (hoặc top N tương ứng).
12. QUAN TRỌNG - CÂU HỎI LÀM RÕ (CLARIFICATION): Nếu không đủ tin cậy để gọi `query_metrics`, TUYỆT ĐỐI KHÔNG hỏi lại chung chung (như "Bạn muốn xem thông tin gì?"). PHẢI đề xuất 2-3 lựa chọn CỤ THỂ (tên chỉ số/chủ đề, lấy từ Catalog bên dưới) dưới dạng câu hỏi trắc nghiệm ngắn gọn kiểu "Bạn muốn xem A, B hay C?", để người dùng chỉ cần chọn 1 trong các gợi ý đó.
13. BẮT BUỘC - CÂU HỎI QUÁ CHUNG CHUNG: Nếu câu hỏi KHÔNG nhắc tới bất kỳ tên chỉ số, chủ đề, hay đối tượng cụ thể nào (ví dụ chỉ nói "cho tôi xem số liệu", "cho tôi biết thông tin", "xem dữ liệu" mà không nói rõ về AQI, giao thông, bãi đỗ xe, chiếu sáng, sự cố hay chỉ số đáng sống), bạn TUYỆT ĐỐI KHÔNG được tự chọn một cube/measure bất kỳ để trả lời. Trong trường hợp này BẮT BUỘC phải hỏi lại theo đúng Rule 12, kể cả khi Catalog bên dưới chỉ gợi ý 1-2 cube — KHÔNG suy diễn rằng đó là điều người dùng muốn.
"""


def build_catalog_markdown(catalog: Catalog, candidates: dict[str, list[str]] | None = None) -> str:
    """Mô tả catalog đầy đủ tiêu đề và mô tả tiếng Việt chi tiết cho LLM."""
    lines: list[str] = ["# Catalog (Danh mục chỉ số & chiều dữ liệu)"]
    cand_measures = set(candidates.get("measures", [])) if candidates else None
    cand_dimensions = set(candidates.get("dimensions", [])) if candidates else None
    cand_cubes = set(candidates.get("cubes", [])) if candidates else None

    for c in catalog.cubes:
        if cand_cubes and c.name not in cand_cubes:
            continue

        m_list = [m for m in c.measures if cand_measures is None or m.name in cand_measures]
        d_list = [d for d in c.dimensions if cand_dimensions is None or d.name in cand_dimensions]
        t_list = list(c.time_dimensions)

        if not m_list and not d_list:
            continue

        lines.append(f"\n## Cube `{c.name}` ({c.title}):")
        if m_list:
            lines.append("  * Measures (Chỉ số đo lường):")
            for m in m_list:
                desc_str = f" - {m.description}" if m.description else ""
                lines.append(f"    - `{m.name}` ({m.title}){desc_str}")
        if d_list:
            lines.append("  * Dimensions (Chiều phân tích):")
            for d in d_list:
                desc_str = f" - {d.description}" if d.description else ""
                lines.append(f"    - `{d.name}` ({d.title}){desc_str}")
        if t_list:
            lines.append("  * TimeDimensions (Thời gian):")
            for t in t_list:
                desc_str = f" - {t.description}" if t.description else ""
                lines.append(f"    - `{t.name}` ({t.title}){desc_str}")
    return "\n".join(lines)


def build_system_prompt(catalog: Catalog, candidates: dict[str, list[str]] | None = None) -> str:
    return f"{_RULES}\n{build_catalog_markdown(catalog, candidates)}"


def build_clarification_suggestions(
    catalog: Catalog, candidates: dict[str, list[str]] | None, max_suggestions: int = 3
) -> list[str]:
    """Suy ra 1-3 gợi ý ngắn gọn (tiếng Việt) từ RAG candidates, dùng làm
    quick-reply chip ở FE khi status=CLARIFICATION.

    Cố ý KHÔNG parse text câu hỏi làm rõ mà LLM sinh ra (dễ vỡ, phụ thuộc cách
    model diễn đạt) — suy trực tiếp từ `candidates`, cùng nguồn dữ liệu mà
    `build_system_prompt()` đã dùng để dựng catalog cho lượt gọi đó, nên luôn
    nhất quán với những gì model đang "nhìn thấy".
    """
    if not candidates:
        return []

    suggestions: list[str] = []
    for cube_name in candidates.get("cubes", [])[:max_suggestions]:
        cube = catalog.cube(cube_name)
        if cube:
            suggestions.append(cube.title)

    if not suggestions:
        for m_name in candidates.get("measures", [])[:max_suggestions]:
            m = catalog.get_measure(m_name)
            if m:
                suggestions.append(m.title)

    return suggestions[:max_suggestions]


def build_runtime_context(
    today: date | None = None,
    default_time_range_label: str = "30 ngày gần nhất",
) -> str:
    """Phần biến động theo từng request — luôn đặt SAU câu hỏi để không phá cache."""
    today = today or datetime.now(VN_TZ).date()
    return (
        f"<runtime_context>\n"
        f"Hôm nay là {today.isoformat()} (Năm {today.year}).\n"
        f"Nếu người dùng nêu ngày/tháng mà không ghi năm (ví dụ: '27.7', 'ngày 25/7'), BẮT BUỘC lấy năm mặc định là {today.year}.\n"
        f"Nếu câu hỏi không nêu mốc thời gian, hệ thống sẽ mặc định lấy {default_time_range_label}.\n"
        f"</runtime_context>"
    )
