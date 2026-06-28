"""ffmpeg 运行时发现与检查。"""
from __future__ import annotations

import shutil
import sys
# 仅以参数列表执行 ffmpeg/ffprobe 版本检查，不启用 shell。
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path


def _bundled_ffmpeg_dir() -> Path:
    """返回打包或源码环境下的 ffmpeg 目录。"""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / "vendor" / "ffmpeg"
    return Path(__file__).resolve().parents[2] / "vendor" / "ffmpeg"


@dataclass(frozen=True)
class RuntimeCheckResult:
    """外部媒体工具检查结果。"""

    available: bool
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None
    message: str = ""


def resolve_ffmpeg_path(config: dict | None = None) -> Path | None:
    """从配置、应用目录或 PATH 查找 ffmpeg。"""
    configured = _configured_path(config)
    if configured and configured.exists():
        return configured

    bundled = _bundled_ffmpeg_dir() / _exe_name("ffmpeg")
    if bundled.exists():
        return bundled

    found = shutil.which(_exe_name("ffmpeg")) or shutil.which("ffmpeg")
    return Path(found) if found else None


def resolve_ffprobe_path(config: dict | None = None, ffmpeg_path: Path | None = None) -> Path | None:
    """查找 ffprobe，优先使用 ffmpeg 同目录。"""
    if ffmpeg_path:
        sibling = ffmpeg_path.with_name(_exe_name("ffprobe"))
        if sibling.exists():
            return sibling

    configured = _configured_path(config, "ffprobe_path")
    if configured and configured.exists():
        return configured

    bundled = _bundled_ffmpeg_dir() / _exe_name("ffprobe")
    if bundled.exists():
        return bundled

    found = shutil.which(_exe_name("ffprobe")) or shutil.which("ffprobe")
    return Path(found) if found else None


def check_ffmpeg_available(config: dict | None = None) -> RuntimeCheckResult:
    """检查 ffmpeg 和 ffprobe 是否可执行。"""
    ffmpeg = resolve_ffmpeg_path(config)
    if not ffmpeg:
        return RuntimeCheckResult(False, message="未找到 ffmpeg，请安装或在设置中配置路径。")
    ffprobe = resolve_ffprobe_path(config, ffmpeg)
    if not ffprobe:
        return RuntimeCheckResult(False, ffmpeg_path=ffmpeg, message="未找到 ffprobe，无法探测音视频文件。")

    for path, label in ((ffmpeg, "ffmpeg"), (ffprobe, "ffprobe")):
        try:
            subprocess.run(  # nosec B603
                [str(path), "-version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except OSError:
            return RuntimeCheckResult(False, ffmpeg, ffprobe, f"{label} 无法执行。")
        except subprocess.TimeoutExpired:
            return RuntimeCheckResult(False, ffmpeg, ffprobe, f"{label} 响应超时。")
    return RuntimeCheckResult(True, ffmpeg, ffprobe, "ffmpeg 可用")


def _configured_path(config: dict | None, key: str = "ffmpeg_path") -> Path | None:
    value = (
        (config or {})
        .get("audio", {})
        .get("preprocessing", {})
        .get(key)
    )
    if not value:
        return None
    return Path(str(value)).expanduser()


def _exe_name(name: str) -> str:
    return f"{name}.exe" if _is_windows() else name


def _is_windows() -> bool:
    return __import__("os").name == "nt"
