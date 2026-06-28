"""下载项目所需第三方二进制依赖（llama.cpp DLL + ffmpeg）。

用法:
    python scripts/download_deps.py          # 下载全部
    python scripts/download_deps.py --llama  # 仅 llama.cpp DLL
    python scripts/download_deps.py --ffmpeg # 仅 ffmpeg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_INFO_PATH = ROOT / "vendor" / "qwen3-asr-gguf" / "RUNTIME_INFO.json"
LLAMA_BIN_DIR = ROOT / "vendor" / "qwen3-asr-gguf" / "qwen_asr_gguf" / "inference" / "bin"
FFMPEG_DIR = ROOT / "vendor" / "ffmpeg"

# 排除不需要的 DLL（多模态、RPC、量化工具）
EXCLUDE_DLLS = {"mtmd.dll", "ggml-rpc.dll", "llama-quantize.exe"}

FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
FFMPEG_FILES = ["ffmpeg.exe", "ffprobe.exe"]


def sha256_hex(file_path: Path) -> str:
    """计算文件 SHA-256。"""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def download_llama() -> bool:
    """下载 llama.cpp DLL 并校验。"""
    if not RUNTIME_INFO_PATH.exists():
        print(f"[错误] 找不到 {RUNTIME_INFO_PATH}")
        return False

    info = json.loads(RUNTIME_INFO_PATH.read_text(encoding="utf-8"))
    llama_info = info.get("llama_cpp", {})
    url = llama_info.get("download_url", "")
    expected_files = llama_info.get("files", {})

    if not url or not expected_files:
        print("[错误] RUNTIME_INFO.json 缺少 llama_cpp 下载信息")
        return False

    LLAMA_BIN_DIR.mkdir(parents=True, exist_ok=True)

    # 检查是否已全部存在且校验通过
    all_ok = True
    for name, meta in expected_files.items():
        if name in EXCLUDE_DLLS:
            continue
        fpath = LLAMA_BIN_DIR / name
        if not fpath.exists():
            all_ok = False
            break
        if sha256_hex(fpath) != meta.get("sha256", ""):
            print(f"  {name} 校验失败，重新下载")
            all_ok = False
            break

    if all_ok:
        print("[llama.cpp] 所有 DLL 已就绪且校验通过，跳过下载。")
        return True

    print(f"[llama.cpp] 下载 {url} ...")
    try:
        req = Request(url, headers={"User-Agent": "NoisNote/1.0"})
        with urlopen(req, timeout=60) as resp:
            zip_data = resp.read()
    except Exception as e:
        print(f"[错误] 下载失败: {e}")
        return False

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_data)
        zip_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            # 查找 bin/ 目录前缀
            bin_prefix = ""
            for name in zf.namelist():
                if name.endswith("/llama.dll") or name.endswith("\\llama.dll"):
                    bin_prefix = name.rsplit("llama.dll", 1)[0]
                    break

            extracted = 0
            for name, meta in expected_files.items():
                if name in EXCLUDE_DLLS:
                    continue
                arcname = bin_prefix + name if bin_prefix else name
                try:
                    zf.extract(arcname, LLAMA_BIN_DIR)
                    # 如果解压到子目录，移动上来
                    extracted_path = LLAMA_BIN_DIR / arcname
                    target_path = LLAMA_BIN_DIR / name
                    if extracted_path != target_path:
                        extracted_path.rename(target_path)
                    # 校验
                    actual = sha256_hex(target_path)
                    expected = meta.get("sha256", "")
                    if actual != expected:
                        print(f"  [错误] {name} SHA-256 不匹配")
                        return False
                    extracted += 1
                except KeyError:
                    print(f"  [警告] zip 中未找到 {name}，跳过")

            # 清理子目录
            if bin_prefix:
                subdir = LLAMA_BIN_DIR / bin_prefix.split("/")[0]
                if subdir.exists() and subdir.is_dir():
                    shutil.rmtree(subdir)

        print(f"[llama.cpp] 完成，{extracted} 个文件校验通过。")
        return True
    finally:
        zip_path.unlink(missing_ok=True)


def download_ffmpeg() -> bool:
    """下载 ffmpeg 二进制。"""
    FFMPEG_DIR.mkdir(parents=True, exist_ok=True)

    # 检查是否已存在
    missing = [f for f in FFMPEG_FILES if not (FFMPEG_DIR / f).exists()]
    if not missing:
        print("[ffmpeg] 已就绪，跳过下载。")
        return True

    print(f"[ffmpeg] 下载 {FFMPEG_URL} ...")
    try:
        req = Request(FFMPEG_URL, headers={"User-Agent": "NoisNote/1.0"})
        with urlopen(req, timeout=120) as resp:
            zip_data = resp.read()
    except Exception as e:
        print(f"[错误] ffmpeg 下载失败: {e}")
        print("  请手动从 https://github.com/BtbN/FFmpeg-Builds/releases 下载")
        print(f"  并将 ffmpeg.exe 和 ffprobe.exe 放入 {FFMPEG_DIR}")
        return False

    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_data)
        zip_path = Path(tmp.name)

    try:
        with zipfile.ZipFile(zip_path) as zf:
            # ffmpeg zip 通常结构: ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe
            bin_prefix = ""
            for name in zf.namelist():
                if name.endswith("/ffmpeg.exe") or name.endswith("\\ffmpeg.exe"):
                    bin_prefix = name.rsplit("ffmpeg.exe", 1)[0]
                    break

            extracted = 0
            for fname in FFMPEG_FILES:
                arcname = bin_prefix + fname if bin_prefix else fname
                try:
                    zf.extract(arcname, FFMPEG_DIR)
                    extracted_path = FFMPEG_DIR / arcname
                    target_path = FFMPEG_DIR / fname
                    if extracted_path != target_path:
                        extracted_path.rename(target_path)
                    extracted += 1
                except KeyError:
                    print(f"  [警告] zip 中未找到 {fname}")

            if bin_prefix:
                subdir = FFMPEG_DIR / bin_prefix.split("/")[0]
                if subdir.exists() and subdir.is_dir():
                    shutil.rmtree(subdir)

        print(f"[ffmpeg] 完成，{extracted} 个文件就绪。")
        return True
    finally:
        zip_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="下载第三方二进制依赖")
    parser.add_argument("--llama", action="store_true", help="仅下载 llama.cpp DLL")
    parser.add_argument("--ffmpeg", action="store_true", help="仅下载 ffmpeg")
    args = parser.parse_args()

    download_all = not args.llama and not args.ffmpeg

    ok = True
    if download_all or args.llama:
        if not download_llama():
            ok = False
    if download_all or args.ffmpeg:
        if not download_ffmpeg():
            ok = False

    if ok:
        print("\n全部依赖就绪。")
    else:
        print("\n部分依赖下载失败，请检查网络后重试。")
        sys.exit(1)


if __name__ == "__main__":
    main()
