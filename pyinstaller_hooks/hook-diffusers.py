# PyInstaller hook: bundle diffusers for Create-menu SANA Sprint generation.
import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    hiddenimports: list[str] = []
    datas: list[tuple[str, str]] = []
else:
    from PyInstaller.utils.hooks import collect_data_files, collect_submodules

    hiddenimports = collect_submodules("diffusers")
    datas = collect_data_files("diffusers")
