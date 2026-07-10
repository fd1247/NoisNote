from __future__ import annotations

import logging

import pytest

from src.app import config as config_module
from src.utils.logging import LOG_DIR_ENV, LOGGER_NAME


@pytest.fixture(autouse=True)
def isolate_app_config(monkeypatch: pytest.MonkeyPatch, tmp_path):
    config_dir = tmp_path / "app-config"
    monkeypatch.setattr(config_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_dir / "config.json")
    monkeypatch.setenv(LOG_DIR_ENV, str(tmp_path / "logs"))
    yield

    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
