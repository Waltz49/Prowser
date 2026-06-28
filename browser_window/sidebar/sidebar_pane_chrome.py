"""Shared sidebar pane background helpers (palette + stylesheet)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QScrollArea, QWidget

from theme.theme_service import get_active_theme


def apply_sidebar_pane_background(widget: QWidget, bg_hex: str) -> None:
    """Pane color via palette so first paint beats global application-background stylesheet."""
    color = QColor(bg_hex)
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Window, color)
    widget.setPalette(palette)
    widget.setAutoFillBackground(True)


def apply_section_pane_shell(widget: QWidget, bg_hex: str, pane_stylesheet: str) -> None:
    """Section/content shells: beat global application-background QWidget rule."""
    apply_sidebar_pane_background(widget, bg_hex)
    widget.setStyleSheet(pane_stylesheet)


def apply_scroll_area_viewport_background(
    scroll_area: QScrollArea,
    bg_hex: Optional[str] = None,
) -> None:
    """QScrollArea viewport: palette fill matching sidebar pane background."""
    viewport = scroll_area.viewport()
    if viewport is None:
        return
    if bg_hex is None:
        bg_hex = get_active_theme().sidebar_background_color_hex
    apply_sidebar_pane_background(viewport, bg_hex)
