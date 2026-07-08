"""详情区域 WebView 外壳与无 WebEngine 降级视图。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPlainTextEdit, QTextBrowser, QVBoxLayout, QWidget

from .models import timeline_display_text

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


_ASSET_DIR = Path(__file__).resolve().parent / "assets"
_INDEX_HTML = _ASSET_DIR / "index.html"
_DETAIL_CSS = _ASSET_DIR / "detail-viewer.css"
_VNOTE_READ_MODE_ZOOM_FACTOR = 1.1


def _is_link_click_navigation(request_type: Any) -> bool:
    if QWebEnginePage is None:
        return False
    navigation_type = getattr(QWebEnginePage, "NavigationType", None)
    link_clicked = getattr(navigation_type, "NavigationTypeLinkClicked", None) if navigation_type is not None else None
    if link_clicked is None:
        link_clicked = getattr(QWebEnginePage, "NavigationTypeLinkClicked", None)
    return link_clicked is not None and request_type == link_clicked


def _fallback_stylesheet() -> str:
    try:
        return _DETAIL_CSS.read_text(encoding="utf-8")
    except OSError:
        return ""


class DetailWebBridge(QObject):
    """暴露给 JS 的轻量消息桥，所有异常输入都转成诊断消息。"""

    commandReceived = Signal(dict)

    @Slot(str)
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
        if _is_link_click_navigation(request_type):
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
        self._pending_edit_mode: bool | None = None
        self._pending_search_state: dict[str, Any] | None = None
        self.is_edit_mode = False
        self.current_search_state: dict[str, Any] = {"query": "", "index": 0}
        self._rendering_fallback = False
        self._bridge = DetailWebBridge(self)
        self._bridge.commandReceived.connect(self._handle_bridge_command)
        self._web_view: Any = None
        self._fallback: QTextBrowser | QPlainTextEdit | None = None
        self._layout_transition_cover: QWidget | None = None
        self._layout_transition_cover_height: int | None = None
        self._layout_transition_cover_generation = 0

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

    def cover_bottom_for_layout_transition(self, height: int = 180, duration_ms: int = 220) -> None:
        """短暂盖住 WebEngine 底部新暴露区域，避免异步合成帧露出黑底。"""
        self._layout_transition_cover_height = max(1, int(height))
        self._show_layout_transition_cover(duration_ms)

    def cover_for_layout_transition(self, duration_ms: int = 220) -> None:
        """短暂遮住整个 WebEngine，用于宽度突变时避免右侧黑色合成帧。"""
        self._layout_transition_cover_height = None
        self._show_layout_transition_cover(duration_ms)

    def _show_layout_transition_cover(self, duration_ms: int) -> None:
        cover = self._layout_transition_cover
        if cover is None:
            cover = QWidget(self)
            cover.setObjectName("DetailWebViewLayoutTransitionCover")
            cover.setStyleSheet("background-color: #ffffff;")
            cover.hide()
            self._layout_transition_cover = cover
        self._position_layout_transition_cover()
        cover.raise_()
        cover.show()
        self._layout_transition_cover_generation += 1
        generation = self._layout_transition_cover_generation
        QTimer.singleShot(max(0, int(duration_ms)), lambda: self._hide_layout_transition_cover(generation))

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        cover = self._layout_transition_cover
        if cover is not None and cover.isVisible():
            self._position_layout_transition_cover()

    def _hide_layout_transition_cover(self, generation: int) -> None:
        if generation != self._layout_transition_cover_generation:
            return
        if self._layout_transition_cover is not None:
            self._layout_transition_cover.hide()

    def _position_layout_transition_cover(self) -> None:
        cover = self._layout_transition_cover
        if cover is None:
            return
        height = self._layout_transition_cover_height
        if height is None:
            cover.setGeometry(self.rect())
            return
        cover_height = max(1, min(max(1, int(height)), max(1, self.height())))
        cover.setGeometry(0, max(0, self.height() - cover_height), self.width(), cover_height)

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

    def set_edit_mode(self, enabled: bool) -> None:
        """切换详情正文的编辑/视图模式。"""

        self.is_edit_mode = bool(enabled)
        if self.is_webengine_available():
            self._pending_edit_mode = self.is_edit_mode
            self._flush_pending_js()
            return
        if self._fallback is not None:
            self._render_fallback()
            self._fallback.setReadOnly(not self.is_edit_mode)

    def set_search_state(self, query: str, index: int = 0) -> None:
        """同步详情正文搜索词和当前匹配序号。"""

        try:
            safe_index = max(0, int(index))
        except (TypeError, ValueError):
            safe_index = 0
        self.current_search_state = {"query": str(query or ""), "index": safe_index}
        if self.is_webengine_available():
            self._pending_search_state = dict(self.current_search_state)
            self._flush_pending_js()

    def update_playback(self, payload: dict) -> None:
        """保存播放状态，并在 WebView 可用时通知前端高亮当前时间轴行。"""

        self.current_playback = dict(payload)
        if self.is_webengine_available():
            self._pending_playback = self.current_playback
            self._flush_pending_js()
            return

    def _can_create_webengine(self) -> bool:
        if QWebEngineView is None or QWebChannel is None or QWebEnginePage is None:
            return False
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            return False
        return _INDEX_HTML.exists()

    def _setup_webengine(self, layout: QVBoxLayout) -> None:
        self._web_view = QWebEngineView(self)
        page = _LocalOnlyWebEnginePage(self._web_view)
        page.setBackgroundColor(QColor("#ffffff"))
        channel = QWebChannel(page)
        channel.registerObject("detailBridge", self._bridge)
        page.setWebChannel(channel)
        self._web_view.setPage(page)
        self._web_view.setStyleSheet("background-color: #ffffff;")
        self._web_view.setZoomFactor(_VNOTE_READ_MODE_ZOOM_FACTOR)
        self._web_view.loadFinished.connect(self._handle_load_finished)
        self._web_view.load(QUrl.fromLocalFile(str(_INDEX_HTML)))
        layout.addWidget(self._web_view)

    def _setup_fallback(self, layout: QVBoxLayout) -> None:
        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(False)
        browser.setReadOnly(True)
        browser.document().setDefaultStyleSheet(_fallback_stylesheet())
        browser.textChanged.connect(self._handle_fallback_text_changed)
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
        self._pending_edit_mode = None
        self._pending_search_state = None

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
        if self._pending_edit_mode is not None:
            self._run_js_call("setEditMode", {"enabled": self._pending_edit_mode})
            self._pending_edit_mode = None
        if self._pending_search_state is not None:
            self._run_js_call("setSearchState", self._pending_search_state)
            self._pending_search_state = None

    def _run_js_call(self, name: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False)
        self._web_view.page().runJavaScript(f"window.NoisNoteDetail.{name}({encoded});")

    def _render_fallback(self) -> None:
        if self._fallback is None:
            return
        payload = self.current_payload or {}
        mode = str(payload.get("mode") or "transcript")
        content = str(payload.get("content") or "")
        timeline = payload.get("timeline")
        self._rendering_fallback = True
        try:
            if mode == "timeline":
                lines = timeline_display_text(timeline if isinstance(timeline, list) else [])
                self._fallback.setPlainText(lines)
                self._fallback.setReadOnly(not self.is_edit_mode)
                return
            if self.is_edit_mode:
                self._fallback.setPlainText(content)
            else:
                self._fallback.setMarkdown(content)
            self._fallback.setReadOnly(not self.is_edit_mode)
        finally:
            self._rendering_fallback = False

    def _handle_fallback_text_changed(self) -> None:
        if self._fallback is None or self._rendering_fallback or not self.is_edit_mode:
            return
        payload = self.current_payload or {}
        mode = str(payload.get("mode") or "transcript")
        if mode == "timeline":
            return
        text = self._fallback.toPlainText()
        self.current_payload = dict(payload, content=text)
        if self._command_callback is not None:
            self._command_callback(
                {
                    "command": "contentChanged",
                    "recordKey": payload.get("recordKey", ""),
                    "revision": payload.get("revision", 0),
                    "mode": mode,
                    "text": text,
                }
            )
