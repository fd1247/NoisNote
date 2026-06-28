"""详情结果区状态更新工具。"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QPushButton


class ResultStateOwner(Protocol):
    """拥有详情区控件的对象。"""

    active_result_tab: str
    summary_markdown_text: str


def set_transcript_text(owner: ResultStateOwner, text: str) -> None:
    """写入转录文本，并同步当前页复制按钮。"""
    owner.transcript_text.setPlainText(text)  # type: ignore[attr-defined]
    if hasattr(owner, "transcript_copy_button"):
        owner.transcript_copy_button.setVisible(bool(text.strip()))  # type: ignore[attr-defined]


def set_result_tab(owner: ResultStateOwner, kind: str) -> None:
    """切换详情结果区标签，并保留用户的当前选择。"""
    if kind not in {"transcript", "summary"}:
        kind = "transcript"
    owner.active_result_tab = kind
    if hasattr(owner, "result_stack"):
        owner.result_stack.setCurrentIndex(0 if kind == "transcript" else 1)  # type: ignore[attr-defined]
    if hasattr(owner, "transcript_tab_button"):
        owner.transcript_tab_button.setChecked(kind == "transcript")  # type: ignore[attr-defined]
    if hasattr(owner, "summary_tab_button"):
        owner.summary_tab_button.setChecked(kind == "summary")  # type: ignore[attr-defined]


def set_summary_text(owner: ResultStateOwner, summary: str) -> None:
    """以 Markdown 方式展示总结，同时保留原文用于复制和导出。"""
    owner.summary_markdown_text = summary
    if hasattr(owner, "summary_copy_button"):
        owner.summary_copy_button.setVisible(bool(summary.strip()))  # type: ignore[attr-defined]
    if not summary.strip():
        owner.summary_text.clear()  # type: ignore[attr-defined]
        return
    owner.summary_text.setMarkdown(summary)  # type: ignore[attr-defined]


def set_button_object_name(button: QPushButton, object_name: str) -> None:
    """切换按钮样式对象名，并立即刷新 Qt 样式。"""
    if button.objectName() == object_name:
        return
    button.setObjectName(object_name)
    button.style().unpolish(button)
    button.style().polish(button)
