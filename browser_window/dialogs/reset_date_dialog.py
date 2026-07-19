#!/usr/bin/env python3
"""
Reset Date to EXIF Dialog
Shows a confirmation dialog with files that will have their dates reset to match EXIF data
"""

import os
from datetime import datetime
from typing import List, Tuple

from PySide6.QtWidgets import QDialog

from browser_window.dialogs.file_list_confirmation_dialog import (
    FileListConfirmationDialog,
    truncate_display_path,
)
from utils import file_string


class ResetDateDialog(FileListConfirmationDialog):
    """Dialog showing files that will have their dates reset to EXIF data"""

    def __init__(self, files_to_change: List[Tuple[str, float, float]], parent=None):
        count = len(files_to_change)
        info_text = (
            f"The following {count} {file_string(count)} will have their modification "
            f"dates reset to match their EXIF data:"
        )
        super().__init__(
            title="Reset Date to EXIF",
            info_text=info_text,
            parent=parent,
        )
        self.files_to_change = files_to_change
        self.set_plain_content(self._build_plaintext())

    def _build_plaintext(self) -> str:
        content_lines = []
        for file_path, current_mtime, exif_timestamp in self.files_to_change:
            filename = os.path.basename(file_path)
            current_date = datetime.fromtimestamp(current_mtime).strftime("%Y-%m-%d %H:%M:%S")
            exif_date = datetime.fromtimestamp(exif_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            display_path = truncate_display_path(file_path)
            content_lines.extend([
                filename,
                f"  Path: {display_path}",
                f"  Current: {current_date}",
                f"  EXIF:    {exif_date}",
                "",
            ])
        return "\n".join(content_lines)

    @staticmethod
    def show_confirmation(files_to_change: List[Tuple[str, float, float]], parent=None) -> bool:
        if not files_to_change:
            return False
        dialog = ResetDateDialog(files_to_change, parent)
        return dialog.exec() == QDialog.Accepted
