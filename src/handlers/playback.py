"""主窗口音频播放控制逻辑。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPlainTextEdit, QTextEdit

from ..history.service import HistoryRecord
from ..ui.icons import make_action_icon


class PlaybackHandlers:
    """历史记录音频播放、快捷键和进度条控制。"""

    def _init_media_player(self) -> None:
        self.audio_output = QAudioOutput(self)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.positionChanged.connect(self._on_playback_position_changed)
        self.media_player.durationChanged.connect(self._on_playback_duration_changed)
        self.media_player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._reset_playback_ui()

    def _playback_source_for_record(self, record: HistoryRecord) -> Path | None:
        candidates = [record.audio_path]
        if record.normalized_audio_path:
            candidates.append(record.normalized_audio_path)
        for path in candidates:
            if path and path.exists() and path.is_file():
                return path
        return None

    def _set_playback_source(self, record: HistoryRecord) -> None:
        source = self._playback_source_for_record(record)
        if self.playback_record_id == record.record_id:
            self._sync_playback_buttons(bool(source))
            return
        self.stop_playback()
        self.playback_record_id = record.record_id
        self.playback_duration_ms = int(max(0.0, record.duration_seconds or 0.0) * 1000)
        self.playback_slider.setRange(0, max(0, self.playback_duration_ms))
        self.playback_duration_label.setText(_format_playback_ms(self.playback_duration_ms))
        self._sync_playback_buttons(bool(source))
        if self.media_player and source:
            self.media_player.setSource(QUrl.fromLocalFile(str(source)))
            self.media_player.setPlaybackRate(self.playback_rate)

    def _sync_playback_buttons(self, enabled: bool) -> None:
        self.playback_back_button.setEnabled(enabled)
        self.playback_play_button.setEnabled(enabled)
        self.playback_forward_button.setEnabled(enabled)
        self.playback_slider.setEnabled(enabled)
        self.playback_rate_combo.setEnabled(enabled)

    def _reset_playback_ui(self) -> None:
        if hasattr(self, "playback_play_button"):
            self.playback_play_button.setIcon(make_action_icon("play"))
            self.playback_position_label.setText("00:00")
            self.playback_duration_label.setText("00:00")
            self.playback_slider.setRange(0, 0)
            self.playback_slider.setValue(0)
            self._sync_playback_buttons(False)

    def stop_playback(self) -> None:
        if self.media_player:
            self.media_player.stop()
            self.media_player.setSource(QUrl())
        if hasattr(self, "playback_slider"):
            self.playback_slider.setValue(0)
            self.playback_position_label.setText("00:00")
            self.playback_play_button.setIcon(make_action_icon("play"))
        self._refresh_timeline_highlight(force=True)

    def toggle_playback(self) -> None:
        if not self.media_player or not self.current_record:
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            return
        if not self._playback_source_for_record(self.current_record):
            self._set_status("当前记录没有可播放的音频")
            return
        self.media_player.play()

    def seek_playback_backward(self) -> None:
        self._seek_playback_relative(-15_000)

    def seek_playback_forward(self) -> None:
        self._seek_playback_relative(15_000)

    def _seek_playback_relative(self, delta_ms: int) -> None:
        if not self.media_player:
            return
        duration = max(self.playback_duration_ms, self.media_player.duration())
        target = max(0, min(duration, self.media_player.position() + delta_ms))
        self.seek_playback(target)

    def seek_playback(self, position_ms: int) -> None:
        if not self.media_player:
            return
        target = max(0, int(position_ms))
        self.media_player.setPosition(target)
        self._on_playback_position_changed(target)

    def set_playback_rate(self, text: str) -> None:
        value = (text or "1x").rstrip("x")
        try:
            rate = float(value)
        except ValueError:
            rate = 1.0
        self.playback_rate = rate if rate in {0.5, 1.0, 1.5, 2.0} else 1.0
        if self.media_player:
            self.media_player.setPlaybackRate(self.playback_rate)

    def _on_playback_position_changed(self, position_ms: int) -> None:
        if not hasattr(self, "playback_slider"):
            return
        self._updating_playback_slider = True
        try:
            self.playback_slider.setValue(max(0, int(position_ms)))
        finally:
            self._updating_playback_slider = False
        self.playback_position_label.setText(_format_playback_ms(position_ms))
        self._refresh_timeline_highlight(position_ms / 1000.0)

    def _on_playback_duration_changed(self, duration_ms: int) -> None:
        self.playback_duration_ms = max(0, int(duration_ms))
        self.playback_slider.setRange(0, self.playback_duration_ms)
        self.playback_duration_label.setText(_format_playback_ms(self.playback_duration_ms))

    def _on_playback_state_changed(self, state) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.playback_play_button.setIcon(make_action_icon("pause"))
        else:
            self.playback_play_button.setIcon(make_action_icon("play"))

    def _init_playback_shortcuts(self) -> None:
        """注册播放快捷键，避免焦点落在子控件时主窗口收不到按键。"""
        shortcuts = [
            (Qt.Key.Key_Space, "toggle"),
            (Qt.Key.Key_Left, "backward"),
            (Qt.Key.Key_Right, "forward"),
        ]
        self.playback_shortcuts: list[QShortcut] = []
        for key, action in shortcuts:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda checked=False, name=action: self._trigger_playback_shortcut(name))
            self.playback_shortcuts.append(shortcut)

    def _trigger_playback_shortcut(self, action: str) -> None:
        if QApplication.activeModalWidget() is not None or QApplication.activePopupWidget() is not None:
            return
        if self._should_ignore_playback_shortcut() or not self.current_record:
            return
        if not self._playback_source_for_record(self.current_record):
            return
        if action == "toggle":
            self.toggle_playback()
        elif action == "backward":
            self.seek_playback_backward()
        elif action == "forward":
            self.seek_playback_forward()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """播放快捷键：空格播放/暂停，左右方向键快退/快进。"""
        if self._should_ignore_playback_shortcut():
            super().keyPressEvent(event)
            return
        if not self.current_record:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key == Qt.Key.Key_Space:
            self.toggle_playback()
            event.accept()
            return
        if key == Qt.Key.Key_Left:
            self.seek_playback_backward()
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            self.seek_playback_forward()
            event.accept()
            return
        super().keyPressEvent(event)

    def _should_ignore_playback_shortcut(self) -> bool:
        """输入控件获得焦点时不拦截空格和方向键。"""
        focus_widget = QApplication.focusWidget()
        if isinstance(focus_widget, (QLineEdit, QComboBox)):
            return True
        if isinstance(focus_widget, (QPlainTextEdit, QTextEdit)):
            return not focus_widget.isReadOnly()
        return False


def _format_playback_ms(value: object) -> str:
    try:
        total_seconds = max(0, int(round(float(value) / 1000)))
    except (TypeError, ValueError):
        total_seconds = 0
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
