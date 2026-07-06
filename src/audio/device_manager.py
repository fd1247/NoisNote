"""设备管理器。

负责发现 Windows WASAPI Loopback 设备，并通过后台轮询检测蓝牙等音频
设备的连接/断开变化。使用 soundcard 库进行设备发现。

架构参考 demo/windows音频采集demo/device_manager.py 的已验证实现：
- get_loopback_microphone() 每次调用实时查询当前默认设备，不依赖缓存
- 通过 mic.id == speaker.id 精确匹配 loopback（WASAPI 端点 ID）
- _poll_loop 仅负责检测变化并设置 device_changed 事件
"""
from __future__ import annotations

import logging
import re
import threading
import time

import soundcard as sc
from soundcard import default_microphone

from .types import CaptureDeviceInfo

logger = logging.getLogger(__name__)

# 设备轮询间隔（秒）
_POLL_INTERVAL = 1.0
_LOOPBACK_NAME_RE = re.compile(r"\b(loopback|what u hear|stereo mix|立体声混音|系统声音)\b", re.IGNORECASE)

class DeviceManager:
    """音频设备管理器。

    通过 soundcard 枚举 WASAPI Loopback 设备，后台线程轮询检测默认
    输出设备变化。当默认播放设备变化时（如蓝牙耳机连接/断开），设置
    device_changed 事件通知录音模块切换流。

    线程安全：_lock 保护设备信息读写，device_changed 是 threading.Event。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._device_changed = threading.Event()
        self._current_speaker_id: str = ""
        self._current_device_name: str = "未检测到设备"
        self._running = False
        self._poll_thread: threading.Thread | None = None

    # ---- 公开属性 ----

    @property
    def device_changed(self) -> threading.Event:
        """默认输出设备变化时会 set 此 Event，录音模块监控此事件。"""
        return self._device_changed

    @property
    def current_device_name(self) -> str:
        """当前默认播放设备名称（线程安全）。"""
        with self._lock:
            return self._current_device_name

    @property
    def current_speaker_id(self) -> str:
        """当前 WASAPI 默认输出设备端点 ID（线程安全）。"""
        with self._lock:
            return self._current_speaker_id

    # ---- 生命周期 ----

    def start(self, preferred_loopback_id: str | None = None) -> None:
        """初始化设备发现并启动轮询线程。

        Raises:
            RuntimeError: 未找到可用的扬声器设备。
        """
        loopback = self.get_loopback_microphone(preferred_loopback_id)
        speaker = _get_default_speaker()
        if loopback is None and speaker is None:
            raise RuntimeError(
                "未找到音频输出设备。请确保扬声器或耳机已连接。"
            )

        with self._lock:
            self._current_speaker_id = str(getattr(loopback or speaker, "id", ""))
            self._current_device_name = str(getattr(loopback or speaker, "name", "未检测到设备"))

        logger.info("当前录音设备: %s (ID: %s)", self._current_device_name, self._current_speaker_id)

        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop(self) -> None:
        """停止轮询线程。"""
        self._running = False
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=2.0)

    # ---- 核心方法 ----

    def get_loopback_microphone(self, preferred_id: str | None = None):
        """获取当前默认扬声器对应的 Loopback 麦克风。

        通过 include_loopback=True 列出所有 loopback 虚拟麦克风，
        以 WASAPI 端点 ID 精确匹配当前默认扬声器。ID 匹配失败时
        尝试名称匹配。

        每次调用都实时查询当前默认扬声器，不依赖缓存。

        Returns:
            soundcard.Microphone 对象，找不到则返回 None

        架构对齐 demo 中 DeviceManager.get_loopback_microphone()：
            mic.id == speaker.id（WASAPI 端点 ID 精确匹配）
        """
        try:
            mics = _list_loopback_microphones()
            if preferred_id:
                for mic in mics:
                    if mic.id == preferred_id:
                        return mic

            speaker = _get_default_speaker()
            if speaker is None:
                return None

            # 查找匹配的 loopback 麦克风（ID 精确匹配）
            for mic in mics:
                if mic.id == speaker.id:
                    return mic

            # 如果 ID 匹配不上，尝试用名字匹配（兼容非标准设备）
            for mic in mics:
                if _same_endpoint_name(mic.name, speaker.name):
                    return mic

            if len(mics) == 1:
                return mics[0]

            return None
        except Exception as e:
            logger.warning("获取 loopback 麦克风失败: %s", e)
            return None

    def list_loopback_devices(self) -> list[CaptureDeviceInfo]:
        """列出当前可用的 WASAPI loopback 设备。"""
        devices: list[CaptureDeviceInfo] = []
        try:
            default_speaker = _get_default_speaker()
            default_id = default_speaker.id if default_speaker else None
            mics = _list_loopback_microphones()
            for mic in mics:
                devices.append(
                    CaptureDeviceInfo(
                        id=mic.id,
                        name=mic.name,
                        kind="system_loopback",
                        is_default=mic.id == default_id,
                        is_available=True,
                    )
                )
        except Exception:
            pass
        return devices

    def list_microphone_devices(self) -> list[CaptureDeviceInfo]:
        """列出当前可用的麦克风设备（非 loopback）。"""
        devices: list[CaptureDeviceInfo] = []
        try:
            try:
                default_mic = default_microphone()
                default_id = default_mic.id
            except Exception:
                default_id = None
            mics = sc.all_microphones(include_loopback=False)
            for mic in mics:
                devices.append(
                    CaptureDeviceInfo(
                        id=mic.id,
                        name=mic.name,
                        kind="microphone",
                        is_default=mic.id == default_id,
                        is_available=True,
                    )
                )
        except Exception:
            pass
        return devices

    # ---- 内部实现 ----

    def _poll_loop(self) -> None:
        """后台轮询线程：每秒检查默认扬声器是否变化。

        仅负责检测变化并设置 device_changed 事件。
        不对 loopback 设备做任何缓存——loopback 查找由
        get_loopback_microphone() 实时完成。

        架构对齐 demo 中 DeviceManager._poll_loop()。
        """
        last_speaker_id = self._current_speaker_id

        while self._running:
            time.sleep(_POLL_INTERVAL)
            if not self._running:
                break

            try:
                speaker = _get_default_speaker()
            except Exception:
                continue

            if speaker is None:
                continue

            if speaker.id != last_speaker_id:
                with self._lock:
                    old_name = self._current_device_name
                    self._current_speaker_id = speaker.id
                    self._current_device_name = speaker.name

                logger.info(
                    "检测到设备变化: '%s' -> '%s'", old_name, speaker.name
                )
                last_speaker_id = speaker.id
                self._device_changed.set()
                # 注意：不在这里 clear，由录音模块处理后自行 clear


# ---- 辅助函数 ----

def _get_default_speaker():
    """获取当前默认扬声器，失败返回 None。"""
    try:
        return sc.default_speaker()
    except Exception as e:
        logger.warning("获取默认扬声器失败: %s", e)
        return None



def _list_loopback_microphones() -> list:
    """只返回真正的系统回环录音端点。"""
    loopback_candidates = list(sc.all_microphones(include_loopback=True))
    candidate_ids = {str(getattr(mic, "id", "")) for mic in loopback_candidates}
    try:
        normal_ids = {str(getattr(mic, "id", "")) for mic in sc.all_microphones(include_loopback=False)}
    except Exception:
        normal_ids = set()
    if normal_ids == candidate_ids:
        normal_ids = set()

    filtered = [
        mic
        for mic in loopback_candidates
        if _looks_like_loopback(mic) or str(getattr(mic, "id", "")) not in normal_ids
    ]
    return filtered or loopback_candidates

def _looks_like_loopback(mic) -> bool:
    """根据 soundcard 属性和名称判断设备是否为 WASAPI loopback。"""
    for attr in ("isloopback", "is_loopback", "_isloopback", "_is_loopback"):
        value = getattr(mic, attr, None)
        if isinstance(value, bool) and value:
            return True
    name = str(getattr(mic, "name", ""))
    return bool(_LOOPBACK_NAME_RE.search(name))

def _same_endpoint_name(left: str, right: str) -> bool:
    """比较去掉 loopback 后缀后的端点名称。"""
    normalized_left = _normalize_endpoint_name(left)
    normalized_right = _normalize_endpoint_name(right)
    if not normalized_left or not normalized_right:
        return False
    return (
        normalized_left == normalized_right
        or normalized_left in normalized_right
        or normalized_right in normalized_left
    )

def _normalize_endpoint_name(value: str) -> str:
    text = value.lower()
    text = _LOOPBACK_NAME_RE.sub(" ", text)
    text = re.sub(r"[\[\]\(\)（）:：,，._-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

# ---- 公共函数 ----

def list_capture_devices() -> list[CaptureDeviceInfo]:
    """列出当前可用的系统声音 loopback 和麦克风设备。"""
    devices: list[CaptureDeviceInfo] = []

    try:
        default_speaker = _get_default_speaker()
        default_speaker_id = default_speaker.id if default_speaker else None
    except Exception:
        default_speaker_id = None

    try:
        default_mic = default_microphone()
        default_mic_id = default_mic.id
    except Exception:
        default_mic_id = None

    # 系统声音 loopback 设备
    try:
        mics = _list_loopback_microphones()
        for mic in mics:
            devices.append(
                CaptureDeviceInfo(
                    id=mic.id,
                    name=mic.name,
                    kind="system_loopback",
                    is_default=mic.id == default_speaker_id,
                    is_available=True,
                )
            )
    except Exception:
        pass

    # 麦克风设备
    try:
        mics = sc.all_microphones(include_loopback=False)
        for mic in mics:
            devices.append(
                CaptureDeviceInfo(
                    id=mic.id,
                    name=mic.name,
                    kind="microphone",
                    is_default=mic.id == default_mic_id,
                    is_available=True,
                )
            )
    except Exception:
        pass

    return devices


def validate_capture_settings(
    settings,
    devices=None,
) -> None:
    """录音开始前检查所需设备是否可用。"""
    from .types import CaptureDeviceUnavailable, CaptureMode  # noqa: F811

    available = list(devices) if devices is not None else list_capture_devices()
    if settings.mode == CaptureMode.SYSTEM:
        _require_device(
            available, "system_loopback", settings.system_device_id,
            "未找到可用的系统声音设备",
        )
        return
    if settings.mode == CaptureMode.MICROPHONE:
        _require_device(
            available, "microphone", settings.microphone_device_id,
            "未找到可用的麦克风设备",
        )
        return
    raise CaptureDeviceUnavailable(f"未知录音模式：{settings.mode}")


def _require_device(
    devices: list[CaptureDeviceInfo],
    kind: str,
    device_id: str | None,
    message: str,
) -> CaptureDeviceInfo:
    from .types import CaptureDeviceUnavailable  # noqa: F811

    candidates = [item for item in devices if item.kind == kind and item.is_available]
    if device_id:
        candidates = [item for item in candidates if item.id == str(device_id)]
    if not candidates:
        raise CaptureDeviceUnavailable(message)
    preferred = next((item for item in candidates if item.is_default), None)
    return preferred or candidates[0]
