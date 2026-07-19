#!/usr/bin/env python3
"""
Shared base for confirmation dialogs that list files before a destructive or bulk action.
"""

from __future__ import annotations

import html
import os
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from utils import apply_standard_dialog_layout, get_standard_dialog_stylesheet

_MONOSPACE_HTML_WRAPPER = (
    "<div style='font-family: Monaco, Menlo, Courier New; font-size: 12px;'>{}</div>"
)


def escape_html_text(value: str) -> str:
    return html.escape(value, quote=False)


def truncate_display_path(path: str, max_len: int = 80) -> str:
    if len(path) <= max_len:
        return path
    return "..." + path[-(max_len - 3):]


def wrap_monospace_html(body_html: str) -> str:
    return _MONOSPACE_HTML_WRAPPER.format(body_html)


class FileListConfirmationDialog(QDialog):
    """Standard shell for file-list confirmation dialogs."""

    def __init__(
        self,
        *,
        title: str,
        info_text: str,
        parent=None,
        warning_text: Optional[str] = None,
        warning_style: Optional[str] = None,
        ok_text: str = "OK",
        min_width: int = 600,
        min_height: int = 400,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(min_width)
        self.setMinimumHeight(min_height)
        self.setStyleSheet(get_standard_dialog_stylesheet(monospace_text_edit=True))

        main_layout = QVBoxLayout(self)
        apply_standard_dialog_layout(main_layout)

        if warning_text:
            warning_label = QLabel(warning_text)
            warning_label.setWordWrap(True)
            if warning_style:
                warning_label.setStyleSheet(warning_style)
            main_layout.addWidget(warning_label)

        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)

        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        main_layout.addWidget(self._text_edit)

        self._button_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self._button_box.button(QDialogButtonBox.Ok).setText(ok_text)
        self._button_box.button(QDialogButtonBox.Cancel).setText("Cancel")
        self._button_box.button(QDialogButtonBox.Cancel).setDefault(True)
        self._button_box.button(QDialogButtonBox.Cancel).setFocus()
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        main_layout.addWidget(self._button_box)

    def set_plain_content(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    def set_html_content(self, body_html: str) -> None:
        self._text_edit.setHtml(wrap_monospace_html(body_html))

    @staticmethod
    def build_path_block(file_path: str) -> str:
        filename = escape_html_text(os.path.basename(file_path))
        display_path = escape_html_text(truncate_display_path(file_path))
        return f"<div>{filename}</div><div>  Path: {display_path}</div>"
