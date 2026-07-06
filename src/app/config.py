"""配置管理模块。"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 配置目录：%APPDATA%\NoisNote（Windows）或 ~/.config/NoisNote（其他平台）
if sys.platform == "win32":
    APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    CONFIG_DIR = APPDATA / "NoisNote"
else:
    CONFIG_DIR = Path.home() / ".config" / "NoisNote"

CONFIG_FILE = CONFIG_DIR / "config.json"

# 默认用户数据根目录
DEFAULT_DATA_ROOT = Path.home() / "Documents" / "NoisNote"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QWEN3_ASR_GGUF_TOOL_DIR = REPO_ROOT / "vendor" / "qwen3-asr-gguf"
# 旧 demo vendor 路径，兼容迁移前的本地环境
DEV_QWEN3_ASR_GGUF_TOOL_DIR = (
    REPO_ROOT / "demo" / "model_test" / "llama-cpp" / "vendor" / "Qwen3-ASR-Transcribe"
)

QWEN3_ASR_GGUF_REQUIRED_FILES = [
    "qwen3_asr_encoder_frontend.int4.onnx",
    "qwen3_asr_encoder_backend.int4.onnx",
    "qwen3_asr_llm.q4_k.gguf",
]
QWEN3_FORCE_ALIGNER_GGUF_REQUIRED_FILES = [
    "qwen3_aligner_encoder_frontend.int4.onnx",
    "qwen3_aligner_encoder_backend.int4.onnx",
    "qwen3_aligner_llm.q4_k.gguf",
]

QWEN3_ASR_GGUF_06B_ID = "Qwen3-ASR-0.6B-GGUF"
QWEN3_ASR_GGUF_06B_SLUG = "Qwen3-ASR-GGUF-0.6B"
QWEN3_ASR_GGUF_17B_ID = "Qwen3-ASR-1.7B-GGUF"
QWEN3_ASR_GGUF_17B_SLUG = "Qwen3-ASR-GGUF-1.7B"
QWEN3_FORCE_ALIGNER_GGUF_06B_ID = "Qwen3-ForceAligner-GGUF-0.6B"
QWEN3_FORCE_ALIGNER_GGUF_06B_SLUG = "Qwen3-ForceAligner-0.6B-gguf"

QWEN3_ASR_GGUF_06B_URL = (
    "https://github.com/HaujetZhao/Qwen3-ASR-GGUF/releases/download/models/"
    "Qwen3-ASR-0.6B-gguf.zip"
)
QWEN3_ASR_GGUF_17B_URL = (
    "https://github.com/HaujetZhao/Qwen3-ASR-GGUF/releases/download/models/"
    "Qwen3-ASR-1.7B-gguf.zip"
)
QWEN3_FORCE_ALIGNER_GGUF_06B_URL = (
    "https://github.com/HaujetZhao/Qwen3-ASR-GGUF/releases/download/models/"
    "Qwen3-ForceAligner-0.6B-gguf.zip"
)
QWEN3_ASR_GGUF_MODELSCOPE_REVISION = "v1.0.0"
QWEN3_ASR_GGUF_06B_MODELSCOPE_ID = "luciacx/Qwen3-ASR-GGUF-0.6B-mixed"
QWEN3_ASR_GGUF_17B_MODELSCOPE_ID = "luciacx/Qwen3-ASR-GGUF-1.7B-mixed"
QWEN3_FORCE_ALIGNER_GGUF_06B_MODELSCOPE_ID = "luciacx/Qwen3-ForceAligner-GGUF-0.6B-mixed"

QWEN3_ASR_GGUF_06B_FILES: list[dict[str, str | int]] = [
    {"name": "qwen3_asr_encoder_frontend.int4.onnx", "size": 20_343_991},
    {"name": "qwen3_asr_encoder_backend.int4.onnx", "size": 94_750_816},
    {"name": "qwen3_asr_llm.q4_k.gguf", "size": 484_215_360},
]
QWEN3_ASR_GGUF_17B_FILES: list[dict[str, str | int]] = [
    {"name": "qwen3_asr_encoder_frontend.int4.onnx", "size": 20_876_699},
    {"name": "qwen3_asr_encoder_backend.int4.onnx", "size": 164_740_452},
    {"name": "qwen3_asr_llm.q4_k.gguf", "size": 1_282_434_624},
]
QWEN3_FORCE_ALIGNER_GGUF_06B_FILES: list[dict[str, str | int]] = [
    {"name": "qwen3_aligner_encoder_frontend.int4.onnx", "size": 20_876_727},
    {"name": "qwen3_aligner_encoder_backend.int4.onnx", "size": 164_176_179},
    {"name": "qwen3_aligner_llm.q4_k.gguf", "size": 484_399_552},
]

# Anthropic API 常量
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-20250514"
ANTHROPIC_API_VERSION = "2023-06-01"


def _modelscope_resolve_base(modelscope_id: str) -> str:
    return (
        f"https://www.modelscope.cn/models/{modelscope_id}/resolve/"
        f"{QWEN3_ASR_GGUF_MODELSCOPE_REVISION}/"
    )


def _qwen3_asr_download_sources(
    modelscope_id: str,
    files: list[dict[str, str | int]],
    github_url: str,
) -> list[dict[str, Any]]:
    return [
        {
            "name": "modelscope",
            "type": "files",
            "base_url": _modelscope_resolve_base(modelscope_id),
            "revision": QWEN3_ASR_GGUF_MODELSCOPE_REVISION,
            "files": files,
        },
        {
            "name": "github",
            "type": "archive",
            "url": github_url,
        },
    ]

DEFAULT_MODEL_CATALOG = [
    {
        "name": QWEN3_ASR_GGUF_06B_ID,
        "alias": "qwen3-asr-gguf-0.6b",
        "display_name": "Qwen3-ASR-0.6B GGUF",
        "modelscope_id": QWEN3_ASR_GGUF_06B_MODELSCOPE_ID,
        "download_url": _modelscope_resolve_base(QWEN3_ASR_GGUF_06B_MODELSCOPE_ID),
        "download_sources": _qwen3_asr_download_sources(
            QWEN3_ASR_GGUF_06B_MODELSCOPE_ID,
            QWEN3_ASR_GGUF_06B_FILES,
            QWEN3_ASR_GGUF_06B_URL,
        ),
        "revision": QWEN3_ASR_GGUF_MODELSCOPE_REVISION,
        "model_type": "asr",
        "backend": "qwen3_asr_gguf",
        "adapter": "qwen3_asr_gguf",
        "model_size": "0.6B",
        "local_dir_name": QWEN3_ASR_GGUF_06B_SLUG,
        "description": "轻量版，速度更快，适合日常录音和长音频转录",
        "recommended": True,
        "required_files": QWEN3_ASR_GGUF_REQUIRED_FILES,
        "estimated_size_bytes": sum(int(item["size"]) for item in QWEN3_ASR_GGUF_06B_FILES),
    },
    {
        "name": QWEN3_ASR_GGUF_17B_ID,
        "alias": "qwen3-asr-gguf-1.7b",
        "display_name": "Qwen3-ASR-1.7B GGUF",
        "modelscope_id": QWEN3_ASR_GGUF_17B_MODELSCOPE_ID,
        "download_url": _modelscope_resolve_base(QWEN3_ASR_GGUF_17B_MODELSCOPE_ID),
        "download_sources": _qwen3_asr_download_sources(
            QWEN3_ASR_GGUF_17B_MODELSCOPE_ID,
            QWEN3_ASR_GGUF_17B_FILES,
            QWEN3_ASR_GGUF_17B_URL,
        ),
        "revision": QWEN3_ASR_GGUF_MODELSCOPE_REVISION,
        "model_type": "asr",
        "backend": "qwen3_asr_gguf",
        "adapter": "qwen3_asr_gguf",
        "model_size": "1.7B",
        "local_dir_name": QWEN3_ASR_GGUF_17B_SLUG,
        "description": "高精度版，资源占用更高，适合对准确率要求更高的场景",
        "recommended": False,
        "required_files": QWEN3_ASR_GGUF_REQUIRED_FILES,
        "estimated_size_bytes": sum(int(item["size"]) for item in QWEN3_ASR_GGUF_17B_FILES),
    },
    {
        "name": QWEN3_FORCE_ALIGNER_GGUF_06B_ID,
        "alias": "qwen3-force-aligner-gguf-0.6b",
        "display_name": "Qwen3-ForceAligner-0.6B GGUF",
        "modelscope_id": QWEN3_FORCE_ALIGNER_GGUF_06B_MODELSCOPE_ID,
        "download_url": _modelscope_resolve_base(QWEN3_FORCE_ALIGNER_GGUF_06B_MODELSCOPE_ID),
        "download_sources": [
            {
                "name": "modelscope",
                "type": "files",
                "base_url": _modelscope_resolve_base(QWEN3_FORCE_ALIGNER_GGUF_06B_MODELSCOPE_ID),
                "revision": QWEN3_ASR_GGUF_MODELSCOPE_REVISION,
                "files": QWEN3_FORCE_ALIGNER_GGUF_06B_FILES,
            },
            {
                "name": "github",
                "type": "archive",
                "url": QWEN3_FORCE_ALIGNER_GGUF_06B_URL,
            },
        ],
        "revision": QWEN3_ASR_GGUF_MODELSCOPE_REVISION,
        "model_type": "auxiliary",
        "backend": "qwen3_asr_gguf",
        "adapter": "qwen3_force_aligner_gguf",
        "model_size": "0.6B",
        "local_dir_name": QWEN3_FORCE_ALIGNER_GGUF_06B_SLUG,
        "description": "时间戳对齐辅助模型，用于生成逐句时间轴和 SRT 字幕",
        "recommended": False,
        "required_files": QWEN3_FORCE_ALIGNER_GGUF_REQUIRED_FILES,
        "estimated_size_bytes": sum(int(item["size"]) for item in QWEN3_FORCE_ALIGNER_GGUF_06B_FILES),
    },
]

DEFAULT_MODEL_CATALOG_BY_NAME = {
    item["name"]: item
    for item in DEFAULT_MODEL_CATALOG
}
DEFAULT_ASR_MODEL_CATALOG_BY_NAME = {
    item["name"]: item
    for item in DEFAULT_MODEL_CATALOG
    if item.get("model_type") == "asr"
}

DEFAULT_CONFIG: dict[str, Any] = {
    "demo_audio_imported": False,
    "data_root": str(DEFAULT_DATA_ROOT),
    "notebooks": [],
    "last_selected_record_key": "",
    "last_selected_record_keys": {},
    "hotword_sets": [],  # 热词表列表
    "active_hotword_set_ids": [],  # 激活的热词表ID列表
    "selected_asr": {
        "model": QWEN3_ASR_GGUF_06B_ID,
        "model_path": "",
        "device": "auto",
    },
    "qwen3_asr_gguf": {
        "tool_dir": str(DEFAULT_QWEN3_ASR_GGUF_TOOL_DIR),
        "chunk_size": 40.0,
        "memory_num": 1,
        "n_ctx": 2048,
        "context": "",
        "enable_timestamps": False,
    },
    "llm": {
        "provider": "openai",
        "api_key": "",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    },
    "audio": {
        "auto_transcribe": False,
        "auto_summarize": False,
        "capture": {
            "mode": "system",
            "system_device_id": "",
            "microphone_device_id": "",
            "sample_rate": 16000,
            "channels": 1,
            "sample_format": "pcm_s16le",
            "chunk_size": 1024,
            "silence_threshold": 2,
            "silence_hint_seconds": 5,
        },
        "preprocessing": {
            "ffmpeg_path": "",
            "target_sample_rate": 16000,
            "target_channels": 1,
            "target_format": "wav",
        },
    },
    "models": {
        "root_dir": str(DEFAULT_DATA_ROOT / "models"),
        "downloaded": {},
    },
}


def get_data_root(config: dict | None = None) -> Path:
    """获取用户数据根目录。"""
    cfg = config or {}
    return Path(cfg.get("data_root", str(DEFAULT_DATA_ROOT))).expanduser()


def get_output_dir(config: dict | None = None) -> Path:
    """获取录音输出目录（data_root/data）。"""
    return get_data_root(config) / "data"


def _notebook_path_key(path_text: str) -> str:
    """返回用于笔记本去重的规范化路径键。"""
    return os.path.normcase(os.path.abspath(os.path.expanduser(path_text)))


def _notebook_dir_exists(path_text: str) -> bool:
    try:
        return Path(path_text).expanduser().is_dir()
    except OSError:
        return False


def default_notebooks(config: dict | None = None) -> list[dict[str, Any]]:
    """返回默认笔记本配置，默认笔记本兼容现有 data 目录。"""
    cfg = config or {}
    return [
        {
            "id": "default",
            "name": "默认笔记本",
            "path": str(get_output_dir(cfg)),
            "is_default": True,
        }
    ]


def normalize_notebooks(config: dict) -> tuple[list[dict[str, Any]], bool]:
    """规范化笔记本配置，保证默认笔记本始终存在且位于首位。"""
    changed = False
    raw_items = config.get("notebooks")
    if not isinstance(raw_items, list):
        raw_items = []
        changed = True

    default = default_notebooks(config)[0]
    for item in raw_items:
        if isinstance(item, dict) and str(item.get("id") or "").strip() == "default":
            default_name = str(item.get("name") or "").strip()
            if default_name:
                default["name"] = default_name
            break
    normalized: list[dict[str, Any]] = [default]
    seen_ids = {"default"}
    seen_paths = {_notebook_path_key(str(default["path"]))}

    for item in raw_items:
        if not isinstance(item, dict):
            changed = True
            continue
        notebook_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        path_text = str(item.get("path") or "").strip()
        if notebook_id == "default":
            continue
        if not notebook_id or not path_text:
            changed = True
            continue
        path_key = _notebook_path_key(path_text)
        if notebook_id in seen_ids or path_key in seen_paths:
            changed = True
            continue
        if not _notebook_dir_exists(path_text):
            changed = True
            continue
        normalized.append(
            {
                "id": notebook_id,
                "name": name or Path(path_text).name or "笔记本",
                "path": path_text,
                "is_default": False,
            }
        )
        seen_ids.add(notebook_id)
        seen_paths.add(path_key)

    active_id = str(config.get("active_notebook_id") or "").strip()
    if active_id and active_id not in seen_ids:
        config["active_notebook_id"] = "default"
        changed = True

    last_selected_record_key = str(config.get("last_selected_record_key") or "")
    if ":" in last_selected_record_key:
        last_selected_notebook_id = last_selected_record_key.split(":", 1)[0]
        if last_selected_notebook_id and last_selected_notebook_id not in seen_ids:
            config["last_selected_record_key"] = ""
            changed = True

    raw_selected_keys = config.get("last_selected_record_keys")
    normalized_selected_keys: dict[str, str] = {}
    if isinstance(raw_selected_keys, dict):
        for notebook_id, record_key in raw_selected_keys.items():
            notebook_id_text = str(notebook_id or "").strip()
            record_key_text = str(record_key or "").strip()
            if (
                notebook_id_text
                and notebook_id_text in seen_ids
                and record_key_text.startswith(f"{notebook_id_text}:")
            ):
                normalized_selected_keys[notebook_id_text] = record_key_text
            else:
                changed = True
    else:
        changed = True
    if config.get("last_selected_record_keys") != normalized_selected_keys:
        config["last_selected_record_keys"] = normalized_selected_keys
        changed = True

    if config.get("notebooks") != normalized:
        config["notebooks"] = normalized
        changed = True
    return normalized, changed


def get_notebooks(config: dict | None = None) -> list[dict[str, Any]]:
    """读取规范化后的笔记本配置。"""
    cfg = config or get_config()
    notebooks, _changed = normalize_notebooks(cfg)
    return notebooks


def get_model_root_dir(config: dict | None = None) -> Path:
    """获取模型根目录（data_root/models）。"""
    return (get_data_root(config) / "models").expanduser().resolve()


def get_log_dir(config: dict | None = None) -> Path:
    """获取日志目录（data_root/logs）。"""
    return get_data_root(config) / "logs"


def ensure_dirs(config: dict | None = None) -> None:
    """确保应用需要的目录存在。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data_root = get_data_root(config)
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "data").mkdir(parents=True, exist_ok=True)
    (data_root / "models").mkdir(parents=True, exist_ok=True)
    (data_root / "logs").mkdir(parents=True, exist_ok=True)


def get_config() -> dict:
    """读取配置；不存在或损坏时重建默认配置。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict):
                raise ValueError("配置文件格式无效")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("配置文件损坏，将重建默认配置: %s", exc)
            config = _create_default_config()
        else:
            config, changed = _merge_defaults(config, DEFAULT_CONFIG)
            config, storage_changed = _normalize_storage_paths(config)
            config, normalized = _normalize_model_config(config)
            _notebooks, notebook_changed = normalize_notebooks(config)
            if changed or storage_changed or normalized or notebook_changed:
                save_config(config)
    else:
        config = _create_default_config()

    ensure_dirs(config)
    return config


def _create_default_config() -> dict:
    """创建并保存默认配置。"""
    config = copy.deepcopy(DEFAULT_CONFIG)
    _normalize_storage_paths(config)
    normalize_notebooks(config)
    save_config(config)
    logger.info("已创建默认配置文件: %s", CONFIG_FILE)
    return config


def save_config(config: dict) -> None:
    """保存配置到文件。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def update_config(key: str, value, sub_key: str | None = None) -> dict:
    """更新单个配置项。"""
    config = get_config()
    if sub_key:
        config[key][sub_key] = value
    else:
        config[key] = value
    save_config(config)
    return config


def get_qwen3_asr_gguf_tool_dir(config: dict | None = None) -> Path:
    """返回 GGUF 推理工具目录，按优先级查找。"""
    candidates = _qwen3_asr_gguf_tool_dir_candidates(config or get_config())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _qwen3_asr_gguf_tool_dir_candidates(config: dict) -> list[Path]:
    """按优先级返回 GGUF 推理工具目录候选，兼容源码和 PyInstaller 包。"""
    configured_value = config.get("qwen3_asr_gguf", {}).get("tool_dir")
    candidates: list[Path] = []

    def add(path: Path) -> None:
        expanded = path.expanduser()
        if expanded not in candidates:
            candidates.append(expanded)

    if configured_value:
        add(Path(str(configured_value)))
    add(DEFAULT_QWEN3_ASR_GGUF_TOOL_DIR)

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        root = Path(str(bundle_root))
        add(root / "vendor" / "qwen3-asr-gguf")
        # 兼容历史 spec 中误把目标写成 _internal/vendor 的包内布局。
        add(root / "_internal" / "vendor" / "qwen3-asr-gguf")

    if getattr(sys, "frozen", False):
        exe_root = Path(sys.executable).resolve().parent
        add(exe_root / "_internal" / "vendor" / "qwen3-asr-gguf")

    add(DEV_QWEN3_ASR_GGUF_TOOL_DIR)
    return candidates


def _merge_defaults(config: dict, defaults: dict) -> tuple[dict, bool]:
    """递归补齐缺失配置，保留用户已有值。"""
    changed = False
    merged = copy.deepcopy(config)
    for key, value in defaults.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
            changed = True
        elif isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key], sub_changed = _merge_defaults(merged[key], value)
            changed = changed or sub_changed
    return merged, changed


def _normalize_storage_paths(config: dict) -> tuple[dict, bool]:
    """归一化用户数据目录，避免测试/旧配置把应用带到临时目录。"""
    changed = False
    data_root = get_data_root(config)
    if _is_transient_test_path(data_root):
        config["data_root"] = str(DEFAULT_DATA_ROOT)
        data_root = DEFAULT_DATA_ROOT
        changed = True

    models = config.setdefault("models", {})
    expected_model_root = str((data_root / "models").expanduser().resolve())
    if models.get("root_dir") != expected_model_root:
        models["root_dir"] = expected_model_root
        changed = True
    if "catalog" in models:
        models.pop("catalog", None)
        changed = True

    audio = config.setdefault("audio", {})
    output_dir = audio.get("output_dir")
    if output_dir and _is_transient_test_path(Path(str(output_dir))):
        audio["output_dir"] = str((data_root / "data").expanduser())
        changed = True
    return config, changed


def _is_transient_test_path(path: Path) -> bool:
    """判断路径是否指向 pytest 临时目录，防止测试配置污染真实用户配置。"""
    try:
        resolved = path.expanduser().resolve(strict=False)
        temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    except OSError:
        return False
    if resolved != temp_root and temp_root not in resolved.parents:
        return False
    return any(part.startswith("pytest-") or part.startswith("pytest-of-") for part in resolved.parts)


def _normalize_model_config(config: dict) -> tuple[dict, bool]:
    """标准化模型配置，确保设备和模型值有效。"""
    changed = False
    models = config.setdefault("models", {})

    asr = config.setdefault("selected_asr", {})
    device = str(asr.get("device") or "auto").lower()
    if device == "cuda":
        asr["device"] = "gpu"
        changed = True
    elif device not in {"auto", "cpu", "gpu"}:
        asr["device"] = "auto"
        changed = True

    current_model = asr.get("model")
    if current_model not in DEFAULT_ASR_MODEL_CATALOG_BY_NAME:
        asr["model"] = QWEN3_ASR_GGUF_06B_ID
        asr["model_path"] = ""
        changed = True

    return config, changed
