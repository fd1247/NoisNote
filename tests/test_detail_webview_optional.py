from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextBrowser, QWidget  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_import_detail_webview_module_succeeds() -> None:
    import src.ui.detail.webview as detail_webview

    assert hasattr(detail_webview, "DetailWebBridge")
    assert hasattr(detail_webview, "DetailWebView")


def test_detail_webview_uses_vnote_read_mode_zoom_factor() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "webview.py").read_text(
        encoding="utf-8"
    )

    assert "_VNOTE_READ_MODE_ZOOM_FACTOR = 1.1" in source
    assert "setZoomFactor(_VNOTE_READ_MODE_ZOOM_FACTOR)" in source


def test_detail_webview_forces_white_webengine_background() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "webview.py").read_text(
        encoding="utf-8"
    )

    assert "QColor" in source
    assert 'setBackgroundColor(QColor("#ffffff"))' in source
    assert 'background-color: #ffffff;' in source


def test_detail_webview_layout_transition_cover_can_cover_whole_view() -> None:
    from src.ui.detail.webview import DetailWebView

    app = _app()
    view = DetailWebView()
    try:
        view.resize(320, 180)

        view.cover_for_layout_transition(1)
        app.processEvents()

        cover = view.findChild(QWidget, "DetailWebViewLayoutTransitionCover")
        assert cover is not None
        assert cover.geometry() == view.rect()
    finally:
        view.close()
        app.processEvents()


def test_bridge_post_message_emits_dict_and_json_string() -> None:
    from src.ui.detail.webview import DetailWebBridge

    bridge = DetailWebBridge()
    received: list[dict] = []
    bridge.commandReceived.connect(received.append)

    bridge.postMessage({"command": "ready"})
    bridge.postMessage('{"command": "seek", "seconds": 3.5}')

    assert received == [
        {"command": "ready"},
        {"command": "seek", "seconds": 3.5},
    ]


def test_bridge_webchannel_slot_accepts_json_string_protocol() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "webview.py").read_text(
        encoding="utf-8"
    )

    assert "@Slot(str)" in source
    assert "@Slot(object)" not in source


def test_bridge_post_message_handles_malformed_input_without_raising() -> None:
    from src.ui.detail.webview import DetailWebBridge

    bridge = DetailWebBridge()
    received: list[dict] = []
    bridge.commandReceived.connect(received.append)

    bridge.postMessage("{not-json")
    bridge.postMessage(["bad"])
    bridge.postMessage(None)

    assert all(item.get("command") == "renderError" for item in received)


def test_local_webengine_page_allows_initial_file_navigation_without_legacy_enum() -> None:
    from src.ui.detail.webview import _LocalOnlyWebEnginePage

    class FakePage:
        pass

    class FakeUrl:
        def isLocalFile(self) -> bool:  # noqa: N802
            return True

        def scheme(self) -> str:
            return "file"

    allowed = _LocalOnlyWebEnginePage.acceptNavigationRequest(
        FakePage(),
        FakeUrl(),
        object(),
        True,
    )

    assert allowed is True


def test_detail_webview_fallback_instantiates_and_renders_current_markdown_content() -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    view = DetailWebView(command_callback=lambda _command: None)
    payload = {
        "mode": "summary",
        "title": "Meeting Note",
        "content": "# Summary\n\nThis is **summary**.",
        "timeline": [{"start": 1.0, "end": 2.0, "text": "first sentence"}],
        "playback": {"positionSeconds": 1.2, "isPlaying": True},
    }

    view.set_content(payload)
    view.update_playback({"positionSeconds": 1.6, "isPlaying": False})

    assert view.current_payload == payload
    assert view.current_playback == {"positionSeconds": 1.6, "isPlaying": False}
    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        rendered_text = browser.toPlainText()
        rendered_html = browser.toHtml()
        assert "Summary" in rendered_text
        assert "This is summary." in rendered_text
        assert "Meeting Note" not in rendered_text
        assert "first sentence" not in rendered_text
        assert "<span style=\" font-weight:700;\">summary</span>" in rendered_html


def test_detail_webview_fallback_loads_vnote_stylesheet() -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    view = DetailWebView(command_callback=lambda _command: None)

    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        stylesheet = browser.document().defaultStyleSheet()

        assert "font-family" in stylesheet
        assert "YaHei Consolas Hybrid" in stylesheet
        assert "font-size: 2.2rem;" in stylesheet
        assert "width:100%;" in stylesheet
        assert "#vx-content" in stylesheet


def test_detail_webview_fallback_shows_only_markdown_body_without_debug_fields() -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    view = DetailWebView(command_callback=lambda _command: None)
    payload = {
        "mode": "summary",
        "title": "Debug Title",
        "content": "# Summary\n\n**Topic**: Markdown rendering\n\n1. **First**: ordered item",
        "timeline": [{"start": 1.0, "end": 2.0, "text": "timeline text"}],
        "playback": {"positionSeconds": 12.5, "isPlaying": True},
    }

    view.set_content(payload)
    view.update_playback({"positionSeconds": 13.5, "isPlaying": False})

    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        rendered_text = browser.toPlainText()
        rendered_html = browser.toHtml()

        assert "Debug Title" not in rendered_text
        assert "mode:" not in rendered_text.lower()
        assert "position" not in rendered_text.lower()
        assert "Summary" in rendered_text
        assert "ordered item" in rendered_text
        assert "<span style=\" font-weight:700;\">Topic</span>" in rendered_html
        assert "<ol" in rendered_html


def test_detail_webview_empty_markdown_renders_blank_body() -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    view = DetailWebView(command_callback=lambda _command: None)
    payload = {
        "mode": "transcript",
        "title": "Empty Body",
        "content": "",
        "timeline": [],
        "playback": {"positionSeconds": 0.0, "isPlaying": False},
    }

    view.set_content(payload)

    assert view.current_payload == payload
    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        assert browser.toPlainText() == ""


def test_detail_webview_fallback_playback_update_does_not_rerender_body() -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    view = DetailWebView(command_callback=lambda _command: None)
    payload = {
        "mode": "summary",
        "title": "Playback Check",
        "content": "# Summary\n\nKeep the reader scroll and selection stable.",
        "timeline": [{"start": 1.0, "end": 2.0, "text": "timeline text"}],
        "playback": {"positionSeconds": 0.0, "isPlaying": False},
    }

    view.set_content(payload)

    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        revision_before = browser.document().revision()

        view.update_playback({"positionSeconds": 42.0, "isPlaying": True})

        assert browser.document().revision() == revision_before
        assert view.current_playback == {"positionSeconds": 42.0, "isPlaying": True}


def test_detail_webview_fallback_edit_mode_toggles_readonly() -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    view = DetailWebView(command_callback=lambda _command: None)

    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        assert browser.isReadOnly()

        view.set_edit_mode(True)
        assert not browser.isReadOnly()

        view.set_edit_mode(False)
        assert browser.isReadOnly()


def test_detail_webview_fallback_edit_mode_shows_raw_markdown() -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    view = DetailWebView(command_callback=lambda _command: None)
    view.set_content({"mode": "summary", "content": "**Bold** text", "timeline": []})

    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        assert browser.toPlainText() == "Bold text"

        view.set_edit_mode(True)
        assert browser.toPlainText() == "**Bold** text"

        view.set_edit_mode(False)
        assert browser.toPlainText() == "Bold text"


def test_detail_webview_fallback_renders_timeline_only_in_timeline_mode() -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    view = DetailWebView()
    payload = {
        "mode": "timeline",
        "title": "Timeline Title",
        "content": "# Transcript",
        "timeline": [{"start": 0, "end": 1, "text": "readable timeline"}],
    }

    view.set_content(payload)

    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        rendered = browser.toPlainText()
        assert "readable timeline" in rendered
        assert "Transcript" not in rendered
        assert "Timeline Title" not in rendered


def test_detail_webview_falls_back_when_webengine_setup_raises(monkeypatch) -> None:
    _app()

    from src.ui.detail.webview import DetailWebView

    def raise_setup(self, layout) -> None:  # noqa: ANN001
        self._web_view = object()
        raise RuntimeError("broken webengine runtime")

    monkeypatch.setattr(DetailWebView, "_can_create_webengine", lambda self: True)
    monkeypatch.setattr(DetailWebView, "_setup_webengine", raise_setup)

    view = DetailWebView()
    payload = {
        "mode": "transcript",
        "title": "Fallback Check",
        "content": "WebEngine failed, but body text remains readable.",
        "timeline": [{"start": 0, "end": 1, "text": "readable timeline"}],
    }

    view.set_content(payload)

    assert not view.is_webengine_available()
    browser = view.findChild(QTextBrowser)
    assert browser is not None
    rendered = browser.toPlainText()
    assert "WebEngine failed, but body text remains readable." in rendered
    assert "Fallback Check" not in rendered
    assert "readable timeline" not in rendered


def test_detail_viewer_assets_exist_and_export_expected_symbols() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "assets"

    index = root / "index.html"
    css = root / "detail-viewer.css"
    js = root / "detail-viewer.js"
    markdown = root / "vendor" / "markdown-it.min.js"

    for path in (index, css, js, markdown):
        assert path.exists(), path

    index_text = index.read_text(encoding="utf-8")
    assert "detail-viewer.js" in index_text
    assert 'id="body-container"' in index_text
    assert 'id="vx-content"' in index_text
    assert "detailTitle" not in index_text
    assert "modeLabel" not in index_text
    assert "copyButton" not in index_text
    css_text = css.read_text(encoding="utf-8")
    assert "timeline-entry" in css_text
    assert "timeline-range" in css_text
    assert "timeline-token" in css_text
    assert "timeline-token.active" in css_text
    assert 'font-family: "YaHei Consolas Hybrid", "Noto Sans", "Helvetica Neue"' in css_text
    assert "color: #34495E;" in css_text
    assert "font-size: 2.2rem;" in css_text
    assert "#vx-content" in css_text
    assert "padding: 10px 30px 40px;" in css_text
    assert "padding: 0 0 12px;" in css_text
    assert "html, body {" in css_text
    assert "min-height: 100%;" in css_text
    assert ".detail-shell,\n.content-panel," in css_text
    assert "min-height: 100vh;" in css_text
    assert "font-size: 17px;" in css_text
    assert "line-height: 1.5;" in css_text
    assert "#timelinePanel span.vx-search-match" in css_text
    assert "#timelinePanel span.vx-current-search-match" in css_text

    js_text = js.read_text(encoding="utf-8")
    assert 'window.addEventListener("scroll", handleScrollState' in js_text
    assert 'document.addEventListener("wheel"' not in js_text
    assert "handleWheelState" not in js_text
    assert "[hidden]" in css_text
    assert ".timeline-list[hidden]" in css_text
    assert "width:100%;" in css_text
    assert "background-color: #f2f2f2;" in css_text
    assert "color: #e96900;" in css_text
    script = js.read_text(encoding="utf-8")
    assert "NoisNoteDetail" in script
    assert "setContent" in script
    assert "updatePlayback" in script
    assert 'html: true' in script
    assert 'breaks: false' in script
    assert 'langPrefix: "lang-"' in script
    assert "postBridgeMessage" in script
    assert "JSON.stringify(command || {})" in script
    assert "state.bridge.postMessage(command)" not in script
    assert 'state.bridge.postMessage({ command: "renderError"' not in script
    assert "markdownItAnchor" in script
    assert "markdownItTocDoneRight" in script
    assert '"vx-data-anchor-icon": "¶"' in script
    assert "$(\"vx-content\")" in script
    assert 'mode === "timeline"' in script
    assert "clearTimeline();" in script
    assert 'return "";' in script
    assert 'command: "scrollState"' in script
    assert "window.addEventListener(\"scroll\"" in script
    assert "document.addEventListener(\"wheel\"" not in script
    assert "emitScrollState(false, true)" not in script
    assert "wheelDelta < 0" not in script
    assert "emitScrollState(true, true)" not in script
    assert "setEditMode" in script
    assert "editorPanel" in script
    assert 'Boolean(state.editMode) && selected !== "timeline"' in script
    assert '$("timelinePanel").hidden = selected !== "timeline";' in script
    assert 'command: "contentChanged"' in script
    assert "event.ctrlKey" not in script
    assert "canScrollDown" not in script
    assert "renderTimelineTokens" in script
    assert "timeline-token" in script
    assert "data-token-index" in script
    assert "activeToken" in script
    assert "currentViewportBottom" in script
    assert "isBelowCurrentPage" in script
    assert "scrollTimelinePage" in script
    assert 'text.setAttribute("contenteditable", state.editMode ? "true" : "false");' in script
    assert "emitTimelineChange" in script
    assert "tokenizeTimelineText(text, item.start || 0, item.end || item.start || 0)" in script
    assert "renderTimelineText(text, item)" in script
    assert 'item.tokens = text ? [{ start: item.start || 0, end: item.end || item.start || 0, text: text }] : []' not in script
    assert "timeline: state.payload.timeline" in script
    assert 'state.editMode && selectedMode() !== "timeline"' in script
    assert "setSearchState" in script
    assert 'command: "searchChanged"' in script
    assert "matchCount" in script
    assert "goToSearchMatch" not in script
    assert "vx-search-match" in script
    assert "vx-current-search-match" in script
    markdown_text = markdown.read_text(encoding="utf-8")
    assert "markdown-it 14.1.0" in markdown_text
    assert "compatibility" not in markdown_text.lower()


def test_detail_viewer_short_content_does_not_hide_header_on_wheel() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "assets"
    css_text = (root / "detail-viewer.css").read_text(encoding="utf-8")
    script = (root / "detail-viewer.js").read_text(encoding="utf-8")

    assert "#vx-content,\n#timelinePanel,\n.markdown-editor {\n    box-sizing: border-box;\n}" in css_text
    assert "function isPageMeaningfullyScrollable()" in script
    assert "DETAIL_SCROLL_OVERFLOW_THRESHOLD" in script
    assert "node.scrollTop = 0;" in script
    assert "emitScrollState(true, false);" in script
    assert "if (!isPageMeaningfullyScrollable())" in script


def test_detail_viewer_sanitizes_inline_styles_under_strict_csp() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "assets"
    index_text = (root / "index.html").read_text(encoding="utf-8")
    script = (root / "detail-viewer.js").read_text(encoding="utf-8")

    assert "style-src 'self'" in index_text
    assert "unsafe-inline" not in index_text
    assert "function sanitizeRenderedHtml" in script
    assert "template.innerHTML = html;" in script
    assert 'template.content.querySelectorAll("style").forEach' in script
    assert 'template.content.querySelectorAll("[style]").forEach' in script
    assert 'node.removeAttribute("style");' in script
    assert "return sanitizeRenderedHtml(html);" in script


def test_detail_viewer_loads_vnote_markdown_plugins() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "assets"
    index_text = (root / "index.html").read_text(encoding="utf-8")

    plugin_files = [
        "markdown-it-task-lists.js",
        "markdown-it-sub.min.js",
        "markdown-it-sup.min.js",
        "markdown-it-emoji.min.js",
        "markdown-it-footnote.min.js",
        "markdown-it-container.min.js",
        "markdown-it-front-matter.js",
        "markdown-it-imsize.min.js",
        "markdown-it-inject-linenumbers.js",
        "markdownItAnchor.umd.js",
        "markdownItTocDoneRight.umd.js",
        "markdown-it-implicit-figure.js",
        "markdown-it-mark.min.js",
    ]

    for filename in plugin_files:
        assert f"./vendor/{filename}" in index_text
        assert (root / "vendor" / filename).exists()


def test_detail_viewer_timeline_rendering_uses_generation_token() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "assets"
    script = (root / "detail-viewer.js").read_text(encoding="utf-8")

    assert "timelineRenderGeneration" in script
    assert "state.timelineRenderGeneration += 1" in script
    assert "renderTimelineChunk(items, 0, generation)" in script
    assert "generation !== state.timelineRenderGeneration" in script


def test_detail_viewer_timeline_uses_token_seek_and_viewport_paging() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "assets"
    script = (root / "detail-viewer.js").read_text(encoding="utf-8")

    assert 'span.dataset.start = String(token.start' in script
    assert 'command: "seek"' in script
    assert "var seekSeconds = target && target.dataset" in script
    assert "Number(target.dataset.start || current.dataset.start || 0)" in script
    assert "seconds: seekSeconds" in script
    assert "row.querySelectorAll(\".timeline-token.active\")" in script
    assert "active.activeToken.classList.add(\"active\")" in script
    assert "var scrollTarget = row;" in script
    assert "isOutsideCurrentPage(scrollTarget)" in script
    assert "isFullyVisible(scrollTarget)" in script
    assert "timelineContentRect(row)" in script
    assert "timelineTextLineRects(text)" in script
    assert "range.getClientRects()" in script
    assert "currentTimelineVisibleBottom()" in script
    assert "TIMELINE_PAGE_TOLERANCE" in script
    assert "var TIMELINE_PAGE_TOLERANCE = 2;" in script


def test_detail_viewer_debounces_edit_save_commands() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "assets"
    script = (root / "detail-viewer.js").read_text(encoding="utf-8")

    assert "editSaveTimer" in script
    assert "scheduleContentChanged" in script
    assert "window.clearTimeout(state.editSaveTimer)" in script
    assert "window.setTimeout" in script
    assert "isAboveCurrentPage" in script
    assert 'target.scrollIntoView({ block: "start", behavior: "smooth" })' in script
    assert "window.setTimeout(function ()" not in script


def test_detail_viewer_resets_active_timeline_cache_when_clearing_rows() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "detail" / "assets"
    script = (root / "detail-viewer.js").read_text(encoding="utf-8")

    clear_start = script.index("function clearTimeline()")
    clear_end = script.index("function renderTimelineChunk", clear_start)
    clear_timeline_source = script[clear_start:clear_end]

    assert "state.activeId = null" in clear_timeline_source
