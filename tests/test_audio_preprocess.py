from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

from audio_recorder.audio.preprocess import (
    AudioInputError,
    AudioPreprocessRequest,
    build_ffmpeg_normalize_command,
    is_supported_media,
    media_filter_string,
    normalize_audio,
    probe_media,
    source_kind_for_path,
)
from audio_recorder.utils.ffmpeg import check_ffmpeg_available, resolve_ffmpeg_path


def write_wav(path: Path, frames: int = 16000, rate: int = 16000, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames * channels)


def test_media_support_and_filter_string() -> None:
    assert is_supported_media(Path("meeting.mp3"))
    assert is_supported_media(Path("meeting.mp4"))
    assert not is_supported_media(Path("meeting.docx"))
    assert source_kind_for_path(Path("meeting.mp4")) == "local_video"
    assert source_kind_for_path(Path("meeting.wav")) == "local_audio"
    assert "*.mp3" in media_filter_string()
    assert "*.webm" in media_filter_string()


def test_probe_wav_without_ffmpeg(tmp_path: Path) -> None:
    source = tmp_path / "audio.wav"
    write_wav(source, frames=32000)

    result = probe_media(source)

    assert result.has_audio_stream
    assert result.audio_sample_rate == 16000
    assert result.audio_channels == 1
    assert result.duration_seconds == 2


def test_normalize_standard_wav_copies_to_record_dir(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    record_dir = tmp_path / "record"
    write_wav(source)

    result = normalize_audio(AudioPreprocessRequest(source, record_dir, "local_audio"))

    assert result.normalized_audio_path == record_dir / "audio.normalized.wav"
    assert result.normalized_audio_path.exists()
    assert result.sample_rate == 16000
    assert result.channels == 1


def test_probe_media_rejects_unsupported_format(tmp_path: Path) -> None:
    source = tmp_path / "notes.txt"
    source.write_text("hello", encoding="utf-8")

    with pytest.raises(AudioInputError) as excinfo:
        probe_media(source)

    assert excinfo.value.kind == "unsupported_format"


def test_build_ffmpeg_command_uses_asr_standard_format(tmp_path: Path) -> None:
    request = AudioPreprocessRequest(tmp_path / "in.mp4", tmp_path, "local_video")

    command = build_ffmpeg_normalize_command(
        Path("ffmpeg"),
        request.source_path,
        tmp_path / "audio.normalized.wav",
        request,
    )

    assert "-vn" in command
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "16000"


def test_check_ffmpeg_available_reports_missing(monkeypatch) -> None:
    monkeypatch.setattr("audio_recorder.utils.ffmpeg_runtime.shutil.which", lambda name: None)

    assert resolve_ffmpeg_path({}) is None
    result = check_ffmpeg_available({})
    assert not result.available
    assert "ffmpeg" in result.message


def test_check_ffmpeg_available_accepts_configured_paths(monkeypatch, tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_text("", encoding="utf-8")
    ffprobe.write_text("", encoding="utf-8")
    monkeypatch.setattr("audio_recorder.utils.ffmpeg_runtime.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "audio_recorder.utils.ffmpeg_runtime.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )

    config = {"audio": {"preprocessing": {"ffmpeg_path": str(ffmpeg)}}}
    result = check_ffmpeg_available(config)

    assert result.available
    assert result.ffmpeg_path == ffmpeg
    assert result.ffprobe_path == ffprobe
