"""
Keyboard Handler Module

Centralized keyboard handling system for the Image Browser application.
Provides a clean, maintainable API for handling keyboard events across different view modes.

Architecture:
- BaseKeyboardHandler: Core functionality and common patterns
- View-specific handlers: ThumbnailHandler, FullscreenHandler, SlideshowHandler, etc.
- KeyBinding: Centralized key mapping configuration
- Event routing: Clean separation of concerns

Author: AI Assistant
"""

# Standard library imports
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

# Third-party imports
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication

# Local imports
from config import get_config

logger = logging.getLogger(__name__)


class KeyBinding:
    """Represents a key binding with modifiers and associated action."""

    def __init__(self, key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.NoModifier,
                 description: str = "", repeatable: bool = False):
        self.key = key
        self.modifiers = modifiers
        self.description = description
        self.repeatable = repeatable

    def matches(self, event: QKeyEvent) -> bool:
        """Check if this key binding matches the given event."""
        
        event_key = event.key()
        event_modifiers = event.modifiers()

        # Special handling for arrow keys: allow both NoModifier and KeypadModifier
        if event_key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            if self.modifiers == Qt.NoModifier:
                # Accept both NoModifier and KeypadModifier for arrow keys
                match = event_key == self.key and (event_modifiers == Qt.NoModifier or event_modifiers == Qt.KeypadModifier)
            elif self.modifiers == Qt.ShiftModifier:
                # For Shift+Arrow: Accept ShiftModifier with or without KeypadModifier
                event_mods_without_keypad = event_modifiers & ~Qt.KeypadModifier
                match = event_key == self.key and event_mods_without_keypad == Qt.ShiftModifier
            elif self.modifiers == Qt.ControlModifier:
                # For Cmd+Arrow: Accept either ControlModifier or MetaModifier (Command key on macOS)
                event_mods_without_keypad = event_modifiers & ~Qt.KeypadModifier
                cmd_pressed = bool(event_mods_without_keypad & (Qt.ControlModifier | Qt.MetaModifier))
                other_mods = event_mods_without_keypad & ~(Qt.ControlModifier | Qt.MetaModifier)
                # Check if other_mods is NoModifier (can be enum or 0)
                no_other_mods = (other_mods == Qt.NoModifier or other_mods == 0)
                match = event_key == self.key and cmd_pressed and no_other_mods
            elif self.modifiers == (Qt.ControlModifier | Qt.ShiftModifier):
                # For Cmd+Shift+Arrow: Accept either ControlModifier or MetaModifier with ShiftModifier
                event_mods_without_keypad = event_modifiers & ~Qt.KeypadModifier
                cmd_pressed = bool(event_mods_without_keypad & (Qt.ControlModifier | Qt.MetaModifier))
                shift_pressed = bool(event_mods_without_keypad & Qt.ShiftModifier)
                other_mods = event_mods_without_keypad & ~(Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier)
                # Check if other_mods is NoModifier (can be enum or 0)
                no_other_mods = (other_mods == Qt.NoModifier or other_mods == 0)
                match = event_key == self.key and cmd_pressed and shift_pressed and no_other_mods
            else:
                # For arrow keys with other modifiers, require exact match of modifiers (but allow KeypadModifier as additional)
                # This ensures shift-cmd-left doesn't match shift-left
                event_mods_without_keypad = event_modifiers & ~Qt.KeypadModifier
                required_mods_without_keypad = self.modifiers & ~Qt.KeypadModifier
                match = event_key == self.key and event_mods_without_keypad == required_mods_without_keypad
        # Special handling for Shift+number keys: Qt reports shifted character codes
        elif self.modifiers == Qt.ShiftModifier and event_modifiers == Qt.ShiftModifier:
            # Handle Shift+1 ('!') and Shift+2 ('@') on US keyboard
            if self.key == Qt.Key_1 and event_key == 33:  # '!' = 33
                match = True
            elif self.key == Qt.Key_2 and event_key == 64:  # '@' = 64
                match = True
            else:
                match = event_key == self.key and event_modifiers == self.modifiers
        # Special handling for Control+number keys (MetaModifier on macOS)
        # On macOS, Control key is MetaModifier, and we need to ensure exact match
        # Allow KeypadModifier as additional modifier (like arrow keys)
        elif self.modifiers == Qt.MetaModifier:
            # Check if modifiers match (MetaModifier, optionally with KeypadModifier)
            event_mods_without_keypad = event_modifiers & ~Qt.KeypadModifier
            required_mods_without_keypad = self.modifiers & ~Qt.KeypadModifier
            if event_mods_without_keypad == required_mods_without_keypad:
                match = event_key == self.key
            else:
                match = False
        # Special handling for ControlModifier (Command key on macOS)
        # On macOS, Command key is ControlModifier, but we should also accept MetaModifier
        # as some systems might report it differently
        elif self.modifiers == Qt.ControlModifier:
            # Accept either ControlModifier or MetaModifier (Command key on macOS)
            event_mods_without_keypad = event_modifiers & ~Qt.KeypadModifier
            cmd_pressed = bool(event_mods_without_keypad & (Qt.ControlModifier | Qt.MetaModifier))
            other_mods = event_mods_without_keypad & ~(Qt.ControlModifier | Qt.MetaModifier)
            required_other_mods = self.modifiers & ~Qt.ControlModifier
            match = event_key == self.key and cmd_pressed and other_mods == required_other_mods
        elif self.modifiers == (Qt.ControlModifier | Qt.ShiftModifier):
            # Handle Control+Shift (Cmd+Shift on macOS)
            event_mods_without_keypad = event_modifiers & ~Qt.KeypadModifier
            # Check for Command+Shift: either ControlModifier or MetaModifier with ShiftModifier
            cmd_pressed = bool(event_mods_without_keypad & (Qt.ControlModifier | Qt.MetaModifier))
            shift_pressed = bool(event_mods_without_keypad & Qt.ShiftModifier)
            other_mods = event_mods_without_keypad & ~(Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier)
            match = event_key == self.key and cmd_pressed and shift_pressed and other_mods == 0
        # For NoModifier bindings: accept KeypadModifier as additional (e.g. keypad 0 sends KeypadModifier)
        elif self.modifiers == Qt.NoModifier:
            event_mods_without_keypad = event_modifiers & ~Qt.KeypadModifier
            match = event_key == self.key and (event_mods_without_keypad == Qt.NoModifier or event_mods_without_keypad == 0)
        else:
            # For other keys, check if the modifiers match exactly
            match = event_key == self.key and event_modifiers == self.modifiers

        return match

    def __str__(self) -> str:
        """String representation of the key binding."""
        mod_str = ""
        if self.modifiers & Qt.ShiftModifier:
            mod_str += "Shift+"
        if self.modifiers & Qt.ControlModifier:
            mod_str += "Cmd+"
        if self.modifiers & Qt.AltModifier:
            mod_str += "Alt+"
        if self.modifiers & Qt.MetaModifier:
            mod_str += "Ctrl+"

        key_sequence = QKeySequence(self.key)
        return f"{mod_str}{key_sequence.toString()}"


class BaseKeyboardHandler(QObject):
    """Base class for keyboard handlers with common functionality."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._key_bindings: Dict[str, Tuple[KeyBinding, Callable]] = {}
        self._context_handlers: Dict[str, Callable] = {}
        self._active_contexts: List[str] = []
        self.config = get_config()

    def add_key_binding(self, name: str, key_binding: KeyBinding, handler: Callable):
        """Add a key binding with its associated handler."""
        self._key_bindings[name] = (key_binding, handler)

    def add_context_handler(self, context: str, handler: Callable):
        """Add a context-specific handler."""
        self._context_handlers[context] = handler

    def handle_key_event(self, event: QKeyEvent, context_data: Dict[str, Any] = None) -> bool:
        """
        Handle a key event.

        Args:
            event: The key event to handle
            context_data: Additional context data for the handler

        Returns:
            bool: True if the event was handled, False otherwise
        """
        
        if context_data is None:
            context_data = {}

        # Check for context-specific handlers first
        for context in self._active_contexts:
            if context in self._context_handlers:
                handler = self._context_handlers[context]
                if handler(event, context_data):
                    return True

        # Check key bindings
        for name, (key_binding, handler) in self._key_bindings.items():
            if key_binding.matches(event):
                try:
                    # Visible logging for E and H keys
                    if event.key() in (Qt.Key_E, Qt.Key_H):
                        key_name = "E" if event.key() == Qt.Key_E else "H"
                        logger.info(f"Keyboard handler '{name}' matched for key {key_name}")
                    result = handler(event, context_data)
                    if result is not False:  # Allow handlers to return False to continue processing
                        if event.key() in (Qt.Key_E, Qt.Key_H):
                            key_name = "E" if event.key() == Qt.Key_E else "H"
                            logger.info(f"Keyboard handler '{name}' returned True for key {key_name}")
                        return True
                except Exception as e:
                    logger.error(f"Error in key handler '{name}': {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    return False
        return False

    def get_key_bindings_help(self) -> Dict[str, str]:
        """Get help text for all key bindings."""
        help_dict = {}
        for name, (key_binding, _) in self._key_bindings.items():
            if key_binding.description:
                help_dict[str(key_binding)] = key_binding.description
        return help_dict
    
    def refresh_favorite_bindings(self):
        """Refresh favorite key binding descriptions from current config."""
        try:
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            favorites = settings.get('favorite_directories', [None] * 9)
            favorites = (favorites + [None] * 9)[:9]
            
            # Update descriptions for favorite bindings (ctrl_1 through ctrl_9)
            for i in range(1, 10):
                binding_name = f"ctrl_{i}"
                if binding_name in self._key_bindings:
                    key_binding, handler = self._key_bindings[binding_name]
                    favorite_path = favorites[i-1] if i-1 < len(favorites) else None
                    
                    # Update description based on current favorite
                    if favorite_path and favorite_path.strip():
                        favorite_path = favorite_path.strip()
                        if os.path.exists(favorite_path):
                            if os.path.isdir(favorite_path):
                                display_name = os.path.basename(favorite_path.rstrip('/'))
                            else:
                                display_name = os.path.basename(favorite_path)
                            key_binding.description = f"Open {display_name}"
                        else:
                            key_binding.description = f"Open favorite directory {i}"
                    else:
                        key_binding.description = f"Open favorite directory {i}"
        except Exception as e:
            logger.error(f"Error refreshing favorite bindings: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _handle_j_imagegen_activity_menu(
        self, event: QKeyEvent, context_data: Dict[str, Any]
    ) -> bool:
        """J — imagegen status-bar dot menu while a model background task is active."""
        mgr = getattr(self.main_window, "status_bar_manager", None)
        if mgr is None:
            return False
        if mgr.show_imagegen_task_menu_from_keyboard():
            event.accept()
            return True
        return False

    def _handle_j_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """J in thumbnail/list: imagegen task menu when active, else View menu toggle."""
        if event.isAutoRepeat():
            return True
        if self._handle_j_imagegen_activity_menu(event, context_data):
            return True
        return False


class ThumbnailKeyboardHandler(BaseKeyboardHandler):
    """Keyboard handler for thumbnail view mode."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._setup_key_bindings()
        self._setup_context_handlers()

    def _setup_key_bindings(self):
        """Set up key bindings for thumbnail view."""
        CMD = Qt.ControlModifier
        SHIFT = Qt.ShiftModifier
        CTRL = Qt.MetaModifier
        # Navigation keys
        self.add_key_binding("left_arrow", KeyBinding(Qt.Key_Left, description="Move highlight to left"), self._handle_left_arrow)
        self.add_key_binding("right_arrow", KeyBinding(Qt.Key_Right, description="Move highlight to right"), self._handle_right_arrow)
        self.add_key_binding("up_arrow", KeyBinding(Qt.Key_Up, description="Move highlight to up"), self._handle_up_arrow)
        self.add_key_binding("down_arrow", KeyBinding(Qt.Key_Down, description="Move highlight to down"), self._handle_down_arrow)

        # Shift+Arrow for range selection
        self.add_key_binding("shift_left", KeyBinding(Qt.Key_Left, Qt.ShiftModifier, description="Select range left"), self._handle_shift_left)
        self.add_key_binding("shift_right", KeyBinding(Qt.Key_Right, Qt.ShiftModifier, description="Select range right"), self._handle_shift_right)
        self.add_key_binding("shift_up", KeyBinding(Qt.Key_Up, Qt.ShiftModifier, description="Select range up"), self._handle_shift_up)
        self.add_key_binding("shift_down", KeyBinding(Qt.Key_Down, Qt.ShiftModifier, description="Select range down"), self._handle_shift_down)

        # Shift+Cmd+Arrow for window shifting (when limit is set)
        self.add_key_binding("shift_cmd_left", KeyBinding(Qt.Key_Left, SHIFT | CMD, description="Shift window left (used with limit)"), self._handle_shift_cmd_left)
        self.add_key_binding("shift_cmd_right", KeyBinding(Qt.Key_Right, SHIFT | CMD, description="Shift window right (used with limit)"), self._handle_shift_cmd_right)

        # Cmd+Arrow for multi-select - handle both Meta (Cmd) and Control modifiers

        self.add_key_binding("cmd_left_ctrl", KeyBinding(Qt.Key_Left, Qt.ControlModifier, description="Multi-select left"), self._handle_cmd_left)
        self.add_key_binding("cmd_right_ctrl", KeyBinding(Qt.Key_Right, Qt.ControlModifier, description="Multi-select right"), self._handle_cmd_right)
        self.add_key_binding("cmd_up_ctrl", KeyBinding(Qt.Key_Up, Qt.ControlModifier, description="Multi-select up"), self._handle_cmd_up)
        self.add_key_binding("cmd_down_ctrl", KeyBinding(Qt.Key_Down, Qt.ControlModifier, description="Multi-select down"), self._handle_cmd_down)

        # Other navigation
        # self.add_key_binding("home", KeyBinding(Qt.Key_Home, description="Go to first image"), self._handle_home)
        # self.add_key_binding("end", KeyBinding(Qt.Key_End, description="Go to last image"), self._handle_end)
        self.add_key_binding("h_key", KeyBinding(Qt.Key_H, description="Home - Jump to first image"), self._handle_h_key)
        self.add_key_binding("shift_h", KeyBinding(Qt.Key_H, Qt.ShiftModifier, description="Select range to first image"), self._handle_shift_h_select_to_first)
        self.add_key_binding("e_key", KeyBinding(Qt.Key_E, description="End - Jump to last image"), self._handle_e_key)
        self.add_key_binding("page_up", KeyBinding(Qt.Key_PageUp, description="Page up"), self._handle_page_up)
        self.add_key_binding("page_down", KeyBinding(Qt.Key_PageDown, description="Page down"), self._handle_page_down)

        # Shift+Home for range selection (Shift+H is the same action; see shift_h binding above)
        self.add_key_binding("shift_home_key", KeyBinding(Qt.Key_Home, Qt.ShiftModifier, description="Home - Select to first image"), self._handle_shift_home)
        self.add_key_binding("shift_E", KeyBinding(Qt.Key_E, Qt.ShiftModifier, description="End - Select to last image"), self._handle_shift_end)

        # Actions
        self.add_key_binding("return", KeyBinding(Qt.Key_Return, description="View image"), self._handle_return)
        self.add_key_binding("space", KeyBinding(Qt.Key_Space, description="View image"), self._handle_space)
        # F key is handled by menu system (Enter Image Viewer)

        # Escape
        self.add_key_binding("escape", KeyBinding(Qt.Key_Escape, description="Clear Selections or Navigate Back"), self._handle_escape)
        # Q key - close list view when in list mode
        self.add_key_binding("q_key", KeyBinding(Qt.Key_Q, description="Close list view"), self._handle_q_key_close_list)
        # Shift+Escape for forward navigation
        self.add_key_binding("shift_escape", KeyBinding(Qt.Key_Escape, Qt.ShiftModifier, description="Navigate forward in directory history"), self._handle_shift_escape)
        # F10 to clear history stacks
        self.add_key_binding("f10", KeyBinding(Qt.Key_F10, description="Clear forward and backward history stacks"), self._handle_f10)

        # List view row height adjustment (+/- keys)
        self.add_key_binding("list_plus", KeyBinding(Qt.Key_Plus, description="Increase list view row height"), self._handle_list_plus)
        self.add_key_binding("list_equal", KeyBinding(Qt.Key_Equal, description="Increase list view row height"), self._handle_list_plus)
        self.add_key_binding("list_minus", KeyBinding(Qt.Key_Minus, description="Decrease list view row height"), self._handle_list_minus)
        self.add_key_binding("list_zero", KeyBinding(Qt.Key_0, description="Reset list view row height to default"), self._handle_list_zero)
        
        # Thumbnail size (debug mode only)
        self.add_key_binding("minus_key", KeyBinding(Qt.Key_Minus, description="Decrease minimum thumbnail size"), self._handle_minus_key)
        self.add_key_binding("equals_key", KeyBinding(Qt.Key_Equal, description="Increase minimum thumbnail size"), self._handle_equals_key)
        self.add_key_binding("zero_key", KeyBinding(Qt.Key_0, description="Reset thumbnail size"), self.handle_zero_key)

        # Help and settings
        self.add_key_binding("question", KeyBinding(Qt.Key_Question, description="Show help"), self._handle_question)
        # F1 is handled by menu system
        self.add_key_binding("slash", KeyBinding(Qt.Key_Slash, description="Show help"), self._handle_question)

        # Debug and maintenance
        self.add_key_binding("ctrl_shift_d", KeyBinding(Qt.Key_D, Qt.ControlModifier | Qt.ShiftModifier, description="Debug mode Toggle"), self._handle_ctrl_shift_d)
        self.add_key_binding("ctrl_d", KeyBinding(Qt.Key_D, Qt.ControlModifier, description="Debug cache status"), self._handle_ctrl_d)
        
        # self.add_key_binding("ctrl_shift_c", KeyBinding(Qt.Key_C, Qt.ControlModifier | Qt.ShiftModifier, description="Clear all caches"), self._handle_ctrl_shift_c)
        # Ctrl+C is handled by menu system (Copy File Path)

        # File operations
        # Ctrl+Backspace is handled by menu system (Delete File)
        self.add_key_binding("ctrl_delete", KeyBinding(Qt.Key_Delete, Qt.ControlModifier, description="Delete selected files"), self._handle_ctrl_delete)
        
        # Lock/Unlock operations
        # cmd-L (lock) - only works when allow_thumbnail_locking is enabled
        self.add_key_binding("ctrl_l", KeyBinding(Qt.Key_L, CMD, description="Lock selected files"), self._handle_ctrl_l_lock)
        # shift-cmd-L (unlock) - always works, even when setting is off
        self.add_key_binding("ctrl_shift_l", KeyBinding(Qt.Key_L, CMD | SHIFT, description="Unlock selected files"), self._handle_ctrl_shift_l_unlock)

        # Other operations
        self.add_key_binding("ctrl_shift_return", KeyBinding(Qt.Key_Return, Qt.ControlModifier | Qt.ShiftModifier, description="Expand file tree"), self._handle_ctrl_shift_return)
        self.add_key_binding("ctrl_return", KeyBinding(Qt.Key_Return, Qt.ControlModifier, description="Collapse file tree"), self._handle_ctrl_return)
        # Ctrl+E is handled by menu system (Edit with external editor)
        # I key toggles Information sidebar (right sidebar with EXIF info)
        # Ctrl+I (Cmd+I) toggles filename overlay on thumbnails
        self.add_key_binding("i_key", KeyBinding(Qt.Key_I, description="Information sidebar toggle"), self._handle_i_key_metadata)
        self.add_key_binding("o_key", KeyBinding(Qt.Key_O, description="Organize sidebar toggle"), self._handle_o_key_sidebar)
        self.add_key_binding(
            "j_key",
            KeyBinding(Qt.Key_J, description="Jobs pane toggle / imagegen task menu"),
            self._handle_j_key,
        )
        self.add_key_binding("ctrl_i", KeyBinding(Qt.Key_I, CMD, description="Cycle filename display"), self._handle_ctrl_i_filename)
        self.add_key_binding("ctrl_shift_i", KeyBinding(Qt.Key_I, Qt.ControlModifier | Qt.ShiftModifier, description="Information overlay toggle"), self._handle_ctrl_shift_i)
        # F11 is handled by menu system (MacOS Fullscreen)
        # Ctrl+F is handled by menu system (Search by Description)

        # Preview widget controls
        # A key is handled by menu system in browse view (Actual Size), keep for thumbnail view
        self.add_key_binding("a_key", KeyBinding(Qt.Key_A, description="Actual Size Toggle"), self._handle_a_key)
        
        # Sort controls
        self.add_key_binding("n_key", KeyBinding(Qt.Key_N, description="Sort by name (A-Z)"), self._handle_n_key)
        self.add_key_binding("shift_n", KeyBinding(Qt.Key_N, SHIFT, description="Sort by name (Z-A)"), self._handle_shift_n_key)
        self.add_key_binding("r_key", KeyBinding(Qt.Key_R, description="Random sort"), self._handle_r_key)
        self.add_key_binding("d_key", KeyBinding(Qt.Key_D, description="Sort by date (Oldest first)"), self._handle_d_key)
        self.add_key_binding("shift_d", KeyBinding(Qt.Key_D, SHIFT, description="Sort by date (Newest first)"), self._handle_shift_d_key)
        self.add_key_binding("z_key", KeyBinding(Qt.Key_Z, description="Sort by size/area (Largest first)"), self._handle_z_key)
        self.add_key_binding("shift_z", KeyBinding(Qt.Key_Z, SHIFT, description="Sort by size/area (Smallest first)"), self._handle_shift_z_key)
        self.add_key_binding("c_key", KeyBinding(Qt.Key_C, description="Custom sort"), self._handle_c_key)
        self.add_key_binding("cmd_k", KeyBinding(Qt.Key_K, CMD, description="Find similar images"), self._handle_cmd_k)
        
        # Favorite directories shortcuts (Ctrl+1 through Ctrl+9)
        # On macOS, we need to check both ControlModifier and MetaModifier
        # because Qt's mapping can vary. We'll check for MetaModifier first (actual Control key)
        # but also handle ControlModifier if needed for compatibility
        CTRL = Qt.MetaModifier
        for i in range(1, 10):
            key = getattr(Qt, f'Key_{i}')
            # Create handler with index captured in closure
            def make_handler(idx):
                def handler(event, context_data):
                    return self._handle_favorite_directory(event, context_data, idx)
                return handler
            self.add_key_binding(f"ctrl_{i}", KeyBinding(key, CTRL, description=f"Open favorite directory {i}"), 
                                make_handler(i-1))

    def _setup_context_handlers(self):
        """Set up context-specific handlers."""
        self.add_context_handler("multi_select", self._handle_multi_select_context)

    def _handle_multi_select_context(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Reset multi-select state when command is not held
        key = event.key()
        modifiers = event.modifiers()
        kb_mods = QApplication.keyboardModifiers()
        cmd_held = bool(kb_mods & (Qt.MetaModifier | Qt.ControlModifier))

        if not cmd_held and key not in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self.main_window.cmd_multi_origin_index = None
            self.main_window.cmd_multi_axis = None
            self.main_window.cmd_multi_sign = 0
            return True

        return False

    # Navigation handlers
    def _handle_left_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle left arrow - navigate to previous image by file path (source of truth)"""
        if self.main_window.selected_files:
            self.main_window.clear_selection()
        self.main_window.range_anchor_index = None
        
        # Get current image path (source of truth)
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return False
        
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            # No current image or not in displayed - use first
            if displayed:
                self.main_window.set_current_image_by_path(displayed[0])
                self.main_window.highlight_image()
            return True
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            current_idx = 0
        
        # Compute next index
        if not self.main_window.wrap_around:
            if current_idx > 0:
                next_idx = current_idx - 1
            else:
                next_idx = current_idx  # Can't go before first
        else:
            next_idx = (current_idx - 1) % len(displayed)
        
        # Set current image by path (source of truth)
        next_path = displayed[next_idx]
        self.main_window.set_current_image_by_path(next_path)
        self.main_window.highlight_image()
        
        # Scroll to highlighted item in list view
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'list' and
            hasattr(self.main_window, 'list_view_container') and 
            self.main_window.list_view_container):
            QTimer.singleShot(10, lambda: self.main_window.list_view_container.scroll_to_highlighted(
                next_idx, force=False))
        
        event.accept()
        return True

    def _handle_right_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle right arrow - navigate to next image by file path (source of truth)"""
        if self.main_window.selected_files:
            self.main_window.clear_selection()
        self.main_window.range_anchor_index = None
        
        # Get current image path (source of truth)
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return False
        
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            # No current image or not in displayed - use first
            if displayed:
                self.main_window.set_current_image_by_path(displayed[0])
                self.main_window.highlight_image()
            return True
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            current_idx = 0
        
        # Compute next index
        if not self.main_window.wrap_around:
            if current_idx < len(displayed) - 1:
                next_idx = current_idx + 1
            else:
                next_idx = current_idx  # Can't go after last
        else:
            next_idx = (current_idx + 1) % len(displayed)
        
        # Set current image by path (source of truth)
        next_path = displayed[next_idx]
        self.main_window.set_current_image_by_path(next_path)
        self.main_window.highlight_image()
        
        # Scroll to highlighted item in list view
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'list' and
            hasattr(self.main_window, 'list_view_container') and 
            self.main_window.list_view_container):
            QTimer.singleShot(10, lambda: self.main_window.list_view_container.scroll_to_highlighted(
                next_idx, force=False))
        
        event.accept()
        return True

    def _handle_up_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle up arrow - navigate up in grid by file path (source of truth)"""
        if self.main_window.selected_files:
            self.main_window.clear_selection()
        self.main_window.range_anchor_index = None

        # Get current image path (source of truth)
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return False
        
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            # No current image or not in displayed - use first
            if displayed:
                self.main_window.set_current_image_by_path(displayed[0])
                self.main_window.highlight_image()
            return True
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            current_idx = 0

        # For list view, use simple +/-1 navigation (one row at a time)
        # For thumbnail view, use grid-based navigation
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            # Simple navigation: move up by 1
            if not self.main_window.wrap_around:
                target_index = max(0, current_idx - 1)
            else:
                target_index = (current_idx - 1) % len(displayed)
        else:
            # Use navigation_manager to compute next index (handles segmented layouts)
            target_index = self._compute_next_index(current_idx, 'v', -1)

        if target_index < 0:
            target_index = 0
        
        # Set current image by path (source of truth)
        target_path = displayed[target_index]
        self.main_window.set_current_image_by_path(target_path)
        self.main_window.highlight_image()
        
        # Scroll to highlighted item in list view
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'list' and
            hasattr(self.main_window, 'list_view_container') and 
            self.main_window.list_view_container):
            QTimer.singleShot(10, lambda: self.main_window.list_view_container.scroll_to_highlighted(
                target_index, force=False))
        
        event.accept()
        return True

    def _handle_down_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle down arrow - navigate down in grid by file path (source of truth)"""
        if self.main_window.selected_files:
            self.main_window.clear_selection()
        self.main_window.range_anchor_index = None

        # Get current image path (source of truth)
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return False
        
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            # No current image or not in displayed - use first
            if displayed:
                self.main_window.set_current_image_by_path(displayed[0])
                self.main_window.highlight_image()
            return True
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            current_idx = 0

        # For list view, use simple +/-1 navigation (one row at a time)
        # For thumbnail view, use grid-based navigation
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            # Simple navigation: move down by 1
            last_index = len(displayed) - 1
            if not self.main_window.wrap_around:
                target_index = min(last_index, current_idx + 1)
            else:
                target_index = (current_idx + 1) % len(displayed)
        else:
            # Use navigation_manager to compute next index (handles segmented layouts)
            target_index = self._compute_next_index(current_idx, 'v', +1)
            last_row_end = len(displayed) - 1
            if target_index > last_row_end:
                target_index = last_row_end
        
        # Set current image by path (source of truth)
        target_path = displayed[target_index]
        self.main_window.set_current_image_by_path(target_path)
        self.main_window.highlight_image()
        
        # Scroll to highlighted item in list view
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'list' and
            hasattr(self.main_window, 'list_view_container') and 
            self.main_window.list_view_container):
            QTimer.singleShot(10, lambda: self.main_window.list_view_container.scroll_to_highlighted(
                target_index, force=False))
        
        event.accept()
        return True

    # Shift+Arrow handlers (range selection)
    def _handle_shift_left(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Left for range selection - uses file paths (source of truth)"""
        # Only available in thumbnail view
        if self.main_window.current_view_mode != 'thumbnail':
            return False
        
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return False
        
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            return False
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            return False
        
        # Set anchor if needed
        if self.main_window.range_anchor_index is None:
            self.main_window.range_anchor_index = current_idx
        
        # Compute next index
        if not self.main_window.wrap_around:
            if current_idx > 0:
                next_idx = current_idx - 1
            else:
                next_idx = current_idx
        else:
            next_idx = (current_idx - 1) % len(displayed)
        
        # Set current image by path, then handle range selection
        next_path = displayed[next_idx]
        self.main_window.set_current_image_by_path(next_path)
        # Use selection_manager for range selection
        if hasattr(self.main_window, 'selection_manager') and self.main_window.selection_manager:
            self.main_window.selection_manager.handle_range_selection(self.main_window.highlight_index, anchor=self.main_window.range_anchor_index)
        event.accept()
        return True

    def _handle_shift_right(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Right for range selection - uses file paths (source of truth)"""
        # Only available in thumbnail view
        if self.main_window.current_view_mode != 'thumbnail':
            return False
        
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return False
        
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            return False
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            return False
        
        # Set anchor if needed
        if self.main_window.range_anchor_index is None:
            self.main_window.range_anchor_index = current_idx
        
        # Compute next index
        if not self.main_window.wrap_around:
            if current_idx < len(displayed) - 1:
                next_idx = current_idx + 1
            else:
                next_idx = current_idx
        else:
            next_idx = (current_idx + 1) % len(displayed)
        
        # Set current image by path, then handle range selection
        next_path = displayed[next_idx]
        self.main_window.set_current_image_by_path(next_path)
        # Use selection_manager for range selection
        if hasattr(self.main_window, 'selection_manager') and self.main_window.selection_manager:
            self.main_window.selection_manager.handle_range_selection(self.main_window.highlight_index, anchor=self.main_window.range_anchor_index)
        event.accept()
        return True

    def _handle_shift_up(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Up for range selection - uses file paths (source of truth)"""
        # Only available in thumbnail view
        if self.main_window.current_view_mode != 'thumbnail':
            return False
        
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return False
        
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            return False
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            return False
        
        # Set anchor if needed
        if self.main_window.range_anchor_index is None:
            self.main_window.range_anchor_index = current_idx
        
        # Compute target index using grid
        # Use navigation_manager to compute next index (handles segmented layouts)
        target_index = self._compute_next_index(current_idx, 'v', -1)
        
        if target_index < 0:
            target_index = 0
        
        # Set current image by path, then handle range selection
        target_path = displayed[target_index]
        self.main_window.set_current_image_by_path(target_path)
        # Use selection_manager for range selection
        if hasattr(self.main_window, 'selection_manager') and self.main_window.selection_manager:
            self.main_window.selection_manager.handle_range_selection(self.main_window.highlight_index, anchor=self.main_window.range_anchor_index)
        event.accept()
        return True

    def _handle_shift_down(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Down for range selection - uses file paths (source of truth)"""
        # Only available in thumbnail view
        if self.main_window.current_view_mode != 'thumbnail':
            return False
        
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return False
        
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            return False
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            return False
        
        # Set anchor if needed
        if self.main_window.range_anchor_index is None:
            self.main_window.range_anchor_index = current_idx
        
        # Compute target index using grid
        # Use navigation_manager to compute next index (handles segmented layouts)
        target_index = self._compute_next_index(current_idx, 'v', +1)
        last_row_end = len(displayed) - 1
        
        if target_index > last_row_end:
            target_index = last_row_end
        
        # Set current image by path, then handle range selection
        target_path = displayed[target_index]
        self.main_window.set_current_image_by_path(target_path)
        # Use selection_manager for range selection
        if hasattr(self.main_window, 'selection_manager') and self.main_window.selection_manager:
            self.main_window.selection_manager.handle_range_selection(self.main_window.highlight_index, anchor=self.main_window.range_anchor_index)
        event.accept()
        return True

    # Shift+Cmd+Arrow handlers (window shifting)
    def _handle_shift_cmd_left(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Cmd+Left for window shifting."""
        # Shift the thumbnail window left by one limit amount
        # Only works when we're in thumbnail view with a limit set and more files than the limit
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'thumbnail' and
            hasattr(self.main_window, 'limit') and 
            self.main_window.limit < 99999):
            # Get full list to check if windowing is active
            all_images = self.main_window.get_full_sorted_filtered_list()
            if len(all_images) > self.main_window.limit:
                # Window shifting mode: shift window left by one limit
                if self.main_window.shift_thumbnail_window(-1):
                    event.accept()
                    return True
        return False

    def _handle_shift_cmd_right(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Cmd+Right for window shifting."""
        # Shift the thumbnail window right by one limit amount
        # Only works when we're in thumbnail view with a limit set and more files than the limit
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'thumbnail' and
            hasattr(self.main_window, 'limit') and 
            self.main_window.limit < 99999):
            # Get full list to check if windowing is active
            all_images = self.main_window.get_full_sorted_filtered_list()
            if len(all_images) > self.main_window.limit:
                # Window shifting mode: shift window right by one limit
                if self.main_window.shift_thumbnail_window(1):
                    event.accept()
                    return True
        return False


    # Cmd+Arrow handlers (multi-select)
    def _handle_cmd_left(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self._handle_cmd_arrow('h', -1)
        return True

    def _handle_cmd_right(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self._handle_cmd_arrow('h', +1)
        return True

    def _handle_cmd_up(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self._handle_cmd_arrow('v', -1)
        return True

    def _handle_cmd_down(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self._handle_cmd_arrow('v', +1)
        return True

    def _handle_cmd_arrow(self, axis: str, step_sign: int):
        """Handle cmd-arrow for multiselection - uses file paths (source of truth)"""
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        total_count = len(displayed)
        if total_count <= 0:
            return

        self.main_window.ensure_multi_mode()

        # Get current image path (source of truth)
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            return
        
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            return

        # Initialize origin on first cmd-arrow in a sequence
        # CRITICAL: Store origin by file path (source of truth), not index
        if self.main_window.cmd_multi_origin_index is None:
            # Store origin index (will be converted to path-based tracking)
            self.main_window.cmd_multi_origin_index = current_idx
            self.main_window.cmd_multi_axis = axis
            self.main_window.cmd_multi_sign = step_sign
            # Do not toggle origin; move to next and toggle
            next_index = self._compute_next_index(current_idx, axis, step_sign)
            # If next is the origin (e.g., at boundary), do not toggle origin
            if next_index == self.main_window.cmd_multi_origin_index:
                next_path = displayed[next_index]
                self.main_window.set_current_image_by_path(next_path)
                self.main_window.highlight_image()
                return
            next_path = displayed[next_index]
            self.main_window.set_current_image_by_path(next_path)
            self._toggle_index(next_index)
            self.main_window.highlight_image()
            return

        # Subsequent cmd-arrows in a sequence
        # CRITICAL: Compare origin using file paths (source of truth)
        # Get origin file path to compare
        origin_index = self.main_window.cmd_multi_origin_index
        if origin_index is None or not (0 <= origin_index < len(displayed)):
            # Origin invalid - reset
            self.main_window.cmd_multi_origin_index = current_idx
            origin_index = current_idx
        
        origin_path = displayed[origin_index]
        current_is_origin = (current_path == origin_path)
        
        # Determine whether this movement is towards or away from origin along the active axis
        if axis == 'h':
            def _dist(i):
                return abs(i - origin_index)
        else:
            grid_info = self.main_window.get_actual_grid_info()
            columns = grid_info["columns"] or 1
            origin_row = origin_index // columns
            def _dist(i):
                return abs((i // columns) - origin_row)

        next_index_peek = self._compute_next_index(current_idx, axis, step_sign)
        moving_towards_origin = _dist(next_index_peek) < _dist(current_idx)

        if current_is_origin:
            # Do not change origin selection; move to next and toggle
            next_index = self._compute_next_index(current_idx, axis, step_sign)
            next_path = displayed[next_index]
            if next_index == origin_index:
                self.main_window.set_current_image_by_path(next_path)
                # If vertical movement to a new row becomes the model, keep origin stable here
                if axis == 'v':
                    # Update origin to the new position (by file path)
                    # Get the current image path and find its index to update origin
                    current_path_after_move = self.main_window.get_current_image_path()
                    if current_path_after_move and current_path_after_move in displayed:
                        try:
                            new_origin_idx = displayed.index(current_path_after_move)
                            self.main_window.cmd_multi_origin_index = new_origin_idx
                        except ValueError:
                            pass
                self.main_window.highlight_image()
                return
            self.main_window.set_current_image_by_path(next_path)
            self._toggle_index(next_index)
            if axis == 'v':
                # Update origin to the new position (by file path)
                # Get the current image path and find its index to update origin
                current_path_after_move = self.main_window.get_current_image_path()
                if current_path_after_move and current_path_after_move in displayed:
                    try:
                        new_origin_idx = displayed.index(current_path_after_move)
                        self.main_window.cmd_multi_origin_index = new_origin_idx
                    except ValueError:
                        pass
            self.main_window.highlight_image()
            return

        # Not on origin
        if moving_towards_origin:
            # Shrinking selection: deselect current (if not origin), move towards origin
            # CRITICAL: Compare using file paths (source of truth)
            if current_path in self.main_window.selected_files and current_path != origin_path:
                self.main_window.selected_files.remove(current_path)
            next_index = self._compute_next_index(current_idx, axis, step_sign)
            # If we have shrunk back to only the origin, begin extending on this side
            # CRITICAL: Check origin selection using file path
            if (len(self.main_window.selected_files) == 1 and
                origin_path in self.main_window.selected_files):
                if next_index == origin_index:
                    # Step one more away from origin and toggle
                    away_index = self._compute_next_index(next_index, axis, step_sign)
                    away_path = displayed[away_index]
                    self.main_window.set_current_image_by_path(away_path)
                    if away_index != next_index:
                        self._toggle_index(away_index)
                else:
                    next_path = displayed[next_index]
                    self.main_window.set_current_image_by_path(next_path)
            else:
                # Normal shrink: move highlight only, do not toggle
                next_path = displayed[next_index]
                self.main_window.set_current_image_by_path(next_path)
        else:
            # Extending selection: keep current, move away and toggle that next
            next_index = self._compute_next_index(current_idx, axis, step_sign)
            next_path = displayed[next_index]
            # CRITICAL: Compare using file paths (source of truth)
            if next_index == origin_index:
                self.main_window.set_current_image_by_path(next_path)
                self.main_window.highlight_image()
                return
            self.main_window.set_current_image_by_path(next_path)
            self._toggle_index(next_index)

        # If we moved vertically to a new row, treat the new row item as the new origin
        # CRITICAL: Update origin based on current image path (source of truth)
        if axis == 'v':
            # Get the current image path and find its index to update origin
            current_path_after_move = self.main_window.get_current_image_path()
            if current_path_after_move and current_path_after_move in displayed:
                try:
                    new_origin_idx = displayed.index(current_path_after_move)
                    self.main_window.cmd_multi_origin_index = new_origin_idx
                except ValueError:
                    pass
        self.main_window.highlight_image()

    def _compute_next_index(self, current_index: int, axis: str, step_sign: int) -> int:
        """Compute the next index for navigation."""
        # Use navigation_manager which handles segmented layouts (EXIF date, duplicates)
        return self.main_window.navigation_manager.compute_next_index(current_index, axis, step_sign)

    def _toggle_index(self, idx: int):
        """Toggle selection state of an index.
        
        CRITICAL: Sets current_image_path (source of truth) and derives highlight_index from it.
        """
        if not (0 <= idx < len(self.main_window.displayed_images)):
            return
        file_path = self.main_window.displayed_images[idx]
        if file_path in self.main_window.selected_files:
            self.main_window.selected_files.remove(file_path)
        else:
            self.main_window.selected_files.add(file_path)
        
        # Update multi_select_mode based on selection count
        # multi_select_mode is now automatically derived from selected_files count
        
        # CRITICAL: Set current image by path (source of truth) - this derives highlight_index
        self.main_window.set_current_image_by_path(file_path)
        
        # Update canvas selection
        self.main_window._emit_selection_changed()

    # Other navigation handlers
    def _handle_home(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if event.modifiers() & Qt.ShiftModifier:
            if self.main_window.range_anchor_index is None:
                self.main_window.range_anchor_index = self.main_window.highlight_index
            old_index = self.main_window.highlight_index
            self.main_window.highlight_index = 0
            self.main_window.selection_manager.handle_range_selection(self.main_window.highlight_index, anchor=self.main_window.range_anchor_index)
        else:
            if self.main_window.selected_files:
                self.main_window.clear_selection()
            self.main_window.range_anchor_index = None
            old_index = self.main_window.highlight_index
            self.main_window.highlight_index = 0
            self.main_window.highlight_image()
        return True

    def _handle_end(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        total_count = self.main_window.get_widget_count()
        if event.modifiers() & Qt.ShiftModifier:
            if self.main_window.range_anchor_index is None:
                self.main_window.range_anchor_index = self.main_window.highlight_index
            old_index = self.main_window.highlight_index
            self.main_window.highlight_index = total_count - 1
            self.main_window.selection_manager.handle_range_selection(self.main_window.highlight_index, anchor=self.main_window.range_anchor_index)
        else:
            if self.main_window.selected_files:
                self.main_window.clear_selection()
            self.main_window.range_anchor_index = None
            old_index = self.main_window.highlight_index
            self.main_window.highlight_index = total_count - 1
            self.main_window.highlight_image()
        return True

    def _handle_page_up(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Page Up - navigate up by one page of images, highlight it, and scroll to it"""
        event.accept()
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return True
        
        if self.main_window.selected_files:
            self.main_window.clear_selection()
        self.main_window.range_anchor_index = None
        
        # Get current image path (source of truth)
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            # No current image - use first
            if displayed:
                self.main_window.set_current_image_by_path(displayed[0])
                self.main_window.highlight_image()
            return True
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            current_idx = 0
        
        # Calculate page size (rows per page * columns)
        rows_per_page, _ = self.main_window.calculate_page_scroll_info()
        grid_info = self.main_window.get_actual_grid_info()
        columns = grid_info.get("columns", 1)
        if columns < 1:
            columns = 1
        page_size = rows_per_page * columns
        
        # Move up by one page
        target_idx = max(0, current_idx - page_size)
        
        # Set current image by path (source of truth) - this updates highlight_index
        target_path = displayed[target_idx]
        self.main_window.set_current_image_by_path(target_path)
        
        # highlight_image() will scroll to the highlighted image automatically
        self.main_window.highlight_image()
        return True

    def _handle_page_down(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Page Down - navigate down by one page of images, highlight it, and scroll to it"""
        event.accept()
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return True
        
        if self.main_window.selected_files:
            self.main_window.clear_selection()
        self.main_window.range_anchor_index = None
        
        # Get current image path (source of truth)
        current_path = self.main_window.get_current_image_path()
        if not current_path or current_path not in displayed:
            # No current image - use first
            if displayed:
                self.main_window.set_current_image_by_path(displayed[0])
                self.main_window.highlight_image()
            return True
        
        # Find current index
        try:
            current_idx = displayed.index(current_path)
        except ValueError:
            current_idx = 0
        
        # Calculate page size (rows per page * columns)
        rows_per_page, _ = self.main_window.calculate_page_scroll_info()
        grid_info = self.main_window.get_actual_grid_info()
        columns = grid_info.get("columns", 1)
        if columns < 1:
            columns = 1
        page_size = rows_per_page * columns
        
        # Move down by one page
        target_idx = min(len(displayed) - 1, current_idx + page_size)
        
        # Set current image by path (source of truth) - this updates highlight_index
        target_path = displayed[target_idx]
        self.main_window.set_current_image_by_path(target_path)
        
        # highlight_image() will scroll to the highlighted image automatically
        self.main_window.highlight_image()
        return True

    def _handle_shift_home(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        return self._handle_home(event, context_data)

    def _handle_shift_end(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        return self._handle_end(event, context_data)

    # Action handlers
    def _handle_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not (event.modifiers() & Qt.ControlModifier):
            self.main_window.open_current_browse_view()
            return True
        return False

    def _handle_space(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not (event.modifiers() & Qt.ControlModifier):
            self.main_window.open_current_browse_view()
            return True
        return False

    def _handle_f_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.open_current_browse_view()
        return True

    def _handle_escape(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Explicitly accept the event before potentially blocking operations
        event.accept()
        # In list mode, ESC closes list view
        if self.main_window.current_view_mode == 'list':
            self.main_window.toggle_list_view()
            return True
        # Check if we're in specific files mode (stacked thumbnails) - prioritize navigation over selection clearing
        if (self.main_window.current_view_mode == 'thumbnail' and 
            getattr(self.main_window, 'specific_files_active', False)):
            # In specific files mode, ESC should navigate backward to preserve selections
            self.main_window.directory_stack_history_handler.navigate_backward()
            return True
        elif self.main_window.multi_select_mode and self.main_window.selected_files and self.main_window.current_view_mode == 'thumbnail':
            self.main_window.clear_selection()
            return True
        elif self.main_window.current_view_mode == 'thumbnail':
            self.main_window.directory_stack_history_handler.navigate_backward()
            return True
        elif self.main_window.current_view_mode == 'fullscreen':
            self.main_window.close_browse_view()
            return True
        return False

    def _handle_q_key_close_list(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Q key to close list view when in list mode."""
        if self.main_window.current_view_mode == 'list':
            event.accept()
            self.main_window.toggle_list_view()
            return True
        return False

    def _handle_shift_escape(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Escape to navigate forward in directory history"""
        # Explicitly accept the event before potentially blocking operations
        event.accept()
        if self.main_window.current_view_mode == 'thumbnail':
            self.main_window.directory_stack_history_handler.navigate_forward()
            return True
        return False

    def _handle_f10(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle F10 to clear forward and backward history stacks"""
        event.accept()
        if self.main_window.current_view_mode == 'thumbnail':
            handler = self.main_window.directory_stack_history_handler
            backward_count = len(handler.backward_stack)
            forward_count = len(handler.forward_stack)
            handler.backward_stack.clear()
            handler.forward_stack.clear()
            total_cleared = backward_count + forward_count
            if total_cleared > 0:
                handler._notify_status(f"Cleared {total_cleared} history entries", 3000)
            else:
                handler._notify_status("History stacks already empty", 2000)
            return True
        return False

    def _handle_question(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.show_help_test()
        return True

    # Debug and maintenance handlers
    def _handle_ctrl_shift_d(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.toggle_debug_mode()
        return True

    def _handle_ctrl_d(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:           
        if not (event.modifiers() & Qt.ShiftModifier):
            self.main_window.debug_cache_status()
            return True
        return False

    # def _handle_ctrl_shift_c(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
    #     self.main_window.clear_all_cache()
    #     return True

    def _handle_ctrl_delete(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.delete_selected_files()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(300, self.main_window.sequential_refresh_after_browse) 

        return True

    def _handle_ctrl_l_lock(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle cmd-L for locking files - only works when allow_thumbnail_locking is enabled"""
        if getattr(self.main_window, 'current_view_mode', None) == 'browse':
            # Browse reserves Cmd+L for File ▸ Last Image (Tools menu clears Lock shortcut in browse)
            return False
        from config import get_config
        config = get_config()
        settings = config.load_settings()
        allow_thumbnail_locking = settings.get('allow_thumbnail_locking', False)
        
        if not allow_thumbnail_locking:
            return False  # Don't handle if setting is disabled
        
        if hasattr(self.main_window, 'lock_selected_files'):
            self.main_window.lock_selected_files()
            return True
        return False

    def _handle_ctrl_shift_l_unlock(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle shift-cmd-L for unlocking files - always works, even when setting is off"""
        if hasattr(self.main_window, 'unlock_selected_files'):
            self.main_window.unlock_selected_files()
            return True
        return False

    # Other operation handlers

    def _handle_ctrl_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if self.main_window and hasattr(self.main_window, 'file_tree_handler'):
            self.main_window.file_tree_handler.collapse_file_tree()
        return True
    
    def _handle_ctrl_shift_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if self.main_window and hasattr(self.main_window, 'file_tree_handler'):
            self.main_window.file_tree_handler.expand_file_tree()
        return True

    def _handle_i_key_metadata(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Toggle Information sidebar (right sidebar with EXIF info) - I key
        self.main_window.toggle_information_display()
        return True

    def _handle_o_key_sidebar(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Toggle Shortcuts sidebar (Favorites and Move lists) - O key
        self.main_window.toggle_shortcuts_display()
        return True
    
    def _handle_ctrl_i_filename(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Toggle filename overlay on thumbnails - Cmd+I key
        self.main_window.toggle_thumbnail_filename_overlay()
        return True
    
    def _handle_ctrl_shift_i(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Toggle number overlay visibility
        self.main_window.number_overlay_visible = not self.main_window.number_overlay_visible
        self.main_window.update_number_overlay()
        return True

    def _handle_a_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.toggle_preview_fit_mode()
        return True

    def _handle_n_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle N key for name sort (A-Z)"""
        self.main_window.set_name_sort(reverse=False)
        return True

    def _handle_shift_n_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+N key for name sort (Z-A)"""
        self.main_window.set_name_sort(reverse=True)
        return True

    def _handle_r_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle R key for random sort"""
        self.main_window.view_mode_manager.set_random_mode()
        return True

    def _handle_d_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle D key for date sort (Oldest first)"""
        self.main_window.set_date_sort(reverse=True)
        return True

    def _handle_shift_d_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+D key for date sort (Newest first)"""
        self.main_window.set_date_sort(reverse=False)
        return True

    def _handle_z_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Z key for size sort (Largest first)"""
        self.main_window.set_size_sort(reverse=False)
        return True

    def _handle_shift_z_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Z key for size sort (Smallest first)"""
        self.main_window.set_size_sort(reverse=True)
        return True

    def _handle_c_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle C key for custom sort"""
        self.main_window.set_custom_sort()
        return True

    def _handle_cmd_k(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Cmd+K for similarity search"""
        # Work in thumbnail, browse, and list modes
        if self.main_window.current_view_mode in ['thumbnail', 'browse', 'list']:
            # Set focus to thumbnail view before executing (if in thumbnail view)
            if (self.main_window.current_view_mode == 'thumbnail' and
                hasattr(self.main_window, 'main_content_widget') and 
                self.main_window.main_content_widget):
                self.main_window.main_content_widget.setFocus()
            self.main_window.reorder_images_by_similarity()
            # After search, ensure focus is set if we're now in thumbnail mode
            if (self.main_window.current_view_mode == 'thumbnail' and
                hasattr(self.main_window, 'main_content_widget') and 
                self.main_window.main_content_widget):
                self.main_window.main_content_widget.setFocus()
            return True
        return False
    
    def _handle_favorite_directory(self, event: QKeyEvent, context_data: Dict[str, Any], index: int) -> bool:
        """Handle Ctrl+number to open favorite directory"""
        try:
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            favorites = settings.get('favorite_directories', [None] * 9)
            
            # Ensure we have exactly 9 items
            favorites = (favorites + [None] * 9)[:9]
            
            # Check if favorite at index exists and is valid
            if 0 <= index < len(favorites) and favorites[index]:
                favorite_path = favorites[index].strip()
                if favorite_path:
                    # Check if it's a directory or an image file
                    is_directory = os.path.isdir(favorite_path)
                    is_image_file = False
                    if not is_directory and os.path.isfile(favorite_path):
                        from thumbnail_constants import get_image_extensions
                        _, ext = os.path.splitext(favorite_path)
                        ext_lower = ext.lower()
                        image_extensions = get_image_extensions()
                        is_image_file = ext_lower in image_extensions
                    
                    if is_directory or is_image_file:
                        # Use QTimer.singleShot to defer load call to main thread
                        # This ensures thread safety and prevents segfaults when interrupting thumbnail loading
                        def load_favorite():
                            try:
                                # Save current state before opening (like request_directory_opening does)
                                # This ensures Esc and Shift+Esc work correctly
                                if hasattr(self.main_window, 'directory_stack_history_handler'):
                                    try:
                                        self.main_window.directory_stack_history_handler.save_current_state(
                                            "keyboard_handler._handle_favorite_directory", delay=0.0)
                                    except Exception:
                                        pass
                                
                                if is_directory:
                                    # Use request_directory_opening to properly update tree view
                                    # This ensures tree view is updated even when directory has no files
                                    if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
                                        try:
                                            self.main_window.file_tree_handler.request_directory_opening(favorite_path)
                                        except Exception:
                                            # Fallback to load_directory if request_directory_opening fails
                                            if hasattr(self.main_window, 'load_directory'):
                                                self.main_window.load_directory(favorite_path, external_load=True)
                                    elif hasattr(self.main_window, 'load_directory'):
                                        # Fallback if file_tree_handler doesn't exist
                                        self.main_window.load_directory(favorite_path, external_load=True)
                                elif is_image_file:
                                    # Load specific file and open in browse view
                                    # For single files, load_specific_files calls load_file_with_directory_thumbnails
                                    # which already handles opening browse view with the correct image
                                    if hasattr(self.main_window, 'load_specific_files'):
                                        self.main_window.load_specific_files([favorite_path], external_load=True)
                            except Exception as e:
                                logger.error(f"Error loading favorite {index}: {e}")
                                import traceback
                                logger.error(traceback.format_exc())
                        
                        QTimer.singleShot(0, load_favorite)
                        event.accept()
                        return True
            
            # Do nothing if field is not set or path doesn't exist or is invalid
            event.accept()
            return True
        except Exception as e:
            logger.error(f"Error handling favorite directory {index}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            event.accept()
            return True

    def _handle_h_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        event.accept()
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return True
        if self.main_window.selected_files:
            self.main_window.clear_selection()
        self.main_window.range_anchor_index = None
        # Set current image by path (source of truth) - use first image
        self.main_window.set_current_image_by_path(displayed[0])
        self.main_window.highlight_image()
        # Scroll to first item in list view (H key should scroll to show first item)
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'list' and
            hasattr(self.main_window, 'list_view_container') and 
            self.main_window.list_view_container):
            QTimer.singleShot(10, lambda: self.main_window.list_view_container.scroll_to_highlighted(
                self.main_window.highlight_index, force=True))
        return True

    def _handle_shift_h_select_to_first(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Select from first image through anchor (same behavior as Shift+Home on thumbnail grid)."""
        event.accept()
        if self.main_window.range_anchor_index is None:
            self.main_window.range_anchor_index = self.main_window.highlight_index
        self.main_window.highlight_index = 0
        self.main_window.selection_manager.handle_range_selection(
            self.main_window.highlight_index, anchor=self.main_window.range_anchor_index
        )
        return True

    def _handle_e_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        event.accept()
        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return True
        if self.main_window.selected_files:
            self.main_window.clear_selection()
        self.main_window.range_anchor_index = None
        # Set current image by path (source of truth) - use last image
        last_image_path = displayed[-1]
        self.main_window.set_current_image_by_path(last_image_path)
        self.main_window.highlight_image()
        # Scroll to last item in list view (E key should scroll to show last item)
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'list' and
            hasattr(self.main_window, 'list_view_container') and 
            self.main_window.list_view_container):
            QTimer.singleShot(10, lambda: self.main_window.list_view_container.scroll_to_highlighted(
                self.main_window.highlight_index, force=True))
        return True

    def _handle_list_plus(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle +/= keys to increase list view row height"""
        # Only handle in list view mode
        if not (hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list'):
            return False
        
        # Check if list view container exists
        if not (hasattr(self.main_window, 'list_view_container') and self.main_window.list_view_container):
            return False
        
        # Increase row height
        canvas = self.main_window.list_view_container.canvas
        if hasattr(canvas, 'increase_row_height'):
            canvas.increase_row_height()
            return True
        
        return False
    
    def _handle_list_minus(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle - key to decrease list view row height"""
        # Only handle in list view mode
        if not (hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list'):
            return False
        
        # Check if list view container exists
        if not (hasattr(self.main_window, 'list_view_container') and self.main_window.list_view_container):
            return False
        
        # Decrease row height
        canvas = self.main_window.list_view_container.canvas
        if hasattr(canvas, 'decrease_row_height'):
            canvas.decrease_row_height()
            return True
        
        return False
    
    def _handle_list_zero(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle 0 key to reset list view row height to default"""
        # Only handle in list view mode
        if not (hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list'):
            return False
        
        # Check if list view container exists
        if not (hasattr(self.main_window, 'list_view_container') and self.main_window.list_view_container):
            return False
        
        # Reset row height to default
        canvas = self.main_window.list_view_container.canvas
        if hasattr(canvas, 'reset_row_height'):
            canvas.reset_row_height()
            return True
        
        return False
    
    def _handle_minus_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Don't handle in list view mode (handled by list view handler)
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            return False
        
        # Only work in debug mode
        # if not getattr(self.main_window, 'debug_mode', False):
        #     return False
            
        from thumbnail_constants import MIN_THUMBNAIL_SIZE, MAX_THUMBNAIL_SIZE
        
        current_size = getattr(self.main_window, 'current_thumbnail_size', MIN_THUMBNAIL_SIZE)
        multiplier = 1 / 1.1
        new_size = max(64, int(current_size * multiplier))
        new_size = int(new_size)
        
        if new_size != current_size:
            # Set manual size flag to prevent automatic recalculation
            self.main_window.manual_thumbnail_size = True
            self.main_window.set_thumbnail_size(new_size)
            # Show status notification
            # self.main_window.status_notification.show_message(f"- Thumbnail size: {new_size}px")
            self.main_window.highlight_image() #DGN Wrong thing to refresh thumbnails
            # Force a resize event to ensure proper layout update after thumbnail size change
            QTimer.singleShot(100, self.main_window.force_resize_event)
        return True

    def _handle_equals_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Don't handle in list view mode (handled by list view handler)
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            return False
        
        # Only work in debug mode
        # if not getattr(self.main_window, 'debug_mode', False):
        #     return False
            
        from thumbnail_constants import MIN_THUMBNAIL_SIZE, MAX_THUMBNAIL_SIZE
        
        current_size = getattr(self.main_window, 'current_thumbnail_size', MIN_THUMBNAIL_SIZE)
        multiplier = 1.1
        new_size = min(MAX_THUMBNAIL_SIZE, int(current_size * multiplier))
        
        if new_size != current_size:
            # Set manual size flag to prevent automatic recalculation
            self.main_window.manual_thumbnail_size = True
            self.main_window.set_thumbnail_size(new_size)
            # Show status notification
            self.main_window.status_notification.show_message(f"+ Thumbnail size: {new_size}px")
            
            # Force a resize event to ensure proper layout update after thumbnail size change
            QTimer.singleShot(100, self.main_window.force_resize_event)
        return True
    def handle_zero_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Don't handle in list view mode (handled by list view handler)
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            return False
        
        self.main_window.manual_thumbnail_size = False
        # Call set_dynamic_thumbnail_size directly - force_resize_event uses same old/new size
        # so resizeEvent returns early and never triggers thumbnail recalculation
        if hasattr(self.main_window, 'set_dynamic_thumbnail_size'):
            self.main_window.set_dynamic_thumbnail_size()
        new_size = getattr(self.main_window, 'current_thumbnail_size', 0)
        if hasattr(self.main_window, 'status_notification') and self.main_window.status_notification:
            self.main_window.status_notification.show_message(f"0 Thumbnail size reset to default: {new_size}px")
        QTimer.singleShot(100, self.main_window.force_resize_event)
        return True

class BrowseViewKeyboardHandler(BaseKeyboardHandler):
    """Keyboard handler for browse view mode."""

    # Double-tap window in seconds (same key within this interval = double-tap)
    _DOUBLE_TAP_MS = 2400

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._double_tap_last_key: Optional[int] = None
        self._double_tap_last_time: float = 0.0
        self._setup_key_bindings()

    def _setup_key_bindings(self):
        """Set up key bindings for browse view."""

        CMD = Qt.ControlModifier
        SHIFT = Qt.ShiftModifier
        CTRL = Qt.MetaModifier

        # Navigation
        self.add_key_binding("left_arrow", KeyBinding(Qt.Key_Left, description="Previous image"), self._handle_left_arrow)
        self.add_key_binding("right_arrow", KeyBinding(Qt.Key_Right, description="Next image"), self._handle_right_arrow)
        self.add_key_binding("up_arrow", KeyBinding(Qt.Key_Up, description="Previous image"), self._handle_up_arrow)
        self.add_key_binding("down_arrow", KeyBinding(Qt.Key_Down, description="Next image"), self._handle_down_arrow)

        # Shift+Arrow for image transformations (rotate/flip)
        self.add_key_binding("shift_left", KeyBinding(Qt.Key_Left, SHIFT, description="Rotate counterclockwise"), self._handle_shift_left)
        self.add_key_binding("shift_right", KeyBinding(Qt.Key_Right, SHIFT, description="Rotate clockwise"), self._handle_shift_right)
        self.add_key_binding("shift_up", KeyBinding(Qt.Key_Up, SHIFT, description="Flip vertical"), self._handle_shift_up)
        self.add_key_binding("shift_down", KeyBinding(Qt.Key_Down, SHIFT, description="Flip horizontal"), self._handle_shift_down)

        # Home/End navigation
        self.add_key_binding("home", KeyBinding(Qt.Key_Home, description="Home - Jump to first image"), self._handle_home)
        self.add_key_binding("end", KeyBinding(Qt.Key_End, description="End - Jump to last image"), self._handle_end)
        self.add_key_binding("h_key", KeyBinding(Qt.Key_H, description="Home - Jump to first image"), self._handle_h_key)
        self.add_key_binding("e_key", KeyBinding(Qt.Key_E, description="End - Jump to last image"), self._handle_e_key)

        # Help and settings
        self.add_key_binding("question", KeyBinding(Qt.Key_Question, description="Show help"), self._handle_question)
        # F1 is handled by menu system
        self.add_key_binding("slash", KeyBinding(Qt.Key_Slash, description="Show help"), self._handle_question)

        # Zoom controls
        self.add_key_binding("plus", KeyBinding(Qt.Key_Plus, description="Zoom in"), self._handle_plus)
        self.add_key_binding("shift_plus", KeyBinding(Qt.Key_Plus, Qt.ShiftModifier, description="Zoom in"), self._handle_plus)
        self.add_key_binding("equal", KeyBinding(Qt.Key_Equal, description="Zoom in"), self._handle_equal)
        self.add_key_binding("shift_equal", KeyBinding(Qt.Key_Equal, Qt.ShiftModifier, description="Zoom in"), self._handle_equal)
        self.add_key_binding("minus", KeyBinding(Qt.Key_Minus, description="Zoom out"), self._handle_minus)
        self.add_key_binding("shift_minus", KeyBinding(Qt.Key_Minus, Qt.ShiftModifier, description="Zoom out"), self._handle_minus)
        self.add_key_binding("underscore", KeyBinding(Qt.Key_Underscore, description="Zoom out"), self._handle_underscore)
        self.add_key_binding("shift_underscore", KeyBinding(Qt.Key_Underscore, Qt.ShiftModifier, description="Zoom out"), self._handle_underscore)
        # A key is handled by menu system (Actual Size)
        # I key is used for Information sidebar toggle (zoom in/out via +/- and -)
        # Mac keyboard Control+W (Qt.MetaModifier): fit image width to browse canvas, scroll to top
        self.add_key_binding("ctrl_w_fit_canvas_width", KeyBinding(Qt.Key_W, CTRL, description="Fit image to canvas width (top)"), self._handle_ctrl_w_fit_canvas_width)

        # Cmd+Arrow for panning when zoomed
        self.add_key_binding("cmd_left_ctrl", KeyBinding(Qt.Key_Left, CMD, description="Pan left"), self._handle_cmd_left)
        self.add_key_binding("cmd_right_ctrl", KeyBinding(Qt.Key_Right, CMD, description="Pan right"), self._handle_cmd_right)
        self.add_key_binding("cmd_up_ctrl", KeyBinding(Qt.Key_Up, CMD, description="Pan up"), self._handle_cmd_up)
        self.add_key_binding("cmd_down_ctrl", KeyBinding(Qt.Key_Down, CMD, description="Pan down"), self._handle_cmd_down)

        # Actions
        self.add_key_binding("space", KeyBinding(Qt.Key_Space, description="Next image / Return to thumbnails"), self._handle_space)
        self.add_key_binding("shift_space", KeyBinding(Qt.Key_Space, SHIFT, description="Toggle space bar behavior"), self._handle_shift_space)
        self.add_key_binding("return", KeyBinding(Qt.Key_Return, description="Return to thumbnails"), self._handle_return)
        self.add_key_binding("enter", KeyBinding(Qt.Key_Enter, description="Return to thumbnails"), self._handle_enter)
        self.add_key_binding("escape", KeyBinding(Qt.Key_Escape, description="Return to thumbnails"), self._handle_escape)
        self.add_key_binding("q_key", KeyBinding(Qt.Key_Q, description="Return to thumbnails"), self._handle_q_key)
        self.add_key_binding("f_key", KeyBinding(Qt.Key_F, description="Return to thumbnails"), self._handle_f_key)
        # F11 is handled by menu system (MacOS Fullscreen)
        # Ctrl+F is handled by menu system (Search by Description)
        # self.add_key_binding("f12", KeyBinding(Qt.Key_F12, description="Toggle maximized"), self._handle_f12)
        # F10 to clear history stacks
        self.add_key_binding("f10", KeyBinding(Qt.Key_F10, description="Clear forward and backward history stacks"), self._handle_f10)
        # Shift+Esc to navigate forward in directory history
        self.add_key_binding("shift_escape", KeyBinding(Qt.Key_Escape, Qt.ShiftModifier, description="Navigate forward in directory history"), self._handle_shift_escape)

        # Shift+R for reset transformations
        self.add_key_binding("shift_r", KeyBinding(Qt.Key_R, SHIFT, description="Reset image transformations"), self._handle_shift_r)

        # Overlays
        # I key toggles Information sidebar (right sidebar with EXIF info)
        # Ctrl+I (Cmd+I) toggles filename overlay (simple filename/number overlay)
        self.add_key_binding("i_key", KeyBinding(Qt.Key_I, description="Information sidebar toggle"), self._handle_i_key_metadata)
        self.add_key_binding("o_key", KeyBinding(Qt.Key_O, description="Organize sidebar toggle"), self._handle_o_key_sidebar)
        self.add_key_binding("ctrl_i", KeyBinding(Qt.Key_I, CMD, description="Information overlay toggle"), self._handle_ctrl_i_filename_overlay)

        # Debug and settings
        self.add_key_binding("ctrl_shift_d", KeyBinding(Qt.Key_D, CMD | SHIFT, description="Debug mode toggle"), self._handle_ctrl_shift_d)

        # Search actions
        # Cmd+K for similarity search (also handled by menu system)
        self.add_key_binding("cmd_k", KeyBinding(Qt.Key_K, CMD, description="Find similar images"), self._handle_cmd_k)
        # Ctrl+F is handled by menu system (Search by Description)

        # Favorite directories shortcuts (Ctrl+1 through Ctrl+9)
        # On macOS, Qt.MetaModifier is the actual Control key (not Command)
        for i in range(1, 10):
            key = getattr(Qt, f'Key_{i}')
            # Create handler with index captured in closure - use default parameter to capture correctly
            def make_handler(idx):
                def handler(event, context_data=None):
                    return self._handle_favorite_directory(event, context_data, idx)
                return handler
            self.add_key_binding(f"ctrl_{i}", KeyBinding(key, CTRL, description=f"Open favorite directory {i}"), 
                                make_handler(i-1))

        # Other - status bar handled by View menu action shortcut
        self.add_key_binding("ctrl_shift_return", KeyBinding(Qt.Key_Return, CMD | SHIFT, description="Expand file tree"), self._handle_ctrl_shift_return)
        self.add_key_binding("ctrl_return", KeyBinding(Qt.Key_Return, CMD, description="Collapse file tree"), self._handle_ctrl_return)
        self.add_key_binding("ctrl_enter", KeyBinding(Qt.Key_Enter, CMD, description="Collapse file tree"), self._handle_ctrl_enter)

        # Double-tap T/P: switch to thumbnail and show tree or preview (T and P disabled in browse per UX)
        self.add_key_binding("t_key", KeyBinding(Qt.Key_T, description="Double-tap: switch to thumbnails and show tree"), self._handle_t_key)
        self.add_key_binding("p_key", KeyBinding(Qt.Key_P, description="Double-tap: switch to thumbnails and show preview"), self._handle_p_key)
        self.add_key_binding(
            "j_key",
            KeyBinding(Qt.Key_J, description="Switch to thumbnails and show jobs pane"),
            self._handle_j_key_browse,
        )

        # External editors

    def _handle_question(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.show_help_test()
        return True

    def _handle_t_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Double-tap T: switch to thumbnail mode and show tree (not toggle)."""
        if event.isAutoRepeat():
            return True
        now = time.perf_counter()
        window_ms = self._DOUBLE_TAP_MS / 1000.0
        if (self._double_tap_last_key == Qt.Key_T and
                (now - self._double_tap_last_time) < window_ms):
            self._double_tap_last_key = None
            self._double_tap_last_time = 0.0
            self.main_window.close_browse_view()
            def _show_tree():
                if hasattr(self.main_window, 'combined_sidebar') and self.main_window.combined_sidebar:
                    self.main_window.combined_sidebar.set_tree_visible(True)
            QTimer.singleShot(50, _show_tree)
            return True
        self._double_tap_last_key = Qt.Key_T
        self._double_tap_last_time = now
        # First tap: do not consume — let View > T (toggle file tree) QAction run.
        return False

    def _handle_p_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Double-tap P: switch to thumbnail mode and show preview (not toggle)."""
        if event.isAutoRepeat():
            return True
        now = time.perf_counter()
        window_ms = self._DOUBLE_TAP_MS / 1000.0
        if (self._double_tap_last_key == Qt.Key_P and
                (now - self._double_tap_last_time) < window_ms):
            self._double_tap_last_key = None
            self._double_tap_last_time = 0.0
            self.main_window.close_browse_view()
            def _show_preview():
                if hasattr(self.main_window, 'combined_sidebar') and self.main_window.combined_sidebar:
                    self.main_window.combined_sidebar.set_preview_visible(True)
            QTimer.singleShot(50, _show_preview)
            return True
        self._double_tap_last_key = Qt.Key_P
        self._double_tap_last_time = now
        # First tap: do not consume — let View > P (toggle preview) QAction run.
        return False

    def _handle_j_key_browse(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """J in browse: return to thumbnails and show jobs pane (always show, not toggle)."""
        if event.isAutoRepeat():
            return True
        self.main_window.close_browse_view()

        QTimer.singleShot(50, self.main_window.show_jobs_pane)
        event.accept()
        return True

    # Navigation handlers
    def _handle_left_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not (event.modifiers() & Qt.ShiftModifier):
            self.main_window.show_previous_image()
            event.accept()
            return True
        return False

    def _handle_right_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not (event.modifiers() & Qt.ShiftModifier):
            self.main_window.show_next_image()
            event.accept()
            return True
        return False

    def _handle_up_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not (event.modifiers() & Qt.ShiftModifier):
            self.main_window.show_previous_image()
            event.accept()
            return True
        return False

    def _handle_down_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not (event.modifiers() & Qt.ShiftModifier):
            self.main_window.show_next_image()
            event.accept()
            return True
        return False

    # Image transformation handlers (shift-arrow keys rotate/flip images)
    def _handle_shift_left(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Left for rotating counterclockwise"""
        self.main_window.rotate_image_counterclockwise()
        event.accept()
        return True

    def _handle_shift_right(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Right for rotating clockwise"""
        self.main_window.rotate_image_clockwise()
        event.accept()
        return True

    def _handle_shift_up(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Up for flipping vertically"""
        self.main_window.flip_image_vertical()
        event.accept()
        return True

    def _handle_shift_down(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Down for flipping horizontally"""
        self.main_window.flip_image_horizontal()
        event.accept()
        return True

    # Helper methods for scrolling when zoomed
    def _scroll_left(self) -> bool:
        """Scroll left when zoomed in - moves 10% of available view width"""
        # Use screen size for scroll amount calculation to allow full image panning
        available_size = self.main_window.get_physical_screen_size()
        if self.main_window.status_bar_visible:
            status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
            available_size = QSize(available_size.width(), available_size.height() - status_bar_height)
        move_amount_x = int(available_size.width() * 0.1)
        self.main_window.scroll_x += move_amount_x
        self.main_window.apply_pan_offset()
        return True

    def _scroll_right(self) -> bool:
        """Scroll right when zoomed in - moves 10% of available view width"""
        # Use screen size for scroll amount calculation to allow full image panning
        available_size = self.main_window.get_physical_screen_size()
        if self.main_window.status_bar_visible:
            status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
            available_size = QSize(available_size.width(), available_size.height() - status_bar_height)
        move_amount_x = int(available_size.width() * 0.1)
        self.main_window.scroll_x -= move_amount_x
        self.main_window.apply_pan_offset()
        return True

    def _scroll_up(self) -> bool:
        """Scroll up when zoomed in - moves 10% of available view height"""
        # Use screen size for scroll amount calculation to allow full image panning
        available_size = self.main_window.get_physical_screen_size()
        if self.main_window.status_bar_visible:
            status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
            available_size = QSize(available_size.width(), available_size.height() - status_bar_height)
        move_amount_y = int(available_size.height() * 0.1)
        self.main_window.scroll_y += move_amount_y
        self.main_window.apply_pan_offset()
        return True

    def _scroll_down(self) -> bool:
        """Scroll down when zoomed in - moves 10% of available view height"""
        # Use screen size for scroll amount calculation to allow full image panning
        available_size = self.main_window.get_physical_screen_size()
        if self.main_window.status_bar_visible:
            status_bar_height = self.main_window.status_bar.height() if self.main_window.status_bar.isVisible() else 0
            available_size = QSize(available_size.width(), available_size.height() - status_bar_height)
        move_amount_y = int(available_size.height() * 0.1)
        self.main_window.scroll_y -= move_amount_y
        self.main_window.apply_pan_offset()
        return True

    # Home/End handlers
    def _handle_home(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.scroll_x = 0
        self.main_window.scroll_y = 0
        self.main_window.update()
        return True

    def _handle_end(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.scroll_x = 0
        self.main_window.scroll_y = 0
        self.main_window.update()
        return True

    # Zoom handlers
    def _handle_plus(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.zoom_in()
        return True

    def _handle_equal(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.zoom_in()
        return True

    def _handle_minus(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.zoom_out()
        return True

    def _handle_underscore(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.zoom_out()
        return True

    def _handle_ctrl_w_fit_canvas_width(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        h = getattr(self.main_window, 'browse_view_handler', None)
        if h:
            h.fit_image_to_canvas_width()
        event.accept()
        return True

    def _handle_a_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.toggle_actual_size()
        return True

    # Panning handlers (cmd-arrow keys pan the image when zoomed)
    def _handle_cmd_left(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Cmd+Left for panning left"""
        self._scroll_left()
        event.accept()
        return True

    def _handle_cmd_right(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Cmd+Right for panning right"""
        self._scroll_right()
        event.accept()
        return True

    def _handle_cmd_up(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Cmd+Up for panning up"""
        self._scroll_up()
        event.accept()
        return True

    def _handle_cmd_down(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Cmd+Down for panning down"""
        self._scroll_down()
        event.accept()
        return True

    # Action handlers
    def _handle_space(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            if self.main_window.space_key_mode == 'advance':
                self.main_window.show_next_image()
            else:
                self.main_window.close_browse_view()
            return True
        return False

    def _handle_shift_space(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.toggle_space_bar_behavior()
        return True

    def _handle_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not (event.modifiers() & Qt.ControlModifier):
            self.main_window.close_browse_view()
            return True
        return False

    def _handle_enter(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not (event.modifiers() & Qt.ControlModifier):
            self.main_window.close_browse_view()
            return True
        return False

    def _handle_escape(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Explicitly accept the event before potentially blocking operations
        event.accept()
        self.main_window.close_browse_view()
        return True

    def _handle_f10(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle F10 to clear forward and backward history stacks"""
        event.accept()
        if self.main_window.current_view_mode == 'browse':
            handler = self.main_window.directory_stack_history_handler
            backward_count = len(handler.backward_stack)
            forward_count = len(handler.forward_stack)
            handler.backward_stack.clear()
            handler.forward_stack.clear()
            total_cleared = backward_count + forward_count
            if total_cleared > 0:
                handler._notify_status(f"Cleared {total_cleared} history entries", 3000)
            else:
                handler._notify_status("History stacks already empty", 2000)
            return True
        return False

    def _handle_shift_escape(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Shift+Escape to navigate forward in directory history"""
        # Explicitly accept the event before potentially blocking operations
        event.accept()
        if self.main_window.current_view_mode == 'browse':
            self.main_window.directory_stack_history_handler.navigate_forward()
            return True
        return False

    def _handle_q_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.close_browse_view()
        return True

    def _handle_f_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.close_browse_view()
        return True

    def _handle_f12(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            self.main_window.toggle_maximized()
            return True
        return False

    def _handle_shift_r(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.reset_image_transformations()
        return True

    # Overlay handlers
    def _handle_i_key_metadata(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Toggle Information sidebar (right sidebar with EXIF info) - I key in browse mode
        self.main_window.toggle_information_display()
        return True

    def _handle_o_key_sidebar(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Toggle Shortcuts sidebar (Favorites and Move lists) - O key in browse mode
        self.main_window.toggle_shortcuts_display()
        return True

    def _handle_ctrl_i_filename_overlay(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Toggle filename overlay - Cmd+I key in browse mode
        # In browse mode, this toggles the simple filename overlay (filename/number)
        self.main_window.number_overlay_visible = not self.main_window.number_overlay_visible
        self.main_window.update_number_overlay()
        return True

    def _handle_ctrl_shift_i(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Toggle number overlay visibility
        self.main_window.number_overlay_visible = not self.main_window.number_overlay_visible
        self.main_window.update_number_overlay()
        return True

    # Debug and settings handlers
    def _handle_ctrl_shift_d(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.toggle_debug_mode()
        return True

    def _handle_cmd_k(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Handle Cmd+K for similarity search in browse mode"""
        # Switch to thumbnail mode and execute search
        self.main_window.reorder_images_by_similarity()
        # After search, ensure focus is set if we're now in thumbnail mode
        if (self.main_window.current_view_mode == 'thumbnail' and
            hasattr(self.main_window, 'main_content_widget') and 
            self.main_window.main_content_widget):
            self.main_window.main_content_widget.setFocus()
            return True
    
    def _handle_favorite_directory(self, event: QKeyEvent, context_data: Dict[str, Any], index: int) -> bool:
        """Handle Ctrl+number to open favorite directory or file"""
        try:
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            favorites = settings.get('favorite_directories', [None] * 9)
            
            # Ensure we have exactly 9 items
            favorites = (favorites + [None] * 9)[:9]
            
            # Check if favorite at index exists and is valid
            if 0 <= index < len(favorites) and favorites[index]:
                favorite_path = favorites[index].strip()
                if favorite_path:
                    # Check if it's a directory or an image file
                    is_directory = os.path.isdir(favorite_path)
                    is_image_file = False
                    if not is_directory and os.path.isfile(favorite_path):
                        from thumbnail_constants import get_image_extensions
                        _, ext = os.path.splitext(favorite_path)
                        ext_lower = ext.lower()
                        image_extensions = get_image_extensions()
                        is_image_file = ext_lower in image_extensions
                    
                    if is_directory or is_image_file:
                        # Use QTimer.singleShot to defer load call to main thread
                        # This ensures thread safety and prevents segfaults when interrupting thumbnail loading
                        def load_favorite():
                            try:
                                # Save current state before opening (like request_directory_opening does)
                                # This ensures Esc and Shift+Esc work correctly
                                if hasattr(self.main_window, 'directory_stack_history_handler'):
                                    try:
                                        self.main_window.directory_stack_history_handler.save_current_state(
                                            "keyboard_handler._handle_favorite_directory", delay=0.0)
                                    except Exception:
                                        pass
                                
                                if is_directory:
                                    # Use request_directory_opening to properly update tree view
                                    # This ensures tree view is updated even when directory has no files
                                    if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
                                        try:
                                            self.main_window.file_tree_handler.request_directory_opening(favorite_path)
                                        except Exception:
                                            # Fallback to load_directory if request_directory_opening fails
                                            if hasattr(self.main_window, 'load_directory'):
                                                self.main_window.load_directory(favorite_path, external_load=True)
                                    elif hasattr(self.main_window, 'load_directory'):
                                        # Fallback if file_tree_handler doesn't exist
                                        self.main_window.load_directory(favorite_path, external_load=True)
                                elif is_image_file:
                                    # Load specific file and open in browse view
                                    # For single files, load_specific_files calls load_file_with_directory_thumbnails
                                    # which already handles opening browse view with the correct image
                                    if hasattr(self.main_window, 'load_specific_files'):
                                        self.main_window.load_specific_files([favorite_path], external_load=True)
                            except Exception as e:
                                logger.error(f"Error loading favorite {index}: {e}")
                                import traceback
                                logger.error(traceback.format_exc())
                        
                        QTimer.singleShot(0, load_favorite)
                        event.accept()
                        return True
            
            # Do nothing if field is not set or path doesn't exist or is invalid
            event.accept()
            return True
        except Exception as e:
            logger.error(f"Error handling favorite directory {index}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            event.accept()
            return True

    # Other handlers - status bar moved to View menu

    def _handle_ctrl_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if self.main_window and hasattr(self.main_window, 'file_tree_handler'):
            self.main_window.file_tree_handler.collapse_file_tree()
        return True

    def _handle_ctrl_enter(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.main_window.collapse_file_tree()
        return True
    
    def _handle_ctrl_shift_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if self.main_window and hasattr(self.main_window, 'file_tree_handler'):
            self.main_window.file_tree_handler.expand_file_tree()
        return True


    # External editor handler
    def _handle_h_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        displayed = self.main_window.get_displayed_images()
        if displayed:
            self.main_window.current_index = 0
            self.main_window.highlight_index = 0
            self.main_window.show_image(displayed[0], 0)
            # Trigger scroll-aware loading after programmatic scroll
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self.main_window.on_scroll_changed())
        return True

    def _handle_e_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        displayed = self.main_window.get_displayed_images()
        last_index = len(displayed) - 1 if displayed else 0
        self.main_window.current_index = last_index
        self.main_window.highlight_index = last_index
        if displayed:
            self.main_window.show_image(displayed[last_index], last_index)
            # Trigger scroll-aware loading after programmatic scroll
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: self.main_window.on_scroll_changed())
        return True


class SlideshowKeyboardHandler(BaseKeyboardHandler):
    """Keyboard handler for slideshow mode."""

    def __init__(self, slideshow_manager, parent=None):
        super().__init__(parent)
        self.slideshow_manager = slideshow_manager
        self._setup_key_bindings()

    def _setup_key_bindings(self):
        """Set up key bindings for slideshow mode."""
        # Basic slideshow controls
        # S key is handled by menu system (Slideshow)
        self.add_key_binding("escape", KeyBinding(Qt.Key_Escape, description="Stop slideshow"), self._handle_escape)

        # Navigation
        self.add_key_binding("n_key", KeyBinding(Qt.Key_N, description="Advance slideshow"), self._handle_n_key)

        # Speed controls
        self.add_key_binding("key_1", KeyBinding(Qt.Key_1, description="Slow down slideshow"), self._handle_key_1)
        self.add_key_binding("key_2", KeyBinding(Qt.Key_2, description="Speed up slideshow"), self._handle_key_2)

        # Transition controls
        self.add_key_binding("key_3", KeyBinding(Qt.Key_3, description="Slow down transitions"), self._handle_key_3)
        self.add_key_binding("key_4", KeyBinding(Qt.Key_4, description="Speed up transitions"), self._handle_key_4)

        # Rotation controls
        self.add_key_binding("key_5", KeyBinding(Qt.Key_5, description="Decrease max rotation"), self._handle_key_5)
        self.add_key_binding("key_6", KeyBinding(Qt.Key_6, description="Increase max rotation"), self._handle_key_6)

        # Overlap controls
        self.add_key_binding("key_7", KeyBinding(Qt.Key_7, description="Decrease overlap"), self._handle_key_7)
        self.add_key_binding("key_8", KeyBinding(Qt.Key_8, description="Increase overlap"), self._handle_key_8)

        # Preset controls
        self.add_key_binding("key_0", KeyBinding(Qt.Key_0, description="Slow speed preset"), self._handle_key_0)
        self.add_key_binding("key_9", KeyBinding(Qt.Key_9, description="Fast speed preset"), self._handle_key_9)

        # Direction controls
        self.add_key_binding("up_arrow", KeyBinding(Qt.Key_Up, description="Change direction to top"), self._handle_up_arrow)
        self.add_key_binding("down_arrow", KeyBinding(Qt.Key_Down, description="Change direction to bottom"), self._handle_down_arrow)
        self.add_key_binding("left_arrow", KeyBinding(Qt.Key_Left, description="Change direction to left"), self._handle_left_arrow)
        self.add_key_binding("right_arrow", KeyBinding(Qt.Key_Right, description="Change direction to right"), self._handle_right_arrow)
        self.add_key_binding("shift_r", KeyBinding(Qt.Key_R, Qt.ShiftModifier, description="Set random direction"), self._handle_shift_r)
        self.add_key_binding("c_key", KeyBinding(Qt.Key_C, description="Set no transition"), self._handle_c_key)

        # Space and Enter for fullscreen
        self.add_key_binding("space", KeyBinding(Qt.Key_Space, description="Enter browse mode"), self._handle_space)
        self.add_key_binding("shift_space", KeyBinding(Qt.Key_Space, Qt.ShiftModifier, description="Toggle space bar behavior"), self._handle_shift_space)
        self.add_key_binding("return", KeyBinding(Qt.Key_Return, description="Enter browse mode"), self._handle_return)
        self.add_key_binding("f_key", KeyBinding(Qt.Key_F, description="Enter browse mode"), self._handle_f_key)
        # F11 is handled by menu system (MacOS Fullscreen)
        # Ctrl+F is handled by menu system (Search by Description)

        # File tree
        self.add_key_binding("ctrl_return", KeyBinding(Qt.Key_Return, Qt.ControlModifier, description="Collapse file tree"), self._handle_ctrl_return)
        self.add_key_binding("ctrl_enter", KeyBinding(Qt.Key_Enter, Qt.ControlModifier, description="Collapse file tree"), self._handle_ctrl_enter)

        # Help and settings
        self.add_key_binding("question", KeyBinding(Qt.Key_Question, description="Show help"), self._handle_question)
        # F1 is handled by menu system
        self.add_key_binding("slash", KeyBinding(Qt.Key_Slash, description="Show help"), self._handle_question)

    def _handle_question(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow_manager.main_window.show_help_test()
        return True

    def _handle_escape(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Explicitly accept the event before potentially blocking operations
        event.accept()
        self.slideshow_manager.stop_slideshow()
        return True

    def _handle_n_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow_manager.advance_slideshow()
        return True

    def _handle_key_1(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Slow down slideshow rate
        rate_ms = self.slideshow_manager.slideshow_rate
        if rate_ms < 1000:
            # Convert ms to seconds for fractional stepping
            rate_sec = rate_ms / 1000.0
            # Step up by 0.125 seconds, clamp to max of 10 seconds
            new_rate_sec = min(10.0, rate_sec + 0.125)
            new_rate_ms = int(round(new_rate_sec * 1000))
        else:
            # Step up by 1 second
            new_rate_ms = min(60000, rate_ms + 1000)
        self.slideshow_manager.slideshow_rate = new_rate_ms
        self.slideshow_manager.slideshow_timer.setInterval(new_rate_ms)
        self.slideshow_manager.debounced_save_setting('slideshow_rate', new_rate_ms)
        if self.slideshow_manager.status_notification:
            sec = new_rate_ms / 1000.0
            if sec >= 1.0:
                msg = f"Slowed slideshow to {sec:.3g}s"
            else:
                msg = f"Slowed slideshow to {new_rate_ms}ms"
            self.slideshow_manager.status_notification.show_message(msg)
        return True

    def _handle_key_2(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Speed up slideshow rate
        rate_ms = self.slideshow_manager.slideshow_rate
        if rate_ms <= 1000:
            rate_sec = rate_ms / 1000.0
            new_rate_sec = max(0.0, rate_sec - 0.125)
            new_rate_ms = int(round(new_rate_sec * 1000))
        else:
            # Step down by 1 second
            new_rate_ms = max(0, rate_ms - 1000)
        self.slideshow_manager.slideshow_rate = new_rate_ms
        self.slideshow_manager.slideshow_timer.setInterval(new_rate_ms)
        self.slideshow_manager.debounced_save_setting('slideshow_rate', new_rate_ms)
        if self.slideshow_manager.status_notification:
            sec = new_rate_ms / 1000.0
            if sec >= 1.0:
                msg = f"Sped up slideshow to {sec:.3g}s"
            else:
                msg = f"Sped up slideshow to {new_rate_ms}ms"
            self.slideshow_manager.status_notification.show_message(msg)
        return True

    def _handle_key_3(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # decrease transition speed
        self.slideshow_manager.slideshow_transition_speed = min(6000, self.slideshow_manager.slideshow_transition_speed + 100)
        self.slideshow_manager.debounced_save_setting('slideshow_transition_speed', self.slideshow_manager.slideshow_transition_speed)
        if self.slideshow_manager.status_notification:
            self.slideshow_manager.status_notification.show_message(f"Slowed transitions to {self.slideshow_manager.slideshow_transition_speed}ms")
        return True

    def _handle_key_4(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # increase transition speed
        self.slideshow_manager.slideshow_transition_speed = max(0, self.slideshow_manager.slideshow_transition_speed - 100)
        self.slideshow_manager.debounced_save_setting('slideshow_transition_speed', self.slideshow_manager.slideshow_transition_speed)
        if self.slideshow_manager.status_notification:
            self.slideshow_manager.status_notification.show_message(f"Sped up transitions to {self.slideshow_manager.slideshow_transition_speed}ms")
        return True

    def _handle_key_5(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # decrease max rotation
        self.slideshow_manager.slideshow_max_rotation = max(0, self.slideshow_manager.slideshow_max_rotation - 5)
        self.slideshow_manager.debounced_save_setting('slideshow_max_rotation', self.slideshow_manager.slideshow_max_rotation)
        if self.slideshow_manager.status_notification:
            self.slideshow_manager.status_notification.show_message(f"Max rotation: {self.slideshow_manager.slideshow_max_rotation}°")
        return True

    def _handle_key_6(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # increase max rotation
        self.slideshow_manager.slideshow_max_rotation = min(360, self.slideshow_manager.slideshow_max_rotation + 5)
        self.slideshow_manager.debounced_save_setting('slideshow_max_rotation', self.slideshow_manager.slideshow_max_rotation)
        if self.slideshow_manager.status_notification:
            self.slideshow_manager.status_notification.show_message(f"Max rotation: {self.slideshow_manager.slideshow_max_rotation}°")
        return True

    def _handle_key_7(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # decrease overlap
        self.slideshow_manager.decrease_slideshow_overlap()
        return True

    def _handle_key_8(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # increase overlap
        self.slideshow_manager.increase_slideshow_overlap()
        return True

    def _handle_key_0(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # reset to slow preset
        self.slideshow_manager.reset_to_slow_preset()
        return True

    def _handle_key_9(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # reset to fast preset
        self.slideshow_manager.reset_to_fast_preset()
        return True

    def _handle_up_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if self.slideshow_manager.slideshow_direction == 'top':
            self.slideshow_manager.advance_slideshow()
        else:
            self.slideshow_manager.slideshow_direction = 'top'
            self.slideshow_manager.debounced_save_setting('slideshow_direction', self.slideshow_manager.slideshow_direction)
            if self.slideshow_manager.status_notification:
                self.slideshow_manager.status_notification.show_message("Slideshow direction: From top")
        return True

    def _handle_down_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if self.slideshow_manager.slideshow_direction == 'bottom':
            self.slideshow_manager.advance_slideshow()
        else:
            self.slideshow_manager.slideshow_direction = 'bottom'
            self.slideshow_manager.debounced_save_setting('slideshow_direction', self.slideshow_manager.slideshow_direction)
            if self.slideshow_manager.status_notification:
                self.slideshow_manager.status_notification.show_message("Slideshow direction: From bottom")
        return True

    def _handle_left_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:                                       
        if self.slideshow_manager.slideshow_direction == 'left':
            self.slideshow_manager.advance_slideshow()
        else:
            self.slideshow_manager.slideshow_direction = 'left'
            self.slideshow_manager.debounced_save_setting('slideshow_direction', self.slideshow_manager.slideshow_direction)
            if self.slideshow_manager.status_notification:
                self.slideshow_manager.status_notification.show_message("Slideshow direction: From left")
        return True

    def _handle_right_arrow(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if self.slideshow_manager.slideshow_direction == 'right':
            self.slideshow_manager.advance_slideshow()
        else:
            self.slideshow_manager.slideshow_direction = 'right'
            self.slideshow_manager.debounced_save_setting('slideshow_direction', self.slideshow_manager.slideshow_direction)
            if self.slideshow_manager.status_notification:
                self.slideshow_manager.status_notification.show_message("Slideshow direction: From right")
        return True

    def _handle_shift_r(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        
        # Accept Shift+R key
        if event.nativeVirtualKey() == 15:  # R key (using native virtual key to be sure)
            self.slideshow_manager.slideshow_direction = 'random'
            self.slideshow_manager.debounced_save_setting('slideshow_direction', self.slideshow_manager.slideshow_direction)
            if self.slideshow_manager.status_notification:
                self.slideshow_manager.status_notification.show_message("Slideshow direction: Random")
            return True
        return False

    def _handle_c_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Set to a valid direction but with zero transition speed for no movement
        self.slideshow_manager.slideshow_direction = 'none'
        # self.slideshow_manager.slideshow_transition_speed = 0
        self.slideshow_manager.debounced_save_setting('slideshow_direction', self.slideshow_manager.slideshow_direction)
        # self.config.update_setting('slideshow_transition_speed', self.slideshow_manager.slideshow_transition_speed)
        if self.slideshow_manager.status_notification:
            self.slideshow_manager.status_notification.show_message("Slideshow direction: None (no transition)")
        return True

    def _handle_space(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow_manager.stop_slideshow()
        # Get actual index from highlight_index
        if hasattr(self.slideshow_manager, 'image_indices') and self.slideshow_manager.image_indices and 0 <= self.slideshow_manager.highlight_index < len(self.slideshow_manager.image_indices):
            actual_index = self.slideshow_manager.image_indices[self.slideshow_manager.highlight_index]
            self.slideshow_manager.open_browse_view(actual_index)
        else:
            self.slideshow_manager.open_browse_view(self.slideshow_manager.highlight_index)
        return True

    def _handle_shift_space(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow_manager.toggle_space_bar_behavior()
        return True

    def _handle_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow_manager.stop_slideshow()
        # Get actual index from highlight_index
        if hasattr(self.slideshow_manager, 'image_indices') and self.slideshow_manager.image_indices and 0 <= self.slideshow_manager.highlight_index < len(self.slideshow_manager.image_indices):
            actual_index = self.slideshow_manager.image_indices[self.slideshow_manager.highlight_index]
            self.slideshow_manager.open_browse_view(actual_index)
        else:
            self.slideshow_manager.open_browse_view(self.slideshow_manager.highlight_index)
        return True

    def _handle_f_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow_manager.stop_slideshow()
        # Get actual index from highlight_index
        if hasattr(self.slideshow_manager, 'image_indices') and self.slideshow_manager.image_indices and 0 <= self.slideshow_manager.highlight_index < len(self.slideshow_manager.image_indices):
            actual_index = self.slideshow_manager.image_indices[self.slideshow_manager.highlight_index]
            self.slideshow_manager.open_browse_view(actual_index)
        else:
            self.slideshow_manager.open_browse_view(self.slideshow_manager.highlight_index)
        return True

    def _handle_ctrl_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if hasattr(self.slideshow_manager, 'main_window') and self.slideshow_manager.main_window and hasattr(self.slideshow_manager.main_window, 'file_tree_handler'):
            self.slideshow_manager.main_window.file_tree_handler.collapse_file_tree()
        return True

    def _handle_ctrl_enter(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if hasattr(self.slideshow_manager, 'main_window') and hasattr(self.slideshow_manager.main_window, 'collapse_file_tree'):
            self.slideshow_manager.main_window.collapse_file_tree()
        return True


class Slideshow2KeyboardHandler(BaseKeyboardHandler):
    """Keyboard handler for slideshow2 mode."""

    def __init__(self, slideshow2_manager, parent=None):
        super().__init__(parent)
        self.slideshow2_manager = slideshow2_manager
        self._setup_key_bindings()

    def _setup_key_bindings(self):
        """Set up key bindings for slideshow2 mode."""
        CTRL = Qt.MetaModifier

        # Basic slideshow controls
        # S key is handled by menu system (Slideshow)
        self.add_key_binding("escape", KeyBinding(Qt.Key_Escape, description="Stop slideshow2"), self._handle_escape)

        # Zoom controls
        self.add_key_binding("minus", KeyBinding(Qt.Key_Minus, description="Zoom out"), self._handle_minus)
        self.add_key_binding("shift_minus", KeyBinding(Qt.Key_Minus, Qt.ShiftModifier, description="Zoom out"), self._handle_minus)
        self.add_key_binding("underscore", KeyBinding(Qt.Key_Underscore, description="Zoom out"), self._handle_underscore)
        self.add_key_binding("shift_underscore", KeyBinding(Qt.Key_Underscore, Qt.ShiftModifier, description="Zoom out"), self._handle_underscore)
        self.add_key_binding("plus", KeyBinding(Qt.Key_Plus, description="Zoom in"), self._handle_plus)
        self.add_key_binding("shift_plus", KeyBinding(Qt.Key_Plus, Qt.ShiftModifier, description="Zoom in"), self._handle_plus)
        self.add_key_binding("equal", KeyBinding(Qt.Key_Equal, description="Zoom in"), self._handle_equal)
        self.add_key_binding("shift_equal", KeyBinding(Qt.Key_Equal, Qt.ShiftModifier, description="Zoom in"), self._handle_equal)
        # Mac keyboard Control+W (Qt.MetaModifier): fit image width to canvas (pan continues)
        self.add_key_binding("ctrl_w_fit_canvas_width", KeyBinding(Qt.Key_W, CTRL, description="Fit image to canvas width (slideshow2)"), self._handle_ctrl_w_fit_canvas_width)

        # Speed controls
        self.add_key_binding("key_1", KeyBinding(Qt.Key_1, description="Slow down slideshow2"), self._handle_key_1)
        self.add_key_binding("shift_1", KeyBinding(Qt.Key_1, Qt.ShiftModifier, description="Slow down slideshow2 (large step)"), self._handle_shift_1)
        self.add_key_binding("key_2", KeyBinding(Qt.Key_2, description="Speed up slideshow2"), self._handle_key_2)
        self.add_key_binding("shift_2", KeyBinding(Qt.Key_2, Qt.ShiftModifier, description="Speed up slideshow2 (large step)"), self._handle_shift_2)

        # High-quality scaling
        self.add_key_binding("q_key", KeyBinding(Qt.Key_Q, description="Quality scaling toggle"), self._handle_q_key)

        # Navigation (Shift+Arrow)
        self.add_key_binding("shift_left", KeyBinding(Qt.Key_Left, Qt.ShiftModifier, description="Previous image"), self._handle_shift_left)
        self.add_key_binding("shift_right", KeyBinding(Qt.Key_Right, Qt.ShiftModifier, description="Next image"), self._handle_shift_right)
        self.add_key_binding("shift_up", KeyBinding(Qt.Key_Up, Qt.ShiftModifier, description="Previous image"), self._handle_shift_up)
        self.add_key_binding("shift_down", KeyBinding(Qt.Key_Down, Qt.ShiftModifier, description="Next image"), self._handle_shift_down)

        # Space and Enter for fullscreen
        self.add_key_binding("space", KeyBinding(Qt.Key_Space, description="Enter browse mode"), self._handle_space)
        self.add_key_binding("return", KeyBinding(Qt.Key_Return, description="Enter browse mode"), self._handle_return)
        # F key is handled by menu system shortcut (browse_view_action) which calls toggle_viewer()
        # F11 is handled by menu system (MacOS Fullscreen)
        # Ctrl+F is handled by menu system (Search by Description)

        # File tree
        self.add_key_binding("ctrl_return", KeyBinding(Qt.Key_Return, Qt.ControlModifier, description="Collapse file tree"), self._handle_ctrl_return)
        self.add_key_binding("ctrl_enter", KeyBinding(Qt.Key_Enter, Qt.ControlModifier, description="Collapse file tree"), self._handle_ctrl_enter)

        # Help and settings
        self.add_key_binding("question", KeyBinding(Qt.Key_Question, description="Show help"), self._handle_question)
        # F1 is handled by menu system
        self.add_key_binding("slash", KeyBinding(Qt.Key_Slash, description="Show help"), self._handle_question)

    def _handle_question(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow2_manager.window.show_help_test()
        return True

    def _handle_escape(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            # Explicitly accept the event before potentially blocking operations
            event.accept()
            self.slideshow2_manager.stop_slideshow2()
            return True
        return False

    def _handle_minus(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        new_enlargement = max(0.5, self.slideshow2_manager.slideshow2_enlargement - 0.2)
        self.slideshow2_manager.zoom_slideshow2_image(new_enlargement)
        return True

    def _handle_underscore(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        new_enlargement = max(0.5, self.slideshow2_manager.slideshow2_enlargement - 0.2)
        self.slideshow2_manager.zoom_slideshow2_image(new_enlargement)
        return True

    def _handle_plus(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        new_enlargement = min(3.0, self.slideshow2_manager.slideshow2_enlargement + 0.2)
        self.slideshow2_manager.zoom_slideshow2_image(new_enlargement)
        return True

    def _handle_equal(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        new_enlargement = min(3.0, self.slideshow2_manager.slideshow2_enlargement + 0.2)
        self.slideshow2_manager.zoom_slideshow2_image(new_enlargement)
        return True

    def _handle_ctrl_w_fit_canvas_width(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow2_manager.fit_slideshow2_image_to_canvas_width()
        event.accept()
        return True

    def _handle_key_1(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:        
        if not event.modifiers():
            self.slideshow2_manager.slideshow2_speed = max(1, self.slideshow2_manager.slideshow2_speed - 2)
            self.config.update_setting('slideshow2_speed', self.slideshow2_manager.slideshow2_speed)
            if self.slideshow2_manager.status_notification:
                self.slideshow2_manager.status_notification.show_message(f"Slideshow2 speed: {self.slideshow2_manager.slideshow2_speed}px/s")
            return True
        return False

    def _handle_shift_1(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow2_manager.slideshow2_speed = max(1, self.slideshow2_manager.slideshow2_speed - 100)
        self.config.update_setting('slideshow2_speed', self.slideshow2_manager.slideshow2_speed)
        if self.slideshow2_manager.status_notification:
            self.slideshow2_manager.status_notification.show_message(f"Slideshow2 speed: {self.slideshow2_manager.slideshow2_speed}px/s")
        return True

    def _handle_key_2(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            self.slideshow2_manager.slideshow2_speed = min(1860, self.slideshow2_manager.slideshow2_speed + 2)
            self.config.update_setting('slideshow2_speed', self.slideshow2_manager.slideshow2_speed)
            if self.slideshow2_manager.status_notification:
                self.slideshow2_manager.status_notification.show_message(f"Slideshow2 speed: {self.slideshow2_manager.slideshow2_speed}px/s")
            return True
        return False

    def _handle_shift_2(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow2_manager.slideshow2_speed = min(1860, self.slideshow2_manager.slideshow2_speed + 100)
        self.config.update_setting('slideshow2_speed', self.slideshow2_manager.slideshow2_speed)
        if self.slideshow2_manager.status_notification:
            self.slideshow2_manager.status_notification.show_message(f"Slideshow2 speed: {self.slideshow2_manager.slideshow2_speed}px/s")
        return True

    def _handle_q_key(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            self.slideshow2_manager.slideshow2_high_quality_scaling = not self.slideshow2_manager.slideshow2_high_quality_scaling
            self.config.update_setting('slideshow2_high_quality_scaling', self.slideshow2_manager.slideshow2_high_quality_scaling)
            if self.slideshow2_manager.status_notification:
                status = "enabled" if self.slideshow2_manager.slideshow2_high_quality_scaling else "disabled"
                self.slideshow2_manager.status_notification.show_message(f"High-quality scaling: {status}")
            # Re-apply current image with new scaling setting
            if self.slideshow2_manager.current_image_path:
                # Get actual index from highlight_index
                if hasattr(self.slideshow2_manager, 'image_indices') and self.slideshow2_manager.image_indices and 0 <= self.slideshow2_manager.highlight_index < len(self.slideshow2_manager.image_indices):
                    actual_index = self.slideshow2_manager.image_indices[self.slideshow2_manager.highlight_index]
                    self.slideshow2_manager.show_slideshow2_image(self.slideshow2_manager.current_image_path, actual_index)
                else:
                    self.slideshow2_manager.show_slideshow2_image(self.slideshow2_manager.current_image_path, self.slideshow2_manager.highlight_index)
            return True
        return False

    def _handle_shift_left(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        displayed = self.slideshow2_manager.get_displayed_images() or []
        if displayed:
            # Get current actual image index from highlight_index
            if hasattr(self.slideshow2_manager, 'image_indices') and self.slideshow2_manager.image_indices and 0 <= self.slideshow2_manager.highlight_index < len(self.slideshow2_manager.image_indices):
                current_actual = self.slideshow2_manager.image_indices[self.slideshow2_manager.highlight_index]
                next_actual = (current_actual - 1) % len(displayed)
                # Find thumbnail index for next image
                try:
                    new_highlight = self.slideshow2_manager.image_indices.index(next_actual)
                    self.slideshow2_manager.highlight_index = new_highlight
                except ValueError:
                    self.slideshow2_manager.highlight_index = next_actual
            else:
                # Fallback to direct mapping
                self.slideshow2_manager.highlight_index = (self.slideshow2_manager.highlight_index - 1) % len(displayed)

            # Show the previous image
            try:
                prev_path = displayed[next_actual]
                self.slideshow2_manager.show_slideshow2_image(prev_path, next_actual)
            except (IndexError, TypeError):
                pass
        return True

    def _handle_shift_right(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        displayed = self.slideshow2_manager.get_displayed_images() or []
        if displayed:
            # Get current actual image index from highlight_index
            if hasattr(self.slideshow2_manager, 'image_indices') and self.slideshow2_manager.image_indices and 0 <= self.slideshow2_manager.highlight_index < len(self.slideshow2_manager.image_indices):
                current_actual = self.slideshow2_manager.image_indices[self.slideshow2_manager.highlight_index]
                next_actual = (current_actual + 1) % len(displayed)
                # Find thumbnail index for next image
                try:
                    new_highlight = self.slideshow2_manager.image_indices.index(next_actual)
                    self.slideshow2_manager.highlight_index = new_highlight
                except ValueError:
                    self.slideshow2_manager.highlight_index = next_actual
            else:
                # Fallback to direct mapping
                self.slideshow2_manager.highlight_index = (self.slideshow2_manager.highlight_index + 1) % len(displayed)

            # Show the next image
            try:
                next_path = displayed[next_actual]
                self.slideshow2_manager.show_slideshow2_image(next_path, next_actual)
            except (IndexError, TypeError):
                pass
        return True

    def _handle_shift_up(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        return self._handle_shift_left(event, context_data)

    def _handle_shift_down(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        return self._handle_shift_right(event, context_data)

    def _handle_space(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            self.slideshow2_manager.stop_slideshow2(target_mode='browse')
            # Reset image label after stopping slideshow2 to ensure clean transition
            self.slideshow2_manager.reset_image_label_for_fullscreen()
            # Get actual index from highlight_index
            if hasattr(self.slideshow2_manager, 'image_indices') and self.slideshow2_manager.image_indices and 0 <= self.slideshow2_manager.highlight_index < len(self.slideshow2_manager.image_indices):
                actual_index = self.slideshow2_manager.image_indices[self.slideshow2_manager.highlight_index]
                self.slideshow2_manager.open_browse_view(actual_index)
            else:
                self.slideshow2_manager.open_browse_view(self.slideshow2_manager.highlight_index)
            return True
        return False

    def _handle_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            self.slideshow2_manager.stop_slideshow2(target_mode='browse')
            # Reset image label after stopping slideshow2 to ensure clean transition
            self.slideshow2_manager.reset_image_label_for_fullscreen()
            # Get actual index from highlight_index
            if hasattr(self.slideshow2_manager, 'image_indices') and self.slideshow2_manager.image_indices and 0 <= self.slideshow2_manager.highlight_index < len(self.slideshow2_manager.image_indices):
                actual_index = self.slideshow2_manager.image_indices[self.slideshow2_manager.highlight_index]
                self.slideshow2_manager.open_browse_view(actual_index)
            else:
                self.slideshow2_manager.open_browse_view(self.slideshow2_manager.highlight_index)
            return True
        return False


    def _handle_ctrl_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if hasattr(self.slideshow2_manager, 'main_window') and self.slideshow2_manager.main_window and hasattr(self.slideshow2_manager.main_window, 'file_tree_handler'):
            self.slideshow2_manager.main_window.file_tree_handler.collapse_file_tree()
        return True

    def _handle_ctrl_enter(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if hasattr(self.slideshow2_manager, 'main_window') and hasattr(self.slideshow2_manager.main_window, 'collapse_file_tree'):
            self.slideshow2_manager.main_window.collapse_file_tree()
        return True


class Slideshow3KeyboardHandler(BaseKeyboardHandler):
    """Keyboard handler for slideshow3 mode (Frames Slideshow)."""

    def __init__(self, slideshow3_manager, parent=None):
        super().__init__(parent)
        self.slideshow3_manager = slideshow3_manager
        self.config = get_config()
        self._setup_key_bindings()

    def _setup_key_bindings(self):
        """Set up key bindings for slideshow3 mode."""
        # Basic slideshow controls
        self.add_key_binding("escape", KeyBinding(Qt.Key_Escape, description="Stop slideshow3"), self._handle_escape)

        # Speed controls
        self.add_key_binding("key_1", KeyBinding(Qt.Key_1, description="Slower movement"), self._handle_key_1)
        self.add_key_binding("key_2", KeyBinding(Qt.Key_2, description="Faster movement"), self._handle_key_2)
        
        # Frame count controls (moved before frame size controls)
        self.add_key_binding("key_3", KeyBinding(Qt.Key_3, description="Fewer images"), self._handle_key_3)
        self.add_key_binding("key_4", KeyBinding(Qt.Key_4, description="More images"), self._handle_key_4)
        
        # Frame size controls (now after frame count controls)
        self.add_key_binding("key_5", KeyBinding(Qt.Key_5, description="Smaller average image size"), self._handle_key_5)
        self.add_key_binding("key_6", KeyBinding(Qt.Key_6, description="Larger average image size"), self._handle_key_6)
        
        # Preset controls
        self.add_key_binding("key_9", KeyBinding(Qt.Key_9, description="Small slow images preset"), self._handle_key_9)
        self.add_key_binding("key_0", KeyBinding(Qt.Key_0, description="Larger slow images preset"), self._handle_key_0)

        # Space and Enter for browse mode
        self.add_key_binding("space", KeyBinding(Qt.Key_Space, description="Enter browse mode"), self._handle_space)
        self.add_key_binding("return", KeyBinding(Qt.Key_Return, description="Enter browse mode"), self._handle_return)
        # F key is handled by menu system shortcut (browse_view_action) which calls toggle_viewer()

        # File tree
        self.add_key_binding("ctrl_return", KeyBinding(Qt.Key_Return, Qt.ControlModifier, description="Collapse file tree"), self._handle_ctrl_return)
        self.add_key_binding("ctrl_enter", KeyBinding(Qt.Key_Enter, Qt.ControlModifier, description="Collapse file tree"), self._handle_ctrl_enter)

        # Help and settings
        self.add_key_binding("f1", KeyBinding(Qt.Key_F1, description="Show help"), self._handle_question)
        self.add_key_binding("question", KeyBinding(Qt.Key_Question, description="Show help"), self._handle_question)
        self.add_key_binding("slash", KeyBinding(Qt.Key_Slash, description="Show help"), self._handle_question)

    def _handle_question(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        self.slideshow3_manager.window.show_help_test()
        return True

    def _handle_escape(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            # Explicitly accept the event before potentially blocking operations
            event.accept()
            self.slideshow3_manager.stop_slideshow3()
            return True
        return False

    def _handle_space(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            # Explicitly accept the event before potentially blocking operations
            event.accept()
            # Stop slideshow3 and exit to thumbnail mode (same as Esc)
            self.slideshow3_manager.stop_slideshow3()
            return True
        return False

    def _handle_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            # Explicitly accept the event before potentially blocking operations
            event.accept()
            # Stop slideshow3 and exit to thumbnail mode (same as Esc)
            self.slideshow3_manager.stop_slideshow3()
            return True
        return False

    def _handle_ctrl_return(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if hasattr(self.slideshow3_manager, 'main_window') and self.slideshow3_manager.main_window and hasattr(self.slideshow3_manager.main_window, 'file_tree_handler'):
            self.slideshow3_manager.main_window.file_tree_handler.collapse_file_tree()
        return True

    def _handle_ctrl_enter(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if hasattr(self.slideshow3_manager, 'main_window') and hasattr(self.slideshow3_manager.main_window, 'collapse_file_tree'):
            self.slideshow3_manager.main_window.collapse_file_tree()
        return True

    def _handle_key_1(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Slow down movement (increase duration range)"""
        if not event.modifiers():
            # Increase both min and max by 1 second
            self.slideshow3_manager.speed_min_seconds = min(44, self.slideshow3_manager.speed_min_seconds + 1.0)
            self.slideshow3_manager.speed_max_seconds = min(45, self.slideshow3_manager.speed_min_seconds + 6.0)
            self.slideshow3_manager.config.update_setting('slideshow3_speed_min_seconds', self.slideshow3_manager.speed_min_seconds)
            self.slideshow3_manager.config.update_setting('slideshow3_speed_max_seconds', self.slideshow3_manager.speed_max_seconds)
            if self.slideshow3_manager.status_notification:
                self.slideshow3_manager.status_notification.show_message(
                    f"Slower: {self.slideshow3_manager.speed_min_seconds:.1f}-{self.slideshow3_manager.speed_max_seconds:.1f}s"
                )
            return True
        return False

    def _handle_key_2(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Speed up movement (decrease duration range)"""
        if not event.modifiers():
            # Decrease both min and max by 1 second (but keep min >= 3)
            self.slideshow3_manager.speed_min_seconds = max(1, self.slideshow3_manager.speed_min_seconds - 1.0)
            self.slideshow3_manager.speed_max_seconds = max(self.slideshow3_manager.speed_min_seconds + 6, self.slideshow3_manager.speed_max_seconds - 1.0)
            self.slideshow3_manager.config.update_setting('slideshow3_speed_min_seconds', self.slideshow3_manager.speed_min_seconds)
            self.slideshow3_manager.config.update_setting('slideshow3_speed_max_seconds', self.slideshow3_manager.speed_max_seconds)
            if self.slideshow3_manager.status_notification:
                self.slideshow3_manager.status_notification.show_message(
                    f"Faster: {self.slideshow3_manager.speed_min_seconds:.1f}-{self.slideshow3_manager.speed_max_seconds:.1f}s"
                )
            return True
        return False

    _FRAME_SIZE_RANGES = [
        (5, 10),
        (10, 20),
        (10, 30),
        (10, 40),
        (10, 50),
        (20, 60),
        (30, 70),
        (40, 80),
        (50, 80),
        (60, 80),
        (70, 80),
        (90, 100),
        (100, 110),
        (110, 200),
        (300, 400)
    ]

    def _get_current_frame_size_index(self):
        current = (self.slideshow3_manager.frame_size_min_percent, self.slideshow3_manager.frame_size_max_percent)
        # Find exact match
        try:
            return self._FRAME_SIZE_RANGES.index(current)
        except ValueError:
            # Otherwise, find the closest match by min_percent
            min_percent = self.slideshow3_manager.frame_size_min_percent
            max_percent = self.slideshow3_manager.frame_size_max_percent
            # Find candidate by comparing both min and max
            candidates = [
                (i, abs(min_percent - mn) + abs(max_percent - mx))
                for i, (mn, mx) in enumerate(self._FRAME_SIZE_RANGES)
            ]
            if not candidates:
                return 0
            # Return the index of the minimum distance
            return min(candidates, key=lambda t: t[1])[0]

    def _handle_key_3(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Decrease maximum simultaneous frames (fewer images)"""
        if not event.modifiers():
            # Ensure the value is within bounds before and after adjustment
            current_max = self.slideshow3_manager.max_simultaneous_frames
            # Clamp value before decrement to avoid underflow from accidental large values
            current_max = max(1, min(30, current_max))
            new_max = max(1, current_max - 1)
            self.slideshow3_manager.max_simultaneous_frames = new_max
            self.slideshow3_manager.config.update_setting('slideshow3_max_simultaneous_frames', new_max)

            # Enforce immediately by removing excess frames
            if hasattr(self.slideshow3_manager, '_enforce_max_frames'):
                self.slideshow3_manager._enforce_max_frames()

            if self.slideshow3_manager.status_notification:
                self.slideshow3_manager.status_notification.show_message(
                    f"Fewer images: max {self.slideshow3_manager.max_simultaneous_frames} frames"
                )
            return True
        return False

    def _handle_key_4(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Increase maximum simultaneous frames (more images)"""
        if not event.modifiers():
            current_max = self.slideshow3_manager.max_simultaneous_frames
            # Clamp value before increment to avoid overflow from accidental large values
            current_max = max(1, min(30, current_max))
            new_max = min(30, current_max + 1)
            self.slideshow3_manager.max_simultaneous_frames = new_max
            self.slideshow3_manager.config.update_setting('slideshow3_max_simultaneous_frames', new_max)

            if self.slideshow3_manager.status_notification:
                self.slideshow3_manager.status_notification.show_message(
                    f"More images: max {self.slideshow3_manager.max_simultaneous_frames} frames"
                )
            return True
        return False

    def _handle_key_5(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Decrease average frame size"""
        if not event.modifiers():
            idx = self._get_current_frame_size_index()
            if idx > 0:
                idx -= 1
                min_percent, max_percent = self._FRAME_SIZE_RANGES[idx]
                self.slideshow3_manager.frame_size_min_percent = min_percent
                self.slideshow3_manager.frame_size_max_percent = max_percent
                self.slideshow3_manager.config.update_setting('slideshow3_frame_size_min_percent', min_percent)
                self.slideshow3_manager.config.update_setting('slideshow3_frame_size_max_percent', max_percent)
                if self.slideshow3_manager.status_notification:
                    self.slideshow3_manager.status_notification.show_message(
                        f"Smaller frames: {min_percent}-{max_percent}%"
                    )
            else:
                # Already at minimum, just show message
                min_percent, max_percent = self._FRAME_SIZE_RANGES[0]
                if self.slideshow3_manager.status_notification:
                    self.slideshow3_manager.status_notification.show_message(
                        f"Smaller frames: {min_percent}-{max_percent}% (min)"
                    )
            return True
        return False

    def _handle_key_6(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Increase average frame size"""
        if not event.modifiers():
            idx = self._get_current_frame_size_index()
            if idx < len(self._FRAME_SIZE_RANGES) - 1:
                idx += 1
                min_percent, max_percent = self._FRAME_SIZE_RANGES[idx]
                self.slideshow3_manager.frame_size_min_percent = min_percent
                self.slideshow3_manager.frame_size_max_percent = max_percent
                self.slideshow3_manager.config.update_setting('slideshow3_frame_size_min_percent', min_percent)
                self.slideshow3_manager.config.update_setting('slideshow3_frame_size_max_percent', max_percent)
                if self.slideshow3_manager.status_notification:
                    self.slideshow3_manager.status_notification.show_message(
                        f"Larger frames: {min_percent}-{max_percent}%"
                    )
            else:
                # Already at maximum
                min_percent, max_percent = self._FRAME_SIZE_RANGES[-1]
                if self.slideshow3_manager.status_notification:
                    self.slideshow3_manager.status_notification.show_message(
                        f"Larger frames: {min_percent}-{max_percent}% (max)"
                    )
            return True
        return False

    def _handle_key_9(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Preset: Small slow images"""
        if not event.modifiers():
            # Small frames (5-15%), slow movement (12-18 seconds)
            self.slideshow3_manager.frame_size_min_percent = 5
            self.slideshow3_manager.frame_size_max_percent = 15
            self.slideshow3_manager.speed_min_seconds = 12
            self.slideshow3_manager.speed_max_seconds = 18
            self.slideshow3_manager.config.update_setting('slideshow3_frame_size_min_percent', self.slideshow3_manager.frame_size_min_percent)
            self.slideshow3_manager.config.update_setting('slideshow3_frame_size_max_percent', self.slideshow3_manager.frame_size_max_percent)
            self.slideshow3_manager.config.update_setting('slideshow3_speed_min_seconds', self.slideshow3_manager.speed_min_seconds)
            self.slideshow3_manager.config.update_setting('slideshow3_speed_max_seconds', self.slideshow3_manager.speed_max_seconds)
            if self.slideshow3_manager.status_notification:
                self.slideshow3_manager.status_notification.show_message(
                    f"Preset 9: Small slow ({self.slideshow3_manager.frame_size_min_percent}-{self.slideshow3_manager.frame_size_max_percent}%, {self.slideshow3_manager.speed_min_seconds}-{self.slideshow3_manager.speed_max_seconds}s)"
                )
            return True
        return False

    def _handle_key_0(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        """Preset: Larger slow images"""
        if not event.modifiers():
            # Larger frames (20-35%), slow movement (12-18 seconds)
            self.slideshow3_manager.frame_size_min_percent = 20
            self.slideshow3_manager.frame_size_max_percent = 35
            self.slideshow3_manager.speed_min_seconds = 12
            self.slideshow3_manager.speed_max_seconds = 18
            self.slideshow3_manager.config.update_setting('slideshow3_frame_size_min_percent', self.slideshow3_manager.frame_size_min_percent)
            self.slideshow3_manager.config.update_setting('slideshow3_frame_size_max_percent', self.slideshow3_manager.frame_size_max_percent)
            self.slideshow3_manager.config.update_setting('slideshow3_speed_min_seconds', self.slideshow3_manager.speed_min_seconds)
            self.slideshow3_manager.config.update_setting('slideshow3_speed_max_seconds', self.slideshow3_manager.speed_max_seconds)
            if self.slideshow3_manager.status_notification:
                self.slideshow3_manager.status_notification.show_message(
                    f"Preset 0: Larger slow ({self.slideshow3_manager.frame_size_min_percent}-{self.slideshow3_manager.frame_size_max_percent}%, {self.slideshow3_manager.speed_min_seconds}-{self.slideshow3_manager.speed_max_seconds}s)"
                )
            return True
        return False


class HelpKeyboardHandler(BaseKeyboardHandler):
    """Keyboard handler for help dialog."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._setup_key_bindings()

    def _setup_key_bindings(self):
        self.add_key_binding("escape", KeyBinding(Qt.Key_Escape, description="Close help"), self._close_help)
        self.add_key_binding("return", KeyBinding(Qt.Key_Return, description="Close help"), self._close_help)
        self.add_key_binding("enter", KeyBinding(Qt.Key_Enter, description="Close help"), self._close_help)
        self.add_key_binding("question", KeyBinding(Qt.Key_Question, description="Close help"), self._close_help)
        self.add_key_binding("slash", KeyBinding(Qt.Key_Slash, description="Close help"), self._close_help)
        # F1 is handled by menu system

    def _close_help(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        if not event.modifiers():
            self.main_window.help_dialog.hide()
            return True
        return False

# FileTreeKeyboardHandler removed - tree widget handles its own keyboard events natively


class ThumbnailCanvasKeyboardHandler(BaseKeyboardHandler):
    """Keyboard handler for thumbnail canvas."""

    def __init__(self, thumbnail_canvas, parent=None):
        super().__init__(parent)
        self.thumbnail_canvas = thumbnail_canvas
        self._setup_key_bindings()

    def _setup_key_bindings(self):
        """Set up key bindings for thumbnail canvas."""
        # Delegate most keys to main window, but handle some canvas-specific ones
        self.add_key_binding("tab", KeyBinding(Qt.Key_Tab, description="Focus navigation"), self._handle_tab)

    def _handle_tab(self, event: QKeyEvent, context_data: Dict[str, Any]) -> bool:
        # Let Qt handle tab navigation
        event.ignore()
        return False

    def handle_key_event(self, event: QKeyEvent, context_data: Dict[str, Any] = None) -> bool:
        """
        Handle key event for thumbnail canvas.
        Most keys are delegated to the main window.
        """
        if context_data is None:
            context_data = {}

        # For most keys, delegate to main window
        if hasattr(self.thumbnail_canvas, 'main_window') and self.thumbnail_canvas.main_window:
            return self.thumbnail_canvas.main_window.keyPressEvent(event)

        return False


class KeyboardHandlerManager:
    """Central manager for all keyboard handlers."""

    def __init__(self, main_window, parent=None):
        self.main_window = main_window
        self.handlers = {}
        self.current_handler = None
        self._initialize_handlers()

    def _initialize_handlers(self):
        """Initialize all keyboard handlers."""
        # Create handlers for different view modes
        self.handlers['thumbnail'] = ThumbnailKeyboardHandler(self.main_window, self.main_window)
        self.handlers['browse'] = BrowseViewKeyboardHandler(self.main_window, self.main_window)
        self.handlers['help'] = HelpKeyboardHandler(self.main_window, self.main_window)
        self.handlers['canvas'] = ThumbnailCanvasKeyboardHandler(self.main_window.thumbnail_canvas if hasattr(self.main_window, 'thumbnail_canvas') else None, self.main_window)

        # Create handlers for slideshow managers (these will be set later when managers are available)
        self.handlers['slideshow'] = SlideshowKeyboardHandler(self.main_window.slideshow_manager, self.main_window)
        self.handlers['slideshow2'] = Slideshow2KeyboardHandler(self.main_window.slideshow2_manager, self.main_window)
        self.handlers['slideshow3'] = Slideshow3KeyboardHandler(self.main_window.slideshow3_manager, self.main_window)
        self.handlers['file_tree'] = None
        

    def set_slideshow_handler(self, slideshow_manager):
        """Set the slideshow keyboard handler."""
        self.handlers['slideshow'] = SlideshowKeyboardHandler(slideshow_manager, self.main_window)

    def set_slideshow2_handler(self, slideshow2_manager):
        """Set the slideshow2 keyboard handler."""
        self.handlers['slideshow2'] = Slideshow2KeyboardHandler(slideshow2_manager, self.main_window)
    
    def set_slideshow3_handler(self, slideshow3_manager):
        """Set the slideshow3 keyboard handler."""
        self.handlers['slideshow3'] = Slideshow3KeyboardHandler(slideshow3_manager, self.main_window)

    # File tree handler removed - tree widget handles its own keyboard events natively

    def handle_key_event(self, event: QKeyEvent, mode: str = None, context_data: Dict[str, Any] = None) -> bool:
        """
        Handle a key event using the appropriate handler.

        Args:
            event: The key event to handle
            mode: The current view mode ('thumbnail', 'browse', 'slideshow', etc.)
            context_data: Additional context data

        Returns:
            bool: True if the event was handled
        """
        
        if context_data is None:
            context_data = {}

        # Ensure Cmd+Z (ControlModifier + Z on macOS) passes through to menu action
        # Don't intercept undo shortcut
        if event.key() == Qt.Key_Z and (event.modifiers() & Qt.ControlModifier):
            return False  # Let menu action handle it

        # Cmd+J (Ctrl+J in QAction) — job queue; do not treat as plain J
        if event.key() == Qt.Key_J:
            event_mods = event.modifiers() & ~Qt.KeypadModifier
            cmd_pressed = bool(
                event_mods & (Qt.ControlModifier | Qt.MetaModifier)
            )
            other_mods = event_mods & ~(
                Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier | Qt.AltModifier
            )
            if cmd_pressed and (
                other_mods == Qt.NoModifier or other_mods == 0
            ):
                return False

        # Determine which handler to use
        if mode is None:
            mode = self._determine_current_mode()


        handler = self.handlers.get(mode)
        if handler:
            result = handler.handle_key_event(event, context_data)
            if result:
                return True
            else:
                return False
        return False

    def _determine_current_mode(self) -> str:
        """Determine the current view mode based on application state."""
        
        # Check for help dialog first
        if hasattr(self.main_window, 'help_dialog') and self.main_window.help_dialog and self.main_window.help_dialog.isVisible():
            return 'help'

        # Check current view mode, but also verify with stacked widget index for reliability
        if hasattr(self.main_window, 'current_view_mode'):
            mode = self.main_window.current_view_mode

            # If mode is browse but stacked widget is at index 0 (thumbnail view), override
            if hasattr(self.main_window, 'stacked_widget') and mode == 'browse':
                current_index = self.main_window.stacked_widget.currentIndex()
                if current_index == 0:  # Thumbnail view
                    return 'thumbnail'

            if mode in ('browse', 'slideshow', 'slideshow2', 'slideshow3'):
                return mode

        # Default to thumbnail view
        return 'thumbnail'

    def get_key_bindings_help(self, mode: str = None) -> Dict[str, str]:
        """Get help text for key bindings in the specified mode."""
        if mode is None:
            mode = self._determine_current_mode()

        handler = self.handlers.get(mode)
        if handler:
            return handler.get_key_bindings_help()

        return {}
    
    def refresh_favorite_bindings(self):
        """Refresh favorite key binding descriptions in all handlers."""
        for handler in self.handlers.values():
            if handler and hasattr(handler, 'refresh_favorite_bindings'):
                handler.refresh_favorite_bindings()

