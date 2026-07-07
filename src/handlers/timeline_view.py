"""主窗口逐句时间轴视图逻辑。"""
from __future__ import annotations

from ..history.service import HistoryRecord
from ..ui.detail.models import timeline_display_text


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
        self.timeline_text.clear()
        self.timeline_copy_button.hide()
        if self.active_result_tab == "timeline":
            self._sync_timeline_detail_webview([])

    def _timeline_display_text(self, record: HistoryRecord) -> str:
        """把结构化时间轴格式化为详情页可读文本。"""
        items = self.timeline_items or self.history_service.read_timeline(record)
        return timeline_display_text(items)

    def _set_timeline_items(self, items: list[dict]) -> None:
        self.timeline_items = items
        display_text = timeline_display_text(items)
        self.timeline_text.setPlainText(display_text)
        self.timeline_copy_button.setVisible(bool(display_text.strip()) and self.active_result_tab == "timeline")
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
                "content": timeline_display_text(items),
                "timeline": items or [],
            }
        )
        detail_webview.set_content(payload)

    def _refresh_timeline_highlight(self, position_seconds: float | None = None, force: bool = False) -> None:
        update_detail_playback = getattr(self, "_update_detail_playback", None)
        if callable(update_detail_playback):
            update_detail_playback(position_seconds)
