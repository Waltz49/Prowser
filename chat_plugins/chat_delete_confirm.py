#!/usr/bin/env python3
"""Chat confirmation dialogs with keyboard navigation and session hide."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from utils import get_button_style, get_dialog_shell_stylesheet

_suppress_delete_confirm_for_session = False
_suppress_clear_confirm_for_session = False


def _confirm_with_hide_for_session(
    parent: QWidget | None,
    *,
    title: str,
    message: str,
    confirm_label: str,
    is_suppressed: Callable[[], bool],
    set_suppressed: Callable[[bool], None],
) -> bool:
    if is_suppressed():
        return True

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumWidth(360)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    layout.setContentsMargins(20, 20, 20, 20)

    message_label = QLabel(message)
    message_label.setWordWrap(True)
    layout.addWidget(message_label)

    hide_checkbox = QCheckBox("Hide for session")
    hide_checkbox.setToolTip(
        "Do not show this confirmation again until the program restarts"
    )
    layout.addWidget(hide_checkbox)

    button_row = QHBoxLayout()
    button_row.addStretch(1)
    no_button = QPushButton("No")
    confirm_button = QPushButton(confirm_label)
    button_row.addWidget(no_button)
    button_row.addWidget(confirm_button)
    layout.addLayout(button_row)

    for widget in (hide_checkbox, no_button, confirm_button):
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    no_button.setDefault(True)
    no_button.setAutoDefault(True)

    QWidget.setTabOrder(hide_checkbox, no_button)
    QWidget.setTabOrder(no_button, confirm_button)
    QWidget.setTabOrder(confirm_button, hide_checkbox)

    confirmed = False

    def accept_confirm() -> None:
        nonlocal confirmed
        if hide_checkbox.isChecked():
            set_suppressed(True)
        confirmed = True
        dialog.accept()

    confirm_button.clicked.connect(accept_confirm)
    no_button.clicked.connect(dialog.reject)
    dialog.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
    no_button.setFocus()

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    return confirmed


def confirm_chat_message_delete(parent: QWidget | None) -> bool:
    """Ask before deleting a chat message; returns True when delete is confirmed."""
    return _confirm_with_hide_for_session(
        parent,
        title="Delete Message",
        message="Delete this message?",
        confirm_label="Delete",
        is_suppressed=lambda: _suppress_delete_confirm_for_session,
        set_suppressed=_set_delete_suppressed,
    )


def confirm_clear_chat(parent: QWidget | None) -> bool:
    """Ask before clearing the chat; returns True when clear is confirmed."""
    return _confirm_with_hide_for_session(
        parent,
        title="Clear Chat",
        message="Clear the entire chat history for this session?",
        confirm_label="Clear",
        is_suppressed=lambda: _suppress_clear_confirm_for_session,
        set_suppressed=_set_clear_suppressed,
    )


def _set_delete_suppressed(value: bool) -> None:
    global _suppress_delete_confirm_for_session
    _suppress_delete_confirm_for_session = value


def _set_clear_suppressed(value: bool) -> None:
    global _suppress_clear_confirm_for_session
    _suppress_clear_confirm_for_session = value
