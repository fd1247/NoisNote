"""主窗口结果导出逻辑。"""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from ..history.service import HistoryRecord


class ExportHandlers:
    """转录、时间轴、总结导出入口。"""

    def _export_result_with_format(self, format_type: str) -> None:
        """按指定格式导出当前记录结果。"""
        if not self.current_record:
            self._show_error("请先选择或生成一条录音")
            return

        format_map = {
            "txt": ("txt", "export_transcript_txt"),
            "srt": ("srt", "export_timeline_srt"),
            "markdown": ("md", "export_summary_markdown"),
        }
        if format_type not in format_map:
            self._show_error(f"不支持的导出格式：{format_type}")
            return

        suffix, service_method = format_map[format_type]
        method = getattr(self.history_service, service_method, None)
        if not method:
            self._show_error(f"导出方法不可用：{service_method}")
            return

        unavailable_message = self._export_unavailable_message(format_type, self.current_record)
        if unavailable_message:
            self._show_error(unavailable_message)
            return

        dir_path = QFileDialog.getExistingDirectory(
            self,
            "选择导出目录",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not dir_path:
            return

        try:
            source_path = method(self.current_record)
        except Exception as exc:
            self._show_error(str(exc))
            return

        export_dir = Path(dir_path)
        export_filename = f"{self.current_record.display_name}.{suffix}"
        export_path = export_dir / export_filename

        try:
            shutil.copy2(source_path, export_path)
            self._set_status(f"已导出：{export_filename}")
        except Exception as exc:
            self._show_error(f"导出失败：{exc}")

    def _export_unavailable_message(self, format_type: str, record: HistoryRecord) -> str:
        """返回指定格式不可导出时的提示文案。"""
        if format_type == "txt" and not self.history_service.read_transcript(record).strip():
            return "当前记录没有可导出的转录文字"
        if format_type == "srt" and not self.history_service.read_timeline(record):
            return "当前记录没有可导出的逐句时间轴"
        if format_type == "markdown" and not self.history_service.read_summary(record).strip():
            return "当前记录没有可导出的总结内容"
        return ""
