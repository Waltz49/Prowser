#!/usr/bin/env python3
"""File tree pane tools and context menu."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QPushButton

from theme.theme_service import get_active_theme

_MENU_ACTION_ORDER = (
    "collapse",
    "rename_status",
    "settings",
    "filter_all",
    "filter_images",
    "filter_use_filter",
)


def _populate_tree_menu(menu: QMenu, handler) -> None:
    specs = {spec["action_id"]: spec for spec in handler.tree_toolbar_action_specs()}
    toolbar = getattr(handler, "_toolbar", None)
    for action_id in _MENU_ACTION_ORDER:
        if action_id == "filter_all":
            menu.addSeparator()
        spec = specs.get(action_id)
        if spec is None or not spec["visible"]:
            continue
        icon = toolbar.action_icon(action_id) if toolbar is not None else None
        if icon is not None and not icon.isNull():
            action = menu.addAction(icon, spec["label"])
        else:
            action = menu.addAction(spec["label"])
        action.setEnabled(spec["enabled"])
        if spec.get("checkable"):
            action.setCheckable(True)
            action.setChecked(bool(spec.get("checked")))
        action.triggered.connect(
            lambda _checked=False, aid=action_id: handler.trigger_tree_toolbar_action(
                aid
            )
        )

    menu.addSeparator()
    show_bar = menu.addAction("Show Toolbar")
    show_bar.setCheckable(True)
    show_bar.setChecked(handler.is_tree_toolbar_visible())
    show_bar.toggled.connect(handler.set_tree_toolbar_visible)


def show_tree_tools_menu(handler, anchor: QPushButton) -> None:
    menu = QMenu(anchor)
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    _populate_tree_menu(menu, handler)
    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def show_tree_context_menu(handler, global_pos) -> None:
    menu = QMenu()
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    _populate_tree_menu(menu, handler)
    menu.exec(global_pos)
