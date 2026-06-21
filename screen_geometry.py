#!/usr/bin/env python3
"""Physical screen size in logical points (macOS NSScreen / Qt fallback)."""

from typing import Optional

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

try:
    from AppKit import NSScreen

    MACOS_SCREEN_AVAILABLE = True
except ImportError:
    MACOS_SCREEN_AVAILABLE = False
    NSScreen = None


def get_physical_screen_size(fallback_size: Optional[QSize] = None) -> QSize:
    """
    Screen size in points for display/wallpaper sizing.
    Uses NSScreen.frame() or QScreen.geometry() — not backing-store pixels.
    """
    try:
        if MACOS_SCREEN_AVAILABLE and NSScreen:
            screen = NSScreen.mainScreen()
            if screen:
                frame_size = screen.frame().size
                return QSize(int(frame_size.width), int(frame_size.height))
    except Exception:
        pass

    try:
        app = QApplication.instance()
        if app and app.primaryScreen():
            geom = app.primaryScreen().geometry()
            return QSize(geom.width(), geom.height())
    except Exception:
        pass

    if fallback_size is not None:
        return fallback_size
    return QSize(1920, 1080)
