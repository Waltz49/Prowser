# Prowser — Image Browser

Prowser is a native macOS image browser for Apple Silicon, built with Python, PySide6, and Qt. Browse folders of images in a thumbnail grid or fullscreen, manage files, search and sort, run slideshows, and optionally generate images locally from the **Create** menu.

The latest DMG is at the [website](https://waltzremote.com/).

The first time you use AI-based features (similarity sort, text search, or Create) the app downloads and caches models; that pass can be slow, later use is much faster.

## What you can do

- Browse images in a grid or fullscreen with keyboard and mouse
- Move, copy, rename, delete (to Trash), lock files, and undo deletes
- Sort, filter, find similar images, text search, and find duplicates
- Slideshows, EXIF tools, external editor integration, set desktop wallpaper
- Optional local image generation (**Create** menu) when dependencies are installed

Press **F1** or **/** in the app for keyboard shortcuts for the current view. See [KEYBOARD.md](KEYBOARD.md) for a full list.

## Requirements (running from source)

- **macOS** on Apple Silicon
- **Python 3.14** (`python3.14` on your PATH — see `setup.sh` and `.python-version`)
- Dependencies listed in `minimal_requirements.txt` (installed by `setup.sh`)

## macOS folder access (Desktop, Documents, etc.)

Prowser must **list files** in the folder you open. macOS protects some locations (especially **Desktop**, **Documents**, and **Downloads**) unless the process that launches Python has permission.

| How you launch | What to grant Full Disk Access to |
|----------------|-----------------------------------|
| **Prowser.app** (from DMG) | **Prowser** |
| **`./run.sh` in Terminal** | **Terminal** (or iTerm, etc.) |
| **VS Code / Cursor** integrated terminal or **Run/Debug** | **Code** / **Cursor** (the editor app, not Prowser) |

Without that access, protected folders may show as empty (“No images available”) or log permission errors when reading `.prsort` lock files. The app will show a **Folder Access Denied** warning when listing is blocked.

**To fix:** System Settings → **Privacy & Security** → **Full Disk Access** → enable the app in the table above → quit and restart that app, then open the folder again.

Most folders outside the protected set (for example a project directory under `~/dev`) work without extra steps.

## Install and run — app from the DMG

1. Open the DMG and drag **Prowser.app** to **Applications** (or another location).
2. Launch **Prowser** like any Mac app, or set it as your default image viewer.

To run the bundled app from Terminal:

```bash
~/Applications/Prowser.app/Contents/MacOS/Prowser <options>
```

Use `-h` or `--help` for command-line options.

## Install and run — from source

The DMG includes a **source** folder with the project files. Use this if you want to run or hack on the code without rebuilding the app bundle.

1. Copy the **source** folder from the DMG to somewhere on your Mac (for example `~/Prowser-source`).
2. Open **Terminal** (or your editor’s terminal — see [macOS folder access](#macos-folder-access-desktop-documents-etc) above).
3. Go to that folder:

   ```bash
   cd ~/Prowser-source
   ```

4. Run setup **once** (creates `venv_image_browser` and installs dependencies):

   ```bash
   ./setup.sh
   ```

   This can take a while the first time (PySide6, optional Create-menu packages, etc.).

5. Start Prowser:

   ```bash
   ./run.sh
   ```

   You can pass a folder or other arguments, for example:

   ```bash
   ./run.sh ~/Pictures
   ./run.sh -l 0 ~/Downloads/
   ```

If you change the code in an editor, run `./run.sh` again after saving. You only need `./setup.sh` again when dependencies change.

## Build your own app bundle

From a source directory that already has a venv from `setup.sh`:

```bash
./pyInstallerBuild.sh
```

The app bundle appears under `dist/` (for example `dist/Prowser.app`).

## Settings

Settings and caches live under `~/.prowser/` by default. Open the settings dialog with **⌘.** (Command–period).

To use a different profile directory:

```bash
./run.sh -p ~/.prowser-test
```

## Supported formats

Common formats include JPEG, PNG, GIF, BMP, TIFF, WebP, SVG, HEIC, and HEIF. Not every feature (for example all EXIF operations) applies to every format.

## Development

### Entry and layout

- **Entry:** `main.py` → `ImageBrowserWindow` (`image_browser_window.py`)
- **Flat modules:** most features live as `*_manager.py` files at the repo root (navigation, files, thumbnails, slideshow, etc.)
- **Subpackages:**
  - `imagegen_plugins/` — **Create** menu (registry, worker subprocess, dialogs)
  - `settings/widgets/` — settings UI pieces (e.g. `multi_row_tab_widget.py`)
  - `file_ops/`, `prowser/window/` — placeholders for incremental splits of very large modules

Heavy ML runs in separate processes (`--model-tasks-worker`, `--imagegen-worker` from `main.py`), not on the UI thread.

### Core state (where to look when debugging)

| Piece | Role |
|-------|------|
| `file_data_model.py` | Single source of truth for displayed files, current image path, index, directory, view mode |
| `event_bus.py` | Cross-module events |
| `window_model_bridge.py` | Model Qt signals → EventBus |
| `window_sync.py` | Window updates that write the model (including status bar on path change) |
| `directory_loader.py` | Directory scan and load |
| `configuration_sync_manager.py` | Legacy API/pipe message handling; model writes go through `window_sync` |

Navigation and refresh rules are documented in comments in `file_data_model.py` and `refresh_manager.py`.

### Shared helpers

- `prsort_io.py` — custom sort / lock files (`.prsort`)
- `screen_geometry.py` — screen size for wallpaper / fit
- `path_exclusions.py` — ignored paths and directory-walk pruning
- `pil_image_io.py` → `exif_image_loader.py` / `worker_image_loader.py` — image loading
- `beachball_fix.py` — guards against concurrent refresh/thumbnail work

### Tests

```bash
source venv_image_browser/bin/activate
pip install pytest   # if not already installed
python -m pytest tests/ -q
```

Tests cover `FileDataModel`, `.prsort` parsing, and path exclusions (no GUI).

More detail: [ARCHITECTURE.md](ARCHITECTURE.md).

## More documentation

- [KEYBOARD.md](KEYBOARD.md) — shortcuts
- [API.md](API.md) — pipe API for controlling a running instance
- [IMAGE_CREATE_PLUGINS.md](IMAGE_CREATE_PLUGINS.md) — **Create** menu and local generation
- [ARCHITECTURE.md](ARCHITECTURE.md) — code structure and module map (for contributors)

## License

See [LICENSE](LICENSE) (Business Source License).
