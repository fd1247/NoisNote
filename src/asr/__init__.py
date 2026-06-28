"""ASR 转录引擎。"""
from .engine import TranscriptionEngine
from .runtime import Qwen3AsrGgufRuntime
from .types import (
    DeviceResolution,
    ProgressReporter,
    Qwen3AsrGgufError,
    Qwen3AsrGgufProgress,
    Qwen3AsrGgufResult,
    Qwen3AsrGgufRuntimeConfig,
    TranscriptionProgress,
    resolve_device_mode,
)

__all__ = [
    "DeviceResolution",
    "ProgressReporter",
    "Qwen3AsrGgufError",
    "Qwen3AsrGgufProgress",
    "Qwen3AsrGgufResult",
    "Qwen3AsrGgufRuntime",
    "Qwen3AsrGgufRuntimeConfig",
    "TranscriptionEngine",
    "TranscriptionProgress",
    "resolve_device_mode",
]
