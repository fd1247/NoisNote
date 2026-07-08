"""任务队列持久化。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from .types import AppTask, TaskKind, TaskStatus


class RecordLookup(Protocol):
    def get_record_by_key(self, record_key: str): ...


class TaskQueueStore:
    """只持久化可恢复的排队处理任务。"""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self, history_service: RecordLookup) -> list[AppTask]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_tasks = payload.get("tasks") if isinstance(payload, dict) else []
        if not isinstance(raw_tasks, list):
            return []
        restored: list[AppTask] = []
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            try:
                task = AppTask.from_dict(item)
            except ValueError:
                continue
            if not self._is_restoreable(task, history_service):
                continue
            restored.append(task)
        return restored

    def save(self, tasks: list[AppTask]) -> None:
        queued = [
            task.to_dict()
            for task in tasks
            if task.kind is TaskKind.PROCESS_RECORD and task.status is TaskStatus.QUEUED
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": 1, "tasks": queued}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _is_restoreable(self, task: AppTask, history_service: RecordLookup) -> bool:
        if task.kind is not TaskKind.PROCESS_RECORD or task.status is not TaskStatus.QUEUED:
            return False
        if not task.record_key:
            return False
        record = history_service.get_record_by_key(task.record_key)
        if record is None:
            return False
        if task.options.summary_only:
            return record.has_transcript
        if not record.audio_path.exists():
            return False
        if record.has_transcript and not task.options.overwrite_existing:
            return False
        return True
