# PyInstaller hook: bundle accelerate (used by diffusers pipelines).
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("accelerate")
