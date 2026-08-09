"""Sinh system prompt từ Cube catalog.

System prompt và tool schema derive từ CÙNG một catalog (Cube Meta API), nên
không bao giờ lệch nhau — xem docs/02-cube-architecture.md mục 3. Phần mô tả
catalog là ổn định -> đặt trong `system` và bật prompt caching (tuỳ provider).
Phần biến động theo request (ngày giờ hiện tại) tách riêng ở
`build_runtime_context()` để không phá cache.
"""

from __future__ import annotations

from datetime import date

from app.catalog.models import Catalog

_RULES = """\
# Nhiệm vụ
Bạn là trợ lý phân tích dữ liệu của nền tảng Smart City. Nhiệm vụ duy nhất của bạn
là chuyển câu hỏi tiếng Việt hoặc tiếng Anh của người dùng thành một lời gọi tool
`query_metrics` có tham số chính xác. Bạn KHÔNG viết SQL và KHÔNG tự bịa số liệu.

# Quy tắc bắt buộc
1. Chỉ dùng đúng tên measure và dimension có trong danh mục bên dưới. Không tự đặt tên mới.
2. Tất cả measure trong một lần gọi tool phải cùng một cube (cùng tiền tố trước dấu chấm).
   Nếu câu hỏi cần measure từ nhiều cube khác nhau, hãy hỏi lại người dùng muốn xem cube nào trước.
3. Lọc theo thời gian luôn dùng `timeDimensions`, không đưa vào `filters`.
4. Nếu người dùng không nói gì về thời gian, bỏ trống `timeDimensions`; hệ thống sẽ áp mặc định
   và hiển thị rõ cho người dùng biết.
5. Nếu câu hỏi mơ hồ, thiếu thông tin, hoặc nằm ngoài danh mục dữ liệu bên dưới:
   ĐỪNG gọi tool. Hãy trả lời bằng một câu hỏi ngắn gọn để làm rõ, và nêu các lựa chọn
   gần nhất có trong danh mục. Đây là quy tắc quan trọng nhất — đoán bừa tệ hơn hỏi lại.
6. Với câu hỏi dạng "top N", đặt `limit` và `order` thay vì mô tả bằng lời.
7. Giá trị filter hãy giữ nguyên như người dùng viết (đặt trong `values`, kể cả khi
   chỉ có một giá trị). Hệ thống sẽ tự đối chiếu với giá trị thật trong cơ sở dữ liệu.
"""


def build_catalog_markdown(catalog: Catalog) -> str:
    """Mô tả catalog dưới dạng text cho LLM đọc."""
    lines: list[str] = ["# Danh mục dữ liệu"]

    for cube in catalog.cubes:
        lines.append(f"\n## Cube `{cube.name}` — {cube.title}")

        lines.append("Measures:")
        for m in cube.measures:
            desc = f": {m.description}" if m.description else ""
            lines.append(f"  - `{m.name}`{desc}")

        if cube.dimensions:
            lines.append("Dimensions:")
            for d in cube.dimensions:
                desc = f": {d.description}" if d.description else ""
                lines.append(f"  - `{d.name}`{desc}")

        if cube.time_dimensions:
            lines.append("Time dimensions:")
            for t in cube.time_dimensions:
                desc = f": {t.description}" if t.description else ""
                lines.append(f"  - `{t.name}`{desc}")

    return "\n".join(lines)


def build_system_prompt(catalog: Catalog) -> str:
    """Phần ổn định của prompt — an toàn để cache."""
    return f"{_RULES}\n{build_catalog_markdown(catalog)}"


def build_runtime_context(
    today: date | None = None,
    default_time_range_label: str = "30 ngày gần nhất",
) -> str:
    """Phần biến động theo từng request — luôn đặt SAU câu hỏi để không phá cache."""
    today = today or date.today()
    return (
        f"<runtime_context>\n"
        f"Hôm nay là {today.isoformat()}.\n"
        f"Nếu câu hỏi không nêu mốc thời gian, hệ thống sẽ mặc định lấy {default_time_range_label}.\n"
        f"</runtime_context>"
    )
