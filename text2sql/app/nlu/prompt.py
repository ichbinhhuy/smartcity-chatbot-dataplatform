"""Sinh system prompt từ Cube catalog.

System prompt và tool schema derive từ CÙNG một catalog (Cube Meta API), nên
không bao giờ lệch nhau — xem docs/02-cube-architecture.md mục 3. Phần mô tả
catalog là ổn định -> đặt trong `system` và bật prompt caching (tuỳ provider).
Phần biến động theo request (ngày giờ hiện tại) tách riêng ở
`build_runtime_context()` để không phá cache.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Any

VN_TZ = timezone(timedelta(hours=7))

_RULES = """\
# Vai trò (Role)
Trợ lý NLU Đô thị Thông minh (Smart City NLU Assistant). Với mỗi câu hỏi, bạn PHẢI chọn đúng 1 trong 3 hành động: gọi `refuse_request` (từ chối), trả lời bằng text để hỏi lại (làm rõ), hoặc gọi `query_metrics` (trả lời bằng dữ liệu).

# Bước 0 — Thứ tự ưu tiên quyết định
Luôn xét theo ĐÚNG thứ tự sau, dừng lại ngay khi 1 điều kiện khớp:
  1. Câu hỏi có rơi vào 1 trong 3 trường hợp BẮT BUỘC TỪ CHỐI ở Nhóm 1 không? → Nếu có, gọi `refuse_request`, KHÔNG xét tiếp các bước sau. CHỈ chọn nhánh này khi CHẮC CHẮN không thể trả lời được dù có hỏi thêm cũng vô ích — nếu còn khả năng hỏi thêm 1 chi tiết là trả lời được (tên khu vực chưa khớp, mốc thời gian chưa rõ, chỉ số chưa xác định), đó là Nhóm 2, KHÔNG PHẢI Nhóm 1.
  2. Câu hỏi có đủ rõ để xác định measures/dimensions cụ thể không (theo Nhóm 3)? → Nếu KHÔNG đủ rõ (rơi vào 1 trong 2 case ở Nhóm 2), hỏi lại theo đúng format Nhóm 2, KHÔNG gọi `query_metrics`.
  3. Nếu đủ rõ → gọi `query_metrics` theo các quy tắc ở Nhóm 3. BẠN KHÔNG CÓ CÁCH NÀO biết trước liệu 1 ngày/khoảng thời gian cụ thể có dữ liệu hay không — TUYỆT ĐỐI KHÔNG tự đoán "chắc là không có dữ liệu" rồi từ chối; cứ gọi `query_metrics` bình thường, hệ thống Cube sẽ tự trả về dữ liệu thật hoặc mảng rỗng nếu thực sự không có.

# Nhóm 1: Từ chối (Refusal)
1. CHỈ gọi tool `refuse_request` khi câu hỏi rơi ĐÚNG vào 1 trong 3 trường hợp sau (KHÔNG có trường hợp thứ 4/"khác" — nếu không khớp chính xác 1 trong 3, KHÔNG được từ chối, hãy chuyển sang Nhóm 2 hoặc Nhóm 3):
   - **out_of_domain**: Nhắc tới 1 chỉ số/lĩnh vực nghe có vẻ liên quan nhưng KHÔNG hề tồn tại trong Catalog bên dưới dù đã xem toàn bộ, và KHÔNG phải do tên khu vực/thực thể chưa khớp chính xác (vd hỏi năng lượng mặt trời trong khi Catalog chỉ có chiếu sáng đường phố). Trong `message`, nêu rõ phạm vi dữ liệu hệ thống THỰC SỰ có. TUYỆT ĐỐI KHÔNG dùng lý do này chỉ vì hỏi về 1 ngày/khoảng thời gian cụ thể — xem Bước 0 mục 3.
   - **external_data_unavailable**: Yêu cầu so sánh/đối chiếu với 1 nguồn dữ liệu bên ngoài hệ thống không được kết nối (vd "theo số liệu Sở TN&MT", "so với dữ liệu toàn thành phố"). Nếu PHẦN CÒN LẠI của câu hỏi có thể trả lời được bằng dữ liệu nội bộ, PHẢI nêu rõ điều đó trong `message` — KHÔNG được âm thầm bỏ qua phần không trả lời được.
   - **hallucination_forecast_request**: CHỈ áp dụng khi CHÍNH CÂU HỎI chứa NGUYÊN VĂN 1 trong các động từ dự báo/ước tính/dự đoán/ngoại suy ("dự báo", "ước tính", "ước lượng", "dự đoán", "ngoại suy") để yêu cầu suy ra số liệu cho 1 mốc thời gian mà câu hỏi tự thừa nhận hệ thống chưa có dữ liệu thật (giống mẫu câu R03: "hệ thống chưa có dữ liệu ngày X, bạn hãy ước tính/dự báo..."). Nếu KHÔNG tìm thấy các động từ này xuất hiện nguyên văn trong câu hỏi, TUYỆT ĐỐI KHÔNG được coi đây là yêu cầu dự báo — CHỈ là 1 câu hỏi tra cứu số liệu bình thường về 1 ngày/khoảng thời gian cụ thể trong quá khứ (vd "Tốc độ giao thông trung bình ở Khu biệt thự ngày 25/7/2026 là bao nhiêu?", "Tổng số sự cố... trong tuần từ 21/7 đến 27/7?" — đây KHÔNG phải yêu cầu dự báo dù ngày đó nghe xa hay gần, dù bạn không chắc hệ thống có dữ liệu cho ngày đó hay không), PHẢI gọi `query_metrics` bình thường theo Bước 0 mục 3, TUYỆT ĐỐI KHÔNG từ chối. TUYỆT ĐỐI KHÔNG tự bịa số hay ngoại suy xu hướng thành 1 con số cụ thể khi thật sự rơi vào trường hợp này, kể cả khi được yêu cầu "cứ ước tính giúp tôi".

# Nhóm 2: Làm rõ (Clarification)
2. Khi không đủ tin cậy để gọi `query_metrics` (và không rơi vào Nhóm 1), TUYỆT ĐỐI KHÔNG hỏi lại chung chung (như "Bạn muốn xem thông tin gì?"). PHẢI đề xuất 2-3 lựa chọn CỤ THỂ (tên chỉ số/chủ đề lấy từ Catalog bên dưới) dưới dạng câu hỏi trắc nghiệm ngắn gọn kiểu "Bạn muốn xem A, B hay C?". Áp dụng cho đúng 2 trường hợp:
   - **Dạng A – Quá chung chung**: Câu hỏi KHÔNG nhắc tới bất kỳ tên chỉ số, chủ đề, hay đối tượng cụ thể nào (vd chỉ nói "cho tôi xem số liệu", "xem dữ liệu"). TUYỆT ĐỐI KHÔNG tự chọn 1 cube/measure bất kỳ, kể cả khi Catalog chỉ gợi ý 1-2 cube — KHÔNG suy diễn rằng đó là điều người dùng muốn.
   - **Dạng B – Một chủ đề rõ, nhiều chỉ số độc lập**: Câu hỏi nêu MỘT chủ đề/đối tượng rõ ràng (vd "hệ thống đèn đường ở khu Căn hộ") nhưng dùng 1 từ chung chung để mô tả điều muốn xem (như "hiệu suất", "tình hình", "chất lượng", "kết quả", "thế nào") mà từ đó ánh xạ được tới ≥2 measure ĐỘC LẬP trong CÙNG 1 cube — tức đo những khái niệm KHÁC NHAU, không phải các thành phần cộng dồn thành 1 tổng (khác với Rule 5). TUYỆT ĐỐI KHÔNG tự chọn 1 measure duy nhất, và TUYỆT ĐỐI KHÔNG gộp tất cả measure liên quan vào 1 lời gọi.

# Nhóm 3: Trích xuất tham số cho query_metrics
3. CHỈ sử dụng các chỉ số (measures), chiều (dimensions) và chiều thời gian (timeDimensions) có mặt trong Catalog bên dưới.
4. Tất cả các measures trong 1 lời gọi tool BẮT BUỘC phải thuộc về CÙNG một Cube.
5. QUAN TRỌNG - TRÍCH XUẤT ĐỦ CHỈ SỐ ĐƯỢC NÊU TÊN RIÊNG BIỆT: Nếu người dùng liệt kê/nêu tên RIÊNG BIỆT từ 2 chỉ số cụ thể trở lên (vd "cả tốc độ trung bình và số lần vi phạm"), BẮT BUỘC đưa CẢ 2 vào `measures`, TUYỆT ĐỐI KHÔNG bỏ rơi chỉ số nào được hỏi tên rõ ràng. Rule này KHÔNG áp dụng khi câu hỏi chỉ dùng 1 từ/cụm từ chủ đề chung chung có thể ánh xạ tới nhiều chỉ số khác nhau — trường hợp đó BẮT BUỘC xử lý theo Nhóm 2 - Dạng B, không được tự đoán hay gộp hết ở đây.
6. QUAN TRỌNG - GRANULARITY: CHỈ gán `"granularity": "hour"` khi câu hỏi CÓ TỪ HỎI RÕ VỀ GIỜ (như 'mấy giờ', 'lúc mấy giờ', 'khung giờ nào', 'giờ cao điểm', 'vào giờ nào', 'theo từng giờ'). Khi câu hỏi hỏi tổng thể theo ngày/tuần/tháng (như 'hôm 25/7', 'ngày 25/7', 'tháng 7', 'tuần qua') MÀ KHÔNG hỏi mốc giờ, TUYỆT ĐỐI KHÔNG gán `granularity` (để `granularity` rỗng hoặc null) để hệ thống tính tổng tích lũy cho cả khoảng thời gian đó.
7. QUAN TRỌNG - TRÍCH XUẤT DIMENSION KHI HỎI ĐỐI TƯỢNG (ENTITY QUESTION DIMENSIONS): Khi câu hỏi dạng 'X nào' (như 'đèn nào', 'cột đèn nào', 'camera nào', 'khu vực nào', 'sự cố nào'), bạn BẮT BUỘC phải đưa chiều định danh đối tượng tương ứng (như `smart_lighting.pole_id`, `traffic_flow.camera_id`, `section_id`) vào danh sách `dimensions` để hệ thống gom nhóm theo từng đối tượng.
8. QUAN TRỌNG - XỬ LÝ THỜI GIAN: Lọc thời gian BẮT BUỘC sử dụng `timeDimensions` (vd: `air_quality.recorded_at`, `traffic_flow.recorded_at`, `city_health_index.date`, `smart_parking.recorded_at`, `smart_lighting.recorded_at`, `street_incidents.timestamp_start`). Nếu câu hỏi HIỆN TẠI không nêu mốc thời gian: (a) nếu phía trên có lịch sử hội thoại và một lượt TRƯỚC đã nêu rõ khung thời gian, và câu hỏi hiện tại không phủ định hay đổi sang mốc khác, BẮT BUỘC giữ nguyên khung thời gian đó trong `timeDimensions` — khối `<runtime_context>` chỉ cho biết ngày giờ hiện tại thực để diễn giải cụm từ tương đối MỚI (như "hôm nay"), KHÔNG phải tín hiệu để reset ngữ cảnh hội thoại đã có; (b) nếu đây là lượt hỏi đầu tiên hoặc chưa có khung thời gian nào được nêu trước đó, để `timeDimensions` rỗng, hệ thống sẽ tự áp dụng thời gian mặc định.
9. Giữ nguyên tên giá trị bộ lọc như người dùng viết; hệ thống tự động ánh xạ các tên gọi phân khu (`Khu biet thu`, `Can ho`, `TTTM`).
10. QUAN TRỌNG - SẮP XẾP HẠNG TOP/PEAK: Khi câu hỏi có từ so sánh nhất (như 'nhiều nhất', 'cao nhất', 'lớn nhất', 'ít nhất', 'thấp nhất', 'đông nhất'), bạn BẮT BUỘC phải gán `order` theo measure đó (`"direction": "desc"` hoặc `"asc"`) và gán `"limit": 1` (hoặc top N tương ứng).
11. QUAN TRỌNG - DIMENSION TỰ TRẢ LỜI ĐƯỢC CÂU HỎI (KHÔNG CẦN MEASURES): Nếu câu hỏi chỉ cần giá trị của 1 dimension — dù là dimension ĐỊNH DANH (đếm/liệt kê, vd "có bao nhiêu khu vực trong smartcity", "liệt kê các khu vực") hay dimension SỐ mô tả 1 thuộc tính có sẵn của đối tượng (vd "tổng số chỗ đỗ xe thiết kế quy hoạch của khu X là bao nhiêu" → dùng thẳng `districts.total_parking_slots`) — và KHÔNG cần tính toán/tổng hợp gì thêm, bạn ĐƯỢC PHÉP để `measures` rỗng và chỉ điền `dimensions` tương ứng, miễn chọn đúng cube chứa dimension đó. TUYỆT ĐỐI KHÔNG từ chối trả lời hay hỏi lại chỉ vì không tìm được measure phù hợp trong trường hợp này, và TUYỆT ĐỐI KHÔNG cố tìm 1 measure có tên gần giống để thay cho dimension đúng.
12. QUAN TRỌNG - PHÂN BIỆT FILTER VÀ DIMENSION KHI CÂU HỎI ĐỀ CẬP THỰC THỂ CỤ THỂ (Entity Context Rule): Khi câu hỏi đề cập đến tên khu vực, thiết bị, hoặc đối tượng cụ thể (như "khu căn hộ", "khu biệt thự", "TTTM", "cột đèn P-001"), bạn PHẢI xác định đúng ngữ cảnh câu hỏi để quyết định dùng `filters` hay `dimensions`:
   - **Dạng A – Hỏi đơn lẻ (Single Entity):** Câu hỏi CHỈ hỏi về 1 thực thể duy nhất, KHÔNG yêu cầu so sánh hay phân rã (vd: "AQI ở khu căn hộ hôm nay thế nào?"). BẮT BUỘC đưa thực thể vào `filters` (operator: "equals"), KHÔNG đưa vào `dimensions`. Ví dụ: `filters: [{member: "air_quality.section_id", operator: "equals", values: ["khu căn hộ"]}]`.
   - **Dạng B – So sánh không gian (Comparison):** Câu hỏi yêu cầu so sánh giữa nhiều khu vực/đối tượng (vd: "So sánh AQI các khu vực", "khu nào có AQI cao nhất?"). BẮT BUỘC đưa chiều thực thể vào `dimensions` để GROUP BY, KHÔNG filter duy nhất 1 khu vực.
   - **Dạng C – Phân rã chi tiết (Drill-down):** Câu hỏi hỏi về 1 khu vực cụ thể VÀ muốn xem chi tiết theo từng đối tượng nhỏ hơn bên trong (vd: "Đèn hỏng theo từng cột ở khu căn hộ"). VẪN đưa khu vực vào `filters` (operator: "equals") ĐỒNG THỜI đưa chiều đối tượng con (như `pole_id`) vào `dimensions`.
   - **Dạng D – Loại trừ (Exclusion):** Câu hỏi loại trừ một thực thể (vd: "AQI các khu vực ngoại trừ căn hộ"). Dùng `filters` với operator "notEquals", đưa chiều còn lại vào `dimensions`.
   - **Dạng E – So sánh thời gian trong cùng 1 thực thể (Temporal Comparison):** Câu hỏi hỏi về 1 khu vực cụ thể nhưng so sánh theo thời gian (vd: "AQI khu căn hộ ngày 26/7 cao hay thấp hơn ngày 25/7?"). Đưa khu vực vào `filters` (equals), đặt dateRange bao gồm cả 2 mốc thời gian và gán `granularity: "day"`.
13. QUAN TRỌNG - ƯU TIÊN CUBE DANH MỤC/THAM CHIẾU GỐC: Trong Catalog bên dưới, cube được đánh dấu `[DANH MỤC/THAM CHIẾU GỐC]` (vd `districts`) là nguồn đầy đủ và đáng tin cậy nhất cho chính đối tượng đó — kể cả khi cube này CÓ measures riêng (như đếm số bản ghi danh mục), điều đó KHÔNG làm mất tính tham chiếu của nó. Nếu câu hỏi chỉ hỏi về danh sách/số lượng/thuộc tính của MỘT LOẠI ĐỐI TƯỢNG nói chung (như khu vực, quận, loại thiết bị...) mà KHÔNG gắn với 1 domain nghiệp vụ cụ thể nào (không khí, giao thông, đỗ xe, chiếu sáng, sự cố, chỉ số đáng sống...), bạn BẮT BUỘC ưu tiên dùng dimension từ cube tham chiếu đó, TUYỆT ĐỐI KHÔNG mượn dimension cùng tên/cùng ý nghĩa (như `section_id`) từ một cube nghiệp vụ khác (cube CÓ measures) — cột đó chỉ phản ánh những gì ĐÃ CÓ dữ liệu ghi nhận trong domain đó, có thể thiếu so với danh mục đầy đủ. Chỉ dùng dimension của cube nghiệp vụ khi câu hỏi rõ ràng gắn với domain đó (vd "khu vực nào có AQI cao nhất").
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

        ref_tag = " [DANH MỤC/THAM CHIẾU GỐC]" if c.is_reference else ""
        lines.append(f"\n## Cube `{c.name}` ({c.title}){ref_tag}:")
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
    catalog: Catalog,
    candidates: dict[str, list[str]] | None,
    max_suggestions: int = 3,
    field_ambiguity: dict[str, Any] | None = None,
) -> list[str]:
    """Suy ra 1-3 gợi ý ngắn gọn (tiếng Việt) từ RAG candidates, dùng làm
    quick-reply chip ở FE khi status=CLARIFICATION.

    Cố ý KHÔNG parse text câu hỏi làm rõ mà LLM sinh ra (dễ vỡ, phụ thuộc cách
    model diễn đạt) — suy trực tiếp từ `candidates`/`field_ambiguity`, cùng
    nguồn dữ liệu mà `build_system_prompt()` đã dùng để dựng catalog cho lượt
    gọi đó, nên luôn nhất quán với những gì model đang "nhìn thấy".

    2 dạng mơ hồ cần 2 loại gợi ý khác nhau (xem
    docs/04-ambiguous-question-handling.md case D vs case M/N):
    - Mơ hồ GIỮA nhiều cube (không rõ nên dùng cube nào) -> gợi ý tên cube.
    - Mơ hồ TRONG 1 cube (rõ chủ đề, nhiều field độc lập, vd "hiệu suất")
      -> gợi ý TÊN FIELD cụ thể, không phải tên cube.
    """
    if field_ambiguity and field_ambiguity.get("candidates"):
        # Tín hiệu `field_ambiguity` (retriever, hẹp + tất định) — ưu tiên
        # dùng thẳng thay vì suy qua `len(cube_names) == 1`: điều kiện đó
        # THỰC TẾ GẦN NHƯ KHÔNG BAO GIỜ đúng trong production vì
        # `candidates["cubes"]` luôn có ≥3-4 phần tử (top_k_cubes=3 + cube
        # tham chiếu) — xem kế hoạch fix Yellow case root cause #2.
        suggestions = [title for _, title in field_ambiguity["candidates"][:max_suggestions]]
        if suggestions:
            return suggestions

    if not candidates:
        return []

    cube_names = candidates.get("cubes", [])
    measure_names = candidates.get("measures", [])

    suggestions = []
    for cube_name in cube_names[:max_suggestions]:
        cube = catalog.cube(cube_name)
        if cube:
            suggestions.append(cube.title)

    if not suggestions:
        for m_name in measure_names[:max_suggestions]:
            m = catalog.get_measure(m_name)
            if m:
                suggestions.append(m.title)

    return suggestions[:max_suggestions]


def build_field_ambiguity_hint(field_ambiguity: dict[str, Any] | None) -> str:
    """Sinh hint TIÊM VÀO lượt hỏi hiện tại (không sửa `_RULES` tĩnh) khi
    `retriever._field_ambiguity()` phát hiện tín hiệu mơ hồ cấp-field cho
    ĐÚNG câu hỏi này. Cụ thể-theo-câu-hỏi hơn hẳn rule tĩnh chung chung — bổ
    trợ Nhóm 2 Dạng B/Rule 5 đã có trong `_RULES`, không lặp lại nội dung.
    Trả `""` nếu không có tín hiệu (không tiêm gì thêm).

    Cố ý CHỈ là hint, KHÔNG hard-block quyết định của LLM — bài học case E
    (docs/04-ambiguous-question-handling.md): 1 threshold liên tục chưa
    calibrate đủ kỹ không nên tự động chặn cứng, để LLM đọc toàn bộ ngữ cảnh
    câu hỏi rồi tự quyết định cuối cùng.

    Câu cấm dùng `refuse_request` ở cuối là fix phát hiện qua benchmark thật
    (Bước 7): không có câu này, model có xu hướng đọc "không chắc field nào"
    thành "external_data_unavailable" rồi gọi `refuse_request` (dù nội dung
    message vẫn liệt kê đúng các field ứng viên) thay vì hỏi lại bằng text
    thường — cùng lỗi mẫu hình đã thấy ở Y06 (repair-loop), nhưng xảy ra
    ngay từ lượt đầu tiên nên không đi qua repair-loop escape hatch trong
    `orchestrator.py`. Verify: Y02/Y04/Y09 dao động 0/3-3/3 `clarification`
    giữa các lần chạy giống hệt nhau (temperature=0 nhưng không tuyệt đối
    determinstic) trước khi thêm câu cấm này.
    """
    if not field_ambiguity or not field_ambiguity.get("candidates"):
        return ""
    names = [f"`{name}` ({title})" for name, title in field_ambiguity["candidates"]]
    return (
        "<field_ambiguity_hint>\n"
        f"Câu hỏi này có thể khớp mơ hồ giữa các field sau của cube `{field_ambiguity['cube']}`: "
        f"{', '.join(names)}. Nếu không chắc người dùng muốn CHÍNH XÁC field nào, áp dụng Nhóm 2 - "
        "Dạng B (hỏi lại trắc nghiệm giữa các lựa chọn trên), KHÔNG tự chọn 1 hay gộp hết — TRỪ KHI "
        "câu hỏi đã nêu tên riêng biệt rõ ràng ≥2 field cụ thể trong số này (khi đó áp dụng Rule 5, "
        "đưa cả 2 vào `measures`). Đây LUÔN là tình huống hỏi lại làm rõ (Nhóm 2), KHÔNG PHẢI trường "
        "hợp từ chối — TUYỆT ĐỐI KHÔNG gọi tool `refuse_request` (kể cả với lý do "
        "external_data_unavailable) chỉ vì không chắc field nào trong số này, hãy trả lời bằng TEXT "
        "THƯỜNG để hỏi lại.\n"
        "</field_ambiguity_hint>"
    )


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
