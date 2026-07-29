#!/usr/bin/env python3
"""Position QComboBox and custom popups below their anchor (Windows-style)."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QComboBox, QListView, QWidget

_POPUP_MARGIN = 8
_LIST_VIEW_ATTR = "_combo_popup_below_list_view_installed"
_original_qcombobox_show_popup: Optional[Callable[..., None]] = None


def combo_popup_widget(combo: QComboBox) -> Optional[QWidget]:
    """Return the top-level widget Qt uses for a combo's item list."""
    view = combo.view()
    if view is None:
        return None
    window = view.window()
    if window is combo:
        return None
    return window


def ensure_combo_list_view(combo: QComboBox) -> None:
    """Use a non-native QListView so popup placement is reliable on macOS."""
    if getattr(combo, _LIST_VIEW_ATTR, False):
        return
    if not isinstance(combo.view(), QListView):
        view = QListView(combo)
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        combo.setView(view)
    setattr(combo, _LIST_VIEW_ATTR, True)


def position_popup_below_anchor(
    popup: QWidget,
    anchor: QWidget,
    *,
    margin: int = _POPUP_MARGIN,
) -> None:
    """Place *popup* just below *anchor*, flipping above when it would not fit."""
    screen = anchor.screen()
    avail = screen.availableGeometry() if screen is not None else None

    popup_w = popup.width()
    popup_h = popup.height()
    global_pos = anchor.mapToGlobal(QPoint(0, anchor.height()))

    if avail is not None:
        if global_pos.x() + popup_w > avail.right() - margin:
            global_pos.setX(max(avail.left() + margin, avail.right() - margin - popup_w))
        if global_pos.x() < avail.left() + margin:
            global_pos.setX(avail.left() + margin)

        if global_pos.y() + popup_h > avail.bottom() - margin:
            above_y = anchor.mapToGlobal(QPoint(0, 0)).y() - popup_h
            if above_y >= avail.top() + margin:
                global_pos.setY(above_y)
            else:
                global_pos.setY(
                    max(avail.top() + margin, avail.bottom() - margin - popup_h)
                )

    popup.move(global_pos)


def reposition_combo_popup_below(
    combo: QComboBox,
    *,
    margin: int = _POPUP_MARGIN,
) -> None:
    """Reposition a combo list below the control unless it would leave the screen."""
    popup = combo_popup_widget(combo)
    if popup is None:
        return
    position_popup_below_anchor(popup, combo, margin=margin)


def install_combo_popup_below_globally() -> None:
    """Patch QComboBox.showPopup so every dropdown opens below unless it will not fit."""
    global _original_qcombobox_show_popup
    if _original_qcombobox_show_popup is not None:
        return

    _original_qcombobox_show_popup = QComboBox.showPopup

    def show_popup_below(self: QComboBox) -> None:
        ensure_combo_list_view(self)
        _original_qcombobox_show_popup(self)
        reposition_combo_popup_below(self)

    QComboBox.showPopup = show_popup_below  # type: ignore[method-assign]
