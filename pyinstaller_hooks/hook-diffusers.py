# PyInstaller hook: bundle diffusers for Create-menu SANA Sprint generation.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = collect_submodules("diffusers")
datas = collect_data_files("diffusers")
