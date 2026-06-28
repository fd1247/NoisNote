"""NoisNote —— Windows 桌面应用，录制/导入音视频，本地 ASR 转文字，LLM 总结。"""
from .app.version import APP_VERSION, get_version_string

__all__ = ["APP_VERSION", "get_version_string"]
__version__ = str(APP_VERSION)
