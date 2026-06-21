#!/usr/bin/env python3
"""
Reset Date to EXIF Dialog
Shows a confirmation dialog with files that will have their dates reset to match EXIF data
"""

import os
from datetime import datetime
from typing import List, Tuple, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QDialogButtonBox, QTextEdit, QScrollArea, QWidget
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
)
from theme.theme_service import get_active_theme
from utils import file_string


def qtcolor_to_hex(color):
    """Convert QColor to hex string"""
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


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
        
        th = get_active_theme()
        bg_color = th.default_background_color_hex
        text_color = th.dialog_text_color_hex
        border_color = th.border_default_hex
        focus_border = th.current_image_border_color_hex
        button_bg_default = th.button_bg_default_hex
        button_text_default = th.button_text_default_hex
        button_border_default = th.button_border_default_hex
        button_bg_hover = th.button_bg_hover_hex
        button_text_hover = th.button_text_hover_hex
        button_border_hover = th.button_border_hover_hex
        button_bg_pressed = th.button_bg_pressed_hex
        button_focus_text = th.button_focus_text_hex
        text_disabled = th.text_disabled_hex
        widget_bg_disabled = th.widget_bg_disabled_hex
        dialog_background = th.dialog_background_hex
        
        self.setWindowTitle("Reset Date to EXIF")
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
                background-color: {button_bg_default};
                color: {button_text_default};
                border: 1px solid {button_border_default};
                border-radius: 5px;
                padding: 6px 18px;
                min-width: 100px;
                font-size: 13px;
                font-family: 'Arial Narrow', Arial;
                letter-spacing: 0.5px;
            }}
            QPushButton:focus {{
                background-color: {bg_color};
                color: {button_focus_text};
                border: 1px solid {focus_border};
                outline: none;
            }}
            QPushButton:hover {{
                background-color: {button_bg_hover};
                color: {button_text_hover};
                border: 1px solid {button_border_hover};
            }}
            QPushButton:pressed {{
                background-color: {button_bg_pressed};
                color: {button_focus_text};
            }}
            QPushButton:disabled {{
                color: {text_disabled};
                background-color: {widget_bg_disabled};
                border-color: {dialog_background};
            }}
            QDialogButtonBox QPushButton {{
                min-width: 80px;
                padding: 6px 14px;
            }}
            QTextEdit {{
                background-color: {button_bg_default};
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
