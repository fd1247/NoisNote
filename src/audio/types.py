"""录音模块数据类型。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class CaptureMode(str, Enum):
    """录音采集模式。"""

    SYSTEM = "system"
    MICROPHONE = "microphone"


@dataclass(frozen=True)
class CaptureDeviceInfo:
    """录音设备信息。"""

    id: str
    name: str
    kind: str
    is_default: bool = False
    is_available: bool = True
    index: int | None = None


@dataclass(frozen=True)
class CaptureSettings:
    """一次录音采集的参数。"""

    mode: CaptureMode = CaptureMode.SYSTEM
    system_device_id: str | None = None
    microphone_device_id: str | None = None
    sample_rate: int = 16000
    channels: int = 1
    sample_format: str = "pcm_s16le"
    chunk_size: int = 1024
    silence_threshold: int = 2
    silence_hint_seconds: int = 5


class CaptureDeviceUnavailable(RuntimeError):
    """录音设备不可用。"""

    def __init__(self, message: str, kind: str = "device_unavailable"):
        super().__init__(message)
        self.kind = kind


VolumeCallback = Callable[[int], None]
