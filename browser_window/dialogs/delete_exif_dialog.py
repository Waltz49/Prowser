#!/usr/bin/env python3
"""
Delete EXIF Date Dialog
Shows a warning dialog with files that will have their EXIF date/time data permanently deleted
"""

from datetime import datetime
from typing import List, Optional, Tuple

from PySide6.QtWidgets import QDialog

from browser_window.dialogs.file_list_confirmation_dialog import (
    FileListConfirmationDialog,
    escape_html_text,
)
from theme.theme_service import get_active_theme
from utils import file_string


class DeleteExifDialog(FileListConfirmationDialog):
    """Dialog showing warning for files that will have their EXIF date/time data permanently deleted"""

    def __init__(self, files_to_delete: List[Tuple[str, Optional[float]]], parent=None):
        th = get_active_theme()
        error_color = th.error_color_hex
        text_disabled = th.text_disabled_hex
        count = len(files_to_delete)

        warning_text = (
            f"⚠️ WARNING: EXIF date/time data will be PERMANENTLY DELETED from "
            f"{count} {file_string(count)}.\n\n"
            f"This action CANNOT be undone. The EXIF date/time metadata will be "
            f"completely removed from these files."
        )
        info_text = (
            f"The following {count} {file_string(count)} will have their EXIF "
            f"date/time data deleted:"
        )

        super().__init__(
            title="Delete EXIF Date",
            info_text=info_text,
            parent=parent,
            warning_text=warning_text,
            warning_style=f"color: {error_color}; font-weight: bold; font-size: 14px;",
            ok_text="Delete",
        )
        self.files_to_delete = files_to_delete
        self._error_color = error_color
        self._text_disabled = text_disabled
        self.set_html_content(self._build_html())

    def _build_html(self) -> str:
        html_lines = []
        for file_path, exif_timestamp in self.files_to_delete:
            html_lines.append(self.build_path_block(file_path))
            if exif_timestamp is not None:
                exif_date = datetime.fromtimestamp(exif_timestamp).strftime("%Y-%m-%d %H:%M:%S")
                exif_date_escaped = escape_html_text(exif_date)
                html_lines.append(
                    f'<div>  <span style="color: {self._error_color}; font-weight: bold;">'
                    f"EXIF Date to DELETE: {exif_date_escaped}</span></div>"
                )
            else:
                html_lines.append(
                    f'<div>  <span style="color: {self._text_disabled};">'
                    f"No EXIF date found (will be skipped)</span></div>"
                )
            html_lines.append("<div><br></div>")
        return "".join(html_lines)

    @staticmethod
    def show_confirmation(files_to_delete: List[Tuple[str, Optional[float]]], parent=None) -> bool:
        if not files_to_delete:
            return False
        dialog = DeleteExifDialog(files_to_delete, parent)
        return dialog.exec() == QDialog.Accepted
