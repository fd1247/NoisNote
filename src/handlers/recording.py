"""主窗口录音相关处理逻辑。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtMultimedia import QMediaDevices

from ..audio import AudioRecorder, CaptureMode, CaptureSettings, list_capture_devices
from ..app.config import get_output_dir
from ..utils.logging import file_context, hash_text, log_event, record_context
from ..ui.pages.result import set_button_object_name
from ..ui.dialogs.recording import RecordingDialog


class RecordingHandlers:
    """录音设备、录音流程和录音页状态处理。"""

    def _init_recorder(self) -> None:
        try:
            output_dir = get_output_dir(self.config)
            self.recorder = AudioRecorder(str(output_dir))
            self._sync_capture_controls_from_config()
            self._populate_device_combos()
            self._update_device_combo_visibility()
            self.recorder.configure(self._capture_settings_from_config())
            self.record_device_label.setText(f"录音设备：{self.recorder.get_device_name()}")
            self.recording_hint_label.setText(f"准备捕获{self.recorder.capture_source_label()}")
            log_event(
                "audio.device.detected",
                module="audio",
                message="录音设备初始化完成",
                context=self._capture_log_context(),
            )
            # 监听系统音频输出设备变更（蓝牙连接/断开等），
            # 通过 threading.Event 通知录音线程即时恢复
            try:
                self._media_devices = QMediaDevices()
                self._media_devices.audioOutputsChanged.connect(
                    self._on_audio_outputs_changed
                )
            except Exception:
                self._media_devices = None
        except Exception as exc:
            self.recorder = None
            self.record_button.setEnabled(False)
            self.record_device_label.setText(f"录音设备初始化失败：{exc}")
            log_event(
                "audio.record.failed",
                level="ERROR",
                module="audio",
                message="录音设备初始化失败",
                context={"error": str(exc)},
                error_code="AUD-001",
                error_type=type(exc).__name__,
            )

    def _on_audio_outputs_changed(self) -> None:
        """Qt 音频输出设备变更回调，通知录音线程。"""
        if self.recorder and self.recorder.is_recording:
            self.recorder.device_changed_event.set()

    def _sync_capture_controls_from_config(self) -> None:
        """启动时默认选中系统声音。"""
        mode = CaptureMode.SYSTEM.value
        self.config.setdefault("audio", {}).setdefault("capture", {})["mode"] = mode
        index = self.capture_mode_combo.findData(mode)
        self.capture_mode_combo.blockSignals(True)
        self.capture_mode_combo.setCurrentIndex(index)
        self.capture_mode_combo.blockSignals(False)

    def _populate_device_combos(self) -> None:
        """填充系统声和麦克风设备下拉框，每次启动默认选中"默认"。"""
        try:
            devices = list_capture_devices()
        except Exception:
            devices = []

        # 填充系统声设备下拉框
        self.system_device_combo.blockSignals(True)
        self.system_device_combo.clear()
        self.system_device_combo.addItem("默认", None)
        system_devices = [d for d in devices if d.kind == "system_loopback"]
        for d in system_devices:
            self.system_device_combo.addItem(d.name, d.id)
        self.system_device_combo.blockSignals(False)

        # 填充麦克风设备下拉框
        self.microphone_device_combo.blockSignals(True)
        self.microphone_device_combo.clear()
        self.microphone_device_combo.addItem("默认", None)
        mic_devices = [d for d in devices if d.kind == "microphone"]
        for d in mic_devices:
            self.microphone_device_combo.addItem(d.name, d.id)
        self.microphone_device_combo.blockSignals(False)

    def _update_device_combo_visibility(self) -> None:
        """根据当前录音源模式显示/隐藏对应的设备下拉框整行。"""
        mode = self.capture_mode_combo.currentData() or CaptureMode.SYSTEM.value
        is_system = mode == CaptureMode.SYSTEM.value
        if hasattr(self, "system_device_widget"):
            self.system_device_widget.setVisible(is_system)
        if hasattr(self, "microphone_device_widget"):
            self.microphone_device_widget.setVisible(not is_system)

    def _on_device_selection_changed(self) -> None:
        """设备选择变化后同步配置和 recorder。"""
        if not self.recorder:
            return
        capture = self.config.setdefault("audio", {}).setdefault("capture", {})

        # 读取当前系统声设备选择
        system_device_id = self.system_device_combo.currentData()
        capture["system_device_id"] = system_device_id or ""

        # 读取当前麦克风设备选择
        mic_device_id = self.microphone_device_combo.currentData()
        capture["microphone_device_id"] = mic_device_id or ""

        try:
            self.recorder.configure(self._capture_settings_from_config())
            self.record_device_label.setText(f"录音设备：{self.recorder.get_device_name()}")
            log_event(
                "audio.capture.device_changed",
                module="audio",
                message="录音设备已切换",
                context=self._capture_log_context(),
            )
        except Exception as exc:
            self.record_device_label.setText(f"录音设备配置失败：{exc}")

    def _on_capture_mode_changed(self) -> None:
        """录音源选择变化后同步配置、recorder 和设备下拉框可见性。"""
        mode = self.capture_mode_combo.currentData() or CaptureMode.SYSTEM.value
        self.config.setdefault("audio", {}).setdefault("capture", {})["mode"] = mode
        self._update_device_combo_visibility()
        if self.recorder:
            try:
                self.recorder.configure(self._capture_settings_from_config())
                self.record_device_label.setText(f"录音设备：{self.recorder.get_device_name()}")
                self.recording_hint_label.setText(f"准备捕获{self.recorder.capture_source_label()}")
                log_event(
                    "audio.capture.mode_changed",
                    module="audio",
                    message="录音源已切换",
                    context=self._capture_log_context(),
                )
            except Exception as exc:
                self.record_device_label.setText(f"录音设备配置失败：{exc}")
                log_event(
                    "audio.record.failed",
                    level="ERROR",
                    module="audio",
                    message="录音设备配置失败",
                    context={"capture_mode": mode, "error": str(exc)},
                    error_code="AUD-001",
                    error_type=type(exc).__name__,
                )

    def _capture_settings_from_config(self) -> CaptureSettings:
        """读取录音采集配置，优先从下拉框获取设备选择。"""
        capture = self.config.get("audio", {}).get("capture", {})
        mode_value = self.capture_mode_combo.currentData() or capture.get("mode") or CaptureMode.SYSTEM.value
        try:
            mode = CaptureMode(mode_value)
        except ValueError:
            mode = CaptureMode.SYSTEM

        # 优先从下拉框读取设备 ID，回退到 config 中的值
        system_device_id = self.system_device_combo.currentData() if hasattr(self, "system_device_combo") else None
        if not system_device_id:
            system_device_id = capture.get("system_device_id") or None
        mic_device_id = self.microphone_device_combo.currentData() if hasattr(self, "microphone_device_combo") else None
        if not mic_device_id:
            mic_device_id = capture.get("microphone_device_id") or None

        return CaptureSettings(
            mode=mode,
            system_device_id=system_device_id,
            microphone_device_id=mic_device_id,
            sample_rate=int(capture.get("sample_rate") or 16000),
            channels=int(capture.get("channels") or 1),
            sample_format=str(capture.get("sample_format") or "pcm_s16le"),
            chunk_size=int(capture.get("chunk_size") or 1024),
            silence_threshold=int(capture.get("silence_threshold") or 2),
            silence_hint_seconds=int(capture.get("silence_hint_seconds") or 5),
        )

    def _capture_log_context(self) -> dict:
        """生成录音配置和设备摘要，不记录真实设备名称。"""
        settings = self._capture_settings_from_config()
        device_name = self.recorder.get_device_name() if self.recorder else ""
        return {
            "mode": settings.mode.value,
            "sample_rate": settings.sample_rate,
            "channels": settings.channels,
            "sample_format": settings.sample_format,
            "chunk_size": settings.chunk_size,
            "device_name_hash": hash_text(device_name) if device_name else "",
        }

    def toggle_recording(self) -> None:
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()

    def show_recording_dialog(self) -> None:
        """显示录音源和录音状态弹窗。"""
        if self.recording_dialog is None:
            self.recording_dialog = RecordingDialog(self.recording_page, self.record_button, self)
        self.recording_dialog.sync_recording_state(self.is_recording)
        self.recording_dialog.show()
        self.recording_dialog.raise_()
        self.recording_dialog.activateWindow()

    def start_recording(self) -> None:
        if not self.recorder:
            self._show_error("录音设备不可用")
            log_event(
                "audio.record.failed",
                level="ERROR",
                module="audio",
                message="录音设备不可用",
                context=self._capture_log_context(),
                error_code="AUD-001",
            )
            return
        task_id = self._new_task_id("record")
        try:
            self.recorder.configure(self._capture_settings_from_config())
            self.recorder.start_recording()
            self.active_task_ids["recording"] = task_id
            self.is_recording = True
            self.record_button.setText("停止录音")
            self.record_button.setObjectName("DangerButton")
            self.record_button.style().unpolish(self.record_button)
            self.record_button.style().polish(self.record_button)
            self.silence_started_at = None
            self.recording_hint_label.setText(f"正在捕获{self.recorder.capture_source_label()}")
            self._sync_sidebar_actions()
            self._sync_recording_dialog_state()
            self._set_status("录音中")
            self.record_timer.start()
            log_event(
                "audio.record.started",
                module="audio",
                message="开始录音",
                task_id=task_id,
                context=self._capture_log_context(),
            )
        except Exception as exc:
            self._sync_sidebar_actions()
            self._sync_recording_dialog_state()
            log_event(
                "audio.record.failed",
                level="ERROR",
                module="audio",
                message="录音启动失败",
                task_id=task_id,
                context={**self._capture_log_context(), "error": str(exc)},
                error_code="AUD-002",
                error_type=type(exc).__name__,
            )
            self._show_error(f"录音失败：{exc}")

    def stop_recording(self) -> None:
        if not self.recorder:
            return
        task_id = self.active_task_ids.get("recording", "")
        self.record_timer.stop()
        self.is_recording = False
        self.record_button.setText("处理中")
        self.record_button.setObjectName("RecordButton")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        self.level_bar.setValue(0)
        self.recording_hint_label.setText("正在保存录音")
        self._sync_recording_dialog_state()

        try:
            output_file = self.recorder.stop_recording()
        except Exception as exc:
            self.record_button.setText("开始录音")
            self.recording_hint_label.setText("准备捕获系统声音")
            self._set_processing_ui(False)
            self._sync_sidebar_actions()
            self._sync_recording_dialog_state()
            self.active_task_ids.pop("recording", None)
            log_event(
                "audio.record.failed",
                level="ERROR",
                module="audio",
                message="停止录音失败",
                task_id=task_id,
                context={**self._capture_log_context(), "error": str(exc)},
                error_code="AUD-002",
                error_type=type(exc).__name__,
            )
            self._show_error(f"停止录音失败：{exc}")
            return

        if not output_file:
            self.record_button.setText("开始录音")
            self.duration_label.setText("00:00:00")
            self.recording_hint_label.setText("准备捕获系统声音")
            self._set_processing_ui(False)
            self._sync_sidebar_actions()
            self._sync_recording_dialog_state()
            self._set_status("未录到音频")
            self.active_task_ids.pop("recording", None)
            log_event(
                "audio.silence.detected",
                level="WARNING",
                module="audio",
                message="停止录音后没有生成音频",
                task_id=task_id,
                context=self._capture_log_context(),
                error_code="AUD-003",
            )
            return

        self.current_record = self.history_service.adopt_audio_file(Path(output_file))
        self.active_task_ids.pop("recording", None)
        log_event(
            "audio.record.stopped",
            module="audio",
            message="录音已保存",
            task_id=task_id,
            record_id=self.current_record.record_id,
            context={
                **self._capture_log_context(),
                "audio_file": file_context(self.current_record.audio_path),
                "record": record_context(self.current_record),
            },
        )
        self._handle_audio_record_ready(self.current_record, "已保存录音", source="recording")

    def _refresh_recording_state(self) -> None:
        if not self.recorder:
            return
        if self.is_recording and self.recorder.get_recording_error() is not None:
            self.stop_recording()
            return
        duration = self.recorder.get_duration()
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)
        seconds = int(duration % 60)
        self.duration_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        level = int(self.recorder.get_rms_level())
        self.level_bar.setValue(level)
        self.level_text_label.setText(self._recording_level_text(level, int(duration * 4)))
        self._sync_recording_dialog_state()

    def show_recording_page(self) -> None:
        """兼容旧入口：停止播放并打开录音弹窗。"""
        if hasattr(self, "stop_playback"):
            self.stop_playback()
        if hasattr(self, "playback_record_id"):
            self.playback_record_id = ""
        self.content_stack.setCurrentWidget(self.history_page)
        self.page_title_label.setText("")
        self._set_app_window_title()
        if hasattr(self, "history_tree"):
            self.history_tree.clearSelection()
        self._sync_history_selection(-1)
        self.show_recording_dialog()

    def _update_recording_entry(self) -> None:
        self._sync_sidebar_actions()
        self._sync_recording_dialog_state()

    def _sync_sidebar_actions(self) -> None:
        """统一更新主操作入口状态。"""
        self._sync_record_toolbar_state()

    def _sync_record_toolbar_state(self) -> None:
        if not hasattr(self, "record_toolbar_button"):
            return
        object_name = "ToolbarRecordingButton" if self.is_recording else "ToolbarIconButton"
        self.record_toolbar_button.setObjectName(object_name)
        self.record_toolbar_button.setToolTip("正在录音" if self.is_recording else "录音")
        self.record_toolbar_button.style().unpolish(self.record_toolbar_button)
        self.record_toolbar_button.style().polish(self.record_toolbar_button)

    def _sync_recording_dialog_state(self) -> None:
        self._sync_record_toolbar_state()
        if self.recording_dialog is not None:
            self.recording_dialog.sync_recording_state(self.is_recording)

    def _set_button_object_name(self, button, object_name: str) -> None:
        """切换按钮样式对象名，并立即刷新 Qt 样式。"""
        set_button_object_name(button, object_name)

    def _recording_level_text(self, level: int, tick: int) -> str:
        """生成录音时的竖条动态提示。"""
        if not self.is_recording:
            return ""
        active_count = max(1, min(9, int(level / 12) + 1))
        offset = tick % 9
        bars = []
        for index in range(9):
            is_active = ((index + offset) % 9) < active_count
            bars.append("|" if is_active else " ")
        return "".join(bars)

    def new_recording(self) -> None:
        if self.is_recording:
            self.show_recording_dialog()
            return
        if self.is_processing:
            self._set_status("正在处理中，请稍后重试")
            return
        if hasattr(self, "stop_playback"):
            self.stop_playback()
        if hasattr(self, "playback_record_id"):
            self.playback_record_id = ""

        self.current_record = None
        self.processing_source = None
        self._set_transcript_text("")
        if hasattr(self, "_set_timeline_items"):
            self._set_timeline_items([])
        self._set_summary_text("")
        self.transcript_status.setText("等待内容")
        if hasattr(self, "timeline_status"):
            self.timeline_status.setText("等待内容")
        self.summary_status.setText("等待内容")
        self.detail_processing_status_label.hide()
        self.record_button.setText("开始录音")
        self.record_button.setObjectName("RecordButton")
        self.record_button.style().unpolish(self.record_button)
        self.record_button.style().polish(self.record_button)
        self.record_button.setEnabled(bool(self.recorder))
        self.duration_label.setText("00:00:00")
        self.level_bar.setValue(0)
        self.level_text_label.setText("")
        self.recording_hint_label.setText("准备捕获系统声音")
        self._update_recording_entry()
        self.content_stack.setCurrentWidget(self.history_page)
        self.page_title_label.setText("")
        self._set_app_window_title()
        if hasattr(self, "history_tree"):
            self.history_tree.clearSelection()
        self._sync_history_selection(-1)
        self._set_status("")
