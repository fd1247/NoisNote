"""详情结果区状态更新工具。"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QPushButton


class ResultStateOwner(Protocol):
    """拥有详情区控件的对象。"""

    active_result_tab: str
    summary_markdown_text: str


_VALID_RESULT_TABS = {"transcript", "timeline", "summary"}


def set_transcript_text(owner: ResultStateOwner, text: str) -> None:
    """写入转录文本，并同步当前页复制按钮。"""
    owner.transcript_text.setPlainText(text)  # type: ignore[attr-defined]
    if hasattr(owner, "transcript_copy_button"):
        owner.transcript_copy_button.setVisible(bool(text.strip()))  # type: ignore[attr-defined]
    if getattr(owner, "active_result_tab", "transcript") == "transcript":
        _sync_detail_webview(owner, "transcript", text)


def set_result_tab(owner: ResultStateOwner, kind: str) -> None:
    """切换详情结果区标签，并保留用户的当前选择。"""
    if kind not in _VALID_RESULT_TABS:
        kind = "transcript"
    owner.active_result_tab = kind
    if hasattr(owner, "result_stack"):
        index_map = {"transcript": 0, "timeline": 1, "summary": 2}
        owner.result_stack.setCurrentIndex(index_map[kind])  # type: ignore[attr-defined]
    if hasattr(owner, "transcript_tab_button"):
        owner.transcript_tab_button.setChecked(kind == "transcript")  # type: ignore[attr-defined]
    if hasattr(owner, "timeline_tab_button"):
        owner.timeline_tab_button.setChecked(kind == "timeline")  # type: ignore[attr-defined]
    if hasattr(owner, "summary_tab_button"):
        owner.summary_tab_button.setChecked(kind == "summary")  # type: ignore[attr-defined]
    _sync_detail_webview(owner, kind)


def set_summary_text(owner: ResultStateOwner, summary: str) -> None:
    """以 Markdown 方式展示总结，同时保留原文用于复制和导出。"""
    owner.summary_markdown_text = summary
    if hasattr(owner, "summary_copy_button"):
        owner.summary_copy_button.setVisible(bool(summary.strip()))  # type: ignore[attr-defined]
    if not summary.strip():
        owner.summary_text.clear()  # type: ignore[attr-defined]
        if getattr(owner, "active_result_tab", "transcript") == "summary":
            _sync_detail_webview(owner, "summary", "")
        return
    owner.summary_text.setMarkdown(summary)  # type: ignore[attr-defined]
    if getattr(owner, "active_result_tab", "transcript") == "summary":
        _sync_detail_webview(owner, "summary", summary)


def _sync_detail_webview(owner: ResultStateOwner, kind: str, content: str | None = None) -> None:
    """同步详情 WebView 的最小兼容 payload，完整数据绑定由后续任务接管。"""
    detail_webview = getattr(owner, "detail_webview", None)
    if detail_webview is None or not hasattr(detail_webview, "set_content"):
        return
    if kind not in _VALID_RESULT_TABS:
        kind = "transcript"
    payload = dict(getattr(detail_webview, "current_payload", None) or {})
    if content is None:
        content = _current_mode_text(owner, kind)
    title_label = getattr(owner, "detail_title_label", None)
    title = title_label.text() if title_label is not None and hasattr(title_label, "text") else "详情"
    payload.update(
        {
            "mode": kind,
            "title": title,
            "content": content,
            "timeline": payload.get("timeline") or [],
        }
    )
    detail_webview.set_content(payload)


def _current_mode_text(owner: ResultStateOwner, kind: str) -> str:
    """读取当前模式的兼容控件文本，避免 Task 4 引入完整历史 payload 依赖。"""
    if kind == "summary":
        return str(getattr(owner, "summary_markdown_text", ""))
    if kind == "timeline" and hasattr(owner, "timeline_text"):
        return owner.timeline_text.toPlainText()  # type: ignore[attr-defined]
    if hasattr(owner, "transcript_text"):
        return owner.transcript_text.toPlainText()  # type: ignore[attr-defined]
    return ""


def set_button_object_name(button: QPushButton, object_name: str) -> None:
    """切换按钮样式对象名，并立即刷新 Qt 样式。"""
    if button.objectName() == object_name:
        return
    button.setObjectName(object_name)
    button.style().unpolish(button)
    button.style().polish(button)
