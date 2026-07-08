# Final Fix Report

## Changes

- Fixed `MainWindow.closeEvent()` so active recording is included in the unfinished-work confirmation before stopping. Confirmed close now stops through the existing recording save/adopt flow, and processing tasks created during close remain persisted instead of starting.
- Bound queue-owned summary callbacks to the summary worker id, queue task id, and record key. Cancelled/interrupted summary task ids are ignored on late completion/failure so stale callbacks cannot write to the next record or complete the wrong task.
- Reworked remote import tracking to use `active_remote_imports` keyed by unique remote task id, with per-task probe/import callbacks and configured `tasks.max_remote_imports` enforcement.
- Changed task queue persistence path lookup to read `src.app.config.CONFIG_DIR` dynamically and removed the copied `APP_CONFIG_DIR` alias.
- Removed tracked `.superpowers/sdd/task-5-report.md` and `.superpowers/sdd/task-8-report.md`; `.superpowers/` is ignored locally via Git exclude.

## Tests

- Focused regressions:
  - `python -m pytest tests/test_qt_main_window_p0.py::test_close_cancel_keeps_active_recording_running tests/test_qt_main_window_p0.py::test_close_confirm_saves_active_recording_and_persists_queue tests/test_qt_main_window_p0.py::test_cancelled_running_summary_late_completion_does_not_update_next_task tests/test_qt_remote_import.py::test_two_remote_imports_complete_and_fail_with_separate_records tests/test_qt_remote_import.py::test_remote_import_limit_rejects_new_task tests/test_task_persistence.py::test_task_queue_path_uses_patched_config_dir -q`
  - Result: `6 passed in 2.22s`
- Covering suite:
  - `python -m pytest tests/test_qt_main_window_p0.py tests/test_qt_main_window_ch07.py tests/test_qt_remote_import.py tests/test_transcription_worker.py tests/test_task_manager.py tests/test_task_persistence.py -q`
  - Result: `204 passed in 26.80s`

## Concerns

- No real ASR/model/download/WASAPI/network workflows were run, per constraints.

## Final Re-review Fixes

- Routed remote subtitle auto-summary through `enqueue_record_processing(..., summary_only=True)` so subtitle-derived transcripts no longer bypass the serial processing queue when another task is already active.
- Added close-time remote import cleanup: confirmed exit now interrupts/terminates active remote probe/import workers, removes their `active_remote_imports` entries, and marks created remote records with an input error via `HistoryService.mark_input_error(...)`.
- Added regressions for queued remote subtitle summarization, active remote import interruption on close, and probe-only remote cleanup on close.
