#!/usr/bin/env python3
"""Position custom floating QLabel tooltips away from the cursor and on-screen."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QLabel, QMenu, QWidget

TOOLTIP_MARGIN = 10
_OFFSET_X = 12
_OFFSET_Y = 20


def clamp_bounds_for_widget(widget: QWidget | None) -> QRect:
    """Global rect to keep the popup inside (host window, else screen)."""
    if widget is not None:
        win = widget.window()
        if win is not None and win.isVisible() and not isinstance(win, QMenu):
            return win.frameGeometry()
    screen = QGuiApplication.screenAt(QCursor.pos())
    if screen is not None:
        return screen.availableGeometry()
    return QRect(0, 0, 1920, 1080)


def clamp_popup_position(
    global_pos: QPoint, size, bounds: QRect, *, margin: int = TOOLTIP_MARGIN
) -> QPoint:
    x, y = global_pos.x(), global_pos.y()
    left = bounds.left() + margin
    top = bounds.top() + margin
    right = bounds.right() - margin - size.width()
    bottom = bounds.bottom() - margin - size.height()
    return QPoint(max(left, min(x, right)), max(top, min(y, bottom)))


def position_tooltip_near_cursor(
    label: QLabel,
    *,
    clamp_widget: QWidget | None = None,
    margin: int = TOOLTIP_MARGIN,
    offset_x: int = _OFFSET_X,
    offset_y: int = _OFFSET_Y,
) -> QPoint:
    """Place ``label`` below-right of the cursor; flip and clamp if needed."""
    bounds = clamp_bounds_for_widget(clamp_widget)
    cursor = QCursor.pos()
    size = label.size()

    x = cursor.x() + offset_x
    y = cursor.y() + offset_y
    if x + size.width() > bounds.right() - margin:
        x = cursor.x() - size.width() - offset_x
    if y + size.height() > bounds.bottom() - margin:
        y = cursor.y() - size.height() - offset_y

    pos = clamp_popup_position(QPoint(x, y), size, bounds, margin=margin)
    label.move(pos)
    return pos


def ensure_tooltip_label(
    owner: QWidget,
    attr_name: str,
    *,
    window_flags: Qt.WindowType = Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint,
) -> QLabel:
    """Return a lazily created floating tooltip QLabel stored on ``owner``."""
    lbl = getattr(owner, attr_name, None)
    if lbl is None:
        lbl = QLabel(None, window_flags)
        lbl.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        setattr(owner, attr_name, lbl)
    return lbl
