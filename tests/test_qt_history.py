from __future__ import annotations

import wave
import json
from datetime import datetime
from pathlib import Path

from audio_recorder.history.service import HistoryRecord, HistoryService, HistoryStatus


def write_wav(path: Path, frames: int = 16000, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames)


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
    audio_path.with_name("20260618_120000_summary.txt").write_text("总结", encoding="utf-8")

    items = HistoryService(tmp_path).scan()

    assert len(items) == 1
    assert items[0].layout == "folder"
    assert items[0].record_id == "20260618_120000"
    assert items[0].status == HistoryStatus.SUMMARIZED
    assert items[0].has_transcript
    assert items[0].has_summary
    assert items[0].audio_path == tmp_path / "20260618_120000" / "audio.wav"
    assert items[0].transcript_path == tmp_path / "20260618_120000" / "transcript.txt"
    assert items[0].summary_path == tmp_path / "20260618_120000" / "summary.txt"
    assert not audio_path.exists()
    assert not audio_path.with_suffix(".txt").exists()
    assert not audio_path.with_name("20260618_120000_summary.txt").exists()


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
    service.save_markdown(record, "旧导出")
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
        summary_path=tmp_path / "summary.txt",
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
        "summary_file": "summary.txt",
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
    audio_path.with_name("20260618_120000_summary.txt").write_text("总结", encoding="utf-8")
    audio_path.with_suffix(".md").write_text("导出", encoding="utf-8")
    sibling = tmp_path / "20260618_120000_extra.wav"
    write_wav(sibling)
    record = [item for item in service.scan() if item.record_id == "20260618_120000"][0]

    result = service.delete_record(record)

    assert result.success
    assert not audio_path.exists()
    assert not audio_path.with_suffix(".txt").exists()
    assert not audio_path.with_name("20260618_120000_summary.txt").exists()
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
        summary_path=outside.with_name("outside_history_file_summary.txt"),
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
        summary_path=tmp_path / "summary.txt",
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
