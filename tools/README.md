# Development and standalone tools

Scripts in this folder and at the repository root are **not** part of the Prowser application bundle. They are kept for development, diagnostics, and one-off tasks.

Run from the repo root with the project virtual environment active:

```bash
source venv_image_browser/bin/activate
python tools/<script>.py
```

Some older scripts still live at the repo root; they are listed below for reference.

## Root-level scripts (not imported by the app)

| Script | Purpose |
|--------|---------|
| `block_test.py` | Ad-hoc blocking/threading experiments |
| `fast_test.py` | Quick performance checks |
| `jit_test.py` | JIT compilation tests |
| `create_sample_images.py` | Generate sample images for manual testing |
| `gemma4_voice_vision_demo.py` | Standalone voice + vision demo (not the image browser) |
| `hfmodels.py` | Hugging Face model utilities |
| `list_models.py` | List / manage Hugging Face models |
| `prowser_say_exit.py` | Speech exit environment reporter |
| `qt_key_debug.py` | Qt keyboard event debugging |
| `quick_person_search.py` | Person search utility (also used from menus) |
| `random_images_launcher.py` | Launch browser with random images from recents |
| `send_one_file.py` | Pipe API test helper (`API.md`) |
| `generate_minimal_requirements_questionable.py` | Alternate requirements generator (legacy) |

## PyInstaller note

Several of these filenames appear in `pyinstaller_optional_packages.py` under `ANALYZER_SKIP_FILENAMES` so they are excluded from bundle analysis. If you move a script, update that list.

## Application tests

Automated tests live in `tests/` and are run with pytest—not the `*_test.py` scripts at the repo root.
