#!/usr/bin/env python3
"""
Normalize EXIF Steps Dialog
Shows a confirmation dialog listing files whose Image Model line will lose [N] suffix.
"""

from typing import List, Tuple

from PySide6.QtWidgets import QDialog

from browser_window.dialogs.file_list_confirmation_dialog import (
    FileListConfirmationDialog,
    truncate_display_path,
)
from utils import file_string


class NormalizeExifStepsDialog(FileListConfirmationDialog):
    """Dialog listing files to normalize legacy [N] step suffix in Image Model EXIF."""

    def __init__(self, files_to_update: List[Tuple[str, str]], parent=None):
        count = len(files_to_update)
        info_text = (
            f"The following {count} {file_string(count)} will have the legacy "
            f"[N] step suffix removed from the Image Model line in EXIF UserComment."
        )
        super().__init__(
            title="Normalize EXIF Steps",
            info_text=info_text,
            parent=parent,
        )
        self.files_to_update = files_to_update
        self.set_plain_content(self._build_plaintext())

    def _build_plaintext(self) -> str:
        path_lines = []
        for file_path, _new_comment in self.files_to_update:
            path_lines.append(truncate_display_path(file_path))
        return "\n".join(path_lines)

    @staticmethod
    def show_confirmation(files_to_update: List[Tuple[str, str]], parent=None) -> bool:
        if not files_to_update:
            return False
        dialog = NormalizeExifStepsDialog(files_to_update, parent)
        return dialog.exec() == QDialog.Accepted
