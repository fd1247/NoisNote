from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.history.service import HistoryService
from src.remote_import.service import RemoteImportService
from src.remote_import.types import RemoteImportOptions, RemoteMediaInfo, RemoteSubtitle


class FakeClient:
    def __init__(self, subtitle_text: str | None = None, fail_subtitle: bool = False):
        self.subtitle_text = subtitle_text
        self.fail_subtitle = fail_subtitle

    def ensure_available(self) -> None:
        return None

    def probe(self, url: str) -> RemoteMediaInfo:
        return RemoteMediaInfo(
            url=url,
            extractor="youtube",
            webpage_url=url,
            title="Remote Demo",
            duration_seconds=60,
            video_id="demo",
            subtitles=[
                RemoteSubtitle("zh-CN", "中文", "https://example.com/sub.srt", "srt"),
            ]
            if self.subtitle_text is not None
            else [],
        )

    def download_subtitle(self, subtitle: RemoteSubtitle, target_path: Path) -> Path:
        if self.fail_subtitle:
            raise RuntimeError("subtitle download failed")
        target_path.write_text(self.subtitle_text or "", encoding="utf-8")
        return target_path

    def download_audio(self, info: RemoteMediaInfo, target_dir: Path) -> Path:
        audio = target_dir / "remote_audio.m4a"
        audio.write_bytes(b"fake audio")
        return audio


def test_remote_subtitle_import_creates_transcript_timeline_and_metadata(tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    client = FakeClient(
        "1\n00:00:00,000 --> 00:00:01,000\n你好\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n世界\n"
    )
    remote = RemoteImportService(service, client=client)
    info = client.probe("https://youtube.com/watch?v=demo")
    record = service.create_remote_record(info)

    result = remote.import_url(record, info, RemoteImportOptions(url=info.url))
    scanned = service.scan()[0]

    assert result.mode == "subtitle"
    assert scanned.has_transcript
    assert not scanned.audio_path.exists()
    assert scanned.external_subtitle_path.exists()
    assert service.read_transcript(scanned) == "你好\n世界"
    assert service.read_timeline(scanned)[0]["text"] == "你好"
    assert '"transcript_source": "external_subtitle"' in scanned.metadata_path.read_text(encoding="utf-8")


def test_remote_audio_import_falls_back_when_no_subtitle(monkeypatch, tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    client = FakeClient(subtitle_text=None)
    remote = RemoteImportService(service, client=client)
    info = client.probe("https://www.bilibili.com/video/BVdemo")
    record = service.create_remote_record(info)

    def fake_normalize(request, progress_callback=None, config=None):
        normalized = request.record_dir / "audio.normalized.wav"
        normalized.write_bytes(b"normalized")
        return SimpleNamespace(
            normalized_audio_path=normalized,
            duration_seconds=60.0,
            sample_rate=16000,
            channels=1,
            source_format="m4a",
        )

    monkeypatch.setattr("src.remote_import.service.normalize_audio", fake_normalize)

    result = remote.import_url(record, info, RemoteImportOptions(url=info.url))
    scanned = service.scan()[0]

    assert result.mode == "audio"
    assert scanned.audio_path.name == "audio.wav"
    assert scanned.audio_path.exists()
    assert scanned.audio_path.read_bytes() == b"normalized"
    assert not (scanned.record_dir / "audio.normalized.wav").exists()
    assert not (scanned.record_dir / "remote_audio.m4a").exists()
    assert scanned.source_kind == "remote_audio"


def test_remote_audio_import_falls_back_when_subtitle_download_fails(monkeypatch, tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    client = FakeClient(subtitle_text="1\n00:00:00,000 --> 00:00:01,000\n你好\n", fail_subtitle=True)
    remote = RemoteImportService(service, client=client)
    info = client.probe("https://youtube.com/watch?v=demo")
    record = service.create_remote_record(info)

    def fake_normalize(request, progress_callback=None, config=None):
        normalized = request.record_dir / "audio.normalized.wav"
        normalized.write_bytes(b"normalized")
        return SimpleNamespace(
            normalized_audio_path=normalized,
            duration_seconds=60.0,
            sample_rate=16000,
            channels=1,
            source_format="m4a",
        )

    monkeypatch.setattr("src.remote_import.service.normalize_audio", fake_normalize)

    result = remote.import_url(record, info, RemoteImportOptions(url=info.url))
    metadata_text = result.record.metadata_path.read_text(encoding="utf-8")

    assert result.mode == "audio"
    assert result.record.audio_path.exists()
    assert not (result.record.record_dir / "audio.normalized.wav").exists()
    assert not (result.record.record_dir / "remote_audio.m4a").exists()
    assert "subtitle_error" in metadata_text


def test_remote_audio_fallback_cleans_partial_subtitle_outputs(monkeypatch, tmp_path: Path) -> None:
    service = HistoryService(tmp_path)
    client = FakeClient("1\n00:00:00,000 --> 00:00:01,000\n你好\n")
    remote = RemoteImportService(service, client=client)
    info = client.probe("https://youtube.com/watch?v=demo")
    record = service.create_remote_record(info)

    def fail_save_timeline(*_args, **_kwargs):
        raise OSError("timeline write failed")

    def fake_normalize(request, progress_callback=None, config=None):
        normalized = request.record_dir / "audio.normalized.wav"
        normalized.write_bytes(b"normalized")
        return SimpleNamespace(
            normalized_audio_path=normalized,
            duration_seconds=60.0,
            sample_rate=16000,
            channels=1,
            source_format="m4a",
        )

    monkeypatch.setattr(service, "save_timeline", fail_save_timeline)
    monkeypatch.setattr("src.remote_import.service.normalize_audio", fake_normalize)

    result = remote.import_url(record, info, RemoteImportOptions(url=info.url))
    scanned = service.scan()[0]

    assert result.mode == "audio"
    assert scanned.audio_path.exists()
    assert not (scanned.record_dir / "audio.normalized.wav").exists()
    assert not (scanned.record_dir / "remote_audio.m4a").exists()
    assert not scanned.transcript_path.exists()
    assert not scanned.timeline_path.exists()
    assert not scanned.external_subtitle_path.exists()
