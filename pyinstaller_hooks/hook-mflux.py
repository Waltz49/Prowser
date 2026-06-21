# PyInstaller hook: bundle mflux for Create-menu generation (MLX: hook-mlx.py).
import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    hiddenimports: list[str] = []
else:
    from PyInstaller.utils.hooks import collect_submodules

    hiddenimports = collect_submodules("mflux")
