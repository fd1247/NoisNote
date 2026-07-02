"""本地音视频预处理。"""
from __future__ import annotations

import json
import shutil
# 仅以参数列表调用本地 ffmpeg/ffprobe，不启用 shell。
import subprocess  # nosec B404
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import soundfile as sf
import numpy as np


def _subprocess_startupinfo() -> subprocess.STARTUPINFO | None:
    """Windows 下隐藏子进程控制台窗口。"""
    if sys.platform != "win32":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def _subprocess_creationflags() -> int:
    if sys.platform != "win32":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

from ..app.config import get_config
from ..utils.ffmpeg import resolve_ffmpeg_path, resolve_ffprobe_path

DEFAULT_AUDIO_FORMATS = {"wav", "mp3", "m4a", "aac", "flac", "ogg", "wma"}
DEFAULT_VIDEO_FORMATS = {"mp4", "mov", "mkv", "avi", "webm"}


@dataclass(frozen=True)
class MediaProbeResult:
    """媒体探测结果。"""

    path: Path
    source_format: str
    duration_seconds: float | None
    has_audio_stream: bool
    audio_sample_rate: int | None = None
    audio_channels: int | None = None


@dataclass(frozen=True)
class AudioPreprocessRequest:
    """一次音频标准化请求。"""

    source_path: Path
    record_dir: Path
    source_kind: str
    target_sample_rate: int = 16000
    target_channels: int = 1
    target_format: str = "wav"
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None


@dataclass(frozen=True)
class AudioPreprocessResult:
    """音频标准化结果。"""

    normalized_audio_path: Path
    original_path: Path
    duration_seconds: float | None
    sample_rate: int
    channels: int
    source_format: str
    has_audio_stream: bool = True


class AudioInputError(RuntimeError):
    """音频输入或预处理失败。"""

    def __init__(self, kind: str, message: str, details: str = ""):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details or message

    def to_metadata(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "details": self.details,
        }


ProgressCallback = Callable[[str, int | None], None]


def supported_audio_formats(config: dict | None = None) -> set[str]:
    values = (
        (config or get_config())
        .get("audio", {})
        .get("preprocessing", {})
        .get("supported_audio_formats")
        or DEFAULT_AUDIO_FORMATS
    )
    return {str(item).lower().lstrip(".") for item in values}


def supported_video_formats(config: dict | None = None) -> set[str]:
    values = (
        (config or get_config())
        .get("audio", {})
        .get("preprocessing", {})
        .get("supported_video_formats")
        or DEFAULT_VIDEO_FORMATS
    )
    return {str(item).lower().lstrip(".") for item in values}


def is_supported_media(path: Path, config: dict | None = None) -> bool:
    suffix = path.suffix.lower().lstrip(".")
    return suffix in supported_audio_formats(config) or suffix in supported_video_formats(config)


def source_kind_for_path(path: Path, config: dict | None = None) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in supported_video_formats(config):
        return "local_video"
    return "local_audio"


def media_filter_string(config: dict | None = None) -> str:
    audio = " ".join(f"*.{item}" for item in sorted(supported_audio_formats(config)))
    video = " ".join(f"*.{item}" for item in sorted(supported_video_formats(config)))
    return f"音视频文件 ({audio} {video});;音频文件 ({audio});;视频文件 ({video});;所有文件 (*.*)"


def probe_media(path: Path, config: dict | None = None, ffprobe_path: Path | None = None) -> MediaProbeResult:
    """探测媒体文件基础信息。"""
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise AudioInputError("file_unreadable", "文件损坏或无法读取。", str(source))
    if not is_supported_media(source, config):
        raise AudioInputError("unsupported_format", "格式不支持。", source.suffix)

    if source.suffix.lower() == ".wav":
        wav_probe = _probe_wav(source)
        if wav_probe:
            return wav_probe

    ffprobe = ffprobe_path or resolve_ffprobe_path(config)
    if not ffprobe:
        raise AudioInputError("file_unreadable", "缺少 ffprobe，无法探测音视频文件。")

    command = [
        str(ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    try:
        # command 由本地 ffprobe 路径和参数列表组成，不启用 shell。
        # 使用 utf-8 编码避免 Windows 中文系统 GBK 解码失败。
        run_kwargs = {
            "capture_output": True,
            "timeout": 30,
            "check": False,
            "startupinfo": _subprocess_startupinfo(),
        }
        creationflags = _subprocess_creationflags()
        if creationflags:
            run_kwargs["creationflags"] = creationflags
        completed = subprocess.run(command, **run_kwargs)  # nosec B603
    except OSError as exc:
        raise AudioInputError("file_unreadable", "文件损坏或无法读取。", str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioInputError("file_unreadable", "文件损坏或无法读取。", "ffprobe timeout") from exc
    if completed.returncode != 0:
        raise AudioInputError("file_unreadable", "文件损坏或无法读取。", completed.stderr.decode("utf-8", errors="replace"))

    try:
        stdout_text = completed.stdout.decode("utf-8", errors="replace") if completed.stdout else ""
        data = json.loads(stdout_text or "{}")
    except json.JSONDecodeError as exc:
        raise AudioInputError("file_unreadable", "文件损坏或无法读取。", stdout_text) from exc

    streams = data.get("streams") if isinstance(data, dict) else []
    if not isinstance(streams, list):
        streams = []
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not audio_stream:
        raise AudioInputError(
            "no_audio_stream",
            "文件中没有可转录的音轨。",
            details=completed.stderr.decode("utf-8", errors="replace").strip() if hasattr(completed, "stderr") else "",
        )

    duration = _float_or_none(audio_stream.get("duration"))
    if duration is None:
        duration = _float_or_none((data.get("format") or {}).get("duration"))

    return MediaProbeResult(
        path=source,
        source_format=str((data.get("format") or {}).get("format_name") or source.suffix.lstrip(".")),
        duration_seconds=duration,
        has_audio_stream=True,
        audio_sample_rate=_int_or_none(audio_stream.get("sample_rate")),
        audio_channels=_int_or_none(audio_stream.get("channels")),
    )


def normalize_audio(
    request: AudioPreprocessRequest,
    progress_callback: ProgressCallback | None = None,
    config: dict | None = None,
) -> AudioPreprocessResult:
    """把输入音视频转换为 ASR 标准 wav。"""
    _emit(progress_callback, "探测音频", 5)
    source = Path(request.source_path)
    probe = probe_media(source, config=config, ffprobe_path=request.ffprobe_path)
    target = request.record_dir / "audio.normalized.wav"
    request.record_dir.mkdir(parents=True, exist_ok=True)

    if _can_copy_wav(source, probe, request):
        shutil.copy2(source, target)
        _emit(progress_callback, "音频已标准化", 100)
        return AudioPreprocessResult(
            normalized_audio_path=target,
            original_path=source,
            duration_seconds=probe.duration_seconds,
            sample_rate=request.target_sample_rate,
            channels=request.target_channels,
            source_format=probe.source_format,
        )

    ffmpeg = request.ffmpeg_path or resolve_ffmpeg_path()
    if not ffmpeg:
        raise AudioInputError("transcode_failed", "转码失败。", "missing ffmpeg")

    _emit(progress_callback, "正在转换音频", 25)
    command = build_ffmpeg_normalize_command(ffmpeg, source, target, request)
    try:
        # command 由本地 ffmpeg 路径和参数列表组成，不启用 shell。
        # 使用 bytes 模式避免 Windows 中文系统 GBK 解码失败。
        run_kwargs = {
            "capture_output": True,
            "timeout": None,
            "check": False,
            "startupinfo": _subprocess_startupinfo(),
        }
        creationflags = _subprocess_creationflags()
        if creationflags:
            run_kwargs["creationflags"] = creationflags
        completed = subprocess.run(command, **run_kwargs)  # nosec B603
    except OSError as exc:
        raise AudioInputError("transcode_failed", "转码失败。", str(exc)) from exc
    if completed.returncode != 0 or not target.exists():
        raise AudioInputError("transcode_failed", "转码失败。", completed.stderr.decode("utf-8", errors="replace"))

    _emit(progress_callback, "音频已标准化", 100)
    normalized_probe = _probe_wav(target)
    return AudioPreprocessResult(
        normalized_audio_path=target,
        original_path=source,
        duration_seconds=(normalized_probe.duration_seconds if normalized_probe else probe.duration_seconds),
        sample_rate=request.target_sample_rate,
        channels=request.target_channels,
        source_format=probe.source_format,
    )


def build_ffmpeg_normalize_command(
    ffmpeg_path: Path,
    source_path: Path,
    target_path: Path,
    request: AudioPreprocessRequest,
) -> list[str]:
    """构造标准化转码命令。"""
    return [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        str(request.target_channels),
        "-ar",
        str(request.target_sample_rate),
        "-sample_fmt",
        "s16",
        str(target_path),
    ]


def _can_copy_wav(source: Path, probe: MediaProbeResult, request: AudioPreprocessRequest) -> bool:
    return (
        source.suffix.lower() == ".wav"
        and probe.audio_sample_rate == request.target_sample_rate
        and probe.audio_channels == request.target_channels
    )


def _probe_wav(path: Path) -> MediaProbeResult | None:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frames = wav_file.getnframes()
            channels = wav_file.getnchannels()
            duration = frames / frame_rate if frame_rate > 0 else None
    except (wave.Error, OSError, EOFError):
        return None
    return MediaProbeResult(
        path=path,
        source_format="wav",
        duration_seconds=duration,
        has_audio_stream=True,
        audio_sample_rate=frame_rate,
        audio_channels=channels,
    )


def _emit(callback: ProgressCallback | None, text: str, percent: int | None = None) -> None:
    if callback:
        callback(text, percent)


def _float_or_none(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class SilenceDetectionResult:
    """静音检测结果。"""
    is_silent: bool
    max_amplitude: float
    rms_level: float
    threshold: float


def detect_silence(
    audio_path: Path,
    threshold: float = 0.001,
    max_duration: float = 600.0,
) -> SilenceDetectionResult:
    """检测音频是否为静音或接近静音。

    Args:
        audio_path: 音频文件路径
        threshold: 最大振幅阈值，低于此值视为静音（默认 0.001）
        max_duration: 最大检测时长，超过该时长会跳过检测（默认 10 分钟）

    Returns:
        SilenceDetectionResult: 包含是否静音、最大振幅、RMS 水平等信息
    """
    try:
        with sf.SoundFile(audio_path) as audio_file:
            duration = audio_file.frames / audio_file.samplerate if audio_file.samplerate > 0 else None
        if duration is not None and duration > max_duration:
            return SilenceDetectionResult(is_silent=False, max_amplitude=0.0, rms_level=0.0, threshold=threshold)

        y, sr = sf.read(audio_path, dtype='float32')
        if len(y) == 0:
            return SilenceDetectionResult(is_silent=True, max_amplitude=0.0, rms_level=0.0, threshold=threshold)

        # 如果是多声道，转换为单声道（取平均）
        if len(y.shape) > 1:
            y = y.mean(axis=1)

        max_amp = float(np.abs(y).max())
        rms = float(np.sqrt(np.mean(y ** 2)))

        return SilenceDetectionResult(
            is_silent=max_amp < threshold,
            max_amplitude=max_amp,
            rms_level=rms,
            threshold=threshold,
        )
    except Exception:
        # 读取失败时保守地认为不是静音，避免误判
        return SilenceDetectionResult(is_silent=False, max_amplitude=0.0, rms_level=0.0, threshold=threshold)
