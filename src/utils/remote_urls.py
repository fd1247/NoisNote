"""远程视频链接规范化工具。"""
from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def canonicalize_video_url(value: object) -> str:
    """去掉常见视频站分享链接里的跟踪参数，保留可打开的视频页面。"""

    if not isinstance(value, str):
        return ""
    url = value.strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return url

    hostname = (parsed.hostname or "").lower()
    netloc = _safe_netloc(parsed)
    path = parsed.path.rstrip("/")
    if _is_bilibili_host(hostname):
        return urlunparse((parsed.scheme, netloc, path or "/", "", "", ""))

    if _is_youtube_host(hostname):
        return _canonical_youtube_url(parsed, path, netloc)

    return url


def _is_bilibili_host(hostname: str) -> bool:
    return _is_host_or_subdomain(hostname, "bilibili.com") or _is_host_or_subdomain(hostname, "bilibili.cn") or hostname == "b23.tv"


def _is_youtube_host(hostname: str) -> bool:
    return _is_host_or_subdomain(hostname, "youtube.com") or hostname == "youtu.be" or _is_host_or_subdomain(hostname, "youtube-nocookie.com")


def _is_host_or_subdomain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def _safe_netloc(parsed) -> str:
    hostname = parsed.hostname or ""
    if parsed.port is None:
        return hostname
    return f"{hostname}:{parsed.port}"


def _canonical_youtube_url(parsed, path: str, netloc: str) -> str:
    hostname = (parsed.hostname or "").lower()
    if hostname == "youtu.be":
        return urlunparse((parsed.scheme, netloc, path or "/", "", "", ""))

    if path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        query = urlencode({"v": video_id}) if video_id else ""
        return urlunparse((parsed.scheme, netloc, path, "", query, ""))

    return urlunparse((parsed.scheme, netloc, path or "/", "", "", ""))
