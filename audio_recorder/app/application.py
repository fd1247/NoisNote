"""PySide6 应用入口。"""
from __future__ import annotations

import os
import subprocess
import sys

if sys.platform == "win32":
    import ctypes
    # 在 Qt 初始化 COM 之前，先以 MTA 模式初始化 COM，
    # 避免 soundcard 等库提前初始化 COM 导致 Qt 报 RPC_E_CHANGED_MODE
    # STA = 2 (COINIT_APARTMENTTHREADED)，Qt 和 soundcard 都需要 STA 模式
    ctypes.windll.ole32.CoInitializeEx(None, 2)

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .diagnostics import diagnose_asr_runtime
from ..utils.logging import init_logging, install_exception_hooks, log_event
from ..ui.styles import APP_STYLESHEET
from .version import get_version_string


def _patch_subprocess_hide_window() -> None:
    """确保所有子进程不弹出控制台窗口（影响 pydub 等第三方库内部调用）。"""
    if sys.platform != "win32":
        return
    _original_popen = subprocess.Popen

    class _HiddenPopen(_original_popen):
        def __init__(self, *args, **kwargs):
            if sys.platform == "win32" and "startupinfo" not in kwargs:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
                kwargs["startupinfo"] = si
            super().__init__(*args, **kwargs)

    subprocess.Popen = _HiddenPopen  # type: ignore[misc]


def _configure_pydub_ffmpeg() -> None:
    """把打包的 ffmpeg/ffprobe 路径加入 PATH，pydub 的 get_prober_name() 依赖 which() 查找。"""
    from ..utils.ffmpeg import resolve_ffmpeg_path
    ffmpeg = resolve_ffmpeg_path()
    if ffmpeg:
        ffmpeg_dir = str(ffmpeg.parent)
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


def main() -> int:
    """创建并启动 Qt 应用。"""

    _patch_subprocess_hide_window()

    if "--diagnose-asr-runtime" in sys.argv:
        return diagnose_asr_runtime()

    _configure_pydub_ffmpeg()

    log_dir = init_logging()
    install_exception_hooks()
    version = get_version_string()
    log_event(
        "app.started",
        module="app",
        message="应用启动",
        context={"log_dir": log_dir, "version": version},
    )
    app = QApplication(sys.argv)
    app.setApplicationName("音频转录与总结工具")
    app.setApplicationVersion(version)
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    window.show()

    exit_code = app.exec()
    log_event("app.exited", module="app", message="应用退出", context={"exit_code": exit_code})
    return exit_code
