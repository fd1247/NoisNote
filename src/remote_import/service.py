"""远程链接导入主流程。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..audio.preprocess import AudioInputError, AudioPreprocessRequest, normalize_audio
from ..history.service import HistoryRecord, HistoryService
from ..utils.remote_urls import canonicalize_video_url
from .errors import RemoteImportError, RemoteImportErrorKind, message_for_kind, remote_error_from_exception
from .subtitles import normalize_subtitle_file, parse_srt_to_transcript_and_timeline, select_preferred_subtitle
from .types import RemoteImportOptions, RemoteImportResult, RemoteMediaInfo
from .ytdlp_client import YtDlpClient


class RemoteImportService:
    """组织远程链接探测、字幕导入和音频降级。"""

    def __init__(
        self,
        history_service: HistoryService,
        *,
        client: YtDlpClient | None = None,
        config: dict | None = None,
    ):
        self.history_service = history_service
        self.client = client or YtDlpClient()
        self.config = config

    def ensure_available(self) -> None:
        self.client.ensure_available()

    def probe(self, url: str) -> RemoteMediaInfo:
        return self.client.probe(url)

    def import_url(
        self,
        record: HistoryRecord,
        info: RemoteMediaInfo,
        options: RemoteImportOptions,
        progress_callback=None,
    ) -> RemoteImportResult:
        subtitle = select_preferred_subtitle(info, options.preferred_languages)
        subtitle_error: str = ""
        if subtitle:
            try:
                _emit(progress_callback, "正在下载字幕", 30)
                raw_suffix = f".{subtitle.extension.lower().lstrip('.') or 'vtt'}"
                raw_path = record.record_dir / f"external_subtitle.raw{raw_suffix}"
                self.client.download_subtitle(subtitle, raw_path)
                target_path = record.external_subtitle_path
                normalize_subtitle_file(raw_path, target_path)
                transcript, timeline_items = parse_srt_to_transcript_and_timeline(target_path)
                if not transcript.strip():
                    raise RemoteImportError(RemoteImportErrorKind.DOWNLOAD_FAILED, "下载失败", "subtitle is empty")
                self.history_service.save_transcript(record, transcript)
                self.history_service.save_timeline(record, timeline_items)
                metadata = _remote_metadata(info, "subtitle", subtitle)
                self.history_service.save_remote_metadata(record, metadata)
                refreshed = self.history_service.mark_processing_completed(record, "transcription", context=metadata)
                _emit(progress_callback, "字幕已导入", 100)
                return RemoteImportResult(
                    mode="subtitle",
                    record=refreshed,
                    transcript_text=transcript,
                    timeline_items=timeline_items,
                    subtitle_path=target_path,
                    metadata=metadata,
                )
            except Exception as exc:
                subtitle_error = str(exc)
                _cleanup_failed_subtitle_import(record, raw_path, record.external_subtitle_path)
                _emit(progress_callback, "字幕下载失败，正在下载音频", 35)

        if not subtitle:
            _emit(progress_callback, "未找到字幕，正在下载音频", 25)
        try:
            downloaded_audio = self.client.download_audio(info, record.record_dir)
            preprocessing = (self.config or {}).get("audio", {}).get("preprocessing", {})
            request = AudioPreprocessRequest(
                source_path=downloaded_audio,
                record_dir=record.record_dir,
                source_kind="remote_audio",
                target_sample_rate=int(preprocessing.get("target_sample_rate") or 16000),
                target_channels=int(preprocessing.get("target_channels") or 1),
            )
            result = normalize_audio(request, progress_callback=progress_callback, config=self.config)
        except AudioInputError as exc:
            raise RemoteImportError(RemoteImportErrorKind.FFMPEG_FAILED, message_for_kind(RemoteImportErrorKind.FFMPEG_FAILED), exc.details) from exc
        except Exception as exc:
            raise remote_error_from_exception(exc) from exc

        audio_path = record.record_dir / self.history_service.FOLDER_AUDIO
        _move_normalized_audio(result.normalized_audio_path, audio_path)
        metadata = _remote_metadata(info, "audio", None)
        if subtitle_error:
            metadata["remote"]["subtitle_error"] = subtitle_error
        refreshed = self.history_service.save_remote_audio_result(
            record,
            audio_path=audio_path,
            duration_seconds=result.duration_seconds,
            audio_format={
                "sample_rate": result.sample_rate,
                "channels": result.channels,
                "format": "wav",
                "source_format": result.source_format,
            },
            metadata=metadata,
        )
        _cleanup_downloaded_audio(downloaded_audio, record.record_dir, audio_path)
        _emit(progress_callback, "音频已导入", 100)
        return RemoteImportResult(mode="audio", record=refreshed, audio_path=audio_path, metadata=metadata)


def _remote_metadata(info: RemoteMediaInfo, strategy: str, subtitle: Any | None) -> dict[str, Any]:
    original_url = info.url or info.webpage_url
    webpage_url = info.webpage_url or original_url
    canonical_url = canonicalize_video_url(webpage_url or original_url) or webpage_url or original_url
    data: dict[str, Any] = {
        "remote": {
            "url": original_url,
            "original_url": original_url,
            "webpage_url": webpage_url,
            "canonical_url": canonical_url,
            "extractor": info.extractor,
            "title": info.title,
            "video_id": info.video_id,
            "duration_seconds": info.duration_seconds,
            "strategy": strategy,
        },
        "source_type": "remote_url",
        "source_kind": "remote_subtitle" if strategy == "subtitle" else "remote_audio",
    }
    if subtitle is not None:
        data["remote"]["subtitle"] = {
            "language": subtitle.language,
            "name": subtitle.name,
            "extension": subtitle.extension,
            "is_auto": subtitle.is_auto,
        }
        data["transcript_source"] = "external_subtitle_auto" if subtitle.is_auto else "external_subtitle"
    return data


def _emit(callback, text: str, percent: int | None = None) -> None:
    if callback:
        callback(text, percent)


def _cleanup_failed_subtitle_import(record: HistoryRecord, *paths: Path) -> None:
    root = record.record_dir.resolve(strict=False)
    generated_paths = (
        record.transcript_path,
        record.timeline_path,
        record.external_subtitle_path,
        *paths,
    )
    for path in generated_paths:
        target = path.resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError:
            continue
        if target.exists() and target.is_file():
            try:
                target.unlink()
            except OSError:
                continue


def _move_normalized_audio(source: Path, target: Path) -> None:
    source_path = Path(source)
    target_path = Path(target)
    if source_path.resolve(strict=False) == target_path.resolve(strict=False):
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.replace(target_path)


def _cleanup_downloaded_audio(path: Path, record_dir: Path, final_audio_path: Path) -> None:
    target = Path(path).resolve(strict=False)
    root = record_dir.resolve(strict=False)
    final_audio = final_audio_path.resolve(strict=False)
    if target == final_audio:
        return
    try:
        target.relative_to(root)
    except ValueError:
        return
    if target.exists() and target.is_file():
        try:
            target.unlink()
        except OSError:
            return
