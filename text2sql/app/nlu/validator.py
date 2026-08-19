"""Lightweight Validator — bắt lỗi mà enum trong tool schema không bắt được.

Phạm vi cố ý thu hẹp so với thiết kế tự viết semantic engine trước đây (xem
docs/02-cube-architecture.md mục 2, box "Lightweight Validator"). Những ràng
buộc sâu hơn — measure/dimension có join hợp lệ với nhau không, có đúng cube
schema không — được CHỦ Ý để Cube Core tự phát hiện lúc thực thi (nhánh "lỗi
runtime" trong diagram, xem app/query_engine/cube_client.py). Validator ở đây
không lặp lại logic đó, chỉ bắt:

  - field (measure/dimension/timeDimension) có tồn tại trong catalog không,
  - `order` trỏ tới field đã chọn không,
  - `limit` có vượt guardrail không,
  - giá trị filter LLM viết ra có khớp giá trị thật trong DB không (fuzzy-match).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any

from app.catalog.models import Catalog
from app.catalog.sample_values import SampleValues
from app.config import Settings, settings as default_settings
from app.nlu.types import RELATIVE_DATE_RANGES, TIME_GRAINS, CubeQuery, CubeTimeDimension


@dataclass
class ValidationResult:
    ok: bool
    query: CubeQuery | None = None
    errors: list[str] = field(default_factory=list)
    # Thông tin cần hiển thị cho người dùng (ví dụ: đã áp mặc định gì, đã sửa giá trị gì).
    notes: list[str] = field(default_factory=list)


class QueryValidator:
    def __init__(
        self,
        catalog: Catalog,
        sample_values: SampleValues | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.catalog = catalog
        self.sample_values = sample_values or SampleValues({})
        self.settings = settings or default_settings

    # ------------------------------------------------------------------ public

    def validate(
        self,
        raw: dict[str, Any],
        prior_query: CubeQuery | dict[str, Any] | None = None,
    ) -> ValidationResult:
        """`prior_query` (Bug 2, kế hoạch fix Phase 2): `CubeQuery` (hoặc dict
        tương đương) của lần QUERY thành công gần nhất trong session — dùng
        làm nguồn dự phòng tất định cho `timeDimensions` khi lượt hiện tại bỏ
        trống, thay vì chỉ trông chờ prompt Rule 8(a) (Phase 1) khiến model tự
        nhớ lại mốc thời gian lượt trước (benchmark thực tế cho thấy vẫn
        không đủ ổn định — xem README.md Y01/Y03)."""
        errors: list[str] = []
        notes: list[str] = []

        try:
            query = CubeQuery.model_validate(raw)
        except Exception as exc:  # pydantic ValidationError
            return ValidationResult(ok=False, errors=[f"Tham số tool không đúng cấu trúc: {exc}"])

        prior: CubeQuery | None = None
        if prior_query is not None:
            try:
                prior = (
                    prior_query
                    if isinstance(prior_query, CubeQuery)
                    else CubeQuery.model_validate(prior_query)
                )
            except Exception:
                prior = None  # prior_query hỏng/lỗi thời -> bỏ qua êm, không chặn lượt hiện tại

        self._validate_measures(query, errors)
        self._validate_dimensions(query, errors, notes)
        self._validate_filters(query, errors, notes)
        self._validate_time_dimensions(query, errors, notes, prior_query=prior)
        self._validate_order(query, errors)
        self._validate_limit(query, errors, notes)

        if errors:
            return ValidationResult(ok=False, errors=errors, notes=notes)
        return ValidationResult(ok=True, query=query, notes=notes)

    # ----------------------------------------------------------------- private

    def _validate_measures(self, query: CubeQuery, errors: list[str]) -> None:
        names = self.catalog.measure_names()
        for m in query.measures:
            if self.catalog.get_measure(m) is None:
                errors.append(f"Measure '{m}' không tồn tại. {self._suggest(m, names)}")

    @staticmethod
    def _target_cube(query: CubeQuery) -> str | None:
        """Cube "chốt" của cả query — mọi measure/dimension/filter khác phải
        cùng cube này. Ưu tiên suy từ measures[0]; nếu measures rỗng (query
        dimension-only, vd đếm/liệt kê `districts` vốn không có measure nào —
        xem docs/04-ambiguous-question-handling.md) thì suy từ dimensions[0]
        thay thế. `CubeQuery` đã đảm bảo ít nhất 1 trong 2 không rỗng (xem
        `_require_measures_or_dimensions` trong types.py)."""
        if query.measures:
            return query.measures[0].split(".")[0]
        if query.dimensions:
            return query.dimensions[0].split(".")[0]
        return None

    def _validate_dimensions(self, query: CubeQuery, errors: list[str], notes: list[str]) -> None:
        names = set(self.catalog.dimension_names())
        target_cube = self._target_cube(query)

        valid_dims = []
        for d in query.dimensions:
            if target_cube and not d.startswith(target_cube + "."):
                errors.append(
                    f"Dimension '{d}' thuộc Cube khác với '{target_cube}'. Mọi chỉ số, chiều và bộ lọc phải thuộc cùng 1 Cube. Hãy chọn `{target_cube}.{d.split('.')[-1]}` nếu phù hợp."
                )
            elif d not in names:
                errors.append(f"Dimension '{d}' không tồn tại. {self._suggest(d, sorted(names))}")
            else:
                valid_dims.append(d)
        query.dimensions = valid_dims

    def _validate_filters(self, query: CubeQuery, errors: list[str], notes: list[str]) -> None:
        dim_names = set(self.catalog.dimension_names())
        measure_names = set(self.catalog.measure_names())
        all_member_names = dim_names | measure_names
        time_dim_names = set(self.catalog.time_dimension_names())
        target_cube = self._target_cube(query)

        valid_filters = []
        for f in query.filters:
            if f.member in time_dim_names:
                errors.append(
                    f"'{f.member}' là cột thời gian — hãy dùng tham số `timeDimensions` "
                    "thay vì đưa vào `filters`."
                )
                continue

            # Strict Intent Validation: Báo lỗi lệch Cube đẩy về Repair Loop để LLM tự sửa thay vì silent mutate
            if target_cube and not f.member.startswith(target_cube + "."):
                errors.append(
                    f"Filter member '{f.member}' thuộc Cube khác với '{target_cube}'. Mọi chỉ số, chiều và bộ lọc trong 1 truy vấn BẮT BUỘC phải thuộc về CÙNG một Cube. Hãy dùng `{target_cube}.{f.member.split('.')[-1]}` nếu lọc theo chiều tương ứng."
                )
                continue

            # Auto-correct: Nếu filter gọi phép toán số (lt, gt, lte, gte) với con số trên cột Enum -> chuyển sang cột Measure số
            if f.operator in ("lt", "lte", "gt", "gte") and f.values and (f.values[0].replace(".", "", 1).isdigit()):
                prefix = f.member.split(".")[0]
                for m in query.measures:
                    if m.startswith(prefix):
                        notes.append(f"Đã tự động chuyển filter từ '{f.member}' sang measure số '{m}' cho phép toán '{f.operator}'.")
                        f.member = m
                        break

            if f.member not in all_member_names:
                errors.append(
                    f"Filter member '{f.member}' không tồn tại. "
                    f"{self._suggest(f.member, sorted(all_member_names))}"
                )
                continue
            valid_filters.append(f)
            self._resolve_filter_values(f, errors, notes)
        query.filters = valid_filters

    def _resolve_filter_values(self, f: Any, errors: list[str], notes: list[str]) -> None:
        """Đối chiếu giá trị filter với Alias Map hoặc sample_values.yaml.

        Nếu `resolve()` báo giá trị mơ hồ (≥2 candidate gần giống nhau,
        không đủ tin cậy để tự đoán — HOẶC không khớp candidate nào cả trong
        domain hữu hạn đã biết, vd tên khu vực không tồn tại) -> đẩy thành
        lỗi validation, chảy vào repair loop có sẵn ở orchestrator.py (model
        được yêu cầu gọi lại tool với tham số đã sửa) thay vì âm thầm chọn 1
        giá trị có thể sai hoặc âm thầm chấp nhận giá trị không tồn tại. Xem
        docs/04-ambiguous-question-handling.md case G / FIX-04.
        """
        resolved: list[str] = []
        for value in f.values:
            new_value, changed, ambiguous = self.sample_values.resolve(f.member, value)
            if ambiguous:
                errors.append(
                    f"Giá trị '{value}' của '{f.member}' không xác định được chính xác trong hệ "
                    f"thống (giá trị hợp lệ: {', '.join(ambiguous)}) — không đủ tin cậy để tự chọn. "
                    "Hãy nêu rõ giá trị bạn muốn lọc."
                )
                resolved.append(value)
                continue
            if changed:
                notes.append(f"Đã hiểu giá trị '{value}' của '{f.member}' là '{new_value}'.")
            resolved.append(new_value)
        f.values = resolved

    def _validate_time_dimensions(
        self,
        query: CubeQuery,
        errors: list[str],
        notes: list[str],
        prior_query: CubeQuery | None = None,
    ) -> None:
        names = set(self.catalog.time_dimension_names())
        target_cube = self._target_cube(query)

        for td in query.timeDimensions:
            # LƯU Ý (phát hiện trong lúc làm Bug 2, chưa fix — ngoài phạm vi):
            # dòng dưới đây thu gọn dateRange dạng list [start, end] (định
            # dạng hợp lệ của Cube REST API) về CHỈ phần tử đầu tiên, âm thầm
            # bỏ mất ngày kết thúc. Hiếm khi lộ ra vì GPT-4o-mini thường trả
            # range dạng chuỗi đơn "start/end" (xem ví dụ thật trong
            # tools/G06...) thay vì mảng 2 phần tử — nhưng nếu model trả đúng
            # dạng mảng, câu hỏi "tuần 21-28/7" có thể âm thầm chỉ còn tính
            # đúng 1 ngày. Không sửa ở đây để tránh phạm vi ngoài Bug 2.
            if isinstance(td.dateRange, list):
                td.dateRange = td.dateRange[0] if td.dateRange else None

            # Tự động đồng bộ timeDimension nếu LLM nhét nhầm timeDimension của Cube khác
            if target_cube and td.dimension.split(".")[0] != target_cube:
                correct_dim = self._single_time_dimension_for(target_cube)
                if correct_dim:
                    notes.append(f"Đã tự động sửa timeDimension từ '{td.dimension}' sang '{correct_dim}' để khớp với Cube '{target_cube}'.")
                    td.dimension = correct_dim

            if td.dimension not in names:
                errors.append(
                    f"Time dimension '{td.dimension}' không tồn tại. "
                    f"{self._suggest(td.dimension, sorted(names))}"
                )
                continue
            if isinstance(td.dateRange, str) and td.dateRange not in RELATIVE_DATE_RANGES:
                notes.append(
                    f"dateRange '{td.dateRange}' không phải chuỗi chuẩn — Cube Core sẽ cố parse."
                )
            if td.granularity is not None and td.granularity not in TIME_GRAINS:
                errors.append(
                    f"granularity '{td.granularity}' không hợp lệ. "
                    f"Các giá trị cho phép: {', '.join(TIME_GRAINS)}."
                )

        # Chỉ auto-add default time dimension cho query CÓ measures — query
        # dimension-only (vd đếm/liệt kê `districts`, vốn không có time
        # dimension) không cần mốc thời gian mặc định; cố ý không mở rộng
        # hành vi này ra ngoài phạm vi đã có để tránh áp đặt time filter
        # không cần thiết lên câu hỏi kiểu "liệt kê X".
        if not query.timeDimensions and query.measures and target_cube:
            default_dim = self._single_time_dimension_for(target_cube)
            if default_dim is not None:
                # Bug 2: ưu tiên carry-forward timeDimension của lượt TRƯỚC
                # trong cùng session nếu nó thuộc CÙNG cube — tín hiệu tất
                # định, không phụ thuộc model có tự nhớ nhắc lại mốc thời gian
                # hay không (xem docstring `validate()`). Chỉ áp dụng khi
                # cùng cube: timeDimension của cube khác không có ý nghĩa gì
                # với câu hỏi hiện tại.
                prior_td = next(
                    (
                        td
                        for td in (prior_query.timeDimensions if prior_query else [])
                        if td.dimension == default_dim
                    ),
                    None,
                )
                if prior_td is not None:
                    query.timeDimensions = [
                        CubeTimeDimension(
                            dimension=default_dim,
                            dateRange=prior_td.dateRange,
                            granularity=prior_td.granularity,
                        )
                    ]
                    notes.append(
                        f"Câu hỏi không nêu mốc thời gian nên hệ thống giữ nguyên khung thời gian "
                        f"của lượt hỏi trước: {prior_td.dateRange}."
                    )
                else:
                    query.timeDimensions = [
                        CubeTimeDimension(dimension=default_dim, dateRange=self.settings.default_relative_period)
                    ]
                    notes.append(
                        f"Câu hỏi không nêu mốc thời gian nên hệ thống áp mặc định: "
                        f"{self.settings.default_relative_period}."
                    )
        elif query.timeDimensions and target_cube and prior_query:
            # Bug 2 (mở rộng sau khi verify qua UI thật): trên thực tế model
            # KHÔNG luôn để `timeDimensions` rỗng như Rule 8(b) kỳ vọng — nó
            # thường TỰ ĐIỀN đúng giá trị mặc định toàn cục
            # (`settings.default_relative_period`, vd "last 30 days") thay vì
            # để trống cho hệ thống áp — bỏ qua hoàn toàn nhánh carry-forward
            # ở trên (nhánh đó chỉ chạy khi `timeDimensions` rỗng). Coi
            # trường hợp model tự điền ĐÚNG BẰNG giá trị mặc định toàn cục là
            # tín hiệu "model không thực sự biết mốc thời gian" (trùng khớp
            # tuyệt đối với default là đáng ngờ) — vẫn ưu tiên carry-forward
            # nếu prior_query có giá trị khác, cụ thể hơn cho cùng dimension.
            default_dim = self._single_time_dimension_for(target_cube)
            for td in query.timeDimensions:
                if td.dimension != default_dim:
                    continue
                if td.dateRange != self.settings.default_relative_period:
                    continue  # model đưa giá trị cụ thể khác mặc định -> tôn trọng, không ghi đè
                prior_td = next((p for p in prior_query.timeDimensions if p.dimension == td.dimension), None)
                if prior_td is not None and prior_td.dateRange != td.dateRange:
                    td.dateRange = prior_td.dateRange
                    td.granularity = prior_td.granularity
                    notes.append(
                        f"Câu hỏi không nêu mốc thời gian nên hệ thống giữ nguyên khung thời gian "
                        f"của lượt hỏi trước: {prior_td.dateRange} (thay vì mặc định '{self.settings.default_relative_period}' "
                        f"model tự điền)."
                    )

    def _single_time_dimension_for(self, cube_name: str) -> str | None:
        """Tự suy ra time dimension mặc định của Cube."""
        cube = self.catalog.cube(cube_name)
        if cube is None or not cube.time_dimensions:
            return None
        return cube.time_dimensions[0].name

    def _validate_order(self, query: CubeQuery, errors: list[str]) -> None:
        selectable = set(query.measures) | set(query.dimensions)
        for o in query.order:
            if o.field not in selectable:
                errors.append(
                    f"order trỏ tới '{o.field}' nhưng field này không có trong "
                    f"measures/dimensions đã chọn ({', '.join(sorted(selectable))})."
                )

    def _validate_limit(self, query: CubeQuery, errors: list[str], notes: list[str]) -> None:
        if query.limit is None:
            return
        if query.limit < 1:
            errors.append("limit phải là số nguyên dương.")
        elif query.limit > self.settings.max_row_limit:
            notes.append(
                f"limit {query.limit} vượt giới hạn hệ thống, đã giảm về {self.settings.max_row_limit}."
            )
            query.limit = self.settings.max_row_limit

    @staticmethod
    def _suggest(value: str, candidates: list[str]) -> str:
        match = difflib.get_close_matches(value, candidates, n=3, cutoff=0.5)
        if not match:
            return f"Các lựa chọn hợp lệ: {', '.join(candidates[:8])}..."
        return f"Có phải bạn muốn: {', '.join(match)}?"
