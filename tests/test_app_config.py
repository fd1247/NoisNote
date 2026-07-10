from __future__ import annotations

import json

import pytest

from src.app import config as config_module


def test_save_config_keeps_previous_file_when_new_write_fails(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    previous = {"notebooks": [{"id": "work", "name": "工作笔记本"}]}
    config_path.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_path)

    def fail_dump(*args, **kwargs) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(config_module.json, "dump", fail_dump)

    with pytest.raises(OSError, match="simulated write failure"):
        config_module.save_config({"notebooks": [{"id": "new", "name": "新笔记本"}]})

    assert json.loads(config_path.read_text(encoding="utf-8")) == previous
