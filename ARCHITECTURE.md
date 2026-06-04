# Prowser architecture (code-derived)

Native macOS image browser (PySide6). Entry: `main.py` → `ImageBrowserWindow`.

## Boot

- `run.sh` → `python main.py`
- Frozen workers: `--model-tasks-worker`, `--imagegen-worker` (see `main.py` `_frozen_subprocess_bootstrap`)
- Settings: `~/.prowser/data/settings.json` via `config.ImageBrowserConfig`
- Logs: `~/.prowser/logs`

## Core state

| Component | Role |
|-----------|------|
| `FileDataModel` | Single source of truth: `displayed_images`, `current_image_path`, `current_index`, `current_directory`, `current_view_mode` |
| `EventBus` | Cross-module pub/sub (`event_bus.py` constants) |
| `WindowModelBridge` | Forwards model Qt signals → EventBus |
| `window_sync` | Window-level writes to the model (status bar on path change) |
| `ImageBrowserWindow.selected_files` | Multi-select (not the current image) |

Navigation and refresh contracts are documented in `file_data_model.py` and `refresh_manager.py`.

## Orchestrator

`image_browser_window.py` wires managers and views. Prefer adding logic in a `*_manager.py` module rather than growing the window file.

### Managers (representative)

- **Navigation / display:** `navigation_manager`, `image_display_manager`, `view_manager`, `view_mode_manager`, `selection_manager`
- **Files:** `directory_loader`, `file_operations_manager`, `file_tree_handler`, `refresh_manager`, `sorting_manager`, `lock_manager`
- **Thumbnails:** `thumbnail_display_manager`, `canvas_manager`, `list_canvas_manager`, `image_cache`
- **Views:** `thumbnail_canvas`, `list_canvas`, `browse_view_handler`
- **AI / similarity:** `similarity_search_manager`, `cnn_image_similarity_sorter`, `background_clip_controller`
- **Slideshow:** `slideshow_manager`, `slideshow2_manager`, `slideshow3_manager`
- **UI chrome:** `menu_manager`, `keyboard_handler`, `ui_layout_manager`, `sidebar_manager`, `status_bar_config`
- **Settings UI:** `settings_dialog` (+ `settings/widgets/multi_row_tab_widget.py`)
- **Image generation:** `imagegen_plugins/` (registry, worker, dialogs)

## Shared utilities (new / consolidated)

- `prsort_io.py` — `.prsort` parse (lock + custom sort)
- `screen_geometry.py` — physical screen size in points
- `path_exclusions.py` — exclusions + `prune_walk_dirs` for directory walks
- `list_utils.dedupe_preserve_order`
- `beachball_fix.py` — refresh/thumbnail/generate concurrency guards

## Image I/O stack

`pil_image_io` → `exif_image_loader` / `worker_image_loader` → caches (`image_cache`, `background_thumbnail_cache`)

## Incremental package layout

- `settings/widgets/` — settings UI widgets
- `file_ops/` — future slices of `file_operations_manager.py`
- `prowser/window/` — future slices of `image_browser_window.py`

## Tests

`tests/` — pytest unit tests (model, prsort, path exclusions). Run:

```bash
source venv_image_browser/bin/activate
python -m pytest tests/ -q
```
