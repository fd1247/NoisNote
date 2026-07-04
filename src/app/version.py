"""
应用版本管理模块

定义和管理应用版本号，遵循语义化版本规范（SemVer）。
版本号格式：major.minor.patch[-pre_release]
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import total_ordering


@total_ordering
@dataclass(frozen=True)
class VersionInfo:
    """应用版本信息，遵循语义化版本规范"""

    major: int  # 主版本号
    minor: int  # 次版本号
    patch: int  # 修订号
    pre_release: str  # 预发布标识（如 "alpha", "beta", "rc1"），空字符串表示正式版

    def __str__(self) -> str:
        """返回版本字符串，如 "1.0.0" 或 "1.0.0-beta" """
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.pre_release:
            version = f"{version}-{self.pre_release}"
        return version

    @classmethod
    def parse(cls, version_str: str) -> VersionInfo:
        """从字符串解析版本号

        支持格式：
        - "1.0.0" -> VersionInfo(1, 0, 0, "")
        - "1.0.0-beta" -> VersionInfo(1, 0, 0, "beta")
        - "v1.0.0" -> VersionInfo(1, 0, 0, "")（自动去除 v 前缀）

        Args:
            version_str: 版本字符串

        Returns:
            VersionInfo 对象

        Raises:
            ValueError: 版本格式无效
        """
        # 去除 v 前缀
        s = version_str.strip()
        if s.startswith("v") or s.startswith("V"):
            s = s[1:]

        # 分离预发布标识
        pre_release = ""
        if "-" in s:
            parts = s.split("-", 1)
            s = parts[0]
            pre_release = parts[1]

        # 解析 major.minor.patch
        parts = s.split(".")
        if len(parts) != 3:
            raise ValueError(f"无效的版本格式: {version_str}")

        try:
            major = int(parts[0])
            minor = int(parts[1])
            patch = int(parts[2])
        except ValueError:
            raise ValueError(f"无效的版本格式: {version_str}")

        return cls(major=major, minor=minor, patch=patch, pre_release=pre_release)

    def __lt__(self, other: VersionInfo) -> bool:
        """版本比较，用于判断是否有新版本

        比较规则：
        1. 先比较 major.minor.patch 数值
        2. 有预发布标识的版本低于正式版（如 1.0.0-beta < 1.0.0）
        """
        if not isinstance(other, VersionInfo):
            return NotImplemented

        # 比较版本号数值
        self_tuple = (self.major, self.minor, self.patch)
        other_tuple = (other.major, other.minor, other.patch)

        if self_tuple != other_tuple:
            return self_tuple < other_tuple

        # 版本号相同，比较预发布标识
        # 有预发布标识 < 无预发布标识（正式版）
        if self.pre_release and not other.pre_release:
            return True
        if not self.pre_release and other.pre_release:
            return False

        # 都有预发布标识，按字典序比较
        return self.pre_release < other.pre_release

    def __eq__(self, other: object) -> bool:
        """判断版本是否相等"""
        if not isinstance(other, VersionInfo):
            return NotImplemented
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.patch == other.patch
            and self.pre_release == other.pre_release
        )


# 当前应用版本号，遵循语义化版本规范
APP_VERSION = VersionInfo(0, 3, 0, "")


def get_version_string() -> str:
    """获取版本字符串

    Returns:
        版本字符串，如 "0.1.0"
    """
    return str(APP_VERSION)


def get_version_tuple() -> tuple[int, int, int]:
    """获取版本元组（用于 Qt 应用版本）

    Returns:
        版本元组，如 (0, 1, 0)
    """
    return (APP_VERSION.major, APP_VERSION.minor, APP_VERSION.patch)
