from __future__ import annotations

import numpy as np
import pytest

from src.audio import (
    AudioRecorder,
    CaptureDeviceInfo,
    CaptureDeviceUnavailable,
    CaptureMode,
    CaptureSettings,
    list_capture_devices,
    validate_capture_settings,
)
from src.audio import device_manager as dm_module
from src.audio import recorder as rec_module


# ---- Fake soundcard 对象 ----

class FakeSpeaker:
    """模拟 soundcard.Speaker."""

    def __init__(self, id_: str, name: str, channels: int = 2):
        self.id = id_
        self.name = name
        self.channels = channels


class FakeRecorder:
    """模拟 soundcard 的 recorder 上下文管理器。

    record() 返回 float32 静音数组。
    """

    def __init__(self, mic: FakeMicrophone):
        self._mic = mic

    def __enter__(self):
        if self._mic._fail_open:
            raise RuntimeError("device unavailable")
        return self

    def __exit__(self, *args):
        pass

    def record(self, numframes: int) -> np.ndarray:
        if self._mic._fail_read:
            raise RuntimeError("device read failed")
        return np.zeros((numframes, self._mic.channels), dtype=np.float32)


class FakeMicrophone:
    """模拟 soundcard.Microphone."""

    def __init__(
        self,
        id_: str,
        name: str,
        channels: int = 2,
    ):
        self.id = id_
        self.name = name
        self.channels = channels
        self._fail_open = False
        self._fail_read = False
        self.recorder_calls: list[dict] = []

    def recorder(self, samplerate: int = 48000, channels: int | None = None) -> FakeRecorder:
        self.recorder_calls.append({"samplerate": samplerate, "channels": channels})
        return FakeRecorder(self)


# ---- 假设备场景 ----

def _make_speakers_scenario():
    """标准场景：一个扬声器 + 对应的 loopback + 一个麦克风。"""
    speaker = FakeSpeaker("spk_0", "扬声器 (Realtek)", channels=2)
    loopback = FakeMicrophone("spk_0", "扬声器 (Realtek) Loopback", channels=2)
    microphone = FakeMicrophone("mic_0", "默认麦克风", channels=1)
    mics_loopback = [loopback]
    mics_normal = [microphone]
    return speaker, mics_loopback, mics_normal


def _make_bluetooth_scenario():
    """蓝牙场景：蓝牙扬声器 + HFP loopback + 另一个扬声器的 loopback。"""
    speaker = FakeSpeaker("bt_0", "WH-1000XM4 Stereo", channels=2)
    hfp_loopback = FakeMicrophone("bt_0", "WH-1000XM4 Hands-Free AG Audio", channels=1)
    other_loopback = FakeMicrophone("spk_1", "扬声器 loopback", channels=2)
    mics_loopback = [hfp_loopback, other_loopback]
    mics_normal = []
    return speaker, mics_loopback, mics_normal


# ---- list_capture_devices 测试 ----

def test_list_capture_devices_detects_loopback_and_microphone(monkeypatch) -> None:
    """列出 loopback 和麦克风设备。"""
    speaker, mics_loopback, mics_normal = _make_speakers_scenario()
    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    monkeypatch.setattr(dm_module.sc, "all_microphones",
                        lambda include_loopback: mics_loopback if include_loopback else mics_normal)

    monkeypatch.setattr(dm_module, "default_microphone",
                        lambda: mics_normal[0] if mics_normal else None)

    devices = list_capture_devices()
    kinds = [d.kind for d in devices]
    assert "system_loopback" in kinds
    assert "microphone" in kinds


def test_list_capture_devices_marks_default_wasapi_loopback(monkeypatch) -> None:
    """默认扬声器对应的 loopback 应标记为 is_default。"""
    speaker = FakeSpeaker("bt_0", "蓝牙耳机", channels=2)
    loopback_bt = FakeMicrophone("bt_0", "蓝牙耳机 Hands-Free", channels=1)
    loopback_spk = FakeMicrophone("spk_0", "扬声器 loopback", channels=2)

    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    monkeypatch.setattr(dm_module.sc, "all_microphones",
                        lambda include_loopback: [loopback_bt, loopback_spk] if include_loopback else [])

    devices = list_capture_devices()
    loopbacks = [d for d in devices if d.kind == "system_loopback"]
    assert len(loopbacks) == 2
    # ID 匹配默认扬声器的 loopback 应标记为默认
    default_loopback = next(d for d in loopbacks if d.is_default)
    assert default_loopback.id == "bt_0"


# ---- AudioRecorder 初始设备发现测试 ----

def test_recorder_uses_default_wasapi_loopback(monkeypatch, tmp_path) -> None:
    """初始化时通过 find_loopback_for_speaker 发现当前设备名。"""
    speaker = FakeSpeaker("spk_0", "扬声器 (Realtek)", channels=2)
    loopback = FakeMicrophone("spk_0", "扬声器 (Realtek) Loopback", channels=2)
    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    monkeypatch.setattr(dm_module.sc, "all_microphones",
                        lambda include_loopback: [loopback])

    recorder = AudioRecorder(output_dir=tmp_path)
    assert "Realtek" in recorder.get_device_name()


# ---- validate_capture_settings 测试 ----

def test_validate_capture_settings_checks_required_devices() -> None:
    devices = [
        CaptureDeviceInfo("system", "系统声音", "system_loopback"),
        CaptureDeviceInfo("mic", "麦克风", "microphone"),
    ]
    validate_capture_settings(CaptureSettings(mode=CaptureMode.SYSTEM), devices)
    validate_capture_settings(CaptureSettings(mode=CaptureMode.MICROPHONE), devices)


def test_validate_capture_settings_rejects_missing_microphone() -> None:
    devices = [CaptureDeviceInfo("system", "系统声音", "system_loopback")]
    with pytest.raises(CaptureDeviceUnavailable, match="麦克风"):
        validate_capture_settings(CaptureSettings(mode=CaptureMode.MICROPHONE), devices)


# ---- AudioRecorder 录音异常恢复测试 ----

def test_recorder_retries_on_read_error_and_stops_cleanly(
    monkeypatch, tmp_path,
) -> None:
    """流读取异常不应设为致命错误，stop 后应正常退出且 buffer 为空。"""
    speaker = FakeSpeaker("spk_0", "扬声器", channels=2)
    loopback = FakeMicrophone("spk_0", "扬声器 Loopback", channels=2)
    loopback._fail_read = True  # read 时抛出异常

    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    monkeypatch.setattr(dm_module.sc, "all_microphones",
                        lambda include_loopback: [loopback])

    recorder = AudioRecorder(output_dir=tmp_path)
    recorder.start_recording()
    import time
    time.sleep(0.3)

    result = recorder.stop_recording()
    assert result is None
    assert recorder.get_recording_error() is None


def test_recorder_retries_on_open_error(
    monkeypatch, tmp_path,
) -> None:
    """recorder 上下文管理器打开失败时录音线程应重试而非崩溃。"""
    speaker = FakeSpeaker("spk_0", "扬声器", channels=2)
    loopback = FakeMicrophone("spk_0", "扬声器 Loopback", channels=2)
    loopback._fail_open = True  # recorder() 上下文管理器进入时抛出异常

    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    monkeypatch.setattr(dm_module.sc, "all_microphones",
                        lambda include_loopback: [loopback])

    recorder = AudioRecorder(output_dir=tmp_path)
    recorder.start_recording()
    import time
    time.sleep(0.3)

    result = recorder.stop_recording()
    assert result is None


def test_recorder_uses_selected_loopback_device_and_channels(monkeypatch, tmp_path) -> None:
    speaker = FakeSpeaker("default", "默认扬声器", channels=2)
    default_loopback = FakeMicrophone("default", "默认 Loopback", channels=2)
    selected_loopback = FakeMicrophone("selected", "外接声卡 Loopback", channels=2)

    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    monkeypatch.setattr(
        dm_module.sc,
        "all_microphones",
        lambda include_loopback: [default_loopback, selected_loopback] if include_loopback else [],
    )

    recorder = AudioRecorder(
        output_dir=tmp_path,
        settings=CaptureSettings(mode=CaptureMode.SYSTEM, system_device_id="selected"),
    )
    recorder.start_recording()
    import time
    time.sleep(0.3)
    recorder.stop_recording()

    assert not default_loopback.recorder_calls
    assert selected_loopback.recorder_calls
    assert selected_loopback.recorder_calls[0]["channels"] == 2


# ---- DeviceManager 测试 ----

def test_device_manager_start_no_output_device_raises(monkeypatch) -> None:
    """DeviceManager.start() 在无输出设备时抛出 RuntimeError。"""
    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: None)
    dm = dm_module.DeviceManager()
    with pytest.raises(RuntimeError, match="未找到音频输出设备"):
        dm.start()


def test_device_manager_start_discovers_default_speaker(monkeypatch) -> None:
    """DeviceManager.start() 发现默认 WASAPI 扬声器设备。"""
    speaker = FakeSpeaker("spk_0", "扬声器 (Realtek)", channels=2)
    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    dm = dm_module.DeviceManager()
    try:
        dm.start()
        assert "spk_0" in dm.current_speaker_id
        assert "Realtek" in dm.current_device_name
    finally:
        dm.stop()


def test_device_manager_get_loopback_uses_fresh_query(monkeypatch) -> None:
    """get_loopback_microphone() 每次实时查询当前默认设备。"""
    speaker = FakeSpeaker("bt_0", "WH-1000XM4 Stereo", channels=2)
    hfp_loopback = FakeMicrophone("bt_0", "WH-1000XM4 Hands-Free AG Audio", channels=1)
    other_loopback = FakeMicrophone("spk_1", "扬声器 loopback", channels=2)
    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    monkeypatch.setattr(dm_module.sc, "all_microphones",
                        lambda include_loopback: [hfp_loopback, other_loopback])

    dm = dm_module.DeviceManager()
    try:
        dm.start()
        loopback = dm.get_loopback_microphone()
        assert loopback is not None
        # 通过 ID 精确匹配，应返回蓝牙耳机的 loopback（而非扬声器的）
        assert loopback.id == "bt_0"
    finally:
        dm.stop()


def test_device_manager_list_devices(monkeypatch) -> None:
    """DeviceManager 列出 loopback 设备。"""
    speaker = FakeSpeaker("spk_0", "扬声器 (Realtek)", channels=2)
    loopback = FakeMicrophone("spk_0", "扬声器 (Realtek) Loopback", channels=2)
    monkeypatch.setattr(dm_module, "_get_default_speaker", lambda: speaker)
    monkeypatch.setattr(dm_module.sc, "all_microphones",
                        lambda include_loopback: [loopback])

    dm = dm_module.DeviceManager()
    loopbacks = dm.list_loopback_devices()
    assert len(loopbacks) == 1
    assert loopbacks[0].kind == "system_loopback"


# ---- 麦克风录音测试 ----

def test_microphone_recording_no_device_raises(monkeypatch, tmp_path) -> None:
    """麦克风模式下无可用设备应抛出 CaptureDeviceUnavailable。"""
    monkeypatch.setattr(rec_module.sc, "all_microphones",
                        lambda include_loopback: [])

    recorder = AudioRecorder(
        output_dir=tmp_path,
        settings=CaptureSettings(mode=CaptureMode.MICROPHONE),
    )
    with pytest.raises(CaptureDeviceUnavailable, match="麦克风"):
        recorder.start_recording()
