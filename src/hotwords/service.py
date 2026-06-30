"""热词管理业务逻辑。"""
from __future__ import annotations

from typing import Any

from .types import (
    HotwordValidationError,
    _now_iso,
    generate_hotword_set_id,
    validate_active_sets,
    validate_hotword_set,
)


class HotwordService:
    """热词管理服务。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def get_hotword_sets(self) -> list[dict[str, Any]]:
        """获取所有热词表。"""
        return list(self.config.get("hotword_sets", []))

    def get_hotword_set(self, set_id: str) -> dict[str, Any] | None:
        """获取指定ID的热词表。

        Args:
            set_id: 热词表ID

        Returns:
            热词表数据，不存在时返回 None
        """
        for item in self.config.get("hotword_sets", []):
            if item.get("id") == set_id:
                return item
        return None

    def create_hotword_set(
        self, name: str, description: str, words: list[str]
    ) -> dict[str, Any]:
        """创建新热词表。

        Args:
            name: 热词表名称
            description: 描述
            words: 热词列表

        Returns:
            创建的热词表数据

        Raises:
            HotwordValidationError: 验证失败时抛出
        """
        now = _now_iso()
        new_set: dict[str, Any] = {
            "id": generate_hotword_set_id(),
            "name": name,
            "description": description,
            "words": list(words),
            "created_at": now,
            "updated_at": now,
        }

        existing_sets = self.config.get("hotword_sets", [])
        validate_hotword_set(new_set, existing_sets)

        self.config.setdefault("hotword_sets", [])
        self.config["hotword_sets"] = existing_sets + [new_set]
        return new_set

    def update_hotword_set(
        self, set_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """更新热词表。

        Args:
            set_id: 热词表ID
            updates: 更新的字段

        Returns:
            更新后的热词表数据，不存在时返回 None

        Raises:
            HotwordValidationError: 验证失败时抛出
        """
        sets = list(self.config.get("hotword_sets", []))
        for i, item in enumerate(sets):
            if item.get("id") == set_id:
                # 创建更新后的副本用于验证
                updated = {**item, **updates, "updated_at": _now_iso()}
                # 其他热词表（用于验证总热词数）
                other_sets = [s for s in sets if s.get("id") != set_id]
                validate_hotword_set(updated, other_sets)

                sets[i] = updated
                self.config["hotword_sets"] = sets
                return updated
        return None

    def delete_hotword_set(self, set_id: str) -> bool:
        """删除热词表。

        Args:
            set_id: 热词表ID

        Returns:
            是否删除成功
        """
        sets = self.config.get("hotword_sets", [])
        self.config["hotword_sets"] = [s for s in sets if s.get("id") != set_id]

        # 同时从激活列表中移除
        active_ids = self.config.get("active_hotword_set_ids", [])
        self.config["active_hotword_set_ids"] = [
            id_ for id_ in active_ids if id_ != set_id
        ]

        return True

    def set_active_sets(self, active_ids: list[str]) -> list[str]:
        """设置激活的热词表。

        Args:
            active_ids: 激活的热词表ID列表

        Returns:
            设置后的激活热词表ID列表

        Raises:
            HotwordValidationError: 验证失败时抛出
        """
        all_sets = self.config.get("hotword_sets", [])
        validate_active_sets(active_ids, all_sets)

        self.config["active_hotword_set_ids"] = active_ids
        return active_ids

    def get_active_hotword_sets(self) -> list[dict[str, Any]]:
        """获取激活的热词表。

        Returns:
            激活的热词表列表
        """
        active_ids = self.config.get("active_hotword_set_ids", [])
        all_sets = self.config.get("hotword_sets", [])
        return [s for s in all_sets if s.get("id") in active_ids]

    def resolve_active_hotwords(self) -> list[str]:
        """解析激活的热词，返回去重后的热词列表。

        Returns:
            去重后的热词列表
        """
        active_sets = self.get_active_hotword_sets()
        all_words: list[str] = []
        for item in active_sets:
            words = item.get("words", [])
            if isinstance(words, list):
                all_words.extend(words)

        # 去重并保持顺序
        seen: set[str] = set()
        unique_words: list[str] = []
        for word in all_words:
            if word and word not in seen:
                seen.add(word)
                unique_words.append(word)

        return unique_words


__all__ = [
    "HotwordService",
]