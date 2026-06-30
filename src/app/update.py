"""
版本检查模块

检查 GitHub Releases 最新版本，提供更新提示。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import httpx
from PySide6.QtCore import QThread, Signal

from .version import VersionInfo

logger = logging.getLogger(__name__)

# GitHub 仓库信息
GITHUB_OWNER = "fd1247"
GITHUB_REPO = "NoisNote"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# 缓存过期时间（秒）
CACHE_TTL = 3600  # 1 小时


@dataclass
class UpdateInfo:
    """版本检查结果"""

    has_update: bool  # 是否有新版本
    latest_version: str  # 最新版本号
    current_version: str  # 当前版本号
    download_url: str  # 下载页面 URL
    release_notes: str  # 更新说明
    check_time: datetime  # 检查时间


class UpdateCheckWorker(QThread):
    """后台线程执行版本检查"""

    # 信号：检查完成时发出
    update_checked = Signal(object)  # UpdateInfo

    def __init__(self, current_version: VersionInfo, parent=None):
        super().__init__(parent)
        self.current_version = current_version

    def run(self):
        """执行版本检查"""
        try:
            result = check_for_update_sync(self.current_version)
            self.update_checked.emit(result)
        except Exception as e:
            logger.error("版本检查失败: %s", e)
            # 发送无更新的结果
            self.update_checked.emit(UpdateInfo(
                has_update=False,
                latest_version=str(self.current_version),
                current_version=str(self.current_version),
                download_url="",
                release_notes="",
                check_time=datetime.now(timezone.utc),
            ))


# 缓存
_cache: UpdateInfo | None = None
_cache_time: datetime | None = None


def check_for_update_sync(current_version: VersionInfo) -> UpdateInfo:
    """同步检查更新

    Args:
        current_version: 当前版本号

    Returns:
        UpdateInfo 对象
    """
    global _cache, _cache_time

    # 检查缓存
    now = datetime.now(timezone.utc)
    if _cache is not None and _cache_time is not None:
        elapsed = (now - _cache_time).total_seconds()
        if elapsed < CACHE_TTL:
            logger.debug("使用缓存的版本检查结果，剩余 %.0f 秒", CACHE_TTL - elapsed)
            return _cache

    try:
        # 请求 GitHub API
        logger.info("检查新版本，当前版本: %s", current_version)
        with httpx.Client(timeout=10.0) as client:
            response = client.get(GITHUB_API_URL)
            response.raise_for_status()
            data = response.json()

        # 解析版本号
        tag_name = data.get("tag_name", "")
        latest_version_str = tag_name.lstrip("vV")
        latest_version = VersionInfo.parse(latest_version_str)

        # 比较版本
        has_update = latest_version > current_version

        # 构建下载 URL
        html_url = data.get("html_url", "")
        download_url = html_url if html_url else f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

        # 获取更新说明
        release_notes = data.get("body", "暂无更新说明")

        result = UpdateInfo(
            has_update=has_update,
            latest_version=str(latest_version),
            current_version=str(current_version),
            download_url=download_url,
            release_notes=release_notes,
            check_time=now,
        )

        # 更新缓存
        _cache = result
        _cache_time = now

        if has_update:
            logger.info("发现新版本: %s -> %s", current_version, latest_version)
        else:
            logger.info("已是最新版本: %s", current_version)

        return result

    except Exception as e:
        logger.warning("检查更新失败: %s", e)
        return UpdateInfo(
            has_update=False,
            latest_version=str(current_version),
            current_version=str(current_version),
            download_url="",
            release_notes="",
            check_time=now,
        )


def check_for_update_async(
    current_version: VersionInfo,
    callback: Callable[[UpdateInfo], None],
) -> UpdateCheckWorker:
    """异步检查更新

    Args:
        current_version: 当前版本号
        callback: 检查完成后的回调函数

    Returns:
        UpdateCheckWorker 对象（需要保持引用以防止被垃圾回收）
    """
    worker = UpdateCheckWorker(current_version)
    worker.update_checked.connect(callback)
    worker.start()
    return worker
