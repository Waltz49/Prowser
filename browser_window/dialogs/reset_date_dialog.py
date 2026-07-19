#!/usr/bin/env python3
"""
Reset Date to EXIF Dialog
Shows a confirmation dialog with files that will have their dates reset to match EXIF data
"""

import os
from datetime import datetime
from typing import List, Tuple
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel,
    QDialogButtonBox, QTextEdit,
)
from utils import apply_standard_dialog_layout, file_string, get_standard_dialog_stylesheet


class ResetDateDialog(QDialog):
    """Dialog showing files that will have their dates reset to EXIF data"""
    
    def __init__(self, files_to_change: List[Tuple[str, float, float]], parent=None):
        """
        Initialize the dialog
        
        Args:
            files_to_change: List of tuples (file_path, current_mtime, exif_timestamp)
            parent: Parent widget
        """
        super().__init__(parent)
        self.files_to_change = files_to_change
        
        self.setWindowTitle("Reset Date to EXIF")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.setStyleSheet(get_standard_dialog_stylesheet(monospace_text_edit=True))
        
        # Main layout
        main_layout = QVBoxLayout(self)
        apply_standard_dialog_layout(main_layout)
        
        # Info label
        info_label = QLabel(f"The following {len(files_to_change)} {file_string(len(files_to_change))} will have their modification dates reset to match their EXIF data:")
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)
        
        # Text area showing file details
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        
        # Build the text content
        content_lines = []
        for file_path, current_mtime, exif_timestamp in files_to_change:
            filename = os.path.basename(file_path)
            current_date = datetime.fromtimestamp(current_mtime).strftime("%Y-%m-%d %H:%M:%S")
            exif_date = datetime.fromtimestamp(exif_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            
            # Truncate path if too long
            display_path = file_path
            if len(display_path) > 80:
                display_path = "..." + display_path[-77:]
            
            content_lines.append(f"{filename}")
            content_lines.append(f"  Path: {display_path}")
            content_lines.append(f"  Current: {current_date}")
            content_lines.append(f"  EXIF:    {exif_date}")
            content_lines.append("")
        
        text_edit.setPlainText("\n".join(content_lines))
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
    def show_confirmation(files_to_change: List[Tuple[str, float, float]], parent=None) -> bool:
        """
        Static method to show the dialog and return True if user clicked OK
        
        Args:
            files_to_change: List of tuples (file_path, current_mtime, exif_timestamp)
            parent: Parent widget
            
        Returns:
            True if user clicked OK, False if Cancel
        """
        if not files_to_change:
            return False
        
        dialog = ResetDateDialog(files_to_change, parent)
        return dialog.exec() == QDialog.Accepted
