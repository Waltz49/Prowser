#!/usr/bin/env python3
"""
Menu Manager for Image Browser
Handles menu bar setup, actions, and theme management
"""

# Standard library imports
import fnmatch
import hashlib
import os
import random
import sys
import traceback
from typing import Any, Dict, List, Optional

# Third-party imports
from PySide6.QtCore import Qt, QTimer, QSize, QPoint, QMutexLocker
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QKeySequence,
    QPainter,
    QPen,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QWidget,
    QHBoxLayout,
    QWidgetAction,
)

# Local imports
from theme.theme_service import get_active_theme
from event_bus import SELECTION_CHANGED, DIRECTORY_LOADED, FILE_OPERATION_COMPLETE
from cache.cache_prepopulator import prepopulate_cache
from files.external_editor import edit_current_image_with_editor
from config import get_config
from files.file_tree_handler import _get_excluded_paths, _is_excluded_path
from thumbnails.thumbnail_constants import RED, RESET, SKIPPED_PATTERNS, get_image_extensions
from utils import (
    is_macos_space_mode,
    create_gear_icon,
    normalize_path_for_display,
    is_root_or_system_volume,
    show_styled_warning,
    show_styled_critical,
    show_styled_information,
    show_styled_question,
    get_file_extension,
)
from quick_person_search import run_quick_person_search, get_deduped_selected_image_paths, MAX_QUICK_PERSON_IMAGES

_DEFAULT_RANDOM_IMAGES_TARGET_COUNT = 200
_MAX_RANDOM_IMAGES_UNIQUE_DIRS = 5


def _is_subpath(child: str, parent: str) -> bool:
    """True if child is equal to or under parent."""
    parent_norm = os.path.normpath(parent).rstrip(os.sep) + os.sep
    child_norm = os.path.normpath(child)
    return child_norm == parent_norm.rstrip(os.sep) or child_norm.startswith(parent_norm)


def _get_unique_highest_level_dirs(recent_dirs: list[str], max_count: int) -> list[str]:
    """
    From recent_dirs (most recent first), return up to max_count unique highest-level dirs.
    If abc and abc/foo are in the list, keep abc (parent) and drop abc/foo.
    """
    selected: list[str] = []
    for candidate in recent_dirs:
        if len(selected) >= max_count:
            break
        candidate = os.path.normpath(candidate)
        if not os.path.isdir(candidate):
            continue
        if any(_is_subpath(candidate, s) for s in selected):
            continue
        selected = [s for s in selected if not _is_subpath(s, candidate)]
        selected.append(candidate)
    return selected[:max_count]


def _should_skip_random_subdir(dirpath: str, d: str, excluded_paths: list) -> bool:
    """True if subdir d should be skipped (matches SKIPPED_PATTERNS or is under excluded path)."""
    if any(fnmatch.fnmatch(d, p) for p in SKIPPED_PATTERNS):
        return True
    try:
        subpath = os.path.join(dirpath, d)
        return _is_excluded_path(os.path.realpath(subpath), excluded_paths)
    except Exception:
        return True


def _collect_random_image_files(
    search_dirs: list[str], config, progress_dialog: Optional[QProgressDialog] = None
) -> list[str]:
    """Recursively collect image files from search directories up to search_depth."""
    image_extensions = get_image_extensions()
    excluded_paths = _get_excluded_paths(config)
    max_depth = int(config.load_settings().get('search_depth', 4))
    files = []
    dir_count = 0
    for root_dir in search_dirs:
        if not os.path.isdir(root_dir):
            continue
        stack = [(root_dir, 0)]
        while stack:
            if progress_dialog and progress_dialog.wasCanceled():
                return []
            dirpath, depth = stack.pop()
            try:
                dirpath_resolved = os.path.realpath(dirpath)
            except Exception:
                dirpath_resolved = dirpath
            if _is_excluded_path(dirpath_resolved, excluded_paths):
                continue
            try:
                with os.scandir(dirpath) as entries:
                    for entry in entries:
                        if entry.is_file():
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in image_extensions:
                                files.append(entry.path)
                        elif entry.is_dir(follow_symlinks=False) and depth < max_depth:
                            if not _should_skip_random_subdir(dirpath, entry.name, excluded_paths):
                                stack.append((entry.path, depth + 1))
            except (PermissionError, OSError, FileNotFoundError):
                pass
            dir_count += 1
            if progress_dialog and dir_count % 50 == 0:
                progress_dialog.setLabelText(f"Scanning... {len(files)} images found")
                QApplication.processEvents()
    return files


def run_random_images_from_recents(
    main_window, target_count: int = _DEFAULT_RANDOM_IMAGES_TARGET_COUNT
) -> bool:
    """
    Load target_count random images from the first 5 unique recent directories.
    Returns True if images were loaded, False otherwise.
    """
    mw = main_window
    handler = getattr(mw, 'directory_history_handler_for_menu', None)
    if not handler:
        return False
    recent_raw = getattr(handler, 'directory_history', [])
    tmp_trashes = getattr(mw, 'TMP_TRASHES_DIR', None)
    filtered = [
        d for d in reversed(recent_raw)
        if os.path.exists(d) and (tmp_trashes is None or d != tmp_trashes)
    ]
    search_dirs = _get_unique_highest_level_dirs(filtered, _MAX_RANDOM_IMAGES_UNIQUE_DIRS)
    if not search_dirs:
        return False
    config = getattr(mw, 'config', None) or get_config()

    progress_dialog = QProgressDialog("Collecting images from recent directories...", None, 0, 0, mw)
    progress_dialog.setWindowTitle("Random Images")
    progress_dialog.setWindowModality(Qt.WindowModal)
    progress_dialog.setCancelButton(None)
    progress_dialog.setMinimumDuration(0)
    progress_dialog.setAutoClose(True)
    progress_dialog.setRange(0, 0)
    progress_dialog.show()
    QApplication.processEvents()

    try:
        files = _collect_random_image_files(search_dirs, config, progress_dialog)
        if not files:
            return False
        progress_dialog.setLabelText("Selecting random images...")
        QApplication.processEvents()
        selected = random.sample(files, min(target_count, len(files)))
        random.shuffle(selected)
        if hasattr(mw, 'load_specific_files'):
            mw.load_specific_files(selected, external_load=True)
            return True
        return False
    finally:
        progress_dialog.close()


class LineWithText(QWidget):
    """Custom widget that draws a horizontal line with text overlay"""
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text

    def paintEvent(self, event):
        painter = QPainter(self)
        color = QColor(get_active_theme().text_disabled_hex)
        pen = QPen(color)
        pen.setWidth(1)
        painter.setPen(pen)
        height = self.height() // 2

        # Draw horizontal line, leave space around the text
        margin = 8
        font = QFont()
        font.setWeight(QFont.Weight.Normal)
        font.setItalic(True)
        painter.setFont(font)
        text = f"  {self.text}  "
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()

        x1 = margin
        x2 = (self.width() - text_width) // 2 - margin
        x3 = (self.width() + text_width) // 2 + margin
        x4 = self.width() - margin

        if x2 > x1:
            painter.drawLine(x1, height, x2, height)
        if x4 > x3:
            painter.drawLine(x3, height, x4, height)
        # Draw the text
        painter.setPen(QPen(color))
        painter.drawText((self.width() - text_width)//2, height + text_height//3, text)

    def sizeHint(self):
        return QSize(200, 22)


class TextSeparator(QWidget):
    """Custom separator widget with text overlay for menus"""
    def __init__(self, text, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 3, 5, 3)
        line_with_text = LineWithText(text, self)
        layout.addWidget(line_with_text)

# Delay after initial window layout before priming macOS menu shortcuts (main thread).
STARTUP_MENU_SHORTCUT_DELAY_MS = 1500

_face_engine_available_cached: Optional[bool] = None


def _face_engine_available() -> bool:
    """Cached face_engine availability (import is expensive on startup)."""
    global _face_engine_available_cached
    if _face_engine_available_cached is not None:
        return _face_engine_available_cached
    try:
        from faces.face_engine import is_available as face_available

        _face_engine_available_cached = face_available()
    except ImportError:
        _face_engine_available_cached = False
    return _face_engine_available_cached


class MenuManager:
    """Manages menu bar, actions, and theme for the Image Browser"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        self.file_operations_manager = main_window.file_operations_manager
        self.is_mac = True
        self._startup_menu_shortcuts_done = False
        self._startup_menu_shortcut_timer = QTimer()
        self._startup_menu_shortcut_timer.setSingleShot(True)
        self._startup_menu_shortcut_timer.timeout.connect(self._run_startup_menu_shortcut_priming)
        self._deferred_tools_menu_pending = False
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            main_window.event_bus.subscribe(SELECTION_CHANGED, self._on_selection_changed)
            main_window.event_bus.subscribe(DIRECTORY_LOADED, self._on_directory_loaded)
            main_window.event_bus.subscribe(FILE_OPERATION_COMPLETE, self._on_file_operation_complete)
        
    def _on_selection_changed(self, selected=None, highlight_index=None):
        """Handle SELECTION_CHANGED event - update menu enabled states"""
        self.update_edit_menu_states()
        mw = self.main_window
        if getattr(mw, "_loading_directory_mode", False) or getattr(
            mw, "_batch_directory_load", False
        ):
            if not self._deferred_tools_menu_pending:
                self._deferred_tools_menu_pending = True

                def _deferred_menu_updates() -> None:
                    self._deferred_tools_menu_pending = False
                    self.update_tools_menu_states()
                    self.update_search_menu_states()

                QTimer.singleShot(0, _deferred_menu_updates)
            return
        self.update_tools_menu_states()
        self.update_search_menu_states()

    def _on_directory_loaded(self, directory=None, displayed_count=None, external_load=None):
        """Handle DIRECTORY_LOADED event - update search menu states"""
        self.update_search_menu_states()

    def _on_file_operation_complete(self, operation_type=None, paths=None, success=None):
        """Handle FILE_OPERATION_COMPLETE event - update edit menu states (undo, etc.)"""
        self.update_edit_menu_states()
        
    def setup_actions(self):
        """Setup menu bar and toolbar actions"""
        menubar = self.main_window.menuBar()
        menubar.setFocusPolicy(Qt.NoFocus)

        # File menu
        self._setup_file_menu(menubar)
        
        # Edit menu
        self._setup_edit_menu(menubar)
        
        # View menu
        self._setup_view_menu(menubar)
        
        # Search menu
        self._setup_search_menu(menubar)
        
        # Move menu
        self._setup_move_menu(menubar)
        
        # Image menu (optional imagegen plugins)
        try:
            from bundle_capabilities import imagegen_ui_enabled

            if imagegen_ui_enabled():
                from imagegen_plugins.image_gen_menu import setup_create_menu

                setup_create_menu(menubar, self.main_window)
        except ImportError:
            pass
        
        # Tools menu
        self._setup_tools_menu(menubar)
        
        # Help menu
        self._setup_help_menu(menubar)
        
        # Menu states and shortcut priming are deferred until after initial layout
        # (see schedule_startup_menu_shortcut_priming).
    
    def _register_menu_shortcuts_with_window(self):
        """Register all menu actions with the main window so shortcuts work from app startup.
        
        On macOS, Qt's native menu bar may not register shortcuts until the menu is shown.
        Adding actions to the main window via addAction() ensures shortcuts work regardless
        of menu visibility. See: https://forum.qt.io/topic/115009/
        """
        menubar = self.main_window.menuBar()
        window_actions = set(self.main_window.actions())
        
        def add_actions_from_menu(menu):
            if menu is None:
                return
            for action in list(menu.actions()):
                if action.isSeparator():
                    continue
                if isinstance(action, QWidgetAction):
                    continue
                submenu = action.menu()
                if submenu is not None:
                    add_actions_from_menu(submenu)
                elif action not in window_actions:
                    try:
                        if action.shortcut() and not action.shortcut().isEmpty():
                            self.main_window.addAction(action)
                            window_actions.add(action)
                    except (AttributeError, RuntimeError):
                        pass

        for action in list(menubar.actions()):
            submenu = action.menu()
            if submenu is not None:
                add_actions_from_menu(submenu)
            elif action not in window_actions:
                try:
                    if action.shortcut() and not action.shortcut().isEmpty():
                        self.main_window.addAction(action)
                        window_actions.add(action)
                except (AttributeError, RuntimeError):
                    pass

    def schedule_startup_menu_shortcut_priming(
        self, delay_ms: int = STARTUP_MENU_SHORTCUT_DELAY_MS
    ) -> None:
        """Schedule deferred menu shortcut priming after the window reaches its layout size.

        Must run on the Qt main thread (QTimer). On macOS, the native menu bar may not
        register shortcuts until a menu has been shown once; deferring this work keeps
        startup responsive while still fixing the shortcut registration issue.
        """
        if self._startup_menu_shortcuts_done:
            return
        self._startup_menu_shortcut_timer.stop()
        self._startup_menu_shortcut_timer.start(delay_ms)

    def _run_startup_menu_shortcut_priming(self) -> None:
        """Prime menu shortcuts and states after startup layout has settled."""
        if self._startup_menu_shortcuts_done:
            return
        self._startup_menu_shortcuts_done = True
        try:
            self.prime_menu_keys_for_view_change()
            self.initialize_menu_states()
            self._poke_macos_native_menu_bar()
            try:
                from bundle_capabilities import imagegen_ui_enabled

                if imagegen_ui_enabled():
                    from imagegen_plugins.image_gen_menu import _sync_function_menu_shortcuts

                    _sync_function_menu_shortcuts(self.main_window)
                    self._register_menu_shortcuts_with_window()
            except ImportError:
                pass
            mw = self.main_window
            if hasattr(mw, 'focus_canvas'):
                mw.focus_canvas()
            mw.activateWindow()
            mw.raise_()
        except Exception:
            traceback.print_exc()

    def _poke_macos_native_menu_bar(self) -> None:
        """Briefly open one top-level menu off-screen so macOS registers key equivalents."""
        if sys.platform != "darwin":
            return
        menubar = self.main_window.menuBar()
        for top_action in menubar.actions():
            menu = top_action.menu()
            if menu is None:
                continue
            try:
                menu.aboutToShow.emit()
                menu.popup(QPoint(-20000, -20000))
                menu.hide()
            except (RuntimeError, AttributeError):
                pass
            break
    
    def _setup_file_menu(self, menubar):
        """Setup File menu"""
        file_menu = menubar.addMenu("File")
        
        # Open file
        open_action = QAction("Open File...", self.main_window)
        open_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        open_action.triggered.connect(self.main_window.open_file_dialog)
        file_menu.addAction(open_action)
        
        
        # Open Directory
        open_action = QAction("Open Directory...", self.main_window)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.triggered.connect(self.main_window.open_directory_dialog)
        file_menu.addAction(open_action)
        
        # Refresh Directory
        refresh_action = QAction("Refresh Directory", self.main_window)
        refresh_action.setShortcut(QKeySequence("Ctrl+R"))
        # Use refresh_directory(force=True) directly for cmd-R to ensure proper refresh
        refresh_action.triggered.connect(lambda: self.main_window.refresh_directory(force=True))

        file_menu.addAction(refresh_action)
        
        file_menu.addSeparator()
        
        # Settings
        settings_action = QAction("Settings...", self.main_window)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self.main_window.show_settings)
        file_menu.addAction(settings_action)
        
        file_menu.addSeparator()
        
        # Delete File section
        self.main_window.delete_action = QAction("Delete File", self.main_window)
        self.main_window.delete_action.setShortcut(QKeySequence("Ctrl+Backspace"))
        self.main_window.delete_action.triggered.connect(self.file_operations_manager.delete_selected_files)
        file_menu.addAction(self.main_window.delete_action)
        
        file_menu.addSeparator()
        # Only add the Trash action and separator if we can read trash directories
        # (user's home trash or volume-specific trash) and they contain images.
        from files.file_operations_manager import FileOperationsManager
        
        can_view_trash = FileOperationsManager._has_readable_trash_with_images()

        if can_view_trash: 
            file_menu.addSeparator()

            # Trash
            trash_action = QAction("View Copy of Trash...", self.main_window)
            trash_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
            trash_action.triggered.connect(self.main_window.browse_trash_images)
            file_menu.addAction(trash_action)
        
        # About
        about_action = QAction("About...", self.main_window)
        about_action.triggered.connect(self.main_window.show_about)
        file_menu.addAction(about_action)
        
        file_menu.addSeparator()
        
        # Add "Recent..." submenu to File menu to show recent directories

        self.recent_menu = file_menu.addMenu("Recent...")

        # Add "Favorites" submenu to File menu
        self.favorites_menu = file_menu.addMenu("Favorites")

        # Exit
        exit_action = QAction("Exit", self.main_window)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.setMenuRole(QAction.MenuRole.QuitRole)
        exit_action.triggered.connect(self.main_window.close)
        file_menu.addAction(exit_action)

        # Last Image (browse): swap F3 history [0]↔[1], show new first — Cmd+L (Tools Lock uses another key in browse)
        self.main_window.last_image_action = QAction("Last Image", self.main_window)
        self.main_window.last_image_action.setShortcut(QKeySequence("Ctrl+L"))
        self.main_window.last_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.last_image_action.triggered.connect(
            self.main_window.swap_browse_image_history_first_two_and_show
        )
        file_menu.addAction(self.main_window.last_image_action)

        # Image History — last item in File menu (F3)
        self.main_window.browse_image_history_action = QAction("Image History", self.main_window)
        self.main_window.browse_image_history_action.setShortcut(QKeySequence("F3"))
        self.main_window.browse_image_history_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.browse_image_history_action.triggered.connect(self.main_window.open_browse_image_history)
        file_menu.addAction(self.main_window.browse_image_history_action)

        file_menu.aboutToShow.connect(self.update_file_menu_favorites)
        file_menu.aboutToShow.connect(self.update_file_menu_recent_directories)
        file_menu.aboutToShow.connect(self.update_file_menu_can_view_trash)
        file_menu.aboutToShow.connect(self.update_file_menu_delete_action)
        file_menu.aboutToShow.connect(self.update_file_menu_browse_image_history_action)
        file_menu.aboutToShow.connect(self.update_file_menu_last_image_action)
        self.file_menu = file_menu

    
    def _setup_edit_menu(self, menubar):
        """Setup Edit menu"""
        # Create a custom Edit menu - try using a different title to avoid system injection
        edit_menu = menubar.addMenu("Edit\u2060") # \u2060 is a zero-width space to avoid system injection
        # Try setting a custom property to prevent system injection
        # edit_menu.setProperty("_q_systemMenu", False)
        
        # Select All    
        self.main_window.select_all_action = QAction("Select All", self.main_window)
        self.main_window.select_all_action.setShortcut(QKeySequence("Ctrl+A"))
        self.main_window.select_all_action.triggered.connect(self.main_window.select_all_thumbnails)
        edit_menu.addAction(self.main_window.select_all_action)
        
        edit_menu.addSeparator()
        
        # Copy File Path (cmd-c: always copies full path)
        self.main_window.copy_path_action = QAction("Copy File Path", self.main_window)
        self.main_window.copy_path_action.setShortcut(QKeySequence("Ctrl+C"))
        self.main_window.copy_path_action.triggered.connect(self.main_window.copy_file_path_to_clipboard)
        edit_menu.addAction(self.main_window.copy_path_action)
        
        # Copy image (ctrl-C on macOS: copies image content to clipboard for paste into graphics apps)
        self.main_window.copy_image_action = QAction("Copy Image", self.main_window)
        # On macOS: Qt.MetaModifier = Control (⌃), Qt.ControlModifier = Command (⌘)
        self.main_window.copy_image_action.setShortcut(QKeySequence(Qt.Key_C | Qt.MetaModifier))
        self.main_window.copy_image_action.triggered.connect(self.main_window.copy_image_to_clipboard)
        edit_menu.addAction(self.main_window.copy_image_action)

        self.main_window.copy_user_comment_action = QAction("Copy user comment", self.main_window)
        self.main_window.copy_user_comment_action.triggered.connect(
            self.main_window.copy_user_comment_to_clipboard
        )
        edit_menu.addAction(self.main_window.copy_user_comment_action)

        edit_menu.addSeparator()
        
        # Undo
        self.main_window.undo_action = QAction("Undo", self.main_window)
        self.main_window.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        self.main_window.undo_action.triggered.connect(self.main_window.undo_file_operation)
        edit_menu.addAction(self.main_window.undo_action)
        
        edit_menu.addSeparator()

        # Rename with Custom Prefix
        self.main_window.rename_with_custom_prefix_action = QAction("Rename with Custom Prefix...", self.main_window)
        self.main_window.rename_with_custom_prefix_action.setShortcut(QKeySequence("Ctrl+N"))
        self.main_window.rename_with_custom_prefix_action.triggered.connect(self.main_window.rename_with_custom_prefix)
        edit_menu.addAction(self.main_window.rename_with_custom_prefix_action)
        
        # Convert Selected
        self.main_window.convert_selected_action = QAction("Convert Image Format...", self.main_window)
        self.main_window.convert_selected_action.setShortcut(QKeySequence("Ctrl+M"))
        self.main_window.convert_selected_action.triggered.connect(self.main_window.convert_selected_images)
        edit_menu.addAction(self.main_window.convert_selected_action)

        self.main_window.resize_images_action = QAction("Resize...", self.main_window)
        self.main_window.resize_images_action.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        self.main_window.resize_images_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.resize_images_action.triggered.connect(self.main_window.resize_images)
        edit_menu.addAction(self.main_window.resize_images_action)
        
        edit_menu.addSeparator()
        
        # Edit in External Editor
        # Get editor name from config for menu text
        config = get_config()
        settings = config.load_settings()
        editor_app = settings.get('image_editor_app', 'Preview')
        menu_text = f"Edit with {editor_app}"
        
        self.main_window.edit_with_external_editor_action = QAction(menu_text, self.main_window)
        self.main_window.edit_with_external_editor_action.setShortcut(QKeySequence("Ctrl+E"))
        self.main_window.edit_with_external_editor_action.triggered.connect(
            lambda: edit_current_image_with_editor(self.main_window)
        )
        edit_menu.addAction(self.main_window.edit_with_external_editor_action)
        
        # Store reference for later cleanup
        self.edit_menu = edit_menu
        
        # Connect aboutToShow signal to update menu action states
        edit_menu.aboutToShow.connect(self.update_edit_menu_states)
        
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(lambda: self._clean_edit_menu_periodically())
        self.cleanup_timer.start(500)  # Check every 500ms
    
    def _clean_edit_menu_periodically(self):
        """Periodically clean the edit menu of system items"""
        if not hasattr(self, 'edit_menu') or not self.edit_menu:
            return
        
        # Check if the C++ object still exists
        try:
            # Try to access a property to check if object is still valid
            _ = self.edit_menu.title()
        except RuntimeError:
            # Menu has been deleted, clear the reference
            self.edit_menu = None
            return
            
        # List of macOS system menu items to remove
        system_items_to_remove = [
            "Writing Tools",
            "AutoFill", 
            "Start Dictation...",
            "Emoji & Symbols",
            "Substitutions",
            "Transformations",
            "Speech",
            "Look Up",
            "Search with Google",
            "Search with Bing"
        ]
        
        # Get all actions in the menu (snapshot to avoid iteration over modified container)
        try:
            actions = list(self.edit_menu.actions())
        except RuntimeError:
            # Menu was deleted during access, clear reference and return
            self.edit_menu = None
            return
        
        # Remove system items
        for action in actions:
            if action.text() in system_items_to_remove:
                self.edit_menu.removeAction(action)
    
    def _setup_view_menu(self, menubar):
        """Setup View menu"""
        view_menu = menubar.addMenu("View\u2060")
        
        # Separator: --------- UI Elements --------- 
        ui_elements_separator_action = QWidgetAction(self.main_window)
        ui_elements_separator_action.setDefaultWidget(TextSeparator("UI Elements"))
        view_menu.addAction(ui_elements_separator_action)

        # File Tree Toggle
        self.main_window.toggle_file_tree_action = QAction('Hide File Tree', self.main_window)
        self.main_window.toggle_file_tree_action.setCheckable(True)
        self.main_window.toggle_file_tree_action.setChecked(self.main_window.file_tree_visible)
        self.main_window.toggle_file_tree_action.setShortcut(QKeySequence('T'))
        self.main_window.toggle_file_tree_action.triggered.connect(self.main_window.toggle_file_tree)
        view_menu.addAction(self.main_window.toggle_file_tree_action)
        
        # Preview Toggle
        self.main_window.toggle_preview_action = QAction('Show Preview', self.main_window)
        self.main_window.toggle_preview_action.setCheckable(True)
        self.main_window.toggle_preview_action.setChecked(False)  # Preview starts hidden
        self.main_window.toggle_preview_action.setShortcut(QKeySequence('P'))
        self.main_window.toggle_preview_action.triggered.connect(self.main_window.toggle_preview)
        view_menu.addAction(self.main_window.toggle_preview_action)

        # Jobs pane toggle (right combined sidebar)
        try:
            from bundle_capabilities import model_jobs_ui_enabled

            _jobs_ui = model_jobs_ui_enabled()
        except ImportError:
            _jobs_ui = True
        if _jobs_ui:
            self.main_window.toggle_jobs_action = QAction('Show Jobs', self.main_window)
            self.main_window.toggle_jobs_action.setCheckable(True)
            self.main_window.toggle_jobs_action.setChecked(
                getattr(self.main_window, 'jobs_visible', False)
            )
            self.main_window.toggle_jobs_action.setShortcut(QKeySequence('J'))
            self.main_window.toggle_jobs_action.triggered.connect(self.main_window.toggle_jobs)
            view_menu.addAction(self.main_window.toggle_jobs_action)

        try:
            from bundle_capabilities import chat_ui_enabled

            _chat_ui = chat_ui_enabled()
        except ImportError:
            _chat_ui = True
        if _chat_ui:
            self.main_window.toggle_chat_action = QAction('Show Chat', self.main_window)
            self.main_window.toggle_chat_action.setCheckable(True)
            self.main_window.toggle_chat_action.setChecked(
                getattr(self.main_window, 'chat_visible', False)
            )
            self.main_window.toggle_chat_action.setShortcuts([QKeySequence('F9'), QKeySequence(',')])
       
            self.main_window.toggle_chat_action.triggered.connect(self.main_window.toggle_chat)
            view_menu.addAction(self.main_window.toggle_chat_action)
        
        # Toggle Information Sidebar (right sidebar with EXIF info)
        self.main_window.toggle_information_sidebar_action = QAction("Information Sidebar Toggle", self.main_window)
        self.main_window.toggle_information_sidebar_action.setShortcut(QKeySequence("I"))
        self.main_window.toggle_information_sidebar_action.setCheckable(True)
        info_checked = (getattr(self.main_window.right_sidebar, 'is_information_visible', lambda: False)()
                        if hasattr(self.main_window, 'right_sidebar') and self.main_window.right_sidebar
                        else getattr(self.main_window, 'right_sidebar_visible', False))
        self.main_window.toggle_information_sidebar_action.setChecked(info_checked)
        self.main_window.toggle_information_sidebar_action.triggered.connect(self.main_window.toggle_information_display)
        view_menu.addAction(self.main_window.toggle_information_sidebar_action)
        # Status Bar Toggle
        self.main_window.toggle_status_bar_action = QAction('Hide Status Bar', self.main_window)
        self.main_window.toggle_status_bar_action.setCheckable(True)
        self.main_window.toggle_status_bar_action.setChecked(self.main_window.status_bar_visible)
        self.main_window.toggle_status_bar_action.setShortcut(QKeySequence('B'))
        self.main_window.toggle_status_bar_action.triggered.connect(self.main_window.toggle_status_bar)
        view_menu.addAction(self.main_window.toggle_status_bar_action)

        # Toggle Chrome (F4 also handled by ChromeToggleShortcutFilter when child widgets have focus)
        self.main_window.toggle_chrome_action = QAction('Show Panes', self.main_window)
        self.main_window.toggle_chrome_action.setCheckable(True)
        chrome_visible = (
            self.main_window._is_any_chrome_visible()
            if hasattr(self.main_window, '_is_any_chrome_visible')
            else True
        )
        self.main_window.toggle_chrome_action.setChecked(chrome_visible)
        self.main_window.toggle_chrome_action.setText(
            'Hide Panes' if chrome_visible else 'Show Panes'
        )
        self.main_window.toggle_chrome_action.setShortcuts([QKeySequence('F4'), QKeySequence("."),QKeySequence('Ctrl+.')])
   
        self.main_window.toggle_chrome_action.triggered.connect(self.main_window.toggle_chrome)
        view_menu.addAction(self.main_window.toggle_chrome_action)
        
        # Update action text based on initial state
        if self.main_window.file_tree_visible:
            self.main_window.toggle_file_tree_action.setText('Hide File Tree')
        else:
            self.main_window.toggle_file_tree_action.setText('Show File Tree')
        
        # Update preview action text based on initial state
        if hasattr(self.main_window, 'combined_sidebar'):
            preview_visible = self.main_window.combined_sidebar.is_preview_visible()
            self.main_window.toggle_preview_action.setText('Hide Preview' if preview_visible else 'Show Preview')
            self.main_window.toggle_preview_action.setChecked(preview_visible)
            rs = getattr(self.main_window, 'right_sidebar', None)
            jobs_visible = rs.is_jobs_visible() if rs else getattr(self.main_window, 'jobs_visible', False)
            if hasattr(self.main_window, 'toggle_jobs_action'):
                self.main_window.toggle_jobs_action.setText('Hide Jobs' if jobs_visible else 'Show Jobs')
                self.main_window.toggle_jobs_action.setChecked(jobs_visible)
            cs = self.main_window.combined_sidebar
            chat_visible = (
                cs.is_chat_visible()
                if hasattr(cs, 'is_chat_visible')
                else getattr(self.main_window, 'chat_visible', False)
            )
            if hasattr(self.main_window, 'toggle_chat_action'):
                self.main_window.toggle_chat_action.setText('Hide Chat' if chat_visible else 'Show Chat')
                self.main_window.toggle_chat_action.setChecked(chat_visible)
        
        
        # Toggle List View (shortcut F12)
        self.main_window.list_view_action = QAction("List View Toggle", self.main_window)
        self.main_window.list_view_action.setShortcut(QKeySequence("F12"))
        self.main_window.list_view_action.setCheckable(True)
        self.main_window.list_view_action.triggered.connect(self.main_window.toggle_list_view)
        # Set initial checked state and text based on current view mode
        is_list_view = getattr(self.main_window, 'current_view_mode', None) == 'list'
        self.main_window.list_view_action.setChecked(is_list_view)
        self.main_window.list_view_action.setText("Hide List View" if is_list_view else "Show List View")
        view_menu.addAction(self.main_window.list_view_action)


        # Toggle Shortcuts Sidebar (Favorites and Move lists within right_sidebar)
        self.main_window.toggle_shortcuts_sidebar_action = QAction("Organize Sidebar Toggle", self.main_window)
        self.main_window.toggle_shortcuts_sidebar_action.setShortcuts([QKeySequence("O")])
        self.main_window.toggle_shortcuts_sidebar_action.setCheckable(True)
        shortcuts_checked = (self.main_window.right_sidebar.is_shortcuts_visible()
                             if hasattr(self.main_window, 'right_sidebar') and self.main_window.right_sidebar
                             else False)
        self.main_window.toggle_shortcuts_sidebar_action.setChecked(shortcuts_checked)
        self.main_window.toggle_shortcuts_sidebar_action.triggered.connect(self.main_window.toggle_shortcuts_display)
        view_menu.addAction(self.main_window.toggle_shortcuts_sidebar_action)

        # Theme submenu (Light / Dark / User / system)
        theme_menu = view_menu.addMenu("Theme")
        theme_group = QActionGroup(self.main_window)
        theme_group.setExclusive(True)
        self.main_window.theme_light_action = QAction("Light", self.main_window)
        self.main_window.theme_light_action.setCheckable(True)
        self.main_window.theme_dark_action = QAction("Dark", self.main_window)
        self.main_window.theme_dark_action.setCheckable(True)
        self.main_window.theme_user_action = QAction("User", self.main_window)
        self.main_window.theme_user_action.setCheckable(True)
        self.main_window.theme_system_action = QAction("Use System Setting", self.main_window)
        self.main_window.theme_system_action.setCheckable(True)
        theme_group.addAction(self.main_window.theme_light_action)
        theme_group.addAction(self.main_window.theme_dark_action)
        theme_group.addAction(self.main_window.theme_user_action)
        theme_group.addAction(self.main_window.theme_system_action)
        theme_menu.addAction(self.main_window.theme_light_action)
        theme_menu.addAction(self.main_window.theme_dark_action)
        theme_menu.addAction(self.main_window.theme_user_action)
        theme_menu.addSeparator()
        theme_menu.addAction(self.main_window.theme_system_action)
        _ui_theme = self.main_window.config.load_settings().get("ui_theme", "dark")
        from theme.theme_service import apply_theme, connect_system_theme_listener, set_theme_main_window, sync_view_theme_menu_actions

        connect_system_theme_listener()
        set_theme_main_window(self.main_window)
        sync_view_theme_menu_actions(self.main_window, _ui_theme)

        def _apply_ui_theme(theme_id: str):
            apply_theme(
                theme_id,
                app=QApplication.instance(),
                main_window=self.main_window,
                persist=True,
                config=self.main_window.config,
            )
            sync_view_theme_menu_actions(self.main_window, theme_id)

        self.main_window.theme_dark_action.triggered.connect(lambda: _apply_ui_theme("dark"))
        self.main_window.theme_light_action.triggered.connect(lambda: _apply_ui_theme("light"))
        self.main_window.theme_user_action.triggered.connect(lambda: _apply_ui_theme("user"))
        self.main_window.theme_system_action.triggered.connect(lambda: _apply_ui_theme("system"))

        # view_menu.addSeparator()
        # Separator: --------- Thumbnail Control --------- 
        thumbnail_control_separator_action = QWidgetAction(self.main_window)
        thumbnail_control_separator_action.setDefaultWidget(TextSeparator("Thumbnail Control"))
        view_menu.addAction(thumbnail_control_separator_action)
        # Store reference for dynamic text updates
        self.main_window.thumbnail_control_separator_action = thumbnail_control_separator_action
        
        # Browse View
        # Text will be updated dynamically based on view mode in update_view_menu_enabled_states
        self.main_window.browse_view_action = QAction("Enter Image Viewer", self.main_window)
        self.main_window.browse_view_action.setShortcut(QKeySequence("F"))
        self.main_window.browse_view_action.setMenuRole(QAction.MenuRole.NoRole)
        self.main_window.browse_view_action.triggered.connect(lambda: self.main_window.view_mode_manager.toggle_viewer())
        view_menu.addAction(self.main_window.browse_view_action)
        
        # Toggle Filename
        self.main_window.toggle_filename_action = QAction("Information Overlay Toggle", self.main_window)
        self.main_window.toggle_filename_action.setShortcut(QKeySequence("Ctrl+I"))
        self.main_window.toggle_filename_action.setCheckable(True)
        self.main_window.toggle_filename_action.triggered.connect(self.main_window.toggle_thumbnail_filename_overlay)
        view_menu.addAction(self.main_window.toggle_filename_action)
        
        # Sort Actions
        self._setup_sort_actions(view_menu)

        
        # Actual Size (only available in browse mode)
        self.main_window.actual_size_action = QAction("Actual Size", self.main_window)
        self.main_window.actual_size_action.setShortcut(QKeySequence("A"))
        self.main_window.actual_size_action.setCheckable(True)
        self.main_window.actual_size_action.triggered.connect(self.main_window.toggle_actual_size)
        view_menu.addAction(self.main_window.actual_size_action)
        
        
        
        # Update action text based on initial state
        if self.main_window.status_bar_visible:
            self.main_window.toggle_status_bar_action.setText('Hide Status Bar')
        else:
            self.main_window.toggle_status_bar_action.setText('Show Status Bar')
        
        # Separator: --------- macOS display mode --------- 
        macos_display_mode_separator_action = QWidgetAction(self.main_window)
        macos_display_mode_separator_action.setDefaultWidget(
            TextSeparator("macOS Display Mode")
        )
        view_menu.addAction(macos_display_mode_separator_action)

        # macOS Space vs windowed mode — single toggle entry (macOS only)
        if (
            hasattr(self.main_window, 'MACOS_SPACE_MODE_AVAILABLE')
            and self.main_window.MACOS_SPACE_MODE_AVAILABLE
        ):
            in_macos_space = is_macos_space_mode()
            if not in_macos_space and self.main_window.isFullScreen():
                in_macos_space = True
            self.main_window.macos_display_mode_action = QAction(
                "Show in Windowed mode" if in_macos_space else "Show in MacOS Space",
                self.main_window,
            )
            self.main_window.macos_display_mode_action.setShortcut(
                QKeySequence("Ctrl+Meta+F")
            )
            self.main_window.macos_display_mode_action.triggered.connect(
                self.main_window.toggle_macos_display_mode
            )
            view_menu.addAction(self.main_window.macos_display_mode_action)
        
        view_menu.addSeparator()
        
        view_menu.aboutToShow.connect(self.update_view_menu_enabled_states)
    
    def _setup_move_menu(self, menubar):
        """Setup Move/Copy-to destination menu (title follows destination_menu_action)."""
        settings = self.main_window.config.load_settings()
        dest_action = settings.get('destination_menu_action', 'move')
        menu_title = "Copy to" if dest_action == 'copy' else "Move to"
        self.move_menu = menubar.addMenu(menu_title)

        # Separator: --------- User Defined Destinations --------- 
        self.destination_separator_action = QWidgetAction(self.main_window)
        self.destination_separator_action.setDefaultWidget(TextSeparator("User Defined Destinations"))
        self.move_menu.addAction(self.destination_separator_action)

        # Move to Destination 1-9 (cmd-1 through cmd-9)
        self.main_window.move_to_destination_actions = []
        for i in range(1, 10):
            action = QAction(f"Move to Destination {i}", self.main_window)
            action.setShortcut(QKeySequence(f"Ctrl+{i}"))
            # Use a lambda that captures i correctly
            action.triggered.connect(lambda checked, idx=i: self.main_window.move_to_destination(idx))
            action.setVisible(False)  # Initially hidden, will be shown when valid destinations are configured
            self.move_menu.addAction(action)
            self.main_window.move_to_destination_actions.append(action)
        
        # Separator: --------- Dynamic Destination --------- 
        self.dynamic_move_separator_action = QWidgetAction(self.main_window)
        self.dynamic_move_separator_action.setDefaultWidget(TextSeparator("Dynamic Destination"))
        self.move_menu.addAction(self.dynamic_move_separator_action)

        # Move to Last Drop Location (cmd-0)
        self.main_window.move_to_last_drop_action = QAction("Move to Last Drop Location", self.main_window)
        self.main_window.move_to_last_drop_action.setShortcut(QKeySequence("Ctrl+0"))
        self.main_window.move_to_last_drop_action.triggered.connect(self.main_window.move_to_last_drop_location)
        self.move_menu.addAction(self.main_window.move_to_last_drop_action)

        # Copy to Destination 1-9 (Option+Cmd+1 through Option+Cmd+9) — not in menu, shortcuts only
        self.main_window.copy_to_destination_actions = []
        for i in range(1, 10):
            action = QAction(self.main_window)
            action.setShortcut(QKeySequence(f"Alt+Ctrl+{i}"))
            action.triggered.connect(
                lambda checked, idx=i: self.main_window.move_to_destination(idx, copy_only=True)
            )
            self.main_window.addAction(action)
            self.main_window.copy_to_destination_actions.append(action)

        # Copy to Last Drop Location (Option+Cmd+0)
        self.main_window.copy_to_last_drop_action = QAction(self.main_window)
        self.main_window.copy_to_last_drop_action.setShortcut(QKeySequence("Alt+Ctrl+0"))
        self.main_window.copy_to_last_drop_action.triggered.connect(
            lambda: self.main_window.move_to_last_drop_location(copy_only=True)
        )
        self.main_window.addAction(self.main_window.copy_to_last_drop_action)
        
        # Separator: --------- Move Work Files --------- 
        self.move_work_files_separator_action = QWidgetAction(self.main_window)
        self.move_work_files_separator_action.setDefaultWidget(TextSeparator("Move Work Files"))
        self.move_menu.addAction(self.move_work_files_separator_action)
        
        # Move work files
        self.main_window.move_work_files_action = QAction("Move Work Files...", self.main_window)
        self.main_window.move_work_files_action.triggered.connect(self.main_window.move_work_files)
        self.move_menu.addAction(self.main_window.move_work_files_action)
        
        # Separator: --------- Dynamic Destination --------- 
        self.settings_separator_action = QWidgetAction(self.main_window)
        self.settings_separator_action.setDefaultWidget(TextSeparator("Settings"))
        self.move_menu.addAction(self.settings_separator_action)

        # Edit destinations (opens settings to Move Keys tab)
        edit_destinations_action = QAction("Edit Destinations...", self.main_window)
        edit_destinations_action.setIcon(create_gear_icon("#808890"))
        edit_destinations_action.triggered.connect(
            lambda: self.main_window.show_settings(tab_id="move_destinations")
        )
        self.move_menu.addAction(edit_destinations_action)
        
        # Connect aboutToShow signal to update menu action states
        self.move_menu.aboutToShow.connect(self.update_edit_menu_states)
    
    def _setup_search_menu(self, menubar):
        """Setup Search menu"""
        search_menu = menubar.addMenu("Search")
        
        # Separator: --------- Image Content --------- 
        image_content_separator_action = QWidgetAction(self.main_window)
        image_content_separator_action.setDefaultWidget(TextSeparator("Image Content"))
        search_menu.addAction(image_content_separator_action)
        
        # Find Similar Images
        self.main_window.reorder_by_similarity_action = QAction("Search for Similar Images...", self.main_window)
        self.main_window.reorder_by_similarity_action.setShortcut(QKeySequence("Ctrl+K"))
        # Ensure shortcut works even when child widgets have focus
        # WindowShortcut is default, but explicitly set it to be sure
        self.main_window.reorder_by_similarity_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        def _reorder_by_similarity_with_focus():
            # Check if tree had focus BEFORE moving focus (for context-aware dialog priming)
            tree_had_focus = self.main_window._tree_has_focus() if hasattr(self.main_window, '_tree_has_focus') else False
            self.main_window._tree_had_focus_when_invoked = tree_had_focus
            
            # Set focus to thumbnail view before executing (if in thumbnail view)
            if (hasattr(self.main_window, 'current_view_mode') and 
                self.main_window.current_view_mode == 'thumbnail' and
                hasattr(self.main_window, 'main_content_widget') and 
                self.main_window.main_content_widget):
                self.main_window.main_content_widget.setFocus()
            self.main_window.reorder_images_by_similarity()
            # After search, ensure focus is set if we're now in thumbnail mode
            if (hasattr(self.main_window, 'current_view_mode') and 
                self.main_window.current_view_mode == 'thumbnail' and
                hasattr(self.main_window, 'main_content_widget') and 
                self.main_window.main_content_widget):
                self.main_window.main_content_widget.setFocus()
            # Clear the flag after use
            self.main_window._tree_had_focus_when_invoked = False
        self.main_window.reorder_by_similarity_action.triggered.connect(_reorder_by_similarity_with_focus)
        search_menu.addAction(self.main_window.reorder_by_similarity_action)
        
        # Search by Description
        self.main_window.clip_search_action = QAction("Search by Text...", self.main_window)
        # Add alternate shortcut Ctrl+Shift+K to also trigger CLIP search
        self.main_window.clip_search_action.setShortcuts([
            QKeySequence("Ctrl+F"),
            QKeySequence("Ctrl+Shift+K")
        ])
        def _reorder_by_clip_search_with_focus():
            # Check if tree had focus BEFORE moving focus (for context-aware dialog priming)
            tree_had_focus = self.main_window._tree_has_focus() if hasattr(self.main_window, '_tree_has_focus') else False
            self.main_window._tree_had_focus_when_invoked = tree_had_focus
            
            # Set focus to thumbnail view before executing (if in thumbnail view)
            if (hasattr(self.main_window, 'current_view_mode') and 
                self.main_window.current_view_mode == 'thumbnail' and
                hasattr(self.main_window, 'main_content_widget') and 
                self.main_window.main_content_widget):
                self.main_window.main_content_widget.setFocus()
            self.main_window.reorder_images_by_clip_search()
            # After search, ensure focus is set if we're now in thumbnail mode
            if (hasattr(self.main_window, 'current_view_mode') and 
                self.main_window.current_view_mode == 'thumbnail' and
                hasattr(self.main_window, 'main_content_widget') and 
                self.main_window.main_content_widget):
                self.main_window.main_content_widget.setFocus()
            # Clear the flag after use
            self.main_window._tree_had_focus_when_invoked = False
        self.main_window.clip_search_action.triggered.connect(_reorder_by_clip_search_with_focus)
        search_menu.addAction(self.main_window.clip_search_action)

        # Search by person: single action that opens a dialog (avoids native submenu issues on macOS)
        try:
            from bundle_capabilities import faces_ui_enabled

            _faces_ui = faces_ui_enabled()
        except ImportError:
            _faces_ui = True
        if _faces_ui:
            self.main_window.search_by_person_action = QAction("Search by Person...", self.main_window)
            self.main_window.search_by_person_action.setShortcut(QKeySequence("Ctrl+P"))
            def _show_filter_by_person_with_focus():
                tree_had_focus = self.main_window._tree_has_focus() if hasattr(self.main_window, '_tree_has_focus') else False
                self.main_window._tree_had_focus_when_invoked = tree_had_focus
                try:
                    self.main_window.show_filter_by_person_dialog()
                finally:
                    self.main_window._tree_had_focus_when_invoked = False
            self.main_window.search_by_person_action.triggered.connect(_show_filter_by_person_with_focus)
            search_menu.addAction(self.main_window.search_by_person_action)

            self.main_window.quick_person_search_action = QAction("Quick Person Search", self.main_window)
            self.main_window.quick_person_search_action.setShortcut(QKeySequence("Meta+Ctrl+P"))
            self.main_window.quick_person_search_action.triggered.connect(
                lambda: run_quick_person_search(self.main_window)
            )
            search_menu.addAction(self.main_window.quick_person_search_action)
       
        # search_menu.addSeparator()
       
        # Separator: --------- Physical File --------- 
        physical_file_separator_action = QWidgetAction(self.main_window)
        physical_file_separator_action.setDefaultWidget(TextSeparator("Physical File"))
        search_menu.addAction(physical_file_separator_action)
       
        # Find Exact Duplicates submenu
        find_duplicates_menu = search_menu.addMenu("Find Duplicate Image Files")
        
        # Find in this directory
        find_in_directory_action = QAction("Find in This Directory", self.main_window)
        find_in_directory_action.triggered.connect(self.main_window.find_exact_duplicates)
        find_duplicates_menu.addAction(find_in_directory_action)
        self.main_window.find_duplicates_action = find_in_directory_action
        
        # Find in this and subdirectories
        find_recursive_action = QAction("Find in This and Subdirectories", self.main_window)
        find_recursive_action.setShortcut(QKeySequence("Shift+F"))
        find_recursive_action.triggered.connect(self.main_window.find_exact_duplicates_recursive)
        find_duplicates_menu.addAction(find_recursive_action)
        self.main_window.find_duplicates_recursive_action = find_recursive_action

        find_similar_menu = search_menu.addMenu("Find Similar Image Files")
        find_similar_in_dir_action = QAction("Find in This Directory", self.main_window)
        find_similar_in_dir_action.triggered.connect(self.main_window.find_similar_image_files)
        find_similar_menu.addAction(find_similar_in_dir_action)
        self.main_window.find_similar_image_files_action = find_similar_in_dir_action

        find_similar_recursive_action = QAction("Find in This and Subdirectories", self.main_window)
        find_similar_recursive_action.triggered.connect(self.main_window.find_similar_image_files_recursive)
        find_similar_menu.addAction(find_similar_recursive_action)
        self.main_window.find_similar_image_files_recursive_action = find_similar_recursive_action

        self.main_window.debug_extract_faces_action = QAction("Extract Faces", self.main_window)
        self.main_window.debug_extract_faces_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.main_window.debug_extract_faces_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.debug_extract_faces_action.triggered.connect(self._debug_extract_faces)
        search_menu.addAction(self.main_window.debug_extract_faces_action)
        
        search_menu.addSeparator()
        
        # Show image in directory
        self.main_window.show_image_in_directory_action = QAction("Show Image in Directory", self.main_window)
        self.main_window.show_image_in_directory_action.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.main_window.show_image_in_directory_action.triggered.connect(self.main_window.show_image_in_directory)
        search_menu.addAction(self.main_window.show_image_in_directory_action)
        
        # Connect aboutToShow signal to update menu action states
        search_menu.aboutToShow.connect(self.update_search_menu_states)
        self.search_menu = search_menu
    
    def _setup_tools_menu(self, menubar):
        """Setup Tools menu"""
        tools_menu = menubar.addMenu("Tools")
        
        # Separator: --------- Organization --------- 
        self.organization_separator_action = QWidgetAction(self.main_window)
        self.organization_separator_action.setDefaultWidget(TextSeparator("Organization"))
        tools_menu.addAction(self.organization_separator_action)
        
        # Quick Mass Rename
        self.main_window.quick_mass_rename_action = QAction("Quick Mass Rename...", self.main_window)
        self.main_window.quick_mass_rename_action.triggered.connect(self.main_window.quick_mass_rename)
        self.main_window.quick_mass_rename_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self.main_window.quick_mass_rename_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        tools_menu.addAction(self.main_window.quick_mass_rename_action)
        
        # Backup Custom Sort
        self.main_window.backup_custom_sort_action = QAction("Backup Custom Sort", self.main_window)
        self.main_window.backup_custom_sort_action.triggered.connect(self._backup_custom_sort)
        tools_menu.addAction(self.main_window.backup_custom_sort_action)
        
        # Restore Custom Sort
        self.main_window.restore_custom_sort_action = QAction("Restore Custom Sort", self.main_window)
        self.main_window.restore_custom_sort_action.triggered.connect(self._restore_custom_sort)
        tools_menu.addAction(self.main_window.restore_custom_sort_action)
        
        # Lock selected files (cmd-L) - only shown when allow_thumbnail_locking is enabled
        self.main_window.lock_files_action = QAction("Lock Selected File", self.main_window)
        self.main_window.lock_files_action.setShortcut(QKeySequence("Ctrl+L"))
        self.main_window.lock_files_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.lock_files_action.triggered.connect(self.main_window.lock_selected_files)
        tools_menu.addAction(self.main_window.lock_files_action)
        
        # Unlock selected files (shift-cmd-L) - only shown when allow_thumbnail_locking is enabled
        # Note: shift-cmd-L shortcut is handled by keyboard_handler.py and always works, even when menu item is hidden
        self.main_window.unlock_files_action = QAction("Unlock Selected File", self.main_window)
        # Set shortcut for display purposes in menu (keyboard handler also handles it)
        self.main_window.unlock_files_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.main_window.unlock_files_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.unlock_files_action.triggered.connect(self.main_window.unlock_selected_files)
        tools_menu.addAction(self.main_window.unlock_files_action)
        
        # EXIF and Dates submenu (timestamp tools + user comment)
        exif_dates_menu = QMenu("EXIF and Dates", self.main_window)
        tools_menu.addMenu(exif_dates_menu)
        
        # Reset Date to EXIF
        self.main_window.reset_date_to_exif_action = QAction("Reset File Date to Match EXIF Timestamp...", self.main_window)
        self.main_window.reset_date_to_exif_action.triggered.connect(self.main_window.reset_date_to_exif)
        exif_dates_menu.addAction(self.main_window.reset_date_to_exif_action)
        
        # Reset EXIF to File Date
        self.main_window.reset_exif_to_file_date_action = QAction("Reset EXIF Timestamp to Match File Date...", self.main_window)
        self.main_window.reset_exif_to_file_date_action.triggered.connect(self.main_window.reset_exif_to_file_date)
        exif_dates_menu.addAction(self.main_window.reset_exif_to_file_date_action)
        
        # Delete EXIF Date
        self.main_window.delete_exif_date_action = QAction("Delete EXIF Date from File...", self.main_window)
        self.main_window.delete_exif_date_action.triggered.connect(self.main_window.delete_exif_date)
        exif_dates_menu.addAction(self.main_window.delete_exif_date_action)

        exif_dates_menu.addSeparator()

        # Edit EXIF User Comment (Cmd+Shift+E)
        self.main_window.edit_exif_usercomment_action = QAction("Edit EXIF User Comment...", self.main_window)
        self.main_window.edit_exif_usercomment_action.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.main_window.edit_exif_usercomment_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.edit_exif_usercomment_action.triggered.connect(self.main_window.edit_exif_usercomment)
        exif_dates_menu.addAction(self.main_window.edit_exif_usercomment_action)

        # tools_menu.addSeparator()

        # Separator: --------- Miscellaneous --------- 
        miscellaneous_separator_action = QWidgetAction(self.main_window)
        miscellaneous_separator_action.setDefaultWidget(TextSeparator("Miscellaneous"))
        tools_menu.addAction(miscellaneous_separator_action)

        # Map Location (cmd-G)
        self.main_window.map_location_action = QAction("Show GPS Location on Map", self.main_window)
        self.main_window.map_location_action.setShortcut(QKeySequence("Ctrl+G"))
        self.main_window.map_location_action.triggered.connect(self.main_window.open_map_for_current_image)
        tools_menu.addAction(self.main_window.map_location_action)

        # Create Slideshows submenu
        slideshows_menu = QMenu("Slideshows", self.main_window)
        tools_menu.addMenu(slideshows_menu)

        # Slideshow - Multiple Images
        slideshow_action = QAction("Multiple Images Slideshow", self.main_window)
        slideshow_action.setShortcut(QKeySequence("S"))
        slideshow_action.triggered.connect(lambda: self.main_window.view_mode_manager.toggle_slideshow())
        slideshows_menu.addAction(slideshow_action)
        
        # Slideshow2 - Panning
        slideshow2_action = QAction("Panning Slideshow", self.main_window)
        slideshow2_action.setShortcut(QKeySequence("Shift+S"))
        slideshow2_action.triggered.connect(self.main_window.slideshow2_manager.toggle_slideshow2)
        slideshows_menu.addAction(slideshow2_action)
        
        # Slideshow3 - Floating Frames
        slideshow3_action = QAction("Floating Frames Slideshow", self.main_window)
        slideshow3_action.setShortcut(QKeySequence("Shift+Ctrl+S"))
        slideshow3_action.triggered.connect(self.main_window.slideshow3_manager.toggle_slideshow3)
        slideshows_menu.addAction(slideshow3_action)

        # Wallpaper submenu
        wallpaper_menu = QMenu("Wallpaper", self.main_window)
        self.main_window.wallpaper_menu_action = tools_menu.addMenu(wallpaper_menu)
        
        # Set Wallpaper (last used) - with Shift+Cmd+W hotkey
        self.main_window.wallpaper_last_used_action = QAction("Set Wallpaper (Last Used)", self.main_window)
        self.main_window.wallpaper_last_used_action.setShortcut(QKeySequence("Ctrl+Shift+W"))
        self.main_window.wallpaper_last_used_action.triggered.connect(
            lambda: self.main_window.set_current_image_as_desktop_background()
        )
        wallpaper_menu.addAction(self.main_window.wallpaper_last_used_action)
        
        
        # Fit (Contain) - fits within bounds, no overflow
        self.main_window.wallpaper_contain_action = QAction("Fit (Contain)", self.main_window)
        self.main_window.wallpaper_contain_action.setCheckable(True)
        self.main_window.wallpaper_contain_action.triggered.connect(
            lambda: self.main_window.set_current_image_as_desktop_background('contain')
        )
        wallpaper_menu.addAction(self.main_window.wallpaper_contain_action)
        
        # Fill (Cover) - fills screen, may overflow
        self.main_window.wallpaper_cover_action = QAction("Fill (Cover)", self.main_window)
        self.main_window.wallpaper_cover_action.setCheckable(True)
        self.main_window.wallpaper_cover_action.triggered.connect(
            lambda: self.main_window.set_current_image_as_desktop_background('cover')
        )
        wallpaper_menu.addAction(self.main_window.wallpaper_cover_action)
        
        # Fit to Width - matches screen width exactly
        self.main_window.wallpaper_width_action = QAction("Fit to Width", self.main_window)
        self.main_window.wallpaper_width_action.setCheckable(True)
        self.main_window.wallpaper_width_action.triggered.connect(
            lambda: self.main_window.set_current_image_as_desktop_background('width')
        )
        wallpaper_menu.addAction(self.main_window.wallpaper_width_action)
        
        # Fit to Height - matches screen height exactly
        self.main_window.wallpaper_height_action = QAction("Fit to Height", self.main_window)
        self.main_window.wallpaper_height_action.setCheckable(True)
        self.main_window.wallpaper_height_action.triggered.connect(
            lambda: self.main_window.set_current_image_as_desktop_background('height')
        )
        wallpaper_menu.addAction(self.main_window.wallpaper_height_action)
        
        wallpaper_menu.addSeparator()
        
        # When checked, Fit/Cover/Width/Height use visible browse pixels (zoom/pan); when off, original file + dimensions
        self.main_window.wallpaper_current_display_action = QAction("Use Current Zoomed Display", self.main_window)
        self.main_window.wallpaper_current_display_action.setCheckable(True)
        self.main_window.wallpaper_current_display_action.toggled.connect(
            self.main_window.on_wallpaper_use_zoomed_display_toggled
        )
        wallpaper_menu.addAction(self.main_window.wallpaper_current_display_action)
        
        self.main_window.wallpaper_resize_window_action = QAction("Resize Window", self.main_window)
        self.main_window.wallpaper_resize_window_action.setShortcut(QKeySequence("Shift+W"))
        self.main_window.wallpaper_resize_window_action.triggered.connect(
            self.main_window.resize_window_to_screen_aspect_ratio
        )
        wallpaper_menu.addAction(self.main_window.wallpaper_resize_window_action)
        
        wallpaper_menu.addSeparator()
        # Store reference to wallpaper menu for state updates
        self.main_window.wallpaper_menu = wallpaper_menu
        
        # Create Screen Size Copy submenu
        screen_copy_menu = QMenu("Create Screen Size Copy...", self.main_window)
        self.main_window.screen_copy_menu_action = tools_menu.addMenu(screen_copy_menu)

        # Create screen size copy (last used) - with Shift+Cmd+U hotkey
        self.main_window.screen_copy_last_used_action = QAction("Create Screen Size Copy (Last Used)", self.main_window)
        self.main_window.screen_copy_last_used_action.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.main_window.screen_copy_last_used_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.screen_copy_last_used_action.triggered.connect(
            lambda: self.main_window.create_screen_size_copy()
        )
        screen_copy_menu.addAction(self.main_window.screen_copy_last_used_action)

        screen_copy_menu.addSeparator()

        # Fit (Contain) - fits within bounds, no overflow
        self.main_window.create_screen_copy_contain_action = QAction("Fit (Contain)", self.main_window)
        self.main_window.create_screen_copy_contain_action.setCheckable(True)
        self.main_window.create_screen_copy_contain_action.triggered.connect(
            lambda: self.main_window.create_screen_size_copy('contain')
        )
        screen_copy_menu.addAction(self.main_window.create_screen_copy_contain_action)
        
        # Fill (Cover) - fills screen, may overflow
        self.main_window.create_screen_copy_cover_action = QAction("Fill (Cover)", self.main_window)
        self.main_window.create_screen_copy_cover_action.setCheckable(True)
        self.main_window.create_screen_copy_cover_action.triggered.connect(
            lambda: self.main_window.create_screen_size_copy('cover')
        )
        screen_copy_menu.addAction(self.main_window.create_screen_copy_cover_action)
        
        # Fit to Width - matches screen width exactly
        self.main_window.create_screen_copy_width_action = QAction("Fit to Width", self.main_window)
        self.main_window.create_screen_copy_width_action.setCheckable(True)
        self.main_window.create_screen_copy_width_action.triggered.connect(
            lambda: self.main_window.create_screen_size_copy('width')
        )
        screen_copy_menu.addAction(self.main_window.create_screen_copy_width_action)
        
        # Fit to Height - matches screen height exactly
        self.main_window.create_screen_copy_height_action = QAction("Fit to Height", self.main_window)
        self.main_window.create_screen_copy_height_action.setCheckable(True)
        self.main_window.create_screen_copy_height_action.triggered.connect(
            lambda: self.main_window.create_screen_size_copy('height')
        )
        screen_copy_menu.addAction(self.main_window.create_screen_copy_height_action)
        
        # Store reference to submenu for state updates
        self.main_window.screen_copy_menu = screen_copy_menu
        
        # Separator: --------- Convenience --------- 
        testing_separator_action = QWidgetAction(self.main_window)
        testing_separator_action.setDefaultWidget(TextSeparator("Convenience"))
        tools_menu.addAction(testing_separator_action)

        self.main_window.open_home_directory_action = QAction("Open Home Directory", self.main_window)
        # Was Shift+H; that chord is reserved in thumbnail/list for "select range to first" (same as Shift+Home).
        self.main_window.open_home_directory_action.setShortcut(QKeySequence("Ctrl+Alt+H"))
        self.main_window.open_home_directory_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.open_home_directory_action.triggered.connect(self.main_window.open_home_directory)
        tools_menu.addAction(self.main_window.open_home_directory_action)

        try:
            from bundle_capabilities import lmstudio_ui_enabled

            _lmstudio_ui = lmstudio_ui_enabled()
        except ImportError:
            _lmstudio_ui = True
        if _lmstudio_ui:
            self.main_window.open_lmstudio_action = QAction("Open LM Studio", self.main_window)
            self.main_window.open_lmstudio_action.triggered.connect(self._open_lmstudio)
            tools_menu.addAction(self.main_window.open_lmstudio_action)

        # Cache Subdirectories' Thumbnails
        self.main_window.prepopulate_cache_action = QAction("Cache Subdirectories' Thumbnails", self.main_window)
        self.main_window.prepopulate_cache_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.main_window.prepopulate_cache_action.triggered.connect(self._prepopulate_cache)
        tools_menu.addAction(self.main_window.prepopulate_cache_action)

        # Cache Faces (Cmd+=)
        try:
            from bundle_capabilities import faces_ui_enabled

            _tools_faces_ui = faces_ui_enabled()
        except ImportError:
            _tools_faces_ui = True
        if _tools_faces_ui:
            self.main_window.cache_faces_action = QAction("Cache Subdirectories' Faces", self.main_window)
            self.main_window.cache_faces_action.setShortcut(QKeySequence("Ctrl+="))
            self.main_window.cache_faces_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            def _cache_faces_with_focus():
                tree_had_focus = self.main_window._tree_has_focus() if hasattr(self.main_window, '_tree_has_focus') else False
                self.main_window._tree_had_focus_when_invoked = tree_had_focus
                try:
                    self.main_window.cache_faces()
                finally:
                    self.main_window._tree_had_focus_when_invoked = False
            self.main_window.cache_faces_action.triggered.connect(_cache_faces_with_focus)
            tools_menu.addAction(self.main_window.cache_faces_action)

        # Save Custom Sort Order
        # Developer note: This action is disabled for now but should remain in the codebase.
        self.main_window.save_custom_action = QAction("Save Custom Sort Order", self.main_window)
        self.main_window.save_custom_action.setShortcut(QKeySequence("Ctrl+S"))
        self.main_window.save_custom_action.triggered.connect(lambda: self.main_window.sorting_manager.save_custom_sort(show_message=True))
        # tools_menu.addAction(self.main_window.save_custom_action)
        
        # Exclude Thumbs from View
        self.main_window.exclude_files_action = QAction("Exclude Thumbs from View", self.main_window)
        self.main_window.exclude_files_action.setShortcut(QKeySequence("Ctrl+X"))
        self.main_window.exclude_files_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.main_window.exclude_files_action.triggered.connect(self.main_window.exclude_files_from_view)
        tools_menu.addAction(self.main_window.exclude_files_action)

        # Show Rename Status in Tree    
        self.main_window.show_rename_status_action = QAction("Show Naming Consistency in Tree", self.main_window)
        self.main_window.show_rename_status_action.setCheckable(True)
        self.main_window.show_rename_status_action.setChecked(False)
        self.main_window.show_rename_status_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.main_window.show_rename_status_action.triggered.connect(self.main_window.toggle_rename_status)
        tools_menu.addAction(self.main_window.show_rename_status_action)

        # Debug submenu
        debug_menu = QMenu("Debug", self.main_window)
        tools_menu.addMenu(debug_menu)
        random_images_action = QAction("Random Images", self.main_window)
        random_images_action.triggered.connect(self._debug_random_images)
        debug_menu.addAction(random_images_action)

        view_log_action = QAction("View log", self.main_window)
        view_log_action.setShortcut(QKeySequence("Meta+L"))
        view_log_action.triggered.connect(self._debug_view_print_log)
        debug_menu.addAction(view_log_action)

        debug_menu.addSeparator()

        self.main_window.normalize_exif_steps_action = QAction(
            "Normalize EXIF Steps in Image Model...", self.main_window
        )
        self.main_window.normalize_exif_steps_action.triggered.connect(
            self.main_window.normalize_exif_steps_suffix
        )
        debug_menu.addAction(self.main_window.normalize_exif_steps_action)

        try:
            from bundle_capabilities import imagegen_ui_enabled

            _imagegen_ui = imagegen_ui_enabled()
        except ImportError:
            _imagegen_ui = True
        if _imagegen_ui:
            list_models_action = QAction("List Models", self.main_window)
            list_models_action.triggered.connect(self._debug_list_models)
            debug_menu.addAction(list_models_action)

            check_loras_action = QAction("Check LoRAs", self.main_window)
            check_loras_action.triggered.connect(self._debug_check_loras)
            debug_menu.addAction(check_loras_action)

            reset_gen_settings_action = QAction("Reset All Gen Settings", self.main_window)
            reset_gen_settings_action.triggered.connect(self._debug_reset_all_gen_settings)
            debug_menu.addAction(reset_gen_settings_action)

            see_timings_action = QAction("See timings", self.main_window)
            see_timings_action.triggered.connect(self._debug_see_generation_timings)
            debug_menu.addAction(see_timings_action)

        self.main_window.debug_save_canvas_action = QAction("Save Canvas", self.main_window)
        self.main_window.debug_save_canvas_action.triggered.connect(self._debug_save_canvas)
        debug_menu.addAction(self.main_window.debug_save_canvas_action)
        
        # Connect aboutToShow signal to update menu action states
        tools_menu.aboutToShow.connect(self.update_tools_menu_states)
        self.tools_menu = tools_menu
    
    def _prepopulate_cache(self):
        """Handle prepopulate cache menu action"""
        prepopulate_cache(self.main_window)

    def _open_lmstudio(self):
        """Tools > Convenience > Open LM Studio."""
        from browser_window.managers.lmstudio_launcher import open_lmstudio_or_show_install_help

        open_lmstudio_or_show_install_help(self.main_window)

    def _debug_list_models(self):
        """Tools > Debug > List Models — browse cached HF and LM Studio models."""
        from list_models import run_list_models_window

        run_list_models_window(self.main_window)

    def _debug_see_generation_timings(self):
        """Tools > Debug > See timings — saved generation timing averages."""
        from imagegen_plugins.generation_timing_dialog import show_generation_timing_dialog

        show_generation_timing_dialog(self.main_window)

    def _debug_view_print_log(self):
        """Open the in-app live print() log viewer."""
        import print_log_redirect
        from print_log_dialog import show_print_log_dialog

        path = print_log_redirect.PRINT_LOG_FILE_PATH
        if not path:
            show_styled_warning(
                self.main_window,
                "View log",
                "Print log path is not available.",
            )
            return
        show_print_log_dialog(self.main_window, path)

    def _debug_random_images(self):
        """Handle Tools > Debug > Random Images - load 200 random images from recent dirs"""
        if not run_random_images_from_recents(self.main_window):
            show_styled_warning(
                self.main_window,
                "Debug: Random Images",
                "No recent directories with images found. Open some directories first (File > Recent).",
            )

    def _debug_check_loras(self):
        """Tools > Debug > Check LoRAs — probe MFLUX compatibility per FLUX model."""
        from imagegen_plugins.lora_check_dialog import run_check_loras_dialog

        run_check_loras_dialog(self.main_window)

    def _debug_reset_all_gen_settings(self):
        """Tools > Debug > Reset All Gen Settings — clear saved image-gen dialog field values."""
        reply = show_styled_question(
            self.main_window,
            "Reset All Gen Settings",
            "Reset saved image-generation dialog settings (create, edit, expand, infill) "
            "to each model's defaults?\n\n"
            "Active model choices, window geometry, and LoRA catalog are not changed.",
            default_no=True,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from imagegen_plugins.image_gen_persistence import reset_all_gen_dialog_settings

        reset_all_gen_dialog_settings()
        reopen = ""
        existing = getattr(self.main_window, "_imagegen_function_dialog", None)
        if existing is not None and existing.isVisible():
            reopen = "\n\nClose and reopen the image-generation dialog to see the defaults."
        show_styled_information(
            self.main_window,
            "Reset All Gen Settings",
            f"Image-generation dialog settings were reset.{reopen}",
        )

    def _debug_download_sample_flux_loras(self):
        """Image > Download LoRAs — bash script with hf download commands."""
        from imagegen_plugins.debug_download_script_dialog import (
            run_flux_lora_download_script_dialog,
        )

        run_flux_lora_download_script_dialog(self.main_window)

    def _debug_download_flux_models(self):
        """Image > Manage models — pick a plugin model to install or delete."""
        from imagegen_plugins.debug_download_models_dialog import run_download_models_dialog

        run_download_models_dialog(self.main_window)

    def _debug_save_canvas_available(self, main_window) -> bool:
        """Whether Save Canvas can run (no grab — safe for menu aboutToShow)."""
        mode = getattr(main_window, "current_view_mode", None)
        if mode == "browse":
            image_label = getattr(main_window, "image_label", None)
            if image_label:
                pixmap = image_label.pixmap()
                return pixmap is not None and not pixmap.isNull()
        elif mode == "thumbnail":
            thumb_mgr = getattr(main_window, "thumbnail_container", None)
            canvas = getattr(thumb_mgr, "canvas", None) if thumb_mgr else None
            return (
                canvas is not None
                and canvas.isVisible()
                and canvas.width() > 0
                and canvas.height() > 0
            )
        return False

    def _debug_save_canvas_pixmap(self, main_window):
        """Pixmap for Tools > Debug > Save Canvas (browse label or thumbnail canvas)."""
        if not self._debug_save_canvas_available(main_window):
            return None
        mode = getattr(main_window, "current_view_mode", None)
        if mode == "browse":
            return main_window.image_label.pixmap()
        thumb_mgr = main_window.thumbnail_container
        return thumb_mgr.canvas.grab()

    def _debug_save_canvas(self):
        """Tools > Debug > Save Canvas — PNG of browse or thumbnail canvas (imagegen-NNNN.png)."""
        mw = self.main_window
        pixmap = self._debug_save_canvas_pixmap(mw)
        if pixmap is None:
            mode = getattr(mw, "current_view_mode", None)
            if mode not in ("browse", "thumbnail"):
                show_styled_warning(
                    mw,
                    "Save Canvas",
                    "Switch to browse or thumbnail view first.",
                )
            else:
                show_styled_warning(
                    mw,
                    "Save Canvas",
                    "Nothing to save — the canvas has no display content.",
                )
            return
        from imagegen_plugins.image_gen_naming import next_imagegen_path

        out_path = next_imagegen_path(ext=".png")
        if not pixmap.save(out_path, "PNG"):
            show_styled_critical(
                mw,
                "Save Canvas",
                f"Could not write PNG:\n{out_path}",
            )
            return
        if hasattr(mw, "status_notification") and mw.status_notification:
            mw.status_notification.show_message(
                f"Canvas saved:\n{out_path}",
                duration=4000,
            )

    def _debug_extract_faces(self):
        """Search > Extract faces — same as context menu: current image + Faces tab examine."""
        mw = self.main_window
        if not hasattr(mw, 'selection_manager') or not mw.selection_manager:
            return
        paths = mw.selection_manager.get_selected_files()
        if len(paths) != 1:
            return
        path = paths[0]
        if not path or not os.path.exists(path):
            return
        if hasattr(mw, 'set_current_image_by_path'):
            mw.set_current_image_by_path(path, fallback_index=0)
        if hasattr(mw, 'highlight_image'):
            mw.highlight_image()
        mw.show_settings(auto_extract_faces=True)

    def _backup_custom_sort(self):
        """Backup the .prsort file to .prsort.bak with MD5 hashes"""
        mw = self.main_window
        if not mw.current_directory:
            show_styled_warning(mw, "Error", "No directory is currently open.")
            return
        
        prsort_path = mw.sorting_manager._get_prsort_file_path(mw.current_directory)
        backup_path = prsort_path + '.bak'
        
        if not os.path.exists(prsort_path):
            show_styled_warning(mw, "Error", f"Custom sort file not found:\n{prsort_path}")
            return
        
        try:
            # Read the .prsort file
            prsort_result = mw.sorting_manager._read_prsort_file(mw.current_directory)
            if not prsort_result:
                show_styled_warning(mw, "Error", f"Could not read custom sort file:\n{prsort_path}")
                return
            
            filenames, is_reversed, locked_files = prsort_result
            
            # Compute MD5 hash for each file
            def compute_file_hash(filepath):
                """Compute MD5 hash of a file"""
                try:
                    md5_hash = hashlib.md5()
                    with open(filepath, 'rb') as f:
                        for chunk in iter(lambda: f.read(4096), b''):
                            md5_hash.update(chunk)
                    return md5_hash.hexdigest()
                except Exception as e:
                    print(f"Error computing hash for {filepath}: {e}")
                    return None
            
            # Write backup file with hashes
            with open(backup_path, 'w', encoding='utf-8') as f:
                # Write header comments
                f.write('# THIS FILE IS A BACKUP WITH MD5 HASHES FOR FILE IDENTIFICATION\n')
                f.write('# Format: *filename.jpg:hash (locked) or filename.jpg:hash (unlocked)\n')
                f.write(f'#reversed:{str(is_reversed).lower()}\n')
                
                # Write each file with its hash
                for filename in filenames:
                    file_path = os.path.join(mw.current_directory, filename)
                    if os.path.exists(file_path):
                        file_hash = compute_file_hash(file_path)
                        if file_hash:
                            lock_prefix = '*' if filename in locked_files else ''
                            f.write(f'{lock_prefix}{filename}:{file_hash}\n')
                        else:
                            # If hash computation fails, write without hash (fallback)
                            lock_prefix = '*' if filename in locked_files else ''
                            f.write(f'{lock_prefix}{filename}\n')
                    else:
                        # File doesn't exist, write without hash
                        lock_prefix = '*' if filename in locked_files else ''
                        f.write(f'{lock_prefix}{filename}\n')
            
            if hasattr(mw, 'status_notification'):
                mw.status_notification.show_message(f"Custom sort backed up to:\n{backup_path}", duration=4000)
        except Exception as e:
            show_styled_critical(mw, "Error", f"Failed to backup custom sort:\n{str(e)}")
    
    def _restore_custom_sort(self):
        """Restore the .prsort file from .prsort.bak using MD5 hash matching"""
        mw = self.main_window
        if not mw.current_directory:
            show_styled_warning(mw, "Error", "No directory is currently open.")
            return
        
        prsort_path = mw.sorting_manager._get_prsort_file_path(mw.current_directory)
        backup_path = prsort_path + '.bak'
        
        if not os.path.exists(backup_path):
            show_styled_warning(mw, "Error", f"Backup file not found:\n{backup_path}")
            return
        
        try:
            # Read backup file with hashes
            def read_backup_with_hashes(backup_path):
                """Read backup file and return list of (filename, hash, is_locked) tuples"""
                entries = []
                is_reversed = False
                try:
                    with open(backup_path, 'r', encoding='utf-8') as f:
                        lines = [line.strip() for line in f if line.strip()]
                        if not lines:
                            return None, False
                        
                        # Skip header comments
                        while lines and (lines[0].startswith('#') or not lines[0]):
                            if lines[0].startswith('#reversed:'):
                                is_reversed_str = lines[0].split(':', 1)[1].lower()
                                is_reversed = is_reversed_str == 'true'
                            lines = lines[1:]
                        
                        # Parse entries
                        for line in lines:
                            is_locked = line.startswith('*')
                            if is_locked:
                                line = line[1:]  # Remove lock prefix
                            
                            # Check if hash is present (format: filename:hash)
                            if ':' in line:
                                parts = line.rsplit(':', 1)  # Split from right to handle filenames with colons
                                filename = parts[0]
                                file_hash = parts[1]
                                entries.append((filename, file_hash, is_locked))
                            else:
                                # Old format without hash - use filename as identifier
                                entries.append((line, None, is_locked))
                    
                    return entries, is_reversed
                except Exception as e:
                    print(f"Error reading backup file: {e}")
                    return None, False
            
            # Compute MD5 hash for a file
            def compute_file_hash(filepath):
                """Compute MD5 hash of a file"""
                try:
                    md5_hash = hashlib.md5()
                    with open(filepath, 'rb') as f:
                        for chunk in iter(lambda: f.read(4096), b''):
                            md5_hash.update(chunk)
                    return md5_hash.hexdigest()
                except Exception as e:
                    print(f"Error computing hash for {filepath}: {e}")
                    return None
            
            # Read backup entries
            backup_entries, is_reversed = read_backup_with_hashes(backup_path)
            if backup_entries is None:
                show_styled_warning(mw, "Error", f"Could not read backup file:\n{backup_path}")
                return
            
            # Get all current files in directory
            if not hasattr(mw, 'directory_loader'):
                show_styled_warning(mw, "Error", "Directory loader not available.")
                return
            
            # Get current file list using directory loader's scan method
            current_files = []
            try:
                image_extensions = get_image_extensions()
                for item in os.listdir(mw.current_directory):
                    item_path = os.path.join(mw.current_directory, item)
                    if os.path.isfile(item_path):
                        if get_file_extension(item) in image_extensions:
                            current_files.append(item_path)
            except Exception as e:
                show_styled_critical(mw, "Error", f"Failed to list directory files:\n{str(e)}")
                return
            
            # Compute hashes for all current files
            file_hash_to_paths = {}  # hash -> list of paths (for handling duplicates)
            filename_to_path = {}  # filename -> path (fallback for entries without hash)
            
            for file_path in current_files:
                filename = os.path.basename(file_path)
                filename_to_path[filename] = file_path
                
                file_hash = compute_file_hash(file_path)
                if file_hash:
                    if file_hash not in file_hash_to_paths:
                        file_hash_to_paths[file_hash] = []
                    file_hash_to_paths[file_hash].append(file_path)
            
            # Build restored order
            restored_paths = []
            restored_filenames = set()
            locked_files = set()
            
            # Process backup entries in order
            for backup_filename, backup_hash, is_locked in backup_entries:
                matched_paths = []
                
                if backup_hash:
                    # Match by hash
                    if backup_hash in file_hash_to_paths:
                        matched_paths = file_hash_to_paths[backup_hash]
                else:
                    # Fallback: match by filename (old format without hash)
                    if backup_filename in filename_to_path:
                        matched_paths = [filename_to_path[backup_filename]]
                
                # Add matched files in order (files with same hash in saved order)
                for path in matched_paths:
                    if path not in restored_paths:
                        restored_paths.append(path)
                        restored_filenames.add(os.path.basename(path))
                        if is_locked:
                            locked_files.add(os.path.basename(path))
            
            # Add files not in backup to the end
            for file_path in current_files:
                filename = os.path.basename(file_path)
                if filename not in restored_filenames:
                    restored_paths.append(file_path)
            
            # Write restored .prsort file
            filenames = [os.path.basename(path) for path in restored_paths]
            
            # Write to .prsort file
            with open(prsort_path, 'w', encoding='utf-8') as f:
                f.write('# THIS FILE IS ONLY FOR CUSTOM SORT ORDERING AND FILE LOCKING\n')
                f.write('# DO NOT USE .prsort TO ORDER UNLOCKED FILES\n')
                f.write(f'#reversed:{str(is_reversed).lower()}\n')
                
                for filename in filenames:
                    if filename in locked_files:
                        f.write(f'*{filename}\n')
                    else:
                        f.write(f'{filename}\n')
            
            # Invalidate thumbnail cache for all restored files (memory only, skip disk deletion)
            # This ensures thumbnails are regenerated with the correct order after restore
            # Files haven't changed, so disk cache is still valid - we just need to clear memory cache
            if hasattr(mw, 'cache_manager') and mw.cache_manager and restored_paths:
                try:
                    cache_manager = mw.cache_manager
                    
                    # Batch clear memory cache entries in a single mutex lock (fast, no disk I/O)
                    with QMutexLocker(cache_manager.cache_mutex):
                        # Build set of cache key bases for all restored files
                        cache_key_bases = set()
                        for file_path in restored_paths:
                            cache_key = cache_manager.get_cache_key(file_path)
                            # Extract base cache key (path hash) - cache key format is "hash" or "hash_mtime"
                            cache_key_base = cache_key.split('_')[0] if '_' in cache_key else cache_key
                            cache_key_bases.add(cache_key_base)
                            cache_key_bases.add(cache_key)  # Also match exact key
                        
                        # Remove all matching entries from memory cache
                        keys_to_remove = []
                        for key in list(cache_manager.thumbnail_cache.keys()):
                            # Match keys that start with any of our cache key bases
                            if any(key.startswith(base + "_") or key == base for base in cache_key_bases):
                                keys_to_remove.append(key)
                        
                        for key in keys_to_remove:
                            del cache_manager.thumbnail_cache[key]
                        
                        # Invalidate cache directory listing
                        cache_manager.invalidate_thumbnail_dir_cache()
                except Exception as e:
                    print(f"Error clearing thumbnail cache: {e}")
            
            # Also invalidate thumbnails in canvas if they're currently displayed
            if hasattr(mw, 'thumbnail_container') and hasattr(mw.thumbnail_container, 'canvas'):
                try:
                    mw.thumbnail_container.canvas.invalidate_thumbnails_for_paths(restored_paths)
                except Exception as e:
                    print(f"Error invalidating canvas thumbnails: {e}")
            
            # Reload directory first to scan all files from disk
            directory_to_reload = mw.current_directory
            
            def do_reload_and_custom():
                if not directory_to_reload:
                    return
                
                # First reload directory to scan all files from disk
                if hasattr(mw, 'directory_loader'):
                    mw.directory_loader.load_directory(
                        directory_to_reload,
                        external_load=False,
                        refresh_mode=True
                    )
                
                # Then switch to custom sort mode (this reads .prsort and applies the order)
                def trigger_custom_sort():
                    mw.set_custom_sort()
                
                # Delay to ensure directory is loaded before applying custom sort
                QTimer.singleShot(600, trigger_custom_sort)
            
            # Execute reload and custom sort with a small delay
            QTimer.singleShot(100, do_reload_and_custom)
            
        except Exception as e:
            show_styled_critical(mw, "Error", f"Failed to restore custom sort:\n{str(e)}")
    
    def _setup_sort_actions(self, view_menu):
        """Setup sort-related actions in a "Sort >" submenu"""

        # Create "Sort >" submenu
        sort_menu = QMenu("Sort", self.main_window)
        # Store reference to sort menu action for visibility control
        self.sort_menu_action = view_menu.addMenu(sort_menu)

        # Sort by Date - Newest first (shortcut handled by keyboard handler)
        self.main_window.date_sort_action = QAction("Sort by Date (Newest First)", self.main_window)
        self.main_window.date_sort_action.setShortcut(QKeySequence("D"))
        self.main_window.date_sort_action.setCheckable(True)
        self.main_window.date_sort_action.triggered.connect(lambda: self.main_window.set_date_sort(reverse=False))
        sort_menu.addAction(self.main_window.date_sort_action)
        
        # Sort by Date - Oldest first (shortcut handled by keyboard handler)
        self.main_window.date_sort_newest_action = QAction("Sort by Date (Oldest First)", self.main_window)
        self.main_window.date_sort_newest_action.setShortcut(QKeySequence("Shift+D"))
        self.main_window.date_sort_newest_action.setCheckable(True)
        self.main_window.date_sort_newest_action.triggered.connect(lambda: self.main_window.set_date_sort(reverse=True))
        sort_menu.addAction(self.main_window.date_sort_newest_action)

        # Sort by EXIF Date  month- Newest first
        self.main_window.exif_date_sort_action = QAction("Sort by Month (Newest First)", self.main_window)
        self.main_window.exif_date_sort_action.setShortcut(QKeySequence("X"))
        self.main_window.exif_date_sort_action.setCheckable(True)
        self.main_window.exif_date_sort_action.triggered.connect(lambda: self.main_window.set_exif_date_sort(reverse=False))
        sort_menu.addAction(self.main_window.exif_date_sort_action)

        # Sort by EXIF Date month - Oldest first
        self.main_window.exif_date_sort_reverse_action = QAction("Sort by Month (Oldest First)", self.main_window)
        self.main_window.exif_date_sort_reverse_action.setShortcut(QKeySequence("Shift+X"))
        self.main_window.exif_date_sort_reverse_action.setCheckable(True)
        self.main_window.exif_date_sort_reverse_action.triggered.connect(lambda: self.main_window.set_exif_date_sort(reverse=True))
        sort_menu.addAction(self.main_window.exif_date_sort_reverse_action)

        # Sort by EXIF Date year - Newest first
        self.main_window.exif_year_sort_action = QAction("Sort by Year (Newest First)", self.main_window)
        self.main_window.exif_year_sort_action.setShortcut(QKeySequence("Y"))
        self.main_window.exif_year_sort_action.setCheckable(True)
        self.main_window.exif_year_sort_action.triggered.connect(lambda: self.main_window.set_exif_year_sort(reverse=False))
        sort_menu.addAction(self.main_window.exif_year_sort_action)

        # Sort by EXIF Date year - Oldest first
        self.main_window.exif_year_sort_reverse_action = QAction("Sort by Year (Oldest First)", self.main_window)
        self.main_window.exif_year_sort_reverse_action.setShortcut(QKeySequence("Shift+Y"))
        self.main_window.exif_year_sort_reverse_action.setCheckable(True)
        self.main_window.exif_year_sort_reverse_action.triggered.connect(lambda: self.main_window.set_exif_year_sort(reverse=True))
        sort_menu.addAction(self.main_window.exif_year_sort_reverse_action)


        
        # Sort by Name - A-Z (shortcut handled by keyboard handler)


        self.main_window.name_sort_action = QAction("Sort by Name (A-Z)", self.main_window)
        self.main_window.name_sort_action.setShortcut(QKeySequence("N"))
        self.main_window.name_sort_action.setCheckable(True)
        self.main_window.name_sort_action.triggered.connect(lambda: self.main_window.set_name_sort(reverse=False))
        sort_menu.addAction(self.main_window.name_sort_action)
        
        # Sort by Name - Z-A (shortcut handled by keyboard handler)
        self.main_window.name_sort_reverse_action = QAction("Sort by Name (Z-A)", self.main_window)
        self.main_window.name_sort_reverse_action.setShortcut(QKeySequence("Shift+N"))
        self.main_window.name_sort_reverse_action.setCheckable(True)
        self.main_window.name_sort_reverse_action.triggered.connect(lambda: self.main_window.set_name_sort(reverse=True))
        sort_menu.addAction(self.main_window.name_sort_reverse_action)
        
        # Sort by Size - Largest first (shortcut handled by keyboard handler)
        self.main_window.size_sort_action = QAction("Sort by Image Size (Largest First)", self.main_window)
        self.main_window.size_sort_action.setShortcut(QKeySequence("Z"))
        self.main_window.size_sort_action.setCheckable(True)
        self.main_window.size_sort_action.triggered.connect(lambda: self.main_window.set_size_sort(reverse=False))
        sort_menu.addAction(self.main_window.size_sort_action)
        
        # Sort by Size - Smallest first (shortcut handled by keyboard handler)
        self.main_window.size_sort_reverse_action = QAction("Sort by Image Size (Smallest First)", self.main_window)
        self.main_window.size_sort_reverse_action.setShortcut(QKeySequence("Shift+Z"))
        self.main_window.size_sort_reverse_action.setCheckable(True)
        self.main_window.size_sort_reverse_action.triggered.connect(lambda: self.main_window.set_size_sort(reverse=True))
        
        sort_menu.addAction(self.main_window.size_sort_reverse_action)
        
        # Reverse Order - Toggle current sort direction
        self.main_window.reverse_order_action = QAction("Reverse Sort Order", self.main_window)
        self.main_window.reverse_order_action.setShortcut(QKeySequence("Ctrl+T"))
        self.main_window.reverse_order_action.triggered.connect(self.main_window.simple_reverse_image_order)
        sort_menu.addAction(self.main_window.reverse_order_action)
        
        # Random Order (shortcut handled by keyboard handler)
        self.main_window.random_action = QAction("Random Sort", self.main_window)
        self.main_window.random_action.setShortcut(QKeySequence("R"))
        self.main_window.random_action.setCheckable(True)
        self.main_window.random_action.triggered.connect(lambda: self.main_window.view_mode_manager.set_random_mode())
        sort_menu.addAction(self.main_window.random_action)
        
        # Custom Order (shortcut handled by keyboard handler)
        self.main_window.custom_sort_action = QAction("Custom Sort", self.main_window)
        self.main_window.custom_sort_action.setShortcut(QKeySequence("C"))
        self.main_window.custom_sort_action.setCheckable(True)
        self.main_window.custom_sort_action.triggered.connect(self.main_window.set_custom_sort)
        sort_menu.addAction(self.main_window.custom_sort_action)

    def set_tree_filter_mode(self, mode: str):
        """Set tree filter mode and update config"""
        mw = self.main_window
        # Show tree if it's not visible (only in thumbnail view)
        if mw.current_view_mode == 'thumbnail' and not mw.file_tree_visible:
            # Use combined_sidebar if available, otherwise use toggle_file_tree
            if hasattr(mw, 'combined_sidebar') and mw.combined_sidebar:
                mw.combined_sidebar.set_tree_visible(True)
            elif hasattr(mw, 'toggle_file_tree_action'):
                # Set the action to checked and trigger it
                mw.toggle_file_tree_action.setChecked(True)
                if hasattr(mw, 'toggle_file_tree'):
                    mw.toggle_file_tree()
        # Update the filtered_tree setting
        mw.filtered_tree = mode
        # Apply to file tree handler
        if hasattr(mw, 'file_tree_handler') and mw.file_tree_handler:
            mw.file_tree_handler.apply_filtered_tree(mode)
            # Highlight current directory after filter is applied (delay to ensure tree updates)
            def highlight_after_filter():
                if hasattr(mw, 'file_tree_handler') and mw.file_tree_handler:
                    # CRITICAL: Don't override user-requested directory selection
                    if not mw.file_tree_handler.user_requested_directory:
                        mw.file_tree_handler.highlight_current_directory()
            QTimer.singleShot(100, highlight_after_filter)
        # Save to config
        if hasattr(mw, 'config') and mw.config:
            settings = mw.config.load_settings()
            settings['filtered_tree'] = mode
            mw.config.save_settings(settings)
    
    def _setup_help_menu(self, menubar):
        """Setup Help menu"""
        help_menu = menubar.addMenu("Help")
        
        # Keyboard Shortcuts - F1 shows in menu, but "/" also works
        help_action = QAction("Keyboard Shortcuts", self.main_window)
        help_action.setShortcut("F1")  # Shows F1 in menu
        # Also register "/" as an alternative shortcut (handled by keyboard_handler)
        help_action.triggered.connect(self.main_window.show_help_test)
        help_menu.addAction(help_action)

        pf_keys_action = QAction("PF Keys...", self.main_window)
        pf_keys_action.triggered.connect(self.main_window.show_pf_help)
        help_menu.addAction(pf_keys_action)

        try:
            from bundle_capabilities import imagegen_ui_enabled

            _imagegen_help_ui = imagegen_ui_enabled()
        except ImportError:
            _imagegen_help_ui = True
        if _imagegen_help_ui:
            downloading_models_action = QAction("Downloading AI Models...", self.main_window)
            downloading_models_action.triggered.connect(
                self.main_window.show_downloading_models_help
            )
            help_menu.addAction(downloading_models_action)

        # Modifier+click actions — update browser_window/dialogs/help_hidden_gems.py when adding new ones
        hidden_gems_action = QAction("Hidden Gems...", self.main_window)
        hidden_gems_action.triggered.connect(self.main_window.show_hidden_gems_help)
        help_menu.addAction(hidden_gems_action)
        
        # help_menu.addSeparator()
        # Separator: Developer's notes
        dev_notes_action = QAction("────────── Developer's notes ──────────", self.main_window)
        dev_notes_action.setEnabled(False)
        help_menu.addAction(dev_notes_action)
        
        # Why Was This Written?
        why_action = QAction("Quick Start, Notes and More...", self.main_window)
        why_action.triggered.connect(self.main_window.show_why_written)
        help_menu.addAction(why_action)
       
        # Command Line Help
        command_line_action = QAction("Command Line...", self.main_window)
        command_line_action.triggered.connect(self.main_window.show_command_line_help)
        help_menu.addAction(command_line_action)

        # API documentation
        api_action = QAction("API Documentation...", self.main_window)
        api_action.triggered.connect(self.main_window.show_api_help)
        help_menu.addAction(api_action)
     
    def initialize_menu_states(self):
        """Initialize menu checkmarks and states"""
        # Initialize sort menu checkmarks
        self.update_sort_menu_checkmarks()
        
        # Initialize filename menu text
        self.update_filename_menu_text()
        
        # Initialize edit menu states (including destination menu items)
        self.update_edit_menu_states()
        
        # Initialize favorites menu (to register shortcuts immediately)
        self.update_file_menu_favorites()
        
        # Initialize search menu states
        self.update_search_menu_states()
        
        # Initialize tools menu states
        self.update_tools_menu_states()
        
        # Initialize wallpaper menu checkmarks
        if hasattr(self.main_window, 'wallpaper_contain_action'):
            settings = self.main_window.config.load_settings()
            fit_method = settings.get('last_used_wallpaper_fit_method', 'contain')
            if fit_method == 'current_display':
                fit_method = 'cover'
                settings['last_used_wallpaper_fit_method'] = 'cover'
                settings['wallpaper_use_zoomed_display'] = True
                self.main_window.config.save_settings(settings)
            self.main_window.update_wallpaper_menu_checkmarks(fit_method)
            self.main_window.sync_wallpaper_zoomed_display_menu_from_settings()

        # Initialize screen copy menu checkmarks
        if hasattr(self.main_window, 'create_screen_copy_contain_action'):
            settings = self.main_window.config.load_settings()
            fit_method = settings.get('last_used_screen_copy_fit_method', 'cover')
            self.main_window.update_screen_copy_menu_checkmarks(fit_method)
        
        # Ensure undo action shortcut is properly registered
        # This fixes the issue where Cmd+Z doesn't work the first time
        if hasattr(self.main_window, 'undo_action') and self.main_window.undo_action:
            # Ensure action is enabled
            self.main_window.undo_action.setEnabled(True)
            # Re-register the shortcut to ensure it's active (matches copy_path_action behavior)
            self.main_window.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        
        # Ensure quick mass rename action shortcut is properly registered
        # This fixes the issue where Ctrl+Shift+M doesn't work the first time
        if hasattr(self.main_window, 'quick_mass_rename_action') and self.main_window.quick_mass_rename_action:
            # Ensure action is enabled
            self.main_window.quick_mass_rename_action.setEnabled(True)
            # Re-register the shortcut to ensure it's active
            self.main_window.quick_mass_rename_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
            self.main_window.quick_mass_rename_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
    
    def prime_menu_keys_for_view_change(self):
        """Prime and enable menu keys after a view mode change (thumbnail/browse/list/slideshow).
        
        Runs the same logic as menu aboutToShow handlers plus shortcut re-registration.
        On macOS, Qt's native menu bar may not register shortcuts until the menu is shown;
        calling this on every view transition ensures shortcuts work without opening menus.
        """
        self.update_view_menu_enabled_states()
        self.update_edit_menu_states()
        self.update_tools_menu_states()
        self.update_search_menu_states()
        self.update_file_menu_browse_image_history_action()
        self.update_file_menu_last_image_action()
        self._register_menu_shortcuts_with_window()
    
    def update_macos_display_mode_menu(self):
        """Update the single macOS display mode menu label for current Space/windowed state."""
        mw = self.main_window
        action = getattr(mw, 'macos_display_mode_action', None)
        if not action:
            return
        in_macos_space = is_macos_space_mode()
        if not in_macos_space and hasattr(mw, 'isFullScreen'):
            in_macos_space = mw.isFullScreen()
        try:
            action.setText(
                "Show in Windowed mode" if in_macos_space else "Show in MacOS Space"
            )
        except RuntimeError:
            pass  # C++ object may be deleted (macOS native menu bar)
    
    def apply_dark_theme(self):
        """Apply dark theme to match the web version
        
        Note: Theme is now applied globally via QApplication.setStyleSheet() in main.py.
        This method is kept for backward compatibility but does nothing.
        """
        # Theme is applied globally, no action needed
        pass
    from typing import List, Dict, Any

    def query_menu_keys(self) -> List[Dict[str, Any]]:
        """
        Returns a list of keys defined in the menu and their descriptions.
        Uses macOS native menu queries to avoid PySide6 menu object deletion issues.
        Returns:
            List of dicts: {
                'key_name': <str>,
                'key_description': <str>,
                'key_active': <bool>
            }
        """
        import sys

        menu_keys: List[Dict[str, Any]] = []

        # Helper to format shortcut as "D+Shift+Cmd" (base key first, then modifiers)
        def format_shortcut(base_key, mods):
            # Place base key first, then each modifier with +, e.g. "D+Shift+Cmd"
            if mods:
                return ("+".join(mods) + "+" + base_key).strip("+")
            else:
                return base_key

        # Recursive helper to process menu items and their submenus
        def process_menu(menu, menu_keys):
            """Recursively process a menu and all its nested submenus"""
            if menu is None:
                return
            for j in range(menu.numberOfItems()):
                subItem = menu.itemAtIndex_(j)
                # Check if this item has a submenu - if so, recurse into it first
                # Skip Services submenu - do not show its entries in help
                item_submenu = subItem.submenu()
                if item_submenu is not None and str(subItem.title()) != "Services":
                    process_menu(item_submenu, menu_keys)
                # Check if this item has a keyboard shortcut
                key_equiv = subItem.keyEquivalent()
                if key_equiv:
                    # Build shortcut string (base key first, then modifiers)
                    mods = []
                    modifierMask = subItem.keyEquivalentModifierMask()
                    # Use macOS constants for clarity and reliability
                    if modifierMask & NSEventModifierFlagCommand:
                        mods.append("Cmd")
                    if modifierMask & NSEventModifierFlagShift:
                        mods.append("Shift")
                    if modifierMask & NSEventModifierFlagOption:
                        mods.append("Alt")
                    if modifierMask & NSEventModifierFlagControl:
                        mods.append("Ctrl")
                    shortcut = format_shortcut(key_equiv.upper(), mods)
                    menu_keys.append({
                        'key_name': shortcut,
                        'key_description': str(subItem.title())+  " *",
                        'key_active': subItem.isEnabled()
                    })

        try:
            from AppKit import NSApplication, NSEventModifierFlagCommand, NSEventModifierFlagShift, NSEventModifierFlagOption, NSEventModifierFlagControl
            app = NSApplication.sharedApplication()
            mainMenu = app.mainMenu()
            for i in range(mainMenu.numberOfItems()):
                menuItem = mainMenu.itemAtIndex_(i)
                submenu = menuItem.submenu()
                if submenu is None:
                    continue
                # Use recursive helper to process all menu items including nested submenus
                process_menu(submenu, menu_keys)
        except Exception as e:
            print(f"[query_menu_keys] macOS menu query failed: {e}")
            return []
        return menu_keys

    def update_edit_menu_states(self):
        """Update the enabled states and text of edit menu actions based on view mode and last drop location"""
        mw = self.main_window
        if not hasattr(mw, 'move_to_last_drop_action'):
            return

        settings = mw.config.load_settings()
        dest_action = settings.get('destination_menu_action', 'move')
        show_destinations = dest_action != 'none'
        verb = "Copy" if dest_action == 'copy' else "Move"
        menu_title = "Copy to" if dest_action == 'copy' else "Move to"

        # Update menu title - get fresh reference from menubar (macOS recreates it when dialog closes)
        # When 'none': menu stays visible as "Move To" but destinations/keys are hidden; only "Edit destinations" shown
        try:
            menubar = mw.menuBar()
            for action in menubar.actions():
                submenu = action.menu()
                if submenu and submenu.title() in ("Move to", "Copy to"):
                    # Confirm this is our Move menu before modifying (prevents hiding View/Tools by mistake)
                    if hasattr(mw, 'move_to_last_drop_action') and mw.move_to_last_drop_action in submenu.actions():
                        submenu.setTitle(menu_title)
                        menu_action = submenu.menuAction()
                        if menu_action:
                            menu_action.setText(menu_title)
                        self.move_menu = submenu
                        # Menu always visible; when 'none' only "Edit destinations" subitem is shown
                    break
        except RuntimeError:
            pass  # C++ object already deleted

        # Get last drop location from file tree
        last_drop_location = None
        if (hasattr(mw, 'file_tree_handler') and 
            hasattr(mw.file_tree_handler, 'file_tree') and 
            mw.file_tree_handler.file_tree):
            from files.file_tree_handler import CustomTreeView
            if isinstance(mw.file_tree_handler.file_tree, CustomTreeView):
                last_drop_location = mw.file_tree_handler.file_tree.get_last_drop_location()

        # Show/hide destination separator, last drop action, move work files based on destination_menu_action
        # When 'none': hide all destination items; only "Edit destinations" remains visible
        if hasattr(self, 'destination_separator_action'):
            self.destination_separator_action.setVisible(show_destinations)
        if hasattr(self, 'dynamic_move_separator_action'):
            self.dynamic_move_separator_action.setVisible(show_destinations)
        mw.move_to_last_drop_action.setVisible(show_destinations)

        # Disable shortcuts when 'none' - keys are not enabled
        if not show_destinations:
            mw.move_to_last_drop_action.setShortcut(QKeySequence())
            if hasattr(mw, 'copy_to_last_drop_action'):
                mw.copy_to_last_drop_action.setShortcut(QKeySequence())
        else:
            mw.move_to_last_drop_action.setShortcut(QKeySequence("Ctrl+0"))
            if hasattr(mw, 'copy_to_last_drop_action'):
                mw.copy_to_last_drop_action.setShortcut(QKeySequence("Alt+Ctrl+0"))

        # Enable/disable copy-to-last-drop shortcut (Option+Cmd+0) alongside move shortcut
        if hasattr(mw, 'copy_to_last_drop_action'):
            if not show_destinations:
                mw.copy_to_last_drop_action.setEnabled(False)
            elif mw.current_view_mode in ['slideshow', 'slideshow2', 'slideshow3']:
                mw.copy_to_last_drop_action.setEnabled(False)
            elif mw.current_view_mode in ['thumbnail', 'browse'] and last_drop_location and os.path.isdir(last_drop_location):
                mw.copy_to_last_drop_action.setEnabled(True)
            else:
                mw.copy_to_last_drop_action.setEnabled(False)

        # Enable/disable and update text based on view mode and last drop location
        # Disable move actions in slideshow modes
        if mw.current_view_mode in ['slideshow', 'slideshow2', 'slideshow3']:
            mw.move_to_last_drop_action.setEnabled(False)
            mw.move_to_last_drop_action.setText(f"{verb} to Last Drop Location")
        elif mw.current_view_mode == 'thumbnail' and last_drop_location and os.path.isdir(last_drop_location):
            # Extract last segment of path for menu text
            last_segment = os.path.basename(last_drop_location.rstrip('/'))
            mw.move_to_last_drop_action.setText(f"{verb} to {last_segment}")
            mw.move_to_last_drop_action.setEnabled(True)
        elif mw.current_view_mode == 'browse' and last_drop_location and os.path.isdir(last_drop_location):
            # Enable in fullscreen too
            last_segment = os.path.basename(last_drop_location.rstrip('/'))
            mw.move_to_last_drop_action.setText(f"{verb} to {last_segment}")
            mw.move_to_last_drop_action.setEnabled(True)
        else:
            mw.move_to_last_drop_action.setText(f"{verb} to Last Drop Location")
            mw.move_to_last_drop_action.setEnabled(False)

        # Update destination 1-9 menu items
        if hasattr(mw, 'move_to_destination_actions') and mw.move_to_destination_actions:
            # Get destinations from config
            destinations = settings.get('move_destinations', [None] * 9)

            # Ensure we have exactly 9 items
            while len(destinations) < 9:
                destinations.append(None)
            destinations = destinations[:9]

            # Disable move actions in slideshow modes
            if mw.current_view_mode in ['slideshow', 'slideshow2', 'slideshow3']:
                for action in mw.move_to_destination_actions:
                    action.setEnabled(False)
                if hasattr(mw, 'copy_to_destination_actions'):
                    for action in mw.copy_to_destination_actions:
                        action.setEnabled(False)
            else:
                # Update each menu item
                copy_actions = getattr(mw, 'copy_to_destination_actions', None) or []
                for i, action in enumerate(mw.move_to_destination_actions):
                    destination_index = i + 1  # 1-9
                    destination_path = destinations[i]
                    copy_action = copy_actions[i] if i < len(copy_actions) else None

                    # Check if destination is valid
                    if destination_path and os.path.isdir(destination_path) and show_destinations:
                        # Valid destination - show menu item with path name
                        last_segment = os.path.basename(destination_path.rstrip('/'))
                        action.setText(f"{verb} to {last_segment}")
                        action.setVisible(True)
                        action.setShortcut(QKeySequence(f"Ctrl+{i + 1}"))
                        # Enable in thumbnail and browse modes
                        enabled = mw.current_view_mode in ['thumbnail', 'browse']
                        action.setEnabled(enabled)
                        if copy_action is not None:
                            copy_action.setShortcut(QKeySequence(f"Alt+Ctrl+{i + 1}"))
                            copy_action.setEnabled(enabled)
                    else:
                        # Invalid or empty destination, or 'none' mode - hide menu item and disable shortcut
                        action.setVisible(False)
                        action.setEnabled(False)
                        action.setShortcut(QKeySequence())
                        if copy_action is not None:
                            copy_action.setEnabled(False)
                            copy_action.setShortcut(QKeySequence())
        
        # Update Select All action - only enable in thumbnail mode
        if hasattr(mw, 'select_all_action'):
            mw.select_all_action.setEnabled(mw.current_view_mode == 'thumbnail')
        
        # Update Copy actions text based on selection count
        if hasattr(mw, 'copy_path_action') and mw.current_view_mode == 'thumbnail' and hasattr(mw, 'selection_manager'):
            selected_files = mw.selection_manager.get_selected_files()
            selected_count = len(selected_files) if selected_files else 0
            if selected_count > 1:
                mw.copy_path_action.setText("Copy File Paths")
            else:
                mw.copy_path_action.setText("Copy File Path")
        
        # Copy image action: single image only (no multi-select text change needed)

        # Copy EXIF UserComment: same eligibility as Edit EXIF User Comment (browse or thumbnail, single, supported ext)
        if hasattr(mw, 'copy_user_comment_action'):
            should_enable = False
            if mw.current_view_mode == 'browse':
                current_path = mw.get_current_image_path() if hasattr(mw, 'get_current_image_path') else None
                if current_path:
                    ext = os.path.splitext(current_path)[1].lower()
                    should_enable = ext in {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}
            elif mw.current_view_mode == 'thumbnail':
                if hasattr(mw, 'selection_manager'):
                    selected_files = mw.selection_manager.get_selected_files()
                    if selected_files and len(selected_files) == 1:
                        ext = os.path.splitext(selected_files[0])[1].lower()
                        should_enable = ext in {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}
            mw.copy_user_comment_action.setEnabled(should_enable)
        
        # Update Convert Selected action - only enable in thumbnail mode
        if hasattr(mw, 'convert_selected_action'):
            mw.convert_selected_action.setEnabled(mw.current_view_mode == 'thumbnail')
            # Update text based on selection count
            if mw.current_view_mode == 'thumbnail' and hasattr(mw, 'selection_manager'):
                selected_files = mw.selection_manager.get_selected_files()
                selected_count = len(selected_files) if selected_files else 0
                if selected_count > 1:
                    mw.convert_selected_action.setText("Convert Image Formats...")
                else:
                    mw.convert_selected_action.setText("Convert Image Format...")

        if hasattr(mw, 'resize_images_action'):
            thumb_resize_ok = (
                mw.current_view_mode == 'thumbnail'
                and hasattr(mw, 'selection_manager')
                and mw.selection_manager
                and len(mw.selection_manager.get_selected_files() or []) >= 1
            )
            browse_resize_ok = False
            if mw.current_view_mode == 'browse' and hasattr(mw, 'get_current_image_path'):
                cp = mw.get_current_image_path()
                browse_resize_ok = bool(cp and os.path.exists(cp))
            mw.resize_images_action.setEnabled(thumb_resize_ok or browse_resize_ok)
        
        # Update Undo action - show what it will undo and enable/disable based on availability
        if hasattr(mw, 'undo_action'):
            # Check wallpaper undo first (has priority)
            wallpaper_undo_available = (hasattr(mw, 'wallpaper_manager') and 
                                       mw.wallpaper_manager and 
                                       mw.wallpaper_manager.can_undo_wallpaper())
            
            # Check move undo (second priority)
            # If undo manager is available, check move_operations to determine if next undo is a move
            # Otherwise, check move_operations directly
            move_undo_available = False
            if hasattr(mw, 'move_operations') and mw.move_operations:
                # If undo manager is available, it will handle the undo (maintains order)
                # We check move_operations to determine if it's a move operation
                if (hasattr(mw, 'file_undo_manager') and mw.file_undo_manager and 
                    hasattr(mw.file_undo_manager, 'canUndo') and 
                    mw.file_undo_manager.canUndo()):
                    # Undo manager is available - check if move_operations has entries
                    # (moves are registered to both undo manager and move_operations)
                    move_undo_available = True
                else:
                    # No undo manager, check move_operations directly
                    move_undo_available = True
            
            # Check delete undo (only if move undo not available)
            delete_undo_available = False
            if not move_undo_available:
                if (hasattr(mw, 'file_undo_manager') and mw.file_undo_manager and 
                    hasattr(mw.file_undo_manager, 'canUndo') and 
                    mw.file_undo_manager.canUndo()):
                    delete_undo_available = True
                elif hasattr(mw, 'deletion_operations') and mw.deletion_operations:
                    delete_undo_available = True
            
            # Update text and enabled state (priority: wallpaper > move > delete)
            if wallpaper_undo_available:
                mw.undo_action.setText("Undo Wallpaper")
                mw.undo_action.setEnabled(True)
            elif move_undo_available:
                mw.undo_action.setText("Undo Move")
                mw.undo_action.setEnabled(True)
            elif delete_undo_available:
                mw.undo_action.setText("Undo Delete")
                mw.undo_action.setEnabled(True)
            else:
                mw.undo_action.setText("Undo")
                mw.undo_action.setEnabled(False)
        
        # Update Move work files action - only visible in thumbnail mode when there are image files
        # When 'none': hide move work files; only "Edit destinations" remains
        if hasattr(mw, 'move_work_files_action'):
            # Check if we're in thumbnail mode
            is_thumbnail_mode = mw.current_view_mode == 'thumbnail'
            
            # Check if there are image files present
            has_image_files = False
            if hasattr(mw, 'displayed_images') and mw.displayed_images:
                has_image_files = len(mw.displayed_images) > 0
            
            # Only show in thumbnail mode when there are image files, and when destinations are enabled
            should_show = show_destinations and is_thumbnail_mode and has_image_files
            
            mw.move_work_files_action.setVisible(should_show)
            mw.move_work_files_action.setEnabled(should_show)
            if hasattr(self, 'move_work_files_separator_action'):
                self.move_work_files_separator_action.setVisible(should_show)

    def update_tools_menu_states(self):
        """Update the enabled states of Tools menu actions"""
        mw = self.main_window
        
        # Update Show Rename Status action checkmark
        if hasattr(mw, 'show_rename_status_action') and hasattr(mw, 'rename_status_manager'):
            mw.show_rename_status_action.setChecked(mw.rename_status_manager.is_enabled())
        
        # Update Save Custom action visibility/enabled state
        if hasattr(mw, 'save_custom_action'):
            is_thumbnail_mode = (hasattr(mw, 'current_view_mode') and 
                               mw.current_view_mode == 'thumbnail')
            is_specific_files_mode = getattr(mw, 'specific_files_active', False)
            is_multiple_directories = False
            if hasattr(mw, 'get_displayed_images'):
                displayed_images = mw.get_displayed_images()
                if displayed_images:
                    directories = set()
                    for image_path in displayed_images:
                        if os.path.exists(image_path):
                            directories.add(os.path.dirname(image_path))
                    is_multiple_directories = len(directories) > 1
            should_enable = (is_thumbnail_mode and 
                           not is_specific_files_mode and 
                           not is_multiple_directories)
            mw.save_custom_action.setEnabled(should_enable)
            mw.save_custom_action.setVisible(should_enable)

        # Examine image...: enable when face_engine available, single selection, and has current image
        if hasattr(mw, 'examine_image_action'):
            face_ok = _face_engine_available()
            multiselect = False
            if hasattr(mw, 'selection_manager') and mw.selection_manager:
                selected = mw.selection_manager.get_selected_files()
                multiselect = len(selected) > 1 if selected else False
            has_current = bool(mw.get_current_image_path() if hasattr(mw, 'get_current_image_path') else False)
            mw.examine_image_action.setEnabled(face_ok and not multiselect and has_current)

        if hasattr(mw, "debug_save_canvas_action"):
            mw.debug_save_canvas_action.setEnabled(self._debug_save_canvas_available(mw))

        # Cache Faces: enable only when face_engine is available
        if hasattr(mw, 'cache_faces_action'):
            try:
                from bundle_capabilities import faces_ui_enabled

                if not faces_ui_enabled():
                    mw.cache_faces_action.setEnabled(False)
                else:
                    mw.cache_faces_action.setEnabled(_face_engine_available())
            except ImportError:
                mw.cache_faces_action.setEnabled(False)
        
        # Update Reset Date to EXIF action enabled state and text
        if hasattr(mw, 'reset_date_to_exif_action'):
            is_thumbnail_mode = (hasattr(mw, 'current_view_mode') and 
                               mw.current_view_mode == 'thumbnail')
            is_specific_files_mode = getattr(mw, 'specific_files_active', False)
            should_enable = (is_thumbnail_mode and not is_specific_files_mode)
            mw.reset_date_to_exif_action.setEnabled(should_enable)
            
            # Update text based on selection count
            if should_enable and hasattr(mw, 'selection_manager'):
                selected_files = mw.selection_manager.get_selected_files()
                selected_count = len(selected_files) if selected_files else 0
                if selected_count > 1:
                    mw.reset_date_to_exif_action.setText("Reset File Dates to Match EXIF Timestamps...")
                else:
                    mw.reset_date_to_exif_action.setText("Reset File Date to Match EXIF Timestamp...")
        
        # Update Reset EXIF to File Date action enabled state and text
        if hasattr(mw, 'reset_exif_to_file_date_action'):
            is_thumbnail_mode = (hasattr(mw, 'current_view_mode') and 
                               mw.current_view_mode == 'thumbnail')
            is_specific_files_mode = getattr(mw, 'specific_files_active', False)
            should_enable = (is_thumbnail_mode and not is_specific_files_mode)
            mw.reset_exif_to_file_date_action.setEnabled(should_enable)
            
            # Update text based on selection count
            if should_enable and hasattr(mw, 'selection_manager'):
                selected_files = mw.selection_manager.get_selected_files()
                selected_count = len(selected_files) if selected_files else 0
                if selected_count > 1:
                    mw.reset_exif_to_file_date_action.setText("Reset EXIF Timestamps to Match File Dates...")
                else:
                    mw.reset_exif_to_file_date_action.setText("Reset EXIF Timestamp to Match File Date...")
        
        # Update Delete EXIF Date action enabled state and text
        if hasattr(mw, 'delete_exif_date_action'):
            is_thumbnail_mode = (hasattr(mw, 'current_view_mode') and 
                               mw.current_view_mode == 'thumbnail')
            is_specific_files_mode = getattr(mw, 'specific_files_active', False)
            should_enable = (is_thumbnail_mode and not is_specific_files_mode)
            mw.delete_exif_date_action.setEnabled(should_enable)
            
            # Update text based on selection count
            if should_enable and hasattr(mw, 'selection_manager'):
                selected_files = mw.selection_manager.get_selected_files()
                selected_count = len(selected_files) if selected_files else 0
                if selected_count > 1:
                    mw.delete_exif_date_action.setText("Delete EXIF Dates from Files...")
                else:
                    mw.delete_exif_date_action.setText("Delete EXIF Date from File...")

        # Update Normalize EXIF Steps action enabled state
        if hasattr(mw, 'normalize_exif_steps_action'):
            is_thumbnail_mode = (
                hasattr(mw, 'current_view_mode')
                and mw.current_view_mode == 'thumbnail'
            )
            is_specific_files_mode = getattr(mw, 'specific_files_active', False)
            mw.normalize_exif_steps_action.setEnabled(
                is_thumbnail_mode and not is_specific_files_mode
            )
        
        # Update Edit EXIF User Comment action enabled state
        if hasattr(mw, 'edit_exif_usercomment_action'):
            should_enable = False
            if mw.current_view_mode == 'browse':
                current_path = mw.get_current_image_path() if hasattr(mw, 'get_current_image_path') else None
                if current_path:
                    ext = os.path.splitext(current_path)[1].lower()
                    should_enable = ext in {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}
            elif mw.current_view_mode == 'thumbnail':
                if hasattr(mw, 'selection_manager'):
                    selected_files = mw.selection_manager.get_selected_files()
                    if selected_files and len(selected_files) == 1:
                        ext = os.path.splitext(selected_files[0])[1].lower()
                        should_enable = ext in {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}
            mw.edit_exif_usercomment_action.setEnabled(should_enable)

        # Update Edit in External Editor action text and enabled state
        if hasattr(mw, 'edit_with_external_editor_action'):
            # Update menu text dynamically based on current editor setting
            config = get_config()
            settings = config.load_settings()
            editor_app = settings.get('image_editor_app', 'Preview')
            menu_text = f"Edit in {editor_app}"
            mw.edit_with_external_editor_action.setText(menu_text)
            
            # Update enabled state - disable when more than 1 file is selected (all modes)
            if mw.current_view_mode == 'thumbnail':
                mw.edit_with_external_editor_action.setEnabled(not mw.multi_select_mode)
            elif mw.current_view_mode == 'browse':
                mw.edit_with_external_editor_action.setEnabled(not mw.multi_select_mode)
            elif mw.current_view_mode in ['slideshow', 'slideshow2', 'slideshow3']:
                mw.edit_with_external_editor_action.setEnabled(not mw.multi_select_mode)
            else:
                mw.edit_with_external_editor_action.setEnabled(False)
        
        # Update Wallpaper menu actions
        # Keep enabled in thumb/browse (and in OS fullscreen - handlers show QMessageBox when invoked)
        selected_count = len(mw.selected_files) if hasattr(mw, 'selected_files') else 0
        wallpaper_enabled = (mw.current_view_mode in ['thumbnail', 'browse']) and (selected_count <= 1)
        if hasattr(mw, 'wallpaper_last_used_action'):
            mw.wallpaper_last_used_action.setEnabled(wallpaper_enabled)
        # Zoomed-source toggle + resize: same as other wallpaper actions
        if hasattr(mw, 'wallpaper_current_display_action'):
            mw.wallpaper_current_display_action.setEnabled(wallpaper_enabled)
        if hasattr(mw, 'wallpaper_contain_action'):
            mw.wallpaper_contain_action.setEnabled(wallpaper_enabled)
        if hasattr(mw, 'wallpaper_cover_action'):
            mw.wallpaper_cover_action.setEnabled(wallpaper_enabled)
        if hasattr(mw, 'wallpaper_width_action'):
            mw.wallpaper_width_action.setEnabled(wallpaper_enabled)
        if hasattr(mw, 'wallpaper_height_action'):
            mw.wallpaper_height_action.setEnabled(wallpaper_enabled)
        if hasattr(mw, 'wallpaper_resize_window_action'):
            mw.wallpaper_resize_window_action.setEnabled(
                wallpaper_enabled and mw.current_view_mode == 'browse'
            )
        
        # Update Create Screen Size Copy submenu actions
        if hasattr(mw, 'screen_copy_menu'):
            # Enable if one or more images selected OR if there's an active image (no selection)
            has_active_image = False
            if hasattr(mw, 'get_current_image_path'):
                current_image = mw.get_current_image_path()
                has_active_image = (current_image is not None)
            should_enable = (selected_count >= 1) or (selected_count == 0 and has_active_image)
            if hasattr(mw, 'screen_copy_last_used_action'):
                mw.screen_copy_last_used_action.setEnabled(should_enable)
            if hasattr(mw, 'create_screen_copy_contain_action'):
                mw.create_screen_copy_contain_action.setEnabled(should_enable)
            if hasattr(mw, 'create_screen_copy_cover_action'):
                mw.create_screen_copy_cover_action.setEnabled(should_enable)
            if hasattr(mw, 'create_screen_copy_width_action'):
                mw.create_screen_copy_width_action.setEnabled(should_enable)
            if hasattr(mw, 'create_screen_copy_height_action'):
                mw.create_screen_copy_height_action.setEnabled(should_enable)
            mw.screen_copy_menu.setEnabled(should_enable)
        
        # Update Exclude Files action - only visible in thumbnail view and if there are checked exclude items
        if hasattr(mw, 'exclude_files_action'):
            # Check if there are any checked (enabled) exclude directories with non-blank paths
            settings = mw.config.load_settings() if hasattr(mw, 'config') else {}
            exclude_dirs = settings.get('exclude_directories', [])
            if not isinstance(exclude_dirs, list):
                exclude_dirs = []
            
            # Get checked strings (those with enabled=True and non-blank path)
            has_checked_excludes = False
            for exclude_dir in exclude_dirs:
                if isinstance(exclude_dir, dict):
                    path = exclude_dir.get('path')
                    enabled = exclude_dir.get('enabled', False)
                    if enabled and path and path.strip():
                        has_checked_excludes = True
                        break
            
            # Only show if in thumbnail view AND there are checked exclude items
            should_show = (mw.current_view_mode == 'thumbnail') and has_checked_excludes
            mw.exclude_files_action.setEnabled(should_show)
            mw.exclude_files_action.setVisible(should_show)
        
        # Update Lock/Unlock Files actions - only visible when allow_thumbnail_locking is enabled and in thumbnail or browse mode
        if hasattr(mw, 'lock_files_action') and hasattr(mw, 'unlock_files_action'):
            config = get_config()
            settings = config.load_settings()
            allow_thumbnail_locking = settings.get('allow_thumbnail_locking', False)
            is_thumbnail_or_browse_mode = (hasattr(mw, 'current_view_mode') and 
                               mw.current_view_mode in ['thumbnail', 'browse'])
            
            should_show = allow_thumbnail_locking and is_thumbnail_or_browse_mode
            
            # Lock menu item: only visible/enabled when setting is on
            mw.lock_files_action.setVisible(should_show)
            mw.lock_files_action.setEnabled(should_show)
            if should_show:
                if (getattr(mw, 'browse_image_history_action', None) is not None and
                        mw.current_view_mode == 'browse'):
                    mw.lock_files_action.setShortcut(QKeySequence())
                else:
                    mw.lock_files_action.setShortcut(QKeySequence("Ctrl+L"))
                # Update text based on selection count
                if hasattr(mw, 'selection_manager'):
                    selected_files = mw.selection_manager.get_selected_files()
                    selected_count = len(selected_files) if selected_files else 0
                    if selected_count > 1:
                        mw.lock_files_action.setText("Lock Selected Files")
                    else:
                        mw.lock_files_action.setText("Lock Selected File")
            else:
                mw.lock_files_action.setShortcut(QKeySequence())  # Clear shortcut
            
            # Unlock menu item: only visible when setting is on
            # Note: shift-cmd-L shortcut is always handled by keyboard_handler.py (works even when menu item is hidden)
            mw.unlock_files_action.setVisible(should_show)
            mw.unlock_files_action.setEnabled(should_show)
            # Keep shortcut set for display in menu (keyboard handler also handles it)
            if should_show:
                mw.unlock_files_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
                # Update text based on selection count
                if hasattr(mw, 'selection_manager'):
                    selected_files = mw.selection_manager.get_selected_files()
                    selected_count = len(selected_files) if selected_files else 0
                    if selected_count > 1:
                        mw.unlock_files_action.setText("Unlock Selected Files")
                    else:
                        mw.unlock_files_action.setText("Unlock Selected File")
            else:
                mw.unlock_files_action.setShortcut(QKeySequence())  # Clear when hidden
        
        # Update Map Location action - visible in thumbnail and browse modes
        if hasattr(mw, 'map_location_action'):
            mw.map_location_action.setEnabled(mw.current_view_mode in ['thumbnail', 'browse'])
            mw.map_location_action.setVisible(mw.current_view_mode in ['thumbnail', 'browse'])
            # Update text based on selection count
            if mw.current_view_mode in ['thumbnail', 'browse'] and hasattr(mw, 'selection_manager'):
                selected_files = mw.selection_manager.get_selected_files()
                selected_count = len(selected_files) if selected_files else 0
                if selected_count > 1:
                    mw.map_location_action.setText("Show GPS Locations on Map")
                else:
                    mw.map_location_action.setText("Show GPS Location on Map")
        
        # Update Quick Mass Rename action
        if hasattr(mw, 'quick_mass_rename_action'):
            # Check if quick mass rename is enabled in settings
            config = get_config()
            settings = config.load_settings()
            allow_quick_mass_rename = settings.get('allow_quick_mass_rename', False)
            
            # Keep action visible but grey it out (disable) if setting is off
            mw.quick_mass_rename_action.setVisible(True)
            mw.quick_mass_rename_action.setEnabled(allow_quick_mass_rename)
        
        # Update Backup/Restore Custom Sort actions
        if hasattr(mw, 'backup_custom_sort_action') and hasattr(mw, 'restore_custom_sort_action'):
            # Only show in thumbnail mode, not specific files mode
            is_thumbnail_mode = (hasattr(mw, 'current_view_mode') and 
                               mw.current_view_mode == 'thumbnail')
            is_specific_files_mode = getattr(mw, 'specific_files_active', False)
            
            # Show section only if all conditions are met
            should_show_section = (is_thumbnail_mode and 
                                 not is_specific_files_mode)
            
            if should_show_section and mw.current_directory:
                prsort_path = mw.sorting_manager._get_prsort_file_path(mw.current_directory)
                backup_path = prsort_path + '.bak'
                
                prsort_exists = os.path.exists(prsort_path)
                backup_exists = os.path.exists(backup_path)
                
                # Show backup action only if .prsort exists
                mw.backup_custom_sort_action.setVisible(prsort_exists)
                mw.backup_custom_sort_action.setEnabled(prsort_exists)
                
                # Show restore action only if .prsort.bak exists
                mw.restore_custom_sort_action.setVisible(backup_exists)
                mw.restore_custom_sort_action.setEnabled(backup_exists)
                
                # Show separator only if at least one action is visible (including Quick Mass Rename)
                # Quick Mass Rename is always visible now (shortcut needs to work), so include it
                quick_mass_rename_exists = hasattr(mw, 'quick_mass_rename_action')
                if hasattr(self, 'organization_separator_action'):
                    self.organization_separator_action.setVisible(prsort_exists or backup_exists or quick_mass_rename_exists)
            else:
                # Hide both actions if conditions not met, but Quick Mass Rename is always visible for shortcut
                mw.backup_custom_sort_action.setVisible(False)
                mw.restore_custom_sort_action.setVisible(False)
                quick_mass_rename_exists = hasattr(mw, 'quick_mass_rename_action')
                if hasattr(self, 'organization_separator_action'):
                    self.organization_separator_action.setVisible(quick_mass_rename_exists)
        
        self.update_file_menu_browse_image_history_action()
        self.update_file_menu_last_image_action()
    
    def update_file_menu_last_image_action(self):
        """File ▸ Last Image: browse only; Cmd+L swaps history [0] and [1] then shows new first."""
        mw = self.main_window
        if not hasattr(mw, 'last_image_action'):
            return
        try:
            in_browse = mw.current_view_mode == 'browse'
            mw.last_image_action.setVisible(True)
            if not in_browse:
                mw.last_image_action.setEnabled(False)
                mw.last_image_action.setShortcut(QKeySequence())
                return
            if hasattr(mw, '_prune_browse_image_history'):
                mw._prune_browse_image_history()
            hist = getattr(mw, 'browse_image_history', None) or []
            can_swap = len(hist) >= 2
            mw.last_image_action.setEnabled(can_swap)
            if not can_swap:
                mw.last_image_action.setShortcut(QKeySequence())
            else:
                mw.last_image_action.setShortcut(QKeySequence("Ctrl+L"))
                mw.last_image_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        except RuntimeError:
            pass  # C++ object may be deleted (macOS native menu bar)
    
    def update_file_menu_browse_image_history_action(self):
        """File ▸ Image History: F3 opens specific-files thumbnails of browse image history (browse or thumbnail mode; depth in thumbnail_constants)."""
        mw = self.main_window
        if not hasattr(mw, 'browse_image_history_action'):
            return
        try:
            show_history = mw.current_view_mode in ('browse', 'thumbnail')
            mw.browse_image_history_action.setVisible(show_history)
            if not show_history:
                mw.browse_image_history_action.setEnabled(False)
                mw.browse_image_history_action.setShortcut(QKeySequence())
                return
            mw.browse_image_history_action.setShortcut(QKeySequence("F3"))
            mw.browse_image_history_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            if hasattr(mw, '_prune_browse_image_history'):
                mw._prune_browse_image_history()
            hist = getattr(mw, 'browse_image_history', None) or []
            can_open = any(p and os.path.isfile(p) for p in hist)
            mw.browse_image_history_action.setEnabled(can_open)
        except RuntimeError:
            pass  # C++ object may be deleted (macOS native menu bar)
    
    def update_search_menu_states(self):
        """Update the enabled states of Search menu actions"""
        mw = self.main_window
        
        # Check if current directory is root or system volume
        current_dir = None
        if hasattr(mw, 'current_directory') and mw.current_directory:
            current_dir = mw.current_directory
        elif hasattr(mw, 'displayed_images') and mw.displayed_images:
            current_dir = os.path.dirname(mw.displayed_images[0])
        
        is_restricted = current_dir and is_root_or_system_volume(current_dir)
        
        # Update Find Exact Duplicates actions
        if hasattr(mw, 'find_duplicates_action'):
            # Enable in thumbnail mode
            mw.find_duplicates_action.setEnabled(mw.current_view_mode == 'thumbnail')
        
        if hasattr(mw, 'find_duplicates_recursive_action'):
            # Enable in thumbnail mode, but disable if on root/system volume
            mw.find_duplicates_recursive_action.setEnabled(
                mw.current_view_mode == 'thumbnail' and not is_restricted
            )

        if hasattr(mw, 'find_similar_image_files_action'):
            mw.find_similar_image_files_action.setEnabled(mw.current_view_mode == 'thumbnail')

        if hasattr(mw, 'find_similar_image_files_recursive_action'):
            mw.find_similar_image_files_recursive_action.setEnabled(
                mw.current_view_mode == 'thumbnail' and not is_restricted
            )

        # Update Find Similar Images action
        if hasattr(mw, 'reorder_by_similarity_action'):
            # Enable in thumbnail, browse, and list modes
            mw.reorder_by_similarity_action.setEnabled(mw.current_view_mode in ['thumbnail', 'browse', 'list'])
        
        # Update Search by Description action
        if hasattr(mw, 'clip_search_action'):
            # Enable in thumbnail, browse, and list modes
            mw.clip_search_action.setEnabled(mw.current_view_mode in ['thumbnail', 'browse', 'list'])

        # Update Search by person action
        if hasattr(mw, 'search_by_person_action'):
            mw.search_by_person_action.setEnabled(mw.current_view_mode in ['thumbnail', 'browse', 'list'])

        # Quick Person Search: thumbnail and browse only; 1–4 deduped selected images, face engine
        if hasattr(mw, 'quick_person_search_action'):
            try:
                from faces.face_engine import is_available as face_available
                face_ok_qp = face_available()
            except ImportError:
                face_ok_qp = False
            qp_paths = get_deduped_selected_image_paths(mw)
            nqp = len(qp_paths)
            path_ok_qp = 1 <= nqp <= MAX_QUICK_PERSON_IMAGES
            mw.quick_person_search_action.setEnabled(
                mw.current_view_mode in ['thumbnail', 'browse'] and face_ok_qp and path_ok_qp
            )

        # Extract faces: visible only when exactly one logical selection; enabled when face engine + path ok
        if hasattr(mw, 'debug_extract_faces_action'):
            try:
                from faces.face_engine import is_available as face_available
                face_ok_dbg = face_available()
            except ImportError:
                face_ok_dbg = False
            dbg_paths = []
            if hasattr(mw, 'selection_manager') and mw.selection_manager:
                dbg_paths = mw.selection_manager.get_selected_files()
            one_image = len(dbg_paths) == 1
            path_ok_dbg = one_image and dbg_paths[0] and os.path.exists(dbg_paths[0])
            mw.debug_extract_faces_action.setVisible(one_image)
            mw.debug_extract_faces_action.setEnabled(face_ok_dbg and path_ok_dbg)
        
        # Update Show image in directory action
        if hasattr(mw, 'show_image_in_directory_action'):
            # Visible when specific files mode is active in Browse and thumbnail modes
            is_specific_files_mode = getattr(mw, 'specific_files_active', False)
            is_browse_or_thumbnail = mw.current_view_mode in ['browse', 'thumbnail']
            has_current_image = bool(hasattr(mw, 'current_image_path') and mw.current_image_path)
            should_show = bool(is_specific_files_mode and is_browse_or_thumbnail and has_current_image)
            mw.show_image_in_directory_action.setVisible(should_show)
            mw.show_image_in_directory_action.setEnabled(should_show)

    def update_view_menu_enabled_states(self):
        """Update enabled states and text for view menu actions based on current view mode"""
        mw = self.main_window
        
        # Update Information sidebar action (available in both modes, but hidden during slideshow)
        if hasattr(mw, 'toggle_information_sidebar_action'):
            try:
                if mw.current_view_mode in ['slideshow', 'slideshow2', 'slideshow3']:
                    mw.toggle_information_sidebar_action.setVisible(False)
                else:
                    mw.toggle_information_sidebar_action.setEnabled(True)  # Available in both modes
                    mw.toggle_information_sidebar_action.setVisible(True)  # Visible in thumbnail and browse modes
                    info_visible = (mw.right_sidebar.is_information_visible()
                                   if hasattr(mw, 'right_sidebar') and mw.right_sidebar else False)
                    mw.toggle_information_sidebar_action.setChecked(info_visible)
                    mw.toggle_information_sidebar_action.setText(
                        'Hide Information Sidebar' if info_visible else 'Show Information Sidebar')
            except RuntimeError:
                pass  # C++ object may be deleted (macOS native menu bar)

        # Update Shortcuts sidebar action (within right_sidebar)
        if hasattr(mw, 'toggle_shortcuts_sidebar_action'):
            try:
                if mw.current_view_mode in ['slideshow', 'slideshow2', 'slideshow3']:
                    mw.toggle_shortcuts_sidebar_action.setVisible(False)
                else:
                    mw.toggle_shortcuts_sidebar_action.setEnabled(True)
                    mw.toggle_shortcuts_sidebar_action.setVisible(True)
                    shortcuts_visible = False
                    if hasattr(mw, 'right_sidebar') and hasattr(mw.right_sidebar, 'is_shortcuts_visible'):
                        shortcuts_visible = mw.right_sidebar.is_shortcuts_visible()
                    mw.toggle_shortcuts_sidebar_action.setChecked(shortcuts_visible)
                    mw.toggle_shortcuts_sidebar_action.setText('Hide Organize Sidebar' if shortcuts_visible else 'Show Organize Sidebar')
            except RuntimeError:
                pass  # C++ object may be deleted (macOS native menu bar)
        
        def check_action(action_name: str, setting: bool, obj=None):
            """Check action stored on obj (defaults to main_window/mw)"""
            target = obj if obj is not None else mw
            if hasattr(target, action_name):
                action = getattr(target, action_name)
                try:
                    action.setVisible(setting)
                    action.setEnabled(setting)
                except RuntimeError:
                    # C++ object may be deleted (macOS native menu bar can invalidate actions)
                    pass
        
        # Update macOS OS fullscreen checkbox state
        self.update_macos_display_mode_menu()
        
        # Update browse view action text based on current view mode
        if hasattr(mw, 'browse_view_action'):
            try:
                if mw.current_view_mode == 'browse':
                    mw.browse_view_action.setText("Leave Image Viewer")
                else:
                    mw.browse_view_action.setText("Enter Image Viewer")
            except RuntimeError:
                pass  # C++ object may be deleted (macOS native menu bar)
        
        # Update list view action checked state and text based on current view mode
        if hasattr(mw, 'list_view_action'):
            try:
                is_list_view = mw.current_view_mode == 'list'
                mw.list_view_action.setChecked(is_list_view)
                mw.list_view_action.setText("Hide List View" if is_list_view else "Show List View")
            except RuntimeError:
                pass  # C++ object may be deleted (macOS native menu bar)
        
        # Update thumbnail control separator text based on view mode
        if hasattr(mw, 'thumbnail_control_separator_action'):
            try:
                widget = mw.thumbnail_control_separator_action.defaultWidget()
            except RuntimeError:
                widget = None  # C++ object may be deleted (macOS native menu bar)
            if widget:
                # Find the LineWithText widget inside TextSeparator
                for child in widget.findChildren(QWidget):
                    if isinstance(child, LineWithText):
                        if mw.current_view_mode == 'thumbnail':
                            child.text = "Thumbnail Control"
                        else:  # browse mode or slideshows
                            child.text = "Browse Control"
                        child.update()
                        break
        
        # New logic: All available actions are represented in each section.
        # Slideshows show only minimal actions to exit or navigate away.
        menu_actions = [
            'toggle_file_tree_action',
            'toggle_preview_action',
            'toggle_jobs_action',
            'toggle_chat_action',
            'toggle_status_bar_action',
            'browse_view_action',
            'macos_display_mode_action',
            'toggle_filename_action',
            'actual_size_action',
            'size_sort_action',
            'sort_menu_action',
            'wallpaper_menu_action',
            'map_location_action',
            'quick_mass_rename_action',
            'backup_custom_sort_action',
            'restore_custom_sort_action',
            'exclude_files_action',
            'lock_files_action',
            'unlock_files_action',
            'edit_with_external_editor_action',
            'prepopulate_cache_action',
            'show_rename_status_action',
            'rename_with_custom_prefix_action',
            'copy_path_action',
            'copy_image_action',
            'copy_user_comment_action',
        ]

        # Define each mode's menu config: True = enabled, False = disabled
        menu_mode_config = {
            'thumbnail': {
                'toggle_file_tree_action': True,
                'toggle_preview_action': True,
                'toggle_jobs_action': True,
                'toggle_chat_action': True,
                'toggle_status_bar_action': True,
                'browse_view_action': True,
                'macos_display_mode_action': True,
                'toggle_filename_action': True,
                'actual_size_action': False,
                'size_sort_action': True,
                'sort_menu_action': True,
                'wallpaper_menu_action': True,
                'map_location_action': True,
                'quick_mass_rename_action': True,
                'backup_custom_sort_action': True,
                'restore_custom_sort_action': True,
                'exclude_files_action': True,
                'lock_files_action': True,
                'unlock_files_action': True,
                'edit_with_external_editor_action': True,
                'prepopulate_cache_action': True,
                'show_rename_status_action': True,
                'rename_with_custom_prefix_action': True,
                'copy_path_action': True,
                'copy_image_action': True,
                'copy_user_comment_action': True,
            },
            'browse': {
                'toggle_file_tree_action': False,
                'toggle_preview_action': False,
                'toggle_jobs_action': True,
                'toggle_chat_action': True,
                'toggle_status_bar_action': True,
                'browse_view_action': True,
                'macos_display_mode_action': True,
                'toggle_filename_action': False,
                'actual_size_action': True,
                'size_sort_action': True,
                'sort_menu_action': True,
                'wallpaper_menu_action': True,
                'map_location_action': True,
                'quick_mass_rename_action': True,
                'backup_custom_sort_action': True,
                'restore_custom_sort_action': True,
                'exclude_files_action': True,
                'lock_files_action': True,
                'unlock_files_action': True,
                'edit_with_external_editor_action': True,
                'prepopulate_cache_action': True,
                'show_rename_status_action': False,
                'rename_with_custom_prefix_action': False,
                'copy_path_action': True,
                'copy_image_action': True,
                'copy_user_comment_action': True,
            },
            # Slideshows: Only actions to exit/viewer/navigation are enabled
            'slideshow': {
                'toggle_file_tree_action': False,
                'toggle_preview_action': False,
                'toggle_jobs_action': False,
                'toggle_chat_action': True,
                'toggle_status_bar_action': False,
                'browse_view_action': True,
                'macos_display_mode_action': True,
                'toggle_filename_action': False,
                'actual_size_action': False,
                'size_sort_action': False,
                'sort_menu_action': True, # maybe can sort
                'wallpaper_menu_action': False,
                'map_location_action': False,
                'quick_mass_rename_action': False,
                'backup_custom_sort_action': False,
                'restore_custom_sort_action': False,
                'exclude_files_action': False,
                'lock_files_action': False,
                'unlock_files_action': False,
                'edit_with_external_editor_action': False,
                'prepopulate_cache_action': False,
                'show_rename_status_action': False,
                'rename_with_custom_prefix_action': False,
                'copy_path_action': False,
                'copy_image_action': False,
                'copy_user_comment_action': False,
            },
            'slideshow2': {
                'toggle_file_tree_action': False,
                'toggle_preview_action': False,
                'toggle_jobs_action': False,
                'toggle_chat_action': True,
                'toggle_status_bar_action': False,
                'browse_view_action': True,
                'macos_display_mode_action': True,
                'toggle_filename_action': False,
                'actual_size_action': False,
                'size_sort_action': False,
                'sort_menu_action': True,
                'wallpaper_menu_action': False,
                'map_location_action': False,
                'quick_mass_rename_action': False,
                'backup_custom_sort_action': False,
                'restore_custom_sort_action': False,
                'exclude_files_action': False,
                'lock_files_action': False,
                'unlock_files_action': False,
                'edit_with_external_editor_action': False,
                'prepopulate_cache_action': False,
                'show_rename_status_action': False,
                'rename_with_custom_prefix_action': False,
                'copy_path_action': False,
                'copy_image_action': False,
                'copy_user_comment_action': False,
            },
            'slideshow3': {
                'toggle_file_tree_action': False,
                'toggle_preview_action': False,
                'toggle_jobs_action': False,
                'toggle_chat_action': True,
                'toggle_status_bar_action': False,
                'browse_view_action': True,
                'macos_display_mode_action': True,
                'toggle_filename_action': False,
                'actual_size_action': False,
                'size_sort_action': False,
                'sort_menu_action': True,
                'wallpaper_menu_action': False,
                'map_location_action': False,
                'quick_mass_rename_action': False,
                'backup_custom_sort_action': False,
                'restore_custom_sort_action': False,
                'exclude_files_action': False,
                'lock_files_action': False,
                'unlock_files_action': False,
                'edit_with_external_editor_action': False,
                'prepopulate_cache_action': False,
                'show_rename_status_action': False,
                'rename_with_custom_prefix_action': False,
                'copy_path_action': False,
                'copy_image_action': False,
                'copy_user_comment_action': False,
            },
            'list': {
                'toggle_file_tree_action': True,  # Enable T key to toggle tree
                'toggle_preview_action': True,  # Enable P key to toggle preview
                'toggle_jobs_action': True,  # Enable J key to toggle jobs pane
                'toggle_chat_action': True,  # Enable F9 to toggle chat pane
                'toggle_status_bar_action': True,
                'browse_view_action': True,
                'macos_display_mode_action': True,
                'toggle_filename_action': True,  # Enable I key to toggle Information sidebar
                'actual_size_action': False,
                'size_sort_action': True,
                'sort_menu_action': True,
                'wallpaper_menu_action': True,
                'map_location_action': True,
                'quick_mass_rename_action': True,
                'backup_custom_sort_action': True,
                'restore_custom_sort_action': True,
                'exclude_files_action': True,
                'lock_files_action': True,
                'unlock_files_action': True,
                'edit_with_external_editor_action': True,
                'prepopulate_cache_action': True,
                'show_rename_status_action': True,
                'rename_with_custom_prefix_action': True,
                'copy_path_action': True,
                'copy_image_action': True,
                'copy_user_comment_action': True,
            }
        }

        current_mode = str(mw.current_view_mode)
        config = menu_mode_config.get(current_mode)
        if config is None:
            # Bad mode: disable all and print error/info
            from thumbnails.thumbnail_constants import GREEN, RESET, RED
            print(f"{GREEN}INTERNAL ERROR {RESET}: {RED}update_view_menu_enabled_states{RESET} : Bad view mode: {mw.current_view_mode}")
            for act in menu_actions:
                if act == 'sort_menu_action':
                    check_action(act, False, obj=self)
                else:
                    check_action(act, False)
            show_styled_information(
                self.main_window,
                "Debug Information",
                f"update_view_menu_enabled_states: invalid state.\ncurrent_view_mode: {mw.current_view_mode}",
            )
        else:
            for act in menu_actions:
                setting = config[act]
                if act == 'sort_menu_action':
                    check_action(act, setting, obj=self)
                else:
                    check_action(act, setting)

        # Shortcuts and extra state per mode
        # Always set F shortcut on browse_view_action if available
        if hasattr(mw, 'browse_view_action'):
            try:
                mw.browse_view_action.setShortcut(QKeySequence("F"))
            except RuntimeError:
                pass  # C++ object may be deleted (macOS native menu bar)
        # If in browse, update actual_size_action check state
        if mw.current_view_mode == 'browse' and hasattr(mw, 'actual_size_action'):
            try:
                mw.actual_size_action.setChecked(mw.is_actual_size)
            except RuntimeError:
                pass  # C++ object may be deleted (macOS native menu bar)
        # Fix: Only update the parent menu if it exists and is not deleted
        action = getattr(mw, 'toggle_status_bar_action', None)
        if action is not None:
            parent_menu = action.parent()
            # Defensive: parent_menu may be None or deleted
            if parent_menu is not None:
                try:
                    parent_menu.update()
                except RuntimeError:
                    pass

    def update_file_menu_favorites(self):
        """
        Update the File menu's Favorites submenu.
        Populates favorites from settings and adds Ctrl-number shortcuts.
        Assumes the File menu is always present and valid.
        """
        mw = self.main_window
        favorites_menu = self.favorites_menu
        if favorites_menu is None:
            return

        # Defensive: check if favorites_menu is deleted before accessing actions
        # DO NOT DELETE: On macOS, when a modal settings dialog closes, the native menu bar
        # can be recreated; self.favorites_menu may reference a deleted menu. Both
        # RuntimeError and ReferenceError indicate a stale reference - we must recreate
        # the Favorites submenu instead of returning, or the menu/shortcuts stay stale.
        try:
            actions = favorites_menu.actions()
        except (RuntimeError, ReferenceError):
            # Menu was deleted (e.g. by macOS native menu bar when modal dialog closed).
            # Recreate the Favorites submenu and update our reference.
            # DO NOT DELETE: self.file_menu can also be stale when macOS recreates the menu bar.
            # Get a fresh File menu from the menubar - menubar.actions() returns current menus.
            file_menu = self.file_menu
            try:
                file_actions = file_menu.actions() if file_menu else None
            except (RuntimeError, ReferenceError):
                file_actions = None
            if file_menu is None or file_actions is None:
                # Try to get fresh File menu from menubar
                try:
                    menubar = mw.menuBar()
                    mb_actions = list(menubar.actions())  # snapshot to avoid iteration over modified container
                    found_file = False
                    for action in mb_actions:
                        try:
                            submenu = action.menu() if hasattr(action, "menu") else None
                            t = submenu.title() if submenu else None
                            if submenu and t == "File":
                                file_actions = list(submenu.actions())
                                file_menu = submenu
                                self.file_menu = submenu
                                found_file = True
                                break
                        except (RuntimeError, ReferenceError):
                            continue
                    if not found_file:
                        file_menu = None
                        file_actions = None
                except (RuntimeError, ReferenceError):
                    pass
            if file_menu is None or file_actions is None:
                return
            # Remove stale Favorites action (the one whose menu was deleted)
            for action in list(file_actions):
                try:
                    menu = action.menu() if hasattr(action, "menu") else None
                    if menu and hasattr(menu, "title") and menu.title() == "Favorites":
                        file_menu.removeAction(action)
                        break
                except (RuntimeError, ReferenceError):
                    file_menu.removeAction(action)
                    break
            # Add new Favorites submenu before Exit
            exit_action = None
            file_menu_actions = list(file_menu.actions())  # snapshot to avoid iteration over modified container
            for action in file_menu_actions:
                if getattr(action, "menuRole", lambda: None)() == QAction.MenuRole.QuitRole:
                    exit_action = action
                    break
            # Validate file_menu before using as parent (may be deleted by macOS menu bar)
            try:
                _ = file_menu.title()
            except (RuntimeError, ReferenceError):
                return
            new_favorites = QMenu("Favorites", file_menu)
            if exit_action:
                file_menu.insertMenu(exit_action, new_favorites)
            else:
                file_menu.addMenu(new_favorites)
            self.favorites_menu = new_favorites
            favorites_menu = new_favorites

        # Clear all existing actions
        favorites_menu.clear()

        # Get favorites from config
        config = mw.config
        settings = config.load_settings()
        favorites = settings.get('favorite_directories', [None] * 9)

        # Ensure we have exactly 9 items
        favorites = (favorites + [None] * 9)[:9]

        # Store favorite actions for shortcut management
        if not hasattr(self, 'favorite_actions'):
            self.favorite_actions = []

        # Clear existing actions list
        self.favorite_actions.clear()

        # Add menu items for each favorite (1-9)
        for i, favorite_path in enumerate(favorites):
            favorite_index = i + 1  # 1-9 for display and shortcuts
            
            if favorite_path and os.path.exists(favorite_path):
                # Create display name
                if os.path.isdir(favorite_path):
                    display_name = os.path.basename(favorite_path.rstrip('/'))
                else:
                    display_name = os.path.basename(favorite_path)
                
                # Create action with Control-number shortcut (MetaModifier on macOS)
                # On macOS: Qt.ControlModifier = Cmd (⌘), Qt.MetaModifier = Control (⌃)
                # Move menu uses Ctrl+number which maps to Cmd+number
                # Favorites use MetaModifier+number which is actual Control+number
                action = QAction(f"{favorite_index}. {display_name}", favorites_menu)
                # Create QKeySequence with MetaModifier (Control key on macOS)
                key_map = {
                    1: Qt.Key_1, 2: Qt.Key_2, 3: Qt.Key_3, 4: Qt.Key_4, 5: Qt.Key_5,
                    6: Qt.Key_6, 7: Qt.Key_7, 8: Qt.Key_8, 9: Qt.Key_9
                }
                key_sequence = QKeySequence(key_map[favorite_index] | Qt.MetaModifier)
                action.setShortcut(key_sequence)
                action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
                
                # Connect to handler that opens directory or file
                def create_handler(path):
                    def handler():
                        if os.path.isdir(path):
                            mw.open_directory(path)
                        else:
                            # Open file: load directory and highlight file (same pattern as open_file_dialog)
                            directory = os.path.dirname(path)
                            mw.load_directory(directory, external_load=True)
                            # Highlight the selected file in the loaded directory
                            if path in mw.displayed_images:
                                # Use configuration to control highlight and view mode
                                configuration = {
                                    'files': [path],
                                    'directory': directory,
                                    'highlight_file': path,
                                }
                                mw.refresh_from_configuration(configuration)
                            # Update file tree root when opening file
                            if mw.file_tree_handler.is_tree_initialized():
                                mw.file_tree_handler.update_root_directory(directory)
                    return handler
                
                action.triggered.connect(create_handler(favorite_path))
                favorites_menu.addAction(action)
                self.favorite_actions.append(action)
            else:
                # Add disabled placeholder for empty slots
                action = QAction(f"{favorite_index}. (empty)", favorites_menu)
                action.setEnabled(False)
                favorites_menu.addAction(action)
                self.favorite_actions.append(None)
        
        # Add separator and Edit action
        favorites_menu.addSeparator()
        edit_action = QAction("Edit Favorites...", favorites_menu)
        edit_action.setIcon(create_gear_icon("#808890"))
        edit_action.triggered.connect(lambda: mw.show_settings(tab_id="favorites"))
        favorites_menu.addAction(edit_action)

    def update_file_menu_recent_directories(self):
        """
        Update the File menu's Recent Directories submenu.
        Updates self.recent_menu in place when valid; recreates only when stale.
        """
        mw = self.main_window

        recent_dirs_raw = mw.directory_history_handler_for_menu.directory_history
        filtered_recent_dirs = [
            d
            for d in reversed(recent_dirs_raw)
            if (
                d != mw.TMP_TRASHES_DIR and
                os.path.exists(d)
            )
        ]

        def _populate_recent_menu(menu):
            menu.clear()
            if filtered_recent_dirs:
                for d in filtered_recent_dirs:
                    act = QAction(normalize_path_for_display(d), menu)
                    act.triggered.connect(lambda checked, dirpath=d: mw.open_directory(dirpath))
                    menu.addAction(act)
                menu.addSeparator()
            else:
                ph = QAction("No Recent Directories", menu)
                ph.setEnabled(False)
                menu.addAction(ph)
            clear_action = QAction("Clear History", menu)
            def clear_history():
                mw.directory_history_handler_for_menu.clear_history()
                self.update_file_menu_recent_directories()
            clear_action.triggered.connect(clear_history)
            # Keep enabled even when empty so submenu is visible on macOS (Cocoa hides submenus with all items disabled)
            clear_action.setEnabled(True)
            menu.addAction(clear_action)

        # Try to update self.recent_menu in place (avoids remove/add which can fail on macOS)
        try:
            if getattr(self, 'recent_menu', None) is not None:
                _populate_recent_menu(self.recent_menu)
                return
        except (RuntimeError, ReferenceError):
            pass

        # Fallback: recreate Recent submenu (menu was stale)
        file_menu = self.file_menu
        try:
            actions = list(file_menu.actions()) if file_menu else None
        except (RuntimeError, ReferenceError):
            actions = None
        if file_menu is None or actions is None:
            try:
                menubar = mw.menuBar()
                mb_actions = list(menubar.actions())  # snapshot to avoid iteration over modified container
                for action in mb_actions:
                    try:
                        submenu = action.menu() if hasattr(action, "menu") else None
                        if submenu and submenu.title() == "File":
                            file_menu = submenu
                            self.file_menu = submenu
                            actions = list(submenu.actions())
                            break
                    except (RuntimeError, ReferenceError):
                        continue
            except (RuntimeError, ReferenceError):
                return
        if file_menu is None or actions is None:
            return
        for action in list(actions):
            try:
                menu = action.menu() if hasattr(action, "menu") else None
                if menu and hasattr(menu, "title") and menu.title().startswith("Recent"):
                    file_menu.removeAction(action)
                    break
            except (RuntimeError, ReferenceError):
                continue
        # Validate file_menu before using as parent (may be deleted by macOS menu bar)
        try:
            _ = file_menu.title()
        except (RuntimeError, ReferenceError):
            return
        recent_menu = QMenu("Recent...", file_menu)
        _populate_recent_menu(recent_menu)
        self.recent_menu = recent_menu
        favorites_action = None
        file_actions_snapshot = list(file_menu.actions())  # snapshot to avoid iteration over modified container
        for action in file_actions_snapshot:
            try:
                menu = action.menu() if hasattr(action, "menu") else None
                if menu and hasattr(menu, "title") and menu.title() == "Favorites":
                    favorites_action = action
                    break
            except (RuntimeError, ReferenceError):
                continue
        if favorites_action:
            file_menu.insertMenu(favorites_action, recent_menu)
        else:
            file_menu.addMenu(recent_menu)

    def update_sort_menu_checkmarks(self):
        """Update the checkmarks on sort menu items based on current sort state"""
        mw = self.main_window
        if hasattr(mw, 'random_action'):
            mw.random_action.setChecked(mw.current_sort_mode.value == 'random')
        
        # Name sort actions
        if hasattr(mw, 'name_sort_action'):
            mw.name_sort_action.setChecked(mw.current_sort_mode.value == 'name' and not mw.is_reversed)
        if hasattr(mw, 'name_sort_reverse_action'):
            mw.name_sort_reverse_action.setChecked(mw.current_sort_mode.value == 'name' and mw.is_reversed)
        
        # Date sort actions
        if hasattr(mw, 'date_sort_action'):
            mw.date_sort_action.setChecked(mw.current_sort_mode.value == 'date' and not mw.is_reversed)
        if hasattr(mw, 'date_sort_newest_action'):
            mw.date_sort_newest_action.setChecked(mw.current_sort_mode.value == 'date' and mw.is_reversed)

        # EXIF Date sort actions
        if hasattr(mw, 'exif_date_sort_action'):
            mw.exif_date_sort_action.setChecked(mw.current_sort_mode.value == 'exif_date' and not mw.is_reversed)
        if hasattr(mw, 'exif_date_sort_reverse_action'):
            mw.exif_date_sort_reverse_action.setChecked(mw.current_sort_mode.value == 'exif_date' and mw.is_reversed)

        # Year sort actions
        if hasattr(mw, 'exif_year_sort_action'):
            mw.exif_year_sort_action.setChecked(mw.current_sort_mode.value == 'exif_year' and not mw.is_reversed)
        if hasattr(mw, 'exif_year_sort_reverse_action'):
            mw.exif_year_sort_reverse_action.setChecked(mw.current_sort_mode.value == 'exif_year' and mw.is_reversed)

        
        # Size sort actions
        if hasattr(mw, 'size_sort_action'):
            mw.size_sort_action.setChecked(mw.current_sort_mode.value == 'size' and not mw.is_reversed)
        if hasattr(mw, 'size_sort_reverse_action'):
            mw.size_sort_reverse_action.setChecked(mw.current_sort_mode.value == 'size' and mw.is_reversed)
        
        if hasattr(mw, 'custom_sort_action'):
            mw.custom_sort_action.setChecked(mw.current_sort_mode.value == 'custom')

    def update_filename_menu_text(self):
        """Update the filename toggle menu text and enabled state"""
        mw = self.main_window
        if hasattr(mw, 'toggle_filename_action'):
            # Update text based on current state (cycling through 4 states)
            current_filename = getattr(mw, 'thumbnail_filename_visible', False)
            current_size = getattr(mw, 'show_image_size', False)
            
            if not current_filename and not current_size:
                mw.toggle_filename_action.setText("Show File Names")
            elif current_filename and not current_size:
                mw.toggle_filename_action.setText("Show Image Size")
            elif not current_filename and current_size:
                mw.toggle_filename_action.setText("Show Name and Size")
            else:  # both True
                mw.toggle_filename_action.setText("Hide Name and Size")
            
            # Enable/disable based on current view mode
            is_thumbnail_view = (hasattr(mw, 'current_view_mode') and 
                               mw.current_view_mode == 'thumbnail')
            mw.toggle_filename_action.setEnabled(is_thumbnail_view)
            # Set checked if either is visible
            mw.toggle_filename_action.setChecked(current_filename or current_size)

    def update_file_menu_can_view_trash(self):
        """Update the File menu to show/hide the Trash action based on whether trash images can be viewed"""
        mw = self.main_window
        # Find the "Trash" action dynamically by its text
        trash_action = None
        try:
            file_actions = list(self.file_menu.actions())  # snapshot to avoid iteration over modified container
            for action in file_actions:
                if action.text().replace('&','').startswith("View Copy of Trash"):
                    trash_action = action
                    break
        except (RuntimeError, ReferenceError):
            return
        if trash_action is None:
            return
        
        # Check all trash directories (user's home + volume-specific) for readable images
        from files.file_operations_manager import FileOperationsManager
        can_view_trash = FileOperationsManager._has_readable_trash_with_images()
        trash_action.setEnabled(can_view_trash)
    
    def update_file_menu_delete_action(self):
        mw = self.main_window
        if hasattr(mw, 'delete_action') and hasattr(mw, 'selection_manager'):
            selected_files = mw.selection_manager.get_selected_files()
            selected_count = len(selected_files) if selected_files else 0
            
            # Check if delete confirmation is enabled
            confirm_delete = getattr(mw, 'confirm_delete', True)
            ellipsis = "..." if confirm_delete else ""
            
            if selected_count > 1:
                mw.delete_action.setText(f"Delete Files{ellipsis}")
            else:
                mw.delete_action.setText(f"Delete File{ellipsis}")
    
    def update_sidebar_menu_actions_for_view_mode(self, view_mode):
        """Update sidebar menu actions enabled state based on view mode"""
        mw = self.main_window
        # T / P / J / F4 shortcuts are QAction-based; they only fire when the actions are enabled.
        # Tree/preview toggles are thumbnail/list only; chat (F9) is also available in browse.
        show_tree_preview_toggles = view_mode in ('thumbnail', 'list')
        show_jobs_toggle = view_mode in ('thumbnail', 'list', 'browse')
        try:
            from bundle_capabilities import model_jobs_ui_enabled

            if not model_jobs_ui_enabled():
                show_jobs_toggle = False
        except ImportError:
            pass
        
        # Enable/disable and show/hide file tree action
        if hasattr(mw, 'toggle_file_tree_action'):
            mw.toggle_file_tree_action.setEnabled(show_tree_preview_toggles)
            mw.toggle_file_tree_action.setVisible(show_tree_preview_toggles)
        
        # Enable/disable and show/hide preview action
        if hasattr(mw, 'toggle_preview_action'):
            mw.toggle_preview_action.setEnabled(show_tree_preview_toggles)
            mw.toggle_preview_action.setVisible(show_tree_preview_toggles)
        if hasattr(mw, 'toggle_jobs_action'):
            mw.toggle_jobs_action.setEnabled(show_jobs_toggle)
            mw.toggle_jobs_action.setVisible(show_jobs_toggle)
        show_chat_toggle = True
        try:
            from bundle_capabilities import chat_ui_enabled

            if not chat_ui_enabled():
                show_chat_toggle = False
        except ImportError:
            pass
        if hasattr(mw, 'toggle_chat_action'):
            mw.toggle_chat_action.setEnabled(show_chat_toggle)
            mw.toggle_chat_action.setVisible(show_chat_toggle)