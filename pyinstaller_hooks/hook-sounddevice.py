"""Bundle PortAudio for sounddevice in frozen macOS builds."""

import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    datas: list[tuple[str, str]] = []
    hiddenimports: list[str] = []
else:
    from PyInstaller.utils.hooks import collect_data_files

    datas = collect_data_files("_sounddevice_data")
    hiddenimports = ["sounddevice", "_sounddevice"]
