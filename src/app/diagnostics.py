"""运行环境诊断入口。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from ..app.config import get_config, get_qwen3_asr_gguf_tool_dir
from ..asr.runtime import Qwen3AsrGgufRuntime
from ..asr.types import Qwen3AsrGgufRuntimeConfig


def diagnose_asr_runtime() -> int:
    """诊断打包环境中的 Qwen3-ASR GGUF runtime 导入状态。"""
    config = get_config()
    tool_dir = get_qwen3_asr_gguf_tool_dir(config)
    print(f"tool_dir={tool_dir}")
    print(f"tool_dir_exists={tool_dir.exists()}")
    print(f"frozen={getattr(sys, 'frozen', False)}")
    print(f"meipass={getattr(sys, '_MEIPASS', '')}")
    if not tool_dir.exists():
        return 2

    runtime = Qwen3AsrGgufRuntime(
        Qwen3AsrGgufRuntimeConfig(
            model_dir=Path("."),
            model_name="diagnostic",
            model_size="",
            tool_dir=tool_dir,
        )
    )
    try:
        engine_classes = runtime._import_engine(tool_dir)
    except Exception:
        print("import_ok=false")
        traceback.print_exc()
        return 1

    print("import_ok=true")
    print("engine_classes=" + ",".join(item.__name__ for item in engine_classes))
    return 0
