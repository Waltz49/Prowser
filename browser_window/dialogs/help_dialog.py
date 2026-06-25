#!/usr/bin/env python3
"""
Help Dialog for Image Browser
Displays keyboard shortcuts and menu bindings in a modal dialog
"""

# Standard library imports
import os
import re
from typing import Dict

# Third-party imports
from PySide6.QtCore import Qt, QEvent, QRect, QPoint, QSize, QObject
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QPainter, QColor, QPen, QBrush, QPixmap
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QScrollArea, QSizePolicy

# Local imports
from keyboard_handler import KeyboardHandlerManager
from config import get_config
from tooltip_popup_utils import ensure_tooltip_label, position_tooltip_near_cursor
from thumbnails.thumbnail_constants import (
    DIALOG_BACKGROUND_HEX, DIALOG_TEXT_COLOR_HEX, ERROR_COLOR_HEX,
    DEFAULT_BORDER_COLOR_HEX, HEADING_COLOR_HEX,
    BUTTON_TEXT_HOVER_HEX, BUTTON_BG_DEFAULT_HEX, BUTTON_TEXT_DEFAULT_HEX,
    MODIFIER_SYMBOLS,
)

# Color constants (help-dialog-specific; base colors from thumbnail_constants)
COLOR_BACKGROUND = DIALOG_BACKGROUND_HEX
COLOR_KEY_BOX_BG = BUTTON_BG_DEFAULT_HEX
COLOR_KEY_TEXT = BUTTON_TEXT_DEFAULT_HEX
COLOR_BORDER = DEFAULT_BORDER_COLOR_HEX
COLOR_TEXT = DIALOG_TEXT_COLOR_HEX
COLOR_TITLE_TEXT = HEADING_COLOR_HEX
COLOR_INSTRUCTION_TEXT = DIALOG_TEXT_COLOR_HEX
COLOR_ASTERISK = ERROR_COLOR_HEX
COLOR_ACTIVE_HEADER_TEXT = BUTTON_TEXT_HOVER_HEX
COLOR_INACTIVE_HEADER_TEXT = DIALOG_TEXT_COLOR_HEX


class HelpContentWidget(QWidget):
    """Custom widget that paints help content using QPainter"""
    
    def __init__(self, all_keys, sort_order, parent=None):
        super().__init__(parent)
        self.all_keys = all_keys
        self.sort_order = sort_order
        self.font = QFont("Menlo", 13)
        self.font_metrics = QFontMetrics(self.font)
        self.bold_font = QFont("Menlo", 13)
        self.bold_font.setBold(True)
        self.bold_font_metrics = QFontMetrics(self.bold_font)
        # Larger font for modifier keys
        self.modifier_font = QFont("Menlo", 20)
        self.modifier_font_metrics = QFontMetrics(self.modifier_font)
        # Increase row height to accommodate key boxes and separator line
        # Key boxes extend from baseline - (base_height + 4) to baseline + 4
        # Separator should be below boxes, at baseline + 9
        # Need space above baseline too, so total: (base_height + 4) + 9 = base_height + 13
        base_height = self.font_metrics.height()
        modifier_height = self.modifier_font_metrics.height()
        # Use the larger of base or modifier height to ensure both fit
        max_key_height = max(base_height, modifier_height)
        self.row_height = max_key_height + 8  # Extra space for key box padding and separator (reduced by 6px)
        self.key_col_width = 200
        self.desc_col_width = 300
        self.col_spacing = 20
        self.padding = 10
        
        self.modifier_symbols = MODIFIER_SYMBOLS
        
        self._prepare_data()
        self._calculate_size()
    
    def _prepare_data(self):
        """Prepare sorted keys and split into columns"""
        # Use the same sorting logic as before
        def sort_key_default(key_str):
            if '+' in key_str:
                base_key = key_str.split('+')[-1]
                modifiers = key_str.split('+')[:-1]
            else:
                base_key = key_str
                modifiers = []
            
            has_cmd = 'Cmd' in modifiers
            has_shift = 'Shift' in modifiers
            has_ctrl = 'Ctrl' in modifiers
            if has_cmd and has_shift:
                modifier_priority = 3
            elif has_shift:
                modifier_priority = 2
            elif has_cmd:
                modifier_priority = 1
            elif has_ctrl:
                modifier_priority = 4
            else:
                modifier_priority = 0
            
            if base_key.startswith('F') and len(base_key) > 1:
                try:
                    function_key_num = int(base_key[1:])
                    return (2, function_key_num, modifier_priority)
                except ValueError:
                    pass
            
            if base_key.isdigit():
                number_value = int(base_key)
                return (1.5, modifier_priority, number_value)
            
            is_single_char = len(base_key) == 1 and base_key.isalnum()
            return (0 if is_single_char else 1, base_key, modifier_priority)
        
        def sort_key_by_description(key_str, keys_dict):
            desc = keys_dict.get(key_str, '')
            desc_clean = desc.rstrip(" *") if isinstance(desc, str) else str(desc)
            
            if '+' in key_str:
                parts = key_str.split('+')
                if len(parts) == 2:
                    modifier, base_key = parts[0].strip(), parts[1].strip()
                    if modifier.lower() in ('ctrl', 'control', 'cmd') and base_key.isdigit():
                        number_value = int(base_key)
                        modifier_priority = 1 if modifier.lower() == 'cmd' else 2
                        return ('0', str(modifier_priority).zfill(2), str(number_value).zfill(2), desc_clean.lower())
            
            return ('1', desc_clean.lower(), key_str)
        
        def normalize_key_name(key):
            if not key:
                return ""
            key_str = str(key)
            if key_str == '\b' or key_str == '\x08' or key_str.lower() == 'backspace':
                return 'Backspace'
            if key_str == '\x7f' or key_str == '\x1b[3~]' or key_str.lower() == 'delete':
                return 'Delete'
            if key_str == '+':
                return '+'
            if len(key_str) == 1:
                char_code = ord(key_str)
                if 0xF704 <= char_code <= 0xF70F:
                    function_num = char_code - 0xF704 + 1
                    return f'F{function_num}'
                if 0x01 <= char_code <= 0x0C and char_code != 0x08:
                    function_num = char_code
                    return f'F{function_num}'
            return key_str
        
        # Sort keys
        if self.sort_order == 0:
            sorted_keys = sorted(self.all_keys.keys(), key=sort_key_default)
        else:
            sorted_keys = sorted(self.all_keys.keys(), key=lambda k: sort_key_by_description(k, self.all_keys))
        
        # Split into two columns
        mid_point = (len(sorted_keys) + 1) // 2
        self.left_keys = sorted_keys[:mid_point]
        self.right_keys = sorted_keys[mid_point:]
    
    def _calculate_key_width(self, key_str):
        """Calculate the width needed to draw a key"""
        if not key_str:
            return 0
        
        parts = key_str.split('+') if '+' in key_str else [key_str]
        base_key = parts[-1].strip() if parts else ""
        modifiers = [p.strip() for p in parts[:-1]] if len(parts) > 1 else []
        
        def normalize_key_name(key):
            if not key:
                return ""
            key_str = str(key)
            if key_str == '\b' or key_str == '\x08' or key_str.lower() == 'backspace':
                return 'Backspace'
            if key_str == '\x1b[3~]' or key_str.lower() == 'delete':
                return 'Delete'
            if key_str == '+':
                return '+'
            if len(key_str) == 1:
                char_code = ord(key_str)
                if 0xF704 <= char_code <= 0xF70F:
                    function_num = char_code - 0xF704 + 1
                    return f'F{function_num}'
            return key_str
        
        base_key = normalize_key_name(base_key)
        base_width = self.font_metrics.horizontalAdvance(base_key) + 12
        
        modifier_order = {'Shift': 0, 'Cmd': 1, 'Ctrl': 2, 'Alt': 3, 'Option': 3}
        sorted_modifiers = sorted(modifiers, key=lambda m: modifier_order.get(m, 999))
        
        total_width = base_width + 4
        for idx, mod in enumerate(sorted_modifiers):
            # Add "+" only before the first modifier if there's a base key
            if base_key and idx == 0:
                total_width += self.font_metrics.horizontalAdvance("+") + 4
            mod_symbol = self.modifier_symbols.get(mod, mod)
            # Use larger modifier font metrics for width calculation
            mod_width = self.modifier_font_metrics.horizontalAdvance(mod_symbol) + 12
            # Make modifiers adjacent (no spacing between modifier boxes)
            total_width += mod_width
        
        return total_width
    
    def _calculate_size(self):
        """Calculate widget size based on content"""
        max_rows = max(len(self.left_keys), len(self.right_keys))
        height = (max_rows + 1) * self.row_height + self.padding * 2  # +1 for header
        
        # Calculate dynamic widths
        left_max_key_width = max([self._calculate_key_width(str(key)) for key in self.left_keys], default=0)
        right_max_key_width = max([self._calculate_key_width(str(key)) for key in self.right_keys], default=0)
        
        left_max_desc_width = max([self.font_metrics.horizontalAdvance(
            str(self.all_keys[key]).rstrip(" *")) for key in self.left_keys], default=0)
        right_max_desc_width = max([self.font_metrics.horizontalAdvance(
            str(self.all_keys[key]).rstrip(" *")) for key in self.right_keys], default=0)
        
        key_desc_gap = 12
        col_gap = 60  # Gap between description1 and keys2
        left_desc_x = left_max_key_width + key_desc_gap
        right_key_x = left_desc_x + left_max_desc_width + col_gap
        right_desc_x = right_key_x + right_max_key_width + key_desc_gap
        total_width = right_desc_x + right_max_desc_width + self.padding
        
        self.setMinimumSize(total_width, height)
    
    def _draw_key_box(self, painter, x, y, text):
        """Draw a styled key box and return the total width used"""
        if not text:
            return 0
        
        # Parse key string to extract base key and modifiers
        parts = text.split('+') if '+' in text else [text]
        base_key = parts[-1].strip() if parts else ""
        modifiers = [p.strip() for p in parts[:-1]] if len(parts) > 1 else []
        
        # Normalize base key name
        def normalize_key_name(key):
            if not key:
                return ""
            key_str = str(key)
            if key_str == '\b' or key_str == '\x08' or key_str.lower() == 'backspace':
                return 'Backspace'
            if key_str == '\x1b[3~]' or key_str.lower() == 'delete':
                return 'Delete'
            if key_str == '+':
                return '+'
            if len(key_str) == 1:
                char_code = ord(key_str)
                if 0xF704 <= char_code <= 0xF70F:
                    function_num = char_code - 0xF704 + 1
                    return f'F{function_num}'
            return key_str
        
        base_key = normalize_key_name(base_key)
        
        # Draw base key first
        base_text = base_key
        base_rect = self.font_metrics.boundingRect(base_text)
        base_width = base_rect.width()
        base_height = base_rect.height()
        
        # Draw base key box
        # Position box so text baseline is centered vertically in the box
        key_box_height = base_height + 8  # Padding: 2px top, 6px bottom
        key_box_width = base_width + 12
        # Position box: y is text baseline, box should extend above and below
        # Position box so baseline is 2px from top (leaving 6px at bottom)
        box_top = y - base_height - 2
        box_bottom = box_top + key_box_height
        
        painter.setPen(QPen(QColor(COLOR_BORDER), 1))
        painter.setBrush(QBrush(QColor(COLOR_KEY_BOX_BG)))
        painter.drawRoundedRect(x, box_top, key_box_width, key_box_height, 3, 3)
        
        painter.setPen(QPen(QColor(COLOR_KEY_TEXT)))
        painter.setFont(self.font)
        painter.drawText(x + 6, y, base_text)
        
        current_x = x + key_box_width + 4
        
        # Draw modifier symbols after the base key with "+" only before the first modifier
        modifier_order = {'Shift': 0, 'Cmd': 1, 'Ctrl': 2, 'Alt': 3, 'Option': 3}
        sorted_modifiers = sorted(modifiers, key=lambda m: modifier_order.get(m, 999))
        
        for idx, mod in enumerate(sorted_modifiers):
            # Add "+" only before the first modifier if there's a base key
            if base_key and idx == 0:
                plus_width = self.font_metrics.horizontalAdvance("+")
                painter.setPen(QPen(QColor(COLOR_TEXT)))
                painter.drawText(current_x, y, "+")
                current_x += plus_width + 4
            
            mod_symbol = self.modifier_symbols.get(mod, mod)
            mod_text = mod_symbol
            
            # Use larger font metrics for modifier keys
            mod_rect = self.modifier_font_metrics.boundingRect(mod_text)
            mod_width = mod_rect.width()
            mod_height = mod_rect.height()
            
            # Make modifier box same height as base key box
            base_box_height = base_height + 8  # Base key box height
            mod_box_height = base_box_height  # Match base box height
            mod_box_width = mod_width + 12
            # Position modifier box to align with base key box (same top position)
            mod_box_top = box_top  # Use same top as base key box
            
            painter.setPen(QPen(QColor(COLOR_BORDER), 1))
            painter.setBrush(QBrush(QColor(COLOR_KEY_BOX_BG)))
            painter.drawRoundedRect(current_x, mod_box_top, mod_box_width, mod_box_height, 3, 3)
            
            # Center modifier text vertically within the box
            # Box center vertically: mod_box_top + mod_box_height / 2
            # Text baseline calculation: baseline = box_center + ascent - height/2
            box_center_y = mod_box_top + mod_box_height / 2
            modifier_baseline_y = box_center_y + self.modifier_font_metrics.ascent() - self.modifier_font_metrics.height() / 2
            
            painter.setPen(QPen(QColor(COLOR_KEY_TEXT)))
            painter.setFont(self.modifier_font)  # Use larger font for modifier symbols
            painter.drawText(current_x + 6, modifier_baseline_y, mod_text)
            painter.setFont(self.font)  # Reset to regular font after drawing modifier
            
            # Make modifiers adjacent (no spacing between modifier boxes)
            current_x += mod_box_width
        
        return current_x - x
    
    def paintEvent(self, event):
        """Paint the help content"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Set background
        painter.fillRect(self.rect(), QColor(COLOR_BACKGROUND))
        
        # Set font
        painter.setFont(self.font)
        painter.setPen(QPen(QColor(COLOR_TEXT)))
        
        # Calculate maximum key widths for both columns dynamically
        left_max_key_width = max([self._calculate_key_width(str(key)) for key in self.left_keys], default=0)
        right_max_key_width = max([self._calculate_key_width(str(key)) for key in self.right_keys], default=0)
        
        # Calculate description column widths
        left_max_desc_width = max([self.font_metrics.horizontalAdvance(
            str(self.all_keys[key]).rstrip(" *")) for key in self.left_keys], default=0)
        right_max_desc_width = max([self.font_metrics.horizontalAdvance(
            str(self.all_keys[key]).rstrip(" *")) for key in self.right_keys], default=0)
        
        # Set spacing between key and description (small gap)
        key_desc_gap = 12
        
        # Calculate column positions dynamically
        # Use actual widths of each column, not maximums
        left_key_x = self.padding
        left_desc_x = left_key_x + left_max_key_width + key_desc_gap
        # Only ~30px gap between end of description1 and start of keys2
        col_gap = 30
        right_key_x = left_desc_x + left_max_desc_width + col_gap
        right_desc_x = right_key_x + right_max_key_width + key_desc_gap
        
        # Calculate total width needed
        total_width = right_desc_x + right_max_desc_width + self.padding
        
        y = self.padding + self.row_height
        
        # Draw header with bold active sort word and directional arrow
        arrow = " ↑"
        
        # Left column header
        if self.sort_order == 0:
            # Bold "Key" and add arrow
            painter.setFont(self.bold_font)
            painter.setPen(QPen(QColor(COLOR_ACTIVE_HEADER_TEXT)))
            painter.drawText(left_key_x, y, "Key")
            key_text_width = self.bold_font_metrics.horizontalAdvance("Key")
            painter.drawText(left_key_x + key_text_width, y, arrow)
            # Normal "Description"
            painter.setFont(self.font)
            painter.setPen(QPen(QColor(COLOR_INACTIVE_HEADER_TEXT)))
            painter.drawText(left_desc_x, y, "Description")
        else:
            # Normal "Key"
            painter.setFont(self.font)
            painter.setPen(QPen(QColor(COLOR_INACTIVE_HEADER_TEXT)))
            painter.drawText(left_key_x, y, "Key")
            # Bold "Description" and add arrow
            painter.setFont(self.bold_font)
            painter.setPen(QPen(QColor(COLOR_ACTIVE_HEADER_TEXT)))
            painter.drawText(left_desc_x, y, "Description")
            desc_text_width = self.bold_font_metrics.horizontalAdvance("Description")
            painter.drawText(left_desc_x + desc_text_width, y, arrow)
        
        # Right column header
        painter.setFont(self.font)
        painter.setPen(QPen(QColor(COLOR_TEXT)))
        if self.sort_order == 0:
            # Bold "Key" and add arrow
            painter.setFont(self.bold_font)
            painter.setPen(QPen(QColor(COLOR_ACTIVE_HEADER_TEXT)))
            painter.drawText(right_key_x, y, "Key")
            key_text_width = self.bold_font_metrics.horizontalAdvance("Key")
            painter.drawText(right_key_x + key_text_width, y, arrow)
            # Normal "Description"
            painter.setFont(self.font)
            painter.setPen(QPen(QColor(COLOR_INACTIVE_HEADER_TEXT)))
            painter.drawText(right_desc_x, y, "Description")
        else:
            # Normal "Key"
            painter.setFont(self.font)
            painter.setPen(QPen(QColor(COLOR_INACTIVE_HEADER_TEXT)))
            painter.drawText(right_key_x, y, "Key")
            # Bold "Description" and add arrow
            painter.setFont(self.bold_font)
            painter.setPen(QPen(QColor(COLOR_ACTIVE_HEADER_TEXT)))
            painter.drawText(right_desc_x, y, "Description")
            desc_text_width = self.bold_font_metrics.horizontalAdvance("Description")
            painter.drawText(right_desc_x + desc_text_width, y, arrow)
        
        # Reset font for rest of drawing
        painter.setFont(self.font)
        
        # Draw header underline (at bottom of header row, matching data rows)
        painter.setPen(QPen(QColor(COLOR_BORDER), 1))
        # Position header separator same way as row separators
        header_y = y + 9
        # Draw separate lines for left and right column pairs (excluding gap)
        left_separator_end = left_desc_x + left_max_desc_width
        right_separator_end = right_desc_x + right_max_desc_width
        painter.drawLine(left_key_x, header_y, left_separator_end, header_y)
        painter.drawLine(right_key_x, header_y, right_separator_end, header_y)
        
        y += self.row_height
        
        # Draw rows
        max_rows = max(len(self.left_keys), len(self.right_keys))
        for i in range(max_rows):
            row_y = y + i * self.row_height
            
            # Left column
            if i < len(self.left_keys):
                left_key = self.left_keys[i]
                left_desc = self.all_keys[left_key]
                
                # Remove asterisk for display
                if isinstance(left_desc, str) and left_desc.endswith(" *"):
                    left_desc_display = left_desc[:-2]
                    has_asterisk = True
                else:
                    left_desc_display = str(left_desc) if left_desc else ""
                    has_asterisk = False
                
                # Draw key (moved up 1px to vertically center)
                key_y = row_y - 1
                key_width = self._draw_key_box(painter, left_key_x, key_y, str(left_key))
                
                # Draw description (moved up 1px to match key)
                painter.setPen(QPen(QColor(COLOR_TEXT)))
                painter.drawText(left_desc_x, key_y, left_desc_display)
                
                # Draw asterisk if present
                if has_asterisk:
                    asterisk_x = left_desc_x + self.font_metrics.horizontalAdvance(left_desc_display) + 2
                    painter.setPen(QPen(QColor(COLOR_ASTERISK)))
                    painter.drawText(asterisk_x, key_y, "*")
            
            # Right column
            if i < len(self.right_keys):
                right_key = self.right_keys[i]
                right_desc = self.all_keys[right_key]
                
                # Remove asterisk for display
                if isinstance(right_desc, str) and right_desc.endswith(" *"):
                    right_desc_display = right_desc[:-2]
                    has_asterisk = True
                else:
                    right_desc_display = str(right_desc) if right_desc else ""
                    has_asterisk = False
                
                # Draw key (moved up 1px to vertically center)
                key_y = row_y - 1
                key_width = self._draw_key_box(painter, right_key_x, key_y, str(right_key))
                
                # Draw description (moved up 1px to match key)
                painter.setPen(QPen(QColor(COLOR_TEXT)))
                painter.drawText(right_desc_x, key_y, right_desc_display)
                
                # Draw asterisk if present
                if has_asterisk:
                    asterisk_x = right_desc_x + self.font_metrics.horizontalAdvance(right_desc_display) + 2
                    painter.setPen(QPen(QColor(COLOR_ASTERISK)))
                    painter.drawText(asterisk_x, key_y, "*")
            
            # Draw row border at bottom of row, positioned below key boxes
            # Key boxes extend to row_y + 6 (box bottom), so separator should be below that
            painter.setPen(QPen(QColor(COLOR_BORDER), 1))
            # Position separator below key boxes: boxes bottom at row_y + 6, separator at row_y + 9
            border_y = row_y + 9
            # Draw separate lines for left and right column pairs (excluding gap)
            # Only draw separators if this is not the last row in each column
            left_separator_end = left_desc_x + left_max_desc_width
            right_separator_end = right_desc_x + right_max_desc_width
            # Draw left separator only if not the last row in left column
            if i < len(self.left_keys) - 1:
                painter.drawLine(left_key_x, border_y, left_separator_end, border_y)
            # Draw right separator only if not the last row in right column
            if i < len(self.right_keys) - 1:
                painter.drawLine(right_key_x, border_y, right_separator_end, border_y)


class HelpDialog:
    """Manages help dialog functionality, extracted from ImageBrowserWindow"""
    
    def __init__(self, window):
        """Initialize help dialog handler"""
        self.main_window = window
        self.dialog = None
    
    def show_help(self):
        """Show help dialog in a modal window"""
        
        keyboard_handler = KeyboardHandlerManager(self.main_window)
        help_dict = keyboard_handler.get_key_bindings_help()
        
        # Update favorite directory descriptions to show actual paths
        # and filter out invalid favorites
        config = get_config()
        settings = config.load_settings()
        favorites = settings.get('favorite_directories', [None] * 9)
        # Ensure we have exactly 9 items
        favorites = (favorites + [None] * 9)[:9]
        
        # Update help_dict with actual favorite paths and remove invalid ones
        # Find keys that match Ctrl+number pattern (could be "Ctrl+1", "Ctrl+2", etc.)
        keys_to_remove = []
        for key_str in list(help_dict.keys()):
            # Check if this is a Ctrl+number key (1-9)
            if '+' in key_str:
                parts = key_str.split('+')
                if len(parts) == 2:
                    modifier, number = parts[0].strip(), parts[1].strip()
                    # Check if it's Ctrl modifier and a number 1-9
                    if modifier.lower() in ('ctrl', 'control') and number.isdigit():
                        num = int(number)
                        if 1 <= num <= 9:
                            favorite_path = favorites[num-1] if num-1 < len(favorites) else None
                            if favorite_path and favorite_path.strip():
                                favorite_path = favorite_path.strip()
                                # Check if file or directory exists
                                if os.path.exists(favorite_path):
                                    # Update description to show actual path, replacing home dir with ~
                                    display_path = favorite_path
                                    home_dir = os.path.expanduser("~")
                                    if display_path.startswith(home_dir):
                                        display_path = "~" + display_path[len(home_dir):]
                                    help_dict[key_str] = f"Open {display_path}"
                                else:
                                    # Remove invalid favorite from help display
                                    keys_to_remove.append(key_str)
                            else:
                                # Remove empty favorite from help display
                                keys_to_remove.append(key_str)
        
        # Remove invalid favorites
        for key in keys_to_remove:
            if key in help_dict:
                del help_dict[key]
        
        menu_data = self.main_window.menu_manager.query_menu_keys()
        
        # System menu items to exclude (keep only Preferences...)
        system_menu_items = {
            "About...", "About", "Quit", "Exit", "Hide", "Hide Others", 
            "Show All", "Services", "Minimize", "Zoom", "Bring All to Front"
        }
        
        # Combine help_dict (local keys) and menu_data (menu keys) into a single dictionary
        all_keys = dict(help_dict)
        for entry in menu_data:
            key = entry.get('key_name')
            desc = entry.get('key_description', '')
            active = entry.get('key_active', True)
            # Filter out system menu items except Preferences...
            desc_clean = desc.rstrip(" *") if isinstance(desc, str) else str(desc)
            if desc_clean in system_menu_items:
                continue
            # Only add if active and not already in all_keys
            if key and active and key not in all_keys:
                # Fix Delete key misidentification: if description contains "Delete",
                # normalize the key to use "Delete" instead of function key codes
                desc_lower = desc_clean.lower()
                if 'delete' in desc_lower and key:
                    # Check if key contains a function key code that might be Delete
                    # Split by '+' to check the base key
                    if '+' in key:
                        parts = key.split('+')
                        base_key = parts[-1]
                        modifiers = parts[:-1]
                        # If base key is a single character that might be Delete misidentified as F8
                        if len(base_key) == 1:
                            char_code = ord(base_key)
                            # 0xF70B is F8, but if description says Delete, it's actually Delete
                            if char_code == 0xF70B:
                                # Replace F8 with Delete
                                normalized_key = '+'.join(modifiers + ['Delete'])
                                if normalized_key not in all_keys:
                                    key = normalized_key
                    elif len(key) == 1:
                        char_code = ord(key)
                        if char_code == 0xF70B:
                            key = 'Delete'
                
                # Remove asterisk for menu items if present
                if isinstance(desc, str) and desc.endswith(" *"):
                    desc = desc[:-2]
                all_keys[key] = desc
        
        # Replace home directory paths with ~ in all descriptions
        home_dir = os.path.expanduser("~")
        for key, desc in all_keys.items():
            if isinstance(desc, str) and home_dir in desc:
                all_keys[key] = desc.replace(home_dir, "~")
        
        # Deduplicate Enter/Return: when both have same purpose, show only Return
        for key in list(all_keys.keys()):
            if key == "Enter" or key.endswith("+Enter"):
                return_key = key.replace("Enter", "Return")
                if return_key in all_keys and all_keys[return_key] == all_keys[key]:
                    del all_keys[key]
        
        # Consolidate sort actions: show 1 entry per sort type with "add [shift] for reverse"
        sort_consolidations = [
            ("D", "Shift+D", "Sort by date (old-new):   + ⬆️ (new-old)"),
            ("N", "Shift+N", "Sort by name (A-Z):       + ⬆️ (Z-A)"),
            ("Z", "Shift+Z", "Sort by area (big-small): + ⬆️ (small-big)"),
            ("X", "Shift+X", "Sort by month (new-old):  + ⬆️ (old-new)"),
            ("Y", "Shift+Y", "Sort by year (new-old):   + ⬆️ (old-new)"),
        ]
        for base_key, shift_key, consolidated_desc in sort_consolidations:
            if shift_key in all_keys:
                del all_keys[shift_key]
            if base_key in all_keys:
                all_keys[base_key] = consolidated_desc
        
        if not all_keys:
            return True
        
        # Create modal dialog
        dialog = QDialog(self.main_window)
        self.dialog = dialog
        dialog.setWindowTitle("Key Bindings Help")
        dialog.setModal(True)
        dialog.setSizeGripEnabled(True)  # Allows resizing
        from utils import get_dialog_shell_stylesheet

        dialog.setStyleSheet(get_dialog_shell_stylesheet())
        
        # Create layout
        layout = QVBoxLayout(dialog)
        
        # Determine current view mode
        current_mode = "thumbnail"  # Default
        if hasattr(self.main_window, 'is_fullscreen') and self.main_window.is_fullscreen:
            current_mode = 'browse'
        elif hasattr(self.main_window, 'current_view_mode'):
            current_mode = self.main_window.current_view_mode
        elif hasattr(self.main_window, 'view_mode'):
            current_mode = self.main_window.view_mode
        titles = {
            'thumbnail': 'Keys available when viewing thumbnails',
            'browse': 'Keys available when viewing an image',
            'slideshow': 'Keys available in the multi-image slideshow',
            'slideshow2': 'Keys available in the panning slideshow',
            'slideshow3': 'Keys available in the floating frames slideshow',
        }
        # Add title with floating instruction text in upper right
        title_widget = QWidget()
        title_widget.setFixedHeight(36)
        title_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        title_widget.setStyleSheet(f"background-color: {COLOR_BACKGROUND}; border-bottom: 1px solid {COLOR_TEXT};")
        
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(10, 0, 10, 0)
        title_layout.setSpacing(6)
        
        title = QLabel(titles[current_mode])
        title.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        title.setStyleSheet(f"background-color: transparent; font-size: 20px; font-weight: bold; padding: 0px; margin: 0px; color: {COLOR_TITLE_TEXT};")
        
        # Question mark icon with custom tooltip (QToolTip stylesheet unreliable on macOS)
        qmark_label = QLabel()
        qmark_path = os.path.join(os.path.dirname(__file__), "assets", "qmark.png")
        if os.path.exists(qmark_path):
            qmark_pixmap = QPixmap(qmark_path)
            if not qmark_pixmap.isNull():
                icon_size = 20
                scaled = qmark_pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                qmark_label.setPixmap(scaled)
        qmark_label.setStyleSheet("background-color: transparent;")
        qmark_tooltip_text = (
            "Each view has its own set of (mostly) context-sensitive keys.\n\n"
            "This list is dynamically generated and may have omissions or errors."
        )
        qmark_tooltip_label = ensure_tooltip_label(dialog, "_qmark_tooltip_label")
        qmark_tooltip_label.setStyleSheet(
            f"QLabel {{ background-color: {DIALOG_BACKGROUND_HEX}; color: {BUTTON_TEXT_HOVER_HEX}; "
            f"border: 1px solid {DEFAULT_BORDER_COLOR_HEX}; border-radius: 4px; padding: 4px 8px; font-size: 11pt; }}"
        )
        def qmark_show_tooltip():
            qmark_tooltip_label.setText(qmark_tooltip_text)
            qmark_tooltip_label.adjustSize()
            position_tooltip_near_cursor(qmark_tooltip_label, clamp_widget=dialog)
            qmark_tooltip_label.show()
            qmark_tooltip_label.raise_()
        def qmark_hide_tooltip():
            qmark_tooltip_label.hide()
        def qmark_event_filter(obj, event):
            if event.type() == QEvent.Type.Enter:
                qmark_show_tooltip()
            elif event.type() == QEvent.Type.Leave:
                qmark_hide_tooltip()
            return False
        qmark_filter = QObject(dialog)
        qmark_filter.eventFilter = qmark_event_filter
        qmark_label.installEventFilter(qmark_filter)
        dialog.finished.connect(qmark_hide_tooltip)
        
        instruction = QLabel("(use \u2190/\u2192 to change sort order, \u2191/\u2193 to scroll)")
        instruction.setStyleSheet(f"background-color: transparent; font-size: 11px; padding: 0px; margin: 0px; color: {COLOR_INSTRUCTION_TEXT};")
        instruction.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        title_layout.addStretch()
        title_layout.addWidget(title)
        title_layout.addWidget(qmark_label)
        title_layout.addStretch()
        title_layout.addWidget(instruction)
        
        layout.addWidget(title_widget)
        
        # Sort order: 0 = by keys (single char first, modifiers ordered: none, cmd, shift, shift_cmd), 1 = by description
        # Load saved sort order from config, default to 1 (by description) if not set
        config = get_config()
        saved_sort_order = config.load_settings().get('help_dialog_sort_order', 1)
        # Ensure sort_order is valid (0 or 1)
        saved_sort_order = max(0, min(1, int(saved_sort_order)))
        sort_order = [saved_sort_order]  # Use list to allow modification in nested functions
        
        if self.main_window.debug_mode:
            print("---- Help Dialog (help_dict) ----")
            for k, v in help_dict.items():
                print(f"{k}: {v}")
            print("---- End Help Dialog (help_dict) ----")
            
            print("---- Menu Data (menu_data) ----")
            for entry in menu_data:
                print(f"{entry['key_name']} - {entry['key_description']}, active: {entry['key_active']}")
            print("---- End Menu Data (menu_data) ----")
            
            print("---- All Keys (combined) ----")
            for k, v in all_keys.items():
                print(f"{k}: {v}")
            print("---- End All Keys (combined) ----")
        
        # Create custom widget to display help content
        content_widget = HelpContentWidget(all_keys, sort_order[0])
        
        # Create scroll area for the content widget
        scroll_area = QScrollArea()
        scroll_area.setWidget(content_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setStyleSheet(f"background-color: {COLOR_BACKGROUND};")
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Hide scroll bars but keep scrolling enabled (user will use gestures)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        layout.addWidget(scroll_area)
        
        # Calculate instruction text width for dialog sizing
        instruction_font = QFont("Menlo", 11)
        instruction_font_metrics = QFontMetrics(instruction_font)
        instruction_text_width = instruction_font_metrics.horizontalAdvance("(use \u2190/\u2192 to change sort order, \u2191/\u2193 to scroll)")
        
        # Get screen geometry for dialog sizing
        screen = QGuiApplication.screenAt(self.main_window.mapToGlobal(QPoint(0, 0))) if hasattr(self.main_window, 'mapToGlobal') else QGuiApplication.primaryScreen()
        geometry = screen.geometry() if screen else QGuiApplication.primaryScreen().geometry()
        screen_width = geometry.width()
        
        # Function to rebuild display with current sort order
        def rebuild_display(current_sort_order):
            # Update sort order in widget
            content_widget.sort_order = current_sort_order
            content_widget._prepare_data()
            content_widget._calculate_size()
            content_widget.update()  # Trigger repaint
            # Update dialog width to fit new content
            new_content_width = content_widget.minimumWidth()
            new_dialog_width = max(new_content_width, instruction_text_width + 20)
            new_dialog_width = min(screen_width - 80, new_dialog_width)
            dialog.setMinimumWidth(new_dialog_width)
            if dialog.width() < new_dialog_width:
                dialog.resize(new_dialog_width, dialog.height())
        
        # Build initial display
        rebuild_display(sort_order[0])
        
        # Get actual content width from widget after it's been sized
        content_width = content_widget.minimumWidth()
        
        # Handle ESC and Enter keys to close, arrow keys to cycle sort orders
        def keyPressEvent(event):
            if event.key() == Qt.Key_Escape \
            or event.key() == Qt.Key_Slash \
            or event.key() == Qt.Key_Return \
            or event.key() == Qt.Key_Space \
            or event.key() == Qt.Key_Enter:
                dialog.close()
            elif event.key() == Qt.Key_Left:
                # Cycle to previous sort order (only 0 and 1)
                sort_order[0] = (sort_order[0] - 1) % 2
                rebuild_display(sort_order[0])
                # Save sort order to config
                config.update_setting('help_dialog_sort_order', sort_order[0])
            elif event.key() == Qt.Key_Right:
                # Cycle to next sort order (only 0 and 1)
                sort_order[0] = (sort_order[0] + 1) % 2
                rebuild_display(sort_order[0])
                # Save sort order to config
                config.update_setting('help_dialog_sort_order', sort_order[0])
            elif event.key() == Qt.Key_Up:
                # Scroll up by 2 rows
                scroll_amount = content_widget.row_height * 2
                scroll_area.verticalScrollBar().setValue(
                    scroll_area.verticalScrollBar().value() - scroll_amount
                )
            elif event.key() == Qt.Key_Down:
                # Scroll down by 2 rows
                scroll_amount = content_widget.row_height * 2
                scroll_area.verticalScrollBar().setValue(
                    scroll_area.verticalScrollBar().value() + scroll_amount
                )
            else:
                QDialog.keyPressEvent(dialog, event)
        
        dialog.keyPressEvent = keyPressEvent
        
        # Override scroll area keyPressEvent to forward left/right arrows to dialog
        def scroll_area_keyPressEvent(event):
            if event.key() == Qt.Key_Left or event.key() == Qt.Key_Right:
                # Forward left/right arrows to dialog for sort order switching
                keyPressEvent(event)
            elif event.key() == Qt.Key_Up or event.key() == Qt.Key_Down:
                # Forward up/down arrows to dialog for scrolling by 2 rows
                keyPressEvent(event)
            else:
                # Let scroll area handle other keys
                QScrollArea.keyPressEvent(scroll_area, event)
        
        scroll_area.keyPressEvent = scroll_area_keyPressEvent
        
        # Override event() method on dialog to catch key events at higher level
        def dialog_event(event):
            """Override event() to ensure key events are handled"""
            if event.type() == QEvent.Type.KeyPress:
                # Let keyPressEvent handle it
                keyPressEvent(event)
                return True
            return QDialog.event(dialog, event)
        
        dialog.event = dialog_event
        dialog.setFocusPolicy(Qt.StrongFocus)
        
        # Calculate title width including instruction text
        title_font = QFont("Menlo", 20)
        title_font.setBold(True)
        title_font_metrics = QFontMetrics(title_font)
        title_text_width = title_font_metrics.horizontalAdvance(titles[current_mode])
        
        # Dialog width should accommodate both content width and instruction text
        # Use the larger of: content width or instruction text width + margin
        dialog_content_width = max(content_width, instruction_text_width + 20)  # 20px margin for instruction
        
        # Compute min size based on content width (including title)
        min_width = max(dialog_content_width, 600)  # Ensure minimum 600px for usability
        min_height = 400  # Reasonable default
        dialog.setMinimumWidth(min_width)
        dialog.setMinimumHeight(min_height)
        
        # Get screen geometry for window placement and height adjustment
        screen_left = geometry.left()
        screen_top = geometry.top()
        screen_height = geometry.height()

        # Y position at 100px from top, height so that there's 40px margin at bottom
        desired_y = screen_top + 10
        max_allowed_height = screen_height - 10 - 40  # 100px top margin, 40px bottom
        dialog_height = max(min_height, min(max_allowed_height, screen_height - 140))
        # Dialog width should match content width, but not exceed screen width
        dialog_width = min(screen_width - 80, dialog_content_width)

        # X: center window horizontally if fits, else clamp to left margin
        dialog_x = screen_left + max(40, (screen_width - dialog_width) // 2)

        # Apply geometry
        dialog.resize(dialog_width, dialog_height)
        dialog.move(dialog_x, desired_y)

        # Show dialog and ensure it gets focus
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.setFocus()  # Ensure dialog has focus for keyboard events
        
        return True

    def isVisible(self):
        """Check if the help dialog is currently visible"""
        return self.dialog.isVisible() if self.dialog else False


def main():
    """Test function to run the help dialog independently"""
    import sys
    from PySide6.QtWidgets import QApplication, QWidget
    
    # Create a mock window object for testing
    class MockWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.debug_mode = True
            # Create a minimal menu_manager mock
            class MockMenuManager:
                def query_menu_keys(self):
                    return [
                        {'key_name': 'Cmd+,', 'key_description': 'Preferences...', 'key_active': True},
                        {'key_name': 'Cmd+N', 'key_description': 'New Window', 'key_active': True},
                    ]
            self.menu_manager = MockMenuManager()
            self.is_fullscreen = False
            self.current_view_mode = 'thumbnail'
            self.view_mode = 'thumbnail'
            # Mock slideshow managers (required by KeyboardHandlerManager)
            class MockSlideshowManager:
                pass
            self.slideshow_manager = MockSlideshowManager()
            self.slideshow2_manager = MockSlideshowManager()
            # Mock thumbnail_canvas (optional but may be checked)
            self.thumbnail_canvas = None
    
    # Create QApplication instance
    app = QApplication(sys.argv)
    
    # Create mock window
    mock_window = MockWindow()
    
    # Create and show the help dialog
    help_dialog = HelpDialog(mock_window)
    help_dialog.show_help()
    
    # Run the application event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
