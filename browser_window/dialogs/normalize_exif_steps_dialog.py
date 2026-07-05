#!/usr/bin/env python3
"""
Normalize EXIF Steps Dialog
Shows a confirmation dialog listing files whose Image Model line will lose [N] suffix.
"""

import os
from typing import List, Tuple

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)
from thumbnails.thumbnail_constants import (
    BUTTON_BG_DEFAULT_HEX,
    BUTTON_BG_HOVER_HEX,
    BUTTON_BG_PRESSED_HEX,
    BUTTON_BORDER_DEFAULT_HEX,
    BUTTON_BORDER_HOVER_HEX,
    BUTTON_FOCUS_TEXT_HEX,
    BUTTON_TEXT_DEFAULT_HEX,
    BUTTON_TEXT_HOVER_HEX,
    CURRENT_IMAGE_BORDER_COLOR_HEX,
    DEFAULT_BORDER_COLOR,
    DIALOG_BACKGROUND_HEX,
    DIALOG_TEXT_COLOR_HEX,
    TEXT_DISABLED_HEX,
    WIDGET_BG_DISABLED_HEX,
)
from utils import file_string


def qtcolor_to_hex(color):
    """Convert QColor to hex string."""
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


class NormalizeExifStepsDialog(QDialog):
    """Dialog listing files to normalize legacy [N] step suffix in Image Model EXIF."""

    def __init__(
        self,
        files_to_update: List[Tuple[str, str]],
        parent=None,
    ):
        """
        Args:
            files_to_update: List of (file_path, new_comment_text)
        """
        super().__init__(parent)
        self.files_to_update = files_to_update

        bg_color = DIALOG_BACKGROUND_HEX
        text_color = DIALOG_TEXT_COLOR_HEX
        border_color = qtcolor_to_hex(DEFAULT_BORDER_COLOR)

        self.setWindowTitle("Normalize EXIF Steps")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {bg_color};
            }}
            QLabel {{
                font-size: 13px;
            }}
            QPushButton {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {BUTTON_TEXT_DEFAULT_HEX};
                border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
                border-radius: 5px;
                padding: 6px 18px;
                min-width: 100px;
                font-size: 13px;
                font-family: 'Arial Narrow', Arial;
                letter-spacing: 0.5px;
            }}
            QPushButton:focus {{
                background-color: {DIALOG_BACKGROUND_HEX};
                color: {BUTTON_FOCUS_TEXT_HEX};
                border: 1px solid {CURRENT_IMAGE_BORDER_COLOR_HEX};
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {BUTTON_BG_HOVER_HEX};
                color: {BUTTON_TEXT_HOVER_HEX};
                border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            }}
            QPushButton:pressed {{
                background-color: {BUTTON_BG_PRESSED_HEX};
                color: {BUTTON_FOCUS_TEXT_HEX};
            }}
            QPushButton:disabled {{
                color: {TEXT_DISABLED_HEX};
                background-color: {WIDGET_BG_DISABLED_HEX};
                border-color: {DIALOG_BACKGROUND_HEX};
            }}
            QDialogButtonBox QPushButton {{
                min-width: 80px;
                padding: 6px 14px;
            }}
            QTextEdit {{
                background-color: {BUTTON_BG_DEFAULT_HEX};
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 5px;
                padding: 8px;
                font-family: 'Monaco', 'Menlo', 'Courier New';
                font-size: 12px;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        count = len(files_to_update)
        info_label = QLabel(
            f"The following {count} {file_string(count)} will have the legacy "
            f"[N] step suffix removed from the Image Model line in EXIF UserComment."
        )
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        path_lines = []
        for file_path, _new_comment in files_to_update:
            display_path = file_path
            if len(display_path) > 80:
                display_path = "..." + display_path[-77:]
            path_lines.append(display_path)

        text_edit.setPlainText("\n".join(path_lines))
        main_layout.addWidget(text_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        button_box.button(QDialogButtonBox.Ok).setText("OK")
        button_box.button(QDialogButtonBox.Cancel).setText("Cancel")
        button_box.button(QDialogButtonBox.Cancel).setDefault(True)
        button_box.button(QDialogButtonBox.Cancel).setFocus()
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

    @staticmethod
    def show_confirmation(
        files_to_update: List[Tuple[str, str]],
        parent=None,
    ) -> bool:
        if not files_to_update:
            return False
        files_to_update.sort(
            key=lambda item: os.path.normcase(os.path.normpath(item[0]))
        )
        dialog = NormalizeExifStepsDialog(files_to_update, parent)
        return dialog.exec() == QDialog.Accepted
