#!/usr/bin/env python3
"""Chat pane header tools and context menu."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QPushButton

from theme.theme_service import get_active_theme


def show_chat_tools_menu(chat_pane, anchor: QPushButton) -> None:
    menu = QMenu(anchor)
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    clear_action = menu.addAction("Clear Chat")
    clear_action.triggered.connect(chat_pane.clear_chat)
    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def show_chat_context_menu(chat_pane, global_pos) -> None:
    menu = QMenu(chat_pane)
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    clear_action = menu.addAction("Clear Chat")
    clear_action.triggered.connect(chat_pane.clear_chat)
    menu.exec(global_pos)
