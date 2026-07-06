from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextBrowser  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_import_detail_webview_module_succeeds() -> None:
    import src.ui.detail_webview as detail_webview

    assert hasattr(detail_webview, "DetailWebBridge")
    assert hasattr(detail_webview, "DetailWebView")


def test_bridge_post_message_emits_dict_and_json_string() -> None:
    from src.ui.detail_webview import DetailWebBridge

    bridge = DetailWebBridge()
    received: list[dict] = []
    bridge.commandReceived.connect(received.append)

    bridge.postMessage({"command": "ready"})
    bridge.postMessage('{"command": "seek", "seconds": 3.5}')

    assert received == [
        {"command": "ready"},
        {"command": "seek", "seconds": 3.5},
    ]


def test_bridge_post_message_handles_malformed_input_without_raising() -> None:
    from src.ui.detail_webview import DetailWebBridge

    bridge = DetailWebBridge()
    received: list[dict] = []
    bridge.commandReceived.connect(received.append)

    bridge.postMessage("{not-json")
    bridge.postMessage(["bad"])
    bridge.postMessage(None)

    assert all(item.get("command") == "renderError" for item in received)


def test_detail_webview_fallback_instantiates_and_renders_current_markdown_content() -> None:
    _app()

    from src.ui.detail_webview import DetailWebView

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


def test_detail_webview_fallback_shows_only_markdown_body_without_debug_fields() -> None:
    _app()

    from src.ui.detail_webview import DetailWebView

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


def test_detail_webview_fallback_playback_update_does_not_rerender_body() -> None:
    _app()

    from src.ui.detail_webview import DetailWebView

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


def test_detail_webview_fallback_renders_timeline_only_in_timeline_mode() -> None:
    _app()

    from src.ui.detail_webview import DetailWebView

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

    from src.ui.detail_webview import DetailWebView

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
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "assets" / "detail_viewer"

    index = root / "index.html"
    css = root / "detail-viewer.css"
    js = root / "detail-viewer.js"
    markdown = root / "vendor" / "markdown-it.min.js"

    for path in (index, css, js, markdown):
        assert path.exists(), path

    index_text = index.read_text(encoding="utf-8")
    assert "detail-viewer.js" in index_text
    assert "detailTitle" not in index_text
    assert "modeLabel" not in index_text
    assert "copyButton" not in index_text
    assert "timeline-row" in css.read_text(encoding="utf-8")
    script = js.read_text(encoding="utf-8")
    assert "NoisNoteDetail" in script
    assert "setContent" in script
    assert "updatePlayback" in script
    markdown_text = markdown.read_text(encoding="utf-8")
    assert "markdown-it 14.1.0" in markdown_text
    assert "compatibility" not in markdown_text.lower()


def test_detail_viewer_timeline_rendering_uses_generation_token() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "assets" / "detail_viewer"
    script = (root / "detail-viewer.js").read_text(encoding="utf-8")

    assert "timelineRenderGeneration" in script
    assert "state.timelineRenderGeneration += 1" in script
    assert "renderTimelineChunk(items, 0, generation)" in script
    assert "generation !== state.timelineRenderGeneration" in script


def test_detail_viewer_resets_active_timeline_cache_when_clearing_rows() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "assets" / "detail_viewer"
    script = (root / "detail-viewer.js").read_text(encoding="utf-8")

    clear_start = script.index("function clearTimeline()")
    clear_end = script.index("function renderTimelineChunk", clear_start)
    clear_timeline_source = script[clear_start:clear_end]

    assert "state.activeId = null" in clear_timeline_source
