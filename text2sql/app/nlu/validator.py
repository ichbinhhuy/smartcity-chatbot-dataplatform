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

    def validate(self, raw: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        notes: list[str] = []

        try:
            query = CubeQuery.model_validate(raw)
        except Exception as exc:  # pydantic ValidationError
            return ValidationResult(ok=False, errors=[f"Tham số tool không đúng cấu trúc: {exc}"])

        self._validate_measures(query, errors)
        self._validate_dimensions(query, errors, notes)
        self._validate_filters(query, errors, notes)
        self._validate_time_dimensions(query, errors, notes)
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

    def _validate_dimensions(self, query: CubeQuery, errors: list[str], notes: list[str]) -> None:
        names = set(self.catalog.dimension_names())
        target_cube = query.measures[0].split(".")[0] if query.measures else None

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
        target_cube = query.measures[0].split(".")[0] if query.measures else None

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
            self._resolve_filter_values(f, notes)
        query.filters = valid_filters

    def _resolve_filter_values(self, f: Any, notes: list[str]) -> None:
        """Đối chiếu giá trị filter với Alias Map hoặc sample_values.yaml."""
        resolved: list[str] = []
        for value in f.values:
            new_value, changed = self.sample_values.resolve(f.member, value)
            if changed:
                notes.append(f"Đã hiểu giá trị '{value}' của '{f.member}' là '{new_value}'.")
            resolved.append(new_value)
        f.values = resolved

    def _validate_time_dimensions(
        self, query: CubeQuery, errors: list[str], notes: list[str]
    ) -> None:
        names = set(self.catalog.time_dimension_names())
        target_cube = query.measures[0].split(".")[0] if query.measures else None

        for td in query.timeDimensions:
            if isinstance(td.dateRange, list):
                td.dateRange = td.dateRange[0] if td.dateRange else None
            
            # Tự động đồng bộ timeDimension nếu LLM nhét nhầm timeDimension của Cube khác
            if target_cube and td.dimension.split(".")[0] != target_cube:
                correct_dim = self._single_time_dimension_for(query.measures[0])
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

        if not query.timeDimensions and query.measures:
            default_dim = self._single_time_dimension_for(query.measures[0])
            if default_dim is not None:
                query.timeDimensions = [
                    CubeTimeDimension(dimension=default_dim, dateRange=self.settings.default_relative_period)
                ]
                notes.append(
                    f"Câu hỏi không nêu mốc thời gian nên hệ thống áp mặc định: "
                    f"{self.settings.default_relative_period}."
                )

    def _single_time_dimension_for(self, measure_name: str) -> str | None:
        """Tự suy ra time dimension mặc định của Cube."""
        cube_name = measure_name.split(".", 1)[0]
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
