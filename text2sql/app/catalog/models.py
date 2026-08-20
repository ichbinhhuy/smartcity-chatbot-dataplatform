"""Catalog: danh mục measures/dimensions/timeDimensions lấy từ Cube Meta API.

Đây là bản trong bộ nhớ của cube schema — nguồn duy nhất cho tool schema và
system prompt (xem docs/02-cube-architecture.md mục 3). Không viết tay: luôn
được dựng từ `app.catalog.cube_meta.parse_catalog()`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogField:
    name: str  # dạng "cube.field", đúng khớp Cube member format
    title: str
    description: str = ""
    type: str = "string"


@dataclass(frozen=True)
class CatalogCube:
    name: str
    title: str
    measures: list[CatalogField]
    dimensions: list[CatalogField]
    time_dimensions: list[CatalogField]
    # Cube danh mục/tham chiếu gốc (vd `districts`) — xem
    # cube_meta.py::_REFERENCE_CUBE_NAMES (đáng lẽ nên đọc từ field `meta`
    # chuẩn của Cube schema, nhưng Cube.js v0.34.0 không hỗ trợ `meta` ở cấp
    # cube — xem ghi chú tại cube_meta.py). Nhãn tường minh này thay cho
    # heuristic cũ "cube không có measures" — heuristic đó đã chứng minh dễ
    # vỡ khi 1 cube tham chiếu được thêm measure riêng.
    is_reference: bool = False


@dataclass(frozen=True)
class Catalog:
    cubes: list[CatalogCube]

    def cube(self, name: str) -> CatalogCube | None:
        return next((c for c in self.cubes if c.name == name), None)

    def measure_names(self) -> list[str]:
        return [m.name for c in self.cubes for m in c.measures]

    def dimension_names(self) -> list[str]:
        return [d.name for c in self.cubes for d in c.dimensions]

    def time_dimension_names(self) -> list[str]:
        return [t.name for c in self.cubes for t in c.time_dimensions]

    def get_measure(self, name: str) -> CatalogField | None:
        return next((m for c in self.cubes for m in c.measures if m.name == name), None)

    def get_dimension(self, name: str) -> CatalogField | None:
        """Tìm trong cả dimensions thường lẫn time dimensions."""
        for c in self.cubes:
            for d in c.dimensions:
                if d.name == name:
                    return d
            for t in c.time_dimensions:
                if t.name == name:
                    return t
        return None
