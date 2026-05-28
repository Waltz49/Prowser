# PyInstaller hook: bundle mflux for Create-menu generation (MLX: hook-mlx.py).
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("mflux")
