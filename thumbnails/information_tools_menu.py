#!/usr/bin/env python3
"""File Information pane tools and context menu."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QPushButton

from theme.theme_service import get_active_theme

_MENU_ACTION_ORDER = ("edit", "copy", "speak", "delete", "create", "editai")


def _audio_output_ui_enabled() -> bool:
    try:
        from bundle_capabilities import audio_output_ui_enabled

        return audio_output_ui_enabled()
    except ImportError:
        return True


def _imagegen_create_available() -> bool:
    try:
        from imagegen_plugins.image_gen_menu import imagegen_plugins_available

        return imagegen_plugins_available()
    except ImportError:
        return False


def _imagegen_edit_ai_available() -> bool:
    try:
        from imagegen_plugins.image_gen_menu import imagegen_edit_plugins_available

        return imagegen_edit_plugins_available()
    except ImportError:
        return False


def _populate_information_menu(menu: QMenu, sidebar) -> None:
    specs = {spec["action_id"]: spec for spec in sidebar.info_action_specs()}
    for action_id in _MENU_ACTION_ORDER:
        spec = specs.get(action_id)
        if spec is None or not spec["visible"]:
            continue
        action = menu.addAction(spec["label"])
        action.setEnabled(spec["enabled"])
        action.triggered.connect(
            lambda _checked=False, aid=action_id: sidebar.trigger_info_action(aid)
        )

    menu.addSeparator()
    show_bar = menu.addAction("Show Menu Bar")
    show_bar.setCheckable(True)
    show_bar.setChecked(sidebar.is_action_menu_bar_visible())
    show_bar.toggled.connect(sidebar.set_action_menu_bar_visible)


def show_information_tools_menu(sidebar, anchor: QPushButton) -> None:
    menu = QMenu(anchor)
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    _populate_information_menu(menu, sidebar)
    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def show_information_context_menu(sidebar, global_pos) -> None:
    menu = QMenu(sidebar)
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    _populate_information_menu(menu, sidebar)
    menu.exec(global_pos)
