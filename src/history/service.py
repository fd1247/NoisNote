"""Qt 历史记录管理模块。"""
from __future__ import annotations

import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..asr.timestamps import timeline_from_dicts, timeline_to_dicts, timeline_to_srt
from ..utils.remote_urls import canonicalize_video_url
from .types import DeleteResult, HistoryRecord, MoveRecordResult, NotebookConfig
from .storage import HistoryStorageMixin


class HistoryService(HistoryStorageMixin):
    """扫描、读写和删除历史记录。"""

    METADATA_VERSION = 1
    STORAGE_COPIED = "copied"
    STORAGE_REFERENCE = "reference"
    FOLDER_AUDIO = "audio.wav"
    FOLDER_TRANSCRIPT = "transcript.txt"
    FOLDER_SUMMARY = "summary.md"
    FOLDER_MARKDOWN = "export.md"
    FOLDER_TIMELINE = "timeline.json"
    FOLDER_METADATA = "metadata.json"
    FOLDER_EXTERNAL_SUBTITLE = "external_subtitle.srt"
    PROCESSING_STEPS = ("transcription", "summary")

    def __init__(
        self,
        recordings_dir: str | Path,
        notebooks: list[NotebookConfig] | None = None,
        active_notebook_id: str = "default",
    ):
        self.recordings_dir = Path(recordings_dir)
        self.notebooks = notebooks or [
            NotebookConfig("default", "默认笔记本", self.recordings_dir, True)
        ]
        self.active_notebook_id = active_notebook_id

    @classmethod
    def from_notebooks(
        cls,
        notebooks_config: list[dict],
        active_notebook_id: str = "default",
    ) -> "HistoryService":
        notebooks: list[NotebookConfig] = []
        for item in notebooks_config:
            if not isinstance(item, dict):
                continue
            notebook_id = str(item.get("id") or "").strip()
            path_text = str(item.get("path") or "").strip()
            if not notebook_id or not path_text:
                continue
            path = Path(path_text).expanduser()
            notebooks.append(
                NotebookConfig(
                    notebook_id=notebook_id,
                    name=str(item.get("name") or path.name or "笔记本"),
                    path=path,
                    is_default=bool(item.get("is_default", False)),
                )
            )
        if not notebooks:
            notebooks = [NotebookConfig("default", "默认笔记本", Path("."), True)]
        active = next(
            (item for item in notebooks if item.notebook_id == active_notebook_id),
            notebooks[0],
        )
        return cls(active.path, notebooks, active.notebook_id)

    def scan(self) -> list[HistoryRecord]:
        """扫描所有笔记本下的记录目录。"""
        records: list[HistoryRecord] = []
        for notebook in self.notebooks:
            records.extend(self._scan_notebook(notebook))
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def _scan_notebook(self, notebook: NotebookConfig) -> list[HistoryRecord]:
        if not notebook.path.exists() or not notebook.path.is_dir():
            return []
        if notebook.notebook_id == self.active_notebook_id:
            self.recordings_dir = notebook.path
        if notebook.is_default or notebook.notebook_id == self.active_notebook_id:
            try:
                self.organize_flat_files(notebook.path)
            except OSError:
                return []
        records: list[HistoryRecord] = []
        try:
            children = list(notebook.path.iterdir())
        except OSError:
            return []
        for child in children:
            if child.is_dir():
                record = self._build_folder_record(child, notebook)
                if record:
                    self._ensure_metadata_file(record)
                    records.append(record)
        return records

    def organize_flat_files(self, recordings_dir: Path | None = None) -> int:
        """把录音根目录下散落的旧文件整理成记录文件夹。"""
        root = recordings_dir or self.recordings_dir
        if not root.exists():
            return 0

        migrated = 0
        previous_dir = self.recordings_dir
        self.recordings_dir = root
        try:
            for audio_path in list(root.glob("*.wav")):
                if not audio_path.is_file():
                    continue
                if self._organize_flat_audio(audio_path):
                    migrated += 1
        finally:
            self.recordings_dir = previous_dir
        return migrated

    def _active_notebook(self) -> NotebookConfig:
        return next(
            (item for item in self.notebooks if item.notebook_id == self.active_notebook_id),
            self.notebooks[0],
        )

    def _notebook_for_record_dir(self, record_dir: Path) -> NotebookConfig:
        target = record_dir.resolve(strict=False)
        matches: list[NotebookConfig] = []
        for notebook in self.notebooks:
            root = notebook.path.resolve(strict=False)
            try:
                target.relative_to(root)
            except ValueError:
                continue
            matches.append(notebook)
        if matches:
            return max(matches, key=lambda item: len(item.path.resolve(strict=False).parts))
        active = self._active_notebook()
        if record_dir.parent == active.path:
            return active
        return NotebookConfig("default", "默认笔记本", record_dir.parent, True)

    def _record_root(self, record: HistoryRecord) -> Path:
        if record.notebook_path:
            return record.notebook_path
        return self._notebook_for_record_dir(record.record_dir).path

    def create_record(self) -> HistoryRecord:
        """创建一条空记录目录。"""
        record_id = self._unique_record_id(datetime.now().strftime("%Y%m%d_%H%M%S"))
        record_dir = self.recordings_dir / record_id
        record_dir.mkdir(parents=True, exist_ok=False)
        metadata = {
            "version": self.METADATA_VERSION,
            "record_id": record_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": None,
            "audio_file": self.FOLDER_AUDIO,
            "transcript_file": self.FOLDER_TRANSCRIPT,
            "summary_file": self.FOLDER_SUMMARY,
            "markdown_file": self.FOLDER_MARKDOWN,
            "source_kind": "recording",
            "original_file_path": "",
            "normalized_audio_path": "",
            "audio_format": {},
            "input_error": None,
            "last_error": None,
            "processing": self._default_processing_metadata(),
        }
        self._write_json(record_dir / self.FOLDER_METADATA, metadata)
        return self._build_folder_record(record_dir)  # type: ignore[return-value]

    def adopt_audio_file(self, audio_path: Path) -> HistoryRecord:
        """把录音文件纳入独立记录文件夹。"""
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        source = Path(audio_path)
        record_id = self._unique_record_id(source.stem or datetime.now().strftime("%Y%m%d_%H%M%S"))
        record_dir = self.recordings_dir / record_id
        target = record_dir / self.FOLDER_AUDIO

        if source.resolve(strict=False) == target.resolve(strict=False):
            return self._build_folder_record(record_dir)  # type: ignore[return-value]

        record_dir.mkdir(parents=True, exist_ok=False)
        shutil.move(str(source), str(target))

        created_at = self._parse_timestamp(record_id) or datetime.fromtimestamp(target.stat().st_mtime)
        metadata = {
            "version": self.METADATA_VERSION,
            "record_id": record_id,
            "created_at": created_at.isoformat(timespec="seconds"),
            "duration_seconds": self._wav_duration(target),
            "audio_file": self.FOLDER_AUDIO,
            "transcript_file": self.FOLDER_TRANSCRIPT,
            "summary_file": self.FOLDER_SUMMARY,
            "markdown_file": self.FOLDER_MARKDOWN,
            "source_type": "recorded",
            "source_kind": "recording",
            "original_file_path": str(source),
            "normalized_audio_path": "",
            "audio_format": {
                "sample_rate": None,
                "channels": None,
                "format": target.suffix.lower().lstrip("."),
            },
            "input_error": None,
            "last_error": None,
            "original_file_name": source.name,
            "processing": self._default_processing_metadata(),
        }
        self._write_json(record_dir / self.FOLDER_METADATA, metadata)
        return self._build_folder_record(record_dir)  # type: ignore[return-value]

    def import_audio_file(
        self,
        audio_path: Path,
        *,
        duration_seconds: float | None = None,
        audio_format: dict[str, Any] | None = None,
        source_kind: str | None = None,
    ) -> HistoryRecord:
        """记录外部音视频文件路径，创建一条独立历史记录。"""
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        source = Path(audio_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"音频文件不存在：{source}")

        record_id = self._unique_record_id(source.stem or datetime.now().strftime("%Y%m%d_%H%M%S"))
        record_dir = self.recordings_dir / record_id

        record_dir.mkdir(parents=True, exist_ok=False)

        created_at = datetime.fromtimestamp(source.stat().st_mtime)
        metadata = {
            "version": self.METADATA_VERSION,
            "record_id": record_id,
            "created_at": created_at.isoformat(timespec="seconds"),
            "duration_seconds": duration_seconds,
            "audio_file": source.name,
            "transcript_file": self.FOLDER_TRANSCRIPT,
            "summary_file": self.FOLDER_SUMMARY,
            "markdown_file": self.FOLDER_MARKDOWN,
            "source_type": "imported",
            "source_kind": source_kind or self._source_kind_for_path(source),
            "source_path": str(source),
            "original_file_path": str(source),
            "normalized_audio_path": "",
            "audio_format": audio_format or {
                "sample_rate": None,
                "channels": None,
                "format": source.suffix.lower().lstrip("."),
            },
            "input_error": None,
            "last_error": None,
            "original_file_name": source.name,
            "storage_mode": self.STORAGE_REFERENCE,
            "import_strategy": self.STORAGE_REFERENCE,
            "source_size_bytes": self._file_size(source),
            "processing": self._default_processing_metadata(),
        }
        self._write_json(record_dir / self.FOLDER_METADATA, metadata)
        return self._build_folder_record(record_dir)  # type: ignore[return-value]

    def copy_imported_audio_file(
        self,
        audio_path: Path,
        *,
        duration_seconds: float | None = None,
        audio_format: dict[str, Any] | None = None,
        source_kind: str | None = None,
    ) -> HistoryRecord:
        """复制导入音视频到记录目录，保留原始扩展名。"""
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        source = Path(audio_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"音频文件不存在：{source}")

        record_id = self._unique_record_id(source.stem or datetime.now().strftime("%Y%m%d_%H%M%S"))
        record_dir = self.recordings_dir / record_id
        target = record_dir / source.name

        record_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, target)

        metadata = {
            "version": self.METADATA_VERSION,
            "record_id": record_id,
            "created_at": datetime.fromtimestamp(source.stat().st_mtime).isoformat(timespec="seconds"),
            "duration_seconds": duration_seconds,
            "audio_file": target.name,
            "transcript_file": self.FOLDER_TRANSCRIPT,
            "summary_file": self.FOLDER_SUMMARY,
            "markdown_file": self.FOLDER_MARKDOWN,
            "source_type": "imported",
            "source_kind": source_kind or self._source_kind_for_path(source),
            "source_path": str(source),
            "original_file_path": str(source),
            "normalized_audio_path": "",
            "audio_format": audio_format
            or {
                "sample_rate": None,
                "channels": None,
                "format": source.suffix.lower().lstrip("."),
            },
            "input_error": None,
            "last_error": None,
            "original_file_name": source.name,
            "storage_mode": self.STORAGE_COPIED,
            "import_strategy": self.STORAGE_COPIED,
            "source_size_bytes": self._file_size(source),
            "processing": self._default_processing_metadata(),
        }
        self._write_json(record_dir / self.FOLDER_METADATA, metadata)
        return self._build_folder_record(record_dir)  # type: ignore[return-value]

    def create_remote_record(self, info: Any) -> HistoryRecord:
        """为远程链接创建历史记录。"""
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        title = str(getattr(info, "title", "") or "remote-video")
        original_url = str(getattr(info, "url", "") or getattr(info, "webpage_url", ""))
        webpage_url = str(getattr(info, "webpage_url", "") or original_url)
        canonical_url = canonicalize_video_url(webpage_url or original_url) or webpage_url or original_url
        record_id = self._unique_record_id(title or datetime.now().strftime("%Y%m%d_%H%M%S"))
        record_dir = self.recordings_dir / record_id
        record_dir.mkdir(parents=True, exist_ok=False)
        metadata = {
            "version": self.METADATA_VERSION,
            "record_id": record_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "duration_seconds": getattr(info, "duration_seconds", None),
            "audio_file": self.FOLDER_AUDIO,
            "transcript_file": self.FOLDER_TRANSCRIPT,
            "summary_file": self.FOLDER_SUMMARY,
            "markdown_file": self.FOLDER_MARKDOWN,
            "external_subtitle_file": self.FOLDER_EXTERNAL_SUBTITLE,
            "source_type": "remote_url",
            "source_kind": "remote_url",
            "source_path": canonical_url,
            "original_file_path": original_url,
            "normalized_audio_path": "",
            "audio_format": {},
            "input_error": None,
            "last_error": None,
            "remote": {
                "url": original_url,
                "original_url": original_url,
                "webpage_url": webpage_url,
                "canonical_url": canonical_url,
                "extractor": getattr(info, "extractor", ""),
                "title": title,
                "video_id": getattr(info, "video_id", ""),
                "duration_seconds": getattr(info, "duration_seconds", None),
            },
            "processing": self._default_processing_metadata(),
        }
        self._write_json(record_dir / self.FOLDER_METADATA, metadata)
        return self._build_folder_record(record_dir)  # type: ignore[return-value]

    def save_preprocess_result(self, record: HistoryRecord, result: Any) -> HistoryRecord:
        """保存音频标准化结果，并让转录优先使用标准化音频。"""
        metadata = self._record_metadata(record)
        normalized_path = Path(result.normalized_audio_path)
        try:
            normalized_value = str(normalized_path.relative_to(record.record_dir))
        except ValueError:
            normalized_value = str(normalized_path)
        metadata["normalized_audio_path"] = normalized_value
        metadata["duration_seconds"] = result.duration_seconds
        metadata["audio_format"] = {
            "sample_rate": result.sample_rate,
            "channels": result.channels,
            "format": "wav",
            "source_format": result.source_format,
        }
        metadata["input_error"] = None
        self._clear_last_error_for_stage(metadata, "input")
        self._write_json(record.metadata_path, metadata)
        self._write_folder_metadata(record.record_dir)
        return self._build_folder_record(record.record_dir) or record

    def save_remote_metadata(self, record: HistoryRecord, metadata: dict[str, Any]) -> HistoryRecord:
        """保存远程导入扩展元数据。"""
        stored = self._record_metadata(record)
        stored.update(metadata)
        self._write_json(record.metadata_path, stored)
        self._write_folder_metadata(record.record_dir)
        return self._build_folder_record(record.record_dir) or record

    def save_remote_audio_result(
        self,
        record: HistoryRecord,
        *,
        audio_path: Path,
        duration_seconds: float | None,
        audio_format: dict[str, Any],
        metadata: dict[str, Any],
    ) -> HistoryRecord:
        """保存远程音频下载和标准化结果。"""
        stored = self._record_metadata(record)
        stored.update(metadata)
        stored["audio_file"] = audio_path.name
        stored["duration_seconds"] = duration_seconds
        stored["audio_format"] = audio_format
        stored["normalized_audio_path"] = ""
        stored["input_error"] = None
        self._clear_last_error_for_stage(stored, "input")
        self._write_json(record.metadata_path, stored)
        self._write_folder_metadata(record.record_dir)
        return self._build_folder_record(record.record_dir) or record

    def mark_input_error(self, record: HistoryRecord, error: Any) -> HistoryRecord:
        """保存导入或预处理阶段的错误。"""
        metadata = self._record_metadata(record)
        if hasattr(error, "to_metadata"):
            metadata["input_error"] = error.to_metadata()
            message = metadata["input_error"].get("message") or str(error)
        else:
            metadata["input_error"] = {
                "kind": "input_error",
                "message": str(error),
                "details": str(error),
            }
            message = str(error)
        details = ""
        if isinstance(metadata.get("input_error"), dict):
            details = str(metadata["input_error"].get("details") or "")
        self._set_last_error(metadata, "input", message, details)
        self._write_json(record.metadata_path, metadata)
        return self._build_folder_record(record.record_dir) or record

    def refresh_metadata(self, record: HistoryRecord) -> HistoryRecord:
        """刷新记录状态并返回最新记录。"""
        self._write_folder_metadata(record.record_dir)
        return self._build_folder_record(record.record_dir) or record

    def mark_processing_started(
        self,
        record: HistoryRecord,
        step: str,
        context: dict[str, Any] | None = None,
    ) -> HistoryRecord:
        """记录某个处理步骤开始。"""
        metadata = self._record_metadata(record)
        step_data = self._step_metadata(metadata, step)
        step_data.update(context or {})
        step_data["status"] = "running"
        step_data["started_at"] = datetime.now().isoformat(timespec="seconds")
        step_data["completed_at"] = None
        step_data["elapsed_seconds"] = None
        step_data["error_message"] = ""
        self._write_json(record.metadata_path, metadata)
        return self._build_folder_record(record.record_dir) or record

    def mark_processing_completed(
        self,
        record: HistoryRecord,
        step: str,
        elapsed_seconds: float | None = None,
        context: dict[str, Any] | None = None,
    ) -> HistoryRecord:
        """记录某个处理步骤完成。"""
        metadata = self._record_metadata(record)
        step_data = self._step_metadata(metadata, step)
        step_data.update(context or {})
        step_data["status"] = "completed"
        step_data["completed_at"] = datetime.now().isoformat(timespec="seconds")
        if elapsed_seconds is not None:
            step_data["elapsed_seconds"] = round(max(0.0, elapsed_seconds), 3)
        step_data["error_message"] = ""
        self._clear_last_error_for_stage(metadata, step)
        self._write_json(record.metadata_path, metadata)
        self._write_folder_metadata(record.record_dir)
        return self._build_folder_record(record.record_dir) or record

    def mark_error(
        self,
        record: HistoryRecord,
        message: str,
        step: str | None = None,
        elapsed_seconds: float | None = None,
    ) -> HistoryRecord:
        """记录处理失败状态，保留错误详情用于后续排查。"""
        metadata = self._record_metadata(record)
        self._set_last_error(metadata, step or "general", message)
        if step:
            step_data = self._step_metadata(metadata, step)
            step_data["status"] = "failed"
            step_data["completed_at"] = datetime.now().isoformat(timespec="seconds")
            if elapsed_seconds is not None:
                step_data["elapsed_seconds"] = round(max(0.0, elapsed_seconds), 3)
            step_data["error_message"] = message
        self._write_json(record.metadata_path, metadata)
        return self._build_folder_record(record.record_dir) or record

    def read_transcript(self, record: HistoryRecord) -> str:
        """读取转录文本，不存在时返回空字符串。"""
        return self._read_text(record.transcript_path)

    def read_summary(self, record: HistoryRecord) -> str:
        """读取总结文本，不存在时返回空字符串。"""
        return self._read_text(record.summary_path)

    def save_transcript(self, record: HistoryRecord, text: str) -> Path:
        """保存转录文本。"""
        record.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        record.transcript_path.write_text(text, encoding="utf-8")
        self._write_folder_metadata(record.record_dir)
        return record.transcript_path

    def save_summary(self, record: HistoryRecord, text: str) -> Path:
        """保存总结文本。"""
        record.summary_path.parent.mkdir(parents=True, exist_ok=True)
        record.summary_path.write_text(text, encoding="utf-8")
        self._write_folder_metadata(record.record_dir)
        return record.summary_path

    def read_timeline(self, record: HistoryRecord) -> list[dict[str, Any]]:
        """读取结构化时间轴，不存在时返回空列表。"""
        data = self._read_json(record.timeline_path)
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return timeline_to_dicts(timeline_from_dicts(items))

    def save_timeline(self, record: HistoryRecord, items: list[dict[str, Any]]) -> Path:
        """保存结构化时间轴。"""
        payload = {
            "version": 1,
            "items": timeline_to_dicts(timeline_from_dicts(items)),
        }
        self._write_json(record.timeline_path, payload)
        self._write_folder_metadata(record.record_dir)
        return record.timeline_path

    def export_transcript_txt(self, record: HistoryRecord) -> Path:
        """返回原始转录文字文件路径。"""
        if not record.transcript_path.exists():
            raise FileNotFoundError("当前记录没有可导出的转录文字")
        return record.transcript_path

    def export_summary_markdown(self, record: HistoryRecord) -> Path:
        """把总结结果导出为 Markdown 文件。"""
        summary = self.read_summary(record).strip()
        if not summary:
            raise ValueError("当前记录没有可导出的总结内容")
        return record.summary_path

    def export_timeline_srt(self, record: HistoryRecord) -> Path:
        """根据时间轴生成 SRT 字幕文件。"""
        timeline = timeline_from_dicts(self.read_timeline(record))
        if not timeline:
            raise ValueError("当前记录没有可导出的逐句时间轴")
        srt_path = record.record_dir / "transcript.srt"
        srt_path.write_text(timeline_to_srt(timeline), encoding="utf-8")
        self._write_folder_metadata(record.record_dir)
        return srt_path

    def clear_generated_results(self, record: HistoryRecord) -> HistoryRecord:
        """清理本次流程会覆盖的生成结果，保留音频和元数据。"""
        root = self._record_root(record)
        if not self._is_safe_record_dir(record.record_dir, root):
            raise ValueError("记录目录不安全，无法清理生成结果")

        generated_paths = (
            record.record_dir / self.FOLDER_TRANSCRIPT,
            record.record_dir / self.FOLDER_SUMMARY,
            record.record_dir / self.FOLDER_MARKDOWN,
            record.record_dir / self.FOLDER_TIMELINE,
            record.record_dir / "transcript.srt",
        )
        for path in generated_paths:
            safe_path = path.resolve(strict=False)
            if safe_path.parent != record.record_dir.resolve(strict=False):
                raise ValueError(f"生成文件路径不安全：{safe_path}")
            if safe_path.exists():
                safe_path.unlink()

        metadata = self._record_metadata(record)
        metadata["last_error"] = None
        metadata.pop("error_message", None)
        metadata["processing"] = self._default_processing_metadata()
        self._write_json(record.metadata_path, metadata)
        self._write_folder_metadata(record.record_dir)
        return self._build_folder_record(record.record_dir) or record

    def save_asr_metadata(self, record: HistoryRecord, asr_metadata: dict[str, Any]) -> HistoryRecord:
        """保存 ASR 诊断信息到记录 metadata。"""
        metadata = self._record_metadata(record)
        stored_metadata = dict(asr_metadata)
        stored_metadata.pop("timeline", None)
        metadata["asr"] = stored_metadata
        if isinstance(asr_metadata.get("timestamps"), dict):
            metadata["timestamps"] = dict(asr_metadata["timestamps"])
        self._write_json(record.metadata_path, metadata)
        return self._build_folder_record(record.record_dir) or record

    def rename_record(self, record: HistoryRecord, new_name: str) -> HistoryRecord:
        """重命名记录文件夹并更新元数据。"""
        clean_name = self._sanitize_record_name(new_name)
        if not clean_name:
            raise ValueError("记录名称不能为空")
        root = self._record_root(record)
        if not self._is_safe_record_dir(record.record_dir, root):
            raise ValueError("记录目录不安全，无法重命名")
        if clean_name == record.record_dir.name:
            return record

        previous_dir = self.recordings_dir
        self.recordings_dir = root
        try:
            target_dir = root / self._unique_record_id(clean_name)
        finally:
            self.recordings_dir = previous_dir
        if target_dir == record.record_dir:
            return record
        if target_dir.exists():
            raise FileExistsError(f"记录名称已存在：{target_dir.name}")

        shutil.move(str(record.record_dir), str(target_dir))
        metadata_path = target_dir / self.FOLDER_METADATA
        metadata = self._read_json(metadata_path)
        metadata["record_id"] = target_dir.name
        metadata.setdefault("version", self.METADATA_VERSION)
        metadata.setdefault("created_at", record.created_at.isoformat(timespec="seconds"))
        metadata.setdefault("audio_file", self.FOLDER_AUDIO)
        metadata.setdefault("transcript_file", self.FOLDER_TRANSCRIPT)
        metadata.setdefault("summary_file", self.FOLDER_SUMMARY)
        metadata.setdefault("markdown_file", self.FOLDER_MARKDOWN)
        metadata.setdefault("processing", self._default_processing_metadata())
        self._write_json(metadata_path, metadata)
        self._write_folder_metadata(target_dir)
        return self._build_folder_record(target_dir, self._notebook_for_record_dir(target_dir))  # type: ignore[return-value]

    def move_record_to_notebook(self, record: HistoryRecord, target_notebook_id: str) -> MoveRecordResult:
        """把整条记录目录移动到目标笔记本，目标重名时直接失败。"""
        source_dir = record.record_dir
        source_root = self._record_root(record)
        target_notebook = next(
            (item for item in self.notebooks if item.notebook_id == target_notebook_id),
            None,
        )
        if target_notebook is None:
            return MoveRecordResult(False, source_dir, source_dir, "目标笔记本不存在")
        target_root = target_notebook.path
        target_dir = target_root / source_dir.name

        if target_notebook.notebook_id == record.notebook_id or (
            target_root.resolve(strict=False) == source_root.resolve(strict=False)
        ):
            return MoveRecordResult(True, source_dir, source_dir, "记录已在目标笔记本")
        if not source_dir.exists():
            return MoveRecordResult(False, source_dir, target_dir, "记录不存在或已被删除")
        if not self._is_safe_record_dir(source_dir, source_root):
            return MoveRecordResult(False, source_dir, target_dir, "移动被拒绝：记录目录不安全")
        source_resolved = source_dir.resolve(strict=False)
        target_root_resolved = target_root.resolve(strict=False)
        if target_root_resolved == source_resolved or self._is_relative_to(target_root_resolved, source_resolved):
            return MoveRecordResult(False, source_dir, target_dir, "目标笔记本不能位于记录目录内部")
        if target_dir.exists():
            return MoveRecordResult(False, source_dir, target_dir, f"目标笔记本中已存在同名记录：{source_dir.name}")

        temp_dir = target_root / f".move-{source_dir.name}-{uuid.uuid4().hex[:8]}"
        try:
            target_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source_dir, temp_dir)
            if target_dir.exists():
                shutil.rmtree(temp_dir)
                return MoveRecordResult(False, source_dir, target_dir, f"目标笔记本中已存在同名记录：{source_dir.name}")
            temp_dir.rename(target_dir)
            try:
                shutil.rmtree(source_dir)
            except OSError as exc:
                rollback_error = self._remove_move_target(target_dir)
                if rollback_error:
                    return MoveRecordResult(
                        False,
                        source_dir,
                        target_dir,
                        f"移动失败：{exc}；目标目录回滚失败：{rollback_error}，请手动检查重复记录。",
                    )
                return MoveRecordResult(False, source_dir, target_dir, f"移动失败：{exc}")
        except OSError as exc:
            cleanup_error = self._remove_move_target(temp_dir)
            if cleanup_error:
                return MoveRecordResult(
                    False,
                    source_dir,
                    target_dir,
                    f"移动失败：{exc}；临时目录清理失败：{cleanup_error}",
                )
            return MoveRecordResult(False, source_dir, target_dir, f"移动失败：{exc}")
        return MoveRecordResult(True, source_dir, target_dir, "记录已移动")

    def _remove_move_target(self, path: Path) -> str:
        """清理移动过程中的目标或临时目录，失败时返回错误信息。"""
        if not path.exists():
            return ""
        try:
            shutil.rmtree(path)
            return ""
        except OSError as exc:
            return str(exc)

    def delete_record(self, record: HistoryRecord) -> DeleteResult:
        """删除记录及其关联文件，删除前进行路径边界校验。"""
        deleted: list[Path] = []
        skipped: list[Path] = []

        root = self._record_root(record)
        if not self._is_safe_record_dir(record.record_dir, root):
            return DeleteResult(False, tuple(deleted), (record.record_dir,), "删除被拒绝：记录目录不安全")
        if record.record_dir.exists():
            try:
                shutil.rmtree(record.record_dir)
                deleted.append(record.record_dir)
            except OSError as exc:
                skipped.append(record.record_dir)
                return DeleteResult(
                    False,
                    tuple(deleted),
                    tuple(skipped),
                    f"删除失败：{exc}",
                )
        else:
            skipped.append(record.record_dir)
            return DeleteResult(False, tuple(deleted), tuple(skipped), "记录不存在或已被删除")
        return DeleteResult(True, tuple(deleted), tuple(skipped), "记录已删除")

    def _build_folder_record(
        self,
        record_dir: Path,
        notebook: NotebookConfig | None = None,
    ) -> HistoryRecord | None:
        metadata_path = record_dir / self.FOLDER_METADATA
        metadata = self._read_json(metadata_path)
        if not metadata and not (record_dir / self.FOLDER_AUDIO).exists():
            return None
        notebook = notebook or self._notebook_for_record_dir(record_dir)

        storage_mode = str(metadata.get("storage_mode") or "")
        base_audio_path = record_dir / str(metadata.get("audio_file") or self.FOLDER_AUDIO)
        source_audio_path = self._metadata_path(record_dir, metadata.get("original_file_path") or metadata.get("source_path"))
        normalized_audio_path = self._metadata_path(record_dir, metadata.get("normalized_audio_path"))
        if normalized_audio_path and normalized_audio_path.exists():
            audio_path = normalized_audio_path
        elif storage_mode == self.STORAGE_REFERENCE and source_audio_path:
            audio_path = source_audio_path
        else:
            audio_path = base_audio_path
        transcript_path = record_dir / str(metadata.get("transcript_file") or self.FOLDER_TRANSCRIPT)
        summary_path = record_dir / str(metadata.get("summary_file") or self.FOLDER_SUMMARY)
        markdown_path = record_dir / str(metadata.get("markdown_file") or self.FOLDER_MARKDOWN)
        created_at = self._metadata_datetime(metadata, "created_at")
        if created_at is None:
            created_at = self._parse_timestamp(record_dir.name)
        if created_at is None:
            created_at = self._path_datetime(audio_path if audio_path.exists() else record_dir)

        duration = self._metadata_float(metadata, "duration_seconds")
        if duration is None and audio_path.exists():
            duration = self._wav_duration(audio_path)

        return HistoryRecord(
            record_id=str(metadata.get("record_id") or record_dir.name),
            layout="folder",
            record_dir=record_dir,
            audio_path=audio_path,
            transcript_path=transcript_path,
            summary_path=summary_path,
            markdown_path=markdown_path,
            metadata_path=metadata_path,
            created_at=created_at,
            duration_seconds=duration,
            audio_size_bytes=self._file_size(audio_path),
            total_size_bytes=self._folder_size(record_dir),
            notebook_id=notebook.notebook_id,
            notebook_name=notebook.name,
            notebook_path=notebook.path,
            last_error=self._normalized_last_error(metadata.get("last_error"), metadata.get("error_message")),
            source_kind=str(metadata.get("source_kind") or metadata.get("source_type") or ""),
            original_file_path=source_audio_path,
            normalized_audio_path=normalized_audio_path,
            input_error=metadata.get("input_error") if isinstance(metadata.get("input_error"), dict) else None,
            audio_format=metadata.get("audio_format") if isinstance(metadata.get("audio_format"), dict) else None,
            storage_mode=storage_mode,
            external_subtitle_file=str(metadata.get("external_subtitle_file") or self.FOLDER_EXTERNAL_SUBTITLE),
        )
