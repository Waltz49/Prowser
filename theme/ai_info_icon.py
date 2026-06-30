#!/usr/bin/env python3
"""Shared 'AI' label icon assets (File Information + image-gen prompt toolbar)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap

from theme.theme_base import asset_path
from theme.theme_service import get_active_theme

AI_INFO_ICON_DISPLAY_PX = 16
_AI_HIGHLIGHT_BRIGHTEN = 1.45
_AI_HIGHLIGHT_DARKEN = 0.72


def ai_info_icon_asset_name() -> str:
    th = get_active_theme()
    if getattr(th, "theme_id", "dark") == "light":
        return "ai_icon_info_light.png"
    return "ai_icon_info_dark.png"


def ai_info_icon_highlight_factor() -> float:
    """Brighten on dark themes; darken on light themes for hover/active emphasis."""
    th = get_active_theme()
    if getattr(th, "theme_id", "dark") == "light":
        return _AI_HIGHLIGHT_DARKEN
    return _AI_HIGHLIGHT_BRIGHTEN


def adjust_pixmap_luminance(pixmap: QPixmap, factor: float) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = QColor(image.pixelColor(x, y))
            if color.alpha() == 0:
                continue
            image.setPixelColor(
                x,
                y,
                QColor(
                    min(255, max(0, int(color.red() * factor))),
                    min(255, max(0, int(color.green() * factor))),
                    min(255, max(0, int(color.blue() * factor))),
                    color.alpha(),
                ),
            )
    return QPixmap.fromImage(image)


def ai_info_icon_pixmap(size_px: int = AI_INFO_ICON_DISPLAY_PX) -> QPixmap:
    source = QPixmap(asset_path(ai_info_icon_asset_name()))
    if source.isNull():
        return QPixmap()
    return source.scaled(
        size_px,
        size_px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def create_ai_info_icons(size_px: int = AI_INFO_ICON_DISPLAY_PX) -> tuple[QIcon, QIcon]:
    pixmap = ai_info_icon_pixmap(size_px)
    if pixmap.isNull():
        empty = QIcon()
        return empty, empty
    normal = QIcon(pixmap)
    highlighted = QIcon(
        adjust_pixmap_luminance(pixmap, ai_info_icon_highlight_factor())
    )
    return normal, highlighted


def create_ai_info_icon(size_px: int = AI_INFO_ICON_DISPLAY_PX) -> QIcon:
    return create_ai_info_icons(size_px)[0]
