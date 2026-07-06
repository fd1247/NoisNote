"""详情 WebView 数据绑定与命令处理。"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from ..ui.detail_models import build_detail_payload, parse_detail_command, timeline_display_text
from ..utils.logging import log_event, record_context


class DetailViewHandlers:
    """负责详情 WebView 的真实 payload 刷新和前端命令分发。"""

    def _bump_detail_revision(self) -> None:
        """递增详情视图版本号，用于过滤旧 WebView 消息。"""
        self.detail_revision = int(getattr(self, "detail_revision", 0)) + 1

    def _refresh_detail_payload(self) -> None:
        """根据当前记录、结果页和播放状态刷新详情 WebView。"""
        detail_webview = getattr(self, "detail_webview", None)
        if detail_webview is None or not hasattr(detail_webview, "set_content"):
            return

        record = self.current_record
        mode = str(getattr(self, "active_result_tab", "transcript") or "transcript")
        content = ""
        timeline: list[dict[str, Any]] = []

        if record is None:
            record = SimpleNamespace(record_key="", display_name="")
        elif mode == "summary":
            content = self._detail_summary_content(record)
        elif mode == "timeline":
            timeline = self._detail_timeline_items(record)
            content = timeline_display_text(timeline)
        else:
            content = self._detail_transcript_content(record)

        payload = build_detail_payload(
            record,
            mode,
            int(getattr(self, "detail_revision", 0)),
            content,
            timeline,
            self._detail_playback_position_seconds(),
            self._detail_is_playing(),
        )
        detail_webview.set_content(payload)

    def _on_detail_web_command(self, value: dict) -> None:
        """处理详情 WebView 发回的命令。"""
        current_record_key = self.current_record.record_key if self.current_record else ""
        command = parse_detail_command(
            value,
            current_record_key=current_record_key,
            current_revision=int(getattr(self, "detail_revision", 0)),
        )
        if command is None:
            return

        if command.command == "seek":
            seconds = float(command.payload["seconds"])
            self.seek_playback(int(round(seconds * 1000)))
            return

        if command.command == "copy":
            text = str(command.payload.get("text") or "")
            if not text.strip():
                return
            QApplication.clipboard().setText(text)
            self._set_status("已复制详情内容")
            return

        if command.command == "openExternalUrl":
            QDesktopServices.openUrl(QUrl(str(command.payload["url"])))
            return

        if command.command == "renderError":
            log_event(
                "detail.webview.render_error",
                level="ERROR",
                module="ui",
                message="详情 WebView 渲染错误",
                record_id=(self.current_record.record_id if self.current_record else None),
                context={
                    "record": record_context(self.current_record),
                    "message": str(command.payload.get("message") or ""),
                },
            )
            return

        if command.command == "ready":
            self._refresh_detail_payload()

    def _detail_transcript_content(self, record) -> str:
        record_key = record.record_key
        if getattr(self, "transcript_loaded_record_id", "") != record_key:
            text = self.history_service.read_transcript(record)
            self.transcript_plain_text = text
            self.transcript_loaded_record_id = record_key
            self._sync_legacy_transcript_widgets(text)
        return str(getattr(self, "transcript_plain_text", ""))

    def _detail_summary_content(self, record) -> str:
        record_key = record.record_key
        if getattr(self, "summary_loaded_record_id", "") != record_key:
            summary = self.history_service.read_summary(record)
            self.summary_markdown_text = summary
            self.summary_loaded_record_id = record_key
            self._sync_legacy_summary_widgets(summary)
        return str(getattr(self, "summary_markdown_text", ""))

    def _detail_timeline_items(self, record) -> list[dict[str, Any]]:
        record_key = record.record_key
        if getattr(self, "timeline_loaded_record_id", "") != record_key:
            items = self.history_service.read_timeline(record) if record.has_timeline else []
            self.timeline_items = items
            self.timeline_loaded_record_id = record_key
            self._last_timeline_highlight_key = (None, None)
            if not items:
                self.timeline_text.clear()
                self.timeline_copy_button.hide()
            elif self.active_result_tab == "timeline":
                self._refresh_timeline_highlight(force=True)
                self.timeline_copy_button.show()
        return list(getattr(self, "timeline_items", []) or [])

    def _sync_legacy_transcript_widgets(self, text: str) -> None:
        """保持旧文本控件可用，直到后续任务删除兼容桥。"""
        if hasattr(self, "transcript_text"):
            self.transcript_text.setPlainText(text)
        if hasattr(self, "transcript_copy_button"):
            self.transcript_copy_button.setVisible(bool(text.strip()))

    def _sync_legacy_summary_widgets(self, summary: str) -> None:
        """保持旧总结控件可用，供复制、导出和测试兼容。"""
        if hasattr(self, "summary_copy_button"):
            self.summary_copy_button.setVisible(bool(summary.strip()))
        if not hasattr(self, "summary_text"):
            return
        if summary.strip():
            self.summary_text.setMarkdown(summary)
        else:
            self.summary_text.clear()

    def _detail_playback_position_seconds(self) -> float:
        player = getattr(self, "media_player", None)
        if player is None or not hasattr(player, "position"):
            return 0.0
        try:
            return max(0, int(player.position())) / 1000.0
        except (RuntimeError, TypeError, ValueError):
            return 0.0

    def _detail_is_playing(self) -> bool:
        player = getattr(self, "media_player", None)
        if player is None or not hasattr(player, "playbackState"):
            return False
        try:
            return player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        except RuntimeError:
            return False
