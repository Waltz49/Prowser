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
from utils import apply_standard_dialog_layout, file_string, get_standard_dialog_stylesheet


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

        self.setWindowTitle("Normalize EXIF Steps")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.setStyleSheet(get_standard_dialog_stylesheet(monospace_text_edit=True))

        main_layout = QVBoxLayout(self)
        apply_standard_dialog_layout(main_layout)

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
