# PyInstaller hook: bundle mflux for Create-menu generation (MLX: hook-mlx.py).
import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    hiddenimports: list[str] = []
else:
    from PyInstaller.utils.hooks import collect_submodules

    # ControlNet / concept-attention import cv2 and matplotlib; Prowser does not
    # use those mflux variants, and bundling them pulls ~120MB of unused libs.
    hiddenimports = [
        name
        for name in collect_submodules("mflux")
        if ".controlnet" not in name and ".concept_attention" not in name
    ]
