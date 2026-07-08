"""历史记录元数据、路径和文件存储辅助逻辑。"""
from __future__ import annotations

import json
import shutil
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import HistoryRecord


class HistoryStorageMixin:
    """历史记录元数据和存储相关的共享私有方法。"""

    def _write_folder_metadata(self, record_dir: Path) -> None:
        record = self._build_folder_record(record_dir)
        if not record:
            return
        existing = self._read_json(record.metadata_path)
        metadata = self._base_metadata(record, existing)
        self._write_json(record.metadata_path, metadata)

    def _ensure_metadata_file(self, record: HistoryRecord) -> None:
        """补齐缺失或旧结构元数据，保持重启后可诊断信息完整。"""
        existing = self._read_json(record.metadata_path)
        if existing and not self._metadata_needs_refresh(existing):
            return
        self._write_folder_metadata(record.record_dir)

    def _base_metadata(
        self,
        record: HistoryRecord,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造记录元数据基础结构，并保留已有扩展字段。"""
        existing = existing or {}
        metadata = {
            "version": self.METADATA_VERSION,
            "record_id": record.record_id,
            "created_at": record.created_at.isoformat(timespec="seconds"),
            "duration_seconds": record.duration_seconds,
            "audio_file": existing.get("audio_file") or record.audio_path.name,
            "transcript_file": existing.get("transcript_file") or record.transcript_path.name,
            "summary_file": record.summary_path.name,
            "markdown_file": existing.get("markdown_file") or record.markdown_path.name,
            "last_error": self._normalized_last_error(existing.get("last_error"), existing.get("error_message")),
            "processing": self._default_processing_metadata(existing.get("processing")),
        }
        for key in (
            "source_type",
            "source_kind",
            "source_path",
            "remote",
            "transcript_source",
            "external_subtitle_file",
            "original_file_path",
            "normalized_audio_path",
            "audio_format",
            "input_error",
            "original_file_name",
            "storage_mode",
            "import_strategy",
            "source_size_bytes",
            "asr",
            "timestamps",
            "hotword_sets",
        ):
            if key in existing:
                metadata[key] = existing[key]
        return metadata

    def _record_metadata(self, record: HistoryRecord) -> dict[str, Any]:
        """读取并补齐当前记录元数据。"""
        existing = self._read_json(record.metadata_path)
        return self._base_metadata(record, existing)

    def _default_processing_metadata(
        self,
        existing: Any = None,
    ) -> dict[str, dict[str, Any]]:
        """返回处理步骤默认元数据结构。"""
        existing = existing if isinstance(existing, dict) else {}
        processing: dict[str, dict[str, Any]] = {}
        for step in self.PROCESSING_STEPS:
            old_step = existing.get(step) if isinstance(existing.get(step), dict) else {}
            processing[step] = {
                "status": old_step.get("status") or "pending",
                "started_at": old_step.get("started_at"),
                "completed_at": old_step.get("completed_at"),
                "elapsed_seconds": old_step.get("elapsed_seconds"),
                "error_message": old_step.get("error_message") or "",
            }
            for key, value in old_step.items():
                if key not in processing[step]:
                    processing[step][key] = value
        return processing

    def _step_metadata(self, metadata: dict[str, Any], step: str) -> dict[str, Any]:
        """获取指定处理步骤的元数据节点。"""
        if step not in self.PROCESSING_STEPS:
            raise ValueError(f"未知处理步骤：{step}")
        metadata["processing"] = self._default_processing_metadata(metadata.get("processing"))
        return metadata["processing"][step]

    def _metadata_needs_refresh(self, metadata: dict[str, Any]) -> bool:
        if metadata.get("version") != self.METADATA_VERSION:
            return True
        if "status" in metadata or "last_error" not in metadata:
            return True
        processing = metadata.get("processing")
        if not isinstance(processing, dict):
            return True
        return any(step not in processing for step in self.PROCESSING_STEPS)

    def _normalized_last_error(self, value: Any, legacy_message: Any = None) -> dict[str, Any] | None:
        """把历史错误字段收敛成轻量 last_error 结构。"""
        if isinstance(value, dict):
            message = str(value.get("message") or "").strip()
            if not message:
                return None
            return {
                "stage": str(value.get("stage") or "general"),
                "message": message,
                "details": str(value.get("details") or ""),
            }
        message = str(legacy_message or "").strip()
        if not message:
            return None
        return {"stage": "general", "message": message, "details": ""}

    def _set_last_error(self, metadata: dict[str, Any], stage: str, message: str, details: str = "") -> None:
        metadata["last_error"] = {
            "stage": stage or "general",
            "message": str(message or ""),
            "details": str(details or ""),
        }

    def _clear_last_error_for_stage(self, metadata: dict[str, Any], stage: str) -> None:
        last_error = self._normalized_last_error(metadata.get("last_error"), metadata.get("error_message"))
        if last_error and last_error.get("stage") != stage:
            metadata["last_error"] = last_error
            return
        metadata["last_error"] = None
        metadata.pop("error_message", None)

    def _unique_record_id(self, base_id: str) -> str:
        safe_id = self._sanitize_record_name(base_id)
        if not safe_id:
            safe_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = safe_id
        index = 1
        while (self.recordings_dir / candidate).exists():
            index += 1
            candidate = f"{safe_id}-{index:02d}"
        return candidate

    def _sanitize_record_name(self, value: str) -> str:
        forbidden = '<>:"/\\|?*'
        safe_name = "".join("_" if ch in forbidden or ord(ch) < 32 else ch for ch in value)
        safe_name = safe_name.strip().strip(".")
        if safe_name.upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }:
            safe_name = f"{safe_name}_"
        return safe_name[:80].rstrip().rstrip(".")

    def _imported_audio_name(self, source: Path) -> str:
        suffix = source.suffix.lower()
        if not suffix:
            return self.FOLDER_AUDIO
        return f"audio{suffix}"

    def _source_kind_for_path(self, source: Path) -> str:
        if source.suffix.lower().lstrip(".") in {"mp4", "mov", "mkv", "avi", "webm"}:
            return "local_video"
        return "local_audio"

    def _metadata_path(self, record_dir: Path, value: Any) -> Path | None:
        if not value:
            return None
        path = Path(str(value))
        if not path.is_absolute():
            path = record_dir / path
        return path

    def _organize_flat_audio(self, audio_path: Path) -> bool:
        record_id = self._unique_record_id(audio_path.stem)
        record_dir = self.recordings_dir / record_id
        file_map = (
            (audio_path, record_dir / self.FOLDER_AUDIO),
            (audio_path.with_suffix(".txt"), record_dir / self.FOLDER_TRANSCRIPT),
            (audio_path.with_suffix(".md"), record_dir / self.FOLDER_MARKDOWN),
        )

        try:
            record_dir.mkdir(parents=True, exist_ok=False)
            for source, target in file_map:
                if source.exists() and source.is_file():
                    shutil.move(str(source), str(target))
            self._write_folder_metadata(record_dir)
            return True
        except OSError:
            return False

    def _is_safe_record_dir(self, path: Path, root_dir: Path | None = None) -> bool:
        root = (root_dir or self.recordings_dir).resolve(strict=False)
        target = path.resolve(strict=False)
        return target != root and self._is_relative_to(target, root)

    def _is_relative_to(self, path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="utf-8", errors="replace")

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _metadata_datetime(self, metadata: dict[str, Any], key: str) -> datetime | None:
        value = metadata.get(key)
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _metadata_float(self, metadata: dict[str, Any], key: str) -> float | None:
        value = metadata.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_timestamp(self, value: str) -> datetime | None:
        for fmt in ("%Y%m%d_%H%M%S", "%Y%m%d-%H%M%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def _path_datetime(self, path: Path) -> datetime:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return datetime.now()

    def _wav_duration(self, path: Path) -> float | None:
        if not path.exists():
            return None
        if path.suffix.lower() != ".wav":
            return None
        try:
            with wave.open(str(path), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                if frame_rate <= 0:
                    return None
                return wav_file.getnframes() / frame_rate
        except (wave.Error, OSError, EOFError):
            return None

    def _file_size(self, path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _folder_size(self, path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                total += self._file_size(child)
        return total
