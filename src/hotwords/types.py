"""热词管理数据模型和验证常量。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


# 验证限制常量（保守配置）
MAX_WORDS_PER_SET = 50  # 单个热词表最多热词数
MAX_WORD_LENGTH = 20  # 单个热词最大长度
MAX_ACTIVE_SETS = 3  # 同时激活的热词表数量
HARD_LIMIT_TOTAL_WORDS = 200  # 总热词数量硬上限


@dataclass
class HotwordSet:
    """热词表数据模型。"""

    id: str
    name: str
    description: str = ""
    words: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class HotwordValidationError(Exception):
    """热词验证错误。"""

    def __init__(self, message: str, field: str = ""):
        super().__init__(message)
        self.message = message
        self.field = field


def generate_hotword_set_id() -> str:
    """生成新的热词表ID。"""
    return str(uuid4())


def _now_iso() -> str:
    """获取当前时间的 ISO8601 格式字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_hotword_set(hotword_set: dict[str, Any], existing_sets: list[dict[str, Any]]) -> None:
    """验证热词表数据是否符合限制。

    Args:
        hotword_set: 待验证的热词表数据
        existing_sets: 已存在的其他热词表（用于计算总热词数）

    Raises:
        HotwordValidationError: 验证失败时抛出
    """
    # 验证名称
    if not hotword_set.get("name", "").strip():
        raise HotwordValidationError("热词表名称不能为空", "name")

    # 验证热词列表
    words = hotword_set.get("words", [])
    if not isinstance(words, list):
        raise HotwordValidationError("热词列表格式错误", "words")

    # 验证热词数量
    if len(words) > MAX_WORDS_PER_SET:
        raise HotwordValidationError(f"单个热词表最多{MAX_WORDS_PER_SET}个热词", "words")

    # 验证热词长度
    for word in words:
        if not isinstance(word, str):
            raise HotwordValidationError("热词必须为字符串", "words")
        if len(word) > MAX_WORD_LENGTH:
            raise HotwordValidationError(f"热词「{word}」超过{MAX_WORD_LENGTH}字符限制", "words")

    # 验证总热词数（硬上限）
    existing_word_count = sum(len(s.get("words", [])) for s in existing_sets)
    total_words = existing_word_count + len(words)
    if total_words > HARD_LIMIT_TOTAL_WORDS:
        raise HotwordValidationError(f"总热词数量不能超过{HARD_LIMIT_TOTAL_WORDS}个", "words")


def validate_active_sets(active_ids: list[str], all_sets: list[dict[str, Any]]) -> None:
    """验证激活的热词表数量限制。

    Args:
        active_ids: 激活的热词表 ID 列表
        all_sets: 所有热词表

    Raises:
        HotwordValidationError: 验证失败时抛出
    """
    if not isinstance(active_ids, list):
        raise HotwordValidationError("激活热词表ID列表格式错误", "active_ids")

    if len(active_ids) > MAX_ACTIVE_SETS:
        raise HotwordValidationError(f"同时激活最多{MAX_ACTIVE_SETS}个热词表", "active_ids")

    # 验证激活的热词表ID都存在
    valid_ids = {s.get("id") for s in all_sets}
    for hotword_id in active_ids:
        if hotword_id not in valid_ids:
            raise HotwordValidationError(f"热词表ID「{hotword_id}」不存在", "active_ids")


__all__ = [
    "HotwordSet",
    "HotwordValidationError",
    "generate_hotword_set_id",
    "validate_hotword_set",
    "validate_active_sets",
    "MAX_WORDS_PER_SET",
    "MAX_WORD_LENGTH",
    "MAX_ACTIVE_SETS",
    "HARD_LIMIT_TOTAL_WORDS",
]