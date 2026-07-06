"""主窗口逐句时间轴视图逻辑。"""
from __future__ import annotations

from ..asr.timestamps import format_display_time, timeline_from_dicts, timeline_to_html
from ..history.service import HistoryRecord


class TimelineViewHandlers:
    """逐句时间轴展示、高亮和复制文本格式化。"""

    def _switch_to_timeline_tab(self) -> None:
        """切换到逐句时间轴标签页。"""
        if self.current_record and self.current_record.has_timeline:
            self._set_result_tab("timeline")

    def _set_timeline_text(self, text: str) -> None:
        """写入逐句时间轴，并同步复制按钮。"""
        self.timeline_text.setHtml(text)
        self.timeline_copy_button.setVisible(bool(text.strip()))

    def _release_timeline_resources(self) -> None:
        """释放长时间轴数据和 QTextDocument，避免后台高亮刷新拖慢切换。"""
        self.timeline_items = []
        self.timeline_loaded_record_id = ""
        self._last_timeline_highlight_key = (None, None)
        self.timeline_text.clear()
        self.timeline_copy_button.hide()

    def _timeline_display_text(self, record: HistoryRecord) -> str:
        """把结构化时间轴格式化为详情页可读文本。"""
        items = self.timeline_items or self.history_service.read_timeline(record)
        lines: list[str] = []
        for item in items:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            start = _format_timeline_seconds(item.get("start", 0.0))
            end = _format_timeline_seconds(item.get("end", 0.0))
            lines.append(f"{start} - {end}  {text}")
        return "\n".join(lines)

    def _set_timeline_items(self, items: list[dict]) -> None:
        self.timeline_items = items
        self._last_timeline_highlight_key = (None, None)
        if self.active_result_tab == "timeline":
            self._sync_timeline_detail_webview(items)
        if not items:
            self._release_timeline_resources()
            return
        if self.active_result_tab != "timeline":
            self.timeline_copy_button.hide()
            return
        self._refresh_timeline_highlight(force=True)
        self.timeline_copy_button.show()

    def _sync_timeline_detail_webview(self, items: list[dict]) -> None:
        detail_webview = getattr(self, "detail_webview", None)
        if detail_webview is None or not hasattr(detail_webview, "set_content"):
            return
        payload = dict(getattr(detail_webview, "current_payload", None) or {})
        title_label = getattr(self, "detail_title_label", None)
        title = title_label.text() if title_label is not None and hasattr(title_label, "text") else "详情"
        payload.update(
            {
                "mode": "timeline",
                "title": title,
                "content": _timeline_items_display_text(items),
                "timeline": items or [],
            }
        )
        detail_webview.set_content(payload)

    def _refresh_timeline_highlight(self, position_seconds: float | None = None, force: bool = False) -> None:
        if self.active_result_tab != "timeline" or not self.timeline_items:
            return
        key = self._timeline_highlight_key(position_seconds)
        if not force and key == self._last_timeline_highlight_key:
            return
        previous_key = self._last_timeline_highlight_key
        previous_scroll = self.timeline_text.verticalScrollBar().value()
        self._last_timeline_highlight_key = key
        timeline = timeline_from_dicts(self.timeline_items)
        self.timeline_text.setHtml(timeline_to_html(timeline, position_seconds))
        sentence_changed = force or key[0] != previous_key[0]
        if key[0] is not None and sentence_changed:
            self.timeline_text.scrollToAnchor("timeline-current")
        elif key[0] is not None:
            scroll_bar = self.timeline_text.verticalScrollBar()
            scroll_bar.setValue(min(previous_scroll, scroll_bar.maximum()))

    def _timeline_highlight_key(self, position_seconds: float | None) -> tuple[int | None, int | None]:
        if position_seconds is None:
            return (None, None)
        position = max(0.0, float(position_seconds))
        for sentence_index, item in enumerate(self.timeline_items):
            start = _safe_float(item.get("start", 0.0))
            end = max(start, _safe_float(item.get("end", start)))
            if not (start <= position <= end):
                continue
            tokens = item.get("tokens")
            if isinstance(tokens, list):
                for token_index, token in enumerate(tokens):
                    if not isinstance(token, dict):
                        continue
                    token_start = _safe_float(token.get("start", start))
                    token_end = max(token_start, _safe_float(token.get("end", token_start)))
                    if token_start <= position <= token_end:
                        return (sentence_index, token_index)
            return (sentence_index, None)
        return (None, None)


def _format_timeline_seconds(value: object) -> str:
    try:
        seconds = max(0.0, float(value))
    except (TypeError, ValueError):
        seconds = 0.0
    return format_display_time(seconds)


def _timeline_items_display_text(items: list[dict]) -> str:
    lines: list[str] = []
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = _format_timeline_seconds(item.get("start", 0.0))
        end = _format_timeline_seconds(item.get("end", 0.0))
        lines.append(f"{start} - {end}  {text}")
    return "\n".join(lines)


def _safe_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
