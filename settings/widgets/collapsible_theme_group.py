#!/usr/bin/env python3
"""Collapsible section for the Settings theme tab."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QStyle,
    QStyleOptionGroupBox,
    QVBoxLayout,
    QWidget,
)

import thumbnails.thumbnail_constants as tc

_COLLAPSED_PREFIX = "\u25b6 "  # ▶
_EXPANDED_PREFIX = "\u25bc "  # ▼

THEME_COLLAPSE_GROUP_KEYS = (
    "text_background",
    "dialogs",
    "sidebar_chrome",
    "button_settings",
    "thumbnails_selection",
    "browse_colors",
)


def default_theme_settings_groups_expanded() -> dict[str, bool]:
    return {key: False for key in THEME_COLLAPSE_GROUP_KEYS}


def merge_theme_settings_groups_expanded(saved: dict | None) -> dict[str, bool]:
    merged = default_theme_settings_groups_expanded()
    if isinstance(saved, dict):
        for key in THEME_COLLAPSE_GROUP_KEYS:
            if key in saved:
                merged[key] = bool(saved[key])
    return merged


class _ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _ClickableTitleGroupBox(QGroupBox):
    title_clicked = Signal()

    def __init__(self, title: str = "", parent=None):
        super().__init__(title, parent)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._title_rect_contains(event.pos()):
            self.title_clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._title_rect_contains(event.pos()):
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)

    def _title_rect_contains(self, pos) -> bool:
        opt = QStyleOptionGroupBox()
        self.initStyleOption(opt)
        title_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox,
            opt,
            QStyle.SubControl.SC_GroupBoxLabel,
            self,
        )
        return title_rect.contains(pos)


class CollapsibleThemeGroup(QWidget):
    """Theme tab section: collapsed single-line header or expanded QGroupBox, never both."""

    expanded_changed = Signal(str, bool)

    def __init__(self, title: str, parent=None, *, state_key: str = "", expanded: bool = False):
        super().__init__(parent)
        self._title = title
        self._state_key = state_key
        self._expanded = expanded

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._collapsed_header = _ClickableLabel(f"{_COLLAPSED_PREFIX}{title}")
        self._collapsed_header.setStyleSheet(f"color: {tc.DIALOG_TEXT_COLOR_HEX}; padding: 2px 0px;")
        self._collapsed_header.clicked.connect(self._expand)

        self._group_box = _ClickableTitleGroupBox(f"{_EXPANDED_PREFIX}{title}")
        self._group_box.title_clicked.connect(self._collapse)
        self._content_layout = QVBoxLayout(self._group_box)

        root.addWidget(self._collapsed_header)
        root.addWidget(self._group_box)
        self._apply_expanded_state()

    def state_key(self) -> str:
        return self._state_key

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._apply_expanded_state()
        if self._state_key:
            self.expanded_changed.emit(self._state_key, self._expanded)

    def _expand(self) -> None:
        self.set_expanded(True)

    def _collapse(self) -> None:
        self.set_expanded(False)

    def _apply_expanded_state(self) -> None:
        self._collapsed_header.setVisible(not self._expanded)
        self._group_box.setVisible(self._expanded)
