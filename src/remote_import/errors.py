"""远程导入错误分类。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RemoteImportErrorKind(str, Enum):
    """用户可理解的远程导入错误类型。"""

    UNSUPPORTED_SITE = "unsupported_site"
    LOGIN_REQUIRED = "login_required"
    NETWORK_TIMEOUT = "network_timeout"
    DOWNLOAD_FAILED = "download_failed"
    FFMPEG_FAILED = "ffmpeg_failed"
    FILE_TOO_LARGE = "file_too_large"
    YTDLP_MISSING = "ytdlp_missing"
    INVALID_URL = "invalid_url"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RemoteImportError(RuntimeError):
    """远程导入失败。"""

    kind: RemoteImportErrorKind
    message: str
    detail: str = ""

    def __str__(self) -> str:
        return self.message

    def to_metadata(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "details": self.detail or self.message,
        }


def classify_error_text(text: object) -> RemoteImportErrorKind:
    """把 yt-dlp/网络/转码错误文本归入固定类型。"""
    value = str(text or "").lower()
    if any(marker in value for marker in ("unsupported url", "no suitable extractor", "unsupported site")):
        return RemoteImportErrorKind.UNSUPPORTED_SITE
    if any(marker in value for marker in ("login", "sign in", "private", "members-only", "premium", "需要登录", "会员")):
        return RemoteImportErrorKind.LOGIN_REQUIRED
    if any(marker in value for marker in ("timed out", "timeout", "read timed out", "connection aborted", "网络超时")):
        return RemoteImportErrorKind.NETWORK_TIMEOUT
    if any(marker in value for marker in ("file too large", "too large", "exceeds", "文件太大")):
        return RemoteImportErrorKind.FILE_TOO_LARGE
    if any(marker in value for marker in ("ffmpeg", "ffprobe", "transcode", "转码")):
        return RemoteImportErrorKind.FFMPEG_FAILED
    if any(marker in value for marker in ("download", "http error", "unable to download", "下载")):
        return RemoteImportErrorKind.DOWNLOAD_FAILED
    return RemoteImportErrorKind.UNKNOWN


def message_for_kind(kind: RemoteImportErrorKind) -> str:
    """返回用户界面显示文案。"""
    return {
        RemoteImportErrorKind.UNSUPPORTED_SITE: "不支持的网站",
        RemoteImportErrorKind.LOGIN_REQUIRED: "需要登录",
        RemoteImportErrorKind.NETWORK_TIMEOUT: "网络超时",
        RemoteImportErrorKind.DOWNLOAD_FAILED: "下载失败",
        RemoteImportErrorKind.FFMPEG_FAILED: "ffmpeg 转码失败",
        RemoteImportErrorKind.FILE_TOO_LARGE: "文件太大",
        RemoteImportErrorKind.YTDLP_MISSING: "缺少 yt-dlp，请先安装依赖",
        RemoteImportErrorKind.INVALID_URL: "请输入有效的视频链接",
        RemoteImportErrorKind.UNKNOWN: "链接导入失败",
    }[kind]


def remote_error_from_exception(exc: Exception) -> RemoteImportError:
    """把未知异常归一化为远程导入错误。"""
    if isinstance(exc, RemoteImportError):
        return exc
    kind = classify_error_text(exc)
    return RemoteImportError(kind, message_for_kind(kind), str(exc))
