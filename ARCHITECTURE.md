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

- **Navigation / display:** `browser_window/managers/navigation_manager`, `image_display_manager`, `thumbnails/view_manager`, `view_mode_manager`, `selection_manager`
- **Files:** `browser_window/managers/directory_loader`, `files/file_operations_manager`, `files/file_tree_handler`, `refresh_manager`, `sorting_manager` (root), `lock_manager`
- **Thumbnails:** `browser_window/managers/thumbnail_display_manager`, `cache/image_cache`, `thumbnails/thumbnail_canvas`, `thumbnails/list_canvas`
- **Views:** `files/browse_view_handler`, `thumbnails/combined_sidebar_widget`, `thumbnails/information_sidebar`
- **AI / similarity:** `browser_window/managers/similarity_search_manager`, `search/cnn_image_similarity_sorter`, `background_clip_controller`
- **Slideshow:** `slideshow/slideshow_manager`, `slideshow2_manager`, `slideshow3_manager`
- **UI chrome:** `menu_manager`, `keyboard_handler` (root), `ui_layout_manager`, `sidebar_manager`, `status_bar_config`
- **Settings UI:** `settings_dialog` (+ `settings/widgets/multi_row_tab_widget.py`)
- **Image generation:** `imagegen_plugins/` (registry, worker, dialogs)
- **Workers / background:** `workers/` (model tasks, clip worker, beachball guards, idle detector)

## Shared utilities (new / consolidated)

- `files/prsort_io.py` — `.prsort` parse (lock + custom sort)
- `screen_geometry.py` — physical screen size in points
- `path_exclusions.py` — exclusions + `prune_walk_dirs` for directory walks
- `list_utils.dedupe_preserve_order`
- `workers/beachball_fix.py` — refresh/thumbnail/generate concurrency guards

## Image I/O stack

`pil_image_io` → `exif/exif_image_loader` / `worker_image_loader` → caches (`cache/image_cache`, `background_thumbnail_cache`)

## Package boundaries

Flat feature packages at repo root (move-only repackaging; see `docs/restructure-plan.md`):

| Package | Role |
|---------|------|
| `browser_window/` | Main-window managers, dialogs, sidebar |
| `imagegen_plugins/` | Image generation UI, registry, pipelines |
| `slideshow/`, `search/`, `cache/`, `faces/`, `workers/`, `files/`, `thumbnails/`, `theme/`, `exif/` | Domain-specific modules |

Rules:

- **Core** (`config`, `file_data_model`, `event_bus`, `sort_mode`, `utils`) must not import UI packages.
- **Feature packages** must not import `image_browser_window`; use `sort_mode`, `event_bus`, and duck-typed `main_window` parameters.
- **`imagegen_plugins/`** must not import `image_browser_window` (import from `browser_window.*` instead).

## Incremental package layout

- `settings/widgets/` — settings UI widgets
- `browser_window/` — extracted main-window UI (managers, dialogs)
- `file_ops/` — placeholder for future `file_operations_manager` slices

## Tests

`tests/` — pytest unit tests (model, prsort, path exclusions). Run:

```bash
source venv_image_browser/bin/activate
python -m pytest tests/ -q
```
