# Prowser architecture (code-derived)

Native macOS image browser (PySide6). Entry: `main.py` → `ImageBrowserWindow`.

## Boot

- `run.sh` → `python main.py` (uses `venv_image_browser/`, falls back to `venv/`)
- Frozen workers: `--model-tasks-worker`, `--imagegen-worker` (see `main.py` `_frozen_subprocess_bootstrap`)
- `--profile` / `-p DIR` — alternate profile root (default `~/.prowser`)
- `--background {default,thread,process}` — model-tasks worker thread vs subprocess (`workers/model_tasks_launch.py`)
- `--test-create-deps` — frozen-only diagnostic for Create/Image menu dependencies
- Settings: `~/.prowser/data/settings.json` via `config.ImageBrowserConfig`
- Logs: `~/.prowser/logs` (early stdout also routed via `print_log_redirect.py`)

## Core state

| Component | Role |
|-----------|------|
| `FileDataModel` | Single source of truth: `displayed_images`, `current_image_path`, `current_index`, `current_directory`, `current_view_mode` |
| `EventBus` | Cross-module pub/sub (`event_bus.py` constants) |
| `browser_window/infra/window_model_bridge.py` | Forwards model Qt signals → EventBus |
| `browser_window/infra/mvc_controller.py` | `MVCController`, wired on the main window |
| `window_sync` | Window-level writes to the model (status bar on path change) |
| `ImageBrowserWindow.selected_files` | Multi-select (not the current image) |

Navigation and refresh contracts are documented in `file_data_model.py` and `browser_window/managers/refresh_manager.py`.

## Orchestrator

`image_browser_window.py` wires managers and views. Prefer adding logic in a `*_manager.py` module rather than growing the window file.

### `browser_window/` layout

| Subpackage | Role |
|------------|------|
| `managers/` | Main-window managers (navigation, files, thumbnails, config sync, …) |
| `dialogs/` | About, help, EXIF, find references, … |
| `sidebar/` | Right sidebar (`right_sidebar_combined`, `preview_widget`, `shortcuts_sidebar`, `sidebar_jobs_widget`) |
| `infra/` | `window_model_bridge`, `mvc_controller` |

### Managers (representative)

- **Navigation / display:** `navigation_manager`, `image_display_manager`, `thumbnails/view_manager`, `view_mode_manager`, `selection_manager`, `directory_history_handler`, `event_handler`
- **Files:** `directory_loader`, `files/file_operations_manager`, `files/file_tree_handler`, `refresh_manager`, `sorting_manager` (root), `lock_manager`, `files/file_move_handler`
- **Thumbnails:** `thumbnail_display_manager`, `cache/image_cache`, `thumbnails/thumbnail_canvas`, `thumbnails/list_canvas`, `thumbnail_context_menu`, `thumbnails/thumbnail_operations_manager`
- **Views:** `files/browse_view_handler`, `thumbnails/combined_sidebar_widget` (left), `thumbnails/information_sidebar`
- **AI / similarity:** `similarity_search_manager`, `search/cnn_image_similarity_sorter`, `background_clip_controller`
- **Slideshow:** `slideshow/slideshow_manager`, `slideshow2_manager`, `slideshow3_manager`, `slideshow/slideshow_image_loader`
- **UI chrome:** `menu_manager` (root), `keyboard_handler` (root), `ui_layout_manager`, `sidebar_manager`, `status_bar_config`, `status_notification`, `wallpaper_manager`, `window_event_filters`
- **Settings UI:** `settings_dialog` (+ `settings/widgets/multi_row_tab_widget.py`)
- **Image generation:** `imagegen_plugins/` (registry, worker, dialogs, `image_gen_controller.py`)
- **Workers / background:** `workers/` (model tasks, CLIP worker, message pipe, beachball guards, idle detector)

## Shared utilities

- `files/prsort_io.py` — `.prsort` parse (lock + custom sort)
- `screen_geometry.py` — physical screen size in points
- `path_exclusions.py` — exclusions + `prune_walk_dirs` for directory walks
- `search/similarity_reorder.py` — `dedupe_preserve_order` and similarity reorder helpers
- `prowser_temp_files.py` — temp directory resolution for settings
- `bundle_capabilities.py` — frozen-bundle feature gating (`--min` build)
- `workers/beachball_fix.py` — refresh/thumbnail/generate concurrency guards

## Image I/O stack

`pil_image_io` → `exif/exif_image_loader` / `exif/exif_utils` → caches (`cache/image_cache`, `cache/thumbnail_cache_key`, `cache/background_cache_importer`, `cache/feature_cache_manager`, `cache/cache_prepopulator`) → `workers/background_clip_worker.py`, `workers/window_background_workers.py`

## Package boundaries

Flat feature packages at repo root (see `docs/restructure-plan.md`):

| Package | Role |
|---------|------|
| `browser_window/` | Main-window managers, dialogs, sidebar, infra |
| `imagegen_plugins/` | Image generation UI, registry, `pipelines/`, `lora_catalogs/` |
| `slideshow/`, `search/`, `cache/`, `faces/`, `workers/`, `files/`, `thumbnails/`, `theme/`, `exif/`, `settings/` | Domain-specific modules |
| `file_ops/` | Placeholder for future `file_operations_manager` slices |
| `mtcnn_face_torch/` | Vendored face-detection code |

Rules:

- **Core** (`config`, `file_data_model`, `event_bus`, `sort_mode`, `utils`) must not import UI packages.
- **Feature packages** must not import `image_browser_window`; use `sort_mode`, `event_bus`, and duck-typed `main_window` parameters.
- **`imagegen_plugins/`** must not import `image_browser_window` (import from `browser_window.*` instead).

## Tests

`tests/` — pytest unit tests. Run:

```bash
source venv_image_browser/bin/activate
python -m pytest tests/ -q
```

| File | Covers |
|------|--------|
| `test_file_data_model.py` | `FileDataModel` |
| `test_prsort_io.py` | `files/prsort_io.py` |
| `test_path_exclusions.py` | `path_exclusions.py` |
| `test_prowser_temp_files.py` | `prowser_temp_files.py` |
