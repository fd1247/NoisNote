from __future__ import annotations

import copy
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.app import config as config_module
from src.app.config import (
    DEFAULT_MODEL_CATALOG,
    QWEN3_ASR_GGUF_MODELSCOPE_REVISION,
    QWEN3_ASR_GGUF_06B_ID,
    QWEN3_ASR_GGUF_06B_SLUG,
    QWEN3_ASR_GGUF_17B_ID,
    QWEN3_ASR_GGUF_17B_SLUG,
    QWEN3_ASR_GGUF_REQUIRED_FILES,
    get_qwen3_asr_gguf_tool_dir,
)
from src.app.main_window import MainWindow, SettingsPanel
from src.model_registry.downloader import ModelDownloadManager
from src.model_registry.service import DownloadTaskState, ModelService, ModelStatus
from src.asr.runtime import (
    Qwen3AsrGgufResult,
    build_context,
    resolve_device_mode,
)
from src.asr.engine import TranscriptionEngine


def make_config(root: Path) -> dict:
    catalog = copy.deepcopy(DEFAULT_MODEL_CATALOG)
    catalog.insert(
        1,
        {
            "name": "legacy-vad",
            "display_name": "VAD",
            "model_type": "vad",
            "backend": "qwen3_asr_gguf",
            "local_dir_name": "legacy-vad",
            "description": "不在本阶段展示",
            "required_files": ["configuration.json"],
        },
    )
    return {
        "demo_audio_imported": True,
        "data_root": str(root),
        "selected_asr": {"model": QWEN3_ASR_GGUF_06B_ID, "model_path": "", "device": "auto"},
        "qwen3_asr_gguf": {
            "tool_dir": str(root / "vendor" / "qwen3-asr-gguf"),
            "chunk_size": 40.0,
            "memory_num": 1,
            "n_ctx": 2048,
            "context": "",
        },
        "llm": {"api_key": "", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1"},
        "audio": {
            "output_dir": str(root / "recordings"),
            "auto_transcribe": True,
            "auto_summarize": True,
        },
        "models": {
            "root_dir": str(root / "models"),
            "catalog": catalog,
            "downloaded": {},
        },
    }


def write_required_model_files(model_dir: Path) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for file_name in QWEN3_ASR_GGUF_REQUIRED_FILES:
        (model_dir / file_name).write_text("model", encoding="utf-8")


def test_catalog_only_returns_gguf_asr_and_target_inside_root(tmp_path: Path) -> None:
    service = ModelService(make_config(tmp_path))

    catalog = service.get_asr_catalog()

    assert [entry.name for entry in catalog] == [
        QWEN3_ASR_GGUF_06B_ID,
        QWEN3_ASR_GGUF_17B_ID,
    ]
    assert catalog[0].backend == "qwen3_asr_gguf"
    assert service.get_target_dir(catalog[0]) == (tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG).resolve()


def test_model_service_uses_data_root_models_when_legacy_root_dir_is_stale(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config["models"]["root_dir"] = str(tmp_path / "stale-models")

    service = ModelService(config)

    assert service.root_dir == (tmp_path / "models").resolve()
    assert config["models"]["root_dir"] == str((tmp_path / "models").resolve())


def test_get_entry_accepts_alias_for_current_values(tmp_path: Path) -> None:
    service = ModelService(make_config(tmp_path))

    entry = service.get_entry("qwen3-asr-gguf-0.6b")

    assert entry is not None
    assert entry.name == QWEN3_ASR_GGUF_06B_ID
    assert entry.download_url.endswith("/resolve/v1.0.0/")
    assert entry.primary_download_url().endswith("/resolve/v1.0.0/")
    assert entry.download_sources[0]["name"] == "modelscope"
    assert entry.download_sources[0]["revision"] == QWEN3_ASR_GGUF_MODELSCOPE_REVISION
    assert entry.download_sources[1]["name"] == "github"
    assert entry.download_sources[1]["url"].endswith("Qwen3-ASR-0.6B-gguf.zip")


def test_catalog_includes_two_qwen_gguf_models(tmp_path: Path) -> None:
    service = ModelService(make_config(tmp_path))

    small_entry = service.get_entry(QWEN3_ASR_GGUF_06B_ID)
    large_entry = service.get_entry(QWEN3_ASR_GGUF_17B_ID)

    assert small_entry is not None
    assert small_entry.adapter == "qwen3_asr_gguf"
    assert small_entry.model_size == "0.6B"
    assert service.get_target_dir(small_entry) == (tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG).resolve()

    assert large_entry is not None
    assert large_entry.adapter == "qwen3_asr_gguf"
    assert large_entry.model_size == "1.7B"
    assert service.get_target_dir(large_entry) == (tmp_path / "models" / QWEN3_ASR_GGUF_17B_SLUG).resolve()


def test_gguf_tool_dir_falls_back_to_bundled_runtime(monkeypatch, tmp_path: Path) -> None:
    bundled = tmp_path / "_internal" / "vendor" / "qwen3-asr-gguf"
    bundled.mkdir(parents=True)
    missing_configured = tmp_path / "missing" / "Qwen3-ASR-Transcribe"
    missing_default = tmp_path / "missing-default" / "Qwen3-ASR-Transcribe"

    monkeypatch.setattr(config_module, "DEFAULT_QWEN3_ASR_GGUF_TOOL_DIR", missing_default)
    monkeypatch.setattr(config_module, "DEV_QWEN3_ASR_GGUF_TOOL_DIR", tmp_path / "missing-dev")
    monkeypatch.setattr(config_module.sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)

    config = {"qwen3_asr_gguf": {"tool_dir": str(missing_configured)}}

    assert get_qwen3_asr_gguf_tool_dir(config) == bundled


def test_validate_downloaded_incomplete_and_available_models(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    service = ModelService(config)
    entry = service.get_entry(QWEN3_ASR_GGUF_06B_ID)
    assert entry is not None

    target = service.get_target_dir(entry)
    target.mkdir(parents=True)
    incomplete = service.validate_model_dir(entry)
    assert incomplete.status == ModelStatus.INCOMPLETE
    assert QWEN3_ASR_GGUF_06B_ID in [item.name for item in service.get_available_models()]

    write_required_model_files(target)
    downloaded = service.get_downloaded_models()

    assert len(downloaded) == 1
    assert downloaded[0].status == ModelStatus.DOWNLOADED
    assert downloaded[0].is_complete
    assert QWEN3_ASR_GGUF_06B_ID in config["models"]["downloaded"]
    assert QWEN3_ASR_GGUF_06B_ID not in [item.name for item in service.get_available_models()]


def test_prepare_download_dir_rejects_paths_outside_root(tmp_path: Path) -> None:
    service = ModelService(make_config(tmp_path))
    bad_entry = service.get_catalog()[0]
    bad_entry = type(bad_entry)(**{**bad_entry.__dict__, "local_dir_name": "../outside"})

    try:
        service.prepare_download_dir(bad_entry)
    except ValueError as exc:
        assert "越界" in str(exc)
    else:
        raise AssertionError("expected unsafe path to be rejected")

    assert not (tmp_path / "outside").exists()


def test_mark_downloaded_requires_key_files(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    service = ModelService(config)
    entry = service.get_entry(QWEN3_ASR_GGUF_06B_ID)
    assert entry is not None
    target = service.get_target_dir(entry)
    target.mkdir(parents=True)

    try:
        service.mark_downloaded(entry, target)
    except ValueError as exc:
        assert "模型文件不完整" in str(exc)
    else:
        raise AssertionError("expected incomplete model to be rejected")

    write_required_model_files(target)
    record = service.mark_downloaded(entry, target)

    assert record["path"] == str(target)
    assert record["backend"] == "qwen3_asr_gguf"
    assert config["models"]["downloaded"][QWEN3_ASR_GGUF_06B_ID]["path"] == str(target)


def test_download_disk_space_check_reports_required_and_available(monkeypatch, tmp_path: Path) -> None:
    service = ModelService(make_config(tmp_path))
    entry = service.get_entry(QWEN3_ASR_GGUF_06B_ID)
    assert entry is not None
    entry = type(entry)(**{**entry.__dict__, "estimated_size_bytes": 1000})
    monkeypatch.setattr(
        "src.model_registry.service.shutil.disk_usage",
        lambda path: SimpleNamespace(free=900),
    )

    result = service.check_download_disk_space(entry)

    assert result.ok is False
    assert result.required_bytes == 2100
    assert result.available_bytes == 900
    assert "磁盘空间不足" in result.message
    assert "预计需要" in result.message
    assert "当前可用" in result.message


def test_delete_downloaded_model_removes_only_target_model(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    service = ModelService(config)
    small = service.get_entry(QWEN3_ASR_GGUF_06B_ID)
    large = service.get_entry(QWEN3_ASR_GGUF_17B_ID)
    assert small is not None
    assert large is not None
    small_dir = service.get_target_dir(small)
    large_dir = service.get_target_dir(large)
    write_required_model_files(small_dir)
    write_required_model_files(large_dir)
    service.mark_downloaded(small, small_dir)
    service.mark_downloaded(large, large_dir)

    result = service.delete_downloaded_model(small)

    assert result.success
    assert result.deleted_path == small_dir
    assert not small_dir.exists()
    assert large_dir.exists()
    assert QWEN3_ASR_GGUF_06B_ID not in config["models"]["downloaded"]
    assert QWEN3_ASR_GGUF_17B_ID in config["models"]["downloaded"]


def test_delete_downloaded_model_rejects_root_dir(tmp_path: Path) -> None:
    service = ModelService(make_config(tmp_path))
    entry = service.get_entry(QWEN3_ASR_GGUF_06B_ID)
    assert entry is not None
    bad_entry = type(entry)(**{**entry.__dict__, "local_dir_name": "."})

    try:
        service.delete_downloaded_model(bad_entry)
    except ValueError as exc:
        assert "模型根目录" in str(exc)
    else:
        raise AssertionError("expected deleting model root to be rejected")


def test_settings_dialog_lists_downloaded_models_and_saves_path(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    model_dir = tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG
    write_required_model_files(model_dir)

    manager = ModelDownloadManager(config)
    panel = SettingsPanel(config, manager)
    try:
        assert panel.model_manager.downloaded_group.text(0) == "已下载"
        assert panel.model_manager.available_group.text(0) == "可下载"
        assert panel.model_manager.downloading_group is None
        assert panel.model_manager.downloaded_group.childCount() == 1
        assert panel.model_manager.available_group.childCount() == 2
        downloaded_item = panel.model_manager.downloaded_group.child(0)
        downloaded_widget = panel.model_manager.model_tree.itemWidget(downloaded_item, 0)
        panel.model_manager.model_tree.setCurrentItem(downloaded_item)
        app.processEvents()
        assert downloaded_widget.property("selected") is True
        assert panel.asr_model.itemData(0) == QWEN3_ASR_GGUF_06B_ID
        assert panel.asr_model.itemText(0) == "Qwen3-ASR-0.6B GGUF"

        updated = panel.updated_config()
        assert updated["selected_asr"]["model"] == QWEN3_ASR_GGUF_06B_ID
        assert updated["selected_asr"]["model_path"] == str(model_dir.resolve())
        assert updated["audio"]["auto_transcribe"] is True

        panel.auto_transcribe.setChecked(False)
        updated = panel.updated_config()
        assert updated["audio"]["auto_transcribe"] is False
    finally:
        panel.close()
        manager.deleteLater()
        app.processEvents()


def test_settings_hotword_activation_uses_replaced_config(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    hotword_set = {
        "id": "hotword-set-1",
        "name": "项目术语",
        "description": "会议常用词",
        "words": ["NoisNote", "Qwen3-ASR"],
    }
    config["hotword_sets"] = [dict(hotword_set)]
    config["active_hotword_set_ids"] = []
    manager = ModelDownloadManager(config)
    panel = SettingsPanel(config, manager)

    replaced_config = dict(config)
    replaced_config["hotword_sets"] = [dict(hotword_set)]
    replaced_config["active_hotword_set_ids"] = []
    panel.config = replaced_config

    try:
        panel.reset_from_config()
        panel.show_section("hotwords")

        item = panel.hotword_set_list.item(0)
        item.setCheckState(Qt.CheckState.Checked)
        app.processEvents()

        updated = panel.updated_config()

        assert replaced_config["active_hotword_set_ids"] == ["hotword-set-1"]
        assert updated["active_hotword_set_ids"] == ["hotword-set-1"]
    finally:
        panel.close()
        manager.deleteLater()
        app.processEvents()


def test_model_manager_cancel_removes_downloading_item_immediately(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    manager = ModelDownloadManager(config)
    panel = SettingsPanel(config, manager)
    name = QWEN3_ASR_GGUF_17B_ID

    class FakeWorker:
        def __init__(self):
            self.cancel_requested = False
            self.terminated = False
            self.wait_timeout = None
            self.wait_count = 0

        def request_cancel(self):
            self.cancel_requested = True

        def isRunning(self):
            return self.wait_count == 0

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            self.wait_timeout = timeout
            self.wait_count += 1
            return True

    try:
        worker = FakeWorker()
        entry = panel.model_manager.service.get_entry(name)
        assert entry is not None
        manager.download_workers[name] = worker
        manager.download_tasks[name] = DownloadTaskState(
            name=name,
            source_url=entry.download_url,
            target_dir=panel.model_manager.service.get_download_temp_dir(entry),
            status_text="下载中",
        )
        panel.model_manager.refresh_lists()
        assert panel.model_manager.downloading_group.childCount() == 1
        panel.model_manager.model_tree.setCurrentItem(panel.model_manager.downloading_group.child(0))
        app.processEvents()
        assert panel.model_manager.model_action_button.text() == "取消下载"

        manager.cancel_download(name)

        assert worker.cancel_requested
        assert worker.wait_timeout == 1200
        assert name not in manager.download_tasks
        assert panel.model_manager.downloading_group is None
    finally:
        panel.close()
        manager.deleteLater()
        app.processEvents()


def test_model_manager_empty_states_and_general_model_placeholder(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)

    manager = ModelDownloadManager(config)
    panel = SettingsPanel(config, manager)
    try:
        assert panel.asr_model.itemText(0) == "暂无已下载模型"
        assert panel.asr_model.itemData(0) == QWEN3_ASR_GGUF_06B_ID
        assert panel.model_manager.downloaded_group.child(0).text(0) == "还没有下载模型"
        # 模型清单现在从常量读取，未下载的模型会出现在"可供下载"分组
        assert panel.model_manager.available_group.childCount() >= 1
        assert panel.model_manager.downloading_group is None
    finally:
        panel.close()
        manager.deleteLater()
        app.processEvents()


def test_model_manager_refresh_preserves_downloading_selection(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    manager = ModelDownloadManager(config)
    panel = SettingsPanel(config, manager)
    available_entries = panel.model_manager.service.get_available_models(set())
    first_name = available_entries[0].name
    try:
        for entry in available_entries:
            manager.download_tasks[entry.name] = DownloadTaskState(
                name=entry.name,
                source_url=entry.download_url,
                target_dir=panel.model_manager.service.get_download_temp_dir(entry),
                status_text="下载中",
                progress_percent=20.0,
            )
        panel.model_manager.refresh_lists()
        first_item = panel.model_manager.downloading_group.child(0)
        panel.model_manager.model_tree.setCurrentItem(first_item)
        app.processEvents()

        assert panel.model_manager.available_group.child(0).text(0) == "没有可下载的模型"
        assert panel.model_manager.selected_kind == "downloading"
        assert panel.model_manager.selected_name == first_name

        manager.download_tasks[first_name] = DownloadTaskState(
            name=first_name,
            source_url=manager.download_tasks[first_name].source_url,
            target_dir=manager.download_tasks[first_name].target_dir,
            status_text="下载中 40%",
            progress_percent=40.0,
        )
        panel.model_manager.refresh_lists()

        current_item = panel.model_manager.model_tree.currentItem()
        assert current_item is not None
        assert current_item.data(0, Qt.UserRole) == ("downloading", first_name)
        assert panel.model_manager.model_action_button.text() == "取消下载"
    finally:
        panel.close()
        manager.deleteLater()
        app.processEvents()


def test_model_manager_deletes_downloaded_model_after_confirmation(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    model_dir = tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG
    write_required_model_files(model_dir)
    manager = ModelDownloadManager(config)
    panel = SettingsPanel(config, manager)
    saved_configs: list[dict] = []
    info_messages: list[str] = []
    confirmation: dict[str, str] = {}
    monkeypatch.setattr("src.ui.model_panel.save_config", lambda value: saved_configs.append(value))

    def fake_confirm(parent, title, text, confirm_text="确认", cancel_text="取消"):
        confirmation["title"] = title
        confirmation["text"] = text
        confirmation["confirm_text"] = confirm_text
        confirmation["cancel_text"] = cancel_text
        return True

    monkeypatch.setattr("src.ui.model_panel.confirm_without_icon", fake_confirm)
    monkeypatch.setattr(
        "src.ui.model_panel.alert_without_icon",
        lambda parent, title, message, confirm_text="确认": info_messages.append(message),
    )

    try:
        downloaded_item = panel.model_manager.downloaded_group.child(0)
        panel.model_manager.model_tree.setCurrentItem(downloaded_item)
        app.processEvents()

        assert not panel.model_manager.delete_model_button.isHidden()

        panel.model_manager._delete_selected_model()

        assert not model_dir.exists()
        assert QWEN3_ASR_GGUF_06B_ID not in config["models"]["downloaded"]
        assert saved_configs == [config]
        assert info_messages == ["模型已删除"]
        assert confirmation == {
            "title": "删除模型",
            "text": "您确定要删除所选模型吗?",
            "confirm_text": "确认",
            "cancel_text": "取消",
        }
        panel._refresh_asr_model_options()
        assert panel.asr_model.itemText(0) == "暂无已下载模型"
    finally:
        panel.close()
        manager.deleteLater()
        app.processEvents()


def test_model_manager_cancel_delete_keeps_downloaded_model(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    model_dir = tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG
    write_required_model_files(model_dir)
    manager = ModelDownloadManager(config)
    panel = SettingsPanel(config, manager)
    monkeypatch.setattr(
        "src.ui.model_panel.confirm_without_icon",
        lambda *args, **kwargs: False,
    )

    try:
        downloaded_item = panel.model_manager.downloaded_group.child(0)
        panel.model_manager.model_tree.setCurrentItem(downloaded_item)
        app.processEvents()

        panel.model_manager._delete_selected_model()

        assert model_dir.exists()
        assert QWEN3_ASR_GGUF_06B_ID in config["models"]["downloaded"]
    finally:
        panel.close()
        manager.deleteLater()
        app.processEvents()


def test_download_manager_uses_worker_progress_without_scan_override(tmp_path: Path) -> None:
    manager = ModelDownloadManager(make_config(tmp_path))
    name = QWEN3_ASR_GGUF_06B_ID
    entry = manager.service.get_entry(name)
    assert entry is not None
    download_dir = manager.service.get_download_temp_dir(entry)
    download_dir.mkdir(parents=True)
    manager.download_tasks[name] = DownloadTaskState(
        name=name,
        source_url=entry.download_url,
        target_dir=download_dir,
        status_text="正在连接模型下载源",
    )

    try:
        manager._on_download_progress(
            name,
            50,
            "已下载 256.0 MB/512.0 MB | 50.0%",
        )

        task = manager.download_tasks[name]
        assert task.status_text == "已下载 256.0 MB/512.0 MB | 50.0%"
        assert task.progress_percent == 50
        assert task.progress_source == "worker"
    finally:
        manager.deleteLater()


def test_download_manager_rejects_second_parallel_download(tmp_path: Path) -> None:
    manager = ModelDownloadManager(make_config(tmp_path))
    first_name = QWEN3_ASR_GGUF_06B_ID
    second_name = QWEN3_ASR_GGUF_17B_ID
    first_entry = manager.service.get_entry(first_name)
    assert first_entry is not None
    messages: list[tuple[str, str]] = []
    manager.download_failed.connect(lambda name, error: messages.append((name, error)))
    manager.download_workers[first_name] = object()
    manager.download_tasks[first_name] = DownloadTaskState(
        name=first_name,
        source_url=first_entry.download_url,
        target_dir=manager.service.get_download_temp_dir(first_entry),
        status_text="下载中",
    )

    try:
        manager.start_download(second_name)

        assert second_name not in manager.download_workers
        assert second_name not in manager.download_tasks
        assert messages == [(second_name, "已有模型正在下载，请等待当前下载完成后再试。")]
    finally:
        manager.download_workers.clear()
        manager.download_tasks.clear()
        manager.deleteLater()


def test_download_manager_rejects_download_when_disk_space_is_insufficient(monkeypatch, tmp_path: Path) -> None:
    manager = ModelDownloadManager(make_config(tmp_path))
    name = QWEN3_ASR_GGUF_06B_ID
    messages: list[tuple[str, str]] = []
    manager.download_failed.connect(lambda model_name, error: messages.append((model_name, error)))
    monkeypatch.setattr(
        manager.service,
        "check_download_disk_space",
        lambda entry: SimpleNamespace(ok=False, message="磁盘空间不足：预计需要 1.0 GB，当前可用 100.0 MB"),
    )

    try:
        manager.start_download(name)

        assert name not in manager.download_workers
        assert name not in manager.download_tasks
        assert messages == [(name, "磁盘空间不足：预计需要 1.0 GB，当前可用 100.0 MB")]
    finally:
        manager.deleteLater()


def test_main_window_settings_dialog_shows_model_section(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.save_config", lambda _config: None)
    monkeypatch.setattr("src.handlers.settings.save_config", lambda _config: None)
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda: None)
    window = MainWindow()
    try:
        window.show_settings()

        assert window.settings_dialog.isVisible()
        assert window.sidebar_stack.currentWidget() == window.main_sidebar
        assert window.settings_dialog.nav_buttons["general"].isChecked()

        window.show_settings_section("models")
        assert window.settings_dialog.nav_buttons["models"].isChecked()
        assert window.settings_panel.settings_stack.currentWidget() == window.settings_panel.model_manager

        window.hide_settings()
        assert not window.settings_dialog.isVisible()
        assert window.content_stack.currentWidget() != window.settings_panel
    finally:
        window.close()
        app.processEvents()


def test_device_resolver_maps_ui_values() -> None:
    assert resolve_device_mode("auto").resolved_device == "cpu"
    assert resolve_device_mode("cpu").onnx_provider == "CPU"
    assert resolve_device_mode("cpu").llm_use_gpu is False
    gpu = resolve_device_mode("gpu")
    assert gpu.resolved_device == "gpu"
    assert gpu.onnx_provider == "DML"
    assert gpu.llm_use_gpu is True


def test_build_context_merges_user_context_and_hotwords() -> None:
    context = build_context("这是一段技术会议。", ["ModelScope", "Qwen3-ASR"])

    assert "这是一段技术会议。" in context
    assert "请优先准确识别以下热词：ModelScope、Qwen3-ASR" in context


def test_transcription_engine_uses_gguf_runtime(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class FakeRuntime:
        def __init__(self, runtime_config):
            captured["runtime_config"] = runtime_config

        def load(self, on_progress=None):
            if on_progress:
                on_progress("模型加载完成")

        def transcribe(self, audio_file, on_progress=None):
            captured["audio_file"] = audio_file
            if on_progress:
                on_progress("转录完成")
            return Qwen3AsrGgufResult(
                text="GGUF text",
                diagnostics={
                    "engine": "qwen3-asr-gguf",
                    "status": "completed",
                    "model_name": QWEN3_ASR_GGUF_06B_ID,
                    "model_size": "0.6B",
                    "requested_device": "gpu",
                    "resolved_device": "gpu",
                    "timings": {"model_load_seconds": 0.12, "transcribe_seconds": 0.34},
                    "performance": {"rtf": 0.02},
                    "error": None,
                },
            )

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr("src.asr.engine.Qwen3AsrGgufRuntime", FakeRuntime)
    model_dir = tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG
    write_required_model_files(model_dir)
    config = make_config(tmp_path)
    config["selected_asr"]["model_path"] = str(model_dir)
    config["selected_asr"]["device"] = "gpu"
    config["hotword_sets"] = [
        {
            "id": "hotword-set-1",
            "name": "项目术语",
            "description": "",
            "words": ["NoisNote", "Qwen3-ASR"],
        }
    ]
    config["active_hotword_set_ids"] = ["hotword-set-1"]

    engine = TranscriptionEngine(config)
    text = engine.transcribe("audio.wav")
    engine.close()

    assert text == "GGUF text"
    assert captured["audio_file"] == "audio.wav"
    assert captured["runtime_config"].model_dir == model_dir.resolve()
    assert captured["runtime_config"].model_size == "0.6B"
    assert captured["runtime_config"].requested_device == "gpu"
    assert captured["runtime_config"].hotwords == ["NoisNote", "Qwen3-ASR"]
    assert engine.last_diagnostics["performance"]["rtf"] == 0.02
    assert captured["closed"] is True
