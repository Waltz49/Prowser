"""Hover-swapping gear icon button used across settings, chat, and image-gen UI."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QEnterEvent, QIcon
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget

from theme.theme_base import asset_path


class GearIconButton(QPushButton):
    """Square gear button with normal/hover SVG icons."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        size_px: int = 22,
        icon_px: Optional[int] = None,
        tooltip: str = "",
        object_name: str = "gearIconBtn",
        stylesheet: str = "",
    ) -> None:
        super().__init__("", parent)
        self.setObjectName(object_name)
        if tooltip:
            self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._normal_icon = QIcon(asset_path("gear.svg"))
        self._hover_icon = QIcon(asset_path("gear_hover.svg"))
        self._hovered = False
        self._icon_px = icon_px if icon_px is not None else max(14, size_px - 4)
        self._apply_icon()
        if stylesheet:
            self.setStyleSheet(stylesheet)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(size_px, size_px)

    def _apply_icon(self) -> None:
        icon = self._hover_icon if self._hovered else self._normal_icon
        px = self._icon_px
        self.setIcon(icon)
        self.setIconSize(QSize(px, px))

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        self._apply_icon()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self._apply_icon()
        super().leaveEvent(event)
