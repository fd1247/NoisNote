from __future__ import annotations

import copy
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.config import (
    DEFAULT_CONFIG,
    DEFAULT_MODEL_CATALOG,
    QWEN3_ASR_GGUF_06B_ID,
    QWEN3_ASR_GGUF_06B_SLUG,
    QWEN3_ASR_GGUF_REQUIRED_FILES,
    QWEN3_FORCE_ALIGNER_GGUF_06B_ID,
    QWEN3_FORCE_ALIGNER_GGUF_06B_SLUG,
    QWEN3_FORCE_ALIGNER_GGUF_REQUIRED_FILES,
)
from src.app.main_window import MainWindow
from src.asr.engine import TranscriptionEngine
from src.asr.timestamps import alignment_items_to_timeline, timeline_from_dicts, timeline_to_dicts, timeline_to_html
from src.history.service import HistoryService
from src.model_registry.downloader import ModelDownloadManager
from src.model_registry.service import ModelService
from src.ui.settings import SettingsPanel


def make_config(root: Path) -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["demo_audio_imported"] = True
    config["data_root"] = str(root)
    config["selected_asr"]["model"] = QWEN3_ASR_GGUF_06B_ID
    config["selected_asr"]["model_path"] = ""
    config["models"]["root_dir"] = str(root / "models")
    return config


def write_files(model_dir: Path, files: list[str]) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for file_name in files:
        (model_dir / file_name).write_text("model", encoding="utf-8")


def test_model_catalog_manages_aligner_but_asr_catalog_excludes_it(tmp_path: Path) -> None:
    service = ModelService(make_config(tmp_path))

    catalog_names = [entry.name for entry in service.get_catalog()]
    asr_names = [entry.name for entry in service.get_asr_catalog()]

    assert QWEN3_FORCE_ALIGNER_GGUF_06B_ID in catalog_names
    assert QWEN3_FORCE_ALIGNER_GGUF_06B_ID not in asr_names
    assert QWEN3_ASR_GGUF_06B_ID in asr_names


def test_default_config_disables_timestamps() -> None:
    assert DEFAULT_CONFIG["qwen3_asr_gguf"]["enable_timestamps"] is False
    assert any(item["name"] == QWEN3_FORCE_ALIGNER_GGUF_06B_ID for item in DEFAULT_MODEL_CATALOG)
    aligner = next(item for item in DEFAULT_MODEL_CATALOG if item["name"] == QWEN3_FORCE_ALIGNER_GGUF_06B_ID)
    assert aligner["download_sources"][0]["name"] == "modelscope"
    assert aligner["download_sources"][1]["name"] == "github"
    assert aligner["download_sources"][1]["url"].endswith("Qwen3-ForceAligner-0.6B-gguf.zip")
    aligner_files = aligner["download_sources"][0]["files"]
    assert aligner["estimated_size_bytes"] == sum(int(item["size"]) for item in aligner_files)
    assert [item["size"] for item in aligner_files] == [
        20_876_727,
        164_176_179,
        484_399_552,
    ]


def test_alignment_items_are_grouped_into_sentence_timeline() -> None:
    items = [
        SimpleNamespace(text="你", start_time=0.0, end_time=0.1),
        SimpleNamespace(text="好", start_time=0.1, end_time=0.2),
        SimpleNamespace(text="。", start_time=0.2, end_time=0.2),
        SimpleNamespace(text="NoisNote", start_time=0.3, end_time=0.8),
        SimpleNamespace(text=" ", start_time=0.8, end_time=0.8),
        SimpleNamespace(text="ready", start_time=0.8, end_time=1.1),
        SimpleNamespace(text="?", start_time=1.1, end_time=1.1),
    ]

    timeline = alignment_items_to_timeline(items)

    assert [(item.start, item.end, item.text) for item in timeline] == [
        (0.0, 0.2, "你好。"),
        (0.3, 1.1, "NoisNote ready?"),
    ]
    assert [token.text for token in timeline[0].tokens] == ["你", "好", "。"]


def test_timeline_dicts_preserve_tokens_and_html_highlights_active_token() -> None:
    timeline = timeline_from_dicts(
        [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "你好。",
                "tokens": [
                    {"start": 0.0, "end": 0.4, "text": "你"},
                    {"start": 0.4, "end": 0.9, "text": "好"},
                    {"start": 0.9, "end": 1.0, "text": "。"},
                ],
            }
        ]
    )

    payload = timeline_to_dicts(timeline)
    html = timeline_to_html(timeline, 0.5)

    assert payload[0]["tokens"][1]["text"] == "好"
    assert "timeline-sentence active" in html
    assert "timeline-table" in html
    assert "padding-right:28px" in html
    assert '<a name="timeline-current"></a>' in html
    assert '<span class="timeline-token">好</span>' in html


def test_timeline_html_highlights_sentence_without_tokens() -> None:
    timeline = timeline_from_dicts([{"start": 0.0, "end": 1.0, "text": "hello"}])

    html = timeline_to_html(timeline, 0.5)

    assert "timeline-sentence active" in html
    assert '<span class="timeline-token">' not in html


def test_settings_asr_dropdown_excludes_downloaded_aligner(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    write_files(tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG, QWEN3_ASR_GGUF_REQUIRED_FILES)
    write_files(
        tmp_path / "models" / QWEN3_FORCE_ALIGNER_GGUF_06B_SLUG,
        QWEN3_FORCE_ALIGNER_GGUF_REQUIRED_FILES,
    )
    manager = ModelDownloadManager(config)
    panel = SettingsPanel(config, manager)
    try:
        dropdown_items = [panel.asr_model.itemData(index) for index in range(panel.asr_model.count())]
        downloaded_names = [
            panel.model_manager.downloaded_group.child(index).data(0, 0)
            for index in range(panel.model_manager.downloaded_group.childCount())
        ]

        assert QWEN3_ASR_GGUF_06B_ID in dropdown_items
        assert QWEN3_FORCE_ALIGNER_GGUF_06B_ID not in dropdown_items
        assert any("ForceAligner" in name for name in downloaded_names)

        panel.enable_timestamps.setChecked(True)
        updated = panel.updated_config()
        assert updated["qwen3_asr_gguf"]["enable_timestamps"] is True
    finally:
        panel.close()
        manager.deleteLater()
        app.processEvents()


def test_transcription_engine_enables_timestamps_only_when_aligner_complete(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config["qwen3_asr_gguf"]["enable_timestamps"] = True
    write_files(tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG, QWEN3_ASR_GGUF_REQUIRED_FILES)
    write_files(
        tmp_path / "models" / QWEN3_FORCE_ALIGNER_GGUF_06B_SLUG,
        QWEN3_FORCE_ALIGNER_GGUF_REQUIRED_FILES,
    )

    runtime_config = TranscriptionEngine(config)._build_runtime_config()

    assert runtime_config.request_timestamps is True
    assert runtime_config.enable_timestamps is True
    assert runtime_config.aligner_model_name == QWEN3_FORCE_ALIGNER_GGUF_06B_ID
    assert runtime_config.aligner_model_dir == (
        tmp_path / "models" / QWEN3_FORCE_ALIGNER_GGUF_06B_SLUG
    ).resolve()
    assert runtime_config.timestamp_degrade_reason == ""


def test_transcription_engine_downgrades_when_aligner_missing(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config["qwen3_asr_gguf"]["enable_timestamps"] = True
    write_files(tmp_path / "models" / QWEN3_ASR_GGUF_06B_SLUG, QWEN3_ASR_GGUF_REQUIRED_FILES)

    runtime_config = TranscriptionEngine(config)._build_runtime_config()

    assert runtime_config.request_timestamps is True
    assert runtime_config.enable_timestamps is False
    assert runtime_config.timestamp_degrade_reason == "aligner_model_incomplete"


def test_history_timeline_export_and_clear_generated_results(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    record = service.create_record()
    record.audio_path.write_bytes(b"audio")
    record = service.refresh_metadata(record)
    service.save_transcript(record, "hello")
    service.save_summary(record, "# summary")
    service.save_timeline(
        record,
        [
            {"start": 0.0, "end": 1.2, "text": "hello"},
            {"start": 1.2, "end": 2.0, "text": "world"},
        ],
    )
    record = service.refresh_metadata(record)

    srt_path = service.export_timeline_srt(record)
    markdown_path = service.export_summary_markdown(record)

    assert record.has_timeline
    assert "00:00:00,000 --> 00:00:01,200" in srt_path.read_text(encoding="utf-8")
    assert markdown_path.read_text(encoding="utf-8") == "# summary"

    cleared = service.clear_generated_results(record)
    assert not cleared.timeline_path.exists()
    assert not (cleared.record_dir / "transcript.srt").exists()


def test_history_read_timeline_preserves_saved_items_without_auto_grouping(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    record = service.create_record()
    service.save_timeline(
        record,
        [
            {"start": 0.0, "end": 0.1, "text": "你"},
            {"start": 0.1, "end": 0.2, "text": "好"},
            {"start": 0.2, "end": 0.2, "text": "。"},
            {"start": 0.3, "end": 0.4, "text": "可"},
            {"start": 0.4, "end": 0.5, "text": "用"},
            {"start": 0.5, "end": 0.5, "text": "！"},
        ],
    )

    items = service.read_timeline(record)
    assert [(item["start"], item["end"], item["text"]) for item in items] == [
        (0.0, 0.1, "你"),
        (0.1, 0.2, "好"),
        (0.2, 0.2, "。"),
        (0.3, 0.4, "可"),
        (0.4, 0.5, "用"),
        (0.5, 0.5, "！"),
    ]
    assert "tokens" not in items[0]


def test_main_window_shows_timeline_tab_only_when_record_has_timeline(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    config = make_config(tmp_path)
    monkeypatch.setattr("src.app.main_window.get_config", lambda: config)
    monkeypatch.setattr("src.app.main_window.ensure_dirs", lambda _config=None: None)
    monkeypatch.setattr("src.app.main_window.AudioRecorder", lambda: None)
    service = HistoryService(tmp_path / "data")
    record = service.create_record()
    record.audio_path.write_bytes(b"audio")
    service.save_transcript(record, "hello")
    service.save_timeline(record, [{"start": 0.0, "end": 1.0, "text": "hello"}])

    window = MainWindow()
    try:
        window.history_service = service
        record = service.scan()[0]
        window._load_history_record(record)

        assert not window.timeline_tab_button.isHidden()
        assert "00:00.000 - 00:01.000" in window.timeline_text.toPlainText()

        service.clear_generated_results(record)
        record = service.scan()[0]
        window._load_history_record(record)
        assert window.timeline_tab_button.isHidden()
    finally:
        window.close()
        app.processEvents()
