"""模型下载逻辑。"""
from __future__ import annotations

import shutil
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from .types import ModelCatalogEntry, format_size

ProgressCallback = Callable[[int | None, str], None]
CancelChecker = Callable[[], bool]
Downloader = Callable[[ModelCatalogEntry, Path, ProgressCallback, CancelChecker], Path]


class _DownloadProgress:
    """按下载源统计模型文件的总下载进度。"""

    def __init__(self, total_size: int | None = None):
        self.total_size = total_size
        self.downloaded_size = 0

    def ensure_total_size(self, total_size: int | None) -> None:
        if self.total_size is None and total_size:
            self.total_size = total_size

    def add_downloaded(self, chunk_size: int) -> None:
        self.downloaded_size += chunk_size

    def emit(self, display_name: str, on_progress: ProgressCallback) -> None:
        if self.total_size:
            downloaded = min(self.downloaded_size, self.total_size)
            percent = min(99.0, downloaded / self.total_size * 100)
            text = f"已下载 {format_size(downloaded)}/{format_size(self.total_size)} | {percent:.1f}%"
            on_progress(int(percent), text)
        else:
            text = f"已下载 {format_size(self.downloaded_size)}"
            on_progress(None, text)


def default_gguf_downloader(
    entry: ModelCatalogEntry,
    download_dir: Path,
    on_progress: ProgressCallback,
    should_cancel: CancelChecker,
) -> Path:
    """按模型清单中的下载源顺序下载模型，首选 ModelScope，保留 GitHub 备用。"""
    if should_cancel():
        raise RuntimeError("下载已取消")

    sources = entry.download_sources or _legacy_download_sources(entry)
    if not sources:
        raise RuntimeError("模型清单缺少下载地址")

    download_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    for index, source in enumerate(sources):
        if should_cancel():
            raise RuntimeError("下载已取消")
        _clear_download_dir(download_dir)
        source_name = str(source.get("name") or "下载源")
        on_progress(None, _source_connecting_text(index))
        try:
            _download_from_source(entry, source, download_dir, on_progress, should_cancel)
            if should_cancel():
                raise RuntimeError("下载已取消")
            _validate_required_files(download_dir, entry.required_files)
            on_progress(100, "模型文件校验完成")
            return download_dir
        except RuntimeError as exc:
            if "下载已取消" in str(exc):
                raise
            failures.append(f"{source_name}: {exc}")
        except urllib.error.URLError as exc:
            failures.append(f"{source_name}: {exc}")
        except OSError as exc:
            failures.append(f"{source_name}: {exc}")

    details = "；".join(failures) if failures else "未知错误"
    raise RuntimeError(f"模型下载失败，请检查网络后重试：{details}")


def _legacy_download_sources(entry: ModelCatalogEntry) -> list[dict]:
    if not entry.download_url:
        return []
    return [{"name": "download_url", "type": "archive", "url": entry.download_url}]


def _source_connecting_text(index: int) -> str:
    """返回下载源连接提示，不把内部源名称直接暴露给用户。"""
    if index == 0:
        return "正在连接模型下载源"
    return "正在尝试备用下载源"


def _download_from_source(
    entry: ModelCatalogEntry,
    source: dict,
    download_dir: Path,
    on_progress: ProgressCallback,
    should_cancel: CancelChecker,
) -> None:
    source_type = str(source.get("type") or "archive")
    if source_type == "files":
        _download_model_files(source, download_dir, on_progress, should_cancel)
        return
    if source_type == "archive":
        _download_model_archive(entry, source, download_dir, on_progress, should_cancel)
        return
    raise RuntimeError(f"不支持的模型下载源类型：{source_type}")


def _download_model_archive(
    entry: ModelCatalogEntry,
    source: dict,
    download_dir: Path,
    on_progress: ProgressCallback,
    should_cancel: CancelChecker,
) -> None:
    url = str(source.get("url") or entry.download_url or "")
    if not url:
        raise RuntimeError("模型清单缺少下载地址")

    archive_name = Path(url.split("?", 1)[0]).name or f"{entry.local_dir_name}.zip"
    archive_path = download_dir / archive_name
    partial_path = download_dir / f"{archive_name}.part"
    progress = _DownloadProgress()
    _download_file(url, partial_path, archive_name, entry.estimated_size_bytes, progress, on_progress, should_cancel)
    partial_path.replace(archive_path)
    on_progress(100, "下载完成，正在解压")
    _extract_model_archive(archive_path, download_dir, entry.required_files, should_cancel)
    archive_path.unlink(missing_ok=True)

    if should_cancel():
        raise RuntimeError("下载已取消")


def _download_model_files(
    source: dict,
    download_dir: Path,
    on_progress: ProgressCallback,
    should_cancel: CancelChecker,
) -> None:
    base_url = str(source.get("base_url") or "")
    files = list(source.get("files") or [])
    if not base_url or not files:
        raise RuntimeError("模型清单缺少 ModelScope 文件列表")

    base_url = base_url.rstrip("/") + "/"
    progress = _DownloadProgress(_files_total_size(files))
    for file_info in files:
        if should_cancel():
            raise RuntimeError("下载已取消")
        file_name = str(file_info.get("name") or "").strip()
        if not file_name or "/" in file_name or "\\" in file_name:
            raise RuntimeError("模型清单包含不安全文件名")
        expected_size = _safe_int(file_info.get("size"))
        url = str(file_info.get("url") or f"{base_url}{file_name}")
        target_path = download_dir / file_name
        partial_path = download_dir / f"{file_name}.part"
        _download_file(url, partial_path, file_name, expected_size, progress, on_progress, should_cancel)
        partial_path.replace(target_path)
        if expected_size is not None and target_path.stat().st_size != expected_size:
            raise RuntimeError(f"{file_name} 文件大小不一致，请重新下载。")


def _download_file(
    url: str,
    target_path: Path,
    display_name: str,
    estimated_size: int | None,
    progress: _DownloadProgress,
    on_progress: ProgressCallback,
    should_cancel: CancelChecker,
) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "file":
        source_path = _file_url_to_path(parsed)
        if not source_path.is_file():
            raise RuntimeError("本地模型文件不存在")
        with source_path.open("rb") as response, open(target_path, "wb") as output:
            progress.ensure_total_size(source_path.stat().st_size or estimated_size)
            _copy_download_stream(response, output, display_name, progress, on_progress, should_cancel)
        return
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("模型下载地址协议不受支持")
    request = urllib.request.Request(url, headers={"User-Agent": "AudioRecorder/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        progress.ensure_total_size(_response_size(response) or estimated_size)
        with open(target_path, "wb") as output:
            _copy_download_stream(response, output, display_name, progress, on_progress, should_cancel)


def _copy_download_stream(
    response,
    output,
    display_name: str,
    progress: _DownloadProgress,
    on_progress: ProgressCallback,
    should_cancel: CancelChecker,
) -> None:
    while True:
        if should_cancel():
            raise RuntimeError("下载已取消")
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        output.write(chunk)
        progress.add_downloaded(len(chunk))
        progress.emit(display_name, on_progress)


def _file_url_to_path(parsed: urllib.parse.ParseResult) -> Path:
    path_text = urllib.request.url2pathname(parsed.path)
    if parsed.netloc:
        path_text = f"//{parsed.netloc}{path_text}"
    return Path(path_text)


def _files_total_size(files: list[dict]) -> int | None:
    total_size = 0
    for file_info in files:
        file_size = _safe_int(file_info.get("size"))
        if file_size is None:
            return None
        total_size += file_size
    return total_size


def _clear_download_dir(download_dir: Path) -> None:
    for child in download_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _validate_required_files(download_dir: Path, required_files: list[str]) -> None:
    missing = [file_name for file_name in required_files if not (download_dir / file_name).exists()]
    if missing:
        raise RuntimeError(f"模型文件不完整：{', '.join(missing)}")


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_model_archive(
    archive_path: Path,
    download_dir: Path,
    required_files: list[str],
    should_cancel: CancelChecker,
) -> None:
    extract_dir = download_dir / "_extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path) as zip_file:
            for member in zip_file.infolist():
                if should_cancel():
                    raise RuntimeError("下载已取消")
                _ensure_safe_zip_member(extract_dir, member.filename)
                zip_file.extract(member, extract_dir)
    except zipfile.BadZipFile as exc:
        raise RuntimeError("模型文件解压失败，请重新下载。") from exc

    source_dir = _find_model_file_dir(extract_dir, required_files)
    if source_dir is None:
        missing = ", ".join(required_files)
        raise RuntimeError(f"模型文件不完整：{missing}")

    for child in source_dir.iterdir():
        target = download_dir / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(child), str(target))
    shutil.rmtree(extract_dir, ignore_errors=True)


def _find_model_file_dir(root: Path, required_files: list[str]) -> Path | None:
    candidates = [root]
    candidates.extend(path for path in root.rglob("*") if path.is_dir())
    for candidate in candidates:
        if all((candidate / file_name).exists() for file_name in required_files):
            return candidate
    return None


def _ensure_safe_zip_member(root: Path, filename: str) -> None:
    target = (root / filename).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise RuntimeError("模型压缩包包含不安全路径，已拒绝解压。")


def _response_size(response) -> int | None:
    value = response.headers.get("Content-Length")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None
