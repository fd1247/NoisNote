from __future__ import annotations

import pytest

from src.app import config as config_module


@pytest.fixture(autouse=True)
def isolate_app_config(monkeypatch: pytest.MonkeyPatch, tmp_path):
    config_dir = tmp_path / "app-config"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_dir / "config.json")
