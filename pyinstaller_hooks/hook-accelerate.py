# PyInstaller hook: bundle accelerate (used by diffusers pipelines).
import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    hiddenimports: list[str] = []
else:
    from PyInstaller.utils.hooks import collect_submodules

    hiddenimports = collect_submodules("accelerate")
