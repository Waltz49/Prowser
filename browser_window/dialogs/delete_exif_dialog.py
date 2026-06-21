#!/usr/bin/env python3
"""
Delete EXIF Date Dialog
Shows a warning dialog with files that will have their EXIF date/time data permanently deleted
"""

import os
from datetime import datetime
from typing import List, Tuple, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit,
    QDialogButtonBox, QTextEdit
)
from thumbnails.thumbnail_constants import (
    DEFAULT_BACKGROUND_COLOR,
    DIALOG_TEXT_COLOR_HEX,
    DEFAULT_BORDER_COLOR,
    CURRENT_IMAGE_BORDER_COLOR,
    BUTTON_BG_DEFAULT_HEX, BUTTON_TEXT_DEFAULT_HEX, BUTTON_BORDER_DEFAULT_HEX,
    BUTTON_BG_HOVER_HEX, BUTTON_TEXT_HOVER_HEX, BUTTON_BORDER_HOVER_HEX,
    BUTTON_BG_PRESSED_HEX, BUTTON_FOCUS_TEXT_HEX, TEXT_DISABLED_HEX,
    WIDGET_BG_DISABLED_HEX, DIALOG_BACKGROUND_HEX, CURRENT_IMAGE_BORDER_COLOR_HEX,
    ERROR_COLOR_HEX,
)
from utils import file_string


def qtcolor_to_hex(color):
    """Convert QColor to hex string"""
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


class DeleteExifDialog(QDialog):
    """Dialog showing warning for files that will have their EXIF date/time data permanently deleted"""
    
    def __init__(self, files_to_delete: List[Tuple[str, Optional[float]]], parent=None):
        """
        Initialize the dialog
        
        Args:
            files_to_delete: List of tuples (file_path, exif_timestamp or None)
            parent: Parent widget
        """
        super().__init__(parent)
        self.files_to_delete = files_to_delete
        
        # Convert QColor constants to hex strings
        bg_color = qtcolor_to_hex(DEFAULT_BACKGROUND_COLOR)
        text_color = DIALOG_TEXT_COLOR_HEX
        border_color = qtcolor_to_hex(DEFAULT_BORDER_COLOR)
        accent_border = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        
        self.setWindowTitle("Delete EXIF Date")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        
        # Dark theme styling
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
                background-color: {qtcolor_to_hex(DEFAULT_BACKGROUND_COLOR)};
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
            QScrollArea {{
                background-color: {bg_color};
                border: none;
            }}
        """)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # Warning label - make it scarier
        warning_text = f"⚠️ WARNING: EXIF date/time data will be PERMANENTLY DELETED from {len(files_to_delete)} {file_string(len(files_to_delete))}."
        warning_text += f"\n\nThis action CANNOT be undone. The EXIF date/time metadata will be completely removed from these files."
        
        warning_label = QLabel(warning_text)
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet(f"color: {ERROR_COLOR_HEX}; font-weight: bold; font-size: 14px;")
        main_layout.addWidget(warning_label)
        
        # Info label
        info_label = QLabel(f"The following {len(files_to_delete)} {file_string(len(files_to_delete))} will have their EXIF date/time data deleted:")
        info_label.setWordWrap(True)
        main_layout.addWidget(info_label)
        
        # Text area showing file details (using HTML to highlight EXIF dates that will be deleted)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        
        # Build the HTML content with highlighted EXIF dates
        html_lines = []
        for file_path, exif_timestamp in files_to_delete:
            filename = os.path.basename(file_path)
            
            # Truncate path if too long
            display_path = file_path
            if len(display_path) > 80:
                display_path = "..." + display_path[-77:]
            
            # Escape HTML special characters
            filename_escaped = filename.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            display_path_escaped = display_path.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            
            html_lines.append(f"<div>{filename_escaped}</div>")
            html_lines.append(f"<div>  Path: {display_path_escaped}</div>")
            
            # Add EXIF date in yellow/red if it exists (will be deleted)
            if exif_timestamp is not None:
                exif_date = datetime.fromtimestamp(exif_timestamp).strftime("%Y-%m-%d %H:%M:%S")
                exif_date_escaped = exif_date.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_lines.append(f'<div>  <span style="color: {ERROR_COLOR_HEX}; font-weight: bold;">EXIF Date to DELETE: {exif_date_escaped}</span></div>')
            else:
                html_lines.append(f'<div>  <span style="color: {TEXT_DISABLED_HEX};">No EXIF date found (will be skipped)</span></div>')
            
            html_lines.append("<div><br></div>")
        
        html_content = "<div style='font-family: Monaco, Menlo, Courier New; font-size: 12px;'>" + "".join(html_lines) + "</div>"
        text_edit.setHtml(html_content)
        main_layout.addWidget(text_edit)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        button_box.button(QDialogButtonBox.Ok).setText("Delete")
        button_box.button(QDialogButtonBox.Cancel).setText("Cancel")
        
        # Set Cancel as default (focus)
        button_box.button(QDialogButtonBox.Cancel).setDefault(True)
        button_box.button(QDialogButtonBox.Cancel).setFocus()
        
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        main_layout.addWidget(button_box)
    
    @staticmethod
    def show_confirmation(files_to_delete: List[Tuple[str, Optional[float]]], parent=None) -> bool:
        """
        Static method to show the dialog and return True if user clicked OK
        
        Args:
            files_to_delete: List of tuples (file_path, exif_timestamp or None)
            parent: Parent widget
            
        Returns:
            True if user clicked OK, False if Cancel
        """
        if not files_to_delete:
            return False
        
        dialog = DeleteExifDialog(files_to_delete, parent)
        return dialog.exec() == QDialog.Accepted
