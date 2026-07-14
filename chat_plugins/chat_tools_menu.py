#!/usr/bin/env python3
"""Chat pane header tools and context menu."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QPushButton

from chat_plugins.chat_persistence import (
    is_automatic_create,
    is_copy_images_to_assistant,
    is_preserve_chat_across_sessions,
)
from chat_plugins.chat_tips_dialog import show_chat_tips_dialog
from theme.theme_service import get_active_theme


def _populate_chat_menu(menu: QMenu, chat_pane) -> None:
    prompt_action = menu.addAction("System Prompt for Chat…")
    prompt_action.triggered.connect(chat_pane.edit_system_prompt)
    fav_action = menu.addAction("Favorite User Prompts…")
    fav_action.triggered.connect(chat_pane.open_favorite_user_prompts)
    preserve_action = menu.addAction("Preserve Chat Across Sessions")
    preserve_action.setCheckable(True)
    preserve_action.setChecked(is_preserve_chat_across_sessions())
    preserve_action.toggled.connect(chat_pane.set_preserve_chat_across_sessions)
    copy_images_action = menu.addAction("Copy images to Assistant's reply")
    copy_images_action.setCheckable(True)
    copy_images_action.setChecked(is_copy_images_to_assistant())
    copy_images_action.toggled.connect(chat_pane.set_copy_images_to_assistant)
    automatic_create_action = menu.addAction("Automatic /create")
    automatic_create_action.setCheckable(True)
    automatic_create_action.setChecked(is_automatic_create())
    automatic_create_action.toggled.connect(chat_pane.set_automatic_create)
    clear_action = menu.addAction("Clear Chat")
    clear_action.triggered.connect(chat_pane.clear_chat)
    menu.addSeparator()
    tips_action = menu.addAction("Tips…")
    tips_action.triggered.connect(lambda: show_chat_tips_dialog(chat_pane))


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
