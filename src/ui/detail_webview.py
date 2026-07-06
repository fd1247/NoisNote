"""详情区域 WebView 外壳与无 WebEngine 降级视图。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWidgets import QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget

try:  # pragma: no cover - 可选依赖在 CI 和精简环境里经常不存在
    from PySide6.QtWebChannel import QWebChannel
except ImportError:  # pragma: no cover
    QWebChannel = None  # type: ignore[assignment]

try:  # pragma: no cover - WebEngine 是否可用取决于安装包和平台
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover
    QWebEnginePage = None  # type: ignore[assignment]
    QWebEngineView = None  # type: ignore[assignment]


_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "detail_viewer"
_INDEX_HTML = _ASSET_DIR / "index.html"


class DetailWebBridge(QObject):
    """暴露给 JS 的轻量消息桥，所有异常输入都转成诊断消息。"""

    commandReceived = Signal(dict)

    @Slot(object)
    def postMessage(self, value: object) -> None:
        """接收 JS 消息；支持 dict 和 JSON 字符串， malformed 输入不向外抛异常。"""

        if isinstance(value, dict):
            self.commandReceived.emit(dict(value))
            return

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                self._emit_render_error("无法解析详情页消息。")
                return
            if isinstance(parsed, dict):
                self.commandReceived.emit(parsed)
                return
            self._emit_render_error("详情页消息不是对象。")
            return

        self._emit_render_error("详情页消息类型不受支持。")

    def _emit_render_error(self, message: str) -> None:
        self.commandReceived.emit({"command": "renderError", "message": message})


class _LocalOnlyWebEnginePage(QWebEnginePage if QWebEnginePage is not None else QObject):
    """限制 WebEngine 只加载本地资源，外链由 JS 发回主进程处理。"""

    def acceptNavigationRequest(self, url: QUrl, request_type: Any, is_main_frame: bool) -> bool:  # noqa: N802
        if not is_main_frame:
            return True
        if request_type == self.NavigationTypeLinkClicked:
            return False
        return url.isLocalFile() or url.scheme() in {"", "qrc"}


class DetailWebView(QWidget):
    """未来详情区使用的 WebView 包装器；缺少 WebEngine 时自动显示纯文本降级视图。"""

    def __init__(self, parent: QWidget | None = None, command_callback: Callable[[dict], None] | None = None) -> None:
        super().__init__(parent)
        self.current_payload: dict[str, Any] | None = None
        self.current_playback: dict[str, Any] | None = None
        self._command_callback = command_callback
        self._page_ready = False
        self._pending_content: dict[str, Any] | None = None
        self._pending_playback: dict[str, Any] | None = None
        self._bridge = DetailWebBridge(self)
        self._bridge.commandReceived.connect(self._handle_bridge_command)
        self._web_view: Any = None
        self._fallback: QTextBrowser | QPlainTextEdit | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if self._can_create_webengine():
            try:
                self._setup_webengine(layout)
            except Exception:
                self._reset_webengine_state()
                self._setup_fallback(layout)
        else:
            self._setup_fallback(layout)

    def is_webengine_available(self) -> bool:
        """返回当前实例是否真实启用了 WebEngine。"""

        return self._web_view is not None

    def set_content(self, payload: dict) -> None:
        """保存并渲染详情 payload；WebView 未 ready 时先排队。"""

        self.current_payload = dict(payload)
        if self.is_webengine_available():
            self._pending_content = self.current_payload
            self._flush_pending_js()
            return
        self._render_fallback()

    def update_playback(self, payload: dict) -> None:
        """保存播放状态，并在 WebView 可用时通知前端高亮当前时间轴行。"""

        self.current_playback = dict(payload)
        if self.is_webengine_available():
            self._pending_playback = self.current_playback
            self._flush_pending_js()
            return
        self._render_fallback()

    def _can_create_webengine(self) -> bool:
        if QWebEngineView is None or QWebChannel is None or QWebEnginePage is None:
            return False
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            return False
        return _INDEX_HTML.exists()

    def _setup_webengine(self, layout: QVBoxLayout) -> None:
        self._web_view = QWebEngineView(self)
        page = _LocalOnlyWebEnginePage(self._web_view)
        channel = QWebChannel(page)
        channel.registerObject("detailBridge", self._bridge)
        page.setWebChannel(channel)
        self._web_view.setPage(page)
        self._web_view.loadFinished.connect(self._handle_load_finished)
        self._web_view.load(QUrl.fromLocalFile(str(_INDEX_HTML)))
        layout.addWidget(self._web_view)

    def _setup_fallback(self, layout: QVBoxLayout) -> None:
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(False)
        browser.setReadOnly(True)
        layout.addWidget(browser)
        self._fallback = browser
        self._render_fallback()

    def _reset_webengine_state(self) -> None:
        """WebEngine 初始化失败时清空半初始化状态，确保降级视图可继续使用。"""

        web_view = self._web_view
        if web_view is not None and hasattr(web_view, "deleteLater"):
            layout = self.layout()
            if layout is not None and isinstance(web_view, QWidget):
                layout.removeWidget(web_view)
            try:
                web_view.deleteLater()
            except RuntimeError:
                pass
        self._web_view = None
        self._page_ready = False
        self._pending_content = None
        self._pending_playback = None

    def _handle_load_finished(self, ok: bool) -> None:
        if not ok:
            self._reset_webengine_state()
            self._setup_fallback(self.layout())  # type: ignore[arg-type]
            return
        self._flush_pending_js()

    def _handle_bridge_command(self, command: dict) -> None:
        if command.get("command") == "ready":
            self._page_ready = True
            self._flush_pending_js()
        if self._command_callback is not None:
            self._command_callback(command)

    def _flush_pending_js(self) -> None:
        if not self._page_ready or self._web_view is None:
            return
        if self._pending_content is not None:
            self._run_js_call("setContent", self._pending_content)
            self._pending_content = None
        if self._pending_playback is not None:
            self._run_js_call("updatePlayback", self._pending_playback)
            self._pending_playback = None

    def _run_js_call(self, name: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False)
        self._web_view.page().runJavaScript(f"window.NoisNoteDetail.{name}({encoded});")

    def _render_fallback(self) -> None:
        if self._fallback is None:
            return
        payload = self.current_payload or {}
        title = str(payload.get("title") or "详情")
        mode = str(payload.get("mode") or "transcript")
        content = str(payload.get("content") or "")
        timeline = payload.get("timeline")
        lines = [title, "", f"模式：{mode}", ""]
        if content:
            lines.extend([content, ""])
        if isinstance(timeline, list) and timeline:
            lines.append("时间轴")
            for item in timeline:
                if not isinstance(item, dict):
                    continue
                start = item.get("start", "")
                end = item.get("end", "")
                text = str(item.get("text") or "").strip()
                if text:
                    lines.append(f"{start} - {end}  {text}")
        if self.current_playback:
            lines.extend(["", f"播放位置：{self.current_playback.get('positionSeconds', 0)}"])
        self._fallback.setPlainText("\n".join(lines).strip())
