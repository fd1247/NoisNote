"""ASR 模型管理服务。"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..app.config import DEFAULT_MODEL_CATALOG
from .types import (
    DiskSpaceCheck,
    DownloadTaskState,
    LocalModelInfo,
    ModelCatalogEntry,
    ModelDeleteResult,
    ModelStatus,
    format_size,
)


class ModelService:
    """集中处理模型清单、校验、路径安全和配置写入。"""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        models_config = self.config.setdefault("models", {})
        self.root_dir = Path(
            models_config.setdefault(
                "root_dir",
                str(Path.home() / "Documents" / "AudioRecorder" / "models"),
            )
        ).expanduser()
        models_config["root_dir"] = str(self.root_dir)
        models_config.setdefault("downloaded", {})

    def get_catalog(self) -> list[ModelCatalogEntry]:
        """返回当前阶段可管理的 ASR 模型清单。"""
        entries = [
            ModelCatalogEntry.from_config(item)
            for item in DEFAULT_MODEL_CATALOG
        ]
        asr_entries = [
            item
            for item in entries
            if item.name and item.model_type == "asr" and item.backend == "qwen3_asr_gguf"
        ]
        return sorted(asr_entries, key=lambda item: (not item.recommended, item.display_name))

    def get_entry(self, name: str) -> ModelCatalogEntry | None:
        """按模型名称查找清单项。"""
        for entry in self.get_catalog():
            if name in {entry.name, entry.alias, entry.modelscope_id}:
                return entry
        return None

    def get_target_dir(self, entry: ModelCatalogEntry) -> Path:
        """返回模型在应用模型目录下的目标路径。"""
        target = self.root_dir / entry.local_dir_name
        return self._ensure_within_root(target)

    def get_download_temp_dir(self, entry: ModelCatalogEntry) -> Path:
        """返回模型下载临时目录。"""
        return self._ensure_within_root(self.root_dir / f".download-{entry.local_dir_name}")

    def validate_model_dir(
        self,
        entry: ModelCatalogEntry,
        path: Path | None = None,
    ) -> LocalModelInfo:
        """检查本地模型目录是否存在且关键文件完整。"""
        local_path = self._ensure_within_root(path or self.get_target_dir(entry))
        exists = local_path.exists() and local_path.is_dir()
        missing_files = []
        if exists:
            for required_file in entry.required_files:
                if not (local_path / required_file).exists():
                    missing_files.append(required_file)
        else:
            missing_files = list(entry.required_files)

        is_complete = exists and not missing_files
        status = ModelStatus.DOWNLOADED if is_complete else ModelStatus.INCOMPLETE
        return LocalModelInfo(
            entry=entry,
            local_path=local_path,
            exists=exists,
            is_complete=is_complete,
            missing_files=missing_files,
            size_bytes=self._directory_size(local_path) if exists else 0,
            status=status,
        )

    def get_downloaded_models(self) -> list[LocalModelInfo]:
        """返回关键文件校验通过的已下载模型。"""
        downloaded: list[LocalModelInfo] = []
        for entry in self.get_catalog():
            info = self.validate_model_dir(entry)
            if info.is_complete:
                downloaded.append(info)
                self._record_downloaded(entry, info.local_path)
        return downloaded

    def get_available_models(self, active_downloads: set[str] | None = None) -> list[ModelCatalogEntry]:
        """返回尚未完整下载且不在下载中的模型。"""
        active_downloads = active_downloads or set()
        available = []
        for entry in self.get_catalog():
            if entry.name in active_downloads:
                continue
            info = self.validate_model_dir(entry)
            if not info.is_complete:
                available.append(entry)
        return available

    def prepare_download_dir(self, entry: ModelCatalogEntry) -> Path:
        """清理同名临时目录和旧目录，准备重新下载。"""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        target_dir = self.get_target_dir(entry)
        temp_dir = self.get_download_temp_dir(entry)
        self._remove_dir_inside_root(temp_dir)
        self._remove_dir_inside_root(target_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def finalize_download(self, entry: ModelCatalogEntry, source_dir: Path) -> Path:
        """把下载结果移动到最终模型目录。"""
        source = self._ensure_within_root(source_dir)
        target = self.get_target_dir(entry)
        self._remove_dir_inside_root(target)
        source.rename(target)
        return target

    def cleanup_temp_dir(self, entry: ModelCatalogEntry) -> None:
        """清理下载临时目录。"""
        self._remove_dir_inside_root(self.get_download_temp_dir(entry))

    def mark_downloaded(self, entry: ModelCatalogEntry, path: Path | None = None) -> dict[str, Any]:
        """校验成功后写入已下载模型配置。"""
        info = self.validate_model_dir(entry, path or self.get_target_dir(entry))
        if not info.is_complete:
            missing = ", ".join(info.missing_files) or "模型目录不存在"
            raise ValueError(f"模型文件不完整：{missing}")
        return self._record_downloaded(entry, info.local_path)

    def resolve_selected_model_path(self, name: str) -> Path | None:
        """解析通用设置中选中模型对应的本地目录。"""
        entry = self.get_entry(name)
        if not entry:
            return None
        info = self.validate_model_dir(entry)
        if not info.is_complete:
            return None
        return info.local_path

    def _record_downloaded(self, entry: ModelCatalogEntry, path: Path) -> dict[str, Any]:
        downloaded = self.config.setdefault("models", {}).setdefault("downloaded", {})
        record = {
            "path": str(path),
            "backend": entry.backend,
            "model_size": entry.model_size,
            "source_url": entry.primary_download_url(),
            "downloaded_at": datetime.now().isoformat(timespec="seconds"),
        }
        downloaded[entry.name] = record
        return record

    def _ensure_within_root(self, path: Path) -> Path:
        root = self.root_dir.resolve()
        resolved = path.expanduser().resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(f"模型路径越界：{resolved}")
        return resolved

    def _remove_dir_inside_root(self, path: Path) -> None:
        safe_path = self._ensure_within_root(path)
        root = self.root_dir.resolve()
        if safe_path == root:
            raise ValueError("不能清理模型根目录")
        if safe_path.exists():
            if not safe_path.is_dir():
                raise ValueError(f"目标不是目录：{safe_path}")
            shutil.rmtree(safe_path)

    def check_download_disk_space(
        self,
        entry: ModelCatalogEntry,
        safety_margin_ratio: float = 0.1,
    ) -> DiskSpaceCheck:
        """检查模型目标盘剩余空间是否足够下载和解压。"""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        estimated_size = int(entry.estimated_size_bytes or 0)
        if estimated_size <= 0:
            return DiskSpaceCheck(True, 0, shutil.disk_usage(self.root_dir).free, "模型大小未知，跳过空间预估")

        # 下载阶段会同时保留 zip 包和解压后的模型目录，按两份体积预留空间。
        required = int(estimated_size * (2 + max(0.0, safety_margin_ratio)))
        available = shutil.disk_usage(self.root_dir).free
        if available >= required:
            return DiskSpaceCheck(
                True,
                required,
                available,
                f"空间充足：预计需要 {format_size(required)}，当前可用 {format_size(available)}",
            )
        return DiskSpaceCheck(
            False,
            required,
            available,
            f"磁盘空间不足：预计需要 {format_size(required)}，当前可用 {format_size(available)}",
        )

    def delete_downloaded_model(self, entry: ModelCatalogEntry) -> ModelDeleteResult:
        """删除模型根目录下的指定已下载模型目录。"""
        target_dir = self.get_target_dir(entry)
        root = self.root_dir.resolve()
        if target_dir == root:
            raise ValueError("不能删除模型根目录")
        if root not in target_dir.parents:
            raise ValueError(f"模型路径越界：{target_dir}")

        if not target_dir.exists():
            self.config.setdefault("models", {}).setdefault("downloaded", {}).pop(entry.name, None)
            return ModelDeleteResult(False, target_dir, "模型目录不存在或已被删除")
        if not target_dir.is_dir():
            raise ValueError(f"目标不是模型目录：{target_dir}")

        shutil.rmtree(target_dir)
        self.config.setdefault("models", {}).setdefault("downloaded", {}).pop(entry.name, None)
        return ModelDeleteResult(True, target_dir, "模型已删除")

    def _directory_size(self, path: Path) -> int:
        total = 0
        if not path.exists():
            return total
        for child in path.rglob("*"):
            if child.is_file():
                total += child.stat().st_size
        return total
