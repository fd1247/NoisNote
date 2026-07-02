"""
构建脚本 - NoisNote

执行完整构建流程：
1. 读取版本号
2. 生成 file_version_info.txt
3. 调用 PyInstaller 执行打包
4. 创建 zip 压缩包
5. 生成 SHA256 校验文件
6. 输出构建结果
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# 项目根目录（build.py 在 scripts/ 下）
ROOT = Path(__file__).parent.parent

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(ROOT))

from src.app.version import get_version_string, get_version_tuple  # noqa: E402

# 配置
APP_NAME = "NoisNote"
BUILD_DIR = ROOT / "build"
DIST_DIR = BUILD_DIR / "dist"
OUTPUT_DIR = DIST_DIR / APP_NAME
ZIP_NAME = f"{APP_NAME}-{get_version_string()}.zip"
ZIP_PATH = DIST_DIR / ZIP_NAME
SHA256_NAME = f"{ZIP_NAME}.sha256"
SHA256_PATH = DIST_DIR / SHA256_NAME
SPEC_FILE = Path(__file__).parent / "build.spec"
VERSION_INFO_TEMPLATE = Path(__file__).parent / "file_version_info.txt"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def generate_version_info() -> None:
    """生成 Windows exe 版本信息文件"""
    logger.info("生成版本信息文件: %s", VERSION_INFO_TEMPLATE)

    version_tuple = get_version_tuple()
    version_str = get_version_string()

    content = f"""# UTF-8
#
# NoisNote - Windows exe 版本信息
# 此文件由 build.py 自动生成，请勿手动编辑
#

VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple + (0,)},
    prodvers={version_tuple + (0,)},
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

    VERSION_INFO_TEMPLATE.write_text(content, encoding="utf-8")
    logger.info("版本信息文件已生成")


def run_pyinstaller() -> bool:
    """执行 PyInstaller 打包"""
    logger.info("开始 PyInstaller 打包...")

    # 清理旧的构建目录
    if BUILD_DIR.exists():
        logger.info("清理构建目录: %s", BUILD_DIR)
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    if DIST_DIR.exists():
        logger.info("清理输出目录: %s", DIST_DIR)
        shutil.rmtree(DIST_DIR, ignore_errors=True)

    # 执行 PyInstaller，通过 --distpath/--workpath 指定绝对路径
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        str(SPEC_FILE),
    ]

    logger.info("执行命令: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("PyInstaller 输出:\n%s", result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error("PyInstaller 执行失败:\n%s", e.stderr)
        return False

    return True


def cleanup_build_output() -> None:
    """清理打包产物中不需要的文件，减小体积。"""
    if not OUTPUT_DIR.exists():
        return

    internal = OUTPUT_DIR / "_internal"
    if not internal.exists():
        return

    removed_size = 0

    # PySide6 精简
    pyside6 = internal / "PySide6"
    if pyside6.exists():
        # 删除 QML 相关（应用不用 QML）
        for name in ["resources", "qml"]:
            target = pyside6 / name
            if target.exists():
                removed_size += sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
                shutil.rmtree(target, ignore_errors=True)
                logger.info("已删除: PySide6/%s", name)

        # 删除软件 OpenGL 渲染器
        opengl = pyside6 / "opengl32sw.dll"
        if opengl.exists():
            removed_size += opengl.stat().st_size
            opengl.unlink(missing_ok=True)
            logger.info("已删除: PySide6/opengl32sw.dll")

        # 删除翻译文件，只保留中文
        translations = pyside6 / "translations"
        if translations.exists():
            for f in translations.iterdir():
                if f.is_file() and "zh_cn" not in f.name.lower():
                    removed_size += f.stat().st_size
                    f.unlink(missing_ok=True)
            # 如果目录空了就删除
            if not any(translations.iterdir()):
                translations.rmdir()
            logger.info("已清理: PySide6/translations（保留中文）")

    # 删除 vendor 内的日志目录（上游打包可能残留）
    vendor_logs = internal / "vendor" / "qwen3-asr-gguf" / "qwen_asr_gguf" / "inference" / "logs"
    if vendor_logs.exists():
        removed_size += sum(f.stat().st_size for f in vendor_logs.rglob("*") if f.is_file())
        shutil.rmtree(vendor_logs, ignore_errors=True)
        logger.info("已删除: vendor/qwen3-asr-gguf 日志目录")

    # 删除 PySide6 未使用的大型模块
    pyside6_dir = internal / "PySide6"
    if pyside6_dir.exists():
        # Qt6WebEngineCore.dll — Chromium 引擎（195 MB），本应用无 Web 功能
        webengine_core = pyside6_dir / "Qt6WebEngineCore.dll"
        if webengine_core.exists():
            removed_size += webengine_core.stat().st_size
            webengine_core.unlink(missing_ok=True)
            logger.info("已删除: PySide6/Qt6WebEngineCore.dll（WebEngine 引擎）")
        # QtWebEngineProcess.exe — WebEngine 子进程
        webengine_proc = pyside6_dir / "QtWebEngineProcess.exe"
        if webengine_proc.exists():
            removed_size += webengine_proc.stat().st_size
            webengine_proc.unlink(missing_ok=True)
            logger.info("已删除: PySide6/QtWebEngineProcess.exe")

    # 删除 OpenSSL 1.1 的 DLL（与主应用的 OpenSSL 3 冲突）
    # Python 3.12 使用 OpenSSL 3，残留的 OpenSSL 1.1 DLL 会导致 _ssl 模块加载失败
    openssl11_files = [
        internal / "libcrypto-1_1-x64.dll",
        internal / "libssl-1_1-x64.dll",
    ]
    for dll_path in openssl11_files:
        if dll_path.exists():
            removed_size += dll_path.stat().st_size
            dll_path.unlink(missing_ok=True)
            logger.info("已删除: %s（OpenSSL 1.1 残留）", dll_path.name)

    if removed_size > 0:
        logger.info("共清理 %.1f MB", removed_size / (1024 * 1024))


def create_zip_archive() -> bool:
    """创建 zip 压缩包"""
    if not OUTPUT_DIR.exists():
        logger.error("输出目录不存在: %s", OUTPUT_DIR)
        return False

    logger.info("创建 zip 压缩包: %s", ZIP_PATH)

    try:
        with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in OUTPUT_DIR.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(DIST_DIR)
                    zf.write(file_path, arcname)

        # 检查 zip 文件大小
        zip_size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
        logger.info("zip 文件大小: %.2f MB", zip_size_mb)

        if zip_size_mb > 300:
            logger.warning("zip 文件超过 300MB 限制!")

        return True
    except Exception as e:
        logger.error("创建 zip 失败: %s", e)
        return False


def generate_sha256_checksum() -> bool:
    """生成 SHA256 校验文件"""
    if not ZIP_PATH.exists():
        logger.error("zip 文件不存在: %s", ZIP_PATH)
        return False

    logger.info("生成 SHA256 校验文件: %s", SHA256_PATH)

    try:
        sha256_hash = hashlib.sha256()
        with open(ZIP_PATH, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        checksum = sha256_hash.hexdigest()
        SHA256_PATH.write_text(f"{checksum}  {ZIP_NAME}\n", encoding="utf-8")

        logger.info("SHA256 校验和: %s", checksum)
        return True
    except Exception as e:
        logger.error("生成 SHA256 失败: %s", e)
        return False


def verify_build() -> bool:
    """验证构建结果"""
    logger.info("验证构建结果...")

    # 检查输出目录
    if not OUTPUT_DIR.exists():
        logger.error("输出目录不存在: %s", OUTPUT_DIR)
        return False

    # 检查可执行文件
    exe_path = OUTPUT_DIR / f"{APP_NAME}.exe"
    if not exe_path.exists():
        logger.error("可执行文件不存在: %s", exe_path)
        return False

    # 检查内部目录
    internal_dir = OUTPUT_DIR / "_internal"
    if not internal_dir.exists():
        logger.error("内部目录不存在: %s", internal_dir)
        return False

    # 检查 zip 文件
    if not ZIP_PATH.exists():
        logger.error("zip 文件不存在: %s", ZIP_PATH)
        return False

    # 检查 SHA256 文件
    if not SHA256_PATH.exists():
        logger.error("SHA256 文件不存在: %s", SHA256_PATH)
        return False

    # 统计文件数量
    file_count = sum(1 for _ in OUTPUT_DIR.rglob("*") if _.is_file())
    logger.info("输出目录文件数量: %d", file_count)

    # 统计目录大小
    total_size = sum(f.stat().st_size for f in OUTPUT_DIR.rglob("*") if f.is_file())
    total_size_mb = total_size / (1024 * 1024)
    logger.info("输出目录大小: %.2f MB", total_size_mb)

    logger.info("构建验证通过!")
    return True


def main() -> int:
    """主函数"""
    start_time = time.time()
    logger.info("=" * 60)
    logger.info("开始构建 %s v%s", APP_NAME, get_version_string())
    logger.info("=" * 60)

    # 步骤 1: 生成版本信息
    generate_version_info()

    # 步骤 2: 执行 PyInstaller
    if not run_pyinstaller():
        logger.error("PyInstaller 打包失败")
        return 1

    # 步骤 2.5: 清理不需要的文件
    cleanup_build_output()

    # 步骤 3: 创建 zip 压缩包
    if not create_zip_archive():
        logger.error("创建 zip 失败")
        return 1

    # 步骤 4: 生成 SHA256 校验文件
    if not generate_sha256_checksum():
        logger.error("生成 SHA256 失败")
        return 1

    # 步骤 5: 验证构建结果
    if not verify_build():
        logger.error("构建验证失败")
        return 1

    logger.info("=" * 60)
    logger.info("构建完成!")
    logger.info("输出目录: %s", OUTPUT_DIR)
    logger.info("zip 文件: %s", ZIP_PATH)
    logger.info("SHA256 文件: %s", SHA256_PATH)
    logger.info("=" * 60)

    elapsed = time.time() - start_time
    logger.info("构建耗时: %.2f 秒 (%.1f 分钟)", elapsed, elapsed / 60)
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
