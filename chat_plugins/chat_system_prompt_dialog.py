#!/usr/bin/env python3
"""Dialog to edit the per-chat system prompt."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chat_plugins.chat_named_system_prompts import run_chat_system_prompt_library
from chat_plugins.chat_prompt_grammar import (
    add_chat_prompt_grammar_button,
    apply_chat_prompt_save_format_to_widget,
)
from chat_plugins.chat_ui_common import (
    chat_prompt_edit_stylesheet,
    install_cmd_enter_accept,
)
from theme.theme_service import get_active_theme
from utils import get_button_style, get_dialog_shell_stylesheet
from widgets.gear_icon_button import GearIconButton

CHAT_GEAR_BTN_SIZE = 26
_CHAT_GEAR_ICON_PX = 18


def _chat_gear_button_stylesheet() -> str:
    t = get_active_theme()
    sz = CHAT_GEAR_BTN_SIZE
    return f"""
        QPushButton#chatSystemPromptGearBtn {{
            background-color: {t.dialog_background_hex};
            border: 1px solid {t.border_default_hex};
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
        }}
        QPushButton#chatSystemPromptGearBtn:focus {{
            border: 1px solid {t.current_image_border_color_hex};
            outline: none;
        }}
        QPushButton#chatSystemPromptGearBtn:hover {{
            background-color: {t.tab_button_hover_bg_hex};
            border: 1px solid {t.tab_button_hover_bg_hex};
        }}
        QPushButton#chatSystemPromptGearBtn:pressed {{
            background-color: {t.sidebar_splitter_handle_hex};
        }}
    """


def edit_chat_system_prompt(parent: QWidget | None, current: str) -> str | None:
    """Show System Prompt for Chat dialog. Returns new text on OK, else None."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("System Prompt for Chat")
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumSize(480, 320)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    layout.setContentsMargins(20, 20, 20, 20)

    header = QLabel("System Prompt for Chat")
    header.setWordWrap(True)
    layout.addWidget(header)

    edit = QPlainTextEdit()
    edit.setPlainText(current)
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    edit.setStyleSheet(chat_prompt_edit_stylesheet())
    layout.addWidget(edit, 1)
    install_cmd_enter_accept(dialog, edit)

    gear_row = QHBoxLayout()
    gear_button = GearIconButton(
        dialog,
        size_px=CHAT_GEAR_BTN_SIZE,
        icon_px=_CHAT_GEAR_ICON_PX,
        tooltip="Manage saved system prompts",
        object_name="chatSystemPromptGearBtn",
        stylesheet=_chat_gear_button_stylesheet(),
    )

    def _open_prompt_library() -> None:
        _, selected_text = run_chat_system_prompt_library(
            dialog,
            suggestion_text=edit.toPlainText(),
        )
        if selected_text is not None:
            edit.setPlainText(selected_text)

    gear_button.clicked.connect(_open_prompt_library)
    gear_row.addWidget(gear_button)
    gear_row.addStretch(1)
    layout.addLayout(gear_row)

    button_row = QHBoxLayout()
    add_chat_prompt_grammar_button(dialog, edit, button_row)
    button_row.addStretch(1)
    cancel_button = QPushButton("Cancel")
    ok_button = QPushButton("OK")
    button_row.addWidget(cancel_button)
    button_row.addWidget(ok_button)
    layout.addLayout(button_row)

    for widget in (edit, gear_button, cancel_button, ok_button):
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    ok_button.setDefault(True)
    ok_button.setAutoDefault(True)

    QWidget.setTabOrder(edit, gear_button)
    QWidget.setTabOrder(gear_button, cancel_button)
    QWidget.setTabOrder(cancel_button, ok_button)

    def accept_dialog() -> None:
        apply_chat_prompt_save_format_to_widget(edit)
        QDialog.accept(dialog)

    dialog.accept = accept_dialog  # type: ignore[method-assign]
    ok_button.clicked.connect(dialog.accept)
    cancel_button.clicked.connect(dialog.reject)
    dialog.setStyleSheet(
        get_dialog_shell_stylesheet()
        + get_button_style()
        + _chat_gear_button_stylesheet()
    )
    edit.setFocus()

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return edit.toPlainText()
