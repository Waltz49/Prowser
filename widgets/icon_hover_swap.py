"""Swap QPushButton icons on mouse hover (PNG/SVG pairs or procedural icons)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton


class IconHoverSwap(QObject):
    """Event filter that swaps button icons on hover enter/leave."""

    def __init__(
        self,
        button: QPushButton,
        normal_icon: QIcon,
        hover_icon: QIcon,
    ) -> None:
        super().__init__(button)
        self._button = button
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon
        self._active = False
        button.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        button.installEventFilter(self)
        self._sync_icon()

    def set_active(self, active: bool) -> None:
        """When active, show the hover icon at rest (toggle-on affordance)."""
        self._active = bool(active)
        self._sync_icon()

    def _sync_icon(self) -> None:
        if self._button.underMouse() or self._active:
            self._button.setIcon(self._hover_icon)
        else:
            self._button.setIcon(self._normal_icon)

    def set_icons(self, normal_icon: QIcon, hover_icon: QIcon) -> None:
        """Update icon pair (e.g. when toggle state changes)."""
        self._normal_icon = normal_icon
        self._hover_icon = hover_icon
        self._sync_icon()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._button:
            if event.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave):
                self._sync_icon()
        return False


def attach_icon_hover_swap(
    button: QPushButton,
    normal_icon: QIcon,
    hover_icon: QIcon,
) -> IconHoverSwap:
    """Enable hover icon swap on an existing button."""
    return IconHoverSwap(button, normal_icon, hover_icon)


def icon_pair_from_assets(normal_name: str, hover_name: Optional[str] = None) -> tuple[QIcon, QIcon]:
    """Load normal/hover icons from assets; hover falls back to normal."""
    from theme.theme_base import asset_path

    normal = QIcon(asset_path(normal_name))
    hover_path = hover_name or normal_name.replace(".png", "_hover.png").replace(".svg", "_hover.svg")
    hover = QIcon(asset_path(hover_path))
    return normal, hover
