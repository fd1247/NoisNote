"""任务队列数据模型。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum


class TaskKind(str, Enum):
    """应用任务类型。"""

    PROCESS_RECORD = "process_record"
    RECORDING = "recording"
    REMOTE_IMPORT = "remote_import"


class TaskStatus(str, Enum):
    """任务生命周期状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class TaskStage(str, Enum):
    """处理任务当前阶段。"""

    WAITING = "waiting"
    PARSING_LINK = "parsing_link"
    EXTRACTING_SUBTITLE = "extracting_subtitle"
    DOWNLOADING_AUDIO = "downloading_audio"
    PREPROCESSING = "preprocessing"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass
class TaskOptions:
    """处理任务选项。"""

    auto_summarize: bool = False
    overwrite_existing: bool = False
    manual: bool = False
    summary_only: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object] | None) -> "TaskOptions":
        data = value or {}
        return cls(
            auto_summarize=bool(data.get("auto_summarize", False)),
            overwrite_existing=bool(data.get("overwrite_existing", False)),
            manual=bool(data.get("manual", False)),
            summary_only=bool(data.get("summary_only", False)),
        )


@dataclass
class AppTask:
    """任务队列中的一项。"""

    task_id: str
    kind: TaskKind
    status: TaskStatus
    stage: TaskStage
    record_key: str = ""
    notebook_id: str = "default"
    record_id: str = ""
    source: str = "manual"
    input_url: str = ""
    restart_stage: TaskStage | None = None
    title: str = ""
    message: str = ""
    progress_percent: int | None = None
    error_message: str = ""
    created_at: str = ""
    queued_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    options: TaskOptions = field(default_factory=TaskOptions)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["kind"] = self.kind.value
        data["status"] = self.status.value
        data["stage"] = self.stage.value
        data["restart_stage"] = self.restart_stage.value if self.restart_stage is not None else None
        data["options"] = self.options.to_dict()
        return data

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "AppTask":
        return cls(
            task_id=str(value.get("task_id") or ""),
            kind=TaskKind(str(value.get("kind") or TaskKind.PROCESS_RECORD.value)),
            status=TaskStatus(str(value.get("status") or TaskStatus.QUEUED.value)),
            stage=TaskStage(str(value.get("stage") or TaskStage.WAITING.value)),
            record_key=str(value.get("record_key") or ""),
            notebook_id=str(value.get("notebook_id") or "default"),
            record_id=str(value.get("record_id") or ""),
            source=str(value.get("source") or "manual"),
            input_url=str(value.get("input_url") or ""),
            restart_stage=(TaskStage(str(value["restart_stage"])) if value.get("restart_stage") else None),
            title=str(value.get("title") or ""),
            message=str(value.get("message") or ""),
            progress_percent=value.get("progress_percent") if value.get("progress_percent") is not None else None,
            error_message=str(value.get("error_message") or ""),
            created_at=str(value.get("created_at") or ""),
            queued_at=str(value.get("queued_at") or ""),
            started_at=str(value.get("started_at")) if value.get("started_at") is not None else None,
            finished_at=str(value.get("finished_at")) if value.get("finished_at") is not None else None,
            options=TaskOptions.from_dict(value.get("options") if isinstance(value.get("options"), dict) else None),
        )


@dataclass(frozen=True)
class TaskSnapshot:
    """供 UI 渲染的任务快照。"""

    running: tuple[AppTask, ...]
    queued: tuple[AppTask, ...]
    completed: tuple[AppTask, ...]
    paused_reason: str = ""
