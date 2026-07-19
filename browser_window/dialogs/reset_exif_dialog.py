#!/usr/bin/env python3
"""
Reset EXIF to File Date Dialog
Shows a warning dialog with files that will have their EXIF date/time updated to match file modification date
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


class ResetExifDialog(FileListConfirmationDialog):
    """Dialog showing warning for files that will have their EXIF date/time updated to match file modification date"""

    def __init__(
        self,
        files_to_update: List[Tuple[str, float, Optional[float]]],
        files_with_existing_exif: int,
        parent=None,
    ):
        th = get_active_theme()
        error_color = th.error_color_hex
        button_text_hover = th.button_text_hover_hex
        count = len(files_to_update)

        warning_text = (
            f"WARNING: EXIF date/time data will be updated for {count} {file_string(count)}."
        )
        if files_with_existing_exif > 0:
            warning_text += (
                f"\n\n{files_with_existing_exif} {file_string(files_with_existing_exif)} "
                f"already have EXIF date/time data that will be overwritten."
            )

        info_text = (
            f"The following {count} {file_string(count)} will have their EXIF date/time "
            f"set to match their file modification date:"
        )

        super().__init__(
            title="Reset EXIF to File Date",
            info_text=info_text,
            parent=parent,
            warning_text=warning_text,
            warning_style=f"color: {error_color}; font-weight: bold;",
        )
        self.files_to_update = files_to_update
        self._button_text_hover = button_text_hover
        self.set_html_content(self._build_html())

    def _build_html(self) -> str:
        html_lines = []
        for file_path, file_mtime, old_exif_timestamp in self.files_to_update:
            file_date = datetime.fromtimestamp(file_mtime).strftime("%Y-%m-%d %H:%M:%S")
            html_lines.append(self.build_path_block(file_path))
            if old_exif_timestamp is not None:
                old_exif_date = datetime.fromtimestamp(old_exif_timestamp).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                old_exif_date_escaped = escape_html_text(old_exif_date)
                html_lines.append(
                    f'<div>  <span style="color: {self._button_text_hover};">'
                    f"Old EXIF Date: {old_exif_date_escaped}</span></div>"
                )
            html_lines.append(f"<div>  New EXIF Date: {escape_html_text(file_date)}</div>")
            html_lines.append("<div><br></div>")
        return "".join(html_lines)

    @staticmethod
    def show_confirmation(
        files_to_update: List[Tuple[str, float, Optional[float]]],
        files_with_existing_exif: int,
        parent=None,
    ) -> bool:
        if not files_to_update:
            return False
        dialog = ResetExifDialog(files_to_update, files_with_existing_exif, parent)
        return dialog.exec() == QDialog.Accepted
