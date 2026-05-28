#!/usr/bin/env python3
"""
Filter Dialog for Image Browser
Allows users to edit and manage a list of filter patterns
"""

import fnmatch
import os
from typing import List, Optional, Tuple
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QFontMetrics
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QDialogButtonBox, QWidget, QScrollArea, QSizePolicy, QApplication
)

from config import ImageBrowserConfig
from thumbnail_constants import (
    DEFAULT_BACKGROUND_COLOR,
    DIALOG_TEXT_COLOR_HEX,
    DEFAULT_BORDER_COLOR,
    CURRENT_IMAGE_BORDER_COLOR,
    BUTTON_BG_DEFAULT_HEX, BUTTON_TEXT_DEFAULT_HEX, BUTTON_BORDER_DEFAULT_HEX,
    BUTTON_BG_HOVER_HEX, BUTTON_TEXT_HOVER_HEX, BUTTON_BORDER_HOVER_HEX,
    BUTTON_BG_PRESSED_HEX, BUTTON_FOCUS_TEXT_HEX, ERROR_COLOR_HEX,
    DIALOG_BACKGROUND_HEX, ACCENT_COLOR_HEX, TEXT_DISABLED_HEX,
    CURRENT_IMAGE_BORDER_COLOR_HEX, WIDGET_BG_DISABLED_HEX,
    DEFAULT_BORDER_COLOR_HEX,
)


def qtcolor_to_hex(color):
    """Convert QColor to hex string"""
    return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"


class FilterEntryWidget(QWidget):
    """A single filter entry widget with text field and delete button"""
    
    delete_requested = Signal(QWidget)
    validation_changed = Signal(QWidget, bool, str)  # widget, is_valid, error_message
    
    def __init__(self, pattern: str = "", parent=None):
        super().__init__(parent)
        self.pattern = pattern
        self.is_valid = True
        self.error_message = ""
        
        # Convert QColor constants to hex strings
        bg_color = qtcolor_to_hex(DEFAULT_BACKGROUND_COLOR)
        text_color = DIALOG_TEXT_COLOR_HEX
        border_color = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        border_focus_color = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        # Lighten border for focus (approximate)
        focus_r = min(255, CURRENT_IMAGE_BORDER_COLOR.red() + 20)
        focus_g = min(255, CURRENT_IMAGE_BORDER_COLOR.green() + 20)
        focus_b = min(255, CURRENT_IMAGE_BORDER_COLOR.blue() + 20)
        border_focus_color = f"#{focus_r:02x}{focus_g:02x}{focus_b:02x}"
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Horizontal layout for input and delete button
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)
        
        # Text input field - use standard application colors
        self.text_input = QLineEdit()
        self.text_input.setText(pattern)
        # Standard application colors from thumbnail_constants
        button_bg_default = BUTTON_BG_DEFAULT_HEX
        button_text_default = BUTTON_TEXT_DEFAULT_HEX
        button_border_default = BUTTON_BORDER_DEFAULT_HEX
        button_bg_hover = BUTTON_BG_HOVER_HEX
        button_text_hover = BUTTON_TEXT_HOVER_HEX
        button_border_hover = BUTTON_BORDER_HOVER_HEX
        text_primary = BUTTON_FOCUS_TEXT_HEX
        focus_border_hex = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        selection_bg = ACCENT_COLOR_HEX
        selection_text = BUTTON_FOCUS_TEXT_HEX
        
        self.text_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {button_bg_default};
                color: {button_text_default};
                border: 1px solid {button_border_default};
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 13px;
                font-family: 'Arial Narrow', Arial;
                letter-spacing: 0.5px;
                selection-background-color: {selection_bg};
                selection-color: {selection_text};
                width: 150px;
            }}
            QLineEdit:focus {{
                background-color: {button_bg_default};
                color: {text_primary};
                border: 1px solid {focus_border_hex};
                outline: none;
            }}
            QLineEdit:hover {{
                background-color: {button_bg_hover};
                color: {button_text_hover};
                border: 1px solid {button_border_hover};
            }}
        """)
        input_layout.addWidget(self.text_input)
        
        # Delete button with trash icon - use standard application colors
        delete_button_size = 12  # pixels
        button_bg_default = BUTTON_BG_DEFAULT_HEX
        button_text_default = BUTTON_TEXT_DEFAULT_HEX
        button_border_default = BUTTON_BORDER_DEFAULT_HEX
        button_bg_hover = BUTTON_BG_HOVER_HEX
        button_text_hover = BUTTON_TEXT_HOVER_HEX
        button_border_hover = BUTTON_BORDER_HOVER_HEX
        button_bg_pressed = BUTTON_BG_PRESSED_HEX
        focus_bg, focus_border, focus_text = self._get_focus_colors()
        
        self.delete_button = QPushButton("−")
        self.delete_button.setFixedSize(delete_button_size, delete_button_size)
        self.delete_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.delete_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {button_bg_default};
                border: 1px solid {button_border_default};
                border-radius: 4px;
                color: {button_text_default};
                font-size: 16px;
                font-weight: bold;
                min-width: {delete_button_size}px;
                max-width: {delete_button_size}px;
                min-height: {delete_button_size}px;
                max-height: {delete_button_size}px;
            }}
            QPushButton:focus {{
                background-color: {focus_bg};
                color: {focus_text};
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
                color: {focus_text};
            }}
        """)
        self.delete_button.setToolTip("Delete this filter")
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit(self))
        input_layout.addWidget(self.delete_button, 0)
        
        layout.addLayout(input_layout)
        
        # Error message label (initially hidden)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet(f"""
            QLabel {{
                color: {ERROR_COLOR_HEX};
                font-size: 11px;
                font-style: italic;
                padding-left: 4px;
            }}
        """)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
    
    def get_pattern(self) -> str:
        """Get the current pattern text"""
        return self.text_input.text().strip()
    
    def _get_focus_colors(self):
        """Get focus colors matching application standard"""
        from thumbnail_constants import CURRENT_IMAGE_BACKGROUND_COLOR, CURRENT_IMAGE_BORDER_COLOR
        focus_bg = qtcolor_to_hex(CURRENT_IMAGE_BACKGROUND_COLOR)
        focus_border = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        focus_text = BUTTON_FOCUS_TEXT_HEX
        return focus_bg, focus_border, focus_text
    
    def set_validation_state(self, is_valid: bool, error_message: str = ""):
        """Set the validation state and error message"""
        self.is_valid = is_valid
        self.error_message = error_message
        
        # Standard application colors
        button_bg_default = BUTTON_BG_DEFAULT_HEX
        button_text_default = BUTTON_TEXT_DEFAULT_HEX
        button_border_default = BUTTON_BORDER_DEFAULT_HEX
        button_bg_hover = BUTTON_BG_HOVER_HEX
        button_text_hover = BUTTON_TEXT_HOVER_HEX
        button_border_hover = BUTTON_BORDER_HOVER_HEX
        text_primary = BUTTON_FOCUS_TEXT_HEX
        focus_border_hex = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        selection_bg = ACCENT_COLOR_HEX
        selection_text = BUTTON_FOCUS_TEXT_HEX
        
        if error_message:
            self.error_label.setText(error_message)
            self.error_label.show()
            # Update input border color to red for invalid
            self.text_input.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {button_bg_default};
                    color: {button_text_default};
                    border: 1px solid {ERROR_COLOR_HEX};
                    border-radius: 5px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-family: 'Arial Narrow', Arial;
                    letter-spacing: 0.5px;
                    selection-background-color: {selection_bg};
                    selection-color: {selection_text};
                }}
                QLineEdit:focus {{
                    background-color: {button_bg_default};
                    color: {text_primary};
                    border: 1px solid {ERROR_COLOR_HEX};
                    outline: none;
                }}
                QLineEdit:hover {{
                    background-color: {button_bg_hover};
                    color: {button_text_hover};
                    border: 1px solid {ERROR_COLOR_HEX};
                }}
            """)
        else:
            self.error_label.hide()
            # Restore normal styling with standard application colors
            self.text_input.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {button_bg_default};
                    color: {button_text_default};
                    border: 1px solid {button_border_default};
                    border-radius: 5px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-family: 'Arial Narrow', Arial;
                    letter-spacing: 0.5px;
                    selection-background-color: {selection_bg};
                    selection-color: {selection_text};
                }}
                QLineEdit:focus {{
                    background-color: {button_bg_default};
                    color: {text_primary};
                    border: 1px solid {focus_border_hex};
                    outline: none;
                }}
                QLineEdit:hover {{
                    background-color: {button_bg_hover};
                    color: {button_text_hover};
                    border: 1px solid {button_border_hover};
                }}
            """)


class FilterDialog(QDialog):
    """Dialog for editing filter patterns"""
    
    def _get_focus_colors(self):
        """Get focus colors matching application standard"""
        from thumbnail_constants import CURRENT_IMAGE_BACKGROUND_COLOR, CURRENT_IMAGE_BORDER_COLOR
        focus_bg = qtcolor_to_hex(CURRENT_IMAGE_BACKGROUND_COLOR)
        focus_border = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        focus_text = BUTTON_FOCUS_TEXT_HEX
        return focus_bg, focus_border, focus_text
    
    def __init__(self, filters: List[str], parent=None, current_filter: Optional[str] = None):
        super().__init__(parent)
        self.original_filters = filters.copy()
        self.filter_widgets: List[FilterEntryWidget] = []
        # Store current filter for pre-filling new entries
        self.current_filter = current_filter
        
        # Convert QColor constants to hex strings
        def qtcolor_to_hex(color):
            """Convert QColor to hex string"""
            return f"#{color.red():02x}{color.green():02x}{color.blue():02x}"
        
        bg_color = qtcolor_to_hex(DEFAULT_BACKGROUND_COLOR)
        border_color = qtcolor_to_hex(DEFAULT_BORDER_COLOR)
        accent_border = qtcolor_to_hex(CURRENT_IMAGE_BORDER_COLOR)
        
        self.setWindowTitle("Edit Filters")
        self.setMinimumWidth(200)
        self.setMinimumHeight(300)
        
        # Dark theme styling using constants
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
            QScrollArea {{
                background-color: {bg_color};
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {bg_color};
            }}
        """)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)
        
        # Scroll area for filter entries
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_widget)
        self.scroll_layout.setSpacing(8)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        
        # Add existing filters (excluding '*' and empty)
        for pattern in filters:
            if pattern and pattern.strip() and pattern.strip() != '*':
                self._add_filter_entry(pattern.strip())
        
        # Add stretch at the end
        self.scroll_layout.addStretch()
        
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)
        
        # Bottom buttons layout
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)
        
        # Add button (+) - use standard application colors
        add_button_size = 16
        button_bg_default = BUTTON_BG_DEFAULT_HEX
        button_text_default = BUTTON_TEXT_DEFAULT_HEX
        button_border_default = BUTTON_BORDER_DEFAULT_HEX
        button_bg_hover = BUTTON_BG_HOVER_HEX
        button_text_hover = BUTTON_TEXT_HOVER_HEX
        button_border_hover = BUTTON_BORDER_HOVER_HEX
        button_bg_pressed = BUTTON_BG_PRESSED_HEX
        focus_bg, focus_border, focus_text = self._get_focus_colors()
        
        self.add_button = QPushButton("+")
        self.add_button.setFixedSize(24, 24)
        self.add_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.add_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {button_bg_default};
                color: {button_text_default};
                border: 1px solid {button_border_default};
                border-radius: 4px;
                font-size: 18px;
                font-weight: bold;
                min-width: {add_button_size}px;    
                max-width: {add_button_size}px;
                min-height: {add_button_size}px;
                max-height: {add_button_size}px;
            }}
            QPushButton:focus {{
                background-color: {focus_bg};
                color: {focus_text};
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
                color: {focus_text};
            }}
        """)
        self.add_button.setToolTip("Add a new filter")
        self.add_button.clicked.connect(self._add_new_filter)
        bottom_layout.addWidget(self.add_button, 0)
        
        bottom_layout.addStretch()
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        button_box.button(QDialogButtonBox.Ok).setText("OK")
        button_box.button(QDialogButtonBox.Cancel).setText("Cancel")
        
        self.ok_button = button_box.button(QDialogButtonBox.Ok)
        self.cancel_button = button_box.button(QDialogButtonBox.Cancel)
        
        # Calculate button widths based on text content + padding
        # Use the button's font (which includes stylesheet font settings)
        font_metrics = QFontMetrics(self.ok_button.font())
        # Padding from stylesheet: 6px 14px (left/right = 14px each side)
        horizontal_padding = 14 * 2  # 14px on each side
        
        # Calculate width for OK button
        ok_text_width = font_metrics.horizontalAdvance("OK")
        ok_min_width = ok_text_width + horizontal_padding
        
        # Calculate width for Cancel button
        cancel_text_width = font_metrics.horizontalAdvance("Cancel")
        cancel_min_width = cancel_text_width + horizontal_padding
        
        # Set minimum widths (buttons will size to content)
        self.ok_button.setMinimumWidth(ok_min_width)
        self.cancel_button.setMinimumWidth(cancel_min_width)
        
        # Use Preferred size policy so buttons size to content but can shrink if needed
        self.ok_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.cancel_button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        
        # Initially disable OK button if filters are invalid
        self._validate_all_filters()
        
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        bottom_layout.addWidget(button_box)
        main_layout.addLayout(bottom_layout)
        
        # Connect text changes to validation
        self._connect_validation()
    
    def _add_filter_entry(self, pattern: str = "") -> FilterEntryWidget:
        """Add a new filter entry widget"""
        entry = FilterEntryWidget(pattern, self)
        entry.delete_requested.connect(self._remove_filter_entry)
        entry.text_input.textChanged.connect(self._validate_all_filters)
        
        # Insert before stretch
        stretch_index = self.scroll_layout.count() - 1
        self.scroll_layout.insertWidget(stretch_index, entry)
        self.filter_widgets.append(entry)
        
        # Validate the new entry
        self._validate_entry(entry)
        
        return entry
    
    def _add_new_filter(self):
        """Add a new filter entry, pre-filled with current filter if not in list"""
        # Check if current filter should be pre-filled
        initial_pattern = ""
        if self.current_filter:
            # Normalize current filter for comparison (remove trailing *)
            current_normalized = self.current_filter.rstrip('*')
            if current_normalized == '':
                current_normalized = '*'
            
            # Check if current filter is already in the list
            is_in_list = False
            for widget in self.filter_widgets:
                widget_pattern = widget.get_pattern().strip()
                widget_normalized = widget_pattern.rstrip('*')
                if widget_normalized == '':
                    widget_normalized = '*'
                if widget_normalized == current_normalized:
                    is_in_list = True
                    break
            
            # Also check against original filters
            if not is_in_list:
                for saved_filter in self.original_filters:
                    saved_normalized = saved_filter.rstrip('*')
                    if saved_normalized == '':
                        saved_normalized = '*'
                    if saved_normalized == current_normalized:
                        is_in_list = True
                        break
            
            # Pre-fill with current filter if not in list and not '*'
            if not is_in_list and current_normalized != '*':
                initial_pattern = current_normalized
        
        entry = self._add_filter_entry(initial_pattern)
        entry.text_input.setFocus()
    
    def _remove_filter_entry(self, widget: FilterEntryWidget):
        """Remove a filter entry widget"""
        if widget in self.filter_widgets:
            self.filter_widgets.remove(widget)
            widget.setParent(None)
            widget.deleteLater()
            self._validate_all_filters()
    
    def _connect_validation(self):
        """Connect all text inputs to validation"""
        for widget in self.filter_widgets:
            widget.text_input.textChanged.connect(self._validate_all_filters)
    
    def _validate_all_filters(self) -> bool:
        """Validate all filter patterns and enable/disable OK button"""
        all_valid = True
        
        # Validate each entry
        for widget in self.filter_widgets:
            is_valid, error_msg = self._validate_entry(widget)
            if not is_valid:
                all_valid = False
        
        self.ok_button.setEnabled(all_valid)
        return all_valid
    
    def _validate_entry(self, widget: FilterEntryWidget) -> Tuple[bool, str]:
        """Validate a single filter entry and update its validation state"""
        pattern = widget.get_pattern()
        
        # Empty patterns are allowed (will be filtered out)
        if not pattern:
            widget.set_validation_state(True, "")
            return True, ""
        
        # '*' pattern is allowed but will be ignored
        if pattern.strip() == '*':
            widget.set_validation_state(True, "")
            return True, ""
        
        # Validate pattern
        is_valid, error_msg = self._validate_filter_pattern(pattern)
        widget.set_validation_state(is_valid, error_msg)
        return is_valid, error_msg
    
    def _validate_filter_pattern(self, pattern: str) -> Tuple[bool, str]:
        """Validate a single filter pattern using fnmatch
        
        Returns:
            tuple: (is_valid, error_message)
        """
        if not pattern:
            return True, ""
        
        # Check for path separators (patterns must be basename only)
        if '/' in pattern or '\\' in pattern:
            return False, "Pattern cannot contain path separators (/, \\)"
        
        # Check for colon (macOS path separator)
        if ':' in pattern:
            return False, "Pattern cannot contain colon (:) - basename only"
        
        # Check for basic syntax errors
        if pattern.count('[') != pattern.count(']'):
            return False, "Unmatched brackets [ ]"
        
        try:
            # Test the pattern with fnmatch
            test_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(pattern)
            # Try to compile the pattern
            fnmatch.translate(test_pattern)
            return True, ""
        except Exception as e:
            return False, f"Invalid pattern syntax: {str(e)}"
    
    def get_filters(self) -> List[str]:
        """Get the list of filters from the dialog"""
        filters = []
        for widget in self.filter_widgets:
            pattern = widget.get_pattern().strip()
            # Skip empty patterns and '*'
            if pattern and pattern != '*':
                filters.append(pattern)
        return filters
    
    @staticmethod
    def edit_filters(filters: List[str], parent=None, current_filter: Optional[str] = None) -> Optional[List[str]]:
        """Static method to show the dialog and return the edited filters"""
        dialog = FilterDialog(filters, parent, current_filter)
        if dialog.exec() == QDialog.Accepted:
            return dialog.get_filters()
        return None

def main():
    import sys
    app = QApplication(sys.argv)
    dummy_filters = ["*.jpg", "*.png", "holiday_*", "*backup?.zip", "202[1-3]*.tif", "*.heic"]
    dlg = FilterDialog(dummy_filters)
    dlg.exec()
    # No app exit or model updates, just show dialog

if __name__ == "__main__":
    main()