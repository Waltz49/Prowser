#!/usr/bin/env python3
"""Chat pane header tools and context menu."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QPushButton

from theme.theme_service import get_active_theme


def _populate_chat_menu(menu: QMenu, chat_pane) -> None:
    prompt_action = menu.addAction("System Prompt for Chat…")
    prompt_action.triggered.connect(chat_pane.edit_system_prompt)
    clear_action = menu.addAction("Clear Chat")
    clear_action.triggered.connect(chat_pane.clear_chat)


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
