#!/usr/bin/env python3
"""
Reset EXIF to File Date Dialog
Shows a warning dialog with files that will have their EXIF date/time updated to match file modification date
"""

import os
from datetime import datetime
from typing import List, Tuple, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QDialogButtonBox, QTextEdit, QScrollArea, QWidget
)
from thumbnail_constants import (
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
from theme_service import get_active_theme
from utils import file_string


def qtcolor_to_hex(color):
    """Convert QColor to hex string"""
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


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
        error_color = th.error_color_hex
        
        self.setWindowTitle("Reset EXIF to File Date")
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
