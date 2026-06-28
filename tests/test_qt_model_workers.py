from __future__ import annotations

import os
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from audio_recorder.app.config import QWEN3_ASR_GGUF_REQUIRED_FILES
from audio_recorder.model_registry.worker import ModelDownloadWorker
from audio_recorder.model_registry.download import default_gguf_downloader
from audio_recorder.model_registry.service import ModelCatalogEntry, format_size


def make_entry() -> ModelCatalogEntry:
    return ModelCatalogEntry(
        name="Qwen3-ASR-0.6B-GGUF",
        display_name="Qwen3-ASR-0.6B GGUF",
        download_url="https://example.test/model.zip",
        local_dir_name="Qwen3-ASR-GGUF-0.6B",
        required_files=QWEN3_ASR_GGUF_REQUIRED_FILES,
    )


def test_download_worker_success(tmp_path: Path) -> None:
    entry = make_entry()
    download_dir = tmp_path / ".download-qwen"
    events = []

    def fake_downloader(entry, target_dir, on_progress, should_cancel):
        target_dir.mkdir(parents=True)
        (target_dir / QWEN3_ASR_GGUF_REQUIRED_FILES[0]).write_text("{}", encoding="utf-8")
        on_progress(45, "写入文件")
        return target_dir

    worker = ModelDownloadWorker(entry, download_dir, downloader=fake_downloader)
    worker.progress.connect(lambda name, percent, text: events.append(("progress", name, percent, text)))
    worker.completed.connect(lambda name, path: events.append(("completed", name, path)))

    worker.run()

    assert ("progress", "Qwen3-ASR-0.6B-GGUF", 45, "写入文件") in events
    assert ("completed", "Qwen3-ASR-0.6B-GGUF", str(download_dir)) in events
    assert (download_dir / QWEN3_ASR_GGUF_REQUIRED_FILES[0]).exists()


def test_download_worker_failed(tmp_path: Path) -> None:
    entry = make_entry()
    events = []

    def fake_downloader(entry, target_dir, on_progress, should_cancel):
        raise RuntimeError("network down")

    worker = ModelDownloadWorker(entry, tmp_path / ".download-qwen", downloader=fake_downloader)
    worker.failed.connect(lambda name, error: events.append(("failed", name, error)))

    worker.run()

    assert events
    assert events[0][0] == "failed"
    assert events[0][1] == "Qwen3-ASR-0.6B-GGUF"
    assert "network down" in events[0][2]


def test_download_worker_cancel_before_start_cleans_temp_dir(tmp_path: Path) -> None:
    entry = make_entry()
    download_dir = tmp_path / ".download-qwen"
    download_dir.mkdir()
    (download_dir / "partial.bin").write_text("partial", encoding="utf-8")
    events = []

    def fake_downloader(entry, target_dir, on_progress, should_cancel):
        raise AssertionError("downloader should not run after cancellation")

    worker = ModelDownloadWorker(entry, download_dir, downloader=fake_downloader)
    worker.cancelled.connect(lambda name: events.append(("cancelled", name)))
    worker.request_cancel()

    worker.run()

    assert events == [("cancelled", "Qwen3-ASR-0.6B-GGUF")]
    assert not download_dir.exists()


def test_default_gguf_downloader_extracts_and_validates_zip(tmp_path: Path) -> None:
    source_zip = tmp_path / "model.zip"
    with zipfile.ZipFile(source_zip, "w") as zip_file:
        for file_name in QWEN3_ASR_GGUF_REQUIRED_FILES:
            zip_file.writestr(f"nested/{file_name}", "model")

    entry = ModelCatalogEntry(
        name="Qwen3-ASR-0.6B-GGUF",
        display_name="Qwen3-ASR-0.6B GGUF",
        download_url=source_zip.as_uri(),
        local_dir_name="Qwen3-ASR-GGUF-0.6B",
        required_files=QWEN3_ASR_GGUF_REQUIRED_FILES,
        estimated_size_bytes=source_zip.stat().st_size,
    )
    download_dir = tmp_path / ".download-qwen"
    events = []

    result_dir = default_gguf_downloader(
        entry,
        download_dir,
        lambda percent, text: events.append((percent, text)),
        lambda: False,
    )

    assert result_dir == download_dir
    assert any("已下载 " in text for _, text in events)
    assert any(f"/{format_size(source_zip.stat().st_size)} |" in text for _, text in events)
    assert any("正在解压" in text for _, text in events)
    for file_name in QWEN3_ASR_GGUF_REQUIRED_FILES:
        assert (download_dir / file_name).exists()
    assert not (download_dir / "model.zip").exists()


def test_default_gguf_downloader_downloads_modelscope_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    file_entries = []
    for file_name in QWEN3_ASR_GGUF_REQUIRED_FILES:
        content = f"model-{file_name}".encode("utf-8")
        (source_dir / file_name).write_bytes(content)
        file_entries.append({"name": file_name, "size": len(content)})

    entry = ModelCatalogEntry(
        name="Qwen3-ASR-0.6B-GGUF",
        display_name="Qwen3-ASR-0.6B GGUF",
        download_url="https://example.test/modelscope/",
        download_sources=[
            {
                "name": "modelscope",
                "type": "files",
                "base_url": f"{source_dir.as_uri()}/",
                "files": file_entries,
            }
        ],
        local_dir_name="Qwen3-ASR-GGUF-0.6B",
        required_files=QWEN3_ASR_GGUF_REQUIRED_FILES,
    )
    download_dir = tmp_path / ".download-qwen"
    events = []
    total_size = sum(item["size"] for item in file_entries)

    result_dir = default_gguf_downloader(
        entry,
        download_dir,
        lambda percent, text: events.append((percent, text)),
        lambda: False,
    )

    assert result_dir == download_dir
    assert any(text == "正在连接模型下载源" for _, text in events)
    assert any(
        text.startswith("已下载 ")
        and f"/{format_size(total_size)} |" in text
        for _, text in events
    )
    assert any("正在解压" in text for _, text in events) is False
    for file_name in QWEN3_ASR_GGUF_REQUIRED_FILES:
        assert (download_dir / file_name).read_bytes() == (source_dir / file_name).read_bytes()


def test_default_gguf_downloader_falls_back_to_github_archive(tmp_path: Path) -> None:
    source_zip = tmp_path / "model.zip"
    with zipfile.ZipFile(source_zip, "w") as zip_file:
        for file_name in QWEN3_ASR_GGUF_REQUIRED_FILES:
            zip_file.writestr(f"nested/{file_name}", "model")

    entry = ModelCatalogEntry(
        name="Qwen3-ASR-0.6B-GGUF",
        display_name="Qwen3-ASR-0.6B GGUF",
        download_url="https://example.test/modelscope/",
        download_sources=[
            {
                "name": "modelscope",
                "type": "files",
                "base_url": f"{(tmp_path / 'missing').as_uri()}/",
                "files": [{"name": QWEN3_ASR_GGUF_REQUIRED_FILES[0], "size": 10}],
            },
            {
                "name": "github",
                "type": "archive",
                "url": source_zip.as_uri(),
            },
        ],
        local_dir_name="Qwen3-ASR-GGUF-0.6B",
        required_files=QWEN3_ASR_GGUF_REQUIRED_FILES,
        estimated_size_bytes=source_zip.stat().st_size,
    )
    events = []

    result_dir = default_gguf_downloader(
        entry,
        tmp_path / ".download-qwen",
        lambda percent, text: events.append((percent, text)),
        lambda: False,
    )

    assert result_dir.exists()
    assert any(text == "正在连接模型下载源" for _, text in events)
    assert any(text == "正在尝试备用下载源" for _, text in events)
    for file_name in QWEN3_ASR_GGUF_REQUIRED_FILES:
        assert (result_dir / file_name).exists()
