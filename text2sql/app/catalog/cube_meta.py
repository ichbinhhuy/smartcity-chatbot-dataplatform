"""Lấy catalog (measures/dimensions/timeDimensions) từ Cube Meta API.

`GET {cube_api_url}/meta` trả về toàn bộ cube schema dưới dạng JSON. Đây là
nguồn duy nhất cho tool schema và system prompt — xem
docs/02-cube-architecture.md mục 3. `parse_catalog()` tách riêng khỏi
`fetch_catalog()` để test được mà không cần Cube Core chạy thật (dùng fixture
JSON, xem tests/fixtures/cube_meta.json).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.catalog.models import Catalog, CatalogCube, CatalogField


class CubeMetaError(RuntimeError):
    """Không lấy được hoặc không đọc được catalog từ Cube Meta API."""


# Cube danh mục/tham chiếu gốc (vd `districts` cho khu vực) — LLM luôn ưu
# tiên dimension của các cube này cho câu hỏi về chính đối tượng, không gắn
# domain cụ thể (xem app/nlu/prompt.py Rule 13). Lẽ ra nên đánh dấu ngay
# trong YAML schema qua field `meta` chuẩn của Cube (single source of
# truth), nhưng Cube.js v0.34.0 đang chạy trong repo này KHÔNG chấp nhận
# `meta` ở cấp cube — thử thêm `meta: {is_reference: true}` vào
# districts.yml làm sập compile TOÀN BỘ schema (lỗi "(meta = [object
# Object]) is not allowed", mọi cube khác báo "doesn't exist" theo). Vì
# vậy tạm dùng constant Python này làm nguồn thay thế — CHẤP NHẬN việc có
# 2 chỗ phải đồng bộ tay (constant này + tên cube thật trong YAML), khác
# với thiết kế gốc, cho tới khi nâng cấp Cube.js lên bản hỗ trợ `meta`.
_REFERENCE_CUBE_NAMES = {"districts"}


def fetch_catalog(base_url: str, token: str | None = None, timeout: float = 10.0) -> Catalog:
    headers = {"Authorization": token} if token else {}
    try:
        response = httpx.get(f"{base_url}/meta", headers=headers, timeout=timeout)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise CubeMetaError(f"Không gọi được Cube Meta API tại {base_url}/meta: {exc}") from exc

    return parse_catalog(response.json())


def parse_catalog(payload: dict[str, Any]) -> Catalog:
    cubes: list[CatalogCube] = []
    for raw_cube in payload.get("cubes", []):
        measures = [_parse_field(m) for m in raw_cube.get("measures", [])]
        dimensions: list[CatalogField] = []
        time_dimensions: list[CatalogField] = []
        for raw_dim in raw_cube.get("dimensions", []):
            parsed = _parse_field(raw_dim)
            if raw_dim.get("type") == "time":
                time_dimensions.append(parsed)
            else:
                dimensions.append(parsed)
        cubes.append(
            CatalogCube(
                name=raw_cube["name"],
                title=raw_cube.get("title", raw_cube["name"]),
                measures=measures,
                dimensions=dimensions,
                time_dimensions=time_dimensions,
                is_reference=raw_cube["name"] in _REFERENCE_CUBE_NAMES,
            )
        )
    return Catalog(cubes=cubes)


def _parse_field(raw: dict[str, Any]) -> CatalogField:
    return CatalogField(
        name=raw["name"],
        title=raw.get("title", raw["name"]),
        description=raw.get("description", ""),
        type=raw.get("type", "string"),
    )


class CatalogSource:
    """Fetch một lần lúc khởi động, cache trong bộ nhớ suốt vòng đời process.

    Tương ứng box "Cube Meta API (fetch 1 lần lúc khởi động, cache toàn bộ
    catalog)" trong diagram ở docs/02-cube-architecture.md mục 2.
    """

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self._base_url = base_url
        self._token = token
        self._catalog: Catalog | None = None

    def get(self, *, force_refresh: bool = False) -> Catalog:
        if self._catalog is None or force_refresh:
            self._catalog = fetch_catalog(self._base_url, self._token)
        return self._catalog
