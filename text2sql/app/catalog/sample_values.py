"""Mapping giá trị hiển thị <-> giá trị thật cho dimension — phần Cube không cung cấp.

Cube Meta API trả về *tên* dimension nhưng không trả về giá trị thật có trong
DB (Cube không có khái niệm "giá trị mẫu"). Đây là ngoại lệ có chủ ý với
nguyên tắc một nguồn, phạm vi hẹp — xem docs/02-cube-architecture.md mục 3.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import yaml


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

    def resolve(self, member: str, value: str) -> tuple[str, bool]:
        """Trả về (giá trị đã quy đổi, có thay đổi hay không)."""
        allowed = self._values.get(member)
        if not allowed or value in allowed:
            return value, False
        match = difflib.get_close_matches(value.lower(), allowed, n=1, cutoff=0.6)
        if match:
            return match[0], True
        return value, False
