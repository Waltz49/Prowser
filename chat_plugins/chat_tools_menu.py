#!/usr/bin/env python3
"""Chat pane header tools and context menu."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QPushButton

from chat_plugins.chat_persistence import is_preserve_chat_across_sessions
from chat_plugins.chat_tips_dialog import show_chat_tips_dialog
from theme.theme_service import get_active_theme

_MENU_ACTION_ORDER = ("system_prompt", "copy_images", "clear_chat")  # clear last


def _populate_chat_menu(menu: QMenu, chat_pane) -> None:
    specs = {spec["action_id"]: spec for spec in chat_pane.chat_toolbar_action_specs()}
    toolbar = getattr(chat_pane, "_toolbar", None)
    for action_id in _MENU_ACTION_ORDER:
        spec = specs.get(action_id)
        if spec is None or not spec["visible"]:
            continue
        icon = toolbar.action_icon(action_id) if toolbar is not None else None
        if icon is not None and not icon.isNull():
            action = menu.addAction(icon, str(spec["label"]))
        else:
            action = menu.addAction(str(spec["label"]))
        action.setEnabled(bool(spec["enabled"]))
        if spec.get("checkable"):
            action.setCheckable(True)
            action.setChecked(bool(spec.get("checked")))
            action.toggled.connect(
                lambda checked, aid=action_id: chat_pane.trigger_chat_toolbar_action(
                    aid, checked
                )
            )
        else:
            action.triggered.connect(
                lambda _checked=False, aid=action_id: chat_pane.trigger_chat_toolbar_action(
                    aid
                )
            )

    menu.addSeparator()
    preserve_action = menu.addAction("Preserve Chat Across Sessions")
    preserve_action.setCheckable(True)
    preserve_action.setChecked(is_preserve_chat_across_sessions())
    preserve_action.toggled.connect(chat_pane.set_preserve_chat_across_sessions)
    tips_action = menu.addAction("Tips…")
    tips_action.triggered.connect(lambda: show_chat_tips_dialog(chat_pane))

    menu.addSeparator()
    show_bar = menu.addAction("Show Toolbar")
    show_bar.setCheckable(True)
    show_bar.setChecked(chat_pane.is_chat_toolbar_visible())
    show_bar.toggled.connect(chat_pane.set_chat_toolbar_visible)


def show_chat_tools_menu(chat_pane, anchor: QPushButton) -> None:
    menu = QMenu(anchor)
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    _populate_chat_menu(menu, chat_pane)
    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def show_chat_context_menu(chat_pane, global_pos) -> None:
    menu = QMenu(chat_pane)
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    _populate_chat_menu(menu, chat_pane)
    menu.exec(global_pos)
