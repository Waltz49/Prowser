# macOS fullscreen Space / focus fix (Prowser.app)

## What was broken (original bug)

In the **bundled** app running `--fullscreen` on a dedicated macOS Space, two actions caused a brief Space switch / focus loss:

1. **Submit** on the Edit Image dialog
2. **Press J** to toggle the Jobs pane while a job was running

Dev mode (`python prowser.py`) did not reproduce the Space bounce reliably.

## Root causes (confirmed by runtime logs)

| Cause | What happened |
|-------|----------------|
| **QProcess worker spawn** | Submit started `Prowser.app --model-tasks-worker` — macOS treated the child as a new app activation and jumped Spaces. |
| **MLX on a Qt thread** | Model load on `QThread` disturbed Cocoa fullscreen focus. |
| **Jobs pane native windows** | `_FlowReferenceThumbs` created a child `QWindow` (`_FlowReferenceThumbsClassWindow`) during `refresh_table`, stealing focus. |
| **mflux subprocess probes** | `system_profiler` / `sysctl` during generation caused extra macOS activation. |
| **J key routing** | View menu `QAction` shortcut and status-bar menu path stole focus in the bundle. |

## What we changed (intended fix)

1. **`frozen_model_tasks_thread.py`** — On frozen macOS, run `model_tasks_worker.run_worker_event_loop()` in a plain `threading.Thread` inside the GUI process (no `QProcess` re-exec).
2. **`model_tasks_worker.run_worker_event_loop()`** — Shared command loop for subprocess and inline worker.
3. **`mflux_macos_shim.py`** — Patch mflux to avoid `system_profiler` / `sysctl` subprocess calls.
4. **`sidebar_jobs_widget.py`** — `WA_DontCreateNativeAncestors` / `WA_NativeWindow=False` on job reference thumbs; no orphan `.show()`.
5. **`image_gen_menu.py`** — `QTimer.singleShot(0, …)` defers `start_generation` until after the modal dialog closes.
6. **`image_gen_edit_dialog.py`** — Dialog uses `raise_()` only (no `activateWindow()`).
7. **J key** — Always toggles jobs pane; removed status-bar menu shortcut path and View menu `J` shortcut.

## Regression (jobs “running” but dead)

After the inline worker landed, jobs could **submit but not actually run** in the bundle:

- Jobs pane showed a row as active but **no elapsed time**
- Status bar showed **nothing running**
- Generation never completed

### Cause

`run_worker_event_loop()` accepts an `emit` callback for inline mode, but **`_run_generate`, `_run_caption`, progress helpers, etc. still called `_emit()` which only `print()`s to stdout**.

In subprocess mode stdout is piped to `ModelTasksController._on_stdout`. In inline mode stdout is **not** connected — only the `emit` callback feeds `json_line` → `_handle_worker_line`.

So the controller received `ready`, sent the generate command, and then **never saw** `job_started`, `progress`, or `result`.

### Fix

- `emit_worker_message()` routes to the active inline callback when set, else stdout.
- `run_worker_event_loop()` sets/clears that callback for the loop lifetime.
- `emit_mflux_progress()` uses `emit_worker_message()` instead of printing directly.
- Subprocess `main()` must pass `_stdout_emit` into `run_worker_event_loop`, **not** `_emit` — otherwise `_active_emit` points at `_emit` → `emit_worker_message` → infinite recursion.

## Files involved

| File | Role |
|------|------|
| `frozen_model_tasks_thread.py` | Inline worker thread + Qt signal bridge |
| `model_tasks_controller.py` | Chooses inline vs QProcess worker |
| `model_tasks_launch.py` | `use_inline_model_tasks_worker()` |
| `model_tasks_worker.py` | Worker loop + `emit_worker_message()` |
| `imagegen_plugins/mflux_macos_shim.py` | Block mflux subprocess focus steals |
| `imagegen_plugins/pipelines/mflux_stepwise_progress.py` | Step progress JSON |
| `sidebar_jobs_widget.py` | Non-native job thumbnails |
| `imagegen_plugins/image_gen_menu.py` | Deferred submit after dialog |
| `keyboard_handler.py`, `menu_manager.py`, `status_bar_config.py` | J → jobs pane only |

## Verification

Bundled app after rebuild:

1. Submit Edit Image — no Space switch; status bar indicator appears; elapsed time ticks; image completes.
2. Press J — jobs pane toggles without Space switch.
3. Logs (if tracing enabled): `H-INLINE` on worker start; no `QProcess --model-tasks-worker` on submit.
