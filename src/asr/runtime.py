"""Qwen3-ASR GGUF 正式推理封装。"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from ..app.config import (
    QWEN3_ASR_GGUF_REQUIRED_FILES,
    QWEN3_FORCE_ALIGNER_GGUF_REQUIRED_FILES,
    get_qwen3_asr_gguf_tool_dir,
)
from .types import (
    DeviceResolution,
    Qwen3AsrGgufError,
    Qwen3AsrGgufProgress,
    Qwen3AsrGgufResult,
    Qwen3AsrGgufRuntimeConfig,
    build_context,
    resolve_device_mode,
)
from .utils import (
    _round_seconds,
    _strip_hotword_prompt_leak,
)
from .timestamps import alignment_items_to_timeline, is_timeline_monotonic, timeline_to_dicts
from ..utils.logging import log_event

ProgressCallback = Callable[[object], None]
_DLL_DIRECTORY_HANDLES: list[object] = []
_DLL_DIRECTORY_PATHS: set[str] = set()

__all__ = [
    "DeviceResolution",
    "Qwen3AsrGgufError",
    "Qwen3AsrGgufProgress",
    "Qwen3AsrGgufResult",
    "Qwen3AsrGgufRuntime",
    "Qwen3AsrGgufRuntimeConfig",
    "build_context",
    "resolve_device_mode",
]


def _alignment_items(result: Any) -> list[Any]:
    alignment = getattr(result, "alignment", None)
    items = getattr(alignment, "items", None)
    if items is None:
        return []
    return list(items)


class Qwen3AsrGgufRuntime:
    """封装 Qwen3-ASR-GGUF vendor engine。"""

    def __init__(self, config: Qwen3AsrGgufRuntimeConfig):
        self.config = config
        self.device = resolve_device_mode(config.requested_device)
        self.engine = None
        self._engine_classes = None
        self.model_load_seconds: float | None = None

    def load(self, on_progress: ProgressCallback | None = None) -> None:
        """加载模型。"""
        if self.engine is not None:
            return
        if on_progress:
            on_progress("正在加载 Qwen3-ASR GGUF 模型")

        log_event("asr.load.started", level="INFO", module="asr",
                  context={"model": self.config.model_name,
                           "device": self.device.resolved_device,
                           "use_dml": self.device.onnx_provider == "DML"})
        self._validate_model_files()
        tool_dir = self._resolve_tool_dir()
        log_event("asr.load.engine_import", level="INFO", module="asr",
                  context={"tool_dir": str(tool_dir)})
        start = time.perf_counter()
        try:
            ASREngineConfig, AlignerConfig, QwenASREngine = self._import_engine(tool_dir)
            align_config = None
            if self.config.enable_timestamps:
                if self.config.aligner_model_dir is None:
                    raise Qwen3AsrGgufError(
                        "时间戳对齐模型未配置，已无法启用时间戳。",
                        "aligner_model_dir is None",
                        "MissingAlignerConfig",
                    )
                align_config = AlignerConfig(
                    model_dir=str(self.config.aligner_model_dir),
                    encoder_frontend_fn="qwen3_aligner_encoder_frontend.int4.onnx",
                    encoder_backend_fn="qwen3_aligner_encoder_backend.int4.onnx",
                    llm_fn="qwen3_aligner_llm.q4_k.gguf",
                    onnx_provider=self.device.onnx_provider,
                    llm_use_gpu=self.device.llm_use_gpu,
                    n_ctx=int(self.config.n_ctx),
                )
            engine_config = ASREngineConfig(
                model_dir=str(self.config.model_dir),
                # 显式指定模型文件名：当前下载的模型是 int4/q4_k 量化版本，
                # 与上游默认的 fp16/q5_k 不同，必须覆盖。
                encoder_frontend_fn="qwen3_asr_encoder_frontend.int4.onnx",
                encoder_backend_fn="qwen3_asr_encoder_backend.int4.onnx",
                llm_fn="qwen3_asr_llm.q4_k.gguf",
                onnx_provider=self.device.onnx_provider,
                llm_use_gpu=self.device.llm_use_gpu,
                n_ctx=int(self.config.n_ctx),
                chunk_size=float(self.config.chunk_size),
                memory_num=int(self.config.memory_num),
                verbose=False,
                enable_aligner=bool(self.config.enable_timestamps),
                align_config=align_config,
            )
            log_event("asr.load.engine_create", level="INFO", module="asr")
            with contextlib.redirect_stdout(io.StringIO()):
                self.engine = QwenASREngine(config=engine_config)
        except Qwen3AsrGgufError:
            raise
        except Exception as exc:
            raise self._map_exception(exc, "load") from exc
        self.model_load_seconds = time.perf_counter() - start

        log_event("asr.load.completed", level="INFO", module="asr",
                  context={"load_seconds": round(self.model_load_seconds, 3)})
        if on_progress:
            on_progress("模型加载完成")

    def transcribe(
        self,
        audio_path: str | Path,
        on_progress: ProgressCallback | None = None,
    ) -> Qwen3AsrGgufResult:
        """执行转录并返回文本和诊断信息。"""
        audio = Path(audio_path)
        if not audio.exists() or not audio.is_file():
            raise Qwen3AsrGgufError(
                "音频文件不存在，无法转录。",
                str(audio),
                "MissingAudioFile",
            )
        if self.engine is None:
            self.load(on_progress)
        if self.engine is None:
            raise Qwen3AsrGgufError(
                "ASR 模型加载失败，无法转录。",
                "Qwen3 ASR engine is still None after load().",
                "EngineNotLoaded",
            )

        if on_progress:
            on_progress("正在转录音频")

        context = build_context(self.config.context, self.config.hotwords)
        start = time.perf_counter()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    result = self.engine.transcribe(
                        audio_file=str(audio),
                        context=context,
                        language=self.config.language,
                        start_second=0.0,
                        duration=0.0,
                        progress_callback=on_progress,
                    )
                except TypeError as exc:
                    if "progress_callback" not in str(exc):
                        raise
                    result = self.engine.transcribe(
                        audio_file=str(audio),
                        context=context,
                        language=self.config.language,
                        start_second=0.0,
                        duration=0.0,
                    )
        except Exception as exc:
            raise self._map_exception(exc, "transcribe") from exc

        transcribe_seconds = time.perf_counter() - start
        text = self._strip_hotword_prompt_leak(str(getattr(result, "text", "") or ""))
        if not text.strip():
            raise Qwen3AsrGgufError(
                "未识别到有效语音内容。",
                "Qwen3-ASR-GGUF returned empty text",
                "EmptyTranscription",
            )

        timeline = alignment_items_to_timeline(_alignment_items(result))
        diagnostics = self._build_diagnostics(
            audio,
            text,
            transcribe_seconds,
            getattr(result, "performance", None),
            timeline,
        )
        if on_progress:
            on_progress("转录完成")
        return Qwen3AsrGgufResult(text=text, diagnostics=diagnostics, timeline=timeline)

    def close(self) -> None:
        """关闭底层 engine。"""
        if self.engine is None:
            return
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.engine.shutdown()
        finally:
            self.engine = None

    def _resolve_tool_dir(self) -> Path:
        config = None
        if self.config.tool_dir:
            config = {"qwen3_asr_gguf": {"tool_dir": str(self.config.tool_dir)}}
        tool_dir = get_qwen3_asr_gguf_tool_dir(config)
        if not tool_dir.exists():
            raise Qwen3AsrGgufError(
                "缺少 Qwen3-ASR GGUF 推理工具，请先完成应用运行环境配置。",
                str(tool_dir),
                "MissingGgufToolDir",
            )
        return tool_dir

    def _validate_model_files(self) -> None:
        model_dir = self.config.model_dir.expanduser()
        if not model_dir.exists() or not model_dir.is_dir():
            raise Qwen3AsrGgufError(
                "模型未下载，请先下载模型。",
                str(model_dir),
                "MissingModelDirectory",
            )
        missing = [
            file_name
            for file_name in QWEN3_ASR_GGUF_REQUIRED_FILES
            if not (model_dir / file_name).exists()
        ]
        if missing:
            raise Qwen3AsrGgufError(
                "模型文件不完整，请重新下载模型。",
                "missing_files=" + ", ".join(missing),
                "MissingModelFile",
            )
        if self.config.enable_timestamps:
            aligner_dir = self.config.aligner_model_dir.expanduser() if self.config.aligner_model_dir else None
            if aligner_dir is None or not aligner_dir.exists() or not aligner_dir.is_dir():
                raise Qwen3AsrGgufError(
                    "时间戳对齐模型未下载，已无法启用时间戳。",
                    str(aligner_dir or ""),
                    "MissingAlignerDirectory",
                )
            missing_aligner = [
                file_name
                for file_name in QWEN3_FORCE_ALIGNER_GGUF_REQUIRED_FILES
                if not (aligner_dir / file_name).exists()
            ]
            if missing_aligner:
                raise Qwen3AsrGgufError(
                    "时间戳对齐模型文件不完整，已无法启用时间戳。",
                    "missing_files=" + ", ".join(missing_aligner),
                    "MissingAlignerModelFile",
                )

    def _import_engine(self, tool_dir: Path):
        if str(tool_dir) not in sys.path:
            sys.path.insert(0, str(tool_dir))
        export_dir = tool_dir / "qwen_asr_gguf" / "export"
        if export_dir.exists() and str(export_dir) not in sys.path:
            sys.path.insert(0, str(export_dir))
        self._add_dll_directory(tool_dir)
        try:
            from qwen_asr_gguf.inference import ASREngineConfig, AlignerConfig, QwenASREngine
        except ImportError as exc:
            raise Qwen3AsrGgufError(
                "Qwen3-ASR GGUF 推理组件加载失败，请检查运行环境。",
                str(exc),
                "MissingGgufRuntime",
            ) from exc
        return ASREngineConfig, AlignerConfig, QwenASREngine

    def _add_dll_directory(self, tool_dir: Path) -> None:
        bin_dir = tool_dir / "qwen_asr_gguf" / "inference" / "bin"
        if not bin_dir.exists():
            log_event("asr.dll_dir.missing", level="WARNING", module="asr",
                      context={"bin_dir": str(bin_dir)})
            return
        if not hasattr(os, "add_dll_directory"):
            return
        # 检查关键 DLL 是否存在
        for dll in ("llama.dll", "ggml.dll", "ggml-base.dll"):
            if not (bin_dir / dll).exists():
                log_event("asr.dll.missing", level="WARNING", module="asr",
                          context={"dll": dll, "bin_dir": str(bin_dir)})
        bin_dir_text = str(bin_dir)
        if bin_dir_text in _DLL_DIRECTORY_PATHS:
            return
        handle = os.add_dll_directory(bin_dir_text)
        _DLL_DIRECTORY_HANDLES.append(handle)
        _DLL_DIRECTORY_PATHS.add(bin_dir_text)

    def _build_diagnostics(
        self,
        audio_path: Path,
        text: str,
        transcribe_seconds: float,
        performance: Any,
        timeline: list[Any] | None = None,
    ) -> dict[str, Any]:
        timeline = timeline or []
        timings = {
            "model_load_seconds": _round_seconds(self.model_load_seconds),
            "transcribe_seconds": _round_seconds(transcribe_seconds),
            "total_seconds": _round_seconds((self.model_load_seconds or 0) + transcribe_seconds),
            "chunk_transcribe_timings": [
                {
                    "index": 1,
                    "seconds": _round_seconds(transcribe_seconds),
                    "note": (
                        "Qwen3-ASR-GGUF release engine handles internal streaming chunks; "
                        "per-internal-chunk timings are not exposed."
                    ),
                }
            ],
        }
        return {
            "engine": "qwen3-asr-gguf",
            "status": "completed",
            "model_name": self.config.model_name,
            "model_size": self.config.model_size,
            "model_dir": str(self.config.model_dir),
            "audio_path": str(audio_path),
            "requested_device": self.device.requested_device,
            "resolved_device": self.device.resolved_device,
            "runtime": {
                **self.device.diagnostic,
                "tool_dir": str(self._resolve_tool_dir()),
                "chunk_size": self.config.chunk_size,
                "memory_num": self.config.memory_num,
                "n_ctx": self.config.n_ctx,
            },
            "timings": timings,
            "performance": performance or {},
            "hotwords": list(self.config.hotwords),
            "context_enabled": bool(build_context(self.config.context, self.config.hotwords)),
            "timestamps": {
                "requested": bool(self.config.request_timestamps),
                "enabled": bool(self.config.enable_timestamps and timeline),
                "aligner_model_name": self.config.aligner_model_name,
                "aligner_model_dir": str(self.config.aligner_model_dir or ""),
                "items_count": len(timeline),
                "monotonic": is_timeline_monotonic(timeline),
                "degrade_reason": self.config.timestamp_degrade_reason,
            },
            "timeline": timeline_to_dicts(timeline),
            "text_length": len(text),
            "error": None,
        }

    def _map_exception(self, exc: Exception, phase: str) -> Qwen3AsrGgufError:
        message = str(exc)
        lower_message = message.lower()
        if "dml" in lower_message or "directml" in lower_message or "provider" in lower_message:
            mapped = Qwen3AsrGgufError(
                "GPU 加速不可用，请切换到 CPU 或检查显卡环境。",
                f"{phase}: {message}",
                "DeviceUnavailable",
            )
        elif "ffmpeg" in lower_message or "pydub" in lower_message or "decode" in lower_message:
            mapped = Qwen3AsrGgufError(
                "当前音频无法处理，请转换格式后重试。",
                f"{phase}: {message}",
                "UnsupportedAudio",
            )
        else:
            mapped = Qwen3AsrGgufError(
                "转录失败，请查看日志或尝试更换设备。",
                f"{phase}: {message}",
                "InferenceFailed",
            )
        log_event("asr.error.mapped", level="WARNING", module="asr",
                  context={"phase": phase,
                           "error_type": mapped.error_type,
                           "exc_type": type(exc).__name__,
                           "exc_message": message[:500]})
        return mapped

    def _strip_hotword_prompt_leak(self, text: str) -> str:
        return _strip_hotword_prompt_leak(text, self.config.hotwords)

    
