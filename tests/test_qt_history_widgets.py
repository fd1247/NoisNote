from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.history.service import HistoryRecord, HistoryStatus
from src.ui.widgets.history_item import HistoryListItemWidget


class DummyHistoryActions:
    def __init__(self) -> None:
        self.selected_index: int | None = None

    def select_history_index(self, index: int) -> None:
        self.selected_index = index

    def rename_history_record(self, index: int) -> None:
        pass

    def open_history_record_folder(self, index: int) -> None:
        pass

    def delete_history_record(self, index: int) -> None:
        pass


def make_record(root: Path, record_id: str = "20260624_120000") -> HistoryRecord:
    return HistoryRecord(
        record_id=record_id,
        layout="folder",
        record_dir=root,
        audio_path=root / "audio.wav",
        transcript_path=root / "transcript.txt",
        summary_path=root / "summary.txt",
        markdown_path=root / "export.md",
        metadata_path=root / "metadata.json",
        created_at=datetime(2026, 6, 24, 12, 0, 0),
        duration_seconds=10,
        audio_size_bytes=1024,
        total_size_bytes=1024,
        status=HistoryStatus.AUDIO_ONLY,
    )


def test_history_more_button_stays_visible_for_selected_item(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    widget = HistoryListItemWidget(make_record(tmp_path), 0, DummyHistoryActions())
    app.processEvents()

    assert widget.more_button.isHidden()

    widget.set_selected(True)
    app.processEvents()

    assert not widget.more_button.isHidden()

    widget.set_selected(False)
    app.processEvents()

    assert widget.more_button.isHidden()


def test_history_more_button_keeps_space_for_long_record_name(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    record_id = "7d3ecf323e2daa48c1a713c63b550b10"
    widget = HistoryListItemWidget(make_record(tmp_path, record_id), 0, DummyHistoryActions())
    widget.resize(220, 64)
    widget.set_selected(True)
    widget.show()
    app.processEvents()

    button_right = widget.more_button.geometry().right()
    assert widget.more_button.isVisible()
    assert button_right <= widget.contentsRect().right()
