"""ASR 子进程入口。

此模块只在独立进程中运行真实 ASR 推理，通过 stdout 输出 JSON Lines
与主界面进程通信。不要在这里导入 Qt。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from typing import Any

# 确保环境变量设置（在子进程启动早期设置）
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# 打包后 sys.__stdout__ 可能被重定向，不重新包装以避免问题
# 依赖 PYTHONIOENCODING 环境变量确保编码正确

from .engine import TranscriptionEngine
from .types import TranscriptionProgress


def _emit(payload: dict[str, Any]) -> None:
    """向父进程发送一条 JSON Lines 消息。直接写入字节避免编码问题。"""
    try:
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode('utf-8')
        sys.__stdout__.buffer.write(line)
        sys.__stdout__.buffer.flush()
    except (ValueError, OSError, BrokenPipeError, AttributeError) as exc:
        # 父进程可能已关闭或断开，写入stderr诊断
        try:
            sys.__stderr__.write(f"[worker] _emit failed: {exc}\n")
            sys.__stderr__.flush()
        except Exception:
            pass


def _progress_payload(progress: object) -> dict[str, Any]:
    if isinstance(progress, TranscriptionProgress):
        return {
            "kind": "transcription_progress",
            "stage": progress.stage,
            "percent": progress.percent,
            "processed_seconds": progress.processed_seconds,
            "total_seconds": progress.total_seconds,
            "message": progress.message,
        }
    if is_dataclass(progress):
        return {"kind": "text_progress", "message": str(asdict(progress))}
    return {"kind": "text_progress", "message": str(progress or "")}


def run_transcription(audio_file: str) -> int:
    # 诊断：记录启动信息到 stderr（会被父进程捕获）
    try:
        sys.__stderr__.write(f"[worker] start: audio={audio_file}, frozen={getattr(sys, 'frozen', False)}\n")
        sys.__stderr__.flush()
    except Exception:
        pass

    engine = TranscriptionEngine()
    try:
        text = engine.transcribe(audio_file, on_progress=lambda item: _emit(_progress_payload(item)))
        _emit({"kind": "completed", "text": text, "diagnostics": engine.last_diagnostics or {}})
        return 0
    except Exception as exc:  # noqa: BLE001 - 子进程边界需要兜底返回错误给父进程
        try:
            sys.__stderr__.write(f"[worker] exception: {exc}\n")
            sys.__stderr__.flush()
        except Exception:
            pass
        _emit({"kind": "failed", "error": str(exc), "diagnostics": engine.last_diagnostics or {}})
        return 0
    finally:
        engine.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NoisNote ASR worker process")
    parser.add_argument("audio_file")
    args = parser.parse_args(argv)
    return run_transcription(args.audio_file)


if __name__ == "__main__":
    raise SystemExit(main())
