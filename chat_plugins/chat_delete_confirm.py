#!/usr/bin/env python3
"""Delete-message confirmation with keyboard navigation and session hide."""

from __future__ import annotations

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


def confirm_chat_message_delete(parent: QWidget | None) -> bool:
    """Ask before deleting a chat message; returns True when delete is confirmed."""
    if _suppress_delete_confirm_for_session:
        return True

    dialog = QDialog(parent)
    dialog.setWindowTitle("Delete Message")
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.setMinimumWidth(360)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)
    layout.setContentsMargins(20, 20, 20, 20)

    message_label = QLabel("Delete this message?")
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
    delete_button = QPushButton("Delete")
    button_row.addWidget(no_button)
    button_row.addWidget(delete_button)
    layout.addLayout(button_row)

    for widget in (hide_checkbox, no_button, delete_button):
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    no_button.setDefault(True)
    no_button.setAutoDefault(True)
    delete_button.setAutoDefault(True)

    QWidget.setTabOrder(hide_checkbox, no_button)
    QWidget.setTabOrder(no_button, delete_button)
    QWidget.setTabOrder(delete_button, hide_checkbox)

    confirmed = False

    def accept_delete() -> None:
        nonlocal confirmed
        global _suppress_delete_confirm_for_session
        if hide_checkbox.isChecked():
            _suppress_delete_confirm_for_session = True
        confirmed = True
        dialog.accept()

    delete_button.clicked.connect(accept_delete)
    no_button.clicked.connect(dialog.reject)
    dialog.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
    no_button.setFocus()

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False
    return confirmed
