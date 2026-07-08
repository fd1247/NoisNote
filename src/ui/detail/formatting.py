"""详情区域展示文本格式化工具。"""
from __future__ import annotations

METADATA_VALUE_MAX_CHARS = 48


def elide_metadata_value(value: object, max_chars: int = METADATA_VALUE_MAX_CHARS) -> str:
    """限制详情元数据单项文本长度，完整值通过 tooltip 保留。"""
    text = str(value or "--")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
