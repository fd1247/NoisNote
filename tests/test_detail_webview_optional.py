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


def test_detail_webview_fallback_instantiates_and_renders_readable_content() -> None:
    _app()

    from src.ui.detail_webview import DetailWebView

    view = DetailWebView(command_callback=lambda _command: None)
    payload = {
        "mode": "summary",
        "title": "会议记录",
        "content": "# 摘要\n\n这是总结。",
        "timeline": [{"start": 1.0, "end": 2.0, "text": "第一句"}],
        "playback": {"positionSeconds": 1.2, "isPlaying": True},
    }

    view.set_content(payload)
    view.update_playback({"positionSeconds": 1.6, "isPlaying": False})

    assert view.current_payload == payload
    assert view.current_playback == {"positionSeconds": 1.6, "isPlaying": False}
    if not view.is_webengine_available():
        browser = view.findChild(QTextBrowser)
        assert browser is not None
        rendered = browser.toPlainText()
        assert "会议记录" in rendered
        assert "摘要" in rendered
        assert "这是总结。" in rendered
        assert "第一句" in rendered


def test_detail_viewer_assets_exist_and_export_expected_symbols() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "ui" / "assets" / "detail_viewer"

    index = root / "index.html"
    css = root / "detail-viewer.css"
    js = root / "detail-viewer.js"
    markdown = root / "vendor" / "markdown-it.min.js"

    for path in (index, css, js, markdown):
        assert path.exists(), path

    assert "detail-viewer.js" in index.read_text(encoding="utf-8")
    assert "timeline-row" in css.read_text(encoding="utf-8")
    script = js.read_text(encoding="utf-8")
    assert "NoisNoteDetail" in script
    assert "setContent" in script
    assert "updatePlayback" in script
    assert "markdownit" in markdown.read_text(encoding="utf-8")
