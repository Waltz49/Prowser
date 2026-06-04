
#!/usr/bin/env python3
"""
Optimized File Tree Handler for Image Browser
Manages the file system tree view and keeps it synchronized with the main image browser
"""

# TODOs:
# - ensure that listeners are added to file during expansion because automatically opened
#   directories don't seem to manage things like automatic opening of files and that is probably
#   because the tree is adding nodes that dont respond to an on_selection_changed callback
#

# Mounted file systems are not visible in the tree.  Fix. (Done below, macOS-specific. See QFileSystemModel settings.)

import hashlib
import os
import traceback
import subprocess
import shutil
import fnmatch
from pathlib import Path
from typing import Optional, Callable, List, Any, Set, Dict, Union, Tuple
from PySide6.QtCore import (QDir, QEventLoop, QTimer, QItemSelectionModel, Qt, QModelIndex, QSortFilterProxyModel, QSize, QObject, QEvent, QPoint, QMutexLocker
)

from config import get_config, ImageBrowserConfig
from status_bar_config import StatusBarManager
from file_move_handler import FileMoveHandler
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeView, QFileSystemModel,
    QHeaderView, QPushButton, QLabel, QMessageBox, QStyleOptionViewItem,
    QStyledItemDelegate, QStyle, QApplication, QDialog, QButtonGroup, QFrame, QMenu, QLineEdit
)
from PySide6.QtGui import (QPainter, QPen, QFont, QColor, QPalette, QKeyEvent, QMouseEvent, QIcon, QPixmap,
    QDragEnterEvent, QDragMoveEvent, QDropEvent, QBrush, QPainterPath, QAction
)

from thumbnail_constants import (get_image_extensions, EXCLUDED_EXTENSIONS, SKIPPED_PATTERNS, MIN_THUMBNAIL_SIZE,
    TREE_UPDATE_DEBOUNCE_TIMER, TREE_FOLDER_WITH_IMAGES_COLOR, TEXT_COLOR, TEXT_COLOR_HEX,
    TREE_DRAG_AUTO_SCROLL_SPEEDS, TREE_DRAG_AUTO_SCROLL_TIMER_MS, asset_path,
)
import thumbnail_constants as tc
from path_exclusions import _get_excluded_paths, _is_excluded_path, prune_walk_dirs
from theme_service import get_active_theme
from utils import (
    entry_debug,
    file_string,
    get_file_extension,
    handle_filter_pattern_mismatch,
    is_inside_photos_library_resources_or_scopes,
    is_root_or_system_volume,
    normalize_path_for_display,
    show_styled_critical,
    show_styled_information,
    show_styled_warning,
)


def get_enabled_root_directories() -> Set[str]:
    """Get the enabled root directories from config"""
    try:
        config = get_config()
        settings = config.load_settings()
        enabled = settings.get('root_directories', ['/Users', '/Volumes', '/tmp'])
        # Ensure it's a list and convert to set
        if not isinstance(enabled, list):
            enabled = ['/Users', '/Volumes', '/tmp']
        # Normalize: ensure all directories have leading slashes (for backward compatibility)
        normalized = []
        for dir_path in enabled:
            if dir_path.startswith('/'):
                normalized.append(dir_path)
            else:
                normalized.append(f"/{dir_path}")
        return set(normalized)
    except Exception:
        # Fallback to defaults
        return {'/Users', '/Volumes', '/tmp'}

def get_show_hidden_directories() -> bool:
    """Get the show hidden directories setting from config"""
    try:
        config = get_config()
        settings = config.load_settings()
        return settings.get('show_hidden_directories', False)
    except Exception:
        # Fallback to default (False)
        return False

def get_always_show_work() -> bool:
    """Get the always show 'work' directories setting from config"""
    try:
        config = get_config()
        settings = config.load_settings()
        return settings.get('always_show_work', False)
    except Exception:
        # Fallback to default (False)
        return False


def get_follow_symlinks() -> bool:
    """Get the follow symlinks setting from config"""
    try:
        config = get_config()
        settings = config.load_settings()
        return settings.get('follow_symlinks', False)
    except Exception:
        # Fallback to default (False)
        return False


def is_enabled_root_symlink(path: str, enabled_root_dirs: Optional[Set[str]] = None) -> bool:
    """True if path is a symlink listed on the Directories tab (root_directories)."""
    normalized = os.path.normpath(path)
    if not os.path.islink(normalized):
        return False
    if enabled_root_dirs is None:
        enabled_root_dirs = get_enabled_root_directories()
    return normalized in enabled_root_dirs


def filter_walk_symlink_dirs(
    root: str,
    dirs: List[str],
    follow_symlinks: bool,
    enabled_root_dirs: Optional[Set[str]] = None,
) -> None:
    """In-place filter of dirs during os.walk; keeps enabled root symlinks when follow_symlinks is False."""
    if follow_symlinks:
        return
    if enabled_root_dirs is None:
        enabled_root_dirs = get_enabled_root_directories()
    dirs[:] = [
        d for d in dirs
        if not os.path.islink(os.path.join(root, d))
        or os.path.normpath(os.path.join(root, d)) in enabled_root_dirs
    ]

# --- CustomTreeView: optimized for clarity and performance ---


class CustomTreeView(QTreeView):
    """Custom QTreeView with manual tree line drawing and optimized key handling."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.main_window: Optional[Any] = None
        # Enable drag and drop
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeView.DragDropMode.DropOnly)
        self._drop_target_directory: Optional[str] = None
        self.highlighted_index: Optional[QModelIndex] = None
        # Store last drop location for "Move to last drop location" feature
        self._last_drop_location: Optional[str] = None
        # Will be initialized when main_window is set
        self.file_move_handler: Optional[FileMoveHandler] = None
        # Initialize timer for delayed single-click handling
        self._single_click_timer = QTimer()
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(self._handle_delayed_single_click)
        self._pending_click_path: Optional[str] = None
        self._pending_click_index: Optional[QModelIndex] = None
        self._rename_editor: Optional[QLineEdit] = None
        self._editing_directory_path: Optional[str] = None

        # Auto-scroll during drag (narrow band, slow speeds)
        self._auto_scroll_timer = QTimer()
        self._auto_scroll_timer.timeout.connect(self._handle_drag_auto_scroll)
        self._auto_scroll_direction = 0  # -1 for up, 1 for down, 0 for none
        self._auto_scroll_speed = 0.0  # Percentage of viewport height per second
        self._scroll_accumulator = 0.0  # Fractional pixels for sub-pixel speeds

    def set_main_window(self, main_window: Any) -> None:
        self.main_window = main_window
        # Initialize file move handler with main window as parent
        self.file_move_handler = FileMoveHandler(main_window)

    def get_last_drop_location(self) -> Optional[str]:
        """Get the last drop location, or None if no drop has occurred"""
        return self._last_drop_location

    def drawRow(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().drawRow(painter, option, index)

    def _get_keys_handled_locally(self) -> Set[int]:
        """
        Returns the set of keys that should be handled locally by the tree view.
        All other keys will be forwarded to the main window's keyboard handler.

        To limit which keys are passed through, add keys to this set.
        To pass through more keys, remove keys from this set.
        """
        return {
            Qt.Key_Return,
            Qt.Key_Enter,
            Qt.Key_Up,
            Qt.Key_Down,
            Qt.Key_Left,
            Qt.Key_Right,
            Qt.Key_PageUp,
            Qt.Key_PageDown,
        }

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key, modifiers = event.key(), event.modifiers()

        # Debug cmd-shift-return
        if key in [Qt.Key_Return, Qt.Key_Enter]:
            cmd_shift = (modifiers & Qt.ShiftModifier) and (modifiers & (Qt.ControlModifier | Qt.MetaModifier))

        # Handle Tab key navigation {{ TABS DO NOT MAKE IT TO HERE }}
        # if key == Qt.Key_Tab:
        #     # Move focus to next widget in tab order
        #     self.focusNextChild()
        #     event.accept()
        #     return

        # Get the set of keys that should be handled locally
        keys_handled_locally = self._get_keys_handled_locally()

        # Handle cmd-P (search by person) and cmd-= (scan for faces) when tree has focus
        # Both must start with the directory represented by the highlighted tree node
        cmd_mod = modifiers & (Qt.ControlModifier | Qt.MetaModifier)
        if cmd_mod and not (modifiers & Qt.ShiftModifier) and not (modifiers & Qt.AltModifier):
            tree_dir = None
            selection = self.selectionModel().selectedIndexes()
            if selection:
                index = selection[0]
                model = self.model()
                if model:
                    source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                    selected_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                    if selected_path:
                        tree_dir = selected_path if os.path.isdir(selected_path) else os.path.dirname(selected_path)
            if key == Qt.Key_P and self.main_window:
                if tree_dir and os.path.isdir(tree_dir):
                    if is_root_or_system_volume(tree_dir):
                        if tree_dir == '/':
                            show_styled_warning(self.main_window, "Action Not Available",
                                                "This action is not available on the root directory.")
                        else:
                            show_styled_warning(self.main_window, "Action Not Available",
                                                "This action is not available on system volumes.")
                    else:
                        self.main_window.show_filter_by_person_dialog(directory_override=tree_dir)
                else:
                    self.main_window._tree_had_focus_when_invoked = True
                    try:
                        self.main_window.show_filter_by_person_dialog()
                    finally:
                        self.main_window._tree_had_focus_when_invoked = False
                event.accept()
                return
            if key == Qt.Key_Equal and self.main_window:
                # Pass tree_dir so cmd-= uses same directory as cmd-P when tree has focus
                dir_to_scan = tree_dir if tree_dir and os.path.isdir(tree_dir) else None
                self.main_window._tree_had_focus_when_invoked = True
                try:
                    self.main_window.scan_for_faces(directory_override=dir_to_scan)
                finally:
                    self.main_window._tree_had_focus_when_invoked = False
                event.accept()
                return

        # Handle F2: initiate rename for highlighted directory (when tree has focus)
        if key == Qt.Key_F2 and not modifiers:
            index = self.currentIndex()
            if index.isValid():
                model = self.model()
                if model:
                    source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                    file_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                    if os.path.isdir(file_path) and self._can_rename_directory(file_path):
                        self._handle_rename(index, file_path)
            event.accept()
            return

        # Handle shift-A: show all images including subdirectories
        if key == Qt.Key_A and modifiers == Qt.ShiftModifier:
            selection = self.selectionModel().selectedIndexes()
            if selection:
                index = selection[0]
                model = self.model()
                if model:
                    source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                    file_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                    if os.path.isdir(file_path):
                        # Check if directory is root or system volume (disable recursive actions)
                        if not is_root_or_system_volume(file_path):
                            self._handle_all_images(file_path)
            event.accept()
            return

        # Handle cmd-shift-return: expand file tree
        # On macOS, Command key is Qt.ControlModifier, but check both for compatibility
        cmd_shift = (modifiers & Qt.ShiftModifier) and (modifiers & (Qt.ControlModifier | Qt.MetaModifier))
        if key in [Qt.Key_Return, Qt.Key_Enter] and cmd_shift:
            if self.main_window and hasattr(self.main_window, 'file_tree_handler'):
                self.main_window.file_tree_handler.expand_file_tree()
            event.accept()
            return
        # Handle cmd-return: collapse file tree
        # On macOS, Command key is Qt.ControlModifier, but check both for compatibility
        cmd_only = modifiers & (Qt.ControlModifier | Qt.MetaModifier)
        if key in [Qt.Key_Return, Qt.Key_Enter] and cmd_only and not (modifiers & Qt.ShiftModifier):
            if self.main_window and hasattr(self.main_window, 'file_tree_handler'):
                self.main_window.file_tree_handler.collapse_file_tree()
            event.accept()
            return
        if key in [Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space] and not modifiers:
            selection = self.selectionModel().selectedIndexes()
            if selection:
                index = selection[0]
                model = self.model()
                if model:
                    source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                    file_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                    if os.path.isdir(file_path):
                        if self.isExpanded(index):
                            self.collapse(index)
                        else:
                            self.expand(index)
                            if self.main_window and hasattr(self.main_window, 'file_tree_handler'):
                                # DON'T set current_highlighted_directory here - let request_directory_opening handle it
                                # Setting it here causes a race condition where the tree selection doesn't match
                                self.main_window.file_tree_handler.request_directory_opening(file_path)
            event.accept()
            return

        # If key is in the "handle locally" set, let the tree view handle it
        if key in keys_handled_locally:
            super().keyPressEvent(event)
            return

        # For all other keys, forward to main window's keyboard handler
        # This allows actions like E (go to end), H (home), etc. to work when tree has focus
        if (self.main_window and
            hasattr(self.main_window, 'keyboard_handler_manager') and
                self.main_window.keyboard_handler_manager):
            result = self.main_window.keyboard_handler_manager.handle_key_event(event)
            if result:
                event.accept()
                return

        # Fallback: let parent handle it
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press events - single click expands/collapses directories and selects items."""
        # Cancel any pending single-click timer
        if self._single_click_timer:
            self._single_click_timer.stop()
        self._pending_click_path = None
        self._pending_click_index = None

        # Handle single click on directories to expand/collapse (delayed to allow double-click detection)
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                model = self.model()
                if model:
                    source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                    file_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""

                    # If clicking on a directory, delay expand/collapse to allow double-click detection
                    if os.path.isdir(file_path) and model.hasChildren(index):
                        # Store the click info for delayed handling
                        self._pending_click_path = file_path
                        self._pending_click_index = index
                        # Use system double-click interval to delay single-click action
                        app = QApplication.instance()
                        interval = app.doubleClickInterval() if app else 400
                        self._single_click_timer.start(interval)
                        # Still allow selection to occur immediately
                        super().mousePressEvent(event)
                        return

        # For non-directories or other cases, use default behavior
        super().mousePressEvent(event)

    def _handle_delayed_single_click(self) -> None:
        """Handle delayed single-click action (expand/collapse directory) after double-click interval."""
        if self._pending_click_path and self._pending_click_index:
            index = self._pending_click_index
            # Verify index is still valid
            if index.isValid():
                if self.isExpanded(index):
                    self.collapse(index)
                else:
                    self.expand(index)
        self._pending_click_path = None
        self._pending_click_index = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Handle mouse double-click events - populate thumbnail view for directories."""
        # Cancel pending single-click action to prevent expand/collapse from firing
        if self._single_click_timer:
            self._single_click_timer.stop()
        self._pending_click_path = None
        self._pending_click_index = None

        # Check if this is a left mouse button double-click
        if event.button() == Qt.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                model = self.model()
                if model:
                    source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                    file_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""

                    # Handle directories - populate thumbnail view
                    if os.path.isdir(file_path):
                        if self.main_window and hasattr(self.main_window, 'file_tree_handler'):
                            self.main_window.file_tree_handler.request_directory_opening(file_path)
                        event.accept()
                        return

        # Call parent for default behavior if not handled
        super().mouseDoubleClickEvent(event)

    def _can_rename_directory(self, directory_path: str) -> bool:
        """Check if directory can be renamed using Unix permissions only"""
        try:
            # Check if directory exists
            if not os.path.isdir(directory_path):
                return False

            # Get parent directory (where rename operation happens)
            parent_dir = os.path.dirname(directory_path.rstrip(os.sep))

            # Check if parent directory exists
            if not parent_dir or not os.path.isdir(parent_dir):
                return False

            # Check parent directory write permission using Unix permissions
            try:
                parent_stat = os.stat(parent_dir)
                parent_mode = parent_stat.st_mode
                # Check if parent directory has write permission (owner write bit)
                if not (parent_mode & 0o200):  # Check if owner write bit is set (octal 200)
                    return False
            except Exception:
                return False

            # Check if directory itself has write permission using Unix permissions
            # A directory with restricted permissions (like 500 = r-x) may fail to rename
            try:
                dir_stat = os.stat(directory_path)
                dir_mode = dir_stat.st_mode
                # Check if directory has write permission (owner write bit)
                # Mode 500 (0o500) = r-x = no write permission
                if not (dir_mode & 0o200):  # Check if owner write bit is set (octal 200)
                    return False
            except Exception:
                return False

            return True
        except Exception:
            return False

    def contextMenuEvent(self, event: QMouseEvent) -> None:
        """Handle context menu (right-click) for directory nodes"""
        index = self.indexAt(event.pos())
        if not index.isValid():
            super().contextMenuEvent(event)
            return

        model = self.model()
        if not model:
            super().contextMenuEvent(event)
            return

        source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
        file_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""

        # Only show menu for directories
        if not os.path.isdir(file_path):
            super().contextMenuEvent(event)
            return

        # Create context menu
        menu = QMenu(self)
        # Set stylesheet to ensure disabled items appear grayed out
        menu.setStyleSheet(tc.QMENU_DEFAULT_STYLE_SHEET)

        # Check if directory is root or system volume (disable recursive actions)
        is_restricted = is_root_or_system_volume(file_path)

        # "Rename" action - check permissions first
        can_rename = self._can_rename_directory(file_path)
        rename_action = menu.addAction("Rename...\tF2")
        rename_action.setEnabled(can_rename)
        if can_rename:
            rename_action.triggered.connect(lambda: self._handle_rename(index, file_path))

        # "Search" action
        search_action = menu.addAction("Search by Description...\t⌘F")
        search_action.setEnabled(not is_restricted)
        if not is_restricted:
            search_action.triggered.connect(lambda: self._handle_search(file_path))

        # "Search by person" action
        search_by_person_action = menu.addAction("Search by Person...\t⌘P")
        search_by_person_action.setEnabled(not is_restricted)
        if not is_restricted:
            search_by_person_action.triggered.connect(lambda: self._handle_search_by_person(file_path))

        # "Copy File Path" action
        copy_path_action = menu.addAction("Copy Directory Path\t⌘C")
        copy_path_action.triggered.connect(lambda: self._handle_copy_file_path(file_path))

        # "Open in Finder" action
        open_finder_action = menu.addAction("Open in Finder")
        open_finder_action.triggered.connect(lambda: self._handle_open_in_finder(file_path))

        # "All Images" action
        all_images_action = menu.addAction("Show All Images inc. Subdirs\t⇧A")
        all_images_action.setEnabled(not is_restricted)
        if not is_restricted:
            all_images_action.triggered.connect(lambda: self._handle_all_images(file_path))

        # "Find Duplicate Image Files" action
        find_duplicates_action = menu.addAction("Find Duplicate Image Files\t⇧F")
        find_duplicates_action.setEnabled(not is_restricted)
        if not is_restricted:
            find_duplicates_action.triggered.connect(lambda: self._handle_find_duplicates(file_path))

        # "Find similar images" from this folder downward (recursive; no menu-bar shortcut)
        find_similar_here_action = menu.addAction("Find VisuallySimilar Image Files")
        find_similar_here_action.setEnabled(not is_restricted)
        if not is_restricted:
            find_similar_here_action.triggered.connect(
                lambda: self._handle_find_similar_images_in_folder(file_path)
            )

        # "Clear cache" action
        clear_cache_action = menu.addAction("Clear Cache")
        clear_cache_action.setEnabled(not is_restricted)
        if not is_restricted:
            clear_cache_action.triggered.connect(lambda: self._handle_clear_cache(file_path))

        # Show menu at cursor position
        menu.exec(event.globalPos())
        event.accept()

    def _handle_all_images(self, directory_path: str) -> None:
        """Handle 'All Images' menu action - scan directory recursively and open as specific files view"""
        if not self.main_window:
            return

        # Check if directory is root or system volume
        if is_root_or_system_volume(directory_path):
            if directory_path == '/':
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on the root directory.")
            else:
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on system volumes.")
            return

        # Save current directory to restore later
        original_current_directory = None
        if hasattr(self.main_window, 'current_directory'):
            original_current_directory = self.main_window.current_directory

        # Scan directory recursively for all images, then apply current filename filter (same as browse mode)
        image_files = self._scan_directory_recursively(directory_path)
        if hasattr(self.main_window, 'sorting_manager') and self.main_window.sorting_manager:
            image_files = self.main_window.sorting_manager.filter_images_by_pattern(image_files)

        if len(image_files) > 100:  # prepopulate cache if there are more than 100 images
            # Temporarily set current_directory to the target directory for prepopulate_cache
            self.main_window.current_directory = directory_path

            # Prepopulate cache with progress dialog (user can cancel); only check/cache filtered paths
            # Suppress success messages, but show cancel message if user cancels
            # Import here to avoid circular dependency
            from cache_prepopulator import prepopulate_cache
            was_canceled = prepopulate_cache(self.main_window, MIN_THUMBNAIL_SIZE, suppress_success_messages=True,
                image_paths=image_files,
            )

            # Restore original current_directory
            if original_current_directory is not None:
                self.main_window.current_directory = original_current_directory
            elif hasattr(self.main_window, 'current_directory'):
                # If it didn't exist before, we might want to clear it or leave it set
                # For now, leave it set to directory_path as it might be useful
                pass

            # If user canceled, don't proceed with building the view
            if was_canceled:
                return

        if not image_files:
            show_styled_information(self.main_window, "No Images Found",
                                    f"No images found in {directory_path} and its subdirectories.")
            return

        # Save current state before switching to specific files view
        if hasattr(self.main_window, 'directory_stack_history_handler'):
            current_state = self.main_window.directory_stack_history_handler.capture_current_state()
            if current_state and not self.main_window.directory_stack_history_handler.is_duplicate_state(current_state):
                self.main_window.directory_stack_history_handler.backward_stack.append(current_state)
                self.main_window.directory_stack_history_handler.forward_stack.clear()

        # Open as specific files view
        configuration = {'files': image_files}
        if hasattr(self.main_window, 'refresh_from_configuration'):
            self.main_window.refresh_from_configuration(configuration)

    def _handle_find_duplicates(self, directory_path: str) -> None:
        """Handle 'Find Duplicate Image Files' menu action - find exact duplicates recursively starting from selected directory"""
        if not self.main_window:
            return

        # Check if directory is root or system volume
        if is_root_or_system_volume(directory_path):
            if directory_path == '/':
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on the root directory.")
            else:
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on system volumes.")
            return

        # Ensure we're in thumbnail view (duplicate search requires it)
        if self.main_window.current_view_mode != 'thumbnail':
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager.close_browse_view()

        # Temporarily set current_directory to the selected directory
        # This allows find_exact_duplicates_recursive to use it as the starting point
        self.main_window.current_directory = directory_path

        # Call the recursive duplicate search
        # This will scan from directory_path recursively and display duplicates
        if hasattr(self.main_window, 'find_exact_duplicates_recursive'):
            self.main_window.find_exact_duplicates_recursive()
        elif hasattr(self.main_window, 'file_operations_manager') and self.main_window.file_operations_manager:
            # Fallback: call directly on file_operations_manager
            self.main_window.file_operations_manager.find_exact_duplicates_recursive()

        # Set focus to thumbnail view after duplicate search completes (if duplicates were found)
        # Use a timer to ensure UI has updated before setting focus
        def set_focus():
            if hasattr(self.main_window, 'main_content_widget') and self.main_window.main_content_widget:
                # Only set focus if we're still in thumbnail view and have displayed images
                if (hasattr(self.main_window, 'current_view_mode') and
                    self.main_window.current_view_mode == 'thumbnail' and
                    hasattr(self.main_window, 'displayed_images') and
                        self.main_window.displayed_images):
                    self.main_window.main_content_widget.setFocus()
        QTimer.singleShot(300, set_focus)

        # Note: We don't restore original_current_directory because the duplicate search
        # changes the view to show duplicates, which is the desired behavior

    def _handle_find_similar_images_in_folder(self, directory_path: str) -> None:
        """Tree context menu: find visually similar images under the selected directory (recursive)."""
        if not self.main_window:
            return

        if is_root_or_system_volume(directory_path):
            if directory_path == '/':
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on the root directory.")
            else:
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on system volumes.")
            return

        if self.main_window.current_view_mode != 'thumbnail':
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager.close_browse_view()

        if hasattr(self.main_window, 'find_similar_image_files_in_directory'):
            self.main_window.find_similar_image_files_in_directory(directory_path)
        elif hasattr(self.main_window, 'file_operations_manager') and self.main_window.file_operations_manager:
            self.main_window.file_operations_manager.find_similar_image_files_in_directory(directory_path)

    def _handle_clear_cache(self, directory_path: str) -> None:
        """Handle 'Clear cache' menu action - clear cached images and search cache data for directory (non-recursive)"""
        if not self.main_window:
            return

        # Check if directory is root or system volume
        if is_root_or_system_volume(directory_path):
            if directory_path == '/':
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on the root directory.")
            else:
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on system volumes.")
            return

        try:
            cleared_count = 0

            # Clear image cache for directory (non-recursive)
            if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
                # Count cache entries before clearing
                with QMutexLocker(self.main_window.cache_manager.cache_mutex):
                    before_metadata = len(self.main_window.cache_manager.metadata_cache)
                    before_thumbnails = len(self.main_window.cache_manager.thumbnail_cache)
                    before_fullimages = len(self.main_window.cache_manager.fullimage_cache)

                self.main_window.cache_manager.clear_cache_for_directory(directory_path, skip_disk_deletion=False)

                # Count cache entries after clearing
                with QMutexLocker(self.main_window.cache_manager.cache_mutex):
                    after_metadata = len(self.main_window.cache_manager.metadata_cache)
                    after_thumbnails = len(self.main_window.cache_manager.thumbnail_cache)
                    after_fullimages = len(self.main_window.cache_manager.fullimage_cache)

                cleared_metadata = before_metadata - after_metadata
                cleared_thumbnails = before_thumbnails - after_thumbnails
                cleared_fullimages = before_fullimages - after_fullimages
                cleared_count = cleared_metadata + cleared_thumbnails + cleared_fullimages

                print(f"Cleared cache: {cleared_metadata} metadata, {cleared_thumbnails} thumbnails, {cleared_fullimages} full images")

            # Clear search cache for directory
            search_cache_cleared = 0
            if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
                if hasattr(self.main_window.file_tree_handler, 'filter_proxy') and self.main_window.file_tree_handler.filter_proxy:
                    if hasattr(self.main_window.file_tree_handler.filter_proxy, 'clear_search_cache_for_directory'):
                        before_search = len(self.main_window.file_tree_handler.filter_proxy.has_images_cache)
                        self.main_window.file_tree_handler.filter_proxy.clear_search_cache_for_directory(directory_path)
                        after_search = len(self.main_window.file_tree_handler.filter_proxy.has_images_cache)
                        search_cache_cleared = before_search - after_search

            # Clear face cache for directory (non-recursive)
            face_cache_cleared = 0
            try:
                from face_cache import clear_face_cache_for_directory
                face_cache_cleared = clear_face_cache_for_directory(directory_path)
            except Exception as e:
                print(f"Error clearing face cache: {e}")
            if face_cache_cleared > 0:
                try:
                    from face_scan_runner import clear_scanned_dir_cache
                    clear_scanned_dir_cache()
                except Exception:
                    pass

            # Clear image recognition cache for directory
            recognition_cache_cleared = 0
            dir_hash = None
            if hasattr(self.main_window, 'cnn_image_similarity_sorter') and self.main_window.cnn_image_similarity_sorter:
                if hasattr(self.main_window.cnn_image_similarity_sorter, 'feature_cache') and self.main_window.cnn_image_similarity_sorter.feature_cache:
                    try:
                        # Count before
                        before_cnn = len(self.main_window.cnn_image_similarity_sorter.feature_cache.cnn_cache)
                        before_clip = len(self.main_window.cnn_image_similarity_sorter.feature_cache.clip_cache)
                        # Clear cache for this directory
                        self.main_window.cnn_image_similarity_sorter.feature_cache.clear_cache_for_directory(directory_path)
                        # Count after
                        after_cnn = len(self.main_window.cnn_image_similarity_sorter.feature_cache.cnn_cache)
                        after_clip = len(self.main_window.cnn_image_similarity_sorter.feature_cache.clip_cache)
                        recognition_cache_cleared = (before_cnn - after_cnn) + (before_clip - after_clip)
                        dir_hash = hashlib.sha256(str(Path(directory_path).resolve()).encode('utf-8')).hexdigest()[:16]
                    except Exception as e:
                        print(f"Error clearing image recognition cache: {e}")
                        import traceback
                        traceback.print_exc()

            # Restart background worker so it repopulates disk (same as settings clear)
            if recognition_cache_cleared > 0 and hasattr(self.main_window, 'background_clip_controller'):
                controller = self.main_window.background_clip_controller
                if controller.enabled:
                    controller.stop_process()
                    controller.start_process()
            # Clear importer tracking for this directory so new cache files will be imported
            if recognition_cache_cleared > 0 and dir_hash and hasattr(self.main_window, 'background_cache_importer'):
                self.main_window.background_cache_importer.clear_imported_for_dir_hash(dir_hash)

            if search_cache_cleared > 0:
                print(f"Cleared {search_cache_cleared} search cache entries")
            if recognition_cache_cleared > 0:
                print(f"Cleared {recognition_cache_cleared} image recognition cache entries")
            if face_cache_cleared > 0:
                print(f"Cleared {face_cache_cleared} face cache entries")

            # Build success message
            message_parts = [f"Cache cleared for directory:\n{directory_path}\n"]
            if cleared_count > 0:
                message_parts.append(f"- {cleared_count} image cache entries")
            if search_cache_cleared > 0:
                message_parts.append(f"- {search_cache_cleared} search cache entries")
            if recognition_cache_cleared > 0:
                message_parts.append(f"- {recognition_cache_cleared} image recognition cache entries")
            if face_cache_cleared > 0:
                message_parts.append(f"- {face_cache_cleared} face cache entries")

            if cleared_count > 0 or search_cache_cleared > 0 or recognition_cache_cleared > 0 or face_cache_cleared > 0:
                show_styled_information(self.main_window,
                    "Cache Cleared",
                    "\n".join(message_parts) +
                    "\n\nCached data has been removed (non-recursive)."
                )
            else:
                show_styled_information(self.main_window,
                    "Cache Cleared",
                    f"Cache cleared for directory:\n{directory_path}\n\nNo cached data found to clear."
                )

        except Exception as e:
            show_styled_warning(self.main_window,
                "Error Clearing Cache",
                f"An error occurred while clearing cache:\n\n{str(e)}"
            )

    def _scan_directory_recursively(self, root_dir: str) -> List[str]:
        """Recursively scan directory for all image files"""
        image_files = []
        image_extensions = get_image_extensions()

        # Get max depth from config (defaults to 4)
        try:
            config = get_config()
            settings = config.load_settings()
            max_depth = int(settings.get('search_depth', 4))
        except Exception:
            max_depth = 4
            config = None

        # Get excluded paths (cache, Photos Library, and ignore directories)
        excluded_paths = []
        try:
            if config is None:
                config = get_config()
            excluded_paths = _get_excluded_paths(config)
        except Exception:
            pass

        # Walk directories recursively
        # Get process hidden directories setting
        process_hidden = get_show_hidden_directories()
        # Get follow symlinks setting
        follow_symlinks = get_follow_symlinks()

        for root, dirs, files in os.walk(root_dir):
            if prune_walk_dirs(
                root,
                dirs,
                excluded_paths=excluded_paths,
                process_hidden=process_hidden,
                skipped_patterns=SKIPPED_PATTERNS,
            ):
                continue

            # Filter symlinks if not following them (except enabled root dirs on Directories tab)
            filter_walk_symlink_dirs(root, dirs, follow_symlinks)

            # Calculate depth relative to root_dir
            rel_path = os.path.relpath(root, root_dir)
            if rel_path == '.':
                depth = 0
            else:
                depth = len([p for p in rel_path.split(os.sep) if p])

            # Stop when depth >= max_depth to match find -maxdepth behavior
            # max_depth=4 means: root (depth 0), subdir (depth 1), subsubdir (depth 2), subsubsubdir (depth 3)
            # This matches find -maxdepth 4 which scans 4 levels total
            if depth >= max_depth:
                dirs[:] = []  # Don't recurse deeper than max_depth
                continue

            # Collect image files
            for file in files:
                if get_file_extension(file) in image_extensions:
                    file_path = f"{root}/{file}"
                    # Skip files in skipped patterns
                    skip_file = False
                    for pattern in SKIPPED_PATTERNS:
                        if pattern in file_path:
                            skip_file = True
                            break
                    if not skip_file:
                        image_files.append(file_path)

        return image_files

    def _handle_rename(self, index: QModelIndex, directory_path: str) -> None:
        """Handle 'Rename' menu action - show inline rename editor"""
        if not self.main_window:
            return

        # Cancel any existing rename editor
        self._cancel_rename()

        # Get the visual rect for the index (in viewport coordinates)
        visual_rect = self.visualRect(index)

        # Get directory name (basename)
        directory_name = os.path.basename(directory_path.rstrip(os.sep))

        # Create inline editor as child of viewport (since visualRect is relative to viewport)
        self._rename_editor = QLineEdit(self.viewport())
        self._rename_editor.setText(directory_name)
        self._rename_editor.selectAll()

        # Calculate text rect position using style option
        # This gives us the exact position where the text is drawn
        try:
            option = QStyleOptionViewItem()
            # Initialize the style option using the delegate if available, otherwise manually
            delegate = self.itemDelegate()
            if delegate and isinstance(delegate, QStyledItemDelegate):
                delegate.initStyleOption(option, index)
                # Ensure rect is set (delegate should set it, but verify)
                if not option.rect.isValid():
                    option.rect = self.visualRect(index)
            else:
                # Manually initialize the option
                option.index = index
                option.state = QStyle.State_None
                if self.selectionModel() and self.selectionModel().isSelected(index):
                    option.state |= QStyle.State_Selected
                if self.hasFocus():
                    option.state |= QStyle.State_HasFocus
                option.rect = self.visualRect(index)
                option.showDecorationSelected = True

            # Ensure option.rect is valid before calling subElementRect
            if not option.rect.isValid():
                # Fallback: set rect from visualRect
                option.rect = self.visualRect(index)

            # Get the text rect from the style (this gives us just the text area)
            # The widget parameter should be the viewport for QTreeView
            text_rect = self.style().subElementRect(QStyle.SE_ItemViewItemText, option, self.viewport()
            )
            if text_rect.isValid() and text_rect.width() > 0 and text_rect.height() > 0:
                # Use the text rect, but need to adjust for indentation and icon
                # Calculate depth (nesting level)
                depth = 0
                parent = index.parent()
                while parent.isValid():
                    depth += 1
                    parent = parent.parent()

                indentation = self.indentation()

                # text_rect.x() might not account for indentation properly, so add it
                # Move right by one indentation level + icon size
                editor_x = text_rect.x() + (depth * indentation) - 4
                editor_y = text_rect.y()
                editor_width = text_rect.width() - (depth * indentation) - 4
                editor_height = text_rect.height()
            else:
                # Fallback: calculate manually from visual rect
                raise ValueError("Invalid text rect")
        except Exception as e:
            print(f"Error in _handle_rename: {e}")
            # Fallback: use visual rect with manual calculation
            # subElementRect may not work reliably for QTreeView, so use manual calculation
            icon_size = self.iconSize().width() if self.iconSize().isValid() else 18
            spacing = 4  # Spacing between icon and text
            indentation = self.indentation()

            # Calculate depth (nesting level)
            depth = 0
            parent = index.parent()
            while parent.isValid():
                depth += 1
                parent = parent.parent()

            # Try to get branch icon width from style
            try:
                # Get branch icon rect using style
                option = QStyleOptionViewItem()
                delegate = self.itemDelegate()
                if delegate and isinstance(delegate, QStyledItemDelegate):
                    delegate.initStyleOption(option, index)
                else:
                    option.rect = visual_rect
                    option.index = index

                # Get branch icon rect (expand/collapse icon)
                branch_rect = self.style().subElementRect(QStyle.SE_TreeViewDisclosureItem, option, self.viewport()
                )
                branch_width = branch_rect.width() if branch_rect.isValid() else 0
            except Exception:
                # Fallback: estimate branch width
                has_branch = self.model().hasChildren(index)
                branch_width = 20 if has_branch else 0

            # Calculate text start position
            # visual_rect.x() + (depth * indentation) + branch_width + icon_size + spacing = text start
            # Need to add indentation level + icon size to move right
            text_start_x = visual_rect.x() + (depth * indentation) + \
                branch_width + icon_size + spacing
            editor_x = text_start_x
            editor_y = visual_rect.y()
            editor_width = max(100, visual_rect.width() -
                               (text_start_x - visual_rect.x()))
            editor_height = visual_rect.height()

            print(f"visual_rect.x(): {visual_rect.x()}, depth: {depth}, indentation: {indentation}, branch_width: {branch_width}, icon_size: {icon_size}, spacing: {spacing}, text_start_x: {text_start_x}")

        self._rename_editor.setGeometry(editor_x, editor_y, editor_width, editor_height)

        # Style with skyblue border (matching thumbnail rename)
        self._rename_editor.setStyleSheet("""
            QLineEdit {
                border: 1px solid #6b6b6b;
                border-radius: 0px;
                background-color: rgba(0, 0, 0, 240);
                color: {TEXT_COLOR_HEX};
                font-family: Arial;
                font-weight: 100;
                font-size: 13px;
                padding: 2px;
            }
        """)

        # Store directory path being edited
        self._editing_directory_path = directory_path

        # Connect signals
        self._rename_editor.editingFinished.connect(self._finish_rename)
        self._rename_editor.installEventFilter(self)

        # Show and focus editor
        self._rename_editor.show()
        self._rename_editor.setFocus()

    def _cancel_rename(self) -> None:
        """Cancel inline rename editing"""
        if self._rename_editor is not None:
            try:
                self._rename_editor.editingFinished.disconnect()
                self._rename_editor.removeEventFilter(self)
                self._rename_editor.hide()
                self._rename_editor.deleteLater()
            except (AttributeError, RuntimeError, TypeError):
                pass
            finally:
                self._rename_editor = None
        self._editing_directory_path = None

    def _finish_rename(self) -> None:
        """Finish inline rename editing"""
        if not self._rename_editor or not self._editing_directory_path:
            return

        new_name = self._rename_editor.text().strip()
        old_path = self._editing_directory_path

        # Validate filename
        is_valid, error_msg = self._validate_directory_name(new_name)
        if not is_valid:
            show_styled_critical(self.main_window, "Invalid Directory Name", error_msg)
            self._cancel_rename()
            return

        # Check if name changed
        old_name = os.path.basename(old_path.rstrip(os.sep))
        if new_name == old_name:
            self._cancel_rename()
            return

        # Construct new path
        parent_dir = os.path.dirname(old_path.rstrip(os.sep))
        new_path = os.path.join(parent_dir, new_name)

        # Check if target already exists
        if os.path.exists(new_path):
            show_styled_critical(self.main_window, "Rename Failed",
                                 f"A directory named '{new_name}' already exists.")
            self._cancel_rename()
            return

        # Perform rename
        try:
            os.rename(old_path, new_path)
            # Refresh tree view
            if hasattr(self.main_window, 'file_tree_handler'):
                self.main_window.file_tree_handler.rebuild_tree()
        except Exception as e:
            show_styled_critical(self.main_window, "Rename Failed", f"Failed to rename directory: {str(e)}")

        self._cancel_rename()

    def _validate_directory_name(self, name: str) -> Tuple[bool, str]:
        """Validate directory name (similar to thumbnail rename validation)"""
        if not name:
            return False, "Directory name cannot be empty"

        # Check for invalid characters
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in invalid_chars:
            if char in name:
                return False, f"Directory name cannot contain '{char}'"

        # Check for reserved names (macOS)
        reserved_names = {'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4',
                          'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 'LPT3',
                          'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'}
        if name.upper() in reserved_names:
            return False, f"'{name}' is a reserved name"

        return True, ""

    def _handle_open_in_finder(self, directory_path: str) -> None:
        """Handle 'Open in Finder' menu action - open directory contents in macOS Finder"""
        try:
            subprocess.run(['open', directory_path], check=True, timeout=5)
        except subprocess.CalledProcessError:
            show_styled_critical(self.main_window if self.main_window else None,
                                 "Error",
                                 f"Failed to open {directory_path} in Finder.")
        except subprocess.TimeoutExpired:
            show_styled_critical(self.main_window if self.main_window else None,
                                 "Error",
                                 f"Timeout while trying to open {directory_path} in Finder.")
        except Exception as e:
            show_styled_critical(self.main_window if self.main_window else None,
                                 "Error",
                                 f"Unexpected error opening {directory_path} in Finder: {str(e)}")

    def _handle_copy_file_path(self, directory_path: str) -> None:
        """Handle 'Copy File Path' menu action - copy directory path to clipboard"""
        try:
            clipboard = QApplication.clipboard()
            clipboard.setText(normalize_path_for_display(directory_path))
            if self.main_window and hasattr(self.main_window, 'status_notification'):
                self.main_window.status_notification.show_message(f"Copied to clipboard: {os.path.basename(directory_path)}")
        except Exception as e:
            show_styled_critical(self.main_window if self.main_window else None,
                                 "Error",
                                 f"Failed to copy path to clipboard: {str(e)}")

    def _handle_search(self, directory_path: str) -> None:
        """Handle 'Search' menu action - open clip search dialog with directory pre-filled"""
        if not self.main_window:
            return

        # Check if directory is root or system volume
        if is_root_or_system_volume(directory_path):
            if directory_path == '/':
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on the root directory.")
            else:
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on system volumes.")
            return

        # Ensure we're in thumbnail view (clip search requires it)
        if self.main_window.current_view_mode != 'thumbnail':
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager.close_browse_view()

        # Lazy initialize UI helper if needed
        if hasattr(self.main_window, '_ensure_cnn_ui_helper_initialized'):
            self.main_window._ensure_cnn_ui_helper_initialized()

        if not hasattr(self.main_window, 'cnn_similarity_ui_helper') or not self.main_window.cnn_similarity_ui_helper:
            return

        # Check if locked files exist in the directory being searched
        has_locked_files = False
        if directory_path and os.path.isdir(directory_path):
            if hasattr(self.main_window, 'lock_manager') and self.main_window.lock_manager:
                locked_files = self.main_window.lock_manager.get_locked_files(directory_path)
                has_locked_files = len(locked_files) > 0

        # Get saved settings
        settings = self.main_window.config.load_settings()
        saved_prompt = settings.get('clip_prompt', '')
        saved_recursive = settings.get('clip_recursive', False)
        saved_threshold = settings.get('clip_similarity_threshold', 0.20)

        # Create dialog with directory pre-filled and checkbox checked
        dialog = self.main_window.cnn_similarity_ui_helper.create_clip_search_dialog("Find Images",
            "Enter text description to search for:",
            text=saved_prompt,
            recursive_default=saved_recursive,
            threshold_default=saved_threshold,
            directory=directory_path,  # Pre-fill with selected directory
            hide_threshold=has_locked_files
        )

        # Check the directory checkbox and set the directory field
        if hasattr(dialog, 'dir_checkbox'):
            dialog.dir_checkbox.setChecked(True)
        if hasattr(dialog, 'dir_input'):
            dialog.dir_input.setText(directory_path)

        # Execute dialog - if user clicks OK, trigger the search
        if not dialog.exec():
            # User canceled dialog - don't perform search
            return

        # Read values from dialog (same as reorder_images_by_clip_search)
        text_prompt = dialog.text_input.text().strip()
        recursive = dialog.recursive_checkbox.isChecked()
        # Force threshold to 0.0 when locked files exist (ignore user setting)
        if has_locked_files:
            threshold = 0.0
        else:
            threshold = dialog.threshold_spinbox.value() if hasattr(dialog, 'threshold_spinbox') else 0.20
        dir_checkbox_checked = dialog.dir_checkbox.isChecked() if hasattr(dialog, 'dir_checkbox') else False
        # Use search_directory if checkbox is checked (regardless of recursive)
        search_directory = dialog.dir_input.text().strip() if dir_checkbox_checked and hasattr(dialog, 'dir_input') else None

        if not text_prompt:
            # User entered empty text - don't perform search
            return

        # Save the prompt, recursive setting, threshold, and directory settings to config for next time
        # Don't save threshold if it was forced to 0.0 due to locked files
        self.main_window.config.update_setting('clip_prompt', text_prompt)
        self.main_window.config.update_setting('clip_recursive', recursive)
        if not has_locked_files:
            self.main_window.config.update_setting('clip_similarity_threshold', threshold)
        if hasattr(dialog, 'dir_checkbox'):
            self.main_window.config.update_setting('clip_search_dir_enabled', dialog.dir_checkbox.isChecked())
        if hasattr(dialog, 'dir_input'):
            self.main_window.config.update_setting('clip_search_dir', dialog.dir_input.text().strip())

        # Trigger the actual search execution
        # We need to call the search logic that's in reorder_images_by_clip_search
        # Since we've already shown the dialog and gotten the values, we'll
        # directly execute the search by calling a helper that does the work
        # For now, we'll replicate the essential search call
        self._execute_clip_search_execution(text_prompt, recursive, threshold, search_directory or directory_path)

    def _handle_search_by_person(self, directory_path: str) -> None:
        """Handle 'Search by person' menu action - open person search dialog with directory pre-filled (checked), recursion from settings."""
        if not self.main_window:
            return
        if is_root_or_system_volume(directory_path):
            if directory_path == '/':
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on the root directory.")
            else:
                show_styled_warning(self.main_window, "Action Not Available",
                                    "This action is not available on system volumes.")
            return
        if self.main_window.current_view_mode != 'thumbnail':
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager.close_browse_view()
        self.main_window.show_filter_by_person_dialog(directory_override=directory_path)

    def _execute_clip_search_execution(self, text_prompt: str, recursive: bool, threshold: float, search_directory: str) -> None:
        """Execute CLIP search with given parameters (replicates logic from reorder_images_by_clip_search)"""
        if not self.main_window:
            return

        # Check if directory is root or system volume (only for recursive searches)
        if recursive:
            if is_root_or_system_volume(search_directory):
                if search_directory == '/':
                    show_styled_warning(self.main_window, "Action Not Available",
                                        "Recursive search is not available on the root directory.")
                else:
                    show_styled_warning(self.main_window, "Action Not Available",
                                        "Recursive search is not available on system volumes.")
                return

        # Import needed modules
        import os
        import fnmatch
        from thumbnail_constants import get_image_extensions

        # Get settings
        settings = self.main_window.config.load_settings()
        max_depth = int(settings.get('search_depth', 4))

        # Get excluded paths (prowser cache and Photos Library paths)
        excluded_paths = _get_excluded_paths(self.main_window.config)

        # Collect images to search
        displayed_images = []
        displayed_images_set = set()
        search_dir = search_directory if search_directory and os.path.isdir(search_directory) else None

        if not search_dir:
            # No valid search directory - can't search
            return

        search_dir_resolved = os.path.realpath(search_dir)
        image_extensions = get_image_extensions()

        # Track filter pattern
        filter_pattern = self.main_window.filter_pattern if hasattr(self.main_window, 'filter_pattern') else None
        match_pattern = None
        if filter_pattern:
            from config import ImageBrowserConfig
            match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)
        non_matching_images = []

        if recursive:
            # Get process hidden directories setting
            from config import get_config
            config = get_config()
            process_hidden = config.load_settings().get('show_hidden_directories', False)
            follow_symlinks = config.load_settings().get('follow_symlinks', False)

            # Walk directories recursively
            for root, dirs, files in os.walk(search_dir):
                root_resolved = os.path.realpath(root)

                # Skip excluded directories (prowser cache and Photos Library paths)
                if _is_excluded_path(root_resolved, excluded_paths):
                    dirs[:] = []
                    continue

                # Filter hidden directories if not processing them
                if not process_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                # Filter symlinks if not following them (except enabled root dirs on Directories tab)
                filter_walk_symlink_dirs(root, dirs, follow_symlinks)

                # Calculate depth
                rel_path = os.path.relpath(root, search_dir)
                depth = 0 if rel_path == '.' else len([p for p in rel_path.split(os.sep) if p])

                if depth > max_depth:
                    dirs[:] = []
                    continue

                # Collect image files
                for file in files:
                    file_path = f"{root}/{file}"
                    if get_file_extension(file) in image_extensions and os.path.isfile(file_path):
                        abs_path = os.path.abspath(os.path.expanduser(file_path))

                        # Check filter pattern
                        matches_filter = True
                        if match_pattern and match_pattern != '*':
                            filename = file
                            matches_filter = fnmatch.fnmatch(filename.lower(), match_pattern.lower())

                        if abs_path not in displayed_images_set:
                            displayed_images_set.add(abs_path)
                            displayed_images.append(abs_path)
                            if not matches_filter:
                                non_matching_images.append(abs_path)
        else:
            # Non-recursive: collect only top-level images
            if not _is_excluded_path(search_dir_resolved, excluded_paths):
                try:
                    for file in os.listdir(search_dir):
                        file_path = f"{search_dir}/{file}"
                        if os.path.isfile(file_path):
                            if get_file_extension(file) in image_extensions:
                                abs_path = os.path.abspath(os.path.expanduser(file_path))

                                # Check filter pattern
                                matches_filter = True
                                if match_pattern and match_pattern != '*':
                                    filename = file
                                    matches_filter = fnmatch.fnmatch(filename.lower(), match_pattern.lower())

                                if abs_path not in displayed_images_set:
                                    displayed_images_set.add(abs_path)
                                    displayed_images.append(abs_path)
                                    if not matches_filter:
                                        non_matching_images.append(abs_path)
                except (OSError, PermissionError):
                    pass

        if not displayed_images:
            show_styled_warning(self.main_window, "No Images Found", "No images found to search.")
            return

        # Handle filter pattern mismatch
        displayed_images = handle_filter_pattern_mismatch(self.main_window, displayed_images, non_matching_images, recursive
        )

        # Now perform the CLIP search
        # Suspend background thumbnail loading
        if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager and self.main_window.cache_manager.background_loader:
            self.main_window.cache_manager.background_loader.stop()

        # Initialize CNN sorter
        self.main_window._ensure_cnn_sorter_initialized()
        self.main_window._ensure_cnn_ui_helper_initialized()

        # Create progress dialog
        is_first_search = self.main_window.cnn_similarity_ui_helper.is_first_clip_search
        progress_dialog = self.main_window.cnn_similarity_ui_helper.create_clip_progress_dialog(text_prompt, len(displayed_images), is_first_search=is_first_search, recursive=recursive, search_directory=search_directory
        )

        progress_cb = self.main_window.cnn_similarity_ui_helper.create_clip_progress_callback(progress_dialog, is_first_search=is_first_search
        )

        # Initialize files_changed flag (will be set after search completes)
        files_changed = True  # Default to True (create new stack) if search fails

        try:
            # Perform CLIP search
            result = self.main_window.cnn_image_similarity_sorter.reorder_by_text_prompt(displayed_images, text_prompt, progress_callback=None if progress_dialog else progress_cb,
                similarity_threshold=threshold, filter_below_threshold=True, progress_dialog=progress_dialog
            )
            new_displayed_images, highest_score = result

            # Handle threshold adjustment if needed
            if len(new_displayed_images) == 0 and highest_score is not None and highest_score < threshold:
                new_threshold = max(highest_score - 0.03, 0.0)
                threshold = new_threshold
                progress_dialog.setStatusText(f"Retrying with adjusted threshold: {threshold:.2f}...")
                progress_dialog.setValue(0)
                result = self.main_window.cnn_image_similarity_sorter.reorder_by_text_prompt(displayed_images, text_prompt, progress_callback=None if progress_dialog else progress_cb,
                    similarity_threshold=threshold, filter_below_threshold=True, progress_dialog=progress_dialog
                )
                new_displayed_images, highest_score = result

            # Remove duplicates
            seen = set()
            unique_images = []
            for img in new_displayed_images:
                if img not in seen:
                    seen.add(img)
                    unique_images.append(img)
            new_displayed_images = unique_images

            # Check if no matches found
            if recursive and len(new_displayed_images) == 0:
                show_styled_information(
                    self.main_window,
                    "No Matches Found",
                    "No images found matching the search criteria.",
                )
                progress_dialog.hide()
                if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager and self.main_window.cache_manager.background_loader:
                    self.main_window.cache_manager.background_loader.start()
                return

            # Mark CLIP search as used
            self.main_window.cnn_similarity_ui_helper.mark_clip_search_used()

            # CRITICAL: Check if files changed before creating new stack
            # Capture current displayed_images BEFORE saving state to history
            current_displayed_images = set()
            current_displayed_images_list = []
            if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images:
                current_displayed_images = set(self.main_window.displayed_images)
                current_displayed_images_list = self.main_window.displayed_images
            new_displayed_images_set = set(new_displayed_images)
            files_changed = current_displayed_images != new_displayed_images_set
            # Also check if order changed (same files but different order)
            order_changed = files_changed or (current_displayed_images_list != new_displayed_images)
        except KeyboardInterrupt:
            progress_dialog.cancel()
            if hasattr(self.main_window, 'cnn_image_similarity_sorter') and self.main_window.cnn_image_similarity_sorter.feature_cache:
                # Use async flush to avoid blocking main thread
                self.main_window.cnn_image_similarity_sorter.feature_cache.flush_caches(async_flush=True)
            if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager and self.main_window.cache_manager.background_loader:
                self.main_window.cache_manager.background_loader.start()
            return
        finally:
            progress_dialog.setValue(len(displayed_images))
            progress_dialog.hide()

        # Handle results
        if recursive:
            # Check if files changed - if same files, rewrite .prsort instead of creating new stack
            if not files_changed:
                # Same files - rewrite .prsort and switch to custom sort mode without creating new stack
                # Check if all search results are from the same directory
                directories = set(os.path.dirname(path) for path in new_displayed_images if os.path.exists(path))
                if len(directories) == 1:
                    dir_path = directories.pop()
                    if hasattr(self.main_window, 'current_directory') and dir_path == self.main_window.current_directory:
                        # All results from current directory - rewrite .prsort with locked files at top
                        if hasattr(self.main_window, 'similarity_search_manager'):
                            self.main_window.similarity_search_manager._rewrite_prsort_with_locked_at_top(new_displayed_images, self.main_window.current_directory)

                            # CRITICAL: Reload directory first to get all files, then trigger "C" action
                            # set_custom_sort() is what pressing "C" does - it reloads and applies custom sort
                            directory_to_reload = self.main_window.current_directory

                            def do_reload_and_custom():
                                if not directory_to_reload:
                                    return

                                # First reload directory to scan all files from disk
                                if hasattr(self.main_window, 'directory_loader'):
                                    self.main_window.directory_loader.load_directory(directory_to_reload,
                                        external_load=False,
                                        refresh_mode=True
                                    )

                                # Then trigger set_custom_sort (what "C" key does)
                                # This will read .prsort and apply the order with locked files at top
                                def trigger_c():
                                    self.main_window.set_custom_sort()
                                    # NOTE: We do NOT call save_custom_sort() here because we've already written
                                    # the .prsort file correctly with the CLIP order in _rewrite_prsort_with_locked_at_top
                                QTimer.singleShot(600, trigger_c)

                            # Delay to ensure .prsort file is written to disk
                            QTimer.singleShot(300, do_reload_and_custom)

                            # Restart thumbnails
                            if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager and self.main_window.cache_manager.background_loader:
                                self.main_window.cache_manager.background_loader.start()
                            return

            # Files changed - save state before switching
            if hasattr(self.main_window, 'directory_stack_history_handler'):
                self.main_window.directory_stack_history_handler.save_current_state(
                    "file_tree_handler._execute_clip_search_execution (recursive)", delay=0.0
                )

            # Set sort mode
            from image_browser_window import SortMode
            self.main_window.current_sort_mode = SortMode.CUSTOM
            self.main_window.is_reversed = False

            # Load results as specific files
            configuration = {'files': new_displayed_images, 'sort_mode': 'custom'}
            self.main_window.refresh_from_configuration(configuration)

            # Save state after load
            if hasattr(self.main_window, 'directory_stack_history_handler'):
                self.main_window.directory_stack_history_handler.save_current_state(
                    "file_tree_handler._execute_clip_search_execution (after load)", delay=0.0
                )

            # Update UI
            self.main_window.update_status_bar_sections()
            self.main_window.update_sort_menu_checkmarks()
            self.main_window.save_sorting_settings()

            # Set focus to thumbnail view (use timer to ensure UI is ready)
            def set_focus():
                if hasattr(self.main_window, 'main_content_widget'):
                    self.main_window.main_content_widget.setFocus()
            QTimer.singleShot(100, set_focus)
        else:
            # Non-recursive: check if files changed - if same files, rewrite .prsort instead of creating new stack
            if not files_changed:
                # Same files - rewrite .prsort and switch to custom sort mode without creating new stack
                # Check if all search results are from the same directory
                directories = set(os.path.dirname(path) for path in new_displayed_images if os.path.exists(path))
                if len(directories) == 1:
                    dir_path = directories.pop()
                    if hasattr(self.main_window, 'current_directory') and dir_path == self.main_window.current_directory:
                        # All results from current directory - rewrite .prsort with locked files at top
                        if hasattr(self.main_window, 'similarity_search_manager'):
                            self.main_window.similarity_search_manager._rewrite_prsort_with_locked_at_top(new_displayed_images, self.main_window.current_directory)

                            # CRITICAL: Reload directory first to get all files, then trigger "C" action
                            # set_custom_sort() is what pressing "C" does - it reloads and applies custom sort
                            directory_to_reload = self.main_window.current_directory

                            def do_reload_and_custom():
                                if not directory_to_reload:
                                    return

                                # First reload directory to scan all files from disk
                                if hasattr(self.main_window, 'directory_loader'):
                                    self.main_window.directory_loader.load_directory(
                                        directory_to_reload,
                                        external_load=False,
                                        refresh_mode=True
                                    )

                                # Then trigger set_custom_sort (what "C" key does)
                                # This will read .prsort and apply the order with locked files at top
                                def trigger_c():
                                    self.main_window.set_custom_sort()
                                    # NOTE: We do NOT call save_custom_sort() here because we've already written
                                    # the .prsort file correctly with the CLIP order in _rewrite_prsort_with_locked_at_top
                                QTimer.singleShot(600, trigger_c)

                            # Delay to ensure .prsort file is written to disk
                            QTimer.singleShot(300, do_reload_and_custom)

                            # Restart thumbnails
                            if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager and self.main_window.cache_manager.background_loader:
                                self.main_window.cache_manager.background_loader.start()
                            return

            # Files changed - update displayed images in place
            saved_selections = set(self.main_window.selected_files) if self.main_window.selected_files else set()

            # CRITICAL: Check if result set is the same as starting set (files and order)
            # If same files and same order, no thumbnail rebuild is needed
            if not files_changed and not order_changed:
                # Same files, same order - no refresh needed, just restart thumbnails
                if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager and self.main_window.cache_manager.background_loader:
                    self.main_window.cache_manager.background_loader.start()
                self.main_window.start_background_thumbnail_loading_if_needed()
                # Update UI
                self.main_window.update_status_bar_sections()
                self.main_window.update_sort_menu_checkmarks()
                self.main_window.save_sorting_settings()
                # Set focus to thumbnail view

                def set_focus():
                    if hasattr(self.main_window, 'main_content_widget'):
                        self.main_window.main_content_widget.setFocus()
                QTimer.singleShot(100, set_focus)
                return

            # Update displayed images using sync helper to ensure FileDataModel consistency
            if hasattr(self.main_window, '_set_displayed_images_with_sync'):
                self.main_window._set_displayed_images_with_sync(new_displayed_images, sync=True)
            else:
                self.main_window.displayed_images = new_displayed_images
            self.main_window.image_indices = list(range(len(new_displayed_images)))
            self.main_window.image_indices_sequential = self.main_window.image_indices.copy()

            # Restore selections
            if saved_selections:
                self.main_window.selected_files = {
                    f for f in saved_selections if f in new_displayed_images}
                if hasattr(self.main_window, '_emit_selection_changed'):
                    self.main_window._emit_selection_changed()

            # Set sort mode
            from image_browser_window import SortMode
            self.main_window.current_sort_mode = SortMode.CUSTOM
            self.main_window.is_reversed = False

            # Refresh display - use generate_thumbnails to ensure thumbnails are properly displayed
            self.main_window.clear_thumbnails()
            # Use generate_thumbnails instead of add_thumbnails_for_files to ensure proper initialization
            self.main_window.generate_thumbnails(force_refresh=True)
            self.main_window.highlight_index = 0
            if new_displayed_images:
                # Use sync helper to set current_image_path
                if hasattr(self.main_window, '_set_current_image_path_with_sync'):
                    self.main_window._set_current_image_path_with_sync(new_displayed_images[0], sync=True)
                else:
                    self.main_window.current_image_path = new_displayed_images[0]
                self.main_window.highlight_image()

            # Update UI
            self.main_window.update_status_bar_sections()
            self.main_window.update_sort_menu_checkmarks()
            self.main_window.save_sorting_settings()

            # Restart thumbnail loading
            if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager and self.main_window.cache_manager.background_loader:
                self.main_window.cache_manager.background_loader.start()
            self.main_window.start_background_thumbnail_loading_if_needed()

            # Set focus to thumbnail view (use timer to ensure UI is ready)
            def set_focus():
                if hasattr(self.main_window, 'main_content_widget'):
                    self.main_window.main_content_widget.setFocus()
            QTimer.singleShot(100, set_focus)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Event filter for rename editor to handle Escape key"""
        if obj == self._rename_editor and event.type() == QEvent.KeyPress:
            key_event = event
            if key_event.key() == Qt.Key_Escape:
                self._cancel_rename()
                return True
        return super().eventFilter(obj, event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        """Handle key release events for navigation."""
        super().keyReleaseEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Handle drag enter events - accept if URLs are present"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Handle drag move events - highlight directory under cursor"""
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        # Get the index under the cursor
        index = self.indexAt(event.pos())
        new_highlight_index = None

        # Check if we're over a valid directory
        if index.isValid():
            model = self.model()
            if model:
                source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                if source_index.isValid() and hasattr(model, 'sourceModel'):
                    file_path = model.sourceModel().filePath(source_index)
                    # Only accept drops on directories
                    if os.path.isdir(file_path):
                        self._drop_target_directory = file_path
                        new_highlight_index = index
                        # Accept the proposed action (could be CopyAction or MoveAction)
                        # Don't force a specific action - let the drag source and macOS decide
                        event.acceptProposedAction()
                    else:
                        self._drop_target_directory = None
                        event.ignore()
                else:
                    self._drop_target_directory = None
                    event.ignore()
        else:
            self._drop_target_directory = None
            event.ignore()

        # Update highlight if it changed
        if self.highlighted_index != new_highlight_index:
            # Clear old highlight
            if self.highlighted_index is not None and self.highlighted_index.isValid():
                old_rect = self.visualRect(self.highlighted_index)
                self.viewport().update(old_rect)

            # Set new highlight
            self.highlighted_index = new_highlight_index
            if new_highlight_index is not None and new_highlight_index.isValid():
                new_rect = self.visualRect(new_highlight_index)
                self.viewport().update(new_rect)

        # Auto-scroll when cursor near top/bottom edge during drag
        self._update_drag_auto_scroll(event.pos())

    def dragLeaveEvent(self, event) -> None:
        """Handle drag leave events"""
        self._stop_drag_auto_scroll()
        # Clear highlight
        if self.highlighted_index is not None and self.highlighted_index.isValid():
            self.viewport().update(self.visualRect(self.highlighted_index))
            self.highlighted_index = None
        self._drop_target_directory = None
        event.accept()

    def _update_drag_auto_scroll(self, pos: QPoint) -> None:
        """Update auto-scroll state based on cursor position during drag. Narrow band, slow speeds."""
        viewport = self.viewport()
        viewport_height = viewport.height()
        viewport_width = viewport.width()

        # event.pos() is viewport-relative for QAbstractItemView (Qt docs)
        y_in_viewport = pos.y()
        x_in_viewport = pos.x()

        # When cursor is above viewport (y<0) or below (y>height), treat as edge trigger - continue scrolling
        # Don't stop: user dragging to top/bottom often moves cursor into header or past viewport
        if x_in_viewport < 0 or x_in_viewport > viewport_width:
            self._stop_drag_auto_scroll()
            return

        # Clamp y to viewport for distance calc; values outside mean "at edge" (keep scrolling)
        distance_from_top = max(0, y_in_viewport)
        distance_from_bottom = max(0, viewport_height - y_in_viewport)

        scroll_direction = 0
        scroll_speed = 0.0

        band_max = TREE_DRAG_AUTO_SCROLL_SPEEDS[0][0]
        if distance_from_top < distance_from_bottom:
            if distance_from_top <= band_max:
                scroll_direction = -1
                scroll_speed = self._calculate_tree_scroll_speed(distance_from_top)
        else:
            if distance_from_bottom <= band_max:
                scroll_direction = 1
                scroll_speed = self._calculate_tree_scroll_speed(distance_from_bottom)

        if scroll_direction != 0 and scroll_speed > 0:
            if self._auto_scroll_direction != scroll_direction or self._auto_scroll_speed != scroll_speed:
                self._auto_scroll_direction = scroll_direction
                self._auto_scroll_speed = scroll_speed
                if not self._auto_scroll_timer.isActive():
                    self._auto_scroll_timer.start(TREE_DRAG_AUTO_SCROLL_TIMER_MS)  # was 15
        else:
            self._stop_drag_auto_scroll()

    def _calculate_tree_scroll_speed(self, distance_from_edge: float) -> float:
        """Calculate scroll speed from distance using TREE_DRAG_AUTO_SCROLL_SPEEDS (same interpolation as thumbnail)."""
        if not TREE_DRAG_AUTO_SCROLL_SPEEDS:
            return 0.0
        for i in range(len(TREE_DRAG_AUTO_SCROLL_SPEEDS)):
            dist, speed = TREE_DRAG_AUTO_SCROLL_SPEEDS[i]
            if distance_from_edge >= dist:
                if i == 0:
                    return speed
                prev_dist, prev_speed = TREE_DRAG_AUTO_SCROLL_SPEEDS[i - 1]
                if prev_dist == dist:
                    return speed
                ratio = (distance_from_edge - dist) / (prev_dist - dist)
                return speed + ratio * (prev_speed - speed)
        return TREE_DRAG_AUTO_SCROLL_SPEEDS[-1][1]

    def _handle_drag_auto_scroll(self) -> None:
        """Timer callback: perform one step of auto-scroll during drag."""
        if self._auto_scroll_direction == 0 or self._auto_scroll_speed == 0:
            self._stop_drag_auto_scroll()
            return

        scroll_bar = self.verticalScrollBar()
        viewport = self.viewport()
        viewport_height = viewport.height()

        current_value = scroll_bar.value()
        max_value = scroll_bar.maximum()

        if self._auto_scroll_direction < 0 and current_value <= 0:
            self._stop_drag_auto_scroll()
            return
        if self._auto_scroll_direction > 0 and current_value >= max_value:
            self._stop_drag_auto_scroll()
            return

        scroll_amount = (self._auto_scroll_speed *
                         viewport_height / 100.0) * (16.0 / 1000.0)
        self._scroll_accumulator += self._auto_scroll_direction * scroll_amount
        step = int(self._scroll_accumulator)
        self._scroll_accumulator -= step
        new_value = current_value + step
        new_value = max(0, min(new_value, max_value))
        scroll_bar.setValue(new_value)

    def _stop_drag_auto_scroll(self) -> None:
        """Stop auto-scroll timer and clear state."""
        if self._auto_scroll_timer.isActive():
            self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        self._auto_scroll_speed = 0.0
        self._scroll_accumulator = 0.0

    def dropEvent(self, event: QDropEvent) -> None:
        """Handle drop events - move files to the target directory"""
        self._stop_drag_auto_scroll()
        # Clear highlight
        if self.highlighted_index is not None and self.highlighted_index.isValid():
            self.viewport().update(self.visualRect(self.highlighted_index))
            self.highlighted_index = None
        self._drop_target_directory = None

        if not event.mimeData().hasUrls():
            event.ignore()
            return

        # Get the target directory
        index = self.indexAt(event.pos())
        if not index.isValid():
            event.ignore()
            return

        model = self.model()
        if not model:
            event.ignore()
            return

        source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
        if not source_index.isValid() or not hasattr(model, 'sourceModel'):
            event.ignore()
            return

        target_directory = model.sourceModel().filePath(source_index)
        if not os.path.isdir(target_directory):
            event.ignore()
            return

        # Extract file paths from URLs
        urls = event.mimeData().urls()
        file_paths = [url.toLocalFile() for url in urls if url.isLocalFile()
                      and os.path.isfile(url.toLocalFile())]

        if not file_paths:
            event.ignore()
            return

        # Check if target is a Photos Library - prevent operations within Photos Libraries
        from utils import is_inside_photos_library, show_styled_warning

        target_in_library = is_inside_photos_library(target_directory)

        # Check if any source files are in Photos Library
        photos_library_sources = [path for path in file_paths if is_inside_photos_library(path)]
        any_source_in_library = len(photos_library_sources) > 0

        # Check if this is dragging OUT of Photos Library (allowed, but must be copy)
        # or dragging INTO/within Photos Library (not allowed)
        if target_in_library:
            if any_source_in_library:
                # This is a within-library operation - not allowed
                show_styled_warning(self.main_window,
                    "Operation Not Allowed",
                    "File operations within macOS Photos Library are not allowed.\n\n"
                    "Photos Library files cannot be moved, renamed, or modified within the library.\n"
                    "You can drag files OUT of the Photos Library to other locations."
                )
                event.ignore()
                return
            else:
                # Dragging external files INTO Photos Library - not allowed
                show_styled_warning(self.main_window,
                    "Operation Not Allowed",
                    "Adding files to macOS Photos Library is not allowed.\n\n"
                    "Please use the Photos app to add files to your Photos Library."
                )
                event.ignore()
                return

        # Determine the drop action early to check if this is a copy or move
        # If dragging OUT of Photos Library, force copy operation (never move)
        if any_source_in_library:
            drop_action = Qt.CopyAction  # Force copy for Photos Library files
        else:
            drop_action = event.dropAction()
            if drop_action != Qt.CopyAction and drop_action != Qt.MoveAction:
                # Default to move for compatibility
                drop_action = Qt.MoveAction

        # Check for locked files - only prevent MOVING locked files to different directory
        # Copying locked files is allowed (when Option key is pressed)
        if drop_action == Qt.MoveAction:
            locked_files = []
            if hasattr(self.main_window, 'lock_manager') and self.main_window.lock_manager:
                for path in file_paths:
                    source_dir = os.path.dirname(path)
                    target_dir = os.path.realpath(target_directory)
                    source_dir_real = os.path.realpath(source_dir)
                    # Only prevent if moving to different directory (internal reordering is allowed)
                    if source_dir_real != target_dir and self.main_window.lock_manager.is_file_locked(path):
                        locked_files.append(os.path.basename(path))

            if locked_files:
                show_styled_warning(self.main_window,
                    "Cannot Move Locked Files",
                    f"The following files are locked and cannot be moved:\n\n" +
                    "\n".join(locked_files[:10]) +  # Show first 10
                    (f"\n... and {len(locked_files) - 10} more" if len(locked_files) > 10 else "") +
                    "\n\nPlease unlock the files (Shift-Cmd-L) before moving them, or hold Option to copy instead."
                )
                event.ignore()
                return

        # Store the last drop location for "Move to last drop location" feature
        self._last_drop_location = target_directory

        # Update menu state to activate cmd-0 key without showing menu
        if self.main_window and hasattr(self.main_window, 'update_edit_menu_states'):
            self.main_window.update_edit_menu_states()
        # Refresh Shortcuts sidebar to show updated cmd-0 destination
        if (self.main_window and getattr(self.main_window, 'right_sidebar', None) and
                hasattr(self.main_window.right_sidebar, 'shortcuts_widget') and
                self.main_window.right_sidebar.shortcuts_widget and
                self.main_window.right_sidebar.is_shortcuts_visible()):
            self.main_window.right_sidebar.shortcuts_widget.refresh_shortcuts()

        # Execute the appropriate operation based on drop action
        if drop_action == Qt.CopyAction:
            # Copy operation (allowed even for locked files)
            self._handle_file_copy(file_paths, target_directory)
            event.setDropAction(Qt.CopyAction)
        else:
            # Move operation
            self._handle_file_move(file_paths, target_directory)
            event.setDropAction(Qt.MoveAction)

        event.acceptProposedAction()

    def _handle_file_copy(self, file_paths: List[str], target_directory: str) -> None:
        """Handle copying files to target directory with overwrite checks"""
        copied_count = 0
        skipped_count = 0
        errors = []  # Collect error messages for failed copies

        if not self.file_move_handler:
            self.file_move_handler = FileMoveHandler(self.main_window)

        # Show progress dialog for > 10 files
        progress_dialog = None
        if len(file_paths) > 10:
            from utils import create_file_operation_progress_dialog
            progress_dialog = create_file_operation_progress_dialog(self.main_window, "Copying Files", len(file_paths)
            )

        # Track "apply to all" state
        apply_to_all_state = {}
        _paths_to_clear_after_copy = []

        for idx, source_path in enumerate(file_paths):
            # Use common handler to resolve target path (handles overwrite dialog and rename)
            target_path, should_cancel = self.file_move_handler.resolve_target_path(source_path, target_directory, apply_to_all_state
            )

            if should_cancel:
                # User cancelled the entire operation
                break

            if target_path is None:
                skipped_count += 1
                # Update progress even for skipped files
                if progress_dialog:
                    progress_dialog.setValue(idx + 1)
                    progress_dialog.setLabelText(f"Copying file {idx + 1} of {len(file_paths)}")
                    QApplication.processEvents()
                continue

            # Update progress before copying
            if progress_dialog:
                progress_dialog.setValue(idx)
                progress_dialog.setLabelText(f"Copying file {idx + 1} of {len(file_paths)}")
                QApplication.processEvents()

            # Copy the file
            try:
                shutil.copy2(source_path, target_path)
                copied_count += 1
                if self.main_window and hasattr(self.main_window, 'cache_manager'):
                    _paths_to_clear_after_copy.append(target_path)

                # Update progress after successful copy
                if progress_dialog:
                    progress_dialog.setValue(idx + 1)
                    progress_dialog.setLabelText(f"Copying file {idx + 1} of {len(file_paths)}")
                    QApplication.processEvents()
            except Exception as e:
                print(f"Error copying file {source_path} to {target_directory}: {e}")
                errors.append(os.path.basename(source_path))
                skipped_count += 1
                # Update progress even on error
                if progress_dialog:
                    progress_dialog.setValue(idx + 1)
                    progress_dialog.setLabelText(f"Copying file {idx + 1} of {len(file_paths)}")
                    QApplication.processEvents()

        # Close progress dialog if it was shown
        if progress_dialog:
            progress_dialog.setValue(len(file_paths))
            progress_dialog.close()

        # Show error dialog if there were failures
        if errors:
            if len(errors) == 1:
                # Single file failed - show filename
                show_styled_critical(self.main_window,
                    "Copy Failed",
                    f"Failed to copy file:\n\n{errors[0]}\n\n"
                    f"Destination: {target_directory}\n\n"
                    f"Please check file permissions and try again."
                )
            else:
                # Multiple files failed - show count
                show_styled_critical(self.main_window,
                    "Copy Failed",
                    f"Failed to copy {len(errors)} {file_string(len(errors))}.\n\n"
                    f"Destination: {target_directory}\n\n"
                    f"Please check file permissions and try again."
                )

        # Show status message
        if copied_count > 0:
            if skipped_count > 0:
                self.main_window.status_notification.show_message(f"Copied {copied_count} {file_string(copied_count)}, skipped {skipped_count}"
                )
            else:
                self.main_window.status_notification.show_message(f"Copied {copied_count} {file_string(copied_count)} to {os.path.basename(target_directory)}"
                )
        else:
            self.main_window.status_notification.show_message("No files copied")

        # Batch clear cache for copied files (avoids N listdirs and O(N*cache_size) work)
        if _paths_to_clear_after_copy and self.main_window and hasattr(self.main_window, 'cache_manager'):
            self.main_window.cache_manager.clear_cache_for_files_batch(_paths_to_clear_after_copy)

        # Don't clear selections for copy operations (files still exist in original location)
        # Refresh directory if needed
        if self.main_window and hasattr(self.main_window, 'debounce_refresh_directory'):
            QTimer.singleShot(100, self.main_window.debounce_refresh_directory)

    def _handle_file_move(self, file_paths: List[str], target_directory: str) -> None:
        """Handle moving files to target directory with overwrite checks.
        Processes files one at a time (copy then delete) to detect read-only source errors early."""
        moved_count = 0
        skipped_count = 0
        user_cancelled = False  # User pressed Esc/Cancel on overwrite dialog - no error to show
        errors = []  # Collect error messages for detailed reporting
        failed_filenames = []  # Track filenames that failed to move/copy
        successfully_moved_files = []  # Track files that were successfully moved
        moved_files_info = []  # Track move info for undo

        # Check for Photos Library operations
        from utils import is_inside_photos_library, show_styled_warning

        target_in_library = is_inside_photos_library(target_directory)

        # Check if this is dragging OUT of Photos Library (allowed)
        # or dragging INTO/within Photos Library (not allowed)
        if target_in_library:
            # Check if any source is also in Photos Library (within-library operation)
            any_source_in_library = any(is_inside_photos_library(path) for path in file_paths)
            if any_source_in_library:
                # This is a within-library operation - not allowed
                show_styled_warning(self.main_window,
                    "Operation Not Allowed",
                    "File operations within macOS Photos Library are not allowed.\n\n"
                    "Photos Library files cannot be moved, renamed, or modified within the library.\n"
                    "You can drag files OUT of the Photos Library to other locations."
                )
                return
            else:
                # Dragging external files INTO Photos Library - not allowed
                show_styled_warning(self.main_window,
                    "Operation Not Allowed",
                    "Adding files to macOS Photos Library is not allowed.\n\n"
                    "Please use the Photos app to add files to your Photos Library."
                )
                return

        if not self.file_move_handler:
            self.file_move_handler = FileMoveHandler(self.main_window)

        # Capture the active file BEFORE any moves (this is the file that should determine next selection)
        active_file_path = None
        if self.main_window:
            active_file_path = self.main_window.get_current_image_path()

        # Track "apply to all" state
        apply_to_all_state = {}

        # Check if destination is writable before starting
        if not os.access(target_directory, os.W_OK):
            show_styled_critical(self.main_window,
                "Cannot Move Files",
                f"Cannot move files to destination:\n\n{target_directory}\n\n"
                f"Reason: Destination is read-only or you don't have write permission.\n\n"
                f"Please check the destination permissions or choose a different location."
            )
            return

        # Show progress dialog for > 10 files
        progress_dialog = None
        if len(file_paths) > 10:
            from utils import create_file_operation_progress_dialog
            progress_dialog = create_file_operation_progress_dialog(self.main_window, "Moving Files", len(file_paths)
            )

        for idx, source_path in enumerate(file_paths):
            # Update progress if dialog is shown
            if progress_dialog:
                progress_dialog.setValue(idx)
                progress_dialog.setLabelText(f"Moving file {idx + 1} of {len(file_paths)}")
                QApplication.processEvents()
            # Use common handler to resolve target path (handles overwrite dialog and rename)
            target_path, should_cancel = self.file_move_handler.resolve_target_path(
                source_path, target_directory, apply_to_all_state
            )

            if should_cancel:
                # User cancelled the entire operation (Esc or Cancel on overwrite dialog)
                user_cancelled = True
                break

            if target_path is None:
                skipped_count += 1
                continue

            # Process move one at a time: copy first, then delete source
            try:
                # Copy the file to destination
                try:
                    shutil.copy2(source_path, target_path)
                except (OSError, PermissionError) as copy_error:
                    # Destination is read-only or permission denied
                    failed_filename = os.path.basename(source_path)
                    failed_filenames.append(failed_filename)
                    error_msg = f"Cannot copy '{failed_filename}' to destination."
                    error_detail = f"Error: {str(copy_error)}\n\n"
                    error_detail += f"Destination: {target_directory}\n"
                    if "read-only" in str(copy_error).lower() or "permission denied" in str(copy_error).lower():
                        error_detail += "\nThe destination directory is read-only or you don't have write permission."
                    errors.append(f"{error_msg}\n{error_detail}")
                    skipped_count += 1
                    continue

                # Try to delete the source file
                try:
                    os.remove(source_path)
                    moved_count += 1
                    successfully_moved_files.append(source_path)
                    displayed = self.main_window.get_displayed_images() if self.main_window else []
                    original_position = displayed.index(source_path) if source_path in displayed else None
                    moved_files_info.append({
                        'source_path': source_path,
                        'target_path': target_path,
                        'original_position': original_position
                    })
                    # Note: We'll remove files from displayed images after all moves complete
                    # to ensure proper next image selection based on original active file
                except (OSError, PermissionError) as delete_error:
                    # Source file could not be deleted (likely read-only folder)
                    # Remove the copied file since move failed
                    try:
                        os.remove(target_path)
                    except Exception:
                        pass  # Ignore errors removing the copy

                    # Ask user if they want to cancel the move operation
                    error_msg = f"Cannot delete source file '{os.path.basename(source_path)}'.\n\n"
                    error_msg += f"Error: {str(delete_error)}\n\n"
                    error_msg += "The file has been copied but the source could not be deleted.\n"
                    error_msg += "Do you want to cancel the remaining move operations?"

                    # Use centralized styled message box
                    from utils import styled_message_box
                    from PySide6.QtWidgets import QMessageBox
                    error_dialog = styled_message_box(
                        self.main_window,
                        QMessageBox.Critical,
                        "Move Operation Failed",
                        error_msg,
                        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        default_button=QMessageBox.StandardButton.Yes
                    )
                    error_dialog.exec()
                    reply = error_dialog.result_data['button'] if error_dialog.result_data.get('button') else QMessageBox.StandardButton.Yes

                    if reply == QMessageBox.StandardButton.Yes:
                        # User wants to cancel remaining operations
                        break
                    else:
                        # User wants to continue (skip this file)
                        skipped_count += 1
                        continue

            except Exception as e:
                print(f"Error moving file {source_path} to {target_directory}: {e}")
                failed_filename = os.path.basename(source_path)
                failed_filenames.append(failed_filename)
                error_msg = f"Error moving '{failed_filename}': {str(e)}"
                errors.append(error_msg)
                skipped_count += 1

        # Close progress dialog if it was shown
        if progress_dialog:
            progress_dialog.setValue(len(file_paths))
            progress_dialog.close()

        # Batch clear cache for moved files (avoids N listdirs and O(N*cache_size) work)
        if successfully_moved_files and self.main_window and hasattr(self.main_window, 'cache_manager'):
            self.main_window.cache_manager.clear_cache_for_files_batch(successfully_moved_files)

        # Register move operations for undo
        if moved_files_info and self.main_window and getattr(self.main_window, 'file_operations_manager', None):
            self.main_window.file_operations_manager._register_undo_for_moved_files(moved_files_info, moved_count)

        # Show error dialog if there were failures
        if failed_filenames:
            if len(failed_filenames) == 1:
                # Single file failed - show filename
                show_styled_critical(
                    self.main_window,
                    "Move Failed",
                    f"Failed to move file:\n\n{failed_filenames[0]}\n\n"
                    f"Destination: {target_directory}\n\n"
                    f"Please check file permissions and try again."
                )
            else:
                # Multiple files failed - show count
                show_styled_critical(self.main_window,
                    "Move Failed",
                    f"Failed to move {len(failed_filenames)} {file_string(len(failed_filenames))}.\n\n"
                    f"Destination: {target_directory}\n\n"
                    f"Please check file permissions and try again."
                )

        # Show status message or error dialog
        if moved_count > 0:
            if skipped_count > 0:
                self.main_window.status_notification.show_message(f"Moved {moved_count} {file_string(moved_count)}, skipped {skipped_count}"
                )
            else:
                self.main_window.status_notification.show_message(f"Moved {moved_count} {file_string(moved_count)} to {os.path.basename(target_directory)}"
                )

        # Show error dialog if no files were moved (but only if not already shown above)
        # Don't show error when user cancelled (Esc) or chose No to skip - those are intentional, not failures
        if moved_count == 0 and not failed_filenames and not user_cancelled and skipped_count == 0:
            error_title = "Cannot Move Files"
            error_text = f"Cannot move files to destination:\n\n{target_directory}\n\n"
            error_text += "No files were moved. All files may have been skipped due to overwrite conflicts."
            show_styled_critical(self.main_window,
                error_title,
                error_text
            )

        # Remove successfully moved files from displayed images and update selection
        # Do this after all moves complete to ensure proper next image selection based on original active file
        if successfully_moved_files and self.main_window and hasattr(self.main_window, 'remove_thumbnails_for_files'):
            self.main_window.remove_thumbnails_for_files(successfully_moved_files, active_file_path)

        # Remove successfully moved files from selections, keep other selections intact
        if self.main_window and hasattr(self.main_window, 'selected_files') and successfully_moved_files:
            self.main_window.selected_files.difference_update(successfully_moved_files)
            if hasattr(self.main_window, '_emit_selection_changed'):
                self.main_window._emit_selection_changed()

        # Refresh directory if needed
        if self.main_window and hasattr(self.main_window, 'debounce_refresh_directory'):
            QTimer.singleShot(100, self.main_window.debounce_refresh_directory)

# --- CustomFileSystemFilter: optimized for filter performance ---


class CustomFileSystemFilter(QSortFilterProxyModel):

    def __init__(self, parent: Optional[QObject] = None, main_window: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.filter_callback: Optional[Callable[[str], bool]] = None
        self.canvas_images: Set[str] = set()
        self.filter_pattern: Optional[str] = None
        self.filtered_tree: str = 'images'  # 'all', 'images', or 'use_filter'
        self.priority_paths: Set[str] = set()
        # Cache for _has_images_in_directory results
        self.has_images_cache: Dict[str, bool] = {}
        # Store main_window reference for rename status checking
        self.main_window: Optional[Any] = main_window
        # Cache for follow_symlinks setting to avoid repeated file I/O
        self._cached_follow_symlinks: Optional[bool] = None
        self._excluded_directories: Set[str] = {
            '/Users/Deleted Users',
            # os.path.expanduser('~/Library'),
            # os.path.expanduser('~/Applications'),
            '/.nofollow', '/.resolve', '/.vol', '/.Trashes', '/.Trash', '/.fseventsd',
            '/.Spotlight-V100', '/.DocumentRevisions-V100', '/.MobileBackups',
            '/.PKInstallSandboxManager-SystemSoftware', '/.file', '/.vol'
        }
        # Add ignore directories from settings (only enabled ones)
        try:
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            ignore_dirs = settings.get('ignore_directories', [])
            if isinstance(ignore_dirs, list):
                for ignore_dir in ignore_dirs:
                    if isinstance(ignore_dir, dict):
                        path = ignore_dir.get('path')
                        enabled = ignore_dir.get('enabled', False)
                        if enabled and path and isinstance(path, str) and path.strip():
                            # Expand ~ to full path before adding to excluded set
                            expanded_path = os.path.expanduser(path.strip())
                            self._excluded_directories.add(expanded_path)
                    elif ignore_dir and isinstance(ignore_dir, str) and ignore_dir.strip():
                        # Backward compatibility: if it's just a string, treat as enabled
                        expanded_path = os.path.expanduser(ignore_dir.strip())
                        self._excluded_directories.add(expanded_path)
        except Exception:
            pass

    def normalize_filtered_tree_mode(self) -> str:
        """Normalize filtered_tree to string format, handling boolean backward compatibility."""
        if isinstance(self.filtered_tree, bool):
            self.filtered_tree = 'use_filter' if self.filtered_tree else 'images'
        return self.filtered_tree

    def set_filter_pattern(self, pattern: Optional[str]) -> None:
        # Normalize pattern for storage (remove trailing asterisk)
        self.filter_pattern = ImageBrowserConfig.normalize_filter_pattern(pattern)
        self.invalidateFilter()
        self.layoutChanged.emit()

    def set_filtered_tree(self, mode: str) -> None:
        """Set tree filtering mode: 'all', 'images', or 'use_filter'

        Args:
            mode: 'all' = show all folders without checking for images
                  'images' = show directories with any images
                  'use_filter' = show directories with images matching filter pattern
        """
        # Convert boolean to string for backward compatibility
        if isinstance(mode, bool):
            mode = 'use_filter' if mode else 'images'

        if self.filtered_tree != mode:
            self.filtered_tree = mode
            self.invalidateFilter()
            self.layoutChanged.emit()

    def _quick_check_matching_images(self, dir_path: str) -> bool:
        """Fast check for matching images in immediate directory only (for icon coloring).
        Returns False if mode is 'all' (no image checking needed).
        Always respects filter_pattern if mode is 'use_filter'."""
        # If mode is 'all', don't check for images - return False to use default icon
        if self.filtered_tree == 'all':
            return False

        if not os.path.isdir(dir_path):
            return False
        try:
            # Quick check of immediate directory only - much faster than subprocess
            for entry in os.listdir(dir_path):
                entry_path = f"{dir_path.rstrip('/')}/{entry}"
                if os.path.isfile(entry_path):
                    if get_file_extension(entry) in get_image_extensions():
                        # If mode is 'use_filter', check filter pattern
                        if self.filtered_tree == 'use_filter':
                            if self.filter_pattern and self.filter_pattern.strip('*') != '':
                                match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(self.filter_pattern)
                                if match_pattern and fnmatch.fnmatch(entry.lower(), match_pattern.lower()):
                                    return True
                            else:
                                # No pattern or pattern is '*', any image matches
                                return True
                        elif self.filtered_tree == 'images':
                            # Mode is 'images', any image matches
                            return True
        except (OSError, PermissionError):
            return False
        return False

    def _has_images_in_directory(self, dir_path: str) -> bool:
        """
        Efficiently check if directory has any images (recursively, up to search_depth setting).
        - If filtered_tree is 'all', always returns True.
        - If filtered_tree is 'use_filter' and a filter pattern is set, only matches files with that pattern.
        """
        # Get depth from settings - include in cache key to invalidate when depth changes
        try:
            config = get_config()
            settings = config.load_settings()
            max_depth = int(settings.get('search_depth', 4))
        except Exception:
            max_depth = 4

        mode = self.normalize_filtered_tree_mode()

        # Include depth, mode, and filter pattern in cache key to ensure cache is invalidated when any of these change
        filter_pattern_key = self.filter_pattern if (mode == 'use_filter' and self.filter_pattern) else ''
        cache_key = f"{dir_path}:{max_depth}:{mode}:{filter_pattern_key}"
        if cache_key in self.has_images_cache:
            return self.has_images_cache[cache_key]
        if mode == 'all':
            self.has_images_cache[cache_key] = True
            return True

        if not os.path.isdir(dir_path):
            self.has_images_cache[cache_key] = False
            return False

        try:
            found = False

            # Get all allowed image extensions, prioritize jpg/jpeg
            image_exts = [e.lstrip('.').lower() for e in get_image_extensions() if e]
            if not image_exts:
                self.has_images_cache[cache_key] = False
                return False

            prioritized_exts = []
            other_exts = image_exts.copy()
            if 'jpg' in other_exts:
                prioritized_exts.append('jpg')
                other_exts.remove('jpg')
            if 'jpeg' in other_exts:
                prioritized_exts.append('jpeg')
                other_exts.remove('jpeg')

            if mode == 'use_filter' and self.filter_pattern:
                match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(self.filter_pattern)
            else:
                match_pattern = None

            if dir_path.endswith(os.sep):
                basecount = dir_path.rstrip(os.sep).count(os.sep)
            else:
                basecount = dir_path.count(os.sep)

            # For efficiency, define the match function directly
            def matches(fname):
                # fname should be just the filename, not the full path
                basename = os.path.basename(fname)
                ext = os.path.splitext(basename)[1][1:].lower()
                # First check if it's an image file
                if ext not in image_exts:
                    return False
                # If filtering is active, also check pattern match (case-insensitive)
                if mode == 'use_filter' and match_pattern and match_pattern != '*':
                    # Use case-insensitive matching to match behavior elsewhere in codebase
                    # Only match against the filename, not the directory path
                    return fnmatch.fnmatch(basename.lower(), match_pattern.lower())
                # If not filtering or pattern is '*', any image file matches
                return True

            # Get process hidden directories setting
            process_hidden = get_show_hidden_directories()
            # Get follow symlinks setting
            follow_symlinks = get_follow_symlinks()
            # Match expand_file_tree / directory listing: do not count images in cache,
            # Photos Library internals, or ignore_directories (same as path_exclusions).
            try:
                _cfg = get_config()
                excluded_paths = _get_excluded_paths(_cfg)
                cache_dir_resolved = os.path.realpath(str(_cfg.cache_dir))
            except Exception:
                excluded_paths = []
                cache_dir_resolved = None

            for root, dirs, files in os.walk(dir_path):
                root_resolved = os.path.realpath(root)
                if _is_excluded_path(root_resolved, excluded_paths):
                    dirs.clear()
                    continue
                if cache_dir_resolved and (root_resolved == cache_dir_resolved or
                                           root_resolved.startswith(cache_dir_resolved + os.sep)):
                    dirs.clear()
                    continue

                # Depth check
                rel_depth = root.count(os.sep) - basecount
                if rel_depth >= max_depth:
                    dirs.clear()
                    continue

                # Filter hidden directories if not processing them
                if not process_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]

                # Filter symlinks if not following them (except enabled root dirs on Directories tab)
                filter_walk_symlink_dirs(root, dirs, follow_symlinks)

                # Skip SKIPPED_PATTERNS directories
                skip_dir = False
                for pattern in SKIPPED_PATTERNS:
                    if pattern in root:
                        skip_dir = True
                        break
                if skip_dir:
                    dirs.clear()
                    continue

                if is_inside_photos_library_resources_or_scopes(root):
                    dirs.clear()
                    continue

                # Prioritize jpg/jpeg for fastest early exit
                for fname in files:
                    ext = os.path.splitext(fname)[1][1:].lower()
                    if ext in prioritized_exts and matches(fname):
                        found = True
                        break
                if found:
                    break

                # Then check other image extensions
                for fname in files:
                    ext = os.path.splitext(fname)[1][1:].lower()
                    if ext in other_exts and matches(fname):
                        found = True
                        break
                if found:
                    break

            self.has_images_cache[cache_key] = found
            return found

        except Exception:
            self.has_images_cache[cache_key] = False
            return False

    def clear_search_cache_for_directory(self, directory_path: str):
        """Clear search cache entries for a specific directory (non-recursive)

        Args:
            directory_path: Path to directory to clear search cache for
        """
        if not os.path.isdir(directory_path):
            return

        # Normalize directory path to absolute path for consistent matching
        # Handle both with and without trailing slash
        abs_dir_path = os.path.abspath(directory_path)
        abs_dir_path_no_slash = abs_dir_path.rstrip(os.sep)
        abs_dir_path_with_slash = abs_dir_path + \
            os.sep if not abs_dir_path.endswith(os.sep) else abs_dir_path

        # Remove cache entries where the directory path in the cache key exactly matches
        # Cache keys are formatted as: f"{dir_path}:{max_depth}:{mode}:{filter_pattern_key}"
        keys_to_remove = []
        for cache_key in list(self.has_images_cache.keys()):
            # Extract directory path from cache key (first part before ':')
            if ':' in cache_key:
                cached_dir_path = cache_key.split(':', 1)[0]
                cached_abs = os.path.abspath(cached_dir_path)
                cached_abs_no_slash = cached_abs.rstrip(os.sep)
                # Match if paths are the same (handling trailing slash variations)
                if (cached_abs == abs_dir_path or
                    cached_abs == abs_dir_path_no_slash or
                    cached_abs == abs_dir_path_with_slash or
                        cached_abs_no_slash == abs_dir_path_no_slash):
                    keys_to_remove.append(cache_key)

        # Remove matching entries
        for key in keys_to_remove:
            if key in self.has_images_cache:
                del self.has_images_cache[key]

    def _get_follow_symlinks_cached(self) -> bool:
        """Get follow symlinks setting with caching to avoid repeated file I/O"""
        if self._cached_follow_symlinks is None:
            self._cached_follow_symlinks = get_follow_symlinks()
        return self._cached_follow_symlinks

    def _refresh_follow_symlinks_cache(self) -> None:
        """Refresh cached follow_symlinks value (call when settings change)"""
        self._cached_follow_symlinks = None

    def _should_check_for_images(self, dir_path: str) -> bool:
        # Don't check for images in root directories - they should always be shown
        # Use the enabled root directories from config plus '/' for the root itself
        # Note: This method is in filter proxy, which doesn't have access to handler instance
        # So we still use the global function here
        root_directories = get_enabled_root_directories() | {'/'}
        return dir_path not in root_directories

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        source_index = self.sourceModel().index(source_row, 0, source_parent)
        if not source_index.isValid():
            return False

        # Use Qt's fileInfo() which is faster than os.path.isdir() since it uses cached model data
        source_model = self.sourceModel()
        file_info = source_model.fileInfo(source_index)

        file_path = source_model.filePath(source_index)
        if not file_path:
            return False

        # Filter out symlinks when follow_symlinks is False, except enabled root dirs
        # on the Directories tab (e.g. macOS /tmp, /etc, /var which are symlinks).
        # Check before isDir() because symlinks to directories pass isDir().
        if not self._get_follow_symlinks_cached():
            normalized_path = os.path.normpath(file_path)
            is_symlink = os.path.islink(normalized_path) or file_info.isSymLink()
            if is_symlink and not is_enabled_root_symlink(normalized_path):
                return False

        # Early exit for files - check directory status first before any other operations
        if not file_info.isDir():
            return False

        filename = os.path.basename(file_path)

        # Rest of the directory filtering logic...
        # Always show enabled root-level directories on macOS - they should always be visible
        # Note: This method is called from filter proxy, which doesn't have access to handler instance
        # So we still use the global function here
        enabled_root_dirs = get_enabled_root_directories()

        if not hasattr(self, '_debug_count'):
            self._debug_count = 0
        if self._debug_count < 10:
            self._debug_count += 1

        # Check if enabled root directory first (matches HEAD behavior)
        # NOTE: Symlink check already happened above, so symlinks won't reach here
        if file_path in enabled_root_dirs:
            return True

        # Check priority paths and bold path BEFORE filtering out root directories
        # This ensures that root directories in these lists are still shown even if not enabled
        # However, when filtering is active, we still need to check for matching images
        # NOTE: Symlink check already happened above, so symlinks won't reach here
        mode = self.normalize_filtered_tree_mode()
        # Fast check: if this path or any of its children are in priority_paths, show it
        # This avoids expensive find commands for directories that contain priority paths
        # However, when filtering is active, we still need to check for matching images
        # NOTE: Symlink check already happened above, so symlinks won't reach here
        in_priority_paths = False
        for p in self.priority_paths:
            if p == file_path or p.startswith(file_path + os.sep):
                in_priority_paths = True
                break
        if in_priority_paths:
            # When filtering, still check if directory has matching images
            if mode == 'use_filter':
                if self._should_check_for_images(file_path) and not self._has_images_in_directory(file_path):
                    return False
            return True

        # Check if this is a root-level directory (parent is "/") that is NOT enabled
        # If so, exclude it from the tree view (but only if not in priority_paths)
        # Use os.path.dirname to check if parent is root - this reliably detects root-level directories
        # Note: Exclude the root directory "/" itself from this check (it should be shown)
        if file_path != "/" and os.path.dirname(file_path) == "/":
            # This is a root-level directory that is not enabled, so exclude it
            return False
        # Check if path is excluded (exact match or subdirectory of excluded path)
        for excluded_path in self._excluded_directories:
            if file_path == excluded_path or file_path.startswith(excluded_path + os.sep):
                return False
        filename_lower = filename.lower()
        if any(filename_lower.endswith(ext) for ext in EXCLUDED_EXTENSIONS):
            return False
        # Check if this is a 'work' directory and always_show_work is enabled
        if get_always_show_work() and filename_lower == 'work':
            return True
        # Allow directories starting with a period (e.g., .git, .vscode)
        # If mode is 'all', skip image checking entirely
        # (mode was already set above when checking priority_paths)
        if mode != 'all':
            if self._should_check_for_images(file_path) and not self._has_images_in_directory(file_path):
                return False
        return True

    def data(self, index: QModelIndex, role: int) -> Any:
        # Override folder icon with colored folder icons based on mode and image content
        # Yellow for directories with matching images, light blue for directories without matching images
        # Green for all directories when mode is 'all'
        if role == Qt.DecorationRole:
            # Only override for the first (name) column
            if index.column() == 0:
                # Access the source model and determine if this index is a directory
                source_index = self.mapToSource(index)
                source_model = self.sourceModel()
                if source_index.isValid() and source_model:
                    file_path = source_model.filePath(source_index)
                    if os.path.isdir(file_path):
                        # Normalize filtered_tree mode
                        mode = self.normalize_filtered_tree_mode()

                        # If mode is 'all', use yellow folder icon with reddish border
                        if mode == 'all':
                            folder_color = TREE_FOLDER_WITH_IMAGES_COLOR
                            # Reddish (Indian Red)
                            border_color = QColor("#F98888")
                            has_border = True
                        else:
                            # Fast icon check: use lightweight check ONLY - no subprocess calls that could block
                            # Wrap in try-except to prevent any errors from breaking tree expansion
                            has_matching_images = False
                            try:
                                # Only use fast check - no subprocess calls in icon rendering path
                                has_matching_images = self._quick_check_matching_images(file_path)
                            except Exception:
                                # If check fails for any reason, default to light blue (no matching images)
                                has_matching_images = False

                            # Compose folder color based on matching images
                            folder_color = TREE_FOLDER_WITH_IMAGES_COLOR if has_matching_images else QColor("#add8e6")
                            has_border = False

                        pixmap = QPixmap(16, 16)
                        pixmap.fill(Qt.transparent)
                        painter = QPainter(pixmap)
                        painter.setRenderHint(QPainter.Antialiasing)

                        # Create folder shape as a single unified path (no internal boundaries)
                        folder_path = QPainterPath()
                        # Draw the entire folder perimeter as one continuous path
                        # Start at top-left of tab
                        folder_path.moveTo(2, 3)
                        # Top edge of tab
                        folder_path.lineTo(8, 3)
                        # Right edge of tab down to base connection
                        folder_path.lineTo(10, 6)
                        # Right edge of base down
                        folder_path.lineTo(14, 6)
                        folder_path.lineTo(14, 13)
                        # Bottom edge of base
                        folder_path.lineTo(2, 13)
                        # Left edge of base up to tab connection
                        folder_path.lineTo(2, 6)
                        # Left edge of tab up to start
                        folder_path.lineTo(2, 3)
                        # Close the path (creates single unified shape)
                        folder_path.closeSubpath()

                        # Draw the folder as one unified element
                        painter.setPen(Qt.transparent)
                        painter.setBrush(folder_color)
                        painter.drawPath(folder_path)

                        # Draw reddish border if mode is 'all'
                        if has_border:
                            painter.setPen(QPen(border_color, 1))
                            painter.setBrush(Qt.transparent)
                            painter.drawPath(folder_path)

                        # Check rename status and overlay checkmark if valid
                        # Draw checkmark AFTER folder icon so it appears on top
                        try:
                            # Only check if rename status is enabled
                            if (self.main_window and
                                hasattr(self.main_window, 'rename_status_manager') and
                                    self.main_window.rename_status_manager.is_enabled()):
                                rename_status = self.main_window.rename_status_manager.get_directory_status(file_path)
                                # Only show checkmark if status is explicitly True (not None or False)
                                if rename_status is True:
                                    # Draw checkmark with black border overlaying the folder icon
                                    # Checkmark coordinates: bottom-left to center to top-right
                                    # Using coordinates that cover the icon area
                                    x1, y1 = 4, 11   # Bottom-left start
                                    x2, y2 = 7, 13   # Center point
                                    x3, y3 = 12, 4   # Top-right end

                                    # First draw black border (thicker pen)
                                    black_pen = QPen(QColor(0, 0, 0), 5)
                                    black_pen.setCapStyle(Qt.RoundCap)
                                    black_pen.setJoinStyle(Qt.RoundJoin)
                                    painter.setPen(black_pen)
                                    painter.drawLine(x1, y1, x2, y2)
                                    painter.drawLine(x2, y2, x3, y3)

                                    # Then draw green checkmark on top (thinner pen for fill)
                                    green_pen = QPen(QColor(0, 255, 0, 255), 3)
                                    green_pen.setCapStyle(Qt.RoundCap)
                                    green_pen.setJoinStyle(Qt.RoundJoin)
                                    painter.setPen(green_pen)
                                    painter.drawLine(x1, y1, x2, y2)
                                    painter.drawLine(x2, y2, x3, y3)
                        except Exception:
                            # Log error for debugging
                            import traceback
                            print(f"Error drawing checkmark for {file_path}")
                            traceback.print_exc()

                        painter.end()
                        return QIcon(pixmap)
        return super().data(index, role)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """Override lessThan to implement case-insensitive sorting"""
        source_model = self.sourceModel()
        if not source_model:
            return False

        # Get file paths
        left_path = source_model.filePath(left)
        right_path = source_model.filePath(right)

        # Check if both are directories or both are files
        left_is_dir = os.path.isdir(left_path)
        right_is_dir = os.path.isdir(right_path)

        # Directories come before files
        if left_is_dir and not right_is_dir:
            return True
        if not left_is_dir and right_is_dir:
            return False

        # Case-insensitive comparison of basenames
        left_name = os.path.basename(left_path).lower()
        right_name = os.path.basename(right_path).lower()

        return left_name < right_name

# --- FileTreeHandler: optimized for clarity and performance ---


class FileTreeHandler(QObject):
    """Handles all file tree operations and maintains synchronization with the main image browser."""

    def __init__(self, main_window: Any, parent_widget: QWidget) -> None:
        super().__init__(parent_widget)
        self.main_window: Any = main_window
        self.parent_widget: QWidget = parent_widget
        self.on_directory_selected_callback: Optional[Callable[[str], None]] = None
        self.on_file_selected_callback: Optional[Callable[[str], None]] = None
        self.on_file_double_clicked_callback: Optional[Callable[[str], None]] = None
        self.get_current_image_callback: Optional[Callable[[], Optional[str]]] = None
        self.get_displayed_images_callback: Optional[Callable[[], List[str]]] = None
        self.file_tree_widget: Optional[QWidget] = None
        self.file_model: Optional[QFileSystemModel] = None
        self.filter_proxy: Optional[CustomFileSystemFilter] = None
        self.file_tree: Optional[QTreeView] = None
        self.current_dir_label: Optional[QLabel] = None
        self.home_button: Optional[QPushButton] = None
        self.collapse_all_button: Optional[QPushButton] = None
        self.current_highlighted_directory: Optional[str] = None
        self.current_highlighted_file: Optional[str] = None
        self._user_input_selection: bool = False
        self._initial_file_loaded: bool = False
        self._suppress_tree_adjustments_once: bool = False
        self._last_highlighted_directory: Optional[str] = None
        # Full path - skip update when unchanged
        self._last_highlighted_file: Optional[str] = None
        self._last_expanded_directory: Optional[str] = None
        self._last_scrolled_file: Optional[str] = None
        self._directory_visibility_cache: Dict[str, bool] = {}
        self._pending_scroll_file: Optional[str] = None
        self._tree_initialized: bool = False
        self._last_refreshed_directory: Optional[str] = None
        # Track directory requested by user click/keyboard
        self.user_requested_directory: Optional[str] = None
        self._expand_in_progress: bool = False  # Prevent concurrent expansions
        # Cache config values to avoid repeated file I/O
        self._cached_enabled_root_dirs: Optional[Set[str]] = None
        self._cached_show_hidden: Optional[bool] = None
        # Cache size limit for directory visibility cache (prevent unbounded growth)
        self._max_visibility_cache_size: int = 1000
        # Track rebuilds to prevent stale index usage
        self._rebuild_counter: int = 0
        self._rebuild_in_progress: bool = False
        # Track pending timers to cancel on rebuild
        self._pending_timers: List[QTimer] = []
        # 200ms debounce when holding scroll key
        self._tree_highlight_debounce_timer: Optional[QTimer] = None
        # Pre-create timers to avoid connect() in double-click path (GIL deadlock mitigation)
        self._clear_user_requested_timer = QTimer(self)
        self._clear_user_requested_timer.setSingleShot(True)
        self._clear_user_requested_timer.timeout.connect(lambda: setattr(self, 'user_requested_directory', None))
        self._restore_tree_focus_timer = QTimer(self)
        self._restore_tree_focus_timer.setSingleShot(True)
        self._restore_tree_focus_timer.timeout.connect(self._restore_tree_focus)
        # Don't initialize tree immediately - wait for first access
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            from event_bus import DIRECTORY_LOADED, CURRENT_IMAGE_CHANGED, DIRECTORY_CHANGED
            main_window.event_bus.subscribe(DIRECTORY_LOADED, self._on_directory_loaded)
            main_window.event_bus.subscribe(CURRENT_IMAGE_CHANGED, self._on_current_image_changed)
            main_window.event_bus.subscribe(DIRECTORY_CHANGED, self._on_directory_changed)

    def _on_current_image_changed(self, image_path: str):
        """Handle CURRENT_IMAGE_CHANGED event - highlight current file in tree"""
        try:
            if (self.is_tree_initialized() and image_path and
                    getattr(self.main_window, 'current_view_mode', '') != 'slideshow'):
                QTimer.singleShot(0, self.highlight_current_file)
        except Exception:
            pass

    def _on_directory_changed(self, directory: str):
        """Handle DIRECTORY_CHANGED event - highlight current directory in tree"""
        try:
            if self.is_tree_initialized() and directory:
                self.highlight_current_directory()
        except Exception:
            pass

    def _on_directory_loaded(self, directory, displayed_count=None, external_load=None):
        """Handle DIRECTORY_LOADED event - update tree highlighting and state"""
        try:
            if self.is_tree_initialized():
                # Update file tree root to show the current directory first
                self.update_root_directory(directory)
                if not self.user_requested_directory:
                    def ensure_directory_highlighted():
                        if self.is_tree_initialized() and not self.user_requested_directory:
                            self._highlight_directory_in_tree(directory)
                    QTimer.singleShot(100, ensure_directory_highlighted)
                if external_load is False and self.main_window.displayed_images:
                    self.apply_filter_pattern(self.main_window.filter_pattern)
                if self.main_window.displayed_images and self.main_window.highlight_index < len(self.main_window.displayed_images):
                    self.force_expand_directory(directory)
                    self.highlight_current_file()
                    self.main_window.highlight_image()
                else:
                    self.force_expand_directory(directory)
                    if not self.user_requested_directory:
                        def highlight_empty_directory():
                            if self.is_tree_initialized() and not self.user_requested_directory:
                                self._highlight_directory_in_tree(directory)
                        QTimer.singleShot(200, highlight_empty_directory)
                    else:
                        if self.is_tree_initialized() and self.file_tree:
                            self.file_tree.viewport().update()
                            # Avoid processEvents - can cause GIL deadlock when nested timer fires singleShot
        except Exception:
            pass

    def set_callbacks(self,
        on_directory_selected: Optional[Callable[[str], None]] = None,
        on_file_selected: Optional[Callable[[str], None]] = None,
        on_file_double_clicked: Optional[Callable[[str], None]] = None,
        get_current_image: Optional[Callable[[], Optional[str]]] = None,
        get_displayed_images: Optional[Callable[[], List[str]]] = None
    ) -> None:
        self.on_directory_selected_callback = on_directory_selected
        self.on_file_selected_callback = on_file_selected
        self.on_file_double_clicked_callback = on_file_double_clicked
        self.get_current_image_callback = get_current_image
        self.get_displayed_images_callback = get_displayed_images

    def is_tree_initialized(self) -> bool:
        """Check if the tree view has been initialized"""
        return self._tree_initialized

    def ensure_tree_initialized(self) -> None:
        """Initialize the tree view if it hasn't been initialized yet"""
        if not self._tree_initialized:
            self.setup_file_tree()
            self._tree_initialized = True

    def _get_enabled_root_directories_cached(self) -> Set[str]:
        """Get enabled root directories with caching"""
        if self._cached_enabled_root_dirs is None:
            self._cached_enabled_root_dirs = get_enabled_root_directories()
        return self._cached_enabled_root_dirs

    def _get_show_hidden_directories_cached(self) -> bool:
        """Get show hidden directories setting with caching"""
        if self._cached_show_hidden is None:
            self._cached_show_hidden = get_show_hidden_directories()
        return self._cached_show_hidden

    def _refresh_config_cache(self) -> None:
        """Refresh cached config values (call when settings change)"""
        self._cached_enabled_root_dirs = None
        self._cached_show_hidden = None

    def _get_filter_flags(self) -> QDir.Filter:
        """Get filter flags based on show_hidden setting"""
        filter_flags = QDir.AllDirs | QDir.NoDotAndDotDot
        if self._get_show_hidden_directories_cached():
            filter_flags |= QDir.Hidden
        return filter_flags

    def _setup_model_root_paths(self, file_model: QFileSystemModel) -> None:
        """Setup root paths for file model efficiently"""
        # Set root path to "/" first
        file_model.setRootPath("/")
        # Set enabled root directories
        enabled_dirs = self._get_enabled_root_directories_cached()
        for root_dir in enabled_dirs:
            file_model.setRootPath(root_dir)
        # Set back to "/" as the primary root (only if changed)
        file_model.setRootPath("/")

    def _safe_map_from_source(self, source_index: QModelIndex) -> Optional[QModelIndex]:
        """Safely map a source index to proxy index, validating model consistency.
        Returns None if the index is invalid or belongs to a different model.

        Note: Qt's mapFromSource doesn't raise Python exceptions for wrong-model indices,
        it prints a warning and returns an invalid index. We check the result validity."""
        if not source_index.isValid():
            return None
        if not self.file_model or not self.filter_proxy:
            return None

        # Get the current source model from the proxy
        current_source_model = self.filter_proxy.sourceModel()
        if current_source_model != self.file_model:
            # Model mismatch - rebuild happened, indices are stale
            return None

        # Validate that the index belongs to the current model
        # Check both that model() is not None and matches
        index_model = source_index.model()
        if index_model is None or index_model != self.file_model:
            return None

        # Double-check: ensure source model hasn't changed between checks
        if self.filter_proxy.sourceModel() != self.file_model:
            return None

        # Call mapFromSource - Qt will print warning if index is from wrong model
        # but won't raise exception, so we check result validity
        proxy_index = self.filter_proxy.mapFromSource(source_index)

        # If Qt detected wrong model, it returns invalid index (and prints warning)
        # Check validity to catch this case
        if not proxy_index.isValid():
            return None

        return proxy_index

    def _get_proxy_index(self, file_path: str) -> Optional[QModelIndex]:
        """Helper method to get proxy index for a file path.
        Validates that the index belongs to the current source model before mapping."""
        if not self.file_model or not self.filter_proxy:
            return None

        source_index = self.file_model.index(file_path)
        if not source_index.isValid():
            return None

        return self._safe_map_from_source(source_index)

    def _add_path_to_priority_paths(self, path: str) -> bool:
        """Add a path and all its parents to priority_paths. Returns True if any paths were added."""
        if not hasattr(self.filter_proxy, 'priority_paths'):
            return False
        added = False
        current_path = path
        while current_path and current_path != os.path.dirname(current_path):
            if current_path not in self.filter_proxy.priority_paths:
                self.filter_proxy.priority_paths.add(current_path)
                added = True
            current_path = os.path.dirname(current_path)
        return added

    def _get_filtered_tree_mode(self) -> str:
        """Get normalized filtered_tree mode."""
        if not self.filter_proxy:
            return 'images'
        filtered_tree_mode = self.filter_proxy.filtered_tree
        if isinstance(filtered_tree_mode, bool):
            return 'use_filter' if filtered_tree_mode else 'images'
        return filtered_tree_mode

    def _needs_priority_paths(self) -> bool:
        """Check if priority_paths are needed based on filtered_tree mode."""
        return self._get_filtered_tree_mode() != 'all'

    def _select_directory_in_tree(self, directory: str, block_signals: bool = True) -> bool:
        """Select a directory in the tree. Returns True if successful."""
        current_dir = getattr(self.main_window, 'current_directory', None)

        if not self.file_tree or not self.file_model or not self.filter_proxy:
            return False
        proxy_dir_index = self._get_proxy_index(directory)
        if not proxy_dir_index or not proxy_dir_index.isValid():
            return False

        selection_model = self.file_tree.selectionModel()
        if not selection_model:
            return False

        # CRITICAL: Add guards here too - don't select wrong directory
        if self.user_requested_directory and directory != self.user_requested_directory:
            return False

        # CRITICAL: Only check current_directory if this is NOT a user-requested selection
        # User-requested selections happen BEFORE load_directory() sets current_directory
        # In specific_files_active mode, files span multiple directories - allow selecting
        # any directory (e.g. parent ~/tmp when navigating from ~/tmp/prowser_wallpaper)
        if (not self.user_requested_directory and not getattr(self.main_window, 'specific_files_active', False)
                and current_dir and directory != current_dir):
            return False

        if block_signals:
            selection_model.blockSignals(True)
        try:
            selection_model.clearSelection()
            selection_model.select(proxy_dir_index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
            self.current_highlighted_directory = directory
            return True
        finally:
            if block_signals:
                selection_model.blockSignals(False)

    def rebuild_tree(self, show_hidden: Optional[bool] = None) -> None:
        """Completely rebuild the tree - useful when tree settings change

        Args:
            show_hidden: If provided, use this value instead of reading from config.
                        If None, read from config.
        """
        # Prevent concurrent rebuilds
        if self._rebuild_in_progress:
            return

        # Skip rebuild if directory was opened from tree view - tree is already expanded correctly
        if self.user_requested_directory:
            return

        # Refresh config cache when rebuilding tree
        self._refresh_config_cache()
        if not self._tree_initialized:
            return
        if not self.file_tree or not self.filter_proxy:
            return

        # Mark rebuild in progress and increment counter
        self._rebuild_in_progress = True
        self._rebuild_counter += 1
        rebuild_id = self._rebuild_counter

        # Cancel any pending timers from previous operations
        for timer in self._pending_timers:
            if timer:
                try:
                    timer.stop()
                    timer.deleteLater()
                except Exception:
                    pass
        self._pending_timers.clear()

        try:
            # Store current directory for highlighting after rebuild
            current_dir = None
            if hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
                current_dir = self.main_window.current_directory

            # Preserve all expanded directory states before rebuild
            expanded_dirs = self.get_expanded_directories()

            # Determine filter setting - use provided value or read from config
            if show_hidden is None:
                show_hidden = self._get_show_hidden_directories_cached()
            else:
                # Update cache if explicit value provided
                self._cached_show_hidden = show_hidden

            # Disconnect signals from old model
            try:
                if self.file_model:
                    self.file_model.directoryLoaded.disconnect()
            except Exception:
                pass

            # Create new model exactly like setup_file_tree does
            from PySide6.QtWidgets import QFileSystemModel
            old_model = self.file_model

            self.file_model = QFileSystemModel()

            # Set filter FIRST (before setting root paths) to ensure directories load with correct filter
            filter_flags = QDir.AllDirs | QDir.NoDotAndDotDot
            if show_hidden:
                filter_flags |= QDir.Hidden
            self.file_model.setFilter(filter_flags)

            # Set root paths AFTER filter is set (using optimized helper)
            self._setup_model_root_paths(self.file_model)

            # Reconnect directory loaded signal (Qt signal - single path arg)
            try:
                self.file_model.directoryLoaded.connect(self._on_file_model_directory_loaded)
            except Exception:
                pass

            # Update filter proxy to use new model
            self.filter_proxy.setSourceModel(self.file_model)

            # Refresh excluded directories from settings
            try:
                from config import get_config
                config = get_config()
                settings = config.load_settings()
                ignore_dirs = settings.get('ignore_directories', [])
                # Clear old user-defined ignore directories (keep hardcoded ones)
                hardcoded = {'/Users/Deleted Users', os.path.expanduser('~/Library'), os.path.expanduser('~/Applications'), '/.nofollow', '/.resolve', '/.vol', '/.Trashes',
                             '/.fseventsd', '/.Spotlight-V100', '/.DocumentRevisions-V100', '/.MobileBackups', '/.PKInstallSandboxManager-SystemSoftware', '/.file', '/.vol'}
                self.filter_proxy._excluded_directories = hardcoded.copy()
                if isinstance(ignore_dirs, list):
                    for ignore_dir in ignore_dirs:
                        if isinstance(ignore_dir, dict):
                            path = ignore_dir.get('path')
                            enabled = ignore_dir.get('enabled', False)
                            if enabled and path and isinstance(path, str) and path.strip():
                                expanded_path = os.path.expanduser(path.strip())
                                self.filter_proxy._excluded_directories.add(expanded_path)
                        elif ignore_dir and isinstance(ignore_dir, str) and ignore_dir.strip():
                            # Backward compatibility: if it's just a string, treat as enabled
                            expanded_path = os.path.expanduser(ignore_dir.strip())
                            self.filter_proxy._excluded_directories.add(expanded_path)
            except Exception:
                pass

            # Refresh cached settings in filter proxy (including follow_symlinks)
            if hasattr(self.filter_proxy, '_refresh_follow_symlinks_cache'):
                self.filter_proxy._refresh_follow_symlinks_cache()

            # Clear directory visibility cache
            self._directory_visibility_cache.clear()

            # Clear image cache in filter proxy so new directories are properly checked
            if self.filter_proxy and hasattr(self.filter_proxy, 'has_images_cache'):
                self.filter_proxy.has_images_cache.clear()

            # Set root index (matching setup_file_tree)
            root_index = self.file_model.index("/")
            if root_index.isValid():
                proxy_root = self._safe_map_from_source(root_index)
                if proxy_root and proxy_root.isValid():
                    self.file_tree.setRootIndex(proxy_root)

            # Process events to let model start loading
            QApplication.processEvents()

            # Clean up old model
            if old_model:
                old_model.deleteLater()

            # Restore expanded directories and highlight current directory if we have one
            if expanded_dirs or (current_dir and os.path.isdir(current_dir)):
                # Add current directory and all parent paths to priority_paths to ensure visibility
                if current_dir and self._needs_priority_paths():
                    filter_needs_update = self._add_path_to_priority_paths(current_dir)
                    if filter_needs_update:
                        self.filter_proxy.invalidateFilter()
                        QApplication.processEvents()

                # Use a delay to ensure model has loaded directories, then restore expansion states
                def restore_expansion_and_highlight():
                    # Check if rebuild happened during delay - if so, abort
                    if rebuild_id != self._rebuild_counter:
                        return

                    # Validate all objects are still valid before proceeding
                    if not self.is_tree_initialized():
                        return
                    if not self.file_tree or not self.file_model or not self.filter_proxy:
                        return
                    if self.file_model != self.filter_proxy.sourceModel():
                        return

                    try:
                        # First, restore all previously expanded directories
                        # Sort by path depth (shallowest first) to ensure parents are expanded before children
                        expanded_dirs_sorted = sorted(expanded_dirs, key=lambda p: p.count(os.sep))

                        for expanded_dir in expanded_dirs_sorted:
                            # Re-validate objects on each iteration in case they change
                            if not self.is_tree_initialized() or not self.file_tree or not self.file_model or not self.filter_proxy:
                                break
                            if self.file_model != self.filter_proxy.sourceModel():
                                break

                            if os.path.isdir(expanded_dir):
                                try:
                                    model_idx = self.file_model.index(expanded_dir)
                                    if not model_idx.isValid():
                                        continue

                                    proxy_idx = self._safe_map_from_source(model_idx)
                                    if not proxy_idx or not proxy_idx.isValid():
                                        continue

                                    # Expand parent path first to ensure this directory is visible
                                    parent_path = os.path.dirname(expanded_dir)
                                    if parent_path != expanded_dir and parent_path:
                                        try:
                                            parent_model_idx = self.file_model.index(parent_path)
                                            if parent_model_idx.isValid():
                                                parent_proxy_idx = self._safe_map_from_source(parent_model_idx)
                                                if parent_proxy_idx and parent_proxy_idx.isValid():
                                                    # Safe check before accessing isExpanded
                                                    try:
                                                        if not self.file_tree.isExpanded(parent_proxy_idx):
                                                            self.file_tree.expand(parent_proxy_idx)
                                                            QApplication.processEvents()
                                                    except (RuntimeError, AttributeError):
                                                        # Object may have been deleted
                                                        break
                                        except (RuntimeError, AttributeError):
                                            # Skip parent expansion if it fails
                                            pass

                                    # Now expand this directory - wrap in try-except for safety
                                    # Re-validate index right before use to prevent segfault
                                    try:
                                        # Re-check that file_tree and models are still valid
                                        if not self.file_tree or not self.file_model or not self.filter_proxy:
                                            break
                                        if self.file_model != self.filter_proxy.sourceModel():
                                            break

                                        # Re-fetch the index right before use to ensure it's still valid
                                        # This prevents segfaults from stale QModelIndex objects
                                        fresh_model_idx = self.file_model.index(expanded_dir)
                                        if not fresh_model_idx.isValid():
                                            continue
                                        fresh_proxy_idx = self._safe_map_from_source(fresh_model_idx)
                                        if not fresh_proxy_idx or not fresh_proxy_idx.isValid():
                                            continue

                                        if not self.file_tree.isExpanded(fresh_proxy_idx):
                                            self.file_tree.expand(fresh_proxy_idx)
                                    except (RuntimeError, AttributeError):
                                        # Object may have been deleted, skip this directory
                                        continue
                                except (RuntimeError, AttributeError, Exception):
                                    # Skip this directory if anything fails
                                    continue

                        QApplication.processEvents()

                        # Then expand to current directory path (if different from expanded dirs)
                        if current_dir and os.path.isdir(current_dir):
                            root_path = "/"
                            path_components: List[str] = []
                            current_path = current_dir
                            while current_path and current_path != root_path and current_path != os.path.dirname(current_path):
                                path_components.append(current_path)
                                current_path = os.path.dirname(current_path)
                            path_components.append(root_path)
                            path_components.reverse()

                            # Expand each path component (only if not already expanded)
                            for path in path_components:
                                # Re-validate objects on each iteration
                                if not self.is_tree_initialized() or not self.file_tree or not self.file_model or not self.filter_proxy:
                                    break
                                if self.file_model != self.filter_proxy.sourceModel():
                                    break

                                if path not in expanded_dirs:
                                    try:
                                        model_idx = self.file_model.index(path)
                                        if not model_idx.isValid():
                                            continue

                                        proxy_idx = self._safe_map_from_source(model_idx)
                                        if not proxy_idx or not proxy_idx.isValid():
                                            continue

                                        # Safe check before accessing isExpanded
                                        # Re-validate index right before use to prevent segfault
                                        try:
                                            # Re-check that file_tree and models are still valid
                                            if not self.file_tree or not self.file_model or not self.filter_proxy:
                                                break
                                            if self.file_model != self.filter_proxy.sourceModel():
                                                break

                                            # Re-fetch the index to ensure it's still valid
                                            fresh_model_idx = self.file_model.index(path)
                                            if not fresh_model_idx.isValid():
                                                continue
                                            fresh_proxy_idx = self._safe_map_from_source(fresh_model_idx)
                                            if not fresh_proxy_idx or not fresh_proxy_idx.isValid():
                                                continue

                                            if not self.file_tree.isExpanded(fresh_proxy_idx):
                                                self.file_tree.expand(fresh_proxy_idx)
                                        except (RuntimeError, AttributeError):
                                            # Object may have been deleted
                                            break
                                    except (RuntimeError, AttributeError, Exception):
                                        # Skip this path if anything fails
                                        continue

                            QApplication.processEvents()

                            # Wait a bit more for everything to settle, then select current directory
                            def select_directory():
                                # Check if rebuild happened - if so, abort
                                if rebuild_id != self._rebuild_counter:
                                    return
                                # Ensure directory is visible and selected
                                # CRITICAL: Don't override user-requested directory selection
                                if current_dir and not self.user_requested_directory:
                                    if self._select_directory_in_tree(current_dir):
                                        proxy_dir_index = self._get_proxy_index(current_dir)
                                        if proxy_dir_index and proxy_dir_index.isValid():
                                            self.file_tree.scrollTo(proxy_dir_index, QTreeView.ScrollHint.EnsureVisible)
                                # Also call update_root_directory to ensure label is updated
                                # CRITICAL: Don't override user-requested directory selection
                                if current_dir and not self.user_requested_directory:
                                    self.update_root_directory(current_dir)

                            timer = QTimer()
                            timer.setSingleShot(True)
                            timer.timeout.connect(select_directory)
                            timer.start(200)
                            self._pending_timers.append(timer)
                    except Exception:
                        traceback.print_exc()

                # Use a delay to ensure model has started loading directories
                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(restore_expansion_and_highlight)
                timer.start(500)
                self._pending_timers.append(timer)

        except Exception:
            traceback.print_exc()
        finally:
            # Mark rebuild complete
            self._rebuild_in_progress = False

    def setup_file_tree(self) -> None:
        # entry_debug(dump_stack=True)
        # If QFileSystemModel is not in global scope, import here to ensure it's available
        from PySide6.QtWidgets import QFileSystemModel

        self.file_tree_widget = QWidget()
        layout = QVBoxLayout(self.file_tree_widget)
        layout.setContentsMargins(5, 5, 7, 5)
        self.setup_navigation_controls(layout)
        self.file_model = QFileSystemModel()

        # --- BEGIN macOS Fix: Show Mounted Volumes ---
        # On macOS, set root path to "/" to show all directories including /Volumes
        # QDir.Drives is Windows-specific and produces unpredictable results on macOS
        # Setting root to "/" ensures we see all top-level directories including /Volumes
        # Set filter FIRST (before setting root paths) to ensure directories load with correct filter
        self.file_model.setFilter(self._get_filter_flags())
        # Set root paths AFTER filter is set (using optimized helper)
        self._setup_model_root_paths(self.file_model)
        # --- END macOS Fix ---

        try:
            self.file_model.directoryLoaded.connect(self._on_file_model_directory_loaded)
        except Exception:
            pass
        self.filter_proxy = CustomFileSystemFilter(main_window=self.main_window)
        self.filter_proxy.setSourceModel(self.file_model)
        self.current_filter_pattern: Optional[str] = None
        self.file_tree = CustomTreeView()
        self.file_tree.set_main_window(self.main_window)
        self.file_tree.setModel(self.filter_proxy)

        # On macOS, set the tree root to "/" to show all directories including /Volumes
        root_index = self.file_model.index("/")
        if root_index.isValid():
            proxy_root = self._safe_map_from_source(root_index)
            if proxy_root and proxy_root.isValid():
                self.file_tree.setRootIndex(proxy_root)

        parent_self = self

        class HighlightDelegate(QStyledItemDelegate):
            def paint(delegate_self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
                try:
                    opt = QStyleOptionViewItem(option)
                    delegate_self.initStyleOption(opt, index)
                    # Check for drag highlight
                    if hasattr(parent_self, 'file_tree') and hasattr(parent_self.file_tree, 'highlighted_index'):
                        if parent_self.file_tree.highlighted_index is not None and parent_self.file_tree.highlighted_index == index:
                            # Apply drag highlight styling (theme-aware)
                            th = get_active_theme()
                            opt.backgroundBrush = QBrush(QColor(th.file_tree_delegate_drag_bg_hex))
                            bold_font = QFont(opt.font)
                            bold_font.setBold(True)
                            opt.font = bold_font
                            pal = QPalette(opt.palette)
                            tc = QColor(th.file_tree_delegate_drag_text_hex)
                            pal.setColor(QPalette.Text, tc)
                            pal.setColor(QPalette.HighlightedText, tc)
                            opt.palette = pal
                    QApplication.style().drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
                except Exception:
                    super(HighlightDelegate, delegate_self).paint(painter, option, index)
        self.file_tree.setItemDelegate(HighlightDelegate(self.file_tree))

        # Connect to expansion signals to update rename status when directories are expanded
        self.file_tree.expanded.connect(self._on_tree_item_expanded)
        self.file_tree.collapsed.connect(self._on_tree_item_collapsed)

        app = QApplication.instance()
        if app:
            # could also be 'windows' or 'macos' or 'Fusion'
            app.setStyle('Fusion')
        self.file_tree.setAnimated(False)
        # Change indentation to half the icon width (icon is 16px, so 8px per level)
        self.file_tree.setIndentation(8)
        self.file_tree.setSortingEnabled(False)
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setAlternatingRowColors(False)
        self.file_tree.setRootIsDecorated(True)
        self.file_tree.setItemsExpandable(True)
        self.file_tree.setUniformRowHeights(True)
        self.file_tree.setExpandsOnDoubleClick(False)  # We handle double-click manually
        self.file_tree.setProperty("show-decoration-selected", True)
        self.file_tree.setStyle(QApplication.style())
        self.file_tree.setAttribute(Qt.WA_MacShowFocusRect, False)
        self.file_tree.setIconSize(QSize(16, 16))
        header = self.file_tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setDefaultSectionSize(200)
        self.filter_proxy.sort(0, Qt.SortOrder.AscendingOrder)
        self.file_tree.hideColumn(1)
        self.file_tree.hideColumn(2)
        self.file_tree.hideColumn(3)
        self.file_tree.setStyleSheet(get_active_theme().file_tree_panel_stylesheet())
        # self.file_tree.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Double click does nothing, as there are no files
        # self.file_tree.doubleClicked.connect(self._on_double_clicked)

        # CRITICAL: Set NoFocus to prevent file_tree from being in tab order
        # The tree_container handles focus, not the file_tree itself
        self.file_tree.setFocusPolicy(Qt.NoFocus)
        self.file_tree.installEventFilter(self)
        layout.addWidget(self.file_tree)

    def _create_checkmark_icon(self, active: bool) -> QIcon:
        """Create a checkmark icon - green when active, black when inactive, with white border"""
        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor(0, 0, 0, 0))  # Transparent background

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Coordinates: bottom-left to center to top-right
        x1, y1 = 4, 12   # Bottom-left start
        x2, y2 = 8, 15   # Center point
        x3, y3 = 15, 5   # Top-right end

        # Draw white border checkmark first (thicker, underlying)
        border_pen = QPen(QColor(255, 255, 255), 3)
        border_pen.setCapStyle(Qt.RoundCap)
        border_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(border_pen)
        painter.drawLine(x1, y1, x2, y2)
        painter.drawLine(x2, y2, x3, y3)

        # Draw colored checkmark on top (thinner)
        # Choose color based on active state
        if active:
            checkmark_color = QColor(0, 255, 0)  # Green
        else:
            checkmark_color = QColor(0, 0, 0)    # Black

        checkmark_pen = QPen(checkmark_color, 2)
        checkmark_pen.setCapStyle(Qt.RoundCap)
        checkmark_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(checkmark_pen)
        painter.drawLine(x1, y1, x2, y2)
        painter.drawLine(x2, y2, x3, y3)

        painter.end()
        return QIcon(pixmap)

    def _create_house_icon(self, color: str = "#eeeeee") -> QIcon:
        """Create a house icon with a triangular roof and rectangular base

        Args:
            color: Color hex code for the house lines (default: #eeeeee)
        """
        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor(0, 0, 0, 0))  # Transparent background

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw house with specified color
        pen = QPen(QColor(color), 1)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Move house up by 2px: all y coordinates -2
        # Roof triangle: top point, left bottom, right bottom
        roof_top_x, roof_top_y = 10, 3   # Center top (5-2 = 3)
        # Move the bottom of the roof down 1px (from 8 to 9)
        roof_left_x, roof_left_y = 3, 9   # Left bottom of roof (was 8)
        roof_right_x, roof_right_y = 17, 9  # Right bottom of roof (was 8)

        # Draw roof (triangle)
        painter.drawLine(roof_top_x, roof_top_y, roof_left_x, roof_left_y)
        painter.drawLine(roof_top_x, roof_top_y, roof_right_x, roof_right_y)
        painter.drawLine(roof_left_x, roof_left_y, roof_left_x+6, roof_left_y)
        painter.drawLine(roof_right_x, roof_right_y,
                         roof_right_x-6, roof_right_y)

        # Draw building box (rectangle)
        box_left = 6
        box_top = 8   # Was 10, now 8
        box_width = 8
        box_height = 8
        painter.setPen(QPen(QColor(color), 1))
        painter.drawLine(box_left, box_top + box_height, box_left + box_width, box_top + box_height)
        painter.drawLine(box_left, box_top, box_left, box_top + box_height)
        painter.drawLine(box_left + box_width, box_top, box_left + box_width, box_top + box_height)

        painter.end()
        return QIcon(pixmap)

    def _create_squeeze_icon(self, color: str = "#909090") -> QIcon:
        """Create an icon representing the symbol '>|<'.

        Args:
            color: Color hex code for the lines (default: #909090)
        """
        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor(0, 0, 0, 0))  # Transparent background

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(QColor(color), 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Draw '>' symbol: two lines converging to the right (slightly smaller, matching size with <)
        # The icon is now 20px wide (0..19)
        # '>' symbol on the left
        painter.drawLine(1, 7, 6, 10)    # Top stroke of >
        painter.drawLine(1, 13, 6, 10)   # Bottom stroke of >

        # '|' symbol in the center (now at x=9 after moving left 3)
        painter.drawLine(9, 5, 9, 15)

        # '<' symbol on the right (also shifted left 3)
        painter.drawLine(17, 7, 12, 10)  # Top stroke of <
        painter.drawLine(17, 13, 12, 10) # Bottom stroke of <

        painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _file_tree_filter_toolbar_button_stylesheet(
        theme: Any, focus_bg: str, focus_border: str, focus_text: str
    ) -> str:
        """Same chrome as nav icon buttons, with :checked for exclusive filter mode."""
        base = theme.file_tree_nav_icon_button_stylesheet(
            focus_bg, focus_border, focus_text, dim=False
        )
        t = theme
        return (
            base
            + f"""
            QPushButton:checked {{
                background-color: {t.file_tree_nav_button_pressed_hex};
            }}
            QPushButton:checked:hover {{
                background-color: {t.file_tree_nav_button_hover_hex};
            }}
        """
        )

    def setup_navigation_controls(self, layout: QVBoxLayout) -> None:
        nav_widget = QWidget()
        self._nav_widget = nav_widget
        nav_widget.setAutoFillBackground(True)
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 5)

        _theme = get_active_theme()
        self._nav_bar_default_style = _theme.file_tree_nav_container_stylesheet().strip()
        nav_widget.setStyleSheet(self._nav_bar_default_style)

        def make_btn(text: str, tooltip: str, slot: Callable[[], None]) -> QPushButton:
            btn = QPushButton(text)
            btn.setToolTip(tooltip)
            btn.setMaximumWidth(30)
            from utils import get_button_focus_colors
            focus_bg, focus_border, focus_text = get_button_focus_colors()
            btn.setStyleSheet(
                _theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=True)
            )
            btn.clicked.connect(slot)
            return btn

        self.home_button = QPushButton()
        self.home_button.setToolTip("Go to Home Directory\nNavigate to your home folder")
        self.home_button.setMaximumWidth(30)
        self.home_button.setIconSize(QSize(20, 20))
        # Get focus colors from centralized function
        from utils import get_button_focus_colors
        focus_bg, focus_border, focus_text = get_button_focus_colors()
        self.home_button.setStyleSheet(
            _theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=False)
        )
        self.home_button.clicked.connect(self.go_to_home_directory)
        self.update_home_button_icon()

        self.collapse_all_button = QPushButton()
        self.collapse_all_button.setToolTip("Collapse to home directory\nCollapse all and expand to home directory")
        self.collapse_all_button.setMaximumWidth(30)
        self.collapse_all_button.setIconSize(QSize(20, 20))
        self.collapse_all_button.setIcon(self._create_squeeze_icon())
        # Get focus colors from centralized function
        from utils import get_button_focus_colors
        focus_bg, focus_border, focus_text = get_button_focus_colors()
        self.collapse_all_button.setStyleSheet(
            _theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=False)
        )
        self.collapse_all_button.clicked.connect(self.collapse_all)

        # Rename status toggle button
        self.rename_status_button = QPushButton()
        self.rename_status_button.setToolTip("Toggle Rename Status Check\nCheck if files matching filter pattern also match rename pattern and are sequentially numbered")
        self.rename_status_button.setMaximumWidth(30)
        self.rename_status_button.setIconSize(QSize(20, 20))
        # Get focus colors from centralized function
        from utils import get_button_focus_colors
        focus_bg, focus_border, focus_text = get_button_focus_colors()
        self.rename_status_button.setStyleSheet(
            _theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=False)
        )
        self.rename_status_button.clicked.connect(self._toggle_rename_status)
        self.update_rename_status_button_icon()

        self.settings_button = QPushButton()
        self.settings_button.setToolTip("Open Settings\nConfigure application preferences")
        self.settings_button.setMaximumWidth(30)
        self.settings_button.setIconSize(QSize(20, 20))
        self.settings_button.setIcon(QIcon(asset_path("gear.svg")))
        self.settings_button.setStyleSheet(
            _theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=False)
        )
        self.settings_button.clicked.connect(self.open_settings_to_max_images)
        self.current_dir_label = QLabel("")
        self.current_dir_label.setStyleSheet(_theme.file_tree_current_dir_label_stylesheet())
        self.current_dir_label.setWordWrap(True)
        self.home_button.setFocusPolicy(Qt.NoFocus)
        self.collapse_all_button.setFocusPolicy(Qt.NoFocus)
        self.rename_status_button.setFocusPolicy(Qt.NoFocus)
        self.settings_button.setFocusPolicy(Qt.NoFocus)
        self.current_dir_label.setFocusPolicy(Qt.NoFocus)
        # nav_layout.addWidget(self.home_button)
        nav_layout.addWidget(self.collapse_all_button)
        nav_layout.addWidget(self.rename_status_button)
        nav_layout.addWidget(self.settings_button)
        nav_layout.addStretch(1)

        # --- Tree View Filtering Buttons (right-aligned group; same style as nav icon buttons) ---
        filter_buttons_widget = QWidget()
        filter_buttons_layout = QHBoxLayout(filter_buttons_widget)
        filter_buttons_layout.setContentsMargins(0, 0, 0, 0)
        filter_buttons_layout.setSpacing(4)

        filter_btn_ss = self._file_tree_filter_toolbar_button_stylesheet(
            _theme, focus_bg, focus_border, focus_text
        )

        # These represent: all ("no filter"), images, images matching filter
        def create_filter_icon(mode: str, selected: bool) -> QIcon:
            """Create a pen-drawn icon for each filter mode"""
            # Create icon sized for 18x18 display (will be scaled)
            icon_pixmap_size = 18
            pixmap = QPixmap(icon_pixmap_size, icon_pixmap_size)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)

            _ft = get_active_theme()
            pen_color = QColor(
                _ft.file_tree_filter_icon_selected_hex if selected else _ft.file_tree_filter_icon_unselected_hex
            )
            pen_width = 1.5

            if mode == "all":
                # Draw large X shape (diagonal lines crossing)
                painter.setPen(QPen(pen_color, pen_width))
                # Diagonal from top-left to bottom-right
                painter.drawLine(4, 4, 14, 14)
                # Diagonal from top-right to bottom-left
                painter.drawLine(14, 4, 4, 14)
            elif mode == "images":
                # Draw hollow square outline
                painter.setPen(QPen(pen_color, pen_width))
                painter.setBrush(Qt.NoBrush)
                # Draw square outline centered
                painter.drawRect(5, 5, 8, 8)
            elif mode == "use_filter":
                # Draw funnel shape
                painter.setPen(QPen(pen_color, pen_width))
                painter.setBrush(Qt.NoBrush)
                # Funnel: closed triangle (like top part of letter "Y"), with vertical stem
                # Draw the funnel body as a triangle pointing down
                # Draw hollow funnel (each outer line individually)
                # Top edge
                painter.drawLine(QPoint(5, 4), QPoint(14, 4))
                # Left side
                painter.drawLine(QPoint(5, 4), QPoint(8, 10))
                painter.drawLine(QPoint(8, 10), QPoint(8, 15))
                # Right side
                painter.drawLine(QPoint(14, 4), QPoint(10, 10))
                painter.drawLine(QPoint(10, 10), QPoint(10, 15))

                # Bottom edge
                painter.drawLine(QPoint(8, 15), QPoint(10, 15))

            painter.end()
            return QIcon(pixmap)

        filter_modes = [
            ("all", "Filtering: None\nShow all folders regardless of image content"),
            ("images", "Filtering: Has Images\nOnly display folders that contain at least one image"),
            ("use_filter", "Filtering: Pattern Matching\nOnly display folders with images matching the filter pattern in Settings"),
        ]
        self._filter_mode_buttons: Dict[str, QPushButton] = {}
        self._filter_mode_group = QButtonGroup(self)
        self._filter_mode_group.setExclusive(True)

        # Get current filter mode
        current_mode = 'images'
        if getattr(self, 'filter_proxy', None):
            current_mode = self.filter_proxy.normalize_filtered_tree_mode()

        icon_size = 20
        for mode, tooltip in filter_modes:
            btn = QPushButton()
            btn.setToolTip(tooltip)
            btn.setCheckable(True)
            btn.setChecked(current_mode == mode)
            btn.setIcon(create_filter_icon(mode, current_mode == mode))
            btn.setIconSize(QSize(icon_size, icon_size))
            btn.setMaximumWidth(30)
            btn.setStyleSheet(filter_btn_ss)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda checked, m=mode: self._on_tree_filter_mode_selected(m))
            filter_buttons_layout.addWidget(btn)
            self._filter_mode_buttons[mode] = btn
            self._filter_mode_group.addButton(btn)

        nav_layout.addWidget(filter_buttons_widget, 0)

        # Function to update button icons when filter mode changes
        def filter_icon_redraw():
            """Update button icons and checked state when filter mode changes"""
            if not hasattr(self, 'filter_proxy') or not self.filter_proxy:
                return
            mode = self.filter_proxy.normalize_filtered_tree_mode()
            for m in self._filter_mode_buttons:
                btn = self._filter_mode_buttons[m]
                btn.setChecked(mode == m)
                btn.setIcon(create_filter_icon(m, mode == m))

        self._filter_icon_redraw = filter_icon_redraw

        # Do not add the directory label to the nav_layout

        layout.addWidget(nav_widget)

        # Add the directory label on a new line (below the nav bar)
        dir_label_container = QWidget()
        dir_label_layout = QHBoxLayout(dir_label_container)
        dir_label_layout.setContentsMargins(0, 0, 0, 5)
        dir_label_layout.addWidget(self.current_dir_label, 1)
        layout.addWidget(dir_label_container)

    def refresh_theme_styles(self) -> None:
        """Re-apply file tree panel and tree chrome after theme change."""
        theme = get_active_theme()
        from utils import get_button_focus_colors

        focus_bg, focus_border, focus_text = get_button_focus_colors()
        if hasattr(self, "file_tree") and self.file_tree:
            self.file_tree.setStyleSheet(theme.file_tree_panel_stylesheet())
        if hasattr(self, "_nav_widget") and self._nav_widget:
            self._nav_bar_default_style = theme.file_tree_nav_container_stylesheet().strip()
            self._nav_widget.setStyleSheet(self._nav_bar_default_style)
        if hasattr(self, "home_button") and self.home_button:
            self.home_button.setStyleSheet(
                theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=False)
            )
        if hasattr(self, "collapse_all_button") and self.collapse_all_button:
            self.collapse_all_button.setStyleSheet(
                theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=False)
            )
        if hasattr(self, "rename_status_button") and self.rename_status_button:
            self.rename_status_button.setStyleSheet(
                theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=False)
            )
        if hasattr(self, "settings_button") and self.settings_button:
            self.settings_button.setStyleSheet(
                theme.file_tree_nav_icon_button_stylesheet(focus_bg, focus_border, focus_text, dim=False)
            )
        if hasattr(self, "current_dir_label") and self.current_dir_label:
            self.current_dir_label.setStyleSheet(theme.file_tree_current_dir_label_stylesheet())
        filter_btn_ss = self._file_tree_filter_toolbar_button_stylesheet(
            theme, focus_bg, focus_border, focus_text
        )
        if hasattr(self, "_filter_mode_buttons") and self._filter_mode_buttons:
            for btn in self._filter_mode_buttons.values():
                if btn:
                    btn.setStyleSheet(filter_btn_ss)
            if hasattr(self, "_filter_icon_redraw"):
                self._filter_icon_redraw()

    def _update_dir_label(self, directory: str) -> None:
        """Update the directory label with truncated path."""
        if self.current_dir_label:
            short = normalize_path_for_display(directory)
            display_path = short if len(short) <= 40 else "..." + short[-37:]
            if display_path == "~":
                display_path = "~ (Home directory)"
            self.current_dir_label.setText(display_path)
            self.current_dir_label.setToolTip(short)

    def _on_tree_filter_mode_selected(self, mode: str) -> None:
        """Handle tree filter mode button click - calls menu manager to keep everything in sync"""
        # Call the menu manager's method to keep everything in sync (config, menu checkmarks, etc.)
        # This matches the View > Tree Filtering menu logic
        if self.main_window and hasattr(self.main_window, 'menu_manager') and self.main_window.menu_manager:
            self.main_window.menu_manager.set_tree_filter_mode(mode)
            # Redraw icons for proper visual checked indication
            if hasattr(self, '_filter_icon_redraw'):
                self._filter_icon_redraw()

    def _toggle_rename_status(self) -> None:
        """Toggle rename status from button click"""
        if self.main_window and hasattr(self.main_window, 'toggle_rename_status'):
            self.main_window.toggle_rename_status()

    def update_rename_status_button_icon(self) -> None:
        """Update the rename status button icon based on current state"""
        if not hasattr(self, 'rename_status_button') or not self.rename_status_button:
            return

        # Check if rename status is enabled
        is_enabled = False
        if (self.main_window and
            hasattr(self.main_window, 'rename_status_manager') and
                self.main_window.rename_status_manager):
            is_enabled = self.main_window.rename_status_manager.is_enabled()

        # Update icon
        icon = self._create_checkmark_icon(is_enabled)
        self.rename_status_button.setIcon(icon)

    def update_home_button_icon(self) -> None:
        """Update the home button icon color based on whether current directory is home"""
        if not hasattr(self, 'home_button') or not self.home_button:
            return

        # Determine icon color based on whether current directory is home
        home_dir = os.path.expanduser('~')
        is_home = False
        if (self.main_window and
            hasattr(self.main_window, 'current_directory') and
                self.main_window.current_directory):
            # Normalize paths for comparison
            current_dir = os.path.normpath(self.main_window.current_directory)
            home_dir_normalized = os.path.normpath(home_dir)
            is_home = current_dir == home_dir_normalized

        # Use #eeeeee if at home, #808080 if not
        color = "#EEEEEE" if is_home else "#808080"

        # Update icon
        icon = self._create_house_icon(color)
        self.home_button.setIcon(icon)

    def _is_user_selection(self, directory: str) -> bool:
        """Check if this is a user-initiated selection."""
        return (self.current_highlighted_directory == directory or
            self.user_requested_directory == directory
        )

    def _is_already_selected(self, directory: str) -> bool:
        """Check if directory is already selected and visible."""
        selection_model = self.file_tree.selectionModel()
        if not selection_model:
            return False
        current_selection = selection_model.selectedIndexes()
        if not current_selection:
            return False
        try:
            current_proxy_index = current_selection[0]
            if current_proxy_index.isValid():
                current_source_index = self.filter_proxy.mapToSource(current_proxy_index)
                if current_source_index.isValid():
                    current_selected_path = self.file_model.filePath(current_source_index)
                    return current_selected_path == directory and self.current_highlighted_directory == directory
        except Exception:
            pass
        return False

    def _select_root_as_fallback(self) -> None:
        """Select root directory as fallback."""
        if self.user_requested_directory:
            return  # Don't override user request
        root_path = "/"
        proxy_root = self._get_proxy_index(root_path)
        if proxy_root and proxy_root.isValid():
            selection_model = self.file_tree.selectionModel()
            if selection_model:
                selection_model.blockSignals(True)
                try:
                    selection_model.clearSelection()
                    selection_model.select(proxy_root, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
                finally:
                    selection_model.blockSignals(False)

    def update_root_directory(self, directory: str) -> None:
        # CRITICAL: For user-requested directories, they're already selected in request_directory_opening()
        # Just update the label and return - don't do ANY selection logic
        is_user_requested = (self.user_requested_directory == directory)

        if is_user_requested:
            # User-requested directory is already selected - just update label and return
            # DO NOT touch selection at all - it's already correct
            if self.is_tree_initialized():
                self._update_dir_label(directory)
                self.update_home_button_icon()
                # Ensure tree view is repainted and directory is scrolled into view
                # This is especially important for empty directories
                if self.file_tree:
                    # Ensure directory is visible in filtered tree model
                    # If it's not visible, add to priority paths and invalidate filter
                    proxy_dir_index = self._get_proxy_index(directory)
                    if not proxy_dir_index or not proxy_dir_index.isValid():
                        # Directory not visible - ensure it's in priority paths and filter is updated
                        if self._needs_priority_paths():
                            self._add_path_to_priority_paths(directory)
                            self.filter_proxy.invalidateFilter()
                            QApplication.processEvents()
                            # Try again after filter update
                            proxy_dir_index = self._get_proxy_index(directory)
                        # If still invalid, try expanding to path and selecting
                        if not proxy_dir_index or not proxy_dir_index.isValid():
                            self._expand_to_path(directory, force_expand=True)
                            QApplication.processEvents()
                            proxy_dir_index = self._get_proxy_index(directory)
                            # Try selecting the directory directly
                            if proxy_dir_index and proxy_dir_index.isValid():
                                self._select_directory_in_tree(directory)
                    if proxy_dir_index and proxy_dir_index.isValid():
                        # Scroll to ensure directory is visible
                        self.file_tree.scrollTo(proxy_dir_index, QTreeView.ScrollHint.EnsureVisible)
                        # Also set as current index to ensure selection is visible
                        self.file_tree.setCurrentIndex(proxy_dir_index)
                        # Ensure selection is set
                        selection_model = self.file_tree.selectionModel()
                        if selection_model:
                            selection_model.select(proxy_dir_index, QItemSelectionModel.SelectionFlag.Select |
                                                   QItemSelectionModel.SelectionFlag.Rows | QItemSelectionModel.SelectionFlag.Current)
                    # Repaint viewport to show selection
                    self.file_tree.viewport().update()
                    QApplication.processEvents()
            return

        # CRITICAL: Don't clear selections when directory changes - selections should persist across directories
        # Selections are file paths, so they can span multiple directories. Only clear selections for
        # explicit user actions (single click, arrow keys, escape), not for directory changes.
        # The user might have selected files from multiple directories and wants to keep those selections.
        # Only remove selections for files that no longer exist on disk
        if hasattr(self.main_window, 'selected_files') and self.main_window.selected_files:
            # Remove only files that don't exist on disk
            existing_selections = {
                path for path in self.main_window.selected_files if os.path.exists(path)}
            if len(existing_selections) != len(self.main_window.selected_files):
                removed_count = len(self.main_window.selected_files) - len(existing_selections)
                print(f"[SELECTION DEBUG] update_root_directory: Removed {removed_count} selections (files don't exist)")
                self.main_window.selected_files = existing_selections
                if hasattr(self.main_window, '_emit_selection_changed'):
                    self.main_window._emit_selection_changed()
        if not self.is_tree_initialized():
            return
        if not self.file_model or not self.file_tree:
            return
        try:
            # Quick check: if directory is already selected and visible, skip most work
            if self._is_already_selected(directory):
                self._update_dir_label(directory)
                self.update_home_button_icon()
                return

            is_user_selection = self._is_user_selection(directory)
            needs_priority_paths = self._needs_priority_paths()

            # Add directory to priority_paths if needed (only once, before filter operations)
            filter_needs_update = False
            if needs_priority_paths:
                filter_needs_update = self._add_path_to_priority_paths(directory)
                if filter_needs_update:
                    self.filter_proxy.invalidateFilter()
                    QApplication.processEvents()

            # Expand to the directory
            self._expand_to_path(directory, force_expand=True)

            # Try to select the directory
            proxy_dir_index = self._get_proxy_index(directory)
            if proxy_dir_index and proxy_dir_index.isValid():
                # Directory is visible - select it IMMEDIATELY
                # CRITICAL: For user-requested directories, select immediately and skip delayed highlights
                # to prevent jumping to old directory
                self._select_directory_in_tree(directory)
                # Only schedule delayed highlight if filter was invalidated AND this is NOT a user-requested directory
                # User-requested directories are already selected above, no need for delayed highlight
                if filter_needs_update and not is_user_requested:
                    def ensure_highlight_after_filter():
                        if self.is_tree_initialized():
                            # Use the directory parameter directly, not current_directory which might not be set yet
                            self._highlight_directory_in_tree(directory)
                    QTimer.singleShot(200, ensure_highlight_after_filter)
            else:
                # Directory not visible in proxy model
                if is_user_selection:
                    # If filter was just updated, wait a bit more and try again
                    if filter_needs_update:
                        QApplication.processEvents()
                        proxy_dir_index = self._get_proxy_index(directory)
                        if proxy_dir_index and proxy_dir_index.isValid():
                            # CRITICAL: Select immediately for user-requested directories
                            self._select_directory_in_tree(directory)
                            self._update_dir_label(directory)
                            # User-requested directories are already selected, no need for delayed highlight
                            return
                    # If still not visible, use _highlight_directory_in_tree
                    # CRITICAL: For user-requested directories, highlight immediately
                    self._highlight_directory_in_tree(directory)
                    self._update_dir_label(directory)
                    # User-requested directories are already highlighted, no need for delayed highlight
                    return
                else:
                    # Not a user selection - select root as fallback
                    if self.user_requested_directory and self.user_requested_directory != directory:
                        return
                    self._select_root_as_fallback()

            self._update_dir_label(directory)
            self.update_home_button_icon()
        except Exception:
            # If anything fails, only try to select root if this wasn't a user selection
            if not self._is_user_selection(directory):
                self._select_root_as_fallback()
            self.update_home_button_icon()

    def _is_tree_showing_only_root(self) -> bool:
        try:
            if not self.file_tree or not hasattr(self.file_tree, 'model') or not self.file_tree.model():
                return True
            root_index = self.file_tree.rootIndex()
            for i in range(min(5, self.file_tree.model().rowCount(root_index))):
                child_index = self.file_tree.model().index(i, 0, root_index)
                if child_index.isValid() and self.file_tree.isExpanded(child_index):
                    return False
            visible_items = self.file_tree.viewport().rect().height() // 20
            return visible_items <= 1
        except Exception:
            return False

    def _expand_to_path(self, path: str, force_expand: bool = False) -> None:
        if not self.file_tree:
            return
        # CRITICAL: Do NOT skip when tree is hidden. Expansion state is stored in QTreeView;
        # expanding while hidden ensures correct state when tree is shown (e.g. exiting browse).
        # The isVisible() check caused tree to stay at root when starting in browse mode.
        if not self.file_model or not self.filter_proxy:
            return
        if not force_expand and getattr(self, '_suppress_tree_adjustments_once', False):
            return

        # Normalize path to directory
        dir_path = path if os.path.isdir(path) else os.path.dirname(path)

        # Check if we can skip expansion (but still need to set current index for sync)
        skip_expansion = False
        if not force_expand:
            last_expanded = getattr(self, '_last_expanded_directory', None)
            if last_expanded == dir_path:
                # Directory already expanded, but still need to set current index for sync
                skip_expansion = True
            # Also check against current_directory for backward compatibility
            elif hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
                if dir_path == self.main_window.current_directory:
                    skip_expansion = True

        try:
            if not skip_expansion:
                # Expand the directory path
                current_path = dir_path
                while current_path and current_path != os.path.dirname(current_path):
                    proxy_index = self._get_proxy_index(current_path)
                    if proxy_index and proxy_index.isValid():
                        if force_expand or not self.file_tree.isExpanded(proxy_index):
                            self.file_tree.expand(proxy_index)
                    current_path = os.path.dirname(current_path)
                # Track the last expanded directory
                self._last_expanded_directory = dir_path

            # Always set current index to keep tree synced (even if already expanded)
            proxy_index = self._get_proxy_index(dir_path)
            if proxy_index and proxy_index.isValid():
                self.file_tree.setCurrentIndex(proxy_index)
        except Exception:
            traceback.print_exc()

    def highlight_current_directory(self) -> None:
        if not self.file_tree or not self.file_tree.isVisible():
            return
        if not self.is_tree_initialized():
            return

        # If user pressed Enter on a directory, ONLY highlight that directory
        if self.user_requested_directory:
            self._select_directory_in_tree(self.user_requested_directory)
            return

        # CRITICAL FIX: Prioritize current_directory over current_image_path
        # current_directory is set SYNCHRONOUSLY in load_directory()
        # current_image_path might still point to OLD directory during async loading
        directory_to_highlight = None

        # First try: Use current_directory (most reliable, set synchronously)
        if hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
            directory_to_highlight = self.main_window.current_directory
        # Second try: Derive from current image (only if current_directory not set)
        elif self.get_current_image_callback:
            current_image_path = self.get_current_image_callback()
            if current_image_path:
                directory_to_highlight = os.path.dirname(current_image_path)

        # Highlight the directory if we have one
        if directory_to_highlight:
            self._highlight_directory_in_tree(directory_to_highlight)

    def highlight_current_file(self, _skip_debounce: bool = False) -> None:
        if not self.file_tree:
            return
        # Use state variable - isVisible() was unreliable for determining tree visibility
        if not getattr(self.main_window, 'file_tree_visible', False):
            if not (hasattr(self.main_window, 'combined_sidebar') and self.main_window.combined_sidebar.is_tree_visible()):
                return
        if not self.is_tree_initialized():
            return

        if not self.get_current_image_callback:
            return
        current_image_path = self.get_current_image_callback()
        if not current_image_path:
            return

        # Skip if same file - no tree update needed (performance: avoids work when unchanged)
        if current_image_path == getattr(self, '_last_highlighted_file', None):
            return

        # Skip if same directory - tree already shows correct directory (performance)
        current_dir_from_path = os.path.dirname(current_image_path)
        if current_dir_from_path == getattr(self, '_last_highlighted_directory', None):
            self._last_highlighted_file = current_image_path
            return

        # CRITICAL: Verify current_image_path matches current_directory before highlighting
        # This prevents highlighting old directory when new directory is loading
        main_current_dir = getattr(self.main_window, 'current_directory', None)

        # If user_requested_directory is set, only proceed if image is from that directory
        # This prevents highlighting wrong directory while user-requested directory is loading
        # Exception: In specific files mode, files can be from many directories - always allow sync
        if self.user_requested_directory and not getattr(self.main_window, 'specific_files_active', False):
            if current_dir_from_path != self.user_requested_directory:
                return
            # Image is from correct directory, allow it to proceed

        import traceback
        is_during_deletion = any('delete_' in frame.name for frame in traceback.extract_stack())
        if is_during_deletion and getattr(self.main_window, 'current_view_mode', '') == 'thumbnail':
            return
        if not getattr(self, '_initial_file_loaded', False) or self._is_tree_showing_only_root():
            dir_path = os.path.dirname(current_image_path)
            if self._needs_priority_paths():
                self._add_path_to_priority_paths(dir_path)
            self._expand_initial_tree(current_image_path)
            self._initial_file_loaded = True
            # DGN 2025-11-13: delay to force hilite
            QTimer.singleShot(200, lambda: self.main_window.highlight_image())

        else:
            # Debounce 200ms when holding scroll key - coalesce rapid updates
            if not _skip_debounce:
                self._schedule_tree_highlight_debounced()
                return

            current_dir = os.path.dirname(current_image_path)
            last_dir = getattr(self, '_last_highlighted_directory', None)
            directory_changed = current_dir != last_dir

            if directory_changed:
                if not self._is_directory_visible_in_tree(current_dir):
                    if self._needs_priority_paths():
                        filter_needs_update = self._add_path_to_priority_paths(current_dir)
                        if filter_needs_update:
                            self.filter_proxy.invalidateFilter()
                            # ExcludeUserInputEvents - avoid GIL deadlock when called from timer callback
                            QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
                    self._scroll_to_directory(current_dir)
                # Don't set _last_highlighted_directory here - _highlight_directory_in_tree sets it
                # when it actually does the work. Setting it here caused first-time highlight to be skipped.

            # Always highlight directory when navigating images (unless user is navigating in tree)
            if not getattr(self, '_user_input_selection', False):
                self._highlight_directory_in_tree(current_dir)

            # Always expand to path to ensure tree stays synced (even if directory unchanged)
            # The _expand_to_path() method will optimize by skipping if already expanded
            self._expand_to_path(os.path.dirname(current_image_path))

            # Track last highlighted file so we can skip redundant updates
            self._last_highlighted_file = current_image_path

    def _schedule_tree_highlight_debounced(self) -> None:
        """Debounce tree updates by 200ms - when user holds scroll key, coalesce rapid updates"""
        if self._tree_highlight_debounce_timer and self._tree_highlight_debounce_timer.isActive():
            self._tree_highlight_debounce_timer.stop()
        if not self._tree_highlight_debounce_timer:
            self._tree_highlight_debounce_timer = QTimer()
            self._tree_highlight_debounce_timer.setSingleShot(True)
            self._tree_highlight_debounce_timer.timeout.connect(lambda: self.highlight_current_file(_skip_debounce=True)
            )
        self._tree_highlight_debounce_timer.start(TREE_UPDATE_DEBOUNCE_TIMER)

    def _expand_initial_tree(self, file_path: str) -> None:
        if not file_path or not os.path.exists(file_path):
            return
        try:
            self._initial_file_loaded = True
            dir_path = os.path.dirname(file_path)
            # Only refresh if the directory has changed
            if dir_path != self._last_refreshed_directory:
                # Root should match that set above - use "/" on macOS
                root_path = "/"
                root_index = self.file_model.index(root_path)
                proxy_root = self._safe_map_from_source(root_index) if root_index.isValid() else QModelIndex()
                if proxy_root and proxy_root.isValid():
                    self.file_tree.setRootIndex(proxy_root)
                path_components: List[str] = []
                current_path = dir_path
                while current_path and current_path != root_path and current_path != os.path.dirname(current_path):
                    path_components.append(current_path)
                    current_path = os.path.dirname(current_path)
                path_components.append(root_path)
                path_components.reverse()
                # Expand all paths first, then process events once
                for path in path_components:
                    model_idx = self.file_model.index(path)
                    if model_idx.isValid():
                        proxy_idx = self._safe_map_from_source(model_idx)
                        if proxy_idx and proxy_idx.isValid():
                            self.file_tree.expand(proxy_idx)
                # Process events once after all expansions
                QApplication.processEvents()
                self._force_model_refresh()
                self._last_refreshed_directory = dir_path
            self._highlight_directory_in_tree(dir_path)
            # No files to select, so skip file selection
            self.file_tree.repaint()
            self.current_highlighted_file = file_path
        except Exception:
            traceback.print_exc()

    def _highlight_directory_in_tree(self, directory_path: str) -> None:
        if not self.file_model or not self.file_tree:
            return

        current_dir = getattr(self.main_window, 'current_directory', None)

        # CRITICAL: If user_requested_directory is set, ONLY highlight that directory
        # Any other directory highlight request should be IGNORED completely
        # Exception: In specific files mode, always allow highlighting as user navigates between directories
        if (self.user_requested_directory and directory_path != self.user_requested_directory and
                not getattr(self.main_window, 'specific_files_active', False)):
            return

        # CRITICAL: Don't skip if this is a user-requested directory - always update selection
        # Also skip if user is navigating in tree
        user_is_navigating = getattr(self, '_user_input_selection', False)
        if (not user_is_navigating and
            getattr(self, '_last_highlighted_directory', None) == directory_path and
                not (self.user_requested_directory == directory_path)):
            return
        try:
            # Ensure directory is visible by adding to priority_paths if filtering is active
            if self._needs_priority_paths():
                filter_needs_update = self._add_path_to_priority_paths(directory_path)
                if filter_needs_update:
                    self.filter_proxy.invalidateFilter()
                    QApplication.processEvents()

            self._expand_to_path(directory_path)
            # CRITICAL: Always select the directory, and update current_highlighted_directory
            if self._select_directory_in_tree(directory_path):
                # _select_directory_in_tree already sets current_highlighted_directory, but ensure it's set
                self.current_highlighted_directory = directory_path
                self._last_highlighted_directory = directory_path
        except Exception:
            pass

    def eventFilter(self, obj, event):
        """Event filter to detect user input (mouse/keyboard) on the file tree"""
        if obj == self.file_tree:
            if event.type() in [QEvent.MouseButtonPress, QEvent.KeyPress]:
                # User input detected - set flag to allow selection processing
                self._user_input_selection = True
                # Reset flag after a short delay
                QTimer.singleShot(200, lambda: setattr(self, '_user_input_selection', False))
        return super().eventFilter(obj, event)

    def _is_directory_visible_in_tree(self, dir_path: str) -> bool:
        try:
            if dir_path in self._directory_visibility_cache:
                return self._directory_visibility_cache[dir_path]
            if not self.file_tree or not self.file_model or not self.filter_proxy:
                return False
            index = self.file_model.index(dir_path)
            if not index.isValid():
                self._directory_visibility_cache[dir_path] = False
                return False
            proxy_index = self._safe_map_from_source(index)
            if not proxy_index or not proxy_index.isValid():
                self._directory_visibility_cache[dir_path] = False
                return False
            rect = self.file_tree.visualRect(proxy_index)
            viewport_rect = self.file_tree.viewport().rect()
            is_visible = viewport_rect.intersects(rect) and rect.width() > 0 and rect.height() > 0
            # Limit cache size to prevent unbounded growth
            if len(self._directory_visibility_cache) >= self._max_visibility_cache_size:
                # Remove oldest entries (simple FIFO - remove first key)
                oldest_key = next(iter(self._directory_visibility_cache))
                del self._directory_visibility_cache[oldest_key]
            self._directory_visibility_cache[dir_path] = is_visible
            return is_visible
        except Exception:
            traceback.print_exc()
            return False

    def _scroll_to_directory(self, dir_path: str) -> bool:
        try:
            if not self.file_tree or not self.file_model or not self.filter_proxy:
                return False
            index = self.file_model.index(dir_path)
            if not index.isValid():
                return False
            proxy_index = self._safe_map_from_source(index)
            if not proxy_index or not proxy_index.isValid():
                return False
            self.file_tree.expand(proxy_index)
            QApplication.processEvents()
            self.file_tree.scrollTo(proxy_index, QTreeView.ScrollHint.EnsureVisible)
            QApplication.processEvents()
            rect = self.file_tree.visualRect(proxy_index)
            viewport_rect = self.file_tree.viewport().rect()
            is_visible = viewport_rect.intersects(rect) and rect.width() > 0 and rect.height() > 0
            self._directory_visibility_cache[dir_path] = is_visible
            return is_visible
        except Exception:
            traceback.print_exc()
            return False

    def get_expanded_directories(self) -> List[str]:
        """Get list of currently expanded directory paths (optimized)"""
        expanded = []
        if not self.file_tree or not self.file_model or not self.filter_proxy:
            return expanded
        try:
            root_index = self.file_tree.rootIndex()
            if not root_index.isValid():
                return expanded

            # Use a stack-based approach instead of recursion for better performance
            stack = []
            row_count = self.filter_proxy.rowCount(root_index)
            for row in range(row_count):
                child_index = self.filter_proxy.index(row, 0, root_index)
                if child_index.isValid():
                    stack.append(child_index)

            while stack:
                index = stack.pop()
                if not index.isValid():
                    continue

                # Check if this directory is expanded
                if self.file_tree.isExpanded(index):
                    source_index = self.filter_proxy.mapToSource(index)
                    if source_index.isValid():
                        dir_path = self.file_model.filePath(source_index)
                        if dir_path and os.path.isdir(dir_path):
                            expanded.append(dir_path)
                            # Add children to stack for processing
                            child_row_count = self.filter_proxy.rowCount(index)
                            for row in range(child_row_count):
                                child_index = self.filter_proxy.index(row, 0, index)
                                if child_index.isValid():
                                    stack.append(child_index)
        except Exception:
            traceback.print_exc()
        return expanded

    def get_all_visible_directory_proxy_indices(self) -> List[Any]:
        """Get proxy indices for all visible directories in tree (for rename status icon refresh)."""
        indices = []
        if not self.file_tree or not self.file_model or not self.filter_proxy:
            return indices
        try:
            root_index = self.file_tree.rootIndex()
            if not root_index.isValid():
                return indices
            stack = []
            for row in range(self.filter_proxy.rowCount(root_index)):
                child_index = self.filter_proxy.index(row, 0, root_index)
                if child_index.isValid():
                    stack.append(child_index)
            while stack:
                index = stack.pop()
                if not index.isValid():
                    continue
                source_index = self.filter_proxy.mapToSource(index)
                if source_index.isValid():
                    path = self.file_model.filePath(source_index)
                    if path and os.path.isdir(path):
                        indices.append(index)
                if self.file_tree.isExpanded(index):
                    for row in range(self.filter_proxy.rowCount(index)):
                        child_index = self.filter_proxy.index(row, 0, index)
                        if child_index.isValid():
                            stack.append(child_index)
        except Exception:
            traceback.print_exc()
        return indices

    def _force_model_refresh(self) -> bool:
        try:
            if self.file_model and self.file_tree:
                # On macOS, use "/" as root to show all directories including /Volumes
                # QDir.Drives is Windows-specific and produces unpredictable results on macOS
                root_path = "/"
                # Set filter based on show_hidden_directories setting (using cached value)
                self.file_model.setFilter(self._get_filter_flags())

                # Collect expanded directories before refresh (to restore expansion after)
                expanded_dirs = self.get_expanded_directories()

                # Force refresh by temporarily setting root to enabled root-level directories then back to /
                enabled_dirs = self._get_enabled_root_directories_cached()
                for root_dir in enabled_dirs:
                    self.file_model.setRootPath(root_dir)
                # Set back to "/" as the primary root
                self.file_model.setRootPath(root_path)
                QApplication.processEvents()

                # Reload expanded directories to force them to refresh with new filter
                for expanded_dir in expanded_dirs:
                    if os.path.isdir(expanded_dir):
                        self.file_model.setRootPath(expanded_dir)
                        QApplication.processEvents()

                # Set back to "/" as the primary root
                self.file_model.setRootPath(root_path)
                QApplication.processEvents()

                if self.filter_proxy:
                    # Clear image cache so new directories are properly checked
                    if hasattr(self.filter_proxy, 'has_images_cache'):
                        self.filter_proxy.has_images_cache.clear()
                    self.filter_proxy.invalidate()
                    QApplication.processEvents()
                root_index = self.file_model.index(root_path)
                if root_index.isValid():
                    proxy_root = self._safe_map_from_source(root_index)
                    if proxy_root and proxy_root.isValid():
                        self.file_tree.setRootIndex(proxy_root)
                self.file_tree.reset()
                self.file_tree.repaint()
                self.file_tree.viewport().repaint()
                QApplication.processEvents()
                return True
        except Exception:
            traceback.print_exc()
        return False

    def _on_file_model_directory_loaded(self, path: str) -> None:
        """Handle Qt file_model.directoryLoaded signal - scroll to pending file when its directory loads"""
        try:
            if not getattr(self, '_pending_scroll_file', None):
                return
            pending = self._pending_scroll_file
            if pending.startswith(path):
                idx = self.file_model.index(pending)
                if idx.isValid():
                    proxy_idx = self._safe_map_from_source(idx)
                    if proxy_idx and proxy_idx.isValid():
                        self.file_tree.scrollTo(proxy_idx)
                    self._pending_scroll_file = None
                    try:
                        self.filter_proxy.priority_paths = set()
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_tree_item_expanded(self, index: QModelIndex) -> None:
        """Handle tree item expansion - update rename status for newly visible directories"""
        try:
            if not self.main_window or not hasattr(self.main_window, 'rename_status_manager'):
                return
            if not self.main_window.rename_status_manager.is_enabled():
                return

            # Get the directory path for this expanded item
            source_index = self.filter_proxy.mapToSource(index)
            if source_index.isValid():
                dir_path = self.file_model.filePath(source_index)
                if dir_path and os.path.isdir(dir_path):
                    # Update rename status for this directory and its immediate children
                    if hasattr(self.main_window, 'update_rename_status'):
                        # Use a small delay to batch multiple expansions
                        QTimer.singleShot(200, self.main_window.update_rename_status)
        except Exception:
            pass

    def _on_tree_item_collapsed(self, index: QModelIndex) -> None:
        """Handle tree item collapse - no action needed, just update display"""
        try:
            # Trigger icon update for collapsed item
            if self.filter_proxy:
                self.filter_proxy.dataChanged.emit(index, index, [Qt.DecorationRole])
        except Exception:
            pass

    def _get_collapse_fallback_directory(self) -> str:
        """Get the fallback directory when collapsing with no current image.
        Structured for future configurability (e.g. config setting)."""
        # Future: settings.get('collapse_fallback_directory', None) -> expand if None
        return os.path.expanduser("~")

    def go_to_home_directory(self) -> None:
        # Collapse all and expand to user directory (same behavior as cmd-enter/cmd-return)
        # The collapse_all() method will handle expansion, highlighting, and opening
        self.collapse_all()

    def go_to_parent_directory(self) -> None:
        if hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
            parent_dir = os.path.dirname(self.main_window.current_directory)
            if parent_dir != self.main_window.current_directory:
                self.update_root_directory(parent_dir)
                try:
                    self.main_window.directory_stack_history_handler.save_current_state("file_tree_handler.go_to_parent_directory", delay=0.0)
                except Exception:
                    pass
                self.main_window.load_directory(parent_dir, external_load=True)

    def _expand_root_to_home(self) -> None:
        try:
            model = self.file_tree.model()
            if not model:
                return
            root_index = self.file_tree.rootIndex()
            if not root_index.isValid():
                root_index = model.index(0, 0)
                if not root_index.isValid():
                    return
            self.file_tree.expand(root_index)
            users_index: Optional[QModelIndex] = None
            volumes_index: Optional[QModelIndex] = None
            for row in range(model.rowCount(root_index)):
                child_index = model.index(row, 0, root_index)
                if child_index.isValid():
                    source_model = model.sourceModel()
                    if source_model:
                        child_source_index = model.mapToSource(child_index)
                        child_path = source_model.filePath(child_source_index)
                        if child_path == "/Users":
                            users_index = child_index
                        elif child_path == "/Volumes":
                            volumes_index = child_index
            # Expand /Volumes one level if it has any directories (filter handles exclusions)
            if volumes_index and volumes_index.isValid() and model.rowCount(volumes_index) > 0:
                self.file_tree.expand(volumes_index)
            if users_index and users_index.isValid():
                self.file_tree.expand(users_index)
                home_dir = os.path.expanduser("~")
                home_username = os.path.basename(home_dir)
                home_index: Optional[QModelIndex] = None
                for row in range(model.rowCount(users_index)):
                    child_index = model.index(row, 0, users_index)
                    if child_index.isValid():
                        source_model = model.sourceModel()
                        if source_model:
                            child_source_index = model.mapToSource(child_index)
                            child_path = source_model.filePath(child_source_index)
                            if child_path == home_dir or os.path.basename(child_path) == home_username:
                                home_index = child_index
                                self.file_tree.expand(child_index)
                                break

            # Determine target: prefer current image dir (keep image as-is), else fallback
            fallback_dir = self._get_collapse_fallback_directory()
            target_dir = fallback_dir
            use_loading = True
            if self.get_current_image_callback:
                current_image_path = self.get_current_image_callback()
                if current_image_path and os.path.isfile(current_image_path):
                    target_dir = os.path.dirname(current_image_path)
                    use_loading = False  # Keep current image as-is, don't load

            # Ensure target is visible in filtered tree
            if self._needs_priority_paths():
                self._add_path_to_priority_paths(target_dir)
                if getattr(self, 'filter_proxy', None):
                    self.filter_proxy.invalidateFilter()
                    QApplication.processEvents()

            def highlight_and_open():
                try:
                    self.user_requested_directory = target_dir
                    self.current_highlighted_directory = target_dir
                    if hasattr(self, '_clear_user_requested_timer'):
                        self._clear_user_requested_timer.stop()
                    self._expand_to_path(target_dir, force_expand=True)
                    if self._select_directory_in_tree(target_dir):
                        if use_loading:
                            self.request_directory_opening(target_dir)
                        else:
                            if not hasattr(self, '_clear_user_requested_timer'):
                                self._clear_user_requested_timer = QTimer()
                                self._clear_user_requested_timer.setSingleShot(True)
                                self._clear_user_requested_timer.timeout.connect(lambda: setattr(self, 'user_requested_directory', None))
                            self._clear_user_requested_timer.stop()
                            self._clear_user_requested_timer.start(2000)
                except Exception:
                    pass
            QTimer.singleShot(100, highlight_and_open)
        except Exception:
            pass

    def collapse_all(self) -> None:
        try:
            model = self.file_tree.model()
            if not model:
                return
            root_index = self.file_tree.rootIndex()
            if not root_index.isValid():
                root_index = model.index(0, 0)
                if not root_index.isValid():
                    return
            self._collapse_recursive(root_index)
            QTimer.singleShot(100, lambda: self._expand_root_to_home())
        except Exception:
            pass

    def _collapse_recursive(self, parent_index: QModelIndex) -> None:
        try:
            model = self.file_tree.model()
            if not model:
                return
            for row in range(model.rowCount(parent_index)):
                child_index = model.index(row, 0, parent_index)
                if child_index.isValid() and model.hasChildren(child_index):
                    self.file_tree.collapse(child_index)
                    self._collapse_recursive(child_index)
        except Exception:
            pass

    def get_widget(self) -> Optional[QWidget]:
        """Get the tree widget, initializing it if necessary"""
        self.ensure_tree_initialized()
        return self.file_tree_widget

    def apply_filter_pattern(self, filter_pattern: Optional[str]) -> None:
        if not self.is_tree_initialized():
            return
        if not self.filter_proxy:
            return
        # Normalize pattern for storage (remove trailing asterisk)
        normalized_pattern = ImageBrowserConfig.normalize_filter_pattern(filter_pattern)
        self.current_filter_pattern = normalized_pattern
        self.filter_proxy.set_filter_pattern(normalized_pattern)

    def apply_filtered_tree(self, mode: str) -> None:
        """Apply filtered_tree setting to the filter proxy

        Args:
            mode: 'all', 'images', or 'use_filter' (or bool for backward compatibility)
        """
        if not self.is_tree_initialized():
            return
        if not self.filter_proxy:
            return
        self.filter_proxy.set_filtered_tree(mode)
        # Update button icons when filter mode changes (e.g., from menu)
        if hasattr(self, '_filter_icon_redraw'):
            self._filter_icon_redraw()
        # Update button icons when filter mode changes (e.g., from menu)
        if hasattr(self, '_filter_icon_redraw'):
            self._filter_icon_redraw()

    def navigate_to_file_directory(self, file_path: str) -> None:
        if not self.is_tree_initialized():
            return
        if not file_path or not os.path.isfile(file_path):
            return
        is_in_current_dir = False
        if hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
            is_in_current_dir = os.path.dirname(file_path) == self.main_window.current_directory
        force_expand = self._is_tree_showing_only_root()
        file_directory = os.path.dirname(file_path)
        if not (is_in_current_dir and not force_expand):
            self._expand_to_path(file_directory, force_expand=force_expand)
        self._update_dir_label(file_directory)

    def request_directory_opening(self, directory_path: str) -> None:
        # Track that this is a user-requested directory
        # Clear any previous flag immediately to avoid GIL deadlock from multiple QTimer.singleShot calls
        # We only need the flag for the current directory being loaded
        self.user_requested_directory = directory_path
        # CRITICAL: Set current_highlighted_directory here so _is_user_selection() works correctly
        self.current_highlighted_directory = directory_path

        # CRITICAL: Select the directory IMMEDIATELY before calling load_directory
        # This ensures ONLY this directory is highlighted and prevents any other selection logic from interfering
        if self.is_tree_initialized():
            # Ensure directory is visible
            if self._needs_priority_paths():
                self._add_path_to_priority_paths(directory_path)
                self.filter_proxy.invalidateFilter()
                # ExcludeUserInputEvents to avoid GIL deadlock from nested user input processing
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
            # Expand to the directory
            self._expand_to_path(directory_path, force_expand=True)
            # Select it IMMEDIATELY - this is the ONLY selection that should happen
            self._select_directory_in_tree(directory_path)

        try:
            self.main_window.directory_stack_history_handler.save_current_state("file_tree_handler.request_directory_opening", delay=0.0)
        except Exception:
            pass
        # DON'T call update_root_directory here - load_directory() will call it
        # Calling it here causes the highlight to jump to the new directory, then back to old, then to new again
        current_focus = QApplication.focusWidget()
        tree_has_focus = (current_focus == self.file_tree)
        self.main_window.load_directory(directory_path, external_load=True)
        # Clear the flag after load_directory completes to allow normal operations
        # CRITICAL: Use a longer delay (2 seconds) to ensure ALL delayed highlights have completed
        # This prevents delayed highlights from overriding the correct selection
        # Timers pre-created in __init__ to avoid connect() in this path (GIL deadlock mitigation)
        self._clear_user_requested_timer.stop()  # Cancel any pending clear
        # Increased to 2 seconds to ensure all delays complete
        self._clear_user_requested_timer.start(2000)
        if tree_has_focus:
            self._restore_tree_focus_timer.stop()
            self._restore_tree_focus_timer.start(100)

        # DON'T schedule another highlight here - load_directory() already handles highlighting
        # Multiple highlights cause the selection to jump around

    def _restore_tree_focus(self) -> None:
        try:
            if self.file_tree and self.file_tree.isVisible():
                self.file_tree.setFocus()
        except Exception:
            pass

    def open_settings_to_max_images(self) -> None:
        """Open settings dialog to General tab with focus on max_images field"""
        if not self.main_window:
            return
        # Show settings dialog with General tab (index 0) and focus on max_images field
        if hasattr(self.main_window, 'show_settings'):
            self.main_window.show_settings()

    def force_expand_directory(self, directory_path: str) -> bool:
        try:
            dir_index = self.file_model.index(directory_path)
            if not dir_index.isValid():
                return False
            proxy_index = self._safe_map_from_source(dir_index)
            if not proxy_index or not proxy_index.isValid():
                return False
            self.file_tree.expand(proxy_index)
            self.file_tree.viewport().update()
            QApplication.processEvents()
            return True
        except Exception:
            return False

    def expand_file_tree(self, depth=None):
        """Expand the file tree from the active node, expanding to specified depth.
        Discovers directories with images (respecting filter settings) by walking the directory tree
        and adds them to priority_paths so they appear in the filtered tree, even if intermediate directories
        don't contain images.

        Args:
            depth: Expand levels for 'all' mode (defaults to shift_cmd_depth from config, or EXPANSION_LEVELS).
                   Walk depth for images/use_filter uses search_depth from config.
        """
        import traceback
        import datetime
        from thumbnail_constants import EXPANSION_LEVELS
        from config import get_config

        # Prevent concurrent expansions
        if self._expand_in_progress:
            return

        self._expand_in_progress = True

        try:
            if not self.is_tree_initialized():
                return
            file_tree_widget = self.get_widget()
            if not file_tree_widget:
                return
            if not file_tree_widget.isVisible():
                return

            file_tree = self.file_tree
            filter_proxy = self.filter_proxy
            file_model = self.file_model
            if not file_tree or not filter_proxy or not file_model:
                return

            # Expand depth (⌘⇧↩) vs walk depth (search_depth) for discovering dirs with images
            try:
                config = get_config()
                settings = config.load_settings()
                walk_max_depth = int(settings.get('search_depth', 4))
                if depth is None:
                    expand_depth = settings.get('shift_cmd_depth', EXPANSION_LEVELS)
                else:
                    expand_depth = depth
            except Exception:
                walk_max_depth = 4
                expand_depth = depth if depth is not None else EXPANSION_LEVELS

            # Get the current selected index, or fallback to root
            selection_model = file_tree.selectionModel()
            if selection_model and selection_model.hasSelection():
                current_index = selection_model.currentIndex()
                if not current_index.isValid():
                    # Try to expand to user's home directory if present under root, else use rootIndex.
                    home_dir = os.path.expanduser("~")
                    matched_home_index = None
                    # Under root, iterate over children to find home dir
                    for row in range(filter_proxy.rowCount(file_tree.rootIndex())):
                        child_idx = filter_proxy.index(row, 0, file_tree.rootIndex())
                        source_idx = filter_proxy.mapToSource(child_idx)
                        child_path = file_model.filePath(source_idx)
                        if child_path == home_dir:
                            matched_home_index = child_idx
                            break
                        # Some platforms: compare by basename
                        if os.path.basename(child_path) == os.path.basename(home_dir):
                            matched_home_index = child_idx
                            break
                    if matched_home_index:
                        current_index = matched_home_index
                    else:
                        current_index = file_tree.rootIndex()
            else:
                current_index = file_tree.rootIndex()

            # Get the starting directory path
            source_index = filter_proxy.mapToSource(current_index)
            if not source_index.isValid() or not file_model.isDir(source_index):
                return

            start_dir = file_model.filePath(source_index)

            # CRITICAL: Set user_requested_directory to start_dir
            # This is a user-initiated action (cmd-shift-return) to expand this directory
            # Setting this flag allows selection restoration to work even if different from current_directory
            self.user_requested_directory = start_dir
            self.current_highlighted_directory = start_dir
            # Cancel any pending timer that would clear the flag
            if hasattr(self, '_clear_user_requested_timer'):
                self._clear_user_requested_timer.stop()

            # CRITICAL: Ensure starting directory is in priority_paths BEFORE invalidating filter
            # This ensures it remains visible and selectable after filter invalidation
            if self._needs_priority_paths():
                self._add_path_to_priority_paths(start_dir)

            # Get filtering mode
            filtered_tree_mode = self._get_filtered_tree_mode()

            # If mode is 'all', we don't need to use find - just expand all directories
            if filtered_tree_mode == 'all':
                # Use simple recursive expansion for 'all' mode
                # remaining_levels: how many more levels to expand (0 = don't expand, 1 = expand this level only)
                def expand_all_levels(index, remaining_levels):
                    if remaining_levels <= 0 or not index.isValid():
                        return
                    file_tree.expand(index)
                    source_idx = filter_proxy.mapToSource(index)
                    if file_model.isDir(source_idx) and remaining_levels > 1:
                        # Only expand children if we have remaining_levels > 1
                        # (remaining_levels=1 means expand this level only, don't recurse)
                        row_count = filter_proxy.rowCount(index)
                        for row in range(row_count):
                            child_idx = filter_proxy.index(row, 0, index)
                            if child_idx.isValid():
                                expand_all_levels(child_idx, remaining_levels - 1)

                # Expand current_index first, then expand its children to the specified depth
                # Depth represents total number of levels to expand (including current_index)
                # So depth=5 means: expand current_index (level 1), then expand 4 more levels below it
                file_tree.expand(current_index)
                QApplication.processEvents()
                # Expand children with depth remaining levels
                # expand_all_levels will expand the index and then recurse with remaining_levels-1
                # So if expand_depth=5, it expands current_index and children with remaining_levels=4
                if expand_depth > 0:
                    QTimer.singleShot(100, lambda: expand_all_levels(current_index, expand_depth))
                return

            # For 'images' or 'use_filter' mode, discover directories with images using Python code
            # Get image extensions
            image_exts = [ext.lower() for ext in get_image_extensions() if ext]

            # If mode is 'use_filter', we need to filter by pattern
            match_pattern = None
            if filtered_tree_mode == 'use_filter' and filter_proxy.filter_pattern:
                pattern = filter_proxy.filter_pattern.strip('*')
                if pattern:
                    match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_proxy.filter_pattern)

            # Get cache directory to exclude
            try:
                config = get_config()
                cache_dir = str(config.cache_dir)
                cache_dir_resolved = os.path.realpath(cache_dir)
                # Get excluded paths (cache, Photos Library, and ignore_directories)
                excluded_paths = _get_excluded_paths(config)
            except Exception:
                cache_dir_resolved = None
                excluded_paths = []

            # Get process hidden directories setting
            process_hidden = get_show_hidden_directories()
            # Get follow symlinks setting
            follow_symlinks = get_follow_symlinks()

            # Walk directories recursively to find image files
            directories_with_images = set()
            walk_count = 0

            try:
                for root, dirs, files in os.walk(start_dir):
                    walk_count += 1
                    root_resolved = os.path.realpath(root)

                    # Skip excluded paths (cache, Photos Library, ignore_directories)
                    if _is_excluded_path(root_resolved, excluded_paths):
                        dirs[:] = []  # Don't recurse into excluded directory
                        continue

                    # Skip cache directory and its subdirectories (redundant check, but keep for safety)
                    if cache_dir_resolved and (root_resolved == cache_dir_resolved or
                                               root_resolved.startswith(cache_dir_resolved + os.sep)):
                        dirs[:] = []  # Don't recurse into cache directory
                        continue

                    # Filter hidden directories if not processing them
                    if not process_hidden:
                        dirs[:] = [d for d in dirs if not d.startswith('.')]

                    # Filter symlinks if not following them (except enabled root dirs on Directories tab)
                    filter_walk_symlink_dirs(root, dirs, follow_symlinks)

                    # Skip directories matching SKIPPED_PATTERNS
                    skip_dir = False
                    for pattern in SKIPPED_PATTERNS:
                        if pattern in root:
                            skip_dir = True
                            break
                    if skip_dir:
                        dirs[:] = []  # Don't recurse into skipped directories
                        continue

                    # Skip directories inside Photos Library resources or scopes
                    if is_inside_photos_library_resources_or_scopes(root):
                        # Don't recurse into Photos Library internal directories
                        dirs[:] = []
                        continue

                    # Calculate depth relative to start_dir
                    rel_path = os.path.relpath(root, start_dir)
                    if rel_path == '.':
                        current_depth = 0
                    else:
                        current_depth = len([p for p in rel_path.split(os.sep) if p])

                    # Stop when depth >= walk_max_depth (search_depth setting)
                    # max_depth=4 means: root (depth 0), subdir (depth 1), subsubdir (depth 2), subsubsubdir (depth 3)
                    # This scans 4 levels total (depths 0-3)
                    if current_depth >= walk_max_depth:
                        dirs[:] = []  # Don't recurse deeper than walk_max_depth
                        continue

                    # Check files in this directory
                    for file in files:
                        if get_file_extension(file) in image_exts:
                            file_path = f"{root}/{file}"

                            # Skip files in skipped patterns
                            skip_file = False
                            for pattern in SKIPPED_PATTERNS:
                                if pattern in file_path:
                                    skip_file = True
                                    break
                            if skip_file:
                                continue

                            # If mode is 'use_filter', check if filename matches the filter pattern
                            if match_pattern:
                                filename = file
                                if not fnmatch.fnmatch(filename.lower(), match_pattern.lower()):
                                    continue

                            # Add this directory and all its parent directories up to start_dir
                            image_dir = root
                            current_path = image_dir
                            while current_path and current_path != os.path.dirname(start_dir):
                                try:
                                    if os.path.commonpath([current_path, start_dir]) == os.path.commonpath([start_dir]):
                                        directories_with_images.add(current_path)
                                    parent = os.path.dirname(current_path)
                                    if parent == current_path:  # Reached root
                                        break
                                    current_path = parent
                                except (ValueError, OSError):
                                    # Path comparison failed (e.g., different drives on Windows)
                                    break

                            # Only need to find one matching image per directory for tree expansion
                            # Break to move to next directory
                            break
            except (PermissionError, OSError) as e:
                # Handle permission errors gracefully - continue with what we found
                import traceback
                traceback.print_exc()
            except Exception:
                import traceback
                traceback.print_exc()
                raise

            # Pre-compute the optimized expansion paths BEFORE invalidating filter
            # This is just string processing and should be instant
            directories_list = list(directories_with_images)
            unique_paths_to_expand = set()

            for dir_path in directories_list:
                # Add all path components from start_dir to this directory
                current_path = dir_path
                path_components = []

                # Build list of all parent paths from this directory up to start_dir
                # We need to expand each level to make the next level visible
                while current_path:
                    try:
                        # Only include paths that are within or equal to start_dir
                        if os.path.commonpath([current_path, start_dir]) == os.path.commonpath([start_dir]):
                            # Stop when we reach start_dir (it's already expanded)
                            if current_path == start_dir:
                                break
                            path_components.append(current_path)
                        parent = os.path.dirname(current_path)
                        if parent == current_path:  # Reached root
                            break
                        current_path = parent
                    except (ValueError, OSError):
                        break

                # Add all these path components to our set
                unique_paths_to_expand.update(path_components)

            # Convert to sorted list by depth (shallowest first)
            # This ensures parent nodes are expanded before children
            paths_to_expand = sorted(unique_paths_to_expand, key=lambda p: p.count(os.sep))
            # Add ALL paths we need to expand to priority_paths (including intermediate parents)
            # This ensures they're visible in the tree
            added_count = 0
            if hasattr(filter_proxy, 'priority_paths'):
                # Add all paths we need to expand (includes all parent paths)
                for dir_path in paths_to_expand:
                    if dir_path not in filter_proxy.priority_paths:
                        filter_proxy.priority_paths.add(dir_path)
                        added_count += 1
                # Also add directories_with_images in case any weren't in paths_to_expand
                for dir_path in directories_with_images:
                    if dir_path not in filter_proxy.priority_paths:
                        filter_proxy.priority_paths.add(dir_path)
                        added_count += 1
                if added_count > 0:
                    # Invalidate filter to ensure new priority paths are visible
                    # Note: invalidateFilter() may reset expansion state, so we'll re-expand after
                    # Store current expansion state before invalidating
                    expanded_before = set()
                    if file_tree:
                        for row in range(filter_proxy.rowCount(file_tree.rootIndex())):
                            idx = filter_proxy.index(row, 0, file_tree.rootIndex())
                            if idx.isValid() and file_tree.isExpanded(idx):
                                source_idx = filter_proxy.mapToSource(idx)
                                if source_idx.isValid():
                                    expanded_before.add(file_model.filePath(source_idx))
                    filter_proxy.invalidateFilter()
                    QApplication.processEvents()
                    # Re-expand nodes that were expanded before
                    if expanded_before:
                        for path in expanded_before:
                            source_idx = file_model.index(path)
                            if source_idx.isValid():
                                proxy_idx = filter_proxy.mapFromSource(source_idx)
                                if proxy_idx.isValid():
                                    file_tree.expand(proxy_idx)

            # Now expand the tree to show all these directories
            # Optimized approach: collect all unique path components and expand them in depth order
            # Qt's expand() only expands one level, so we need to expand each level explicitly
            # But we can optimize by only expanding each unique path once
            def expand_discovered_directories():
                QApplication.processEvents()

                # Look up starting directory fresh after filter invalidation (don't use stored index)
                # The index may have become invalid after invalidateFilter()
                start_source_idx = file_model.index(start_dir)
                if start_source_idx.isValid():
                    start_proxy_idx = self._safe_map_from_source(start_source_idx)
                    if start_proxy_idx and start_proxy_idx.isValid():
                        file_tree.expand(start_proxy_idx)
                        file_tree.scrollTo(start_proxy_idx, QTreeView.ScrollHint.EnsureVisible)
                QApplication.processEvents()

                # Track which paths we've successfully expanded
                expanded_paths = set()

                # Helper to expand a single path, ensuring parent is expanded first
                def expand_single_path(dir_path):
                    """Expand a single path, ensuring its parent is expanded first"""
                    # Check if parent needs to be expanded first
                    parent_path = os.path.dirname(dir_path)
                    if parent_path != dir_path and parent_path != start_dir:
                        # Parent is not start_dir, check if it needs expansion
                        if parent_path in paths_to_expand and parent_path not in expanded_paths:
                            # Parent is in our list but not yet expanded - expand it first
                            if expand_single_path(parent_path):
                                # Parent expanded, now try this path
                                pass
                            else:
                                # Parent expansion failed, this will likely fail too
                                return False

                    # Skip if already expanded
                    if dir_path in expanded_paths:
                        return True

                    try:
                        # Validate models are still current before using indices
                        if filter_proxy.sourceModel() != file_model:
                            # Model changed during operation, abort
                            return False

                        # Look up the index for this directory fresh each time
                        # Never store indices - they can become invalid when model changes
                        # Always use file paths (strings) and look up indices right before use
                        source_idx = file_model.index(dir_path)
                        if not source_idx.isValid():
                            return False

                        # Use safe mapping method to avoid Qt warnings
                        proxy_idx = self._safe_map_from_source(source_idx)
                        if not proxy_idx or not proxy_idx.isValid():
                            return False

                        # Check if already expanded - lookup fresh to ensure index is still valid
                        fresh_source_idx = file_model.index(dir_path)
                        if fresh_source_idx.isValid():
                            fresh_proxy_idx = self._safe_map_from_source(fresh_source_idx)
                            if fresh_proxy_idx and fresh_proxy_idx.isValid() and file_tree.isExpanded(fresh_proxy_idx):
                                expanded_paths.add(dir_path)
                                return True

                        # Expand this directory - lookup index one more time right before use
                        # to ensure it's still valid (model may have changed during batch processing)
                        final_source_idx = file_model.index(dir_path)
                        if not final_source_idx.isValid():
                            return False

                        # Use safe mapping method to avoid Qt warnings
                        final_proxy_idx = self._safe_map_from_source(final_source_idx)
                        if not final_proxy_idx or not final_proxy_idx.isValid():
                            return False

                        file_tree.expand(final_proxy_idx)
                        # Scroll to make expanded node visible (but don't scroll for every node - too slow)
                        # Only scroll for the first few nodes to ensure visibility
                        if len(expanded_paths) < 5:
                            file_tree.scrollTo(final_proxy_idx, QTreeView.ScrollHint.EnsureVisible)
                        expanded_paths.add(dir_path)
                        return True
                    except Exception:
                        return False

                # Expand directories in batches for better performance
                # Only process events between batches to avoid invalidating indices during expansion
                BATCH_SIZE = 20  # Expand 20 directories per batch

                def expand_next_batch(start_idx=0):
                    if start_idx >= len(paths_to_expand):
                        return

                    # Expand a batch of directories without processing events during expansion
                    # This prevents indices from becoming invalid due to model changes
                    end_idx = min(start_idx + BATCH_SIZE, len(paths_to_expand))
                    for idx in range(start_idx, end_idx):
                        dir_path = paths_to_expand[idx]
                        expand_single_path(dir_path)

                    # Process events after batch to update UI and handle user input
                    QApplication.processEvents()

                    # Continue with next batch after minimal delay (just to keep UI responsive)
                    if end_idx < len(paths_to_expand):
                        QTimer.singleShot(10, lambda: expand_next_batch(end_idx))

                # Start expanding after minimal delay
                QTimer.singleShot(50, lambda: expand_next_batch(0))

            # Use QTimer to ensure filter has updated before expanding
            # Increased delay to give filter time to update after invalidateFilter()

            # Store start_dir to restore selection after expansion
            def expand_and_restore_selection():
                try:
                    expand_discovered_directories()
                    # Restore selection to the starting directory after expansion completes
                    # Calculate delay based on number of paths to expand (rough estimate: 10ms per path)
                    delay = max(300, min(1000, len(paths_to_expand) * 10))
                    QTimer.singleShot(delay, lambda: self._restore_selection_after_expansion(start_dir))
                finally:
                    # Always clear the flag, even if there's an error
                    self._expand_in_progress = False
                    # Start timer to clear user_requested_directory after expansion completes
                    if not hasattr(self, '_clear_user_requested_timer'):
                        self._clear_user_requested_timer = QTimer()
                        self._clear_user_requested_timer.setSingleShot(True)
                        self._clear_user_requested_timer.timeout.connect(lambda: setattr(self, 'user_requested_directory', None))
                    self._clear_user_requested_timer.stop()
                    self._clear_user_requested_timer.start(2000)

            QTimer.singleShot(200, expand_and_restore_selection)

        except Exception as e:
            print(f"Exception in expand_file_tree: {e}\n{traceback.format_exc()}")
            self._expand_in_progress = False
            # Start timer to clear user_requested_directory even on error
            if not hasattr(self, '_clear_user_requested_timer'):
                self._clear_user_requested_timer = QTimer()
                self._clear_user_requested_timer.setSingleShot(True)
                self._clear_user_requested_timer.timeout.connect(lambda: setattr(self, 'user_requested_directory', None))
            self._clear_user_requested_timer.stop()
            self._clear_user_requested_timer.start(2000)

    def _restore_selection_after_expansion(self, directory: str):
        """Restore selection to a directory after expansion completes"""
        try:
            self._select_directory_in_tree(directory)
        except Exception:
            pass

    def collapse_file_tree(self):
        """Collapse the file tree if it's visible, otherwise do nothing silently"""
        try:
            # Check if file tree is visible
            if self.is_tree_initialized():
                file_tree_widget = self.get_widget()
                if file_tree_widget and file_tree_widget.isVisible():
                    # Tree is visible, collapse it and highlight home directory
                    self.collapse_all()
                    # collapse_all() calls _expand_root_to_home() which highlights home directory
                # If tree is not visible, do nothing silently (no error messages)
        except Exception:
            # Silently handle any errors - don't show error messages
            pass
