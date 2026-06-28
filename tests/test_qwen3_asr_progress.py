from __future__ import annotations

import types
import wave
from pathlib import Path

from src.asr.runtime import (
    Qwen3AsrGgufProgress,
    Qwen3AsrGgufRuntime,
    Qwen3AsrGgufRuntimeConfig,
)
from src.asr.engine import ProgressReporter, TranscriptionProgress


def write_wav(path: Path, frames: int = 16000, rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\0\0" * frames)


def test_progress_reporter_maps_vendor_chunk_progress() -> None:
    events: list[TranscriptionProgress] = []
    reporter = ProgressReporter(events.append, total_seconds=120)

    reporter.emit_text(
        Qwen3AsrGgufProgress(
            stage="transcribing",
            current_chunk=1,
            total_chunks=3,
            processed_seconds=40,
            total_seconds=120,
            message="正在转录音频 1/3",
        )
    )
    reporter.emit_text(
        Qwen3AsrGgufProgress(
            stage="transcribing",
            current_chunk=3,
            total_chunks=3,
            processed_seconds=120,
            total_seconds=120,
            message="正在转录音频 3/3",
        )
    )

    assert [event.percent for event in events] == [41, 95]
    assert events[0].processed_seconds == 40


def test_runtime_passes_progress_callback_to_vendor_engine(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    tool_dir = tmp_path / "tool"
    model_dir = tmp_path / "model"
    write_wav(audio_path)
    tool_dir.mkdir()
    model_dir.mkdir()
    events: list[object] = []

    class FakeVendorEngine:
        def transcribe(self, **kwargs):
            kwargs["progress_callback"](
                Qwen3AsrGgufProgress(
                    stage="transcribing",
                    current_chunk=1,
                    total_chunks=1,
                    processed_seconds=1,
                    total_seconds=1,
                    message="正在转录音频 1/1",
                )
            )
            return types.SimpleNamespace(text="hello", performance={"decode_time": 0.1})

    runtime = Qwen3AsrGgufRuntime(
        Qwen3AsrGgufRuntimeConfig(
            model_dir=model_dir,
            model_name="Qwen3-ASR-0.6B-GGUF",
            model_size="0.6B",
            tool_dir=tool_dir,
        )
    )
    runtime.engine = FakeVendorEngine()

    result = runtime.transcribe(audio_path, events.append)

    assert result.text == "hello"
    chunk_events = [event for event in events if isinstance(event, Qwen3AsrGgufProgress)]
    assert chunk_events[0].current_chunk == 1
