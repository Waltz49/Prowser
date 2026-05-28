#!/usr/bin/env python3
"""
Shared theme utilities: asset paths for Qt stylesheets and a protocol for theme dataclasses.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

# Assets directory for stylesheet images (Qt ignores base64 data URLs)
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def asset_url(filename: str) -> str:
    """Return Qt stylesheet url() for an asset file. Qt treats file:// as literal path; use plain path."""
    path = os.path.abspath(os.path.join(_ASSETS_DIR, filename)).replace("\\", "/")
    return f"url({path})"


def asset_path(filename: str) -> str:
    """Return absolute path for an asset file (e.g. for QIcon)."""
    return os.path.abspath(os.path.join(_ASSETS_DIR, filename)).replace("\\", "/")


def asset_file_url(filename: str) -> str:
    """Return file:// URL for an asset, for use in HTML img src (e.g. QLabel RichText)."""
    return f"file://{asset_path(filename)}"


@runtime_checkable
class ThemeProtocol(Protocol):
    """Contract for app themes. Add new theme dataclasses implementing these methods."""

    theme_id: str

    def global_stylesheet(self) -> str: ...

    def qmenu_stylesheet(self) -> str: ...

    def main_splitter_stylesheet(self) -> str: ...

    def main_status_bar_chrome_stylesheet(self) -> str: ...

    def floating_progress_bar_stylesheet(self) -> str: ...

    def thumbnail_status_label_stylesheet(self) -> str: ...

    def browse_view_shell_stylesheet(self) -> str: ...

    def browse_filename_textedit_stylesheet(self) -> str: ...

    def browse_filename_document_stylesheet(self) -> str: ...

    def status_bar_context_menu_stylesheet(self) -> str: ...
