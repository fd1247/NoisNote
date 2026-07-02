"""
发布脚本 - NoisNote

自动化 GitHub Release 发布流程：
1. 检查工作目录是否干净
2. 更新 version.py 和 file_version_info.txt 中的版本号
3. 提交版本号变更
4. 创建 Git tag
5. 推送到 GitHub
6. 执行 build.py 生成发布产物
7. 调用 gh CLI 创建 Release 并上传产物
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).parent.parent

# 配置
APP_NAME = "NoisNote"
VERSION_FILE = ROOT / "src" / "app" / "version.py"
BUILD_SCRIPT = ROOT / "scripts" / "build.py"
DIST_DIR = ROOT / "build" / "dist"
GITHUB_OWNER = "fd1247"
GITHUB_REPO = "NoisNote"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_command(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """执行命令并返回结果"""
    logger.info("执行命令: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def check_git_status() -> bool:
    """检查 Git 工作目录是否干净"""
    logger.info("检查 Git 工作目录状态...")

    returncode, stdout, stderr = run_command(["git", "status", "--porcelain"])
    if returncode != 0:
        logger.error("Git 状态检查失败: %s", stderr)
        return False

    if stdout.strip():
        logger.error("工作目录不干净，请先提交所有更改:\n%s", stdout)
        return False

    logger.info("工作目录干净")
    return True


def update_version_file(new_version: str) -> bool:
    """更新 version.py 中的版本号"""
    logger.info("更新版本号: %s", new_version)

    if not VERSION_FILE.exists():
        logger.error("版本文件不存在: %s", VERSION_FILE)
        return False

    content = VERSION_FILE.read_text(encoding="utf-8")

    # 解析版本号
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$", new_version)
    if not match:
        logger.error("无效的版本号格式: %s", new_version)
        return False

    major, minor, patch, pre_release = match.groups()
    pre_release = pre_release or ""

    # 更新 APP_VERSION 定义
    pattern = r"APP_VERSION = VersionInfo\(\d+, \d+, \d+, [^)]*\)"
    replacement = f"APP_VERSION = VersionInfo({major}, {minor}, {patch}, \"{pre_release}\")"

    new_content = re.sub(pattern, replacement, content)

    if new_content == content:
        logger.info("版本号已为 %s，无需更新", new_version)
    else:
        VERSION_FILE.write_text(new_content, encoding="utf-8")
        logger.info("版本号已更新")

    # 同步更新 file_version_info.txt（供 build.py / PyInstaller 使用）""
    _update_version_info_file(major, minor, patch, new_version)
    return True


VERSION_INFO_FILE = ROOT / "scripts" / "file_version_info.txt"


def _update_version_info_file(major: str, minor: str, patch: str, version_str: str) -> None:
    """更新 Windows exe 版本信息文件，与 version.py 保持同步。"""
    logger.info("更新版本信息文件: %s", VERSION_INFO_FILE)

    content = f"""# UTF-8
#
# NoisNote - Windows exe 版本信息
# 此文件由 build.py 自动生成，请勿手动编辑
#

VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, {patch}, 0),
    prodvers=({major}, {minor}, {patch}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'080404B0',
          [
            StringStruct(u'CompanyName', u'NoisNote'),
            StringStruct(u'FileDescription', u'NoisNote'),
            StringStruct(u'FileVersion', u'{version_str}'),
            StringStruct(u'InternalName', u'NoisNote'),
            StringStruct(u'OriginalFilename', u'NoisNote.exe'),
            StringStruct(u'ProductName', u'NoisNote'),
            StringStruct(u'ProductVersion', u'{version_str}'),
            StringStruct(u'LegalCopyright', u'Copyright (c) 2024 NoisNote'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""
    VERSION_INFO_FILE.write_text(content, encoding="utf-8")
    logger.info("版本信息文件已更新")


def commit_version_change(version: str) -> bool:
    """提交版本号变更"""
    logger.info("提交版本号变更...")

    # 添加版本文件
    returncode, stdout, stderr = run_command(
        ["git", "add", str(VERSION_FILE), str(VERSION_INFO_FILE)]
    )
    if returncode != 0:
        logger.error("git add 失败: %s", stderr)
        return False

    # 检查是否有待提交的变更
    returncode, stdout, stderr = run_command(["git", "diff", "--cached", "--quiet"])
    if returncode == 0:
        logger.info("版本号未变更，跳过提交")
        return True

    # 提交
    commit_message = f"chore: bump version to {version}"
    returncode, stdout, stderr = run_command(["git", "commit", "-m", commit_message])
    if returncode != 0:
        logger.error("git commit 失败: %s", stderr)
        return False

    logger.info("版本号变更已提交")
    return True


def create_git_tag(version: str) -> bool:
    """创建 Git tag"""
    tag_name = f"v{version}"
    logger.info("创建 Git tag: %s", tag_name)

    returncode, stdout, stderr = run_command(["git", "tag", tag_name])
    if returncode != 0:
        logger.error("git tag 失败: %s", stderr)
        return False

    logger.info("Git tag 已创建: %s", tag_name)
    return True


def push_to_github() -> bool:
    """推送到 GitHub"""
    logger.info("推送到 GitHub...")

    # 推送提交
    returncode, stdout, stderr = run_command(["git", "push", "origin", "master"])
    if returncode != 0:
        logger.error("git push 失败: %s", stderr)
        return False

    # 推送 tag
    returncode, stdout, stderr = run_command(["git", "push", "origin", "--tags"])
    if returncode != 0:
        logger.error("git push tags 失败: %s", stderr)
        return False

    logger.info("已推送到 GitHub")
    return True


def run_build() -> bool:
    """执行构建脚本"""
    logger.info("执行构建脚本...")

    returncode, stdout, stderr = run_command(
        [sys.executable, str(BUILD_SCRIPT)],
        cwd=ROOT,
    )

    if returncode != 0:
        logger.error("构建失败:\n%s", stderr)
        return False

    logger.info("构建完成")
    return True


def generate_release_notes(version: str) -> str:
    """生成 release notes 模板"""
    return f"NoisNote-{version}"


def create_github_release(version: str) -> bool:
    """创建 GitHub Release"""
    tag_name = f"v{version}"
    release_name = f"NoisNote-{version}"
    release_notes = generate_release_notes(version)

    logger.info("创建 GitHub Release: %s", release_name)

    # 检查 zip 文件是否存在
    zip_name = f"{APP_NAME}-{version}.zip"
    zip_path = DIST_DIR / zip_name
    sha256_path = DIST_DIR / f"{zip_name}.sha256"

    if not zip_path.exists():
        logger.error("zip 文件不存在: %s", zip_path)
        return False

    if not sha256_path.exists():
        logger.error("SHA256 文件不存在: %s", sha256_path)
        return False

    # 使用 gh CLI 创建 Release
    cmd = [
        "gh",
        "release",
        "create",
        tag_name,
        "--repo",
        f"{GITHUB_OWNER}/{GITHUB_REPO}",
        "--title",
        release_name,
        "--notes",
        release_notes,
        str(zip_path),
        str(sha256_path),
    ]

    returncode, stdout, stderr = run_command(cmd)
    if returncode != 0:
        logger.error("gh release create 失败: %s", stderr)
        return False

    logger.info("GitHub Release 已创建: %s", release_name)
    return True


def main() -> int:
    """主函数"""
    parser = argparse.ArgumentParser(
        description="NoisNote发布脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/release.py --version 0.1.0
  python scripts/release.py --version 0.2.0-beta --dry-run
        """,
    )
    parser.add_argument(
        "--version",
        required=True,
        help="版本号（如 0.1.0、0.2.0-beta）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅输出发布流程，不实际执行",
    )

    args = parser.parse_args()
    version = args.version

    logger.info("=" * 60)
    logger.info("开始发布流程: v%s", version)
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("[DRY RUN] 仅输出发布流程，不实际执行")
        logger.info("1. 检查 Git 工作目录状态")
        logger.info("2. 更新 version.py 和 file_version_info.txt: %s", version)
        logger.info("3. 提交版本号变更")
        logger.info("4. 创建 Git tag: v%s", version)
        logger.info("5. 推送到 GitHub")
        logger.info("6. 执行构建脚本")
        logger.info("7. 创建 GitHub Release 并上传产物")
        logger.info("=" * 60)
        logger.info("[DRY RUN] 发布流程预览完成")
        return 0

    # 步骤 1: 检查 Git 工作目录状态
    if not check_git_status():
        return 1

    # 步骤 2: 更新版本号
    if not update_version_file(version):
        return 1

    # 步骤 3: 提交版本号变更
    if not commit_version_change(version):
        return 1

    # 步骤 4: 创建 Git tag
    if not create_git_tag(version):
        return 1

    # 步骤 5: 推送到 GitHub
    if not push_to_github():
        return 1

    # 步骤 6: 执行构建脚本
    if not run_build():
        return 1

    # 步骤 7: 创建 GitHub Release
    if not create_github_release(version):
        return 1

    logger.info("=" * 60)
    logger.info("发布完成!")
    logger.info("版本: v%s", version)
    logger.info("GitHub Release: https://github.com/%s/%s/releases/tag/v%s",
                GITHUB_OWNER, GITHUB_REPO, version)
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
