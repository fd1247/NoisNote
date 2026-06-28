"""音频录制模块。

提供 Windows WASAPI Loopback 系统音频录制功能，支持设备热切换。
"""
from .device_manager import (
    DeviceManager,
    list_capture_devices,
    validate_capture_settings,
)
from .recorder import AudioRecorder
from .types import (
    CaptureDeviceInfo,
    CaptureDeviceUnavailable,
    CaptureMode,
    CaptureSettings,
)

__all__ = [
    "AudioRecorder",
    "CaptureDeviceInfo",
    "CaptureDeviceUnavailable",
    "CaptureMode",
    "CaptureSettings",
    "DeviceManager",
    "list_capture_devices",
    "validate_capture_settings",
]
