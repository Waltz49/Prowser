# PyInstaller hook: bundle local imagegen_plugins package (Create menu).
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("imagegen_plugins")
