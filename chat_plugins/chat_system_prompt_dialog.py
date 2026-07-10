#!/usr/bin/env python3
"""Dialog to edit the per-chat system prompt."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chat_plugins.chat_ui_common import chat_prompt_edit_stylesheet
from utils import get_button_style, get_dialog_shell_stylesheet


def _cmd_enter_pressed(event: QKeyEvent) -> bool:
    if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        return False
    mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    cmd = mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
    if not cmd:
        return False
    other = mods & ~(
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
    )
    return other in (Qt.KeyboardModifier.NoModifier, 0)


class _CmdEnterAcceptFilter(QObject):
    def __init__(self, dialog: QDialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and _cmd_enter_pressed(event)
        ):
            self._dialog.accept()
            return True
        return super().eventFilter(watched, event)


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
    edit.installEventFilter(_CmdEnterAcceptFilter(dialog))

    button_row = QHBoxLayout()
    button_row.addStretch(1)
    cancel_button = QPushButton("Cancel")
    ok_button = QPushButton("OK")
    button_row.addWidget(cancel_button)
    button_row.addWidget(ok_button)
    layout.addLayout(button_row)

    for widget in (edit, cancel_button, ok_button):
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    ok_button.setDefault(True)
    ok_button.setAutoDefault(True)

    QWidget.setTabOrder(edit, cancel_button)
    QWidget.setTabOrder(cancel_button, ok_button)

    ok_button.clicked.connect(dialog.accept)
    cancel_button.clicked.connect(dialog.reject)
    dialog.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
    edit.setFocus()

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return edit.toPlainText()
