# Task 8 Report

## Outcome

- Remote audio completion now has regression coverage proving it queues processing through the shared record-ready path.
- Manual retry while busy now enqueues overwrite processing instead of showing the busy modal, while still preserving immediate missing-record and missing-audio validation.
- Manual summarize while busy now enqueues summary-only processing instead of showing the busy modal, while still preserving immediate missing-record and missing-transcript validation.

## Files Changed

- `src/handlers/transcription.py`
- `src/handlers/summary.py`
- `tests/test_qt_remote_import.py`
- `tests/test_qt_main_window_p0.py`

## Verification

- `python -m pytest tests/test_qt_remote_import.py -q`
- `python -m pytest tests/test_qt_main_window_p0.py::test_import_entry_allowed_while_processing tests/test_qt_main_window_p0.py::test_new_recording_entry_allowed_while_processing tests/test_qt_main_window_p0.py::test_retry_transcription_cancel_keeps_generated_files tests/test_qt_main_window_p0.py::test_retry_transcription_confirm_text_is_user_friendly tests/test_qt_main_window_p0.py::test_retry_transcription_without_audio_uses_audio_file_wording tests/test_qt_main_window_p0.py::test_retry_transcription_queues_when_processing tests/test_qt_main_window_p0.py::test_retry_transcription_busy_missing_audio_shows_error tests/test_qt_main_window_p0.py::test_manual_summary_uses_cached_or_record_transcript tests/test_qt_main_window_p0.py::test_manual_summary_existing_summary_requires_overwrite_confirmation tests/test_qt_main_window_p0.py::test_manual_summarize_queues_when_processing tests/test_qt_main_window_p0.py::test_manual_summarize_busy_missing_transcript_shows_error tests/test_qt_main_window_p0.py::test_cancel_running_processing_task_requests_worker_cancel tests/test_qt_main_window_p0.py::test_task_panel_updates_counts tests/test_qt_main_window_p0.py::test_close_with_running_summary_task_marks_summary_failed tests/test_qt_main_window_p0.py::test_close_with_running_preprocess_task_uses_input_error -q`

## Concerns

- The remote-import audio completion test currently verifies the shared queueing helper rather than a unique remote-only branch, which matches the present architecture but means the regression coverage is indirect.

## Follow-up Fixes

- `src/handlers/task_queue.py`: queued non-summary retranscription now honors `task.options.overwrite_existing` by calling `HistoryService.clear_generated_results()` before `start_transcription()`. This reuses the same cleanup path as the immediate manual retry flow and removes stale transcript, summary, markdown, timeline, and exported SRT outputs.
- `src/tasks/persistence.py`: `TaskQueueStore._is_restoreable()` now restores `summary_only=True` tasks when the record still has a transcript, without requiring audio and without rejecting the task just because a transcript already exists.
- `tests/test_qt_main_window_p0.py`: added regression coverage proving queued overwrite clears generated files before transcription starts.
- `tests/test_task_persistence.py`: added a persistence round-trip test for summary-only queued tasks without audio.
- `tests/test_qt_remote_import.py`: added a negative test proving subtitle completion does not enqueue ASR processing.

## Additional Verification

- `python -m pytest tests/test_task_persistence.py::test_store_round_trips_summary_only_task_without_audio -q`
  - `1 passed in 0.18s`
- `python -m pytest tests/test_qt_remote_import.py::test_remote_subtitle_completion_does_not_enqueue_processing -q`
  - `1 passed in 1.36s`
- `python -m pytest tests/test_qt_main_window_p0.py::test_queued_retry_transcription_clears_generated_files_before_start -q`
  - `1 passed in 1.40s`
- `python -m pytest tests/test_task_persistence.py tests/test_qt_remote_import.py tests/test_qt_main_window_p0.py::test_retry_transcription_queues_when_processing tests/test_qt_main_window_p0.py::test_manual_summarize_queues_when_processing -q`
  - `14 passed in 1.80s`
