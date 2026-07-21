# Prowser — Image Browser

Prowser is a native macOS image browser for Apple Silicon, built with Python, PySide6, and Qt. It is a general purpose image browser that can be used to browse images, and it contains some very simple features for creating and modifying images. 

While it is primarily designed as an image viewer and organizer, it is also a simple way of experimenting with local AI generation and manipulation.

The latest installable file DMG is at the [website](https://waltzremote.com/).

The first time you use AI-based features (similarity sort, text search, or Create) the app downloads and caches models; that pass can be slow, later use is much faster. Some models will require a [huggingface](https://huggingface.co/) account and token to download. 

## Features (partial list)

- Browse images in a grid or fullscreen with keyboard and mouse
- Move, copy, rename, delete (to Trash), lock files, and undo deletes
- Search by image similarity, image description, duplicates, and face recognition
- Slideshows, EXIF tools, external editor integration, set desktop wallpaper
- Local AI image generation and manipulation (**Image** menu) when dependencies are installed
- Models for similarity sort, text search, and face recognition and AI image manipulation are downloaded automatically the first time you use them.

Press **F1** or **/** in the app for keyboard shortcuts for the current view. See [KEYBOARD.md](KEYBOARD.md) for a full list.

## Requirements (running from source)

- **macOS** on Apple Silicon. This was written to run on a 16GB M2 MacBook Air.
- **Python 3.14** if run from source (DMG files include all dependencies)
- Dependencies listed in `requirements.txt` (`setup.sh` installs from `minimal_requirements.txt`; use `requirements.txt` for the complete set, including `peft` for SD 1.5 LoRAs)

## Permissions

The first time you run the app, MacOS will ask for a bunch of permissions to allow the app to list and read images.
If you install the app from the DMG, you can make Prowser the default image viewer through normal MacOS settings.
It is best to close and reopen the app after granting permissions.  If the app seems to hang on startup from another program like VS Code, you may need to grant permissions to that program as well (like full disk access if you trust it).

Due to MacOS restrictions, the "View Copy of Trash" feature is unavailable when running from the bundled app.

## Starting Prowser

From the installed app: Any normal app launch method (Finder, Spotlight, Dock, etc.)

From source (GitHub or a copy of the source folder in the DMG): ./setup.sh (once) and ./run.sh <with parameters>

Use `-h` or `--help` for command-line options.

## Install and run — from source
   You can pass a folder or other arguments, for example:

   ```bash
   ./run.sh ~/Pictures
   ./run.sh -l 0 ~/Downloads/
   ```

If you change the code, `./run.sh` again after saving. You only need to run `./setup.sh` when dependencies change.

## To Build your own app bundle

From a source directory that already has a venv from `setup.sh`:

```bash
./pyInstallerBuild.sh [--min]
```
 
`--min` excludes image generation or AI manipulation dependencies so only basic browser and search features are included.

To create an installation DMG file after creating the app bundle:

```bash
./build_dmg.sh
```

## Settings (Profiles)

Settings and caches live under `~/.prowser/` by default. Open the settings dialog with **⌘,** (Command–comma).
To use a different profile directory:

```bash
./run.sh -p ~/.prowser-test
```

The `-p` path uses the same layout as `~/.prowser/` below.

New files created by AI go to `~/Downloads` by default; change that in the settings dialog (**Image creation directory**).

### Profile layout

```
~/.prowser/                          # or path passed to -p
├── data/
│   ├── settings.json                # app preferences
│   ├── instance.lock                # single-instance lock
│   ├── chat_session_settings.json   # chat pane preferences
│   ├── chat_session_data.json       # saved conversation (when enabled)
│   └── chat_session_images/         # chat images kept across restarts
├── logs/
│   ├── image_browser_print_<uid>.log  # Tools → Debug → View log
│   ├── image_browser_message_debug.log
│   ├── messages.log
│   ├── keyboard.log
│   └── drag_drop.log
├── tmp/                             # disposable work files (see below)
│   ├── chat_conversation/<id>/    # ephemeral chat image copies
│   ├── wallpaper/                   # wallpaper scratch
│   ├── pixelmator/                  # Pixelmator export staging
│   ├── kml/                         # map KML export and rotated previews
│   ├── audio/                       # audio scratch cache
│   ├── imagegen-*                   # generation/infill/mask intermediates
│   ├── whisper-*.wav                # voice-input scratch audio
│   └── say-exit-*.wav               # exit-speech scratch audio
├── cache/
│   ├── image_browser_cache/
│   │   ├── thumbnails/
│   │   └── metadata/
│   ├── hashes/
│   └── image_recognition/           # similarity, CLIP, face models/cache
```

### Temporary and scratch files

Most short-lived work files live under **`~/.prowser/tmp/`** (or `{profile}/tmp/`). That includes image-generation intermediates, infill/mask exports, wallpaper and Pixelmator staging, map KML exports, ephemeral chat image copies, and short WAV/audio scratch files.

Override the work-temp root in **Settings → Temporary files directory**; when blank, the default is `{profile}/tmp/`.

**Safe cleanup** (quit Prowser first):

```bash
rm -rf ~/.prowser/tmp
```

Persistent chat (conversation JSON and images under `data/chat_session_*`) is kept separately when **Preserve chat across sessions** is enabled.

**Outside the profile** (still used by the app):

| Location | Purpose |
|----------|---------|
| `/tmp/image_browser_pipe_<username>` | Named pipe for controlling a running instance ([API.md](API.md)) |
| `/tmp/trashes-<username>` | Temporary “view copy of trash” browse folder; removed on quit |
| `/tmp/exception.txt` | Debug decorator output (cleared at startup) |
| `/tmp/prowserfault.log` | Thread dumps when signal `USR1` is sent |
| `/tmp/slideshow2.log`, `/tmp/points.txt` | Slideshow2 debug output |
| System temp dir | Brief atomic-write scratch for cache/index updates |
| Next to edited images | `*.tmp` sidecar files during EXIF writes |

Generated images saved by the user go to the configured **image creation directory** (default `~/Downloads`), not under the profile.

## Supported formats

Common formats include JPEG, PNG, GIF, BMP, TIFF, WebP, SVG, HEIC, and HEIF. Not every feature (for example all EXIF operations) applies to every format.

## Development

### Entry and layout

- **Entry:** `prowser.py` 

AI related tasks run in separate processes, not on the UI thread. You can force processes vs threads with the `--background [process|thread]` flag.
By default, the app uses threads when bundled into an app, and processes when run from source.

## More documentation

- [KEYBOARD.md](KEYBOARD.md) — shortcuts
- [API.md](API.md) — pipe API for controlling a running instance
- [IMAGE_CREATE_PLUGINS.md](IMAGE_CREATE_PLUGINS.md) — **Image** menu and local generation
- [ARCHITECTURE.md](ARCHITECTURE.md) — code structure and module map (for contributors)
- [tools/README.md](tools/README.md) — standalone dev scripts (not part of the app bundle)

## License

See [LICENSE](LICENSE) (Business Source License).
