# PyInstaller hook: bundle requests (required by transformers/diffusers metadata imports).
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("requests")
