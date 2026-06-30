"""热词表导入导出功能。"""
from __future__ import annotations

import json
from typing import Any

from .types import (
    HotwordValidationError,
    _now_iso,
    generate_hotword_set_id,
    validate_hotword_set,
)

# 导出版本常量
HOTWORD_VERSION = "1.0"


def export_hotword_sets(hotword_sets: list[dict[str, Any]]) -> str:
    """导出热词表为JSON格式。

    Args:
        hotword_sets: 要导出的热词表列表

    Returns:
        JSON格式的字符串
    """
    export_data = {
        "version": HOTWORD_VERSION,
        "exported_at": _now_iso(),
        "hotword_sets": [
            {
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "words": list(item.get("words", [])),
            }
            for item in hotword_sets
        ],
    }
    return json.dumps(export_data, ensure_ascii=False, indent=2)


def import_hotword_sets(
    json_text: str, existing_sets: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """导入热词表。

    Args:
        json_text: JSON格式的文本
        existing_sets: 已存在的热词表列表（用于验证）

    Returns:
        (成功导入的热词表列表, 错误信息列表)
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return [], ["文件格式错误：无法解析JSON"]

    if not isinstance(data, dict):
        return [], ["文件格式错误：根节点必须是对象"]

    raw_sets = data.get("hotword_sets", [])
    if not isinstance(raw_sets, list):
        return [], ["文件格式错误：hotword_sets必须是数组"]

    imported_sets: list[dict[str, Any]] = []
    errors: list[str] = []
    existing_sets_copy = list(existing_sets)

    for i, item in enumerate(raw_sets):
        try:
            if not isinstance(item, dict):
                errors.append(f"第{i + 1}个热词表：必须是对象")
                continue

            # 生成新ID避免冲突
            new_id = generate_hotword_set_id()
            imported_set: dict[str, Any] = {
                "id": new_id,
                "name": item.get("name", ""),
                "description": item.get("description", ""),
                "words": list(item.get("words", [])),
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }

            # 验证热词表
            validate_hotword_set(imported_set, existing_sets_copy)

            imported_sets.append(imported_set)
            existing_sets_copy.append(imported_set)

        except HotwordValidationError as e:
            errors.append(
                f"第{i + 1}个热词表（{item.get('name', '未命名')}）：{e.message}"
            )
        except Exception:
            errors.append(f"第{i + 1}个热词表：未知错误")

    return imported_sets, errors


__all__ = [
    "export_hotword_sets",
    "import_hotword_sets",
    "HOTWORD_VERSION",
]