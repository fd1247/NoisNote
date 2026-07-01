from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def load_demo_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "demo"
        / "model_test"
        / "llama-cpp"
        / "qwen3_asr_gguf_release_demo.py"
    )
    spec = importlib.util.spec_from_file_location("qwen3_asr_gguf_release_demo", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAlignerConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeASREngineConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeExporters:
    @staticmethod
    def export_to_txt(path: str, result) -> None:
        Path(path).write_text(result.text, encoding="utf-8")

    @staticmethod
    def export_to_srt(path: str, result) -> None:
        Path(path).write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

    @staticmethod
    def export_to_json(path: str, result) -> None:
        items = [
            {
                "text": item.text,
                "start": item.start_time,
                "end": item.end_time,
            }
            for item in result.alignment.items
        ]
        Path(path).write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def test_default_aligner_model_dir_points_to_noisnote_models() -> None:
    demo = load_demo_module()

    path = demo._default_aligner_model_dir()

    assert path.parts[-3:] == ("NoisNote", "models", "Qwen3-ForceAligner-0.6B-gguf")
    assert path.parts[-4] == "Documents"


def test_model_dir_candidates_prefer_noisnote_models(monkeypatch, tmp_path: Path) -> None:
    demo = load_demo_module()
    monkeypatch.setattr(demo.Path, "home", lambda: tmp_path)

    candidates = demo._model_dir_candidates(tmp_path / "tool", "0.6B")

    assert candidates[0] == tmp_path / "Documents" / "NoisNote" / "models" / "Qwen3-ASR-GGUF-0.6B"
    assert candidates[1] == tmp_path / "Documents" / "NoisNote" / "models" / "Qwen3-ASR-0.6B"
    assert candidates[2] == tmp_path / "Documents" / "AudioRecorder" / "models" / "Qwen3-ASR-GGUF-0.6B"


def test_timestamp_config_uses_independent_aligner_dir(tmp_path: Path) -> None:
    demo = load_demo_module()
    args = SimpleNamespace(
        model_dir=tmp_path / "asr",
        aligner_model_dir=tmp_path / "aligner",
        timestamp=True,
        device="cpu",
        use_dml=False,
        n_ctx=2048,
        chunk_size=40.0,
        memory_num=1,
    )

    config = demo._build_config(args, FakeASREngineConfig, FakeAlignerConfig)

    assert config.enable_aligner is True
    assert config.model_dir == str(tmp_path / "asr")
    assert config.align_config.model_dir == str(tmp_path / "aligner")
    assert config.align_config.encoder_frontend_fn == "qwen3_aligner_encoder_frontend.int4.onnx"
    assert config.align_config.encoder_backend_fn == "qwen3_aligner_encoder_backend.int4.onnx"
    assert config.align_config.llm_fn == "qwen3_aligner_llm.q4_k.gguf"


def test_check_files_reports_missing_aligner_files(tmp_path: Path) -> None:
    demo = load_demo_module()
    asr_dir = tmp_path / "asr"
    aligner_dir = tmp_path / "aligner"
    asr_dir.mkdir()
    aligner_dir.mkdir()
    for name in demo.ASR_REQUIRED_FILES:
        (asr_dir / name).write_text("", encoding="utf-8")

    config = SimpleNamespace(
        model_dir=asr_dir,
        encoder_frontend_fn=demo.ASR_REQUIRED_FILES[0],
        encoder_backend_fn=demo.ASR_REQUIRED_FILES[1],
        llm_fn=demo.ASR_REQUIRED_FILES[2],
        enable_aligner=True,
        align_config=SimpleNamespace(
            model_dir=aligner_dir,
            encoder_frontend_fn=demo.ALIGNER_REQUIRED_FILES[0],
            encoder_backend_fn=demo.ALIGNER_REQUIRED_FILES[1],
            llm_fn=demo.ALIGNER_REQUIRED_FILES[2],
        ),
    )

    try:
        demo._check_files(config)
    except FileNotFoundError as exc:
        message = str(exc)
    else:
        raise AssertionError("missing aligner files should fail")

    assert "[aligner]" in message
    assert "qwen3_aligner_encoder_frontend.int4.onnx" in message
    assert "qwen3_aligner_llm.q4_k.gguf" in message


def test_alignment_summary_tracks_count_monotonic_and_samples(tmp_path: Path) -> None:
    demo = load_demo_module()
    args = SimpleNamespace(timestamp=True, aligner_model_dir=tmp_path / "aligner")
    items = [
        SimpleNamespace(text="你", start_time=0.0, end_time=0.2),
        SimpleNamespace(text="好", start_time=0.2, end_time=0.5),
    ]
    result = SimpleNamespace(alignment=SimpleNamespace(items=items))

    summary = demo._build_alignment_summary(
        args,
        result,
        tmp_path / "transcript.srt",
        tmp_path / "timestamps.json",
    )

    assert summary["requested"] is True
    assert summary["enabled"] is True
    assert summary["items_count"] == 2
    assert summary["monotonic"] is True
    assert summary["first_item"] == {"text": "你", "start": 0.0, "end": 0.2}
    assert summary["last_item"] == {"text": "好", "start": 0.2, "end": 0.5}


def test_empty_timestamp_alignment_is_validation_failure(tmp_path: Path) -> None:
    demo = load_demo_module()
    args = SimpleNamespace(timestamp=True, aligner_model_dir=tmp_path / "aligner")
    result = SimpleNamespace(alignment=None)

    summary = demo._build_alignment_summary(args, result, None, None)

    assert summary["items_count"] == 0
    assert demo._timestamp_validation_failed(args, summary) is True


def test_write_outputs_includes_alignment_summary_and_files(tmp_path: Path) -> None:
    demo = load_demo_module()
    args = SimpleNamespace(
        output_dir=tmp_path,
        timestamp=True,
        aligner_model_dir=tmp_path / "aligner",
        audio=tmp_path / "audio.wav",
        model_dir=tmp_path / "asr",
        device="cpu",
        use_dml=False,
    )
    items = [SimpleNamespace(text="hello", start_time=0.0, end_time=1.0)]
    result = SimpleNamespace(
        text="hello",
        performance={"align_dec_time": 0.1},
        alignment=SimpleNamespace(items=items),
    )

    summary = demo._write_outputs(args, result, {}, FakeExporters, {}, {})

    assert summary["items_count"] == 1
    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == "hello"
    assert (tmp_path / "transcript.srt").exists()
    assert json.loads((tmp_path / "timestamps.json").read_text(encoding="utf-8"))[0]["text"] == "hello"
    payload = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert payload["alignment"]["items_count"] == 1
    assert payload["alignment"]["monotonic"] is True
