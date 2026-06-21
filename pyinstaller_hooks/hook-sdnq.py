# PyInstaller hook: bundle sdnq for Z-Image Turbo quantized weights.
import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    hiddenimports: list[str] = []
    datas: list[tuple[str, str]] = []
else:
    from PyInstaller.utils.hooks import collect_data_files, collect_submodules

    hiddenimports = collect_submodules("sdnq")
    datas = collect_data_files("sdnq")
