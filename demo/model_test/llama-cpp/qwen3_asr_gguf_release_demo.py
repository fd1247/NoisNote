import argparse
import contextlib
import io
import json
import multiprocessing
import sys
import time
from pathlib import Path

ASR_REQUIRED_FILES = (
    "qwen3_asr_encoder_frontend.int4.onnx",
    "qwen3_asr_encoder_backend.int4.onnx",
    "qwen3_asr_llm.q4_k.gguf",
)

ALIGNER_REQUIRED_FILES = (
    "qwen3_aligner_encoder_frontend.int4.onnx",
    "qwen3_aligner_encoder_backend.int4.onnx",
    "qwen3_aligner_llm.q4_k.gguf",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_tool_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "vendor" / "qwen3-asr-gguf"


def _default_audio() -> Path:
    return Path.home() / "Desktop" / "音视频" / "test_audio_30s.wav"


def _default_aligner_model_dir() -> Path:
    return Path.home() / "Documents" / "NoisNote" / "models" / "Qwen3-ForceAligner-0.6B-gguf"


def _canonical_model_size(model_size: str) -> str:
    normalized = model_size.lower()
    if normalized == "0.6b":
        return "0.6B"
    if normalized == "1.7b":
        return "1.7B"
    raise ValueError(f"Unsupported model size: {model_size}")


def _model_dir_candidates(tool_dir: Path, model_size: str) -> list[Path]:
    model_size = _canonical_model_size(model_size)
    canonical = f"Qwen3-ASR-{model_size}"
    noisnote_model_dir = Path.home() / "Documents" / "NoisNote" / "models"
    legacy_model_dir = Path.home() / "Documents" / "AudioRecorder" / "models"
    candidates = [
        noisnote_model_dir / f"Qwen3-ASR-GGUF-{model_size}",
        noisnote_model_dir / canonical,
        legacy_model_dir / f"Qwen3-ASR-GGUF-{model_size}",
        legacy_model_dir / canonical,
        tool_dir / f"model-{model_size}",
        tool_dir / "models" / canonical,
        tool_dir.parent / f"{canonical}-gguf",
        tool_dir.parent / canonical,
    ]
    if model_size == "0.6B":
        candidates.append(tool_dir / "model")
    return candidates


def _resolve_model_dir(tool_dir: Path, model_size: str, model_dir: Path | None) -> Path:
    if model_dir is not None:
        return model_dir.resolve()

    for candidate in _model_dir_candidates(tool_dir, model_size):
        if candidate.exists():
            return candidate.resolve()

    candidates = "\n".join(str(path) for path in _model_dir_candidates(tool_dir, model_size))
    raise FileNotFoundError(
        f"Cannot find Qwen3-ASR-GGUF {model_size} model directory. "
        f"Pass --model-dir explicitly or place the model in one of:\n{candidates}"
    )


def _import_engine(tool_dir: Path):
    sys.path.insert(0, str(tool_dir))
    from qwen_asr_gguf.inference import ASREngineConfig, AlignerConfig, QwenASREngine, exporters

    return ASREngineConfig, AlignerConfig, QwenASREngine, exporters


def _build_config(args, ASREngineConfig, AlignerConfig):
    align_config = None
    use_dml = args.device == "gpu" or args.use_dml
    onnx_provider = "DML" if use_dml else "CPU"
    if args.timestamp:
        align_config = AlignerConfig(
            model_dir=str(args.aligner_model_dir),
            encoder_frontend_fn=ALIGNER_REQUIRED_FILES[0],
            encoder_backend_fn=ALIGNER_REQUIRED_FILES[1],
            llm_fn=ALIGNER_REQUIRED_FILES[2],
            onnx_provider=onnx_provider,
            llm_use_gpu=use_dml,
            n_ctx=args.n_ctx,
        )

    return ASREngineConfig(
        model_dir=str(args.model_dir),
        # 当前模型为 int4/q4_k 量化版本，显式指定文件名
        encoder_frontend_fn=ASR_REQUIRED_FILES[0],
        encoder_backend_fn=ASR_REQUIRED_FILES[1],
        llm_fn=ASR_REQUIRED_FILES[2],
        onnx_provider=onnx_provider,
        llm_use_gpu=use_dml,
        n_ctx=args.n_ctx,
        chunk_size=args.chunk_size,
        memory_num=args.memory_num,
        verbose=True,
        enable_aligner=args.timestamp,
        align_config=align_config,
    )


def _check_files(config) -> None:
    required: list[tuple[str, Path]] = [
        ("asr", Path(config.model_dir) / config.encoder_frontend_fn),
        ("asr", Path(config.model_dir) / config.encoder_backend_fn),
        ("asr", Path(config.model_dir) / config.llm_fn),
    ]
    if config.enable_aligner and config.align_config:
        required.extend(
            [
                ("aligner", Path(config.align_config.model_dir) / config.align_config.encoder_frontend_fn),
                ("aligner", Path(config.align_config.model_dir) / config.align_config.encoder_backend_fn),
                ("aligner", Path(config.align_config.model_dir) / config.align_config.llm_fn),
            ]
        )

    missing = [f"[{kind}] {path}" for kind, path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing model files:\n" + "\n".join(missing))


def _preview_text(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _parse_hotwords(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    values.extend(args.hotword or [])
    if args.hotwords:
        values.extend(part.strip() for part in args.hotwords.split(","))
    return [value.strip() for value in values if value and value.strip()]


def _build_context(user_context: str, hotwords: list[str]) -> str:
    parts: list[str] = []
    if user_context.strip():
        parts.append(user_context.strip())
    if hotwords:
        parts.append("请优先准确识别以下热词：" + "、".join(hotwords))
    return "\n".join(parts)


def _strip_leading_hotword_prompt(text: str, hotwords: list[str]) -> str:
    marker = "请优先准确识别以下热词："
    cleaned = text.lstrip()
    if not hotwords:
        return cleaned

    hotwords_by_length = sorted({word.strip() for word in hotwords if word.strip()}, key=len, reverse=True)

    def strip_hotword_list(value: str, start: int, has_marker: bool) -> tuple[str, bool]:
        pos = start
        consumed_count = 0
        while pos < len(value):
            while pos < len(value) and value[pos] in " \t\r\n、,，;；":
                pos += 1

            matched = False
            for word in hotwords_by_length:
                if value.startswith(word, pos):
                    pos += len(word)
                    consumed_count += 1
                    matched = True
                    break

            if not matched:
                break

        should_strip = consumed_count > 0 if has_marker else consumed_count >= 2
        return (value[pos:].lstrip(), True) if should_strip else (value, False)

    while True:
        has_marker = cleaned.startswith(marker)
        start = len(marker) if has_marker else 0
        cleaned, changed = strip_hotword_list(cleaned, start, has_marker)
        if not changed:
            return cleaned


def _strip_trailing_hotword_prompt(text: str, hotwords: list[str]) -> str:
    marker = "请优先准确识别以下热词："
    cleaned = text.rstrip()
    if not hotwords:
        return cleaned

    while True:
        marker_pos = cleaned.rfind(marker)
        if marker_pos < 0:
            return cleaned
        tail = cleaned[marker_pos + len(marker) :]
        matched_count = sum(1 for word in hotwords if word and word in tail)
        if matched_count < 2:
            return cleaned
        cleaned = cleaned[:marker_pos].rstrip(" \t\r\n，,。.;；、")


def _strip_hotword_prompt_leak(text: str, hotwords: list[str]) -> str:
    return _strip_trailing_hotword_prompt(_strip_leading_hotword_prompt(text, hotwords), hotwords)


def _alignment_items(result) -> list:
    alignment = getattr(result, "alignment", None)
    items = getattr(alignment, "items", None) if alignment else None
    return list(items or [])


def _alignment_item_to_dict(item) -> dict:
    return {
        "text": str(getattr(item, "text", "") or ""),
        "start": round(float(getattr(item, "start_time", 0.0) or 0.0), 3),
        "end": round(float(getattr(item, "end_time", 0.0) or 0.0), 3),
    }


def _alignment_is_monotonic(items: list) -> bool:
    previous_start = -1.0
    previous_end = -1.0
    for item in items:
        start = float(getattr(item, "start_time", 0.0) or 0.0)
        end = float(getattr(item, "end_time", 0.0) or 0.0)
        if start < previous_start or end < previous_end or end < start:
            return False
        previous_start = start
        previous_end = end
    return True


def _build_alignment_summary(args, result, srt_path: Path | None, timestamps_path: Path | None) -> dict:
    items = _alignment_items(result)
    return {
        "requested": bool(args.timestamp),
        "aligner_model_dir": str(args.aligner_model_dir) if args.timestamp else "",
        "enabled": bool(args.timestamp and items),
        "items_count": len(items),
        "monotonic": _alignment_is_monotonic(items),
        "first_item": _alignment_item_to_dict(items[0]) if items else None,
        "last_item": _alignment_item_to_dict(items[-1]) if items else None,
        "srt_path": str(srt_path) if srt_path else "",
        "timestamps_path": str(timestamps_path) if timestamps_path else "",
    }


def _timestamp_validation_failed(args, alignment_summary: dict) -> bool:
    return bool(args.timestamp and not alignment_summary["items_count"])


def _write_outputs(args, result, timings, exporters, run_parameters, runtime) -> dict:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = args.output_dir / "transcript.txt"
    json_path = args.output_dir / "result.json"
    srt_path = None
    timestamps_path = None
    exporters.export_to_txt(str(txt_path), result)
    if args.timestamp and getattr(result, "alignment", None):
        srt_path = args.output_dir / "transcript.srt"
        timestamps_path = args.output_dir / "timestamps.json"
        exporters.export_to_srt(str(srt_path), result)
        exporters.export_to_json(str(timestamps_path), result)

    alignment_summary = _build_alignment_summary(args, result, srt_path, timestamps_path)

    payload = {
        "engine": "qwen3-asr-gguf-release",
        "run_parameters": run_parameters,
        "runtime": runtime,
        "audio": str(args.audio),
        "model_dir": str(args.model_dir),
        "device": args.device,
        "use_dml": args.device == "gpu" or args.use_dml,
        "timestamp": args.timestamp,
        "alignment": alignment_summary,
        "timings": timings,
        "performance": result.performance,
        "text": result.text,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Transcript: {txt_path}")
    print(f"Result: {json_path}")
    if srt_path:
        print(f"SRT: {srt_path}")
    if timestamps_path:
        print(f"Timestamps: {timestamps_path}")
    return alignment_summary


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Run Qwen3-ASR-GGUF release package with local llama.cpp DLLs.")
    parser.add_argument("--tool-dir", type=Path, default=_default_tool_dir())
    parser.add_argument("--model-size", "--model_size", dest="model_size", choices=("0.6B", "1.7B", "0.6b", "1.7b"), default="0.6B")
    parser.add_argument("--model-dir", type=Path, default=None)
    parser.add_argument("--aligner-model-dir", type=Path, default=_default_aligner_model_dir())
    parser.add_argument("--audio", type=Path, default=_default_audio())
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "outputs" / "qwen3_asr_gguf")
    parser.add_argument("--context", default="")
    parser.add_argument("--hotword", action="append", default=[], help="热词，可重复传入。")
    parser.add_argument("--hotwords", default="", help="逗号分隔的热词列表。")
    parser.add_argument("--language", default=None)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--seek-start", type=float, default=0.0)
    parser.add_argument("--chunk-size", type=float, default=40.0)
    parser.add_argument("--memory-num", type=int, default=1)
    parser.add_argument("--n-ctx", type=int, default=2048)
    parser.add_argument("--device", choices=("cpu", "gpu"), default="cpu", help="cpu 使用 CPU；gpu 使用 DirectML 加速 ONNX Encoder。")
    parser.add_argument("--use-dml", action="store_true", help="兼容旧参数，等同于 --device gpu。")
    parser.add_argument("--timestamp", action="store_true")
    parser.add_argument("--init-only", action="store_true")
    parser.add_argument("--preview-chars", type=int, default=220, help="转录完成后在控制台显示的预览长度。")
    args = parser.parse_args()

    args.model_size = _canonical_model_size(args.model_size)
    args.tool_dir = args.tool_dir.resolve()
    args.model_dir = _resolve_model_dir(args.tool_dir, args.model_size, args.model_dir)
    args.aligner_model_dir = args.aligner_model_dir.expanduser().resolve()
    args.audio = args.audio.resolve()
    args.output_dir = args.output_dir.resolve()

    ASREngineConfig, AlignerConfig, QwenASREngine, exporters = _import_engine(args.tool_dir)
    config = _build_config(args, ASREngineConfig, AlignerConfig)
    _check_files(config)
    use_dml = args.device == "gpu" or args.use_dml
    hotwords = _parse_hotwords(args)
    context = _build_context(args.context, hotwords)
    run_parameters = {
        "tool_dir": str(args.tool_dir),
        "model_size": args.model_size,
        "model_dir": str(args.model_dir),
        "aligner_model_dir": str(args.aligner_model_dir),
        "audio": str(args.audio),
        "output_dir": str(args.output_dir),
        "user_context": args.context,
        "hotwords": hotwords,
        "context": context,
        "language": args.language,
        "duration": args.duration,
        "seek_start": args.seek_start,
        "chunk_size": args.chunk_size,
        "memory_num": args.memory_num,
        "n_ctx": args.n_ctx,
        "device": args.device,
        "use_dml": use_dml,
        "timestamp": args.timestamp,
        "init_only": args.init_only,
    }
    runtime = {
        "requested_device": args.device,
        "model_size": args.model_size,
        "encoder_provider": "DmlExecutionProvider" if use_dml else "CPUExecutionProvider",
        "decoder_backend": "llama.cpp GGUF backend selected by bundled engine",
    }

    engine = None
    timings = {
        "vad_seconds": None,
        "merge_seconds": None,
        "chunk_build_seconds": None,
        "chunk_cut_seconds": None,
        "chunk_transcribe_timings": [],
    }
    try:
        print(f"Tool: {args.tool_dir}")
        print(f"Model size: {args.model_size}")
        print(f"Model: {args.model_dir}")
        if args.timestamp:
            print(f"Aligner: {args.aligner_model_dir}")
        print(f"Audio: {args.audio}")
        print(f"Device: {args.device}, DML: {use_dml}, timestamp: {args.timestamp}")
        print(f"Hotwords: {', '.join(hotwords) if hotwords else '(none)'}")

        t0 = time.perf_counter()
        engine = QwenASREngine(config=config)
        timings["model_load_seconds"] = round(time.perf_counter() - t0, 3)
        print(f"Model loaded in {timings['model_load_seconds']}s")

        if args.init_only:
            return 0

        t1 = time.perf_counter()
        with contextlib.redirect_stdout(io.StringIO()):
            result = engine.transcribe(
                audio_file=str(args.audio),
                context=context,
                language=args.language,
                start_second=args.seek_start,
                duration=args.duration,
            )
        result.text = _strip_hotword_prompt_leak(result.text, hotwords)
        timings["transcribe_seconds"] = round(time.perf_counter() - t1, 3)
        timings["total_seconds"] = round(time.perf_counter() - t0, 3)
        timings["chunk_transcribe_timings"] = [
            {
                "index": 1,
                "seconds": timings["transcribe_seconds"],
                "note": "Qwen3-ASR-GGUF release engine handles internal streaming chunks; per-internal-chunk timings are not exposed.",
            }
        ]
        alignment_summary = _write_outputs(args, result, timings, exporters, run_parameters, runtime)
        if _timestamp_validation_failed(args, alignment_summary):
            print(
                "Timestamp alignment failed: result.alignment.items is empty. "
                "Check the aligner model files and runtime logs.",
                file=sys.stderr,
            )
            return 2
        print(f"Preview: {_preview_text(result.text, args.preview_chars)}")
        return 0
    finally:
        if engine is not None:
            engine.shutdown()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
