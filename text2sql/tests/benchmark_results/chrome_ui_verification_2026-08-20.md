# Verify 30 case qua Claude in Chrome (UI thật, không qua script API) — 2026-08-20

> Tiếp nối [yellow_case_fix_2026-08-20.md](yellow_case_fix_2026-08-20.md) (10/10 Yellow pass qua API).
> Đợt này verify lại **cả 30 case** qua **UI thật** (không phải script gọi thẳng `/api/chat`) —
> đúng nguyên tắc đã có trong dự án: *"cả case E và Y06 gốc đều chỉ lộ ra khi test tay qua UI
> thật, không phải chỉ qua script"*. Dữ liệu chi tiết:
> [chrome_ui_verification_2026-08-20_raw.json](chrome_ui_verification_2026-08-20_raw.json).

**Phương pháp:** dùng Claude in Chrome điều khiển trình duyệt thật, gọi `sendPrompt()` (đúng hàm JS
mà nút gợi ý câu hỏi nhanh trên UI gọi — đi qua nguyên vẹn `fetch('/api/chat/stream')` + render SSE
thật, không bypass), đọc kết quả qua DOM (`className`/`.msg-bubble`/`.json-content` của message bot
cuối cùng). Mỗi case độc lập dùng 1 session mới (reload trang trước mỗi case); 3 case multi-turn
(Y01/Y02/Y03) giữ nguyên session giữa T1 và T2.

## Tóm tắt

| Nhóm | Kết quả |
|---|---|
| **Yellow (10)** | **10/10 T1 `clarification` đúng** — không đổi so với kết quả API. Phát hiện **MỚI**: 2/3 case multi-turn (Y02, Y03) T2 **mất ngữ cảnh** từ T1 |
| **Green (15)** | **12/15 PASS sạch** — G07, G12 tái hiện đúng 2 residual đã biết (không phải lỗi mới); G11 vẫn benign `clarification` |
| **Red (5)** | **4/5 PASS** — R02 tái hiện đúng pattern không tất định đã biết (không phải regression mới) |

Không có regression MỚI nào so với kết quả benchmark API gần nhất, **ngoại trừ 1 phát hiện quan
trọng ở Yellow multi-turn** (xem bên dưới).

---

## ⚠️ Phát hiện mới — Y02/Y03 T2 mất ngữ cảnh (context carry-forward)

Test qua UI thật lộ ra điều script benchmark API trước đó **không phát hiện** (vì các lần benchmark
API gần đây chỉ test Yellow single-turn, không re-test đủ cả 3 case multi-turn cùng lúc trong 1
đợt):

| Case | T2 hỏi | Kỳ vọng giữ từ T1 | Thực tế |
|---|---|---|---|
| **Y01** | "Xem điểm thành phần giao thông" | `section_id=Can ho` + `dateRange=21-28/7` | ✅ **Giữ đúng cả 2** |
| **Y02** | "Nồng độ bụi mịn PM2.5 trung bình" | `section_id=TTTM` + `dateRange=27/7` | ❌ **Mất cả 2** — về `last 30 days`, không filter khu vực. Verify lại 2/2 lần giống hệt nhau (không phải flaky) |
| **Y03** | "Thời gian xử lý trung bình của sự cố công trình" | `section_id=TTTM` + `dateRange=28/7` | ⚠️ **Mất cả 2** — `incident_type=road_work` đúng (chữ thường, Bug 6) nhưng dateRange về `last 30 days`, không filter khu vực |

**So với lịch sử đã ghi trong README.md:**
- Y02 T2 từng được xác nhận **"hoạt động đúng"** (giữ cả district lẫn date) ở lần reverify
  2026-08-19 — **giờ regression**.
- Y03 T2's `dateRange` từng được xác nhận **đã fix** (Bug 2, giữ đúng `2026-07-28`) ở cùng lần
  reverify đó — **giờ cũng mất lại**, dù `incident_type` (Bug 6) vẫn đúng.
- Y01 vẫn là case duy nhất giữ context đầy đủ, nhất quán với mọi lần verify trước.

Đây là phát hiện qua UI thật, **chưa điều tra root cause** — nằm ngoài phạm vi yêu cầu "test lại 30
case" của đợt này. Cần quyết định riêng có nên điều tra tiếp `_resolve_prior_query`/
`_persist_prior_query`/validator carry-forward logic hay không.

---

## Green — 2 residual đã biết, tái hiện đúng (không phải lỗi mới)

- **G07** ("...số lần vi phạm quá tốc độ **và** tỷ lệ kẹt xe...") — chỉ trả `overspeed_count`, bỏ
  sót `congestion_rate` dù được nêu tên rõ. Đã ghi nhận từ Phase 1, không đổi.
- **G12** ("...giữa ngày 22/7 và ngày 26/7 ngày nào cao hơn?") — chỉ query `dateRange:
  "2026-07-22 to 2026-07-22"`, bỏ sót hoàn toàn 26/7. Đã ghi nhận từ Phase 1, không đổi.
- **G11** — vẫn `clarification` (benign, `field_ambiguity` giữa `avg_livability_index`/
  `livability_grade`, câu hỏi không có "trung bình" để tách biệt như G10) — residual đã chấp nhận.

## Red — R02 tái hiện đúng pattern không tất định đã biết

R02 trả `success`, âm thầm bỏ qua toàn bộ phần "so sánh với Sở TN&MT" (không disclose như 1 số lần
chạy trước từng làm) — R02 chưa bao giờ đạt tất định qua các vòng benchmark trước (chỉ R04/R05 có
guardrail tất định). Không phải regression mới.

---

## Kết luận

30/30 case đã verify qua UI thật (Claude in Chrome), khớp với kết quả benchmark API gần nhất ở hầu
hết mọi mặt. **1 phát hiện quan trọng cần theo dõi:** Y02/Y03 T2 (context carry-forward multi-turn)
đã regression so với lần fix Bug 2 (2026-08-19) — cần điều tra riêng nếu muốn xử lý.
