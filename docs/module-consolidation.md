# Module consolidation summary

Consolidation pass to reduce the number of small, single-caller Python modules in the Prowser app by inlining them into their sole importer and deleting the source files.

## Goal

- Reduce root-level module count (~150 → fewer files)
- Target modules **under ~1,000 lines** imported from **only one place**
- Focus on app code (not standalone scripts like `hfmodels.py`, `jit_test.py`, or PyInstaller hooks)
- Skip modules with **no importers** (utilities/scripts left as-is)

## Results

| Metric | Before | After |
|--------|--------|-------|
| Root-level `.py` files | ~159 | **97** |
| Modules removed | — | **~62** |
| `image_browser_window.py` size | ~10,600 lines | **~10,650 lines** (after split; see below) |
| `browser_window/` package | — | **44 modules**, ~15,600 lines total |

Most reduction came from folding former `image_browser_window` dependencies into that file. Other callers absorbed smaller helper modules without becoming oversized.

## `browser_window/` package (split)

The consolidated `image_browser_window.py` grew to ~25k lines and was hard to maintain. It was split using these practices:

1. **Package by feature** — One module per former component (managers, dialogs, sidebar), not one giant file per layer.
2. **Thin orchestrator** — `image_browser_window.py` keeps only `ImageBrowserWindow` and imports from `browser_window.*`.
3. **Avoid circular imports** — Satellite modules must not import `image_browser_window`. Cross-package callers (e.g. `imagegen_flux_prompt_ai`) import from `browser_window.edit_exif_usercomment_dialog`, not the main window module.
4. **Relative vs absolute** — Prefer `from browser_window.shortcuts_sidebar import …` inside the package for clarity.

### Layout

```
browser_window/
  __init__.py
  beachball_fix.py          # concurrency guards for refresh/thumbnail/generate
  message_handler.py
  window_event_filters.py
  window_model_bridge.py    # FileDataModel → EventBus
  mvc_controller.py
  *manager*.py               # selection, navigation, refresh, layout, etc.
  *dialog*.py / help_*.py   # help, EXIF, about, resize
  preview_widget.py
  right_sidebar_combined.py
  shortcuts_sidebar.py
  sidebar_jobs_widget.py
  thumbnail_context_menu.py
  find_references_dialog.py
  edit_exif_usercomment_dialog.py
  lmstudio_launcher.py
  …
image_browser_window.py     # ImageBrowserWindow only (~10.6k lines)
```

### Import pattern

```python
# image_browser_window.py
from browser_window.selection_manager import SelectionManager
from browser_window.help_dialog import HelpDialog
# …
```

External code should import `ImageBrowserWindow` from `image_browser_window` unchanged. For shared dialogs/helpers, import from `browser_window.<module>`.

## Merge map (by target file)

### `image_browser_window.py` (~41 modules)

Dialogs, managers, and sidebar pieces that were only used by the main window, including:

- **Managers:** `selection_manager`, `navigation_manager`, `refresh_manager`, `sidebar_manager`, `lock_manager`, `rename_status_manager`, `wallpaper_manager`, `background_clip_controller`, `directory_loader`, `directory_history_handler`, `thumbnail_display_manager`, `image_display_manager`, `ui_layout_manager`, `configuration_sync_manager`, `view_mode_manager`, `event_handler`, `similarity_search_manager`
- **UI widgets:** `preview_widget`, `right_sidebar_combined`, `shortcuts_sidebar`, `sidebar_jobs_widget`, `status_notification`
- **Dialogs / help:** `about_dialog`, `help_dialog`, `help_pf`, `help_api`, `help_why`, `help_command_line`, `help_downloading_models`, `delete_exif_dialog`, `reset_exif_dialog`, `reset_date_dialog`, `edit_exif_usercomment_dialog`, `resize_images`, `filter_dialog` (via `status_bar_config` first, then related UI)
- **Infrastructure:** `window_model_bridge`, `mvc_controller`, `window_event_filters`, `idle_detector`, `message_handler`, `beachball_fix`, `background_cache_importer`
- **Context menu:** `thumbnail_context_menu` (includes `find_references_dialog`)

### Other root targets

| Target | Merged modules |
|--------|----------------|
| `view_manager.py` | `cursor_manager`, `canvas_manager`, `list_canvas_manager` |
| `background_clip_worker.py` | `worker_image_loader`, `background_thumbnail_cache` |
| `model_tasks_controller.py` | `frozen_model_tasks_thread` |
| `model_tasks_worker.py` | `lmstudio_flux_prompt`, `mflux_macos_shim`, `imagegen_perf_log` |
| `menu_manager.py` | `random_images_from_recents` |
| `list_models.py` | `hf_model_kind` |
| `settings_dialog.py` | `face_assign_dialog` |
| `file_operations_manager.py` | `undo_applescript_fix` |
| `thumbnail_canvas.py` | `drag_drop_manager` |
| `status_bar_config.py` | `filter_dialog` |
| `similarity_reorder.py` | `list_utils` |
| `window_sync.py` | `model_sync` |
| `main.py` | `apple_events_handler` |
| `quick_person_search.py` | `quick_person_face_pick_dialog` |
| `theme_service.py` | `light_theme_definitions` |
| `edit_exif_usercomment_dialog.py` | `lmstudio_launcher` (later folded into `image_browser_window.py`) |

### `imagegen_plugins` (limited)

- `mflux_macos_shim.py` → `model_tasks_worker.py`
- `imagegen_perf_log.py` → `model_tasks_worker.py` (had multiple importers; callers updated to import from `model_tasks_worker`)

## Post-merge fixes (startup)

The bulk merge left some inlined code incomplete. These were repaired so `./main.py` starts cleanly:

1. **Missing class bodies** — Six modules were deleted before their classes were fully inlined: `window_model_bridge`, `mvc_controller`, `idle_detector`, `background_cache_importer`, `rename_status_manager`, `sidebar_jobs_widget`. Bodies restored from git into `image_browser_window.py`.

2. **Missing imports** — Added `event_bus` constants, `fcntl`, `Path`, `queue`, imagegen job-queue helpers, `HeaderWidget`, `asset_file_url`, status-bar browser helpers, etc.

3. **Circular import** — `imagegen_flux_prompt_ai.py` imported `show_ai_caption_error_dialog` from `image_browser_window` at module load. Switched to a lazy import helper.

4. **`view_manager.py`** — `OVERLAY_HEIGHT` constant from merged `canvas_manager` was not carried over; restored.

5. **Stale lazy imports** — Removed leftover `from window_model_bridge import …` (and similar) inside `ImageBrowserWindow.__init__` after inlining.

## Intentionally not merged

- **No importers:** `jit_test.py`, `defsize.py`, `block_test.py`, `send_one_file.py`, `random_images_launcher.py`, etc.
- **PyInstaller / build:** `pyinstaller_runtime_hook.py`, `pyinstaller_imagegen_paths.py`
- **Multi-caller or large:** `hfmodels.py`, `keyboard_handler.py`, `file_tree_handler.py`, most of `imagegen_plugins/`
- **`__init__.py`** — kept at package root

## Tradeoffs

- **Pros:** Root module count stays low (~97); `image_browser_window.py` is back to a maintainable size; related UI code lives in a named package.
- **Cons:** Import paths are longer (`browser_window.help_dialog`); PyInstaller / `copy_project_files.sh` may need to include the new package if not already covered.

## Verification

After fixes:

```bash
python -m py_compile image_browser_window.py
python -c "import image_browser_window; import main"
./main.py
```

Recommended manual smoke tests: browse/thumbnail views, EXIF edit, image generation dialogs, help menus, right sidebar (Organize / Jobs), background CLIP idle import.

## Package restructure (completed)

Root modules were repackaged into flat feature packages (move-only; see `docs/restructure-plan.md`):

| Package | Modules |
|---------|---------|
| `slideshow/` | slideshow managers + image loader |
| `theme/` | theme definitions + `theme_service` |
| `exif/` | `exif_utils`, `exif_image_loader` |
| `search/` | similarity, reference graph, CNN sorter |
| `cache/` | image/feature caches + `background_cache_importer` |
| `faces/` | face engine, scan, known faces |
| `workers/` | model tasks, clip worker, beachball/idle/message |
| `files/` | browse view, file tree, file operations, I/O helpers |
| `thumbnails/` | canvas, list view, view manager, sidebars |
| `browser_window/` | `managers/`, `dialogs/`, `sidebar/`, `infra/` subpackages |

**Root `.py` count after restructure:** ~44 (core + large UI: `settings_dialog`, `keyboard_handler`, `menu_manager`, `status_bar_config`, `sorting_manager`, build/demos).

## Related change (same period)

**Random seed dialog sync** (`image_gen_dialog.py`): “Generate with Random” now checks the Randomize checkbox in the dialog, including infill-paint (`_settings` panel) and controller fallback paths via `sync_random_seed_setting()`.
