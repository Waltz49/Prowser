# PyInstaller hook: bundle mflux for Create-menu generation (MLX: hook-mlx.py).
import os

if os.environ.get("PYINSTALLER_MIN_BUILD", "").strip() in ("1", "true", "yes"):
    hiddenimports: list[str] = []
else:
    from PyInstaller.utils.hooks import collect_submodules

    # Skip flux ControlNet / concept-attention submodules (matplotlib, unused paths).
    # cv2 is still bundled: z_image.variants __init__ imports controlnet at load time.
    hiddenimports = [
        name
        for name in collect_submodules("mflux")
        if ".controlnet" not in name and ".concept_attention" not in name
    ]
