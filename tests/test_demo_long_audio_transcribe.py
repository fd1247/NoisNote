from __future__ import annotations

import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import demo_long_audio_transcribe as demo


def test_audio_info_from_ffprobe_extracts_audio_stream(tmp_path: Path) -> None:
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(b"fake")
    payload = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264"},
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "sample_rate": "44100",
                "channels": 2,
                "duration": "123.45",
            },
        ],
        "format": {
            "format_name": "mp3",
            "size": "4567",
            "bit_rate": "128000",
        },
    }

    info = demo.audio_info_from_ffprobe(payload, audio)

    assert info.codec_name == "mp3"
    assert info.duration_seconds == pytest.approx(123.45)
    assert info.sample_rate == 44100
    assert info.channels == 2
    assert info.size_bytes == 4567
    assert info.bit_rate == 128000


def test_parse_vad_result_supports_funasr_value_shape() -> None:
    result = [{"key": "audio", "value": [[100, 900], [1200, 2500]]}]

    assert demo.parse_vad_result(result) == [(100, 900), (1200, 2500)]


def test_parse_vad_result_supports_dict_segments_shape() -> None:
    result = {"segments": [{"start_ms": 100, "end_ms": 900}, {"start": 1500, "end": 2800}]}

    assert demo.parse_vad_result(result) == [(100, 900), (1500, 2800)]


def test_build_segments_pads_merges_and_splits_long_segments() -> None:
    segments = demo.build_segments(
        raw_segments=[(1000, 10_000), (10_300, 20_000), (40_000, 105_000)],
        duration_seconds=120,
        padding_ms=500,
        merge_gap_ms=1000,
        max_segment_ms=30_000,
    )

    assert [(item.start_ms, item.end_ms) for item in segments] == [
        (500, 20_500),
        (39_500, 69_500),
        (69_500, 99_500),
        (99_500, 105_500),
    ]
    assert [item.index for item in segments] == [1, 2, 3, 4]


def test_build_segments_prefers_quiet_split_point(tmp_path: Path) -> None:
    wav_path = tmp_path / "normalized.wav"
    sample_rate = 1000
    samples = []
    for index in range(70_000):
        if 54_800 <= index <= 55_400:
            samples.append(0)
        else:
            samples.append(1000)
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples))

    segments = demo.build_segments(
        raw_segments=[(0, 70_000)],
        duration_seconds=70,
        padding_ms=0,
        merge_gap_ms=0,
        max_segment_ms=60_000,
        normalized_path=wav_path,
        quiet_search_window_ms=10_000,
    )

    assert len(segments) == 2
    assert 54_700 <= segments[0].end_ms <= 55_500
    assert segments[1].start_ms == segments[0].end_ms


def test_build_fixed_segments_uses_duration_limit() -> None:
    segments = demo.build_fixed_segments(duration_seconds=125, chunk_seconds=60)

    assert segments == [(0, 60_000), (60_000, 120_000), (120_000, 125_000)]


def test_cut_chunks_invokes_ffmpeg_for_each_segment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run_command(args: list[str], timeout: int | None = None):
        calls.append(args)
        Path(args[-1]).write_bytes(b"wav")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(demo, "run_command", fake_run_command)

    source = tmp_path / "normalized.wav"
    source.write_bytes(b"source")
    segments = [
        demo.Segment(index=1, start_ms=0, end_ms=1000),
        demo.Segment(index=2, start_ms=1000, end_ms=2500),
    ]

    updated = demo.cut_chunks(source, segments, tmp_path / "chunks")

    assert len(calls) == 2
    assert calls[0][0] == "ffmpeg"
    assert calls[0][calls[0].index("-ss") + 1] == "0.000"
    assert calls[1][calls[1].index("-to") + 1] == "2.500"
    assert all(Path(item.chunk_file).exists() for item in updated)


def test_normalize_audio_can_clip_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run_command(args: list[str], timeout: int | None = None):
        calls.append(args)
        Path(args[-1]).write_bytes(b"wav")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(demo, "run_command", fake_run_command)

    output = demo.normalize_audio(tmp_path / "source.mp3", tmp_path / "normalized.wav", clip_seconds=180)

    assert output.exists()
    assert "-t" in calls[0]
    assert calls[0][calls[0].index("-t") + 1] == "180"


def test_write_transcripts_creates_timestamped_and_plain_files(tmp_path: Path) -> None:
    results = [
        demo.SegmentResult(1, 0, 1000, "chunk_0001.wav", "第一段"),
        demo.SegmentResult(2, 1000, 2000, "chunk_0002.wav", "", error="失败"),
        demo.SegmentResult(3, 2000, 3000, "chunk_0003.wav", "第三段"),
    ]

    demo.write_transcripts(tmp_path, results)

    assert "[00:00:00 - 00:00:01]" in (tmp_path / "transcript.txt").read_text(encoding="utf-8")
    assert "转录失败：失败" in (tmp_path / "transcript.txt").read_text(encoding="utf-8")
    assert (tmp_path / "transcript_plain.txt").read_text(encoding="utf-8") == "第一段\n第三段"


def test_dry_run_pipeline_with_mocked_external_steps(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake mp3")
    output_dir = tmp_path / "out"

    monkeypatch.setattr(
        demo,
        "parse_args",
        lambda: SimpleNamespace(
            audio=str(audio),
            model="iic/SenseVoiceSmall",
            model_path="",
            device="cpu",
            output_dir=str(output_dir),
            max_audio_seconds=3600,
            max_segment_ms=30_000,
            padding_ms=500,
            merge_gap_ms=800,
            coarse_chunk_seconds=600,
            quiet_search_window_ms=15_000,
            limit_segments=0,
            clip_seconds=0,
            reuse_normalized=False,
            reuse_chunks=False,
            keep_chunks=True,
            dry_run=True,
        ),
    )
    monkeypatch.setattr(
        demo,
        "probe_audio",
        lambda path: demo.AudioInfo(
            path=str(path),
            format_name="mp3",
            duration_seconds=10,
            size_bytes=100,
            bit_rate=128000,
            codec_name="mp3",
            sample_rate=44100,
            channels=2,
        ),
    )
    monkeypatch.setattr(
        demo,
        "normalize_audio",
        lambda source, target, reuse=False, clip_seconds=0: target.write_bytes(b"wav") or target,
    )
    monkeypatch.setattr(demo, "run_funasr_vad", lambda source, max_segment_ms: [(1000, 3000), (3500, 6000)])
    monkeypatch.setattr(
        demo,
        "cut_chunks",
        lambda source, segments, chunks_dir, reuse=False: [
            demo.Segment(item.index, item.start_ms, item.end_ms, str(chunks_dir / f"chunk_{item.index:04d}.wav"))
            for item in segments
        ],
    )

    assert demo.main() == 0

    segments = json.loads((output_dir / "segments.json").read_text(encoding="utf-8"))
    assert len(segments) == 1
    assert segments[0]["start_ms"] == 500
    assert segments[0]["end_ms"] == 6500
