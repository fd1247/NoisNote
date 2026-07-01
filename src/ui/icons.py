"""应用内图标加载。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon


_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
_SVG_DIR = _ASSETS_DIR / "svg"
_APP_ICON_PATH = _ASSETS_DIR / "icon.ico"

# 图标名称到 SVG 文件的映射
_ICON_MAP: dict[str, str] = {
    "back": "返回.svg",
    "settings": "设置.svg",
    "general": "设置.svg",
    "models": "模型.svg",
    "hotwords": "热词管理.svg",
    "shortcuts": "快捷键.svg",
    "import": "导入.svg",
    "filter": "筛选.svg",
    "play": "播放.svg",
    "pause": "暂停.svg",
    "rewind15": "快退15s.svg",
    "forward15": "快进15s.svg",
    "more": "更多.svg",
    "record": "麦克风.svg",
    "record_light": "麦克风-白.svg",
}


def make_action_icon(kind: str) -> QIcon:
    """加载侧栏和录音按钮图标。"""
    svg_name = _ICON_MAP.get(kind) or _ICON_MAP.get(kind.removesuffix("_light"))
    if svg_name:
        svg_path = _SVG_DIR / svg_name
        if svg_path.exists():
            return QIcon(str(svg_path))
    # 回退到麦克风图标
    fallback = _SVG_DIR / "麦克风.svg"
    return QIcon(str(fallback)) if fallback.exists() else QIcon()


def make_app_icon() -> QIcon:
    """返回应用窗口图标。"""
    return QIcon(str(_APP_ICON_PATH))


def make_eye_icon(showing: bool) -> QIcon:
    """加载 API Key 显示/隐藏图标。"""
    svg_name = "eye-open.svg" if showing else "eye-close.svg"
    svg_path = _SVG_DIR / svg_name
    return QIcon(str(svg_path)) if svg_path.exists() else QIcon()


def make_combo_arrow_icon() -> QIcon:
    """加载下拉框箭头图标。"""
    svg_path = _SVG_DIR / "下拉.svg"
    return QIcon(str(svg_path)) if svg_path.exists() else QIcon()


def make_history_icon() -> QIcon:
    """加载历史记录图标。"""
    svg_path = _SVG_DIR / "历史记录-播放.svg"
    return QIcon(str(svg_path)) if svg_path.exists() else QIcon()
