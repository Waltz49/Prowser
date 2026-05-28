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
2. Open **Terminal**.
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

## More documentation

- [KEYBOARD.md](KEYBOARD.md) — shortcuts
- [API.md](API.md) — pipe API for controlling a running instance
- [IMAGE_CREATE_PLUGINS.md](IMAGE_CREATE_PLUGINS.md) — **Create** menu and local generation

## License

See [LICENSE](LICENSE) (Business Source License).
