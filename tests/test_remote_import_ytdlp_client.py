from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

from src.remote_import.errors import RemoteImportErrorKind
from src.remote_import.ytdlp_client import YtDlpClient, is_bilibili_url, is_youtube_url, site_key_for_url


def test_cookie_file_for_bilibili_and_youtube(tmp_path: Path) -> None:
    (tmp_path / "bilibili_cookies.txt").write_text("# cookies", encoding="utf-8")
    (tmp_path / "youtube_cookies.txt").write_text("# cookies", encoding="utf-8")
    client = YtDlpClient(cookie_dir=tmp_path)

    bilibili_opts = client._build_options("https://www.bilibili.com/video/BVdemo", audio_only=True)
    youtube_opts = client._build_options("https://www.youtube.com/watch?v=demo", audio_only=True)

    assert bilibili_opts["cookiefile"] == str(tmp_path / "bilibili_cookies.txt")
    assert youtube_opts["cookiefile"] == str(tmp_path / "youtube_cookies.txt")


def test_missing_cookie_file_falls_back_without_cookiefile(tmp_path: Path) -> None:
    client = YtDlpClient(cookie_dir=tmp_path)

    opts = client._build_options("https://www.bilibili.com/video/BVdemo", audio_only=True)

    assert "cookiefile" not in opts


def test_download_audio_discards_stale_record_artifacts_before_retry(monkeypatch, tmp_path: Path) -> None:
    client = YtDlpClient(cookie_dir=tmp_path)
    (tmp_path / "remote_audio.m4a.part").write_bytes(b"partial")
    (tmp_path / "remote_audio.m4a.ytdl").write_bytes(b"resume metadata")
    (tmp_path / "remote_audio.m4a").write_bytes(b"unfinished final file")
    preserved_audio = tmp_path / "audio.wav"
    preserved_audio.write_bytes(b"normalized audio")
    captured_options: dict = {}

    class FakeYoutubeDL:
        def __init__(self, options: dict) -> None:
            captured_options.update(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def extract_info(self, _url: str, *, download: bool) -> None:
            assert download is True
            assert not (tmp_path / "remote_audio.m4a.part").exists()
            assert not (tmp_path / "remote_audio.m4a.ytdl").exists()
            assert not (tmp_path / "remote_audio.m4a").exists()
            assert preserved_audio.read_bytes() == b"normalized audio"
            (tmp_path / "remote_audio.webm").write_bytes(b"fresh audio")

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    info = SimpleNamespace(url="https://www.bilibili.com/video/BVdemo", webpage_url="")

    audio = client.download_audio(info, tmp_path)

    assert audio == tmp_path / "remote_audio.webm"
    assert captured_options["continuedl"] is False


def test_youtube_options_enable_ejs_defaults(tmp_path: Path) -> None:
    client = YtDlpClient(cookie_dir=tmp_path)

    opts = client._build_options("https://youtu.be/demo", skip_download=True)

    assert opts["js_runtimes"] == {"node": {"path": None}}
    assert opts["remote_components"] == {"ejs:github"}


def test_bilibili_options_do_not_enable_youtube_ejs(tmp_path: Path) -> None:
    client = YtDlpClient(cookie_dir=tmp_path)

    opts = client._build_options("https://www.bilibili.com/video/BVdemo", skip_download=True)

    assert "js_runtimes" not in opts
    assert "remote_components" not in opts
    assert opts["http_headers"]["Referer"] == "https://www.bilibili.com"


def test_site_detection() -> None:
    assert is_bilibili_url("https://b23.tv/abc")
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert site_key_for_url("https://youtu.be/abc") == "youtube"
    assert site_key_for_url("https://example.com/video") is None


def test_bilibili_412_error_mentions_cookie_path(tmp_path: Path) -> None:
    client = YtDlpClient(cookie_dir=tmp_path)

    error = client._remote_error_from_ytdlp_exception(
        "https://www.bilibili.com/video/BVdemo",
        RuntimeError("HTTP Error 412: Precondition Failed"),
    )

    assert error.kind == RemoteImportErrorKind.DOWNLOAD_FAILED
    assert "bilibili_cookies.txt" in error.detail


def test_youtube_challenge_error_mentions_ejs_and_cookie_path(tmp_path: Path) -> None:
    client = YtDlpClient(cookie_dir=tmp_path)

    error = client._remote_error_from_ytdlp_exception(
        "https://www.youtube.com/watch?v=demo",
        RuntimeError("n challenge solving failed. Requested format is not available"),
    )

    assert error.kind == RemoteImportErrorKind.DOWNLOAD_FAILED
    assert "youtube_cookies.txt" in error.detail
    assert "EJS" in error.detail
