"""Guardrail TẤT ĐỊNH — chặn 1 số loại yêu cầu nguy hiểm TRƯỚC khi chạm tới
LLM, không phụ thuộc model có tuân thủ prompt hay không.

Bối cảnh (Bug 3, kế hoạch fix Phase 2): tool `refuse_request` +
Nhóm 1 trong `prompt.py` (Phase 1) xử lý được phần lớn case từ chối (Red
case R01-R03) qua LLM, nhưng benchmark thực tế cho thấy R04 (yêu cầu xoá dữ
liệu lồng trong 1 câu hỏi hợp lệ) và R05 (prompt injection + đòi xuất
credentials) không refuse ổn định — LLM đôi khi vẫn thực hiện phần câu hỏi
hợp lệ mà bỏ qua phần nguy hiểm, hoặc bị dẫn dắt bởi chỉ thị chèn vào giữa
câu hỏi. 2 loại này (phá hoại dữ liệu, rò rỉ credential) không nên phó mặc
cho LLM tự phán đoán — cố ý KHÔNG đưa vào enum `reason` của tool
`refuse_request` (xem app/nlu/tool_schema.py), xử lý bằng lớp riêng ở đây.

CHỈ bắt các case rõ ràng, tránh false positive lên câu hỏi domain hợp lệ —
mỗi pattern đều gắn với ý định rõ ràng (ra lệnh sửa/xoá dữ liệu, đòi xuất
secret, hoặc cố ghi đè vai trò/instruction), không phải chỉ 1 từ khoá đơn lẻ
dễ trùng với câu hỏi bình thường.
"""

from __future__ import annotations

import re

# Regex bắt hành động sửa/xoá dữ liệu, viết dạng chỉ thị (ra lệnh) — không
# phải câu hỏi (đọc dữ liệu là hành vi bình thường của toàn bộ hệ thống này,
# nên chỉ bắt động từ mang tính MUTATE: xoá/xóa/drop/delete/truncate/update...
# đi kèm đối tượng "bản ghi"/"dữ liệu"/"record"/"table"/SQL keyword — tránh
# khớp nhầm câu hỏi thuần đọc dữ liệu, kể cả khi có nhắc measure tên gần
# giống, vd không có case nào trong domain này tên là "xoá").
_DESTRUCTIVE_PATTERN = re.compile(
    r"("
    # SQL DDL/DML mang tính phá hoại — tự nó đã đủ nghĩa, không cần noun đi kèm.
    r"drop\s+table|drop\s+database|delete\s+from|truncate\s+table|update\s+.+\s+set"
    r"|"
    # "xóa" (chính tả hiện hành, dấu ở "ó") và "xoá" (chính tả cũ, dấu ở "á")
    # đều rất phổ biến trong thực tế — phải bắt CẢ HAI cách viết. Cần đi kèm
    # 1 noun "đối tượng bị xoá" trong khoảng gần để tránh khớp nhầm câu không
    # liên quan tới dữ liệu (vd "xoá" dùng nghĩa khác).
    r"(?:xóa|xoá)\s*.{0,40}(?:b[ảa]n\s*ghi|d[ữu]\s*li[eệ]u|record|table|c[ơo]\s*s[ơở]\s*d[ữu]\s*li[eệ]u|database)"
    r")",
    re.IGNORECASE,
)

# Regex bắt yêu cầu xuất/tiết lộ credential, secret, connection string —
# tên biến môi trường/khái niệm cấu hình nhạy cảm THẬT của hệ thống này (xem
# app/config.py) cộng động từ đòi xuất/lộ ra.
_CREDENTIAL_PATTERN = re.compile(
    r"(api[_\s]?key|redis_url|openai_api_key|mật\s*khẩu|password|credentials?|connection\s*string|"
    r"secret\s*key|access\s*token|cube_api_token)",
    re.IGNORECASE,
)
_EXFIL_VERB_PATTERN = re.compile(
    r"(xu[ấa]t|tr[íi]ch\s*xu[ấa]t|cho\s*(tôi|toi)\s*xem|l[ộo]|ti[ếe]t\s*l[ộo]|export|reveal|show\s*me)",
    re.IGNORECASE,
)

# Regex bắt prompt injection / cố ghi đè vai trò-quyền hạn của hệ thống —
# cụm từ đặc trưng cho kiểu tấn công "đóng vai admin/không giới hạn" hoặc
# "bỏ qua hướng dẫn trước đó".
_PROMPT_INJECTION_PATTERN = re.compile(
    r"(đóng\s*vai|dong\s*vai|act\s*as|you\s*are\s*now|bỏ\s*qua\s*(mọi\s*)?(hướng\s*dẫn|instructions?)|"
    r"ignore\s*(previous|all)\s*instructions?|quyền\s*truy\s*cập\s*không\s*giới\s*hạn|"
    r"unrestricted\s*access|system\s*prompt|jailbreak)",
    re.IGNORECASE,
)


def check_deterministic_refusal(question: str) -> str | None:
    """Trả về `reason` (khớp `_REFUSAL_REASONS`-style string, KHÔNG trùng
    enum của `refuse_request` — xem docstring module) nếu câu hỏi khớp 1
    pattern nguy hiểm, ngược lại `None`. Kiểm tra càng SỚM càng tốt trong
    `orchestrator.interpret()`, trước khi tốn 1 lượt gọi RAG/LLM nào.
    """
    if not question or not question.strip():
        return None

    if _DESTRUCTIVE_PATTERN.search(question):
        return "destructive_instruction"

    if _PROMPT_INJECTION_PATTERN.search(question):
        return "prompt_injection"

    if _CREDENTIAL_PATTERN.search(question) and _EXFIL_VERB_PATTERN.search(question):
        return "credential_exfiltration"

    return None


_REFUSAL_MESSAGES: dict[str, str] = {
    "destructive_instruction": (
        "Yêu cầu này chứa chỉ thị sửa/xoá dữ liệu — hệ thống chỉ hỗ trợ truy vấn (đọc) dữ liệu, "
        "không thực hiện thao tác thay đổi/xoá dữ liệu qua chat. Nếu bạn cần xem số liệu, vui lòng "
        "hỏi lại chỉ phần truy vấn, không kèm chỉ thị sửa/xoá."
    ),
    "credential_exfiltration": (
        "Yêu cầu này đòi xuất thông tin cấu hình/kết nối/credential hệ thống — đây là thông tin nhạy "
        "cảm, hệ thống không bao giờ trả loại thông tin này qua chat."
    ),
    "prompt_injection": (
        "Yêu cầu này cố gắng thay đổi vai trò hoặc bỏ qua hướng dẫn hệ thống — hệ thống không chấp "
        "nhận chỉ thị ghi đè vai trò/quyền hạn qua chat."
    ),
}


def refusal_message(reason: str) -> str:
    return _REFUSAL_MESSAGES.get(reason, "Yêu cầu nằm ngoài phạm vi hệ thống hỗ trợ.")
