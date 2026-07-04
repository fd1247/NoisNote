"""yt-dlp 适配层。"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.request import urlopen

from ..app.config import DEFAULT_DATA_ROOT
from .errors import RemoteImportError, RemoteImportErrorKind, message_for_kind, remote_error_from_exception
from .types import RemoteMediaInfo, RemoteSubtitle


COOKIE_FILENAMES = {
    "bilibili": "bilibili_cookies.txt",
    "youtube": "youtube_cookies.txt",
}


class YtDlpClient:
    """封装 yt-dlp，方便测试中替换。"""

    def __init__(self, *, cookie_dir: Path | None = None):
        self.cookie_dir = Path(cookie_dir) if cookie_dir else DEFAULT_DATA_ROOT

    def ensure_available(self) -> None:
        try:
            import yt_dlp  # noqa: F401
        except ImportError as exc:
            raise RemoteImportError(
                RemoteImportErrorKind.YTDLP_MISSING,
                message_for_kind(RemoteImportErrorKind.YTDLP_MISSING),
                str(exc),
            ) from exc

    def probe(self, url: str) -> RemoteMediaInfo:
        self.ensure_available()
        try:
            import yt_dlp

            with yt_dlp.YoutubeDL(self._build_options(url, skip_download=True)) as ydl:
                data = ydl.extract_info(url, download=False)
        except Exception as exc:
            raise self._remote_error_from_ytdlp_exception(url, exc) from exc
        if not isinstance(data, dict):
            raise RemoteImportError(RemoteImportErrorKind.UNKNOWN, "链接导入失败", "yt-dlp did not return metadata")
        return _media_info_from_ytdlp(url, data)

    def download_subtitle(self, subtitle: RemoteSubtitle, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        source_url = subtitle.url
        if not source_url:
            raise RemoteImportError(RemoteImportErrorKind.DOWNLOAD_FAILED, "下载失败", "empty subtitle url")
        try:
            with urlopen(source_url, timeout=60) as response:  # nosec B310
                target_path.write_bytes(response.read())
        except Exception as exc:
            raise remote_error_from_exception(exc) from exc
        return target_path

    def download_audio(self, info: RemoteMediaInfo, target_dir: Path) -> Path:
        self.ensure_available()
        target_dir.mkdir(parents=True, exist_ok=True)
        before = {path.resolve(strict=False) for path in target_dir.glob("*") if path.is_file()}
        outtmpl = str(target_dir / "remote_audio.%(ext)s")
        try:
            import yt_dlp

            with yt_dlp.YoutubeDL(self._build_options(info.webpage_url or info.url, outtmpl=outtmpl, audio_only=True)) as ydl:
                ydl.extract_info(info.webpage_url or info.url, download=True)
        except Exception as exc:
            raise self._remote_error_from_ytdlp_exception(info.webpage_url or info.url, exc) from exc

        candidates = [
            path
            for path in target_dir.glob("remote_audio.*")
            if path.is_file() and path.resolve(strict=False) not in before
        ]
        if not candidates:
            candidates = [path for path in target_dir.glob("remote_audio.*") if path.is_file()]
        if not candidates:
            raise RemoteImportError(RemoteImportErrorKind.DOWNLOAD_FAILED, "下载失败", "audio file was not created")
        return max(candidates, key=lambda item: item.stat().st_mtime)

    def _build_options(
        self,
        url: str,
        *,
        skip_download: bool = False,
        outtmpl: str | None = None,
        audio_only: bool = False,
    ) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "http_headers": _http_headers_for_url(url),
        }
        if skip_download:
            opts["skip_download"] = True
        if outtmpl:
            opts["outtmpl"] = outtmpl
        if audio_only:
            opts["format"] = "bestaudio/best"

        cookie_file = self.cookie_file_for_url(url)
        if cookie_file:
            opts["cookiefile"] = str(cookie_file)

        if is_youtube_url(url):
            opts["js_runtimes"] = {"node": {"path": None}}
            opts["remote_components"] = {"ejs:github"}

        return opts

    def cookie_file_for_url(self, url: str) -> Path | None:
        site = site_key_for_url(url)
        if not site:
            return None
        path = self.cookie_dir / COOKIE_FILENAMES[site]
        return path if path.exists() and path.is_file() else None

    def _remote_error_from_ytdlp_exception(self, url: str, exc: Exception) -> RemoteImportError:
        message = str(exc)
        lower = message.lower()
        if is_bilibili_url(url) and "412" in lower:
            detail = (
                "Bilibili 返回 HTTP 412，通常是缺少或 cookies 已失效。"
                f"请把 Netscape 格式 cookies 保存为 {self.cookie_dir / COOKIE_FILENAMES['bilibili']} 后重试。"
                f"原始错误：{message}"
            )
            return RemoteImportError(RemoteImportErrorKind.DOWNLOAD_FAILED, message_for_kind(RemoteImportErrorKind.DOWNLOAD_FAILED), detail)
        if is_youtube_url(url) and (
            "n challenge" in lower
            or "only images are available" in lower
            or "requested format is not available" in lower
        ):
            detail = (
                "YouTube 音视频格式不可用，通常是 n challenge 解算失败。"
                "源码运行请确保 Node.js >= 22 可用，且网络可访问 yt-dlp 的 ejs:github 远程组件；"
                "也可以运行 python -m pip install -U \"yt-dlp[default]\" 安装本地 EJS。"
                f"如果视频需要登录，请把 Netscape 格式 cookies 保存为 {self.cookie_dir / COOKIE_FILENAMES['youtube']}。"
                f"原始错误：{message}"
            )
            return RemoteImportError(RemoteImportErrorKind.DOWNLOAD_FAILED, message_for_kind(RemoteImportErrorKind.DOWNLOAD_FAILED), detail)
        if is_youtube_url(url) and any(marker in lower for marker in ("sign in", "login", "cookies")):
            detail = (
                "YouTube 需要登录或 cookies 无效。"
                f"请把 Netscape 格式 cookies 保存为 {self.cookie_dir / COOKIE_FILENAMES['youtube']} 后重试。"
                f"原始错误：{message}"
            )
            return RemoteImportError(RemoteImportErrorKind.LOGIN_REQUIRED, message_for_kind(RemoteImportErrorKind.LOGIN_REQUIRED), detail)
        return remote_error_from_exception(exc)


def site_key_for_url(url: str) -> str | None:
    if is_bilibili_url(url):
        return "bilibili"
    if is_youtube_url(url):
        return "youtube"
    return None


def is_bilibili_url(url: str) -> bool:
    value = url.lower()
    return "bilibili.com" in value or "b23.tv" in value or "bilibili.cn" in value


def is_youtube_url(url: str) -> bool:
    value = url.lower()
    return "youtube.com" in value or "youtu.be" in value


def _http_headers_for_url(url: str) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/137.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if is_bilibili_url(url):
        headers["Referer"] = "https://www.bilibili.com"
    return headers


def _media_info_from_ytdlp(url: str, data: dict) -> RemoteMediaInfo:
    return RemoteMediaInfo(
        url=url,
        extractor=str(data.get("extractor") or data.get("extractor_key") or ""),
        webpage_url=str(data.get("webpage_url") or data.get("original_url") or url),
        title=str(data.get("title") or data.get("fulltitle") or "远程视频"),
        duration_seconds=_float_or_none(data.get("duration")),
        video_id=str(data.get("id") or ""),
        subtitles=_subtitles_from_mapping(data.get("subtitles"), is_auto=False),
        automatic_captions=_subtitles_from_mapping(data.get("automatic_captions"), is_auto=True),
    )


def _subtitles_from_mapping(value: object, *, is_auto: bool) -> list[RemoteSubtitle]:
    if not isinstance(value, dict):
        return []
    items: list[RemoteSubtitle] = []
    for language, formats in value.items():
        if not isinstance(formats, list):
            continue
        for item in formats:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            extension = str(item.get("ext") or item.get("extension") or "vtt").lower()
            if not url:
                continue
            items.append(
                RemoteSubtitle(
                    language=str(language),
                    name=str(item.get("name") or language),
                    url=url,
                    extension=extension,
                    is_auto=is_auto,
                )
            )
    return items


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
