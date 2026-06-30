"""热词管理单元测试。"""
import pytest

from src.hotwords.types import (
    HotwordSet,
    HotwordValidationError,
    MAX_ACTIVE_SETS,
    MAX_WORD_LENGTH,
    MAX_WORDS_PER_SET,
    HARD_LIMIT_TOTAL_WORDS,
    generate_hotword_set_id,
    validate_hotword_set,
    validate_active_sets,
)
from src.hotwords.service import HotwordService
from src.hotwords.import_export import HOTWORD_VERSION, export_hotword_sets, import_hotword_sets


class TestHotwordTypes:
    """热词数据类型测试。"""

    def test_generate_hotword_set_id(self):
        """测试热词表ID生成。"""
        id1 = generate_hotword_set_id()
        id2 = generate_hotword_set_id()
        assert id1 != id2
        assert len(id1) == 36  # UUID4 格式

    def test_validate_hotword_set_success(self):
        """测试热词表验证成功。"""
        hotword_set = {
            "id": "test-id",
            "name": "测试",
            "words": ["API", "SDK"],
        }
        validate_hotword_set(hotword_set, [])  # 不应抛出异常

    def test_validate_hotword_set_empty_name(self):
        """测试空名称验证。"""
        hotword_set = {"id": "test-id", "name": "", "words": []}
        with pytest.raises(HotwordValidationError) as exc:
            validate_hotword_set(hotword_set, [])
        assert exc.value.field == "name"

    def test_validate_hotword_set_too_many_words(self):
        """测试热词数量超限。"""
        hotword_set = {
            "id": "test-id",
            "name": "测试",
            "words": [f"word{i}" for i in range(MAX_WORDS_PER_SET + 1)],
        }
        with pytest.raises(HotwordValidationError) as exc:
            validate_hotword_set(hotword_set, [])
        assert exc.value.field == "words"

    def test_validate_hotword_set_word_too_long(self):
        """测试热词长度超限。"""
        hotword_set = {
            "id": "test-id",
            "name": "测试",
            "words": ["a" * (MAX_WORD_LENGTH + 1)],
        }
        with pytest.raises(HotwordValidationError) as exc:
            validate_hotword_set(hotword_set, [])
        assert exc.value.field == "words"

    def test_validate_active_sets_success(self):
        """测试激活热词表验证成功。"""
        all_sets = [
            {"id": "id1", "name": "表1", "words": []},
            {"id": "id2", "name": "表2", "words": []},
        ]
        validate_active_sets(["id1", "id2"], all_sets)  # 不应抛出异常

    def test_validate_active_sets_too_many(self):
        """测试激活数量超限。"""
        with pytest.raises(HotwordValidationError) as exc:
            validate_active_sets(["id1", "id2", "id3", "id4"], [])
        assert exc.value.field == "active_ids"


class TestHotwordService:
    """热词服务测试。"""

    def test_create_hotword_set(self):
        """测试创建热词表。"""
        config = {"hotword_sets": [], "active_hotword_set_ids": []}
        service = HotwordService(config)

        new_set = service.create_hotword_set("技术术语", "常见技术词汇", ["API", "SDK"])

        assert new_set["name"] == "技术术语"
        assert new_set["description"] == "常见技术词汇"
        assert new_set["words"] == ["API", "SDK"]
        assert len(config["hotword_sets"]) == 1

    def test_update_hotword_set(self):
        """测试更新热词表。"""
        config = {"hotword_sets": [], "active_hotword_set_ids": []}
        service = HotwordService(config)

        new_set = service.create_hotword_set("原始", "", ["word1"])
        updated = service.update_hotword_set(new_set["id"], {"name": "更新后"})

        assert updated["name"] == "更新后"

    def test_delete_hotword_set(self):
        """测试删除热词表。"""
        config = {"hotword_sets": [], "active_hotword_set_ids": []}
        service = HotwordService(config)

        new_set = service.create_hotword_set("测试", "", [])
        config["active_hotword_set_ids"] = [new_set["id"]]

        service.delete_hotword_set(new_set["id"])

        assert len(config["hotword_sets"]) == 0
        assert len(config["active_hotword_set_ids"]) == 0

    def test_set_active_sets(self):
        """测试设置激活热词表。"""
        config = {"hotword_sets": [], "active_hotword_set_ids": []}
        service = HotwordService(config)

        set1 = service.create_hotword_set("表1", "", ["word1"])
        set2 = service.create_hotword_set("表2", "", ["word2"])

        active_ids = service.set_active_sets([set1["id"]])

        assert active_ids == [set1["id"]]

    def test_resolve_active_hotwords(self):
        """测试解析激活热词。"""
        config = {"hotword_sets": [], "active_hotword_set_ids": []}
        service = HotwordService(config)

        set1 = service.create_hotword_set("表1", "", ["API", "SDK"])
        set2 = service.create_hotword_set("表2", "", ["前端", "API"])  # 包含重复热词

        service.set_active_sets([set1["id"], set2["id"]])
        hotwords = service.resolve_active_hotwords()

        assert hotwords == ["API", "SDK", "前端"]  # 去重，保持顺序

    def test_total_words_limit(self):
        """测试总热词数硬上限。"""
        config = {"hotword_sets": [], "active_hotword_set_ids": []}
        service = HotwordService(config)

        # 创建多个热词表，接近上限
        words_per_set = MAX_WORDS_PER_SET
        sets_needed = HARD_LIMIT_TOTAL_WORDS // words_per_set

        for i in range(sets_needed):
            words = [f"word{i}-{j}" for j in range(words_per_set)]
            service.create_hotword_set(f"表{i}", "", words)

        # 再创建一个应该失败
        with pytest.raises(HotwordValidationError):
            service.create_hotword_set("超出", "", ["word"])


class TestHotwordImportExport:
    """热词导入导出测试。"""

    def test_export_hotword_sets(self):
        """测试导出热词表。"""
        sets = [
            {"id": "id1", "name": "表1", "description": "desc", "words": ["API"]},
            {"id": "id2", "name": "表2", "description": "", "words": []},
        ]

        json_text = export_hotword_sets(sets)
        import json

        data = json.loads(json_text)

        assert data["version"] == HOTWORD_VERSION
        assert len(data["hotword_sets"]) == 2
        assert data["hotword_sets"][0]["name"] == "表1"

    def test_import_hotword_sets_success(self):
        """测试成功导入热词表。"""
        import json

        json_text = json.dumps(
            {
                "version": HOTWORD_VERSION,
                "hotword_sets": [
                    {"name": "导入表1", "description": "", "words": ["API", "SDK"]},
                ],
            }
        )

        imported_sets, errors = import_hotword_sets(json_text, [])

        assert len(imported_sets) == 1
        assert imported_sets[0]["name"] == "导入表1"
        assert len(errors) == 0

    def test_import_hotword_sets_invalid_json(self):
        """测试导入无效JSON。"""
        imported_sets, errors = import_hotword_sets("invalid json", [])

        assert len(imported_sets) == 0
        assert len(errors) == 1

    def test_import_generates_new_ids(self):
        """测试导入时生成新ID避免冲突。"""
        import json

        json_text = json.dumps(
            {
                "version": HOTWORD_VERSION,
                "hotword_sets": [
                    {"name": "表1", "description": "", "words": []},
                    {"name": "表2", "description": "", "words": []},
                ],
            }
        )

        imported_sets, _ = import_hotword_sets(json_text, [])

        # 确保生成了不同的UUID
        ids = [s["id"] for s in imported_sets]
        assert len(set(ids)) == 2
        assert all(id_ for id_ in ids)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])