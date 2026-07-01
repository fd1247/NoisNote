"""Qwen3-ASR GGUF 数据模型和配置辅助逻辑。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class Qwen3AsrGgufError(RuntimeError):
    """Qwen3-ASR GGUF 推理错误，区分用户提示和诊断信息。"""

    def __init__(self, user_message: str, diagnostic_message: str = "", error_type: str = ""):
        super().__init__(user_message)
        self.user_message = user_message
        self.diagnostic_message = diagnostic_message or user_message
        self.error_type = error_type or self.__class__.__name__

    def to_metadata(self) -> dict[str, str]:
        return {
            "user_message": self.user_message,
            "diagnostic_message": self.diagnostic_message,
            "error_type": self.error_type,
        }


@dataclass(frozen=True)
class DeviceResolution:
    """用户设备选项解析后的运行语义。"""

    requested_device: str
    resolved_device: str
    onnx_provider: str
    llm_use_gpu: bool
    user_message: str
    diagnostic: dict[str, Any]


@dataclass(frozen=True)
class Qwen3AsrGgufRuntimeConfig:
    """GGUF 推理运行配置。"""

    model_dir: Path
    model_name: str
    model_size: str
    requested_device: str = "auto"
    tool_dir: Path | None = None
    chunk_size: float = 40.0
    memory_num: int = 1
    n_ctx: int = 2048
    context: str = ""
    hotwords: list[str] = field(default_factory=list)
    language: str | None = None
    request_timestamps: bool = False
    enable_timestamps: bool = False
    aligner_model_dir: Path | None = None
    aligner_model_name: str = ""
    timestamp_degrade_reason: str = ""


@dataclass(frozen=True)
class Qwen3AsrGgufResult:
    """转录结果和诊断信息。"""

    text: str
    diagnostics: dict[str, Any]
    timeline: list["TimelineSegment"] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineSegment:
    """转录时间轴片段。"""

    start: float
    end: float
    text: str
    tokens: list["TimelineToken"] = field(default_factory=list)


@dataclass(frozen=True)
class TimelineToken:
    """转录时间轴中的最小对齐单元。"""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Qwen3AsrGgufProgress:
    """Qwen3-ASR GGUF vendor 分片进度。"""

    stage: str
    current_chunk: int
    total_chunks: int
    processed_seconds: float
    total_seconds: float
    message: str


def resolve_device_mode(device: str | None) -> DeviceResolution:
    """把界面中的 auto/cpu/gpu 解析为 GGUF runtime 可执行配置。"""
    value = (device or "auto").strip().lower()
    if value == "cuda":
        value = "gpu"
    if value not in {"auto", "cpu", "gpu"}:
        value = "auto"

    if value == "gpu":
        return DeviceResolution(
            requested_device="gpu",
            resolved_device="gpu",
            onnx_provider="DML",
            llm_use_gpu=True,
            user_message="启用 GPU/DirectML 加速",
            diagnostic={
                "encoder_provider": "DmlExecutionProvider",
                "decoder_backend": "llama.cpp GGUF backend",
            },
        )

    resolved = "cpu"
    return DeviceResolution(
        requested_device=value,
        resolved_device=resolved,
        onnx_provider="CPU",
        llm_use_gpu=False,
        user_message="使用 CPU 稳定模式" if value == "auto" else "使用 CPU",
        diagnostic={
            "encoder_provider": "CPUExecutionProvider",
            "decoder_backend": "llama.cpp GGUF backend",
        },
    )


def build_context(user_context: str, hotwords: list[str]) -> str:
    """把上下文和热词合并为 GGUF engine 的 context。"""
    parts: list[str] = []
    if user_context.strip():
        parts.append(user_context.strip())
    clean_hotwords = [item.strip() for item in hotwords if item and item.strip()]
    if clean_hotwords:
        parts.append("请优先准确识别以下热词：" + "、".join(clean_hotwords))
    return "\n".join(parts)


@dataclass(frozen=True)
class TranscriptionProgress:
    """转录进度。"""

    stage: str
    percent: int
    processed_seconds: float | None
    total_seconds: float | None
    message: str


class ProgressReporter:
    """保证转录百分比单调递增，将 vendor 进度翻译为 TranscriptionProgress。"""

    def __init__(self, callback=None, total_seconds: float | None = None):
        self.callback = callback
        self.total_seconds = total_seconds
        self._last_percent = 0

    def emit(
        self,
        stage: str,
        percent: int,
        message: str,
        processed_seconds: float | None = None,
    ) -> None:
        value = max(self._last_percent, min(100, int(percent)))
        self._last_percent = value
        if self.callback:
            self.callback(
                TranscriptionProgress(
                    stage=stage,
                    percent=value,
                    processed_seconds=processed_seconds,
                    total_seconds=self.total_seconds,
                    message=message,
                )
            )

    def emit_vendor_progress(self, progress) -> None:
        total_seconds = progress.total_seconds or self.total_seconds
        if progress.total_chunks <= 0 or not total_seconds:
            self.emit(
                progress.stage or "transcribing",
                max(self._last_percent, 15),
                progress.message or "正在转录音频",
                progress.processed_seconds,
            )
            return
        ratio = max(0.0, min(1.0, progress.processed_seconds / total_seconds))
        percent = 15 + int(ratio * 80)
        self.emit(
            progress.stage or "transcribing",
            percent,
            progress.message or f"正在转录音频 {percent}%",
            progress.processed_seconds,
        )

    def emit_text(self, text: object) -> None:
        if hasattr(text, "total_chunks"):
            self.emit_vendor_progress(text)
            return
        value = str(text or "").strip()
        if not value:
            return
        if "加载" in value and "模型" in value:
            self.emit("loading_asr_model", max(self._last_percent, 5), "正在加载ASR模型")
        elif "完成" in value:
            self.emit("completed", 100, value)
        elif "转录" in value:
            self.emit("transcribing", max(self._last_percent, 15), value)
        elif self.callback:
            self.callback(value)
