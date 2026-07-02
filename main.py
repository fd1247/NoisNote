"""NoisNote - 入口"""
import os
import multiprocessing
import subprocess
import sys


def _patch_subprocess_hide_window() -> None:
    """Windows 下隐藏 worker 内部继发的命令行子进程窗口。"""
    if sys.platform != "win32":
        return
    if getattr(subprocess.Popen, "_noisnote_hidden_window", False):
        return
    original_popen = subprocess.Popen

    class HiddenPopen(original_popen):
        _noisnote_hidden_window = True

        def __init__(self, *args, **kwargs):
            if "startupinfo" not in kwargs:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | int(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            super().__init__(*args, **kwargs)

    subprocess.Popen = HiddenPopen  # type: ignore[misc]


def _configure_pydub_ffmpeg() -> None:
    """把打包的 ffmpeg/ffprobe 路径加入 PATH，pydub 的 get_prober_name() 依赖 which() 查找。"""
    from src.utils.ffmpeg import resolve_ffmpeg_path

    ffmpeg = resolve_ffmpeg_path()
    if ffmpeg:
        ffmpeg_dir = str(ffmpeg.parent)
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")


def _run_asr_worker() -> int | None:
    if "--asr-worker" not in sys.argv:
        return None
    _patch_subprocess_hide_window()
    _configure_pydub_ffmpeg()
    from src.asr.worker_process import main as asr_worker_main

    index = sys.argv.index("--asr-worker")
    return asr_worker_main(sys.argv[index + 1 :])

if __name__ == "__main__":
    # PyInstaller 打包后使用 multiprocessing 必须调用 freeze_support()
    multiprocessing.freeze_support()
    worker_exit_code = _run_asr_worker()
    if worker_exit_code is not None:
        sys.exit(worker_exit_code)
    from src.app.application import main

    sys.exit(main())
