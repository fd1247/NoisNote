"""音频录制引擎。

使用 soundcard 库通过 WASAPI Loopback 采集系统播放音频。
支持蓝牙设备热切换，切换间隙自动填充静音。

设计参考 demo/windows音频采集demo/audio_recorder.py 的已验证架构：
- _record_loop 每次迭代实时查询 loopback 设备（不缓存）
- mic.recorder() 上下文管理器自动管理流生命周期
- device_changed.clear() 在流成功打开后执行
- 流读取错误不设置为致命错误，记录日志后重试
- 上下文管理器退出时自动清理，无需 abort_stream/close/terminate
"""
from __future__ import annotations

import logging
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import soundcard as sc

from .device_manager import DeviceManager
from .types import (
    CaptureDeviceUnavailable,
    CaptureMode,
    CaptureSettings,
    VolumeCallback,
)

logger = logging.getLogger(__name__)

# 每次读取的音频块时长（秒），决定设备切换响应延迟
_BLOCK_DURATION = 0.1  # 100ms

# 读取超时倍数：read_duration 超过 _BLOCK_DURATION * 此值时认为设备断连
_READ_TIMEOUT_MULTIPLIER = 3

# 系统音频 Loopback 录音使用的固定采样率和声道数
# WASAPI loopback 标准格式为 48000 Hz 立体声
_SYSTEM_SAMPLE_RATE = 48000
_SYSTEM_CHANNELS = 2

# 麦克风录音使用的默认采样率和声道数
_MIC_SAMPLE_RATE = 16000
_MIC_CHANNELS = 1


class AudioRecorder:
    """Windows 音频录制器。

    通过 soundcard 的 WASAPI Loopback 采集系统播放音频。
    后台线程持续录音，支持设备热切换。静音填充切换间隙。

    线程安全设计：
    - 流操作全部在录音线程内完成（soundcard 上下文管理器）
    - UI 线程只通过 _is_running 和 _stop_requested 发信号
    - DeviceManager 通过 device_changed Event 通知设备变化
    """

    def __init__(
        self,
        output_dir: str | Path | None = None,
        settings: CaptureSettings | None = None,
    ):
        self.settings = settings or CaptureSettings()
        self._device_manager = DeviceManager()
        self._buffer: list[bytes] = []
        self._is_running = False
        self._stop_requested = False
        self._is_paused = False
        self._start_time: float | None = None
        self._record_thread: threading.Thread | None = None
        self._recording_rate = _SYSTEM_SAMPLE_RATE
        self._recording_channels = _SYSTEM_CHANNELS
        self._rms_level: int = 0
        self._rms_lock = threading.Lock()
        self._recording_error: Exception | None = None
        self._volume_callback: VolumeCallback | None = None
        self._device_name: str = "未检测到设备"
        self.output_dir = Path(output_dir) if output_dir else (
            Path.home() / "Documents" / "NoisNote" / "recordings"
        )
        self._mic_device = None  # soundcard.Microphone 对象

        # 初始设备发现：不启动轮询线程，仅查询当前设备名称
        self._init_device_info()

    # ---- 初始设备发现 ----

    def _init_device_info(self) -> None:
        """执行初始设备发现，不启动轮询线程。"""
        device = self._device_manager.get_loopback_microphone()
        if device is not None:
            self._device_name = str(getattr(device, "name", "未检测到设备"))

    # ---- 状态属性 ----

    @property
    def is_recording(self) -> bool:
        return self._is_running

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def device_name(self) -> str:
        """当前录音设备名称。"""
        return self._device_name

    @property
    def device_changed_event(self) -> threading.Event:
        """设备变化事件，外部可 set 以通知录音线程。"""
        return self._device_manager.device_changed

    def get_device_name(self) -> str:
        """返回录音设备名称（兼容旧接口）。"""
        return self._device_name

    def get_recording_error(self) -> Exception | None:
        return self._recording_error

    def get_duration(self) -> float:
        """获取当前录音时长（秒）。"""
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def volume_callback(self) -> VolumeCallback | None:
        return self._volume_callback

    @volume_callback.setter
    def volume_callback(self, callback: VolumeCallback | None) -> None:
        self._volume_callback = callback

    @property
    def recording_error(self) -> Exception | None:
        return self._recording_error

    @property
    def recording_rate(self) -> int:
        return self._recording_rate

    @property
    def recording_channels(self) -> int:
        return self._recording_channels

    # ---- 配置 ----

    def configure(self, settings: CaptureSettings) -> None:
        """更新录音参数。录音进行中不可调用。"""
        if self._is_running:
            raise RuntimeError("录音进行中，无法切换录音参数")
        self.settings = settings

    def set_output_dir(self, output_dir: str | Path) -> None:
        """更新录音文件输出目录。"""
        self.output_dir = Path(output_dir)

    def get_rms_level(self) -> int:
        """获取当前音频 RMS 电平（0-100）。"""
        with self._rms_lock:
            return self._rms_level

    def capture_source_label(self) -> str:
        labels = {
            CaptureMode.SYSTEM: "系统声音",
            CaptureMode.MICROPHONE: "麦克风",
        }
        return labels.get(self.settings.mode, "系统声音")

    # ---- 生命周期 ----

    def start_recording(self) -> None:
        """开始录音。

        启动 DeviceManager 轮询，然后启动录音线程。

        Raises:
            RuntimeError: 已在录音中时重复调用。
            CaptureDeviceUnavailable: 未找到可用设备。
        """
        if self._is_running:
            raise RuntimeError("录音已在进行中，请先停止当前录音")

        self._recording_error = None
        self._buffer = []
        self._stop_requested = False
        self._is_paused = False
        self._start_time = time.time()

        # 麦克风模式：直接查找设备
        if self.settings.mode == CaptureMode.MICROPHONE:
            self._start_microphone_recording()
            return

        # 系统声音模式：使用 48000 Hz 立体声（WASAPI loopback 标准）
        self._recording_rate = _SYSTEM_SAMPLE_RATE
        self._recording_channels = _SYSTEM_CHANNELS

        # 启动 DeviceManager 轮询
        try:
            self._device_manager.start()
        except RuntimeError:
            raise CaptureDeviceUnavailable("未找到可用的系统声音设备")

        self._device_name = self._device_manager.current_device_name
        self._is_running = True
        self._record_thread = threading.Thread(
            target=self._record_loop, daemon=True, name="AudioRecorder"
        )
        self._record_thread.start()

    def _start_microphone_recording(self) -> None:
        """麦克风模式录音启动。"""
        preferred_id = self.settings.microphone_device_id

        try:
            mics = sc.all_microphones(include_loopback=False)
        except Exception:
            mics = []

        mic = None
        if preferred_id:
            for m in mics:
                if m.id == preferred_id:
                    mic = m
                    break
        if mic is None and mics:
            # 使用默认麦克风（列表中第一个）
            mic = mics[0]

        if mic is None:
            raise CaptureDeviceUnavailable("未找到可用的麦克风设备")

        self._mic_device = mic
        self._device_name = mic.name
        self._recording_rate = _MIC_SAMPLE_RATE
        self._recording_channels = _MIC_CHANNELS
        self._is_running = True
        self._record_thread = threading.Thread(
            target=self._mic_record_loop, daemon=True, name="MicRecorder"
        )
        self._record_thread.start()

    def stop_recording(self) -> str | None:
        """停止录音，返回保存的 WAV 文件路径。"""
        self._stop_requested = True
        self._is_running = False

        if self.settings.mode != CaptureMode.MICROPHONE:
            self._device_manager.stop()

        if self._record_thread and self._record_thread.is_alive():
            self._record_thread.join(timeout=5)

        if self._recording_error is not None:
            error = self._recording_error
            self._recording_error = None
            self._buffer = []
            raise RuntimeError(f"录音设备读取失败：{error}") from error

        if not self._buffer:
            return None

        # 保存为 WAV 文件
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:17]
        output_file = output_dir / f"{timestamp}.wav"

        wf = wave.open(str(output_file), "wb")
        wf.setnchannels(max(1, int(self._recording_channels)))
        wf.setsampwidth(2)  # int16
        wf.setframerate(int(self._recording_rate))
        wf.writeframes(b"".join(self._buffer))
        wf.close()

        return str(output_file)

    def pause_recording(self) -> None:
        self._is_paused = True

    def resume_recording(self) -> None:
        self._is_paused = False

    def cleanup(self) -> None:
        """清理资源。"""
        if self._is_running:
            self._stop_requested = True
            self._is_running = False
        if self.settings.mode != CaptureMode.MICROPHONE:
            self._device_manager.stop()
        if self._record_thread and self._record_thread.is_alive():
            self._record_thread.join(timeout=3)

    # ---- 录音线程 ----

    def _record_stream(self, rec, check_device_change: bool = False) -> None:
        """从 recorder 连续读取音频块，直到停止、错误或设备变化。

        Args:
            rec: soundcard 的 recorder 上下文管理器返回的录制对象
            check_device_change: True 时监控 device_changed 事件（系统声音模式）
        """
        while self._is_running and not self._stop_requested:
            if self._is_paused:
                time.sleep(0.05)
                continue

            if check_device_change and self._device_manager.device_changed.is_set():
                logger.info("设备变化，切换录音流...")
                break

            try:
                read_start = time.perf_counter()
                data = rec.record(numframes=int(self._recording_rate * _BLOCK_DURATION))
                read_duration = time.perf_counter() - read_start
            except Exception as exc:
                logger.warning("读取音频块失败: %s", exc)
                break

            if check_device_change and read_duration > _BLOCK_DURATION * _READ_TIMEOUT_MULTIPLIER:
                silence_frames = int(
                    (read_duration - _BLOCK_DURATION) * self._recording_rate
                )
                if silence_frames > 0:
                    self._append_silence(silence_frames, self._recording_channels)

            if data.shape[0] > 0:
                self._process_audio_block(data)

    def _record_loop(self) -> None:
        """主录音循环（系统声音模式）。

        对应 demo 的 AudioRecorder._record_loop() 架构：
        每次迭代实时查询当前 loopback，通过上下文管理器打开流，
        _record_stream 持续读取直到设备变化或停止。
        """
        while self._is_running and not self._stop_requested:
            mic = self._device_manager.get_loopback_microphone()
            if mic is None:
                logger.warning("无可用 loopback 设备，等待中...")
                for _ in range(50):
                    if not self._is_running or self._stop_requested:
                        return
                    time.sleep(0.1)
                    try:
                        mic = self._device_manager.get_loopback_microphone()
                    except Exception:
                        mic = None
                    if mic is not None:
                        break
                if mic is None:
                    continue

            try:
                recorder = mic.recorder(samplerate=self._recording_rate)
                with recorder as rec:
                    logger.info("已连接到录音设备: %s", mic.name)
                    self._device_name = mic.name
                    self._device_manager.device_changed.clear()
                    self._record_stream(rec, check_device_change=True)
            except Exception as exc:
                logger.warning("录音流异常，将重试: %s", exc)
                time.sleep(0.5)
                continue

        self._is_running = False

    def _mic_record_loop(self) -> None:
        """麦克风录音循环。"""
        if self._mic_device is None:
            self._recording_error = RuntimeError("麦克风设备不可用")
            return

        try:
            recorder = self._mic_device.recorder(samplerate=self._recording_rate)
            with recorder as rec:
                logger.info("已连接到麦克风: %s", self._mic_device.name)
                self._device_name = self._mic_device.name
                self._record_stream(rec, check_device_change=False)
        except Exception as exc:
            logger.warning("麦克风录音异常: %s", exc)

    # ---- 音频处理 ----

    def _process_audio_block(self, data: np.ndarray) -> None:
        """处理一个音频块：追加到 buffer、计算 RMS 电平。

        Args:
            data: soundcard 返回的 float32 数组, shape=(frames, channels),
                  值域 [-1.0, 1.0]
        """
        frames = data.shape[0]
        if frames <= 0:
            return

        # 计算 RMS 电平（在 float32 域计算，值域 [0, 1]）
        try:
            # 取左/单声道计算 RMS
            channel_data = data[:, 0].astype(np.float64)
            rms = float(np.sqrt(np.mean(channel_data ** 2)))
            # 映射到 0-100，乘以 3 放大显示
            level = min(100, int(rms * 300))
        except Exception:
            level = 0

        with self._rms_lock:
            self._rms_level = level
        if self._volume_callback:
            self._volume_callback(level)

        # 转换为 int16 bytes（WAV 格式）
        int_data = (data * 32767.0).clip(-32768, 32767).astype(np.int16)

        # 声道处理
        if int_data.shape[1] < self._recording_channels:
            int_data = np.tile(int_data, (1, self._recording_channels))
        elif int_data.shape[1] > self._recording_channels:
            int_data = int_data[:, :self._recording_channels]

        self._buffer.append(int_data.tobytes())

    def _append_silence(self, num_frames: int, channels: int) -> None:
        """追加静音帧到 buffer。"""
        silence = b"\x00" * (num_frames * channels * 2)  # int16 = 2 bytes
        self._buffer.append(silence)
