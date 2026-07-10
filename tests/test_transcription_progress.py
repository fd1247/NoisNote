from __future__ import annotations

import wave
from pathlib import Path

from src.asr.engine import ProgressReporter, TranscriptionProgress, _wav_duration


def write_wav(path: Path, frames: int = 48000, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames)


def test_wav_duration_reads_total_seconds(tmp_path: Path) -> None:
    source = tmp_path / "long.wav"
    write_wav(source)

    assert _wav_duration(source) == 3


def test_progress_reporter_keeps_percent_monotonic() -> None:
    events: list[TranscriptionProgress] = []
    reporter = ProgressReporter(events.append, total_seconds=10800)

    reporter.emit("transcribing", 40, "正在转录 40%", 4000)
    reporter.emit("transcribing", 20, "正在转录 20%", 2000)
    reporter.emit("completed", 100, "转录完成", 10800)

    assert [event.percent for event in events] == [40, 40, 100]
    assert events[0].total_seconds == 10800


def test_progress_reporter_maps_model_loading_text() -> None:
    events: list[TranscriptionProgress] = []
    reporter = ProgressReporter(events.append, total_seconds=60)

    reporter.emit_text("正在加载 Qwen3-ASR GGUF 模型")

    assert events[0].stage == "loading_asr_model"
    assert events[0].message == "正在加载ASR模型"


def test_progress_reporter_keeps_transcription_progress_independent_from_loading() -> None:
    events: list[TranscriptionProgress] = []
    reporter = ProgressReporter(events.append, total_seconds=100)

    reporter.emit_text("正在加载 Qwen3-ASR GGUF 模型")
    reporter.emit("transcribing", 0, "正在转录", 0)
    reporter.emit("transcribing", 1, "正在转录", 1)

    transcription_events = [event for event in events if event.stage == "transcribing"]
    assert [event.percent for event in transcription_events] == [0, 1]
