#!/usr/bin/env python3
"""Position custom floating QLabel tooltips away from the cursor and on-screen."""

from __future__ import annotations

from typing import Callable

from shiboken6 import isValid

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QWidget

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


class SettingsDialogTooltipFilter(QObject):
    """Replace native QToolTip in settings with an opaque floating label."""

    def __init__(
        self,
        dialog: QWidget,
        stylesheet_fn: Callable[[], str],
        *,
        parent: QObject | None = None,
    ):
        super().__init__(parent or dialog)
        self._dialog = dialog
        self._stylesheet_fn = stylesheet_fn
        self._label = ensure_tooltip_label(dialog, "_settings_dialog_tooltip_label")
        self._source_widget: QWidget | None = None
        self._active = True
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            dialog.destroyed.connect(self._on_dialog_destroyed)

    def _is_descendant(self, widget: QWidget) -> bool:
        host = widget
        while host is not None:
            if host is self._dialog:
                return True
            host = host.parentWidget()
        return False

    def _on_dialog_destroyed(self, *_args) -> None:
        if not self._active:
            return
        self._active = False
        self._hide_tooltip()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

    def _hide_tooltip(self) -> None:
        if isValid(self._label):
            self._label.hide()
        self._source_widget = None

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if not self._active or not isValid(self._dialog):
            self._on_dialog_destroyed()
            return False
        if not self._dialog.isVisible():
            return False
        if not isinstance(obj, QWidget) or not self._is_descendant(obj):
            return False

        if event.type() == QEvent.Type.ToolTip:
            tip = obj.toolTip()
            if tip:
                self._label.setStyleSheet(self._stylesheet_fn())
                self._label.setText(tip)
                self._label.adjustSize()
                position_tooltip_near_cursor(self._label, clamp_widget=self._dialog)
                self._label.show()
                self._label.raise_()
                self._source_widget = obj
            else:
                self._hide_tooltip()
            return True

        if event.type() == QEvent.Type.Leave and obj is self._source_widget:
            self._hide_tooltip()

        return False


def install_settings_dialog_tooltip_filter(
    dialog: QWidget,
    stylesheet_fn: Callable[[], str],
) -> SettingsDialogTooltipFilter:
    """Show opaque custom tooltips for all controls inside the settings dialog."""
    filt = SettingsDialogTooltipFilter(dialog, stylesheet_fn, parent=dialog)
    dialog._settings_dialog_tooltip_filter = filt  # type: ignore[attr-defined]
    return filt
