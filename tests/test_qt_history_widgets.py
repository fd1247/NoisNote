from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QEnterEvent
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
        summary_path=root / "summary.md",
        markdown_path=root / "export.md",
        metadata_path=root / "metadata.json",
        created_at=datetime(2026, 6, 24, 12, 0, 0),
        duration_seconds=10,
        audio_size_bytes=1024,
        total_size_bytes=1024,
        status=HistoryStatus.AUDIO_ONLY,
    )


def test_history_more_button_follows_hover_not_selection(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    widget = HistoryListItemWidget(make_record(tmp_path), 0, DummyHistoryActions())
    app.processEvents()

    assert widget.sizeHint().height() == HistoryListItemWidget.ROW_HEIGHT
    assert widget.more_button.isHidden()

    widget.set_selected(True)
    app.processEvents()

    assert widget.more_button.isHidden()
    assert not widget.more_button.icon().isNull()
    assert widget.title_label.property("selected") is True
    assert widget.subtitle_label.property("selected") is True

    widget.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    app.processEvents()

    assert not widget.more_button.isHidden()

    widget.leaveEvent(QEvent(QEvent.Type.Leave))
    app.processEvents()

    assert widget.more_button.isHidden()

    widget.set_selected(False)
    assert widget.title_label.property("selected") is False
    assert widget.subtitle_label.property("selected") is False


def test_history_more_button_shows_for_unselected_hovered_item(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    widget = HistoryListItemWidget(make_record(tmp_path), 0, DummyHistoryActions())
    widget.show()
    app.processEvents()

    widget.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    app.processEvents()

    assert not widget.more_button.isHidden()


def test_history_more_button_menu_does_not_select_record(monkeypatch, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    actions = DummyHistoryActions()
    widget = HistoryListItemWidget(make_record(tmp_path), 3, actions)

    class FakeMenu:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def addAction(self, *_args, **_kwargs) -> None:
            pass

        def addSeparator(self) -> None:
            pass

        def exec(self, *_args, **_kwargs) -> None:
            pass

    monkeypatch.setattr("src.ui.widgets.history_item.QMenu", FakeMenu)

    widget._show_menu()
    app.processEvents()

    assert actions.selected_index is None


def test_history_more_button_keeps_space_for_long_record_name(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    record_id = "7d3ecf323e2daa48c1a713c63b550b10"
    widget = HistoryListItemWidget(make_record(tmp_path, record_id), 0, DummyHistoryActions())
    widget.resize(220, 64)
    widget.show()
    widget.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    app.processEvents()

    button_right = widget.more_button.geometry().right()
    assert widget.more_button.isVisible()
    assert button_right <= widget.contentsRect().right()
    assert widget.sizeHint().height() >= widget.more_button.height() + 16


def test_history_item_subtitle_is_hidden_until_status_is_set(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    widget = HistoryListItemWidget(make_record(tmp_path, "meeting-01"), 0, DummyHistoryActions())
    widget.show()
    app.processEvents()

    assert widget.title_label.toolTip() == "meeting-01"
    assert widget.subtitle_label.isHidden()

    widget.set_subtitle("正在转录: 0%")
    app.processEvents()

    assert not widget.subtitle_label.isHidden()
    assert widget.subtitle_label.toolTip() == "正在转录: 0%"
