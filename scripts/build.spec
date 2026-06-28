# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec 文件 - 音频转录与总结工具

打包配置：
- 目录模式（onedir），启动快、兼容性好
- 精简依赖，只打包必要的模块
- 包含 ffmpeg/ffprobe
- 包含 GGUF 推理工具（不含模型文件）
"""

import os
import sys
from pathlib import Path

# 项目根目录（build.spec 在 scripts/ 下）
ROOT = Path(SPECPATH).parent

# 版本信息
sys.path.insert(0, str(ROOT))
from audio_recorder.app.version import get_version_string, get_version_tuple

# 应用配置
APP_NAME = "AudioRecorder"
APP_VERSION = get_version_string()
APP_VERSION_TUPLE = get_version_tuple()

# 路径配置
ENTRY_POINT = str(ROOT / "main.py")
ICON_PATH = str(ROOT / "audio_recorder" / "assets" / "icon.ico")
FFMPEG_DIR = str(ROOT / "vendor" / "ffmpeg")
VENDOR_QWEN = str(ROOT / "vendor" / "qwen3-asr-gguf")

# Windows exe 版本信息
VERSION_INFO_PATH = str(ROOT / "file_version_info.txt")

# ============================================================
# 使用 PyInstaller 标准 hook 收集依赖
# ============================================================
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_all

# PySide6 - 让 PyInstaller 自己处理，通过 excludes 排除不需要的模块
pyside6_datas = collect_data_files("PySide6")
pyside6_binaries = collect_dynamic_libs("PySide6")

# numpy、scipy、onnxruntime、soundfile
numpy_datas, numpy_binaries, numpy_hiddenimports = collect_all("numpy")
scipy_datas, scipy_binaries, scipy_hiddenimports = collect_all("scipy")
onnxruntime_datas, onnxruntime_binaries, onnxruntime_hiddenimports = collect_all("onnxruntime")
soundfile_datas, soundfile_binaries, soundfile_hiddenimports = collect_all("soundfile")

# ============================================================
# 过滤不需要的文件
# ============================================================

# 需要排除的 PySide6 目录前缀（相对于 PySide6 包目录）
_PYSIDE6_EXCLUDE_DIRS = {
    "resources",      # QML 资源（字体、样式、控件库）
    "qml",            # QML 模块
    "translations",   # 多语言翻译（下面单独保留中文）
}

# 需要排除的二进制文件名
_PYSIDE6_EXCLUDE_BINARIES = {
    "opengl32sw.dll",       # Mesa 软件 OpenGL 渲染器
}

# 需要排除的翻译文件（保留 zh_CN）
def _should_keep_translation(path_str: str) -> bool:
    if "/translations/" not in path_str and "\\translations\\" not in path_str:
        return True  # 不是翻译文件，保留
    return "zh_CN" in path_str  # 只保留中文翻译

def _filter_pyside6_datas(datas):
    """过滤 PySide6 数据文件，排除不需要的目录和翻译。"""
    filtered = []
    for src, dst in datas:
        # 检查是否在排除目录中
        skip = False
        for excl in _PYSIDE6_EXCLUDE_DIRS:
            if f"/{excl}/" in dst or f"\\{excl}\\" in dst:
                if excl == "translations":
                    # 翻译目录只保留中文
                    if not _should_keep_translation(dst):
                        skip = True
                else:
                    skip = True
                break
        if not skip:
            filtered.append((src, dst))
    return filtered

def _filter_pyside6_binaries(binaries):
    """过滤 PySide6 二进制，排除不需要的 DLL。"""
    filtered = []
    for item in binaries:
        src = item[0]
        filename = Path(src).name.lower()
        if filename in {n.lower() for n in _PYSIDE6_EXCLUDE_BINARIES}:
            continue
        filtered.append(item)
    return filtered

# 需要排除的包（整包移除）
_EXCLUDE_PACKAGES = {
    "llvmlite",       # Numba/LLVM，应用未使用
    "Pythonwin",      # pywin32 COM 扩展
    "lxml",           # XML 解析，未使用
    "mypy",           # 静态类型检查工具
    "cryptography",   # 加密库，运行时用系统 SSL
    "Cython",         # 编译器，运行时不需要
    "zstandard",      # 压缩库，未使用
}

def _filter_binaries_by_package(binaries):
    """过滤二进制，排除整包不需要的库。"""
    filtered = []
    for item in binaries:
        src = item[0]
        src_lower = src.lower().replace("\\", "/")
        skip = False
        for pkg in _EXCLUDE_PACKAGES:
            if f"/{pkg.lower()}/" in src_lower or f"/{pkg.lower()}." in src_lower:
                skip = True
                break
        if not skip:
            filtered.append(item)
    return filtered

def _filter_datas_by_package(datas):
    """过滤数据文件，排除整包不需要的库。"""
    filtered = []
    for src, dst in datas:
        dst_lower = dst.lower().replace("\\", "/")
        skip = False
        for pkg in _EXCLUDE_PACKAGES:
            if f"/{pkg.lower()}/" in dst_lower or f"/{pkg.lower()}." in dst_lower:
                skip = True
                break
        if not skip:
            filtered.append((src, dst))
    return filtered

# ============================================================
# 合并所有收集的资源（应用过滤）
# ============================================================
all_datas = _filter_pyside6_datas(pyside6_datas) + _filter_datas_by_package(numpy_datas + scipy_datas + onnxruntime_datas + soundfile_datas)
all_binaries = _filter_pyside6_binaries(pyside6_binaries) + _filter_binaries_by_package(numpy_binaries + scipy_binaries + onnxruntime_binaries + soundfile_binaries)

# 内置测试音频（历史记录为空时自动导入）
_test_audio_src = ROOT / "audio_recorder" / "assets" / "测试音频.mp3"
if _test_audio_src.exists():
    all_datas.append((str(_test_audio_src), "audio_recorder/assets"))
all_hiddenimports = numpy_hiddenimports + scipy_hiddenimports + onnxruntime_hiddenimports + soundfile_hiddenimports

# ============================================================
# 强制使用正确版本的 OpenSSL DLL
# Python 3.12 (conda) 使用 OpenSSL 3.x，需要确保打包正确的版本
# ============================================================
import sys
_conda_prefix = Path(sys.prefix)
_openssl_dlls = [
    _conda_prefix / "Library" / "bin" / "libssl-3-x64.dll",
    _conda_prefix / "Library" / "bin" / "libcrypto-3-x64.dll",
]
_openssl_names = {"libssl-3-x64.dll", "libcrypto-3-x64.dll"}

# 先移除所有已收集的 SSL DLL（可能是错误版本）
all_binaries = [item for item in all_binaries if Path(item[0]).name not in _openssl_names]

# 添加正确版本的 SSL DLL
for dll_path in _openssl_dlls:
    if dll_path.exists():
        all_binaries.append((str(dll_path), "."))
    else:
        print(f"WARNING: OpenSSL DLL not found: {dll_path}")

# ============================================================
# 添加应用资源
# ============================================================
app_datas = [
    # 应用资源文件
    (str(ROOT / "audio_recorder" / "assets"), "audio_recorder/assets"),
]

# 添加 ffmpeg（只包含 exe 文件）
if os.path.exists(FFMPEG_DIR):
    app_datas.append((FFMPEG_DIR, "vendor/ffmpeg"))

# 添加 GGUF 推理工具（排除模型文件）
# 在 onedir 包中会落到 _internal/vendor/，以匹配 config.py 中的路径计算
if os.path.exists(VENDOR_QWEN):
    # 只收集必要的文件，排除模型目录和冲突的 DLL
    qwen_dir = Path(VENDOR_QWEN)
    # vendor 内部不需要的文件（会与主应用冲突或不需要）
    _VENDOR_EXCLUDE_FILES = {
        "_ssl.pyd",              # Python SSL 模块，会与主应用冲突
        "libssl-1_1-x64.dll",    # OpenSSL 1.1，主应用用 OpenSSL 3
        "libcrypto-1_1-x64.dll", # OpenSSL 1.1 crypto
        "RUNTIME_INFO.json",     # 开发者元数据，用户不需要
        "VENDOR_SOURCE.md",      # 开发者文档，用户不需要
        "README_UPSTREAM.md",    # 上游 readme，用户不需要
    }
    for item in qwen_dir.rglob('*'):
        if item.is_file():
            rel = item.relative_to(qwen_dir)
            rel_str = str(rel)
            # 排除模型文件（model* 目录）
            if rel_str.startswith('model') or rel_str.startswith('model-'):
                continue
            # 排除日志
            if rel_str.startswith('logs/'):
                continue
            # 排除冲突的 DLL 和模块
            if item.name in _VENDOR_EXCLUDE_FILES:
                continue
            target_dir = Path("vendor") / "qwen3-asr-gguf" / rel.parent
            all_datas.append((str(item), str(target_dir)))

all_datas.extend(app_datas)

# ============================================================
# 隐藏导入模块
# ============================================================
hidden_imports = [
        # PySide6 核心插件
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtNetwork",
        # 音频处理
        "soundcard",
        "pydub",
        "soundfile",
        "scipy.io",
        "scipy.io.wavfile",
        # HTTP 客户端
        "httpx",
        "httpx._transports.default",
        # 其他依赖
        "certifi",
        "idna",
        "sniffio",
        "anyio",
        # vendor 模块
        "qwen_asr_gguf",
        "gguf",
        "gguf.constants",
        "srt",
]

all_hiddenimports.extend(hidden_imports)

# ============================================================
# 排除不需要的模块
# ============================================================
excludes = [
    # 标准库
    "tkinter",

    # 科学计算（不需要的）
    "matplotlib",
    "PIL",
    "pandas",
    "IPython",
    "jupyter",
    "notebook",

    # 机器学习（项目不用）
    "torch",
    "torchvision",
    "torchaudio",
    "transformers",
    "tensorflow",
    "keras",
    "sklearn",
    "scikit-learn",
    "faiss",
    "faiss_cpu",
    "xgboost",
    "lightgbm",

    # 其他不需要的
    "cv2",
    "opencv",
    "sympy",
    "networkx",
    "tqdm",
    "boto3",
    "botocore",
    "s3transfer",
    "google",
    "grpc",
    "protobuf",

    # 开发工具和未使用的库
    "llvmlite",         # Numba/LLVM，应用未使用
    "numba",
    "Pythonwin",        # pywin32 COM 扩展
    "lxml",             # XML 解析，未使用
    "mypy",             # 静态类型检查工具
    "Cython",           # 编译器，运行时不需要
    "zstandard",        # 压缩库，未使用
    "ast_serialize",

    # PySide6 不需要的子模块
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    # QtMultimedia 保留：QMediaDevices 用于监听音频设备变更
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtRemoteObjects",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtShaderTools",
    "PySide6.QtQuick3D",
    "PySide6.QtStateMachine",
    "PySide6.QtScxml",
    "PySide6.QtUiTools",
    "PySide6.QtConcurrent",
    "PySide6.QtSql",
    "PySide6.QtXml",
]

# ============================================================
# 分析阶段
# ============================================================
a = Analysis(
    [ENTRY_POINT],
    pathex=[ROOT],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# ============================================================
# 分析后过滤：移除不需要的 PySide6 文件和其他包
# ============================================================

# 需要排除的 PySide6 目录（相对于 PySide6 包）
_PYSIDE6_EXCLUDE_DATS = {
    "resources",
    "qml",
    "opengl32sw.dll",
}

# 需要排除的翻译文件（保留 zh_CN）
def _should_keep_pyside6_dat(dst: str) -> bool:
    dst_lower = dst.lower().replace("\\", "/")
    # 检查是否在排除目录中
    for excl in _PYSIDE6_EXCLUDE_DATS:
        if f"/{excl}/" in dst_lower or dst_lower.endswith(f"/{excl}"):
            return False
    # 翻译文件只保留中文
    if "/translations/" in dst_lower:
        return "zh_cn" in dst_lower
    return True

# 需要排除的二进制包
_EXCLUDE_BIN_PACKAGES = {"llvmlite", "numba", "pythonwin", "lxml", "mypy", "cryptography", "cython", "zstandard"}

def _should_keep_binary(src: str) -> bool:
    src_lower = src.lower().replace("\\", "/")
    for pkg in _EXCLUDE_BIN_PACKAGES:
        if f"/{pkg}/" in src_lower or f"/{pkg}." in src_lower:
            return False
    return True

# 过滤 datas
a.datas = [item for item in a.datas if _should_keep_pyside6_dat(item[0])]
# 过滤 binaries
a.binaries = [item for item in a.binaries if _should_keep_binary(item[0])]

# ============================================================
# 生成 PYZ 压缩包
# ============================================================
pyz = PYZ(a.pure)

# ============================================================
# 生成可执行文件
# ============================================================
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=ICON_PATH if os.path.exists(ICON_PATH) else None,
    version=VERSION_INFO_PATH if os.path.exists(VERSION_INFO_PATH) else None,
)

# ============================================================
# 收集所有文件到目录
# ============================================================
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
