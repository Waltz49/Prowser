#!/usr/bin/env python3
"""
Reset EXIF to File Date Dialog
Shows a warning dialog with files that will have their EXIF date/time updated to match file modification date
"""

import os
from datetime import datetime
from typing import List, Tuple, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,
    QDialogButtonBox, QTextEdit,
)
from theme.theme_service import get_active_theme
from utils import apply_standard_dialog_layout, file_string, get_standard_dialog_stylesheet


class ResetExifDialog(QDialog):
    """Dialog showing warning for files that will have their EXIF date/time updated to match file modification date"""
    
    def __init__(self, files_to_update: List[Tuple[str, float, Optional[float]]], files_with_existing_exif: int, parent=None):
        """
        Initialize the dialog
        
        Args:
            files_to_update: List of tuples (file_path, file_mtime, old_exif_timestamp or None)
            files_with_existing_exif: Number of files that already have EXIF date/time (will be overwritten)
            parent: Parent widget
        """
        super().__init__(parent)
        self.files_to_update = files_to_update
        self.files_with_existing_exif = files_with_existing_exif
        
        th = get_active_theme()
        error_color = th.error_color_hex
        button_text_hover = th.button_text_hover_hex
        
        self.setWindowTitle("Reset EXIF to File Date")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.setStyleSheet(get_standard_dialog_stylesheet(monospace_text_edit=True))
        
        # Main layout
        main_layout = QVBoxLayout(self)
        apply_standard_dialog_layout(main_layout)
        
        # Warning label
        warning_text = f"WARNING: EXIF date/time data will be updated for {len(files_to_update)} {file_string(len(files_to_update))}."
        if files_with_existing_exif > 0:
            warning_text += f"\n\n{files_with_existing_exif} {file_string(files_with_existing_exif)} already have EXIF date/time data that will be overwritten."
        
        warning_label = QLabel(warning_text)
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet(f"color: {error_color}; font-weight: bold;")
        main_layout.addWidget(warning_label)
        
        # Info label
        info_label = QLabel(f"The following {len(files_to_update)} {file_string(len(files_to_update))} will have their EXIF date/time set to match their file modification date:")
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)
        
        # Text area showing file details (using HTML to highlight old EXIF dates)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        
        # Build the HTML content with highlighted old EXIF dates
        html_lines = []
        for file_path, file_mtime, old_exif_timestamp in files_to_update:
            filename = os.path.basename(file_path)
            file_date = datetime.fromtimestamp(file_mtime).strftime("%Y-%m-%d %H:%M:%S")
            
            # Truncate path if too long
            display_path = file_path
            if len(display_path) > 80:
                display_path = "..." + display_path[-77:]
            
            # Escape HTML special characters
            filename_escaped = filename.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            display_path_escaped = display_path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            file_date_escaped = file_date.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            
            html_lines.append(f"<div>{filename_escaped}</div>")
            html_lines.append(f"<div>  Path: {display_path_escaped}</div>")
            
            # Add old EXIF date in yellow if it exists
            if old_exif_timestamp is not None:
                old_exif_date = datetime.fromtimestamp(old_exif_timestamp).strftime("%Y-%m-%d %H:%M:%S")
                old_exif_date_escaped = old_exif_date.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_lines.append(f'<div>  <span style="color: {button_text_hover};">Old EXIF Date: {old_exif_date_escaped}</span></div>')
            
            html_lines.append(f"<div>  New EXIF Date: {file_date_escaped}</div>")
            html_lines.append("<div><br></div>")
        
        html_content = "<div style='font-family: Monaco, Menlo, Courier New; font-size: 12px;'>" + "".join(html_lines) + "</div>"
        text_edit.setHtml(html_content)
        main_layout.addWidget(text_edit)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        button_box.button(QDialogButtonBox.Ok).setText("OK")
        button_box.button(QDialogButtonBox.Cancel).setText("Cancel")
        
        # Set Cancel as default (focus)
        button_box.button(QDialogButtonBox.Cancel).setDefault(True)
        button_box.button(QDialogButtonBox.Cancel).setFocus()
        
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        main_layout.addWidget(button_box)
    
    @staticmethod
    def show_confirmation(files_to_update: List[Tuple[str, float, Optional[float]]], files_with_existing_exif: int, parent=None) -> bool:
        """
        Static method to show the dialog and return True if user clicked OK
        
        Args:
            files_to_update: List of tuples (file_path, file_mtime, old_exif_timestamp or None)
            files_with_existing_exif: Number of files that already have EXIF date/time
            parent: Parent widget
            
        Returns:
            True if user clicked OK, False if Cancel
        """
        if not files_to_update:
            return False
        
        dialog = ResetExifDialog(files_to_update, files_with_existing_exif, parent)
        return dialog.exec() == QDialog.Accepted
