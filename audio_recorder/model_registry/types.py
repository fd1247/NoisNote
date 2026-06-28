"""ASR 模型管理数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ModelStatus(Enum):
    """模型在应用模型目录中的状态。"""

    DOWNLOADED = "downloaded"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class ModelCatalogEntry:
    """内置模型清单中的一项。"""

    name: str
    display_name: str
    modelscope_id: str = ""
    download_url: str = ""
    download_sources: list[dict[str, Any]] = field(default_factory=list)
    alias: str = ""
    revision: str | None = None
    model_type: str = "asr"
    backend: str = "qwen3_asr_gguf"
    adapter: str = ""
    model_size: str = ""
    local_dir_name: str = ""
    description: str = ""
    recommended: bool = False
    required_files: list[str] = field(default_factory=list)
    estimated_size_bytes: int | None = None

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> "ModelCatalogEntry":
        """从配置字典构造清单项。"""
        name = str(data.get("name", "")).strip()
        return cls(
            name=name,
            display_name=str(data.get("display_name") or name),
            modelscope_id=str(data.get("modelscope_id", "")).strip(),
            download_url=str(data.get("download_url", "")).strip(),
            download_sources=list(data.get("download_sources") or []),
            alias=str(data.get("alias") or ""),
            revision=data.get("revision") or None,
            model_type=str(data.get("model_type") or "asr"),
            backend=str(data.get("backend") or "qwen3_asr_gguf"),
            adapter=str(data.get("adapter") or ""),
            model_size=str(data.get("model_size") or ""),
            local_dir_name=str(data.get("local_dir_name") or name),
            description=str(data.get("description") or ""),
            recommended=bool(data.get("recommended", False)),
            required_files=list(data.get("required_files") or []),
            estimated_size_bytes=data.get("estimated_size_bytes") or None,
        )

    def primary_download_url(self) -> str:
        """返回界面展示和兼容记录使用的主下载地址。"""
        if self.download_sources:
            source = self.download_sources[0]
            if source.get("url"):
                return str(source["url"])
            if source.get("base_url"):
                return str(source["base_url"])
        return self.download_url


@dataclass
class LocalModelInfo:
    """本地模型目录的校验结果。"""

    entry: ModelCatalogEntry
    local_path: Path
    exists: bool
    is_complete: bool
    missing_files: list[str]
    size_bytes: int
    status: ModelStatus
    last_error: str = ""


@dataclass
class DownloadTaskState:
    """模型下载任务状态。"""

    name: str
    source_url: str
    target_dir: Path
    progress_percent: float | None = None
    status_text: str = "等待下载"
    is_cancel_requested: bool = False
    error: str = ""
    progress_source: str = "worker"
    active_file_name: str = "模型压缩包"
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    status: str = "pending"


@dataclass(frozen=True)
class DiskSpaceCheck:
    """模型下载前的磁盘空间检查结果。"""

    ok: bool
    required_bytes: int
    available_bytes: int
    message: str


@dataclass(frozen=True)
class ModelDeleteResult:
    """已下载模型删除结果。"""

    success: bool
    deleted_path: Path | None
    message: str


def format_size(size_bytes: int) -> str:
    """格式化模型目录大小。"""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"
