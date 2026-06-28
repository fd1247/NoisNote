"""ASR 转录模块。"""
from __future__ import annotations

import sys
import io
import threading
import wave
from pathlib import Path
from typing import Any

from ..app.config import get_config, get_qwen3_asr_gguf_tool_dir
from ..model_registry.service import ModelService
from .runtime import (
    Qwen3AsrGgufError,
    Qwen3AsrGgufProgress,
    Qwen3AsrGgufRuntime,
    Qwen3AsrGgufRuntimeConfig,
)
from .types import ProgressReporter, TranscriptionProgress

# 确保 UTF-8 输出（打包后 sys.stdout 可能为 None）
if sys.stdout is not None and hasattr(sys.stdout, 'encoding') and sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    except (AttributeError, ValueError):
        pass


class TranscriptionEngine:
    """Qwen3-ASR GGUF 转录引擎。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.runtime: Qwen3AsrGgufRuntime | None = None
        self.is_loaded = False
        self.is_loading = False
        self.config = config or get_config()
        self.last_diagnostics: dict[str, Any] = {}

    def load_model(self, on_progress=None) -> None:
        """加载当前配置中的 GGUF 模型。"""
        if self.is_loaded or self.is_loading:
            return

        self.is_loading = True
        try:
            self.runtime = Qwen3AsrGgufRuntime(self._build_runtime_config())
            self.runtime.load(on_progress)
            self.is_loaded = True
        except Qwen3AsrGgufError as exc:
            self.last_diagnostics = self._failure_diagnostics(exc)
            raise RuntimeError(exc.user_message) from exc
        except Exception as exc:
            wrapped = Qwen3AsrGgufError(
                "转录引擎加载失败，请检查模型和运行环境。",
                str(exc),
                "TranscriptionEngineLoadFailed",
            )
            self.last_diagnostics = self._failure_diagnostics(wrapped)
            raise RuntimeError(wrapped.user_message) from exc
        finally:
            self.is_loading = False

    def transcribe(self, audio_file, on_progress=None):
        """转录音频文件。"""
        audio_path = Path(audio_file)
        reporter = ProgressReporter(on_progress, _wav_duration(audio_path))
        try:
            reporter.emit("preparing_audio", 0, "准备音频", 0.0)
            if not self.is_loaded:
                self.load_model(reporter.emit_text)
            if self.runtime is None:
                raise Qwen3AsrGgufError(
                    "转录引擎未正确初始化。",
                    "runtime is None after load_model",
                    "RuntimeNotInitialized",
                )
            reporter.emit("transcribing", 15, "正在转录 15%", 0.0)
            result = self.runtime.transcribe(audio_file, reporter.emit_text)
            reporter.emit("writing_result", 95, "写入结果", reporter.total_seconds)
            self.last_diagnostics = result.diagnostics
            reporter.emit("completed", 100, "转录完成", reporter.total_seconds)
            return result.text
        except Qwen3AsrGgufError as exc:
            self.last_diagnostics = self._failure_diagnostics(exc)
            raise RuntimeError(exc.user_message) from exc
        except RuntimeError:
            # load_model 已经包装过，诊断信息已在 load_model 中记录
            raise
        except Exception as exc:
            wrapped = Qwen3AsrGgufError("转录失败", str(exc), "TranscribeFailed")
            self.last_diagnostics = self._failure_diagnostics(wrapped)
            raise RuntimeError(wrapped.user_message) from exc

    def close(self) -> None:
        """释放底层运行时。"""
        if self.runtime is not None:
            self.runtime.close()
            self.runtime = None
        self.is_loaded = False

    def _build_runtime_config(self) -> Qwen3AsrGgufRuntimeConfig:
        """根据应用配置构造 GGUF runtime 配置。"""
        asr_config = self.config.get("selected_asr", {})
        selected_model = asr_config.get("model", "")
        service = ModelService(self.config)
        entry = service.get_entry(selected_model)
        if not entry:
            raise Qwen3AsrGgufError(
                "当前 ASR 模型不在正式模型清单中，请在设置中重新选择模型。",
                str(selected_model),
                "UnknownModel",
            )

        local_model_path = asr_config.get("model_path") or ""
        model_dir = Path(local_model_path).expanduser() if local_model_path else service.get_target_dir(entry)
        gguf_config = self.config.get("qwen3_asr_gguf", {})
        hotwords = gguf_config.get("hotwords") or []
        if isinstance(hotwords, str):
            hotwords = [part.strip() for part in hotwords.split(",") if part.strip()]

        return Qwen3AsrGgufRuntimeConfig(
            model_dir=model_dir.resolve(),
            model_name=entry.name,
            model_size=entry.model_size,
            requested_device=asr_config.get("device", "auto"),
            tool_dir=get_qwen3_asr_gguf_tool_dir(self.config),
            chunk_size=float(gguf_config.get("chunk_size") or 40.0),
            memory_num=int(gguf_config.get("memory_num") or 1),
            n_ctx=int(gguf_config.get("n_ctx") or 2048),
            context=str(gguf_config.get("context") or ""),
            hotwords=list(hotwords),
        )

    def _failure_diagnostics(self, error: Qwen3AsrGgufError) -> dict[str, Any]:
        """构造失败场景写入 metadata 的诊断结构。"""
        import platform
        import traceback as tb
        asr_config = self.config.get("selected_asr", {})
        entry = ModelService(self.config).get_entry(asr_config.get("model", ""))
        # 换取完整 traceback 字符串
        cause = error.__cause__
        tb_lines = tb.format_exception(type(error), error, error.__traceback__)
        if cause:
            tb_lines += ["\nCaused by:\n"] + tb.format_exception(type(cause), cause, cause.__traceback__)
        return {
            "engine": "qwen3-asr-gguf",
            "status": "failed",
            "model_name": asr_config.get("model", ""),
            "model_size": entry.model_size if entry else "",
            "model_dir": asr_config.get("model_path", ""),
            "requested_device": asr_config.get("device", "auto"),
            "resolved_device": "",
            "runtime": {},
            "timings": {},
            "performance": {},
            "hotwords": list(self.config.get("qwen3_asr_gguf", {}).get("hotwords") or []),
            "context_enabled": bool(self.config.get("qwen3_asr_gguf", {}).get("context")),
            "error": {
                **error.to_metadata(),
                "exc_type": type(cause).__name__ if cause else type(error).__name__,
                "traceback": "".join(tb_lines),
            },
            "system_info": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "machine": platform.machine(),
                "processor": platform.processor(),
            },
        }

    def transcribe_async(self, audio_file, on_complete=None, on_progress=None):
        """异步转录"""
        def _do_transcribe():
            try:
                text = self.transcribe(audio_file, on_progress)
                if on_complete:
                    on_complete(text, None)
            except Exception as e:
                if on_complete:
                    on_complete(None, e)

        thread = threading.Thread(target=_do_transcribe, daemon=True)
        thread.start()
        return thread


def _wav_duration(path: Path) -> float | None:
    if not path.exists() or path.suffix.lower() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as wav_file:
            rate = wav_file.getframerate()
            if rate <= 0:
                return None
            return wav_file.getnframes() / rate
    except (wave.Error, OSError, EOFError):
        return None
