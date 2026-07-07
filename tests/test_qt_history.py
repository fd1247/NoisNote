from __future__ import annotations

import wave
import json
import shutil
from datetime import datetime
from pathlib import Path

from src.history.service import HistoryRecord, HistoryService, HistoryStatus


def write_wav(path: Path, frames: int = 16000, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames)


def test_notebook_defaults_include_existing_data_dir(tmp_path: Path) -> None:
    from src.app.config import default_notebooks, get_output_dir, normalize_notebooks

    config = {"data_root": str(tmp_path)}
    notebooks, changed = normalize_notebooks(config)

    assert changed is True
    assert notebooks == [
        {
            "id": "default",
            "name": "默认笔记本",
            "path": str(get_output_dir(config)),
            "is_default": True,
        }
    ]
    assert config["notebooks"] == notebooks


def test_notebook_normalization_preserves_user_notebook(tmp_path: Path) -> None:
    from src.app.config import normalize_notebooks

    custom_dir = tmp_path / "work"
    custom_dir.mkdir()
    config = {
        "data_root": str(tmp_path / "root"),
        "notebooks": [
            {"id": "work", "name": "工作", "path": str(custom_dir), "is_default": False}
        ],
    }

    notebooks, changed = normalize_notebooks(config)

    assert changed is True
    assert notebooks[0]["id"] == "default"
    assert notebooks[0]["is_default"] is True
    assert notebooks[1] == {
        "id": "work",
        "name": "工作",
        "path": str(custom_dir),
        "is_default": False,
    }


def test_notebook_normalization_removes_missing_user_notebook(tmp_path: Path) -> None:
    from src.app.config import normalize_notebooks

    missing_dir = tmp_path / "missing"
    config = {
        "data_root": str(tmp_path / "root"),
        "active_notebook_id": "missing",
        "last_selected_record_key": "missing:old-record",
        "notebooks": [
            {
                "id": "missing",
                "name": "Missing",
                "path": str(missing_dir),
                "is_default": False,
            }
        ],
    }

    notebooks, changed = normalize_notebooks(config)

    assert changed is True
    assert [item["id"] for item in notebooks] == ["default"]
    assert config["notebooks"] == notebooks
    assert config["active_notebook_id"] == "default"
    assert config["last_selected_record_key"] == ""
    assert not missing_dir.exists()


def test_notebook_normalization_removes_file_backed_user_notebook(tmp_path: Path) -> None:
    from src.app.config import normalize_notebooks

    file_path = tmp_path / "not-a-dir"
    file_path.write_text("", encoding="utf-8")
    config = {
        "data_root": str(tmp_path / "root"),
        "notebooks": [
            {"id": "bad", "name": "Bad", "path": str(file_path), "is_default": False}
        ],
    }

    notebooks, changed = normalize_notebooks(config)

    assert changed is True
    assert [item["id"] for item in notebooks] == ["default"]
    assert file_path.is_file()


def test_notebook_normalization_preserves_default_notebook_name(tmp_path: Path) -> None:
    from src.app.config import get_output_dir, normalize_notebooks

    config = {
        "data_root": str(tmp_path),
        "last_selected_record_keys": {},
        "notebooks": [
            {
                "id": "default",
                "name": "主笔记本",
                "path": str(get_output_dir({"data_root": str(tmp_path)})),
                "is_default": True,
            }
        ],
    }

    notebooks, changed = normalize_notebooks(config)

    assert notebooks[0]["id"] == "default"
    assert notebooks[0]["name"] == "主笔记本"
    assert changed is False


def test_notebook_normalization_dedupes_equivalent_paths(tmp_path: Path) -> None:
    from src.app.config import get_output_dir, normalize_notebooks

    config = {
        "data_root": str(tmp_path / "root"),
        "notebooks": [
            {
                "id": "duplicate",
                "name": "重复",
                "path": str(tmp_path / "root" / ".." / "root" / "data"),
                "is_default": False,
            }
        ],
    }

    notebooks, changed = normalize_notebooks(config)

    assert changed is True
    assert notebooks == [
        {
            "id": "default",
            "name": "默认笔记本",
            "path": str(get_output_dir(config)),
            "is_default": True,
        }
    ]
    assert config["notebooks"] == notebooks


def test_ensure_dirs_does_not_create_user_notebook_paths(monkeypatch, tmp_path: Path) -> None:
    from src.app import config as config_module

    data_root = tmp_path / "root"
    custom_dir = tmp_path / "external" / "work"
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path / "config")

    config_module.ensure_dirs(
        {
            "data_root": str(data_root),
            "notebooks": [
                {
                    "id": "default",
                    "name": "默认笔记本",
                    "path": str(data_root / "data"),
                    "is_default": True,
                },
                {
                    "id": "work",
                    "name": "工作",
                    "path": str(custom_dir),
                    "is_default": False,
                },
            ],
        }
    )

    assert (data_root / "data").is_dir()
    assert not custom_dir.exists()


def test_scan_multiple_notebooks_preserves_default_layout(tmp_path: Path) -> None:
    default_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    write_wav(default_dir / "default-record" / "audio.wav")
    write_wav(work_dir / "work-record" / "audio.wav")

    notebooks = [
        {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
        {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
    ]

    records = HistoryService.from_notebooks(notebooks).scan()

    assert {record.record_id for record in records} == {"default-record", "work-record"}
    by_id = {record.record_id: record for record in records}
    assert by_id["default-record"].notebook_id == "default"
    assert by_id["default-record"].notebook_name == "默认笔记本"
    assert by_id["default-record"].notebook_path == default_dir
    assert by_id["work-record"].notebook_id == "work"
    assert by_id["work-record"].notebook_name == "工作"
    assert by_id["work-record"].notebook_path == work_dir


def test_single_directory_history_service_still_scans_old_data(tmp_path: Path) -> None:
    write_wav(tmp_path / "old-record" / "audio.wav")

    records = HistoryService(tmp_path).scan()

    assert len(records) == 1
    assert records[0].record_id == "old-record"
    assert records[0].notebook_id == "default"


def test_active_non_default_create_record_preserves_notebook(tmp_path: Path) -> None:
    default_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    notebooks = [
        {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
        {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
    ]
    service = HistoryService.from_notebooks(notebooks, active_notebook_id="work")

    created = service.create_record()
    scanned = service.scan()

    assert created.notebook_id == "work"
    assert created.notebook_name == "工作"
    assert created.notebook_path == work_dir
    assert created.record_dir.parent == work_dir
    assert len(scanned) == 1
    assert scanned[0].record_id == created.record_id
    assert scanned[0].notebook_id == "work"


def test_delete_non_active_notebook_record_uses_record_notebook_root(tmp_path: Path) -> None:
    default_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    write_wav(work_dir / "work-record" / "audio.wav")
    notebooks = [
        {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
        {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
    ]
    service = HistoryService.from_notebooks(notebooks)
    record = service.scan()[0]

    result = service.delete_record(record)

    assert result.success
    assert not record.record_dir.exists()
    assert result.deleted_paths == (work_dir / "work-record",)


def test_rename_non_active_notebook_record_uses_record_notebook_root(tmp_path: Path) -> None:
    default_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    write_wav(work_dir / "work-record" / "audio.wav")
    notebooks = [
        {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
        {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
    ]
    service = HistoryService.from_notebooks(notebooks)
    record = service.scan()[0]

    renamed = service.rename_record(record, "renamed")

    assert renamed.notebook_id == "work"
    assert renamed.record_dir == work_dir / "renamed"
    assert renamed.audio_path.exists()
    assert not (work_dir / "work-record").exists()


def test_scan_ignores_non_directory_notebook_root(tmp_path: Path) -> None:
    bad_root = tmp_path / "bad-root"
    good_root = tmp_path / "good"
    bad_root.write_text("not a directory", encoding="utf-8")
    write_wav(good_root / "good-record" / "audio.wav")
    notebooks = [
        {"id": "bad", "name": "坏路径", "path": str(bad_root), "is_default": True},
        {"id": "good", "name": "可用", "path": str(good_root), "is_default": False},
    ]

    records = HistoryService.from_notebooks(notebooks).scan()

    assert len(records) == 1
    assert records[0].record_id == "good-record"
    assert records[0].notebook_id == "good"


def test_duplicate_record_ids_across_notebooks_have_distinct_record_keys(tmp_path: Path) -> None:
    default_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    write_wav(default_dir / "meeting" / "audio.wav")
    write_wav(work_dir / "meeting" / "audio.wav")
    notebooks = [
        {"id": "default", "name": "默认笔记本", "path": str(default_dir), "is_default": True},
        {"id": "work", "name": "工作", "path": str(work_dir), "is_default": False},
    ]

    records = HistoryService.from_notebooks(notebooks).scan()

    assert {record.record_id for record in records} == {"meeting"}
    assert {record.record_key for record in records} == {"default:meeting", "work:meeting"}


def test_move_record_to_notebook_rejects_name_conflict(tmp_path: Path) -> None:
    source_root = tmp_path / "default"
    target_root = tmp_path / "work"
    write_wav(source_root / "meeting" / "audio.wav")
    write_wav(target_root / "meeting" / "audio.wav")
    service = HistoryService.from_notebooks(
        [
            {"id": "default", "name": "默认笔记本", "path": str(source_root), "is_default": True},
            {"id": "work", "name": "工作", "path": str(target_root), "is_default": False},
        ]
    )
    record = next(item for item in service.scan() if item.notebook_id == "default")

    result = service.move_record_to_notebook(record, "work")

    assert result.success is False
    assert "已存在" in result.message
    assert (source_root / "meeting").exists()
    assert (target_root / "meeting").exists()


def test_move_record_to_notebook_moves_whole_folder(tmp_path: Path) -> None:
    source_root = tmp_path / "default"
    target_root = tmp_path / "work"
    write_wav(source_root / "meeting" / "audio.wav")
    (source_root / "meeting" / "transcript.txt").write_text("text", encoding="utf-8")
    service = HistoryService.from_notebooks(
        [
            {"id": "default", "name": "默认笔记本", "path": str(source_root), "is_default": True},
            {"id": "work", "name": "工作", "path": str(target_root), "is_default": False},
        ]
    )
    record = service.scan()[0]

    result = service.move_record_to_notebook(record, "work")

    assert result.success is True
    assert not (source_root / "meeting").exists()
    assert (target_root / "meeting" / "audio.wav").exists()
    assert (target_root / "meeting" / "transcript.txt").read_text(encoding="utf-8") == "text"
    moved = HistoryService.from_notebooks(
        [
            {"id": "default", "name": "默认笔记本", "path": str(source_root), "is_default": True},
            {"id": "work", "name": "工作", "path": str(target_root), "is_default": False},
        ]
    ).scan()[0]
    assert moved.notebook_id == "work"


def test_move_record_to_notebook_uses_temporary_copy_before_source_delete(monkeypatch, tmp_path: Path) -> None:
    source_root = tmp_path / "default"
    target_root = tmp_path / "work"
    write_wav(source_root / "meeting" / "audio.wav")
    service = HistoryService.from_notebooks(
        [
            {"id": "default", "name": "默认笔记本", "path": str(source_root), "is_default": True},
            {"id": "work", "name": "工作", "path": str(target_root), "is_default": False},
        ]
    )
    record = service.scan()[0]
    copied: list[tuple[Path, Path]] = []
    deleted: list[Path] = []
    real_copytree = shutil.copytree
    real_rmtree = shutil.rmtree

    def spy_copytree(source, target, *args, **kwargs):
        copied.append((Path(source), Path(target)))
        return real_copytree(source, target, *args, **kwargs)

    def spy_rmtree(path, *args, **kwargs):
        deleted.append(Path(path))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("src.history.service.shutil.copytree", spy_copytree)
    monkeypatch.setattr("src.history.service.shutil.rmtree", spy_rmtree)

    result = service.move_record_to_notebook(record, "work")

    assert result.success is True
    assert copied[0][0] == source_root / "meeting"
    assert copied[0][1].name.startswith(".move-meeting-")
    assert source_root / "meeting" in deleted
    assert (target_root / "meeting" / "audio.wav").exists()


def test_move_record_to_notebook_rolls_back_when_source_delete_fails(monkeypatch, tmp_path: Path) -> None:
    source_root = tmp_path / "default"
    target_root = tmp_path / "work"
    write_wav(source_root / "meeting" / "audio.wav")
    service = HistoryService.from_notebooks(
        [
            {"id": "default", "name": "默认笔记本", "path": str(source_root), "is_default": True},
            {"id": "work", "name": "工作", "path": str(target_root), "is_default": False},
        ]
    )
    record = service.scan()[0]
    real_rmtree = shutil.rmtree

    def fail_source_delete(path, *args, **kwargs):
        if Path(path) == source_root / "meeting":
            raise OSError("source locked")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("src.history.service.shutil.rmtree", fail_source_delete)

    result = service.move_record_to_notebook(record, "work")

    assert result.success is False
    assert "source locked" in result.message
    assert (source_root / "meeting" / "audio.wav").exists()
    assert not (target_root / "meeting").exists()
    assert not list(target_root.glob(".move-*"))


def test_move_record_to_nested_notebook_rejects_without_side_effects(tmp_path: Path) -> None:
    source_root = tmp_path / "default"
    record_dir = source_root / "meeting"
    target_root = record_dir / "nested-notebook"
    write_wav(record_dir / "audio.wav")
    service = HistoryService.from_notebooks(
        [
            {"id": "default", "name": "默认笔记本", "path": str(source_root), "is_default": True},
            {"id": "nested", "name": "嵌套", "path": str(target_root), "is_default": False},
        ]
    )
    record = service.scan()[0]

    result = service.move_record_to_notebook(record, "nested")

    assert result.success is False
    assert record_dir.exists()
    assert not target_root.exists()


def test_scan_folder_record(tmp_path: Path) -> None:
    record_dir = tmp_path / "20260618_120000"
    write_wav(record_dir / "audio.wav")
    (record_dir / "transcript.txt").write_text("转录", encoding="utf-8")

    items = HistoryService(tmp_path).scan()

    assert len(items) == 1
    assert items[0].layout == "folder"
    assert items[0].record_id == "20260618_120000"
    assert items[0].status == HistoryStatus.TRANSCRIBED
    assert items[0].duration_seconds == 1
    assert items[0].audio_size_bytes > 0


def test_scan_organizes_flat_record_into_folder(tmp_path: Path) -> None:
    audio_path = tmp_path / "20260618_120000.wav"
    write_wav(audio_path, frames=8000)
    audio_path.with_suffix(".txt").write_text("转录", encoding="utf-8")

    items = HistoryService(tmp_path).scan()

    assert len(items) == 1
    assert items[0].layout == "folder"
    assert items[0].record_id == "20260618_120000"
    assert items[0].status == HistoryStatus.TRANSCRIBED
    assert items[0].has_transcript
    assert not items[0].has_summary
    assert items[0].audio_path == tmp_path / "20260618_120000" / "audio.wav"
    assert items[0].transcript_path == tmp_path / "20260618_120000" / "transcript.txt"
    assert items[0].summary_path == tmp_path / "20260618_120000" / "summary.md"
    assert not audio_path.exists()
    assert not audio_path.with_suffix(".txt").exists()


def test_save_text_for_folder_records(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "20260618_120000"
    write_wav(folder / "audio.wav")
    folder_record = service.scan()[0]

    service.save_transcript(folder_record, "folder transcript")
    service.save_summary(folder_record, "folder summary")
    folder_record = service.scan()[0]

    assert service.read_transcript(folder_record) == "folder transcript"
    assert service.read_summary(folder_record) == "folder summary"
    assert folder_record.summary_path == folder / "summary.md"
    assert (folder / "summary.md").read_text(encoding="utf-8") == "folder summary"
    assert folder_record.status == HistoryStatus.SUMMARIZED
    assert (folder / "metadata.json").exists()


def test_scan_backfills_missing_metadata_defaults(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "20260618_120000"
    write_wav(folder / "audio.wav")

    record = service.scan()[0]
    metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))

    assert metadata["version"] == 1
    assert metadata["record_id"] == "20260618_120000"
    assert metadata["audio_file"] == "audio.wav"
    assert set(metadata["processing"]) == {"transcription", "summary"}
    assert metadata["processing"]["transcription"]["status"] == "pending"


def test_scan_ignores_corrupt_metadata_and_rewrites_defaults(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "broken"
    write_wav(folder / "audio.wav")
    (folder / "metadata.json").write_text("{not json", encoding="utf-8")

    record = service.scan()[0]
    metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))

    assert record.record_id == "broken"
    assert metadata["record_id"] == "broken"
    assert metadata["processing"]["summary"]["status"] == "pending"


def test_mark_error_persists_failure_message(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "20260618_120000"
    write_wav(folder / "audio.wav")
    record = service.scan()[0]

    failed = service.mark_error(record, "模型加载失败")
    scanned = service.scan()[0]

    assert failed.status == HistoryStatus.ERROR
    assert scanned.status == HistoryStatus.ERROR
    assert scanned.error_message == "模型加载失败"
    assert '"status": "error"' in (folder / "metadata.json").read_text(encoding="utf-8")
    assert "模型加载失败" in (folder / "metadata.json").read_text(encoding="utf-8")


def test_mark_error_survives_rescan_with_processing_step(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "20260618_120000"
    write_wav(folder / "audio.wav")
    record = service.scan()[0]

    service.mark_error(record, "未识别到有效语音内容", step="transcription", elapsed_seconds=0.1)
    scanned = HistoryService(tmp_path).scan()[0]
    metadata = json.loads(scanned.metadata_path.read_text(encoding="utf-8"))

    assert scanned.status == HistoryStatus.ERROR
    assert scanned.error_message == "未识别到有效语音内容"
    assert metadata["processing"]["transcription"]["status"] == "failed"
    assert metadata["processing"]["transcription"]["error_message"] == "未识别到有效语音内容"


def test_processing_metadata_records_context_and_elapsed(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "20260618_120000"
    write_wav(folder / "audio.wav")
    record = service.scan()[0]

    record = service.mark_processing_started(
        record,
        "transcription",
        {"model": "iic/test", "model_path": "C:/models/test", "adapter": "paraformer"},
    )
    service.save_transcript(record, "转录")
    record = service.mark_processing_completed(record, "transcription", 1.23456)
    metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))

    step = metadata["processing"]["transcription"]
    assert step["status"] == "completed"
    assert step["model"] == "iic/test"
    assert step["model_path"] == "C:/models/test"
    assert step["adapter"] == "paraformer"
    assert step["elapsed_seconds"] == 1.235
    assert step["error_message"] == ""


def test_processing_success_clears_previous_error(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "20260618_120000"
    write_wav(folder / "audio.wav")
    record = service.scan()[0]

    failed = service.mark_error(record, "第一次失败", step="transcription", elapsed_seconds=0.5)
    service.save_transcript(failed, "重新转录成功")
    completed = service.mark_processing_completed(failed, "transcription", 0.25)
    metadata = json.loads(completed.metadata_path.read_text(encoding="utf-8"))

    assert "error_message" not in metadata
    assert metadata["processing"]["transcription"]["status"] == "completed"
    assert metadata["processing"]["transcription"]["error_message"] == ""


def test_asr_metadata_is_preserved_after_refresh(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "20260618_120000"
    write_wav(folder / "audio.wav")
    record = service.scan()[0]

    record = service.save_asr_metadata(
        record,
        {
            "engine": "qwen3-asr-gguf",
            "model_name": "Qwen3-ASR-0.6B-GGUF",
            "timings": {"transcribe_seconds": 1.23},
        },
    )
    service.save_transcript(record, "转录")
    refreshed = service.refresh_metadata(record)
    metadata = json.loads(refreshed.metadata_path.read_text(encoding="utf-8"))

    assert metadata["asr"]["engine"] == "qwen3-asr-gguf"
    assert metadata["asr"]["timings"]["transcribe_seconds"] == 1.23


def test_clear_generated_results_keeps_audio_and_metadata(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    folder = tmp_path / "20260618_120000"
    write_wav(folder / "audio.wav")
    record = service.scan()[0]
    service.save_transcript(record, "旧转录")
    service.save_summary(record, "旧总结")
    record.markdown_path.write_text("旧导出", encoding="utf-8")
    record = service.mark_error(service.scan()[0], "旧错误", step="summary")

    cleared = service.clear_generated_results(record)
    metadata = json.loads(cleared.metadata_path.read_text(encoding="utf-8"))

    assert cleared.audio_path.exists()
    assert cleared.metadata_path.exists()
    assert not cleared.transcript_path.exists()
    assert not cleared.summary_path.exists()
    assert not cleared.markdown_path.exists()
    assert cleared.status == HistoryStatus.AUDIO_ONLY
    assert "error_message" not in metadata
    assert metadata["processing"]["transcription"]["status"] == "pending"
    assert metadata["processing"]["summary"]["status"] == "pending"


def test_clear_generated_results_rejects_record_root(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    unsafe = HistoryRecord(
        record_id="root",
        layout="folder",
        record_dir=tmp_path,
        audio_path=tmp_path / "audio.wav",
        transcript_path=tmp_path / "transcript.txt",
        summary_path=tmp_path / "summary.md",
        markdown_path=tmp_path / "export.md",
        metadata_path=tmp_path / "metadata.json",
        created_at=datetime.now(),
        duration_seconds=None,
        audio_size_bytes=0,
        total_size_bytes=0,
        status=HistoryStatus.AUDIO_ONLY,
    )

    try:
        service.clear_generated_results(unsafe)
    except ValueError as exc:
        assert "不安全" in str(exc)
    else:
        raise AssertionError("expected unsafe record root to be rejected")


def test_adopt_audio_file_moves_recording_into_folder(tmp_path: Path) -> None:
    source = tmp_path / "20260618_120000.wav"
    write_wav(source)

    service = HistoryService(tmp_path)
    record = service.adopt_audio_file(source)

    assert record.layout == "folder"
    assert record.audio_path.name == "audio.wav"
    assert record.audio_path.exists()
    assert not source.exists()
    assert (record.record_dir / "metadata.json").exists()
    assert service.scan()[0].record_id == "20260618_120000"


def test_import_audio_file_records_source_path_without_copying(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source = source_dir / "meeting.wav"
    write_wav(source)

    service = HistoryService(tmp_path / "records")
    record = service.import_audio_file(source)

    assert record.layout == "folder"
    assert record.record_id == "meeting"
    assert record.audio_path == source
    assert not (record.record_dir / "audio.wav").exists()
    assert source.exists()
    assert record.storage_mode == "reference"

    metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_type"] == "imported"
    assert metadata["source_path"] == str(source)
    assert metadata["original_file_path"] == str(source)
    assert metadata["original_file_name"] == "meeting.wav"
    assert metadata["storage_mode"] == "reference"
    assert metadata["import_strategy"] == "reference"
    assert metadata["source_size_bytes"] == source.stat().st_size
    assert metadata["processing"]["transcription"]["status"] == "pending"

    service.save_transcript(record, "transcript")
    metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_type"] == "imported"
    assert metadata["storage_mode"] == "reference"


def test_import_audio_file_preserves_non_wav_extension(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "voice.m4a"
    source.write_bytes(b"fake m4a data")

    service = HistoryService(tmp_path / "records")
    record = service.import_audio_file(source)

    assert record.audio_path == source
    assert record.audio_path.read_bytes() == b"fake m4a data"
    assert not (record.record_dir / "audio.m4a").exists()
    assert record.duration_seconds is None
    assert source.exists()


def test_import_audio_file_can_store_probed_mp3_duration(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "voice.mp3"
    source.write_bytes(b"fake mp3 data")

    service = HistoryService(tmp_path / "records")
    record = service.import_audio_file(
        source,
        duration_seconds=49.2,
        audio_format={"sample_rate": 44100, "channels": 2, "format": "mp3", "source_format": "mp3"},
        source_kind="local_audio",
    )

    metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))
    assert record.duration_seconds == 49.2
    assert record.duration_text == "00:49"
    assert metadata["duration_seconds"] == 49.2
    assert metadata["audio_format"]["sample_rate"] == 44100
    assert metadata["storage_mode"] == "reference"


def test_copy_imported_audio_file_preserves_extension_and_duration(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "测试音频.mp3"
    source.write_bytes(b"fake mp3 data")

    service = HistoryService(tmp_path / "records")
    record = service.copy_imported_audio_file(
        source,
        duration_seconds=49.2,
        audio_format={"sample_rate": 44100, "channels": 2, "format": "mp3"},
        source_kind="local_audio",
    )

    assert record.audio_path == record.record_dir / "测试音频.mp3"
    assert record.audio_path.exists()
    assert source.exists()
    assert record.duration_text == "00:49"
    assert record.duration_seconds == 49.2
    assert record.storage_mode == HistoryService.STORAGE_COPIED
    metadata = json.loads(record.metadata_path.read_text(encoding="utf-8"))
    assert metadata["audio_file"] == "测试音频.mp3"
    assert metadata["duration_seconds"] == 49.2
    assert metadata["storage_mode"] == "copied"


def test_import_audio_file_uses_unique_folder_for_duplicate_names(tmp_path: Path) -> None:
    source_a = tmp_path / "a" / "meeting.wav"
    source_b = tmp_path / "b" / "meeting.wav"
    write_wav(source_a)
    write_wav(source_b)

    service = HistoryService(tmp_path / "records")
    first = service.import_audio_file(source_a)
    second = service.import_audio_file(source_b)

    assert first.record_id == "meeting"
    assert second.record_id == "meeting-02"
    assert first.audio_path == source_a
    assert second.audio_path == source_b
    assert source_a.exists()
    assert source_b.exists()


def test_create_remote_record_sanitizes_long_windows_title(tmp_path: Path) -> None:
    service = HistoryService(tmp_path / "records")
    info = type(
        "RemoteInfo",
        (),
        {
            "title": 'CON: a very long youtube shorts title with ? invalid | filename * chars / and more text ' * 3,
            "duration_seconds": 12.0,
            "webpage_url": "https://www.youtube.com/shorts/qWFo8GKXHq8",
            "url": "https://www.youtube.com/shorts/qWFo8GKXHq8",
            "extractor": "youtube",
            "video_id": "qWFo8GKXHq8",
        },
    )()

    record = service.create_remote_record(info)

    assert record.record_dir.exists()
    assert len(record.record_id) <= 80
    assert not any(ch in record.record_id for ch in '<>:"/\\|?*')


def test_scans_existing_copied_import_records(tmp_path: Path) -> None:
    record_dir = tmp_path / "records" / "meeting"
    write_wav(record_dir / "audio.wav")
    metadata = {
        "version": HistoryService.METADATA_VERSION,
        "record_id": "meeting",
        "created_at": "2026-06-18T12:00:00",
        "duration_seconds": None,
        "audio_file": "audio.wav",
        "transcript_file": "transcript.txt",
        "summary_file": "summary.md",
        "markdown_file": "export.md",
        "status": "audio_only",
        "source_type": "imported",
        "source_kind": "local_audio",
        "original_file_path": str(tmp_path / "source" / "meeting.wav"),
        "storage_mode": "copied",
        "processing": {
            "transcription": {"status": "pending"},
            "summary": {"status": "pending"},
        },
    }
    (record_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    record = HistoryService(tmp_path / "records").scan()[0]

    assert record.audio_path == record_dir / "audio.wav"
    assert record.storage_mode == "copied"


def test_rename_record_updates_folder_and_metadata(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    write_wav(tmp_path / "20260618_120000" / "audio.wav")
    record = service.scan()[0]

    renamed = service.rename_record(record, "会议纪要")

    assert renamed.record_id == "会议纪要"
    assert renamed.display_name == "会议纪要"
    assert renamed.record_dir == tmp_path / "会议纪要"
    assert renamed.audio_path.exists()
    assert not (tmp_path / "20260618_120000").exists()
    assert '"record_id": "会议纪要"' in (renamed.record_dir / "metadata.json").read_text(
        encoding="utf-8"
    )


def test_delete_folder_record_keeps_other_records(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    write_wav(tmp_path / "20260618_120000" / "audio.wav")
    write_wav(tmp_path / "20260618_130000" / "audio.wav")
    records = service.scan()
    target = [item for item in records if item.record_id == "20260618_120000"][0]

    result = service.delete_record(target)

    assert result.success
    assert not (tmp_path / "20260618_120000").exists()
    assert (tmp_path / "20260618_130000" / "audio.wav").exists()


def test_delete_organized_flat_record_removes_record_folder_only(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    audio_path = tmp_path / "20260618_120000.wav"
    write_wav(audio_path)
    audio_path.with_suffix(".txt").write_text("转录", encoding="utf-8")
    audio_path.with_suffix(".md").write_text("导出", encoding="utf-8")
    sibling = tmp_path / "20260618_120000_extra.wav"
    write_wav(sibling)
    record = [item for item in service.scan() if item.record_id == "20260618_120000"][0]

    result = service.delete_record(record)

    assert result.success
    assert not audio_path.exists()
    assert not audio_path.with_suffix(".txt").exists()
    assert not audio_path.with_suffix(".md").exists()
    assert not (tmp_path / "20260618_120000").exists()
    assert not sibling.exists()
    assert (tmp_path / "20260618_120000_extra" / "audio.wav").exists()


def test_delete_rejects_unsafe_paths(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    outside = tmp_path.parent / "outside_history_file.txt"
    outside.write_text("keep", encoding="utf-8")
    unsafe = HistoryRecord(
        record_id="unsafe",
        layout="folder",
        record_dir=tmp_path,
        audio_path=outside,
        transcript_path=outside.with_suffix(".txt"),
        summary_path=outside.with_name("outside_history_file_summary.md"),
        markdown_path=outside.with_suffix(".md"),
        metadata_path=outside.with_suffix(".json"),
        created_at=datetime.now(),
        duration_seconds=None,
        audio_size_bytes=outside.stat().st_size,
        total_size_bytes=outside.stat().st_size,
        status=HistoryStatus.AUDIO_ONLY,
    )

    result = service.delete_record(unsafe)

    assert not result.success
    assert outside.exists()
    assert tmp_path in result.skipped_paths

    root_record = HistoryRecord(
        record_id="root",
        layout="folder",
        record_dir=tmp_path,
        audio_path=tmp_path / "audio.wav",
        transcript_path=tmp_path / "transcript.txt",
        summary_path=tmp_path / "summary.md",
        markdown_path=tmp_path / "export.md",
        metadata_path=tmp_path / "metadata.json",
        created_at=datetime.now(),
        duration_seconds=None,
        audio_size_bytes=0,
        total_size_bytes=0,
        status=HistoryStatus.MISSING_AUDIO,
    )

    root_result = service.delete_record(root_record)

    assert not root_result.success
    assert tmp_path.exists()
