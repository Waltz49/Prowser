#!/usr/bin/env python3
# for review
"""
Main Image Browser Window - Optimized Version
Complete implementation of all web-based features with single-window design

This is a clean rewrite that eliminates code duplication and unused code
while preserving ALL functionality exactly as the original.
"""
# Standard library
import fnmatch
import html
import inspect
import os
import re
import shutil
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Third-party
from PIL import Image

# Register HEIF opener for HEIC/HEIF support (idempotent; shared with pil_image_io / CNN / workers)
from pil_image_io import register_heif_opener

register_heif_opener()

MACOS_FULLSCREEN_AVAILABLE = True

# PySide6
from PySide6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QMutexLocker, QObject, QPoint, QPointF,
    QPropertyAnimation, QSize, Qt, QThread, QTimer, Signal, Slot
)
from PySide6.QtGui import (
    QColor, QCursor, QDrag, QFont, QGuiApplication, QImage, QKeyEvent, QKeySequence, QPainter,
    QPixmap, QResizeEvent, QTransform
)
from PySide6.QtWidgets import (
    QApplication, QGestureEvent, QInputDialog, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QProgressDialog, QSplitter, QStackedWidget, QStatusBar, QStyle, QVBoxLayout, QWidget
)

# AppKit imports for file operations - will be imported lazily when needed
_NSWorkspace = None
_NSUndoManager = None
_NSObject = None
_NSWorkspaceRecycleOperation = None

def _import_appkit_modules():
    """Lazily import AppKit modules when needed"""
    global _NSWorkspace, _NSUndoManager, _NSObject, _NSWorkspaceRecycleOperation
    
    if _NSWorkspace is None:
        try:
            from AppKit import NSWorkspace, NSUndoManager, NSObject, NSWorkspaceRecycleOperation
            _NSWorkspace = NSWorkspace
            _NSUndoManager = NSUndoManager
            _NSObject = NSObject
            _NSWorkspaceRecycleOperation = NSWorkspaceRecycleOperation
        except ImportError:
            pass

# Local
from about_dialog import AboutDialog
from beachball_fix import safe_refresh_wrapper, safe_thumbnail_wrapper
from browse_view_handler import BrowseViewHandler
from combined_sidebar_widget import CombinedSidebarWidget
from config import (
    ImageBrowserConfig,
    effective_browse_border_color,
    effective_browse_transparency,
    get_config,
)
from configuration_sync_manager import ConfigurationSyncManager
from delete_exif_dialog import DeleteExifDialog
from directory_history_handler import DirectoryHistoryHandler, DirectoryHistoryHandlerForMenu
from directory_loader import DirectoryLoader
from event_handler import EventHandler
from exif_image_loader import (
    get_image_dimensions_fast_metadata,
    get_image_dimensions_and_exif_date,
    load_image_with_exif_correction,
)
from exif_utils import get_exif_bytes_from_pil_raw, get_exif_dict_from_pil
from file_move_handler import FileMoveHandler
from file_operations_manager import FileOperationsManager
from file_tree_handler import FileTreeHandler
from help_api import APIDocumentationDialog
from help_command_line import CommandLineHelpDialog
from help_dialog import HelpDialog
from help_downloading_models import DownloadingAIModelsHelpDialog
from help_pf import PFKeysHelpDialog
from help_why import WhyWasThisWrittenDialog
from image_cache import cleanup_cache, get_cache_manager
from image_display_manager import ImageDisplayManager
from keyboard_handler import KeyboardHandlerManager
from lock_manager import LockManager
from menu_manager import MenuManager
from message_handler import MessageHandler
from navigation_manager import NavigationManager
from path_exclusions import _get_excluded_paths, _is_excluded_path
from preview_widget import PreviewWidget
from qt_key_debug import log_key_event, set_popup_callback
from refresh_manager import RefreshManager
from reset_date_dialog import ResetDateDialog
from reset_exif_dialog import ResetExifDialog
from right_sidebar_combined import RightSidebarCombinedWidget
from selection_manager import SelectionManager
from settings_dialog import SettingsDialog
from sidebar_manager import SidebarManager
from similarity_bootstrap import _import_cnn_modules
from similarity_search_manager import SimilaritySearchManager
from slideshow2_manager import Slideshow2Manager
from slideshow3_manager import Slideshow3Manager
from slideshow_manager import SlideshowManager
from sort_mode import SortMode
from sorting_manager import SortingManager
from status_bar_config import StatusBarManager
from status_notification import StatusNotification
from thumbnail_canvas import create_message_pixmap
from thumbnail_constants import (
    BASE_MARGIN,
    BORDER_SPACE,
    BROWSE_IMAGE_HISTORY_MAX,
    GREEN,
    MAX_THUMBNAIL_SIZE,
    MIN_THUMBNAIL_SIZE,
    RED,
    RESET,
    THUMBNAIL_SPACING,
    TREE_HEADER_FOCUS_BG_HEX,
    clear_image_extensions_cache,
    get_image_extensions,
)
from thumbnail_display_manager import ThumbnailDisplayManager
from thumbnail_operations_manager import ThumbnailOperationsManager
from thumbnail_context_menu import ThumbnailContextMenuHandler

from ui_layout_manager import UILayoutManager
from utils import (
    file_string,
    handle_filter_pattern_mismatch,
    is_macos_spaces_fullscreen,
    normalize_path_for_display,
    show_styled_critical,
    show_styled_information,
    show_styled_question,
    show_styled_warning,
)
from theme_service import get_active_theme
from view_manager import ViewManager
from view_mode_manager import ViewModeManager
from wallpaper_manager import WallpaperManager
from window_background_workers import (
    PersonFaceMatchWorker,
    PersonSearchPrepWorker,
    ThumbnailLoadingWorker,
)
from window_event_filters import ChromeToggleShortcutFilter, ShiftCmdEShortcutFilter, StatusBarPeekFilter

STATUS_BAR_ANIM_HEIGHT = 24  # Height for status bar slide animation
STATUS_BAR_ANIM_MS = 250 # Animation duration in milliseconds


class ImageBrowserWindow(QMainWindow):

    # macOS fullscreen availability (set from module-level constant)
    MACOS_FULLSCREEN_AVAILABLE = MACOS_FULLSCREEN_AVAILABLE

    # Spacing constants for thumbnail layout (imported from ThumbnailContainer)
    # These will be set when the thumbnail container is created
    HORIZONTAL_SPACING = None
    VERTICAL_SPACING = None

    # Temporary trash directory - user-specific to avoid conflicts
    TMP_TRASHES_DIR = f"/tmp/trashes-{os.getenv('USER', 'unknown')}"

    @staticmethod
    def get_button_style() -> str:
        """Returns the standard button style string for all QPushButton widgets.
        Delegates to centralized function in utils.py for consistency."""
        from utils import get_button_style as utils_get_button_style
        return utils_get_button_style()

    # Property accessors delegating to FileDataModel (single source of truth)
    @property
    def displayed_images(self) -> List[str]:
        if getattr(self, 'file_data_model', None):
            return self.file_data_model.get_displayed_images()
        return []

    @displayed_images.setter
    def displayed_images(self, value: List[str]):
        if getattr(self, 'file_data_model', None):
            self.file_data_model.set_displayed_images(value if value else [])

    @property
    def current_image_path(self) -> Optional[str]:
        if getattr(self, 'file_data_model', None):
            return self.file_data_model.get_current_image_path()
        return None

    @current_image_path.setter
    def current_image_path(self, value: Optional[str]):
        if getattr(self, 'file_data_model', None):
            self.file_data_model.set_current_image_path(value)

    @property
    def current_directory(self) -> Optional[str]:
        if getattr(self, 'file_data_model', None):
            return self.file_data_model.get_current_directory()
        return None

    @current_directory.setter
    def current_directory(self, value: Optional[str]):
        if getattr(self, 'file_data_model', None):
            self.file_data_model.set_current_directory(value)

    @property
    def highlight_index(self) -> int:
        if getattr(self, 'file_data_model', None):
            return self.file_data_model.get_current_index()
        return 0

    @highlight_index.setter
    def highlight_index(self, value: int):
        if getattr(self, 'file_data_model', None):
            self.file_data_model.set_current_index(value)

    @property
    def current_index(self) -> int:
        if getattr(self, 'file_data_model', None):
            return self.file_data_model.get_current_index()
        return 0

    @current_index.setter
    def current_index(self, value: int):
        if getattr(self, 'file_data_model', None):
            self.file_data_model.set_current_index(value)

    @property
    def current_view_mode(self) -> str:
        if getattr(self, 'file_data_model', None):
            return self.file_data_model.get_current_view_mode()
        return 'thumbnail'

    @current_view_mode.setter
    def current_view_mode(self, value: str):
        if getattr(self, 'file_data_model', None):
            self.file_data_model.set_current_view_mode(value)

    def __init__(self, limit: Optional[int] = None,
                fullscreen: bool = False, 
                target_file: Optional[str] = None,
                immediate_fullscreen: bool = False, 
                debug_mode: bool = False, 
                filter_pattern: Optional[str] = None):
        super().__init__()

        # Initialize space_key_mode immediately to ensure it's always available
        self.space_key_mode = 'exit'
        self.directory_stack_history_handler = DirectoryHistoryHandler(self)
        
        # Initialize _current_sort_mode early to ensure property works
        # Will be set properly from settings later, but this ensures it exists
        self._current_sort_mode = SortMode.DATE

        # Flag to track when file deletion is in progress
        self.file_deletion_in_progress = False
        
        # Flag to track temporary status bar peek (auto-show when cursor near bottom)
        self._status_bar_peek_active = False
        
        # Flag to prevent infinite loops when auto-opening last directory
        self._opening_last_directory = False
        
        # Track the directory of the currently highlighted file for auto-open fallback
        self._current_highlighted_file_directory = None
        
        # Essential state
        # Initialize FileDataModel for centralized data management
        from file_data_model import FileDataModel
        from event_bus import EventBus
        self.file_data_model = FileDataModel()
        self.event_bus = EventBus()
        # displayed_images, highlight_index, current_index, current_image_path, current_directory, current_view_mode
        # are now properties delegating to file_data_model (single source of truth)
        self.current_thumbnail_size = MIN_THUMBNAIL_SIZE
        self.manual_thumbnail_size = False  # Flag to track if user manually set thumbnail size
        self._refresh_in_progress = False  # Flag to prevent concurrent refreshes (GIL deadlock prevention)
        self._applying_sort = False  # Flag to prevent early return during sort operations
        
        # Connect FileDataModel signals to sync with tree view and EventBus
        self.file_data_model.displayed_images_changed.connect(self._on_displayed_images_changed)
        self.file_data_model.current_image_changed.connect(self._on_current_image_changed)
        self.file_data_model.directory_changed.connect(self._on_directory_changed)
        from window_model_bridge import WindowModelBridge

        self._model_event_bridge = WindowModelBridge(self.file_data_model, self.event_bus)
        self._model_event_bridge.connect()
        # Normalize limit: None or 0 becomes 99999 (unlimited), always a number internally
        if limit is None or limit == 0:
            self.limit = 99999
        else:
            self.limit = limit
        self.launch_fullscreen = fullscreen
        self.target_file = target_file
        self.immediate_fullscreen = immediate_fullscreen
        # Normalize filter pattern for storage (remove trailing asterisk)
        self.filter_pattern = ImageBrowserConfig.normalize_filter_pattern(filter_pattern)
        # When True, the current thumbnail set is a specific list of files provided
        # externally (e.g., via API). Used to avoid replacing the set with a full
        # directory scan when exiting fullscreen.
        self.specific_files_active: bool = False
        self.reference_graph_active: bool = False
        self.reference_graph_data = None
        self.reference_graph_focus_path: Optional[str] = None
        
        # Flag to track if settings changed while in browse mode
        self._settings_changed_in_browse: bool = False
        
        # Window mode support - store the window size for preserving view after browse view exit
        self.window_size: Optional[int] = None
        self.window_target_file: Optional[str] = None
        
        # Formatted list mode: deleted files kept as placeholders with red X overlay
        # (exif_date_sections or duplicate_sections present). Cleared when leaving formatted mode.
        self.deleted_file_placeholders: set = set()  # Set[str] of paths deleted but slot preserved

        # Multiple selection support - using file names as source of truth
        self.selected_files: set = set()  # Set[str] containing full file paths
        # multi_select_mode is now a property derived from selected_files
        self.range_anchor_index = None
        # CMD+Arrow multi-select tracking
        self.cmd_multi_origin_index: Optional[int] = None
        self.cmd_multi_axis: Optional[str] = None  # 'h' or 'v'
        self.cmd_multi_sign: int = 0  # -1 or +1
        
        
        # Copy toggle state tracking for imagegen files
        self._copy_toggle_state: set = set()
        
        self.config = get_config()
        self._cleanup_in_progress = False
        self._initializing_ui = False  # Flag to track UI initialization state
        
        # Random browsing and image order state (loaded from settings below)
        
        # Load settings
        settings = self.config.load_settings()
        
        # CNN similarity sorter - lazy initialization (only created when needed)
        # Store config for lazy initialization
        similarity_metric = settings.get('similarity_metric', 'cosine')
        # Ensure we're not using CLIP (shouldn't be possible, but be safe)
        if similarity_metric == 'clip':
            similarity_metric = 'cosine'
        self._similarity_metric = similarity_metric
        self._similarity_cache_dir = self.config.image_recognition_cache_dir
        self.cnn_image_similarity_sorter = None  # Will be created on first use
        # UI helper for CNN similarity operations - lazy initialization
        self.cnn_similarity_ui_helper = None  # Will be created on first use
        self.debug_mode = debug_mode if debug_mode is not None else settings.get('debug_mode', False)
        self.confirm_delete = settings.get('confirm_delete', True)
        self.is_actual_size = settings.get('browse_view_actual_size', False)
        self.wrap_around = settings.get('wrap_around', True)
        self.ignore_exif_rotation = settings.get('ignore_exif_rotation', False)
        self.drag_drop_auto_date_change = settings.get('drag_drop_auto_date_change', False)
        self.allow_thumbnail_locking = settings.get('allow_thumbnail_locking', False)
        self.allow_quick_mass_rename = settings.get('allow_quick_mass_rename', False)
        self.show_extensions = settings.get('show_extensions', False)
        self.show_image_size = settings.get('show_image_size', False)
        filtered_tree_setting = settings.get('filtered_tree', 'images')
        # Convert boolean to string for backward compatibility
        if isinstance(filtered_tree_setting, bool):
            self.filtered_tree = 'use_filter' if filtered_tree_setting else 'images'
        else:
            self.filtered_tree = filtered_tree_setting
        self.space_key_mode = settings.get('space_key_mode', 'exit')
        _bh_ms = settings.get('browse_image_history_save_after_ms', 3000)
        try:
            self.browse_image_history_save_after_ms = max(0, min(5000, int(_bh_ms)))
        except (TypeError, ValueError):
            self.browse_image_history_save_after_ms = 3000
        
        # Load limit and filter_pattern from settings if not provided via command line
        # If limit was initialized as 99999 (from None/0), check settings
        # Otherwise, limit was explicitly set via command line, so keep it
        if self.limit == 99999:
            saved_limit = settings.get('max_images', 0)
            if saved_limit == 0:  # 0 means unlimited
                self.limit = 99999
            else:
                self.limit = saved_limit
        
        if self.filter_pattern is None:
            saved_filter = settings.get('filter_pattern', '')
            self.filter_pattern = ImageBrowserConfig.normalize_filter_pattern(saved_filter)
        
        # Enhanced similarity settings
        similarity_metric = settings.get('similarity_metric', 'cosine')
        # Ensure we're not using CLIP (shouldn't be possible, but be safe)
        if similarity_metric == 'clip':
            similarity_metric = 'cosine'
        self.similarity_mode = settings.get('similarity_mode', 'accurate')
        # Always use multimodal hash and hash size 16 (hardcoded)
        self.multimodal_hash = True
        self.hash_size = 16
        # Search mode: always image for cmd-K (CLIP uses shift-cmd-K)
        self.similarity_search_mode = 'image'
        
        # Load sorting scheme settings - using SortMode enum
        # Initialize _current_sort_mode early (used by property)
        saved_sort_mode = settings.get('sort_mode', 'date')
        try:
            self._current_sort_mode = SortMode(saved_sort_mode)
        except ValueError:
            self._current_sort_mode = SortMode.DATE
        self.is_reversed = settings.get('sort_reversed', False)
        
        # Cache manager
        self.cache_manager = get_cache_manager()
        # Initialize cache manager's EXIF setting to match window's setting
        self.cache_manager.update_exif_setting(self.ignore_exif_rotation)
        self.cache_manager.metadata_ready.connect(self.on_metadata_ready, Qt.QueuedConnection)
        self.cache_manager.fullimage_ready.connect(self.on_fullimage_ready, Qt.QueuedConnection)
        self.cache_manager.thumbnail_ready.connect(self.on_thumbnail_ready, Qt.QueuedConnection)
        
        # Browse view state (current_view_mode, current_index, current_image_path from file_data_model)
        # Flag to prevent browse view from opening when loading a directory
        self._loading_directory_mode = False
        # watch(self.current_index)
        self.scale_factor = 1.0
        self.scroll_x = 0
        self.scroll_y = 0
        # After manual zoom (pinch / +/- / Ctrl+wheel), window resizes preserve scale and pan anchor
        self.browse_zoom_pinned = False
        self.current_pixmap = None
        self.filename_visible = False
        self.number_overlay_visible = False
        # Thumbnail filename visibility state (loaded from config)
        self.thumbnail_filename_visible = settings.get('thumbnail_filename_visible', False)
        
        # Status bar visibility will be managed as a property
        
        # Image transformation state
        self.image_transformations: Dict[str, Tuple[int, bool, bool]] = {}
        
        # Slideshow managers
        self.slideshow_manager = SlideshowManager(self)
        self.slideshow2_manager = Slideshow2Manager(self)
        self.slideshow3_manager = Slideshow3Manager(self)

        # Keyboard handler manager
        self.keyboard_handler_manager = KeyboardHandlerManager(self)
        self.keyboard_handler_manager.set_slideshow_handler(self.slideshow_manager)
        self.keyboard_handler_manager.set_slideshow2_handler(self.slideshow2_manager)
        self.keyboard_handler_manager.set_slideshow3_handler(self.slideshow3_manager)
        
        # New managers for refactored functionality
        self.navigation_manager = NavigationManager(self)
        self.thumbnail_context_menu_handler = ThumbnailContextMenuHandler(self)
        self.thumbnail_operations_manager = ThumbnailOperationsManager(self)
        self.file_operations_manager = FileOperationsManager(self)
        self.menu_manager = MenuManager(self)
        self.view_manager = ViewManager(self)
        self.browse_view_handler = BrowseViewHandler(self)
        self.help_dialog = HelpDialog(self)
        
        # Phase 1-3 refactored managers
        self.similarity_search_manager = SimilaritySearchManager(self)
        self.directory_loader = DirectoryLoader(self)
        # browse_image_history: ordered unique paths, index 0 = most recent (depth: thumbnail_constants; F3 → specific-files thumbnails)
        self.browse_image_history = []
        self._browse_image_history_debounce_timer = QTimer(self)
        self._browse_image_history_debounce_timer.setSingleShot(True)
        self._browse_image_history_debounce_timer.timeout.connect(self._on_browse_image_history_debounce_timeout)
        self._browse_image_history_debounce_pending_path: Optional[str] = None
        self.refresh_manager = RefreshManager(self)
        self.ui_layout_manager = UILayoutManager(self)
        self.sorting_manager = SortingManager(self)
        self.thumbnail_display_manager = ThumbnailDisplayManager(self)
        self.selection_manager = SelectionManager(self)
        self.image_display_manager = ImageDisplayManager(self)
        self.sidebar_manager = SidebarManager(self)
        self.view_mode_manager = ViewModeManager(self)
        self.event_handler = EventHandler(self)
        self.configuration_sync_manager = ConfigurationSyncManager(self)
        self.lock_manager = LockManager(self)
        # MVC Controller - thin controller, updates model only
        from mvc_controller import MVCController
        self.mvc_controller = MVCController(self.file_data_model, self.event_bus)
        self.mvc_controller.register_service('directory_loader', self.directory_loader)
        self.mvc_controller.register_service('sorting_manager', self.sorting_manager)
        self.mvc_controller.wire_event_bus()
        
        # Initialize lazy-loaded components to None to avoid hasattr checks
        # These attributes are checked throughout the code but never initialized
        self.thumbnail_worker = None
        self._cached_grid_columns = None
        self._cached_thumbnail_size = None
        self.cached_container_width = None
        self.cached_container_height = None
        self.deletion_operations = []
        self.move_operations = []  # Track move operations for undo
        self.browse_view_exit_in_progress = False
        self.image_indices = None
        self.temp_transformed_pixmap = None
        
        self.setup_ui()
        self.setup_actions()
        self.setup_connections()
        self.refresh_theme_styles()
        self.status_notification = None
        self.settings_dialog = None
        
        # Initialize components after UI is ready
        QTimer.singleShot(0, self.initialize_components)
        
        
        
        # Resize timer for debounced window resize handling
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._handle_resize)
        
        # Scroll debounce timer for priority thumbnail loading
        self._scroll_debounce_timer = QTimer()
        self._scroll_debounce_timer.setSingleShot(True)
        self._scroll_debounce_timer.timeout.connect(self._on_scroll_debounced)
        
        # Refresh directory timer - reuse to avoid GIL deadlock from creating new timers
        # CRITICAL: Initialize timer here and reuse it in debounce_refresh_directory() to avoid
        # dropping GIL for signal connection when called from within timer callbacks.
        self._refresh_directory_timer = QTimer()
        self._refresh_directory_timer.setSingleShot(True)
        self._refresh_directory_timer.timeout.connect(self.refresh_directory)
        
        # Splitter resize timer - initialize here to avoid GIL deadlock from creating new timers
        # CRITICAL: Initialize timer here and reuse it to avoid dropping GIL for signal connection.
        self._splitter_resize_timer = QTimer()
        self._splitter_resize_timer.setSingleShot(True)
        self._splitter_resize_timer.timeout.connect(self.update_layout_after_splitter_resize)
        
        # Track if browse mode is ready to accept input
        self.browse_view_input_ready = False
        
        # Resize state tracking
        self._resize_in_progress = False
        self._last_window_size = None
        
        # Mouse drag state for panning
        self.is_dragging = False
        self.drag_start_pos = None
        self.drag_start_scroll_x = 0
        self.drag_start_scroll_y = 0
        
        # Fullscreen size refresh mechanism
        self.browse_view_refresh_timer = QTimer()
        self.browse_view_refresh_timer.setSingleShot(True)
        self.browse_view_refresh_timer.timeout.connect(self._refresh_browse_view_display)
        
        # Flag to prevent recursive calls to thumbnail restart functions
        self._restarting_thumbnails = False
        self.pending_browse_view_refresh = False
        self.last_browse_view_size = QSize()
        
        # Note: immediate_fullscreen handling moved to showEvent to ensure window is visible first
        
        # Enable pinch gesture support for trackpad zoom
        self.grabGesture(Qt.PinchGesture)
        
        # Enable mouse tracking for cursor changes
        self.setMouseTracking(True)
        
        # Zoom center point for cursor-aware zoom
        self.zoom_center_point = QPointF()
        
        # Initialize undo manager for file operations (will be properly initialized in initialize_components)
        self.file_undo_manager = None
        self.deleted_files = []
        
        # Initialize message handler for JSON configuration messages
        self.message_handler = MessageHandler()
        self._processing_message = False  # Guard to prevent recursive message processing
        # Queue-based pipeline: main thread polls via timer (avoids GIL deadlock from signal emit)
        self._message_poll_timer = QTimer(self)
        self._message_poll_timer.timeout.connect(self._poll_message_queue)
        
        # Track state for optimization to avoid unnecessary work
        self._last_window_size = None
        self._last_thumbnail_size = None
        self._last_status_info = None
        
        # Key popup overlay (for key display)
        self.key_popup_label = QLabel(self)
        self.key_popup_label.setVisible(False)
        self.key_popup_label.setStyleSheet('''
            QLabel {
                background-color: black;
                color: white;
                border: 2px solid yellow;
                font-weight: bold;
                font-size: 12pt;
                padding: 8px 16px;
                border-radius: 18px;
            }
        ''')
        self.key_popup_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        self.key_popup_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.key_popup_timer = QTimer(self)
        self.key_popup_timer.setSingleShot(True)
        self.key_popup_timer.timeout.connect(self.hide_key_popup)
        
        # Register key popup callback
        if self.debug_mode:
            set_popup_callback(self.show_key_popup)
        else:
            set_popup_callback(None)
        self.key_popup_label.setVisible(False)
        
        # Initialize cursor manager for browse mode
        self.cursor_manager = None
        
        # Save initial settings
        self.config.update_setting('debug_mode', self.debug_mode)
        self.config.update_setting('confirm_delete', self.confirm_delete)
        self.config.update_setting('browse_view_actual_size', self.is_actual_size)
        self.config.update_setting('wrap_around', self.wrap_around)
        self.config.update_setting('space_key_mode', self.space_key_mode)
        self.config.update_setting('browse_image_history_save_after_ms', self.browse_image_history_save_after_ms)
        
        # Save slideshow settings via manager
        self.slideshow_manager.save_slideshow_settings()
        self.slideshow2_manager.save_slideshow2_settings()
        
    @property
    def multi_select_mode(self) -> bool:
        """Multi-select mode is active when more than one file is selected.
        
        This property is derived from selected_files and eliminates the need
        for manual synchronization of the multi_select_mode flag.
        """
        return len(self.selected_files) > 1

    @property
    def status_bar_visible(self) -> bool:
        """Status bar visibility derived from actual widget state.
        
        This property eliminates the need for manual synchronization of
        the status_bar_visible flag with actual UI state.
        """
        return getattr(self, 'status_bar', None) and self.status_bar.isVisible()

    @property
    def current_sort_mode(self) -> SortMode:
        """Get the current sorting mode."""
        if not hasattr(self, '_current_sort_mode'):
            self._current_sort_mode = SortMode.DATE
        return self._current_sort_mode
    
    @current_sort_mode.setter
    def current_sort_mode(self, mode: SortMode):
        """Set the current sorting mode."""
        # Clear EXIF date sections if not in EXIF_DATE mode
        # This ensures EXIF formatting is turned off whenever sort mode changes
        # Also clear duplicate sections if not in DUPLICATES mode
        if mode not in (SortMode.EXIF_DATE, SortMode.EXIF_YEAR):
            if hasattr(self, 'exif_date_sections'):
                self.exif_date_sections = []
            if hasattr(self, 'exif_section_expanded'):
                self.exif_section_expanded = {}
        # Only clear duplicate_sections if they were actually set (transitioning FROM duplicates mode)
        if (mode != SortMode.DUPLICATES and
            hasattr(self, 'duplicate_sections') and
            self.duplicate_sections):
            self.duplicate_sections = []
        # Clear deleted placeholders when switching to non-formatted mode
        if mode not in (SortMode.EXIF_DATE, SortMode.EXIF_YEAR, SortMode.DUPLICATES) and hasattr(self, 'deleted_file_placeholders'):
            self.deleted_file_placeholders.clear()
        
        # Also clear section separators in thumbnail canvas if it exists
        if getattr(self, 'thumbnail_container', None):
            if hasattr(self.thumbnail_container, 'canvas'):
                if hasattr(self.thumbnail_container.canvas, 'section_separators'):
                    self.thumbnail_container.canvas.section_separators.clear()
                    # Force repaint to remove separators from display
                    self.thumbnail_container.canvas.update()
        
        self._current_sort_mode = mode
    @property
    def sort_direction_reversed(self) -> bool:
        """Whether the current sort direction is reversed.
        
        This provides a cleaner interface to the is_reversed flag.
        """
        return getattr(self, 'is_reversed', False)

    def save_sorting_settings(self):
        """Save current sorting scheme settings to config"""
        self.sorting_manager.save_sorting_settings()

    def set_reference_graph_presentation(
        self, active: bool, paths=None, focus_path: Optional[str] = None
    ) -> None:
        """Enable reference dependency graph canvas for the current specific-files level."""
        if active and paths and len(paths) > 1:
            from reference_graph import build_reference_graph

            self.reference_graph_active = True
            path_set = {os.path.normpath(os.path.abspath(p)) for p in paths}
            focus = focus_path or getattr(self, "current_image_path", None) or paths[0]
            fn = os.path.normpath(os.path.abspath(focus)) if focus else ""
            if fn not in path_set:
                focus = paths[0]
            self.reference_graph_focus_path = focus
            self.reference_graph_data = build_reference_graph(
                list(paths), focus_path=focus
            )
        else:
            self.clear_reference_graph_presentation()

    def clear_reference_graph_presentation(self) -> None:
        """Return thumbnail canvas to normal grid/section layout."""
        self.reference_graph_active = False
        self.reference_graph_data = None
        self.reference_graph_focus_path = None
        if getattr(self, 'thumbnail_container', None) and hasattr(
            self.thumbnail_container, 'canvas'
        ):
            canvas = self.thumbnail_container.canvas
            canvas._reference_graph_edge_routes = []
            canvas._reference_graph_layout_result = None
    
    def set_sort_mode(self, mode: SortMode, toggle_reverse: bool = False):
        """Unified method to set sorting mode."""
        return self.sorting_manager.set_sort_mode(mode, toggle_reverse)
    
    def _apply_current_sort(self):
        """Apply the current sort mode to displayed images."""
        return self.sorting_manager.apply_current_sort()

    def _ensure_cnn_sorter_initialized(self):
        """Lazy initialize CNN similarity sorter if not already created"""
        self.similarity_search_manager._ensure_cnn_sorter_initialized()

    def _ensure_cnn_ui_helper_initialized(self):
        """Lazy initialize CNN similarity UI helper if not already created"""
        self.similarity_search_manager._ensure_cnn_ui_helper_initialized()
    
    def reorder_images_by_similarity(self):
        """Reorder images by similarity (delegates to SimilaritySearchManager / similarity_reorder)."""
        self.similarity_search_manager.reorder_images_by_similarity()

    def reorder_images_by_clip_search(self):
        """CLIP text search reorder (delegates to SimilaritySearchManager / similarity_reorder)."""
        self.similarity_search_manager.reorder_images_by_clip_search()

    def _scan_directory_efficiently(self, directory: str) -> List[str]:
        """Scan directory efficiently using os.scandir instead of os.listdir"""
        return self.directory_loader._scan_directory_efficiently(directory)

    def get_sort_key(self, path):
        """Get sort key for file sorting - consolidated from multiple duplicate functions"""
        return self.sorting_manager.get_sort_key(path)

    def count_total_files_in_directory(self, directory: str) -> int:
        """Count total image files in directory that match the current filter pattern"""
        return self.directory_loader.count_total_files_in_directory(directory)

    # File count is now handled by the status bar manager
    
    def update_status_bar_sections(self):
        """Update all status bar sections with current state"""
        if hasattr(self, 'status_bar_manager'):
            self.status_bar_manager.update_status_bar_sections(self)
    
    def update_status_bar_fit_mode(self):
        """Update the fit mode section of the status bar"""
        if hasattr(self, 'status_bar_manager'):
            self.status_bar_manager.update_fit_mode_section(self)
    
    def update_status_bar_current_image(self, current_image_path=None, displayed=None):
        """Update status bar with current image information.
        
        This is the CENTRALIZED method to update filename, directory, date, and dimensions
        whenever the active image changes. Always call this when current_image_path changes.
        
        Args:
            current_image_path: Optional cached current image path to avoid redundant call.
                               If None, will call get_current_image_path(). File path remains source of truth.
            displayed: Optional cached list of displayed images to avoid redundant calls.
                      If None, status bar methods will fetch it themselves.
        """
        if hasattr(self, 'status_bar_manager'):
            # Update all image-specific sections: filename (full path), date, dimensions
            # These must always be kept in sync with the currently active image
            # Pass cached values to avoid redundant calls
            self.status_bar_manager.update_filename_section(self, current_image_path, displayed)
            self.status_bar_manager.update_dimensions_section(self, current_image_path, displayed)
            self.status_bar_manager.update_date_section(self, current_image_path)
            # Note: directory section removed - full path now shown in filename section

    def _check_and_refresh_if_changed(self):
        """Check if directory files changed and only refresh if necessary - prevents unnecessary flashing"""
        return self.refresh_manager._check_and_refresh_if_changed()
    
    def _efficient_refresh_with_changes(self, current_files, displayed_set):
        """Efficiently refresh directory when files changed - only updates what's necessary"""
        return self.refresh_manager._efficient_refresh_with_changes(current_files, displayed_set)

    def efficient_directory_refresh(self):
        """Efficiently refresh directory by detecting added/removed files and making minimal incremental changes"""
        return self.refresh_manager.efficient_directory_refresh()

    def _is_formatted_list_mode(self) -> bool:
        """True when in EXIF date view or duplicate finder (formatted lists with sections)."""
        return (
            (hasattr(self, 'exif_date_sections') and self.exif_date_sections and len(self.exif_date_sections) > 0) or
            (hasattr(self, 'duplicate_sections') and self.duplicate_sections and len(self.duplicate_sections) > 0)
        )

    def clear_deleted_placeholders_for_paths(self, paths):
        """Remove paths from deleted_file_placeholders and trigger synchronous repaint."""
        placeholders = getattr(self, 'deleted_file_placeholders', None)
        if not placeholders or not paths:
            return
        for p in paths:
            if p:
                placeholders.discard(p)
        # Synchronous repaint - file is on disk, os.path.exists() at paint time controls the X
        if hasattr(self, 'thumbnail_container') and self.thumbnail_container and hasattr(self.thumbnail_container, 'canvas'):
            self.thumbnail_container.canvas.repaint()
        if getattr(self, 'current_view_mode', None) == 'list':
            if hasattr(self, 'list_view_container') and self.list_view_container and hasattr(self.list_view_container, 'canvas'):
                self.list_view_container.canvas.repaint()
            if hasattr(self, 'view_manager') and self.view_manager:
                self.view_manager.update_list_view()

    def remove_thumbnails_for_files(self, files_to_remove, active_file_path=None):
        """Remove specific thumbnails for deleted files without rebuilding the entire grid.
        Delegates to ThumbnailDisplayManager which updates model and refreshes view."""
        if hasattr(self, 'thumbnail_display_manager') and self.thumbnail_display_manager:
            self.thumbnail_display_manager.remove_thumbnails_for_files(files_to_remove, active_file_path)
    

    @safe_refresh_wrapper
    def refresh_from_configuration(self, configuration: dict, from_api: bool = False):
        """Unified method to refresh the browser from a JSON configuration
        
        Args:
            configuration: Dictionary containing files, directory, limit, filter, etc.
            from_api: True if this call originates from the API pipe, False otherwise
        """
        try:
            if self.debug_mode:
                import json

                from debug_log import debug_timestamp

                print(
                    f"{debug_timestamp()} {RED}refresh_from_configuration configuration:{RESET}\n"
                    f"{json.dumps(configuration, indent=4)}{RESET}"
                )
            
            files = configuration.get('files', [])
            directory = configuration.get('directory')
            limit = configuration.get('limit')
            filter_pattern = configuration.get('filter')
            # When loading search results (files with sort_mode), set CUSTOM before load_specific_files
            # This ensures correct mode even if safe_refresh_wrapper defers execution
            config_sort_mode = configuration.get('sort_mode')
            if config_sort_mode == 'custom' and files:
                self.current_sort_mode = SortMode.CUSTOM
                self.is_reversed = False
            fullscreen = configuration.get('fullscreen')
            prevent_browse_view = configuration.get('prevent_browse_view', False)
            force_specific_files_grid = configuration.get('force_specific_files_grid', False)
            limit = configuration.get('limit', self.limit)
            if not limit:
                limit = self.limit if self.limit else 99999
            # When specific files are received, resolve the full names and remove duplicates before sending the configuration
            if files:
                # Build a list of resolved absolute paths, preserving order while removing duplicates
                resolved_list = []
                seen = set()
                for f in files:
                    abs_path = os.path.abspath(f)
                    if abs_path not in seen:
                        seen.add(abs_path)
                        resolved_list.append(abs_path)
                files = resolved_list
                configuration['files'] = files
            presentation = configuration.get('presentation')
            if presentation == 'reference_graph' and files and len(files) > 1:
                self.set_reference_graph_presentation(
                    True,
                    files,
                    focus_path=configuration.get("focus_path"),
                )
            elif not files or presentation != 'reference_graph':
                self.clear_reference_graph_presentation()
            # If not currently in fullscreen, add current image to directory stack history
            # BUT: Skip saving state when loading specific files - the caller should save state
            # before calling refresh_from_configuration, and save correct state after load_specific_files
            # Skip state save if files are provided (will be saved after load_specific_files completes)
            if not files:
                self.directory_stack_history_handler.save_current_state('image_browser_window.refresh_from_configuration')
            if hasattr(self, 'most_recent_selected_index'):
                del self.most_recent_selected_index #DGN    

            # If multiple explicit files are requested, force thumbnail mode handling
            # unless fullscreen is explicitly requested via command line
            is_multiple_files_request = isinstance(files, list) and len(files) > 1
            is_single_file_request = isinstance(files, list) and len(files) == 1
            # Single file requests should go to fullscreen by default (especially from tree clicks)
            # Honor explicit fullscreen requests even for multiple files
            # But respect prevent_browse_view flag when restoring thumbnail mode
            # Also respect explicit fullscreen=False (from --no-fullscreen flag)
            # IMPORTANT: Explicit fullscreen flags take precedence over prevent_browse_view
            if fullscreen is True:
                # Explicitly set to True (e.g., --fullscreen flag): use fullscreen
                requested_fullscreen = True
            elif fullscreen is False:
                # Explicitly set to False (e.g., --no-fullscreen flag): respect it
                requested_fullscreen = False
            elif prevent_browse_view:
                # prevent_browse_view only applies when no explicit fullscreen flag
                requested_fullscreen = False
            else:
                # fullscreen is None: use default behavior (single file = fullscreen)
                requested_fullscreen = is_single_file_request and not is_multiple_files_request
            
            # Normalize limit: None or 0 becomes 99999
            if limit and limit != 0:
                self.limit = limit
            else:
                self.limit = 99999
            if filter_pattern is not None:
                # Normalize filter pattern for storage (remove trailing asterisk)
                self.filter_pattern = ImageBrowserConfig.normalize_filter_pattern(filter_pattern)
                # Update status bar immediately to reflect filter change
                if hasattr(self, 'status_bar_manager'):
                    self.status_bar_manager._update_filter_section(self)
            # Handle OS fullscreen mode - use requested_fullscreen which handles all cases
            # including explicit flags, prevent_browse_view, and default behavior
            if requested_fullscreen and not self.isFullScreen():
                # Use a longer delay to ensure window is fully visible and ready
                def enter_fullscreen():
                    if not self.isFullScreen() and self.isVisible():
                        self.showFullScreen()
                QTimer.singleShot(200, enter_fullscreen)
            
            if self.current_view_mode == 'slideshow':
                self.slideshow_manager.stop_slideshow()
            
            # Ensure we are in thumbnail view before processing multi-file requests,
            # or when not explicitly entering fullscreen.
            # Also ensure thumbnail view when loading a directory (not specific files)
            if self.current_view_mode in ['browse', 'slideshow']:
                if is_multiple_files_request or not requested_fullscreen or directory:
                    self.view_manager.close_browse_view()
            
            self.clear_thumbnails()
            self.displayed_images = []
            self.image_indices = []
            self.image_indices_sequential = []
            self.image_indices_random = []
            self.highlight_index = 0
            self.selected_files.clear()
            
            if files:
                # First pass: check which files exist immediately
                valid_files = [f for f in files if os.path.exists(f)]
                missing_files = [f for f in files if not os.path.exists(f)]
                
                if missing_files:
                    # Second pass: retry with a small delay for files that weren't found
                    if missing_files:
                        # Use time.sleep() instead of nanosleep via ctypes to avoid GIL deadlock
                        # Even though this is in the main thread, nanosleep via ctypes can still cause issues
                        import time
                        time.sleep(0.1)  # 100ms sleep
                        
                        # Check again for missing files
                        still_missing = []
                        newly_found = []
                        for f in missing_files:
                            if os.path.exists(f):
                                newly_found.append(f)
                                valid_files.append(f)
                            else:
                                still_missing.append(f)
                
                if valid_files:
                    if from_api:
                        self.set_date_sort(reverse=False, notify=False)
                        self.load_specific_files(valid_files, external_load=True, force_specific_files_grid=force_specific_files_grid)
                    else:
                        self.load_specific_files(valid_files, external_load=True, force_specific_files_grid=force_specific_files_grid)

                    # Single-file requests (expand, testchat open, etc.) must land in image viewer (browse view).
                    # When already in browse view, load_file_with_directory_thumbnails skips show_image; refresh here.
                    if len(valid_files) == 1 and requested_fullscreen:
                        target_file = valid_files[0]

                        def ensure_single_file_browse_view():
                            if target_file not in getattr(self, 'displayed_images', []):
                                return
                            try:
                                idx = self.displayed_images.index(target_file)
                            except ValueError:
                                idx = self.current_index if self.current_index is not None else 0
                            self.set_current_image_by_path(target_file, fallback_index=idx)
                            self.view_mode_manager.open_browse_view(idx)

                        QTimer.singleShot(200, ensure_single_file_browse_view)
                    elif from_api and len(valid_files) > 1:
                        def activate_newest():
                            newest_file = max(valid_files, key=lambda path: self.get_sort_key(path))
                            if newest_file in self.displayed_images:
                                self.set_current_image_by_path(newest_file, fallback_index=0)
                        QTimer.singleShot(100, activate_newest)
                else:
                    self.status_bar_manager.show_message(f"Error: No valid files found from API call")
            elif directory:
                if os.path.exists(directory):
                    # When loading a directory (not specific files), check if we should prevent browse view
                    # Only prevent browse view if prevent_browse_view is explicitly True (command line directory)
                    # If False or not set, allow restore logic to handle browse view restoration
                    prevent_browse_view = configuration.get('prevent_browse_view', False)
                    
                    if prevent_browse_view:
                        # Directory from command line: ensure thumbnail mode
                        self._loading_directory_mode = True
                        # Clear target_file to prevent browse view from opening on a specific image
                        self.target_file = None
                        # Close browse view if currently in browse mode
                        if self.current_view_mode != 'thumbnail':
                            self.view_manager.close_browse_view()
                        # Ensure we stay in thumbnail mode after loading directory
                        self.current_view_mode = 'thumbnail'
                    else:
                        # Directory from restoration: don't prevent browse view, let restore logic handle it
                        # Still set the flag but don't force thumbnail mode
                        self._loading_directory_mode = True
                    
                    self.load_directory(directory, external_load=True)
                    
                    # After loading directory, ensure correct mode based on prevent_browse_view
                    def ensure_mode_after_load():
                        if prevent_browse_view:
                            # Command line directory: ensure thumbnail mode
                            if self.current_view_mode != 'thumbnail':
                                self.view_manager.close_browse_view()
                        # Clear the flag after ensuring correct mode
                        self._loading_directory_mode = False
                    QTimer.singleShot(200, ensure_mode_after_load)      
        except Exception as e:
            self.status_bar_manager.show_message(f"Error: {str(e)}")
            pass

    def _poll_message_queue(self):
        """Drain message queue and process each message. Called by QTimer on main thread."""
        self.configuration_sync_manager.poll_message_queue()

    def _handle_configuration(self, configuration: dict):
        """Handle JSON configuration messages received from the named pipe"""
        self.configuration_sync_manager._handle_configuration(configuration)

    def _get_current_directory_files(self):
        """Get current image files in directory efficiently"""
        return self.directory_loader._get_current_directory_files()

    def get_full_sorted_filtered_list(self) -> List[str]:
        """Get the full list of files in current directory, sorted and filtered according to current settings."""
        return self.directory_loader.get_full_sorted_filtered_list()

    def handle_application_quit(self):
        """Handle application quit to ensure proper cleanup"""
    
    def cleanup_worker_thread(self, worker_attr_name, delete_after=True):
        """Common method to cleanup any worker thread (non-blocking)
        
        Args:
            worker_attr_name: Name of the worker attribute
            delete_after: Whether to call deleteLater() on the worker
        """
        # Check if worker exists and hasn't been cleaned up already
        if not hasattr(self, worker_attr_name):
            return  # Already cleaned up
        
        worker = getattr(self, worker_attr_name)
        if not worker:
            # Clear the reference if it's None
            delattr(self, worker_attr_name)
            return
        
        # Check if this is a valid QThread object before proceeding
        try:
            # Test if the object is still valid by checking if it's a QThread
            if not hasattr(worker, 'isRunning'):
                # Object is not a valid QThread, just remove the reference
                delattr(self, worker_attr_name)
                return
        except Exception:
            # Object is corrupted, just remove the reference
            delattr(self, worker_attr_name)
            return
        
        try:
            # Stop the worker gracefully (non-blocking)
            if hasattr(worker, 'stop'):
                worker.stop()
            elif hasattr(worker, 'cancel'):
                worker.cancel()
            
            # Use QTimer for non-blocking cleanup instead of blocking wait()
            def check_and_cleanup():
                try:
                    if not hasattr(self, worker_attr_name):
                        return
                    worker = getattr(self, worker_attr_name)
                    if not worker:
                        if hasattr(self, worker_attr_name):
                            delattr(self, worker_attr_name)
                        return
                    
                    if worker.isRunning():
                        # Still running, try to terminate
                        try:
                            worker.terminate()
                        except Exception:
                            pass
                        # Check again after a short delay
                        QTimer.singleShot(100, check_and_cleanup)
                    else:
                        # Worker stopped, cleanup
                        if delete_after:
                            try:
                                worker.deleteLater()
                            except Exception:
                                pass
                        # Clear the reference
                        if hasattr(self, worker_attr_name):
                            delattr(self, worker_attr_name)
                except Exception as e:
                    # Log error but don't fail
                    print(f"Error in cleanup check: {e}")
                    # Even if cleanup fails, try to remove the reference
                    try:
                        if hasattr(self, worker_attr_name):
                            delattr(self, worker_attr_name)
                    except Exception:
                        pass
            
            # Start non-blocking cleanup check
            QTimer.singleShot(50, check_and_cleanup)
            
        except Exception as e:
            # Log error but don't fail
            print(f"Error cleaning up worker thread: {e}")
            # Even if cleanup fails, try to remove the reference
            try:
                if hasattr(self, worker_attr_name):
                    delattr(self, worker_attr_name)
            except Exception:
                pass
    
    
    def ensure_cleanup_before_exit(self):
        """Ensure all resources are cleaned up before application exit"""
        try:
            tmp_trashes = self.TMP_TRASHES_DIR
            if os.path.exists(tmp_trashes):
                shutil.rmtree(tmp_trashes)
        except Exception:
            pass
        
        # Cleanup slideshow managers to ensure pending settings are saved
        try:
            if getattr(self, 'slideshow_manager', None):
                self.slideshow_manager.cleanup()
        except Exception:
            pass
        
        # Cleanup background CLIP controller (stop process and cleanup resources)
        try:
            if getattr(self, 'background_clip_controller', None):
                self.background_clip_controller.cleanup()
        except Exception:
            pass

        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller
            get_imagegen_controller(self).cleanup()
        except ImportError:
            pass

    def initialize_components(self):
        """Initialize components after UI is ready"""
        self.status_notification = StatusNotification(self)
        
        # Initialize directory history handler
        self.directory_history_handler_for_menu = DirectoryHistoryHandlerForMenu()
        
        self.wallpaper_manager = WallpaperManager(self.status_notification)
        
        # Initialize rename status manager
        from rename_status_manager import RenameStatusManager
        self.rename_status_manager = RenameStatusManager()
        # Clear status file at startup
        self.rename_status_manager.clear_all_status()
        # Load status if enabled (will be enabled when menu item is checked)
        # Status will be loaded when menu item is toggled on
        
        # Initialize background CLIP extraction components
        from idle_detector import IdleDetector
        from background_clip_controller import BackgroundClipController
        from background_cache_importer import BackgroundCacheImporter
        
        self.idle_detector = IdleDetector(self)
        self.background_clip_controller = BackgroundClipController(self)
        self.background_cache_importer = BackgroundCacheImporter(self)
        
        # Connect idle detector signals to controller
        # Pass current directory when idle is detected to prioritize it
        def on_idle_detected():
            try:
                self.background_clip_controller.start_process(
                    priority_directory=getattr(self, 'current_directory', None)
                )
            except Exception as e:
                raise
        
        self.idle_detector.idle_detected.connect(on_idle_detected)
        self.idle_detector.user_activity_detected.connect(self.background_clip_controller.pause_process)
        
        # Load background_clip_enabled setting and configure
        settings = self.config.load_settings()
        background_clip_enabled = settings.get('background_clip_enabled', False)
        self.background_clip_controller.set_enabled(background_clip_enabled)
        
        # Start idle detector if enabled
        if background_clip_enabled:
            self.idle_detector.start()
            self.background_cache_importer.start()
        
        self.message_handler.start_listening()
        self._message_poll_timer.start(50)  # Poll every 50ms for queued messages

        _import_appkit_modules()
        # Initialize undo manager for file operations
        if _NSUndoManager is not None:
            self.file_undo_manager = _NSUndoManager.alloc().init()
        else:
            self.file_undo_manager = None

    def closeEvent(self, event):
        """Handle window close event"""
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller
            if not getattr(self, "_api_quit_in_progress", False):
                if not get_imagegen_controller(self).confirm_quit_if_running(self):
                    event.ignore()
                    return
        except ImportError:
            pass

        self._message_poll_timer.stop()
        self.message_handler.cleanup()

        # Stop workers before cleanup_cache to avoid QThread destroyed while running
        if getattr(self, 'thumbnail_worker', None):
            try:
                if self.thumbnail_worker.isRunning():
                    self.thumbnail_worker.cancel()
                    self.thumbnail_worker.wait(2000)
            except Exception:
                pass
        if getattr(self, 'cache_manager', None) and getattr(self.cache_manager, 'background_loader', None):
            try:
                self.cache_manager.background_loader.stop()
            except Exception:
                pass

        cleanup_cache()
        
        if self.cursor_manager:
            self.cursor_manager.cleanup()
        
        if self.wallpaper_manager:
            self.wallpaper_manager.cleanup_temp_files()
        
        # Clean up rename status file at shutdown
        if getattr(self, 'rename_status_manager', None):
            self.rename_status_manager.clear_all_status()
        
        # Stop background CLIP process (cleanup() handles both stop and cleanup)
        if getattr(self, 'background_clip_controller', None):
            self.background_clip_controller.cleanup()

        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller
            get_imagegen_controller(self).cleanup()
        except ImportError:
            pass
        
        if getattr(self, 'idle_detector', None):
            self.idle_detector.stop()
        
        if getattr(self, 'background_cache_importer', None):
            self.background_cache_importer.stop()
        
        # Clean up KML directory
        try:
            from map_manager import cleanup_kml_directory
            cleanup_kml_directory()
        except Exception:
            pass
        
        super().closeEvent(event)

    def hideEvent(self, event):
        """Handle window hide event to ensure proper cleanup"""
        super().hideEvent(event)

    
    def setup_ui(self):
        """Setup the main user interface"""
        self.setWindowTitle("Prowser")
        self.setMinimumSize(400, 600)
        self.resize(1200, 800)
        # Note: immediate_fullscreen handling moved to main.py after window.show() for proper timing
        
        self.setFocusPolicy(Qt.NoFocus)  # Prevent main window from being in tab order
        
        # Load file tree visibility setting first (needed for menu bar setup)
        saved_settings = self.config.load_settings()
        self.file_tree_visible = saved_settings.get('file_tree_visible', False)
        
        # Load preview visibility setting
        self.preview_visible = saved_settings.get('preview_visible', False)
        self.jobs_visible = saved_settings.get('jobs_visible', False)
        
        # Single width for the combined sidebar widget
        self.sidebar_width = saved_settings.get('sidebar_width', 300)
        
        # Right sidebar (info panel) width
        self.right_sidebar_width = saved_settings.get('right_sidebar_width', 400)
        self.right_sidebar_visible = saved_settings.get('right_sidebar_visible', False)
        # Store right sidebar visibility state before slideshow (for restoration)
        self._right_sidebar_visible_before_slideshow = None
        
        # Create main horizontal splitter
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(self.main_splitter)
        
        # Setup file tree handler (but don't initialize tree yet)
        self.file_tree_handler = FileTreeHandler(self, self)
        self.setup_file_tree_callbacks()
        
        # Create combined sidebar widget
        self.combined_sidebar = CombinedSidebarWidget(self)
        self.combined_sidebar.setFocusPolicy(Qt.ClickFocus)
        
        # Set maximum width to allow one column of thumbnails
        max_sidebar_width = self.ui_layout_manager._calculate_max_sidebar_width()
        self.combined_sidebar.setMaximumWidth(max_sidebar_width)
        
        # Connect signals from combined sidebar
        self.combined_sidebar.tree_visibility_changed.connect(self._on_tree_visibility_changed)
        self.combined_sidebar.preview_visibility_changed.connect(self._on_preview_visibility_changed)
        self.combined_sidebar.widget_resized.connect(self._on_sidebar_resized)
        
        # Create focusable container for file tree
        self.tree_container = QWidget()
        self.tree_container.setFocusPolicy(Qt.NoFocus)  # Not in tab order - combined_sidebar handles focus
        # Remove fixed width constraints to allow expansion to full sidebar width
        # self.tree_container.setMinimumWidth(250)
        # self.tree_container.setMaximumWidth(500)
        
        # Add focus event handling to tree container
        def tree_focus_in(event):
            QWidget.focusInEvent(self.tree_container, event)
        
        def tree_focus_out(event):
            QWidget.focusOutEvent(self.tree_container, event)
        
        def tree_key_press(event):
            # Forward keyboard events to the file_tree widget
            if (self.file_tree_handler.is_tree_initialized() and 
                hasattr(self.file_tree_handler, 'file_tree') and self.file_tree_handler.file_tree):
                self.file_tree_handler.file_tree.keyPressEvent(event)
            else:
                QWidget.keyPressEvent(self.tree_container, event)
        
        def tree_key_release(event):
            # Forward keyboard events to the file_tree widget
            if (self.file_tree_handler.is_tree_initialized() and 
                hasattr(self.file_tree_handler, 'file_tree') and self.file_tree_handler.file_tree):
                self.file_tree_handler.file_tree.keyReleaseEvent(event)
            else:
                QWidget.keyReleaseEvent(self.tree_container, event)
        
        self.tree_container.focusInEvent = tree_focus_in
        self.tree_container.focusOutEvent = tree_focus_out
        self.tree_container.keyPressEvent = tree_key_press
        self.tree_container.keyReleaseEvent = tree_key_release
        
        
        tree_layout = QVBoxLayout(self.tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create preview widget
        self.preview_widget = PreviewWidget(self)
        self.preview_widget.setFocusPolicy(Qt.NoFocus)  # Not in tab order

        from sidebar_jobs_widget import SidebarJobsWidget

        self.sidebar_jobs_widget = SidebarJobsWidget(self)
        self.sidebar_jobs_widget.setFocusPolicy(Qt.NoFocus)
        
        # Set widgets in combined sidebar
        self.combined_sidebar.set_tree_widget(self.tree_container)
        self.combined_sidebar.set_preview_widget(self.preview_widget)
        
        # Create main content area
        self.main_content_widget = QWidget()
        self.main_content_widget.setFocusPolicy(Qt.StrongFocus)  # Allow focus for tab navigation
        
        # Add focus event handler to ensure proper focus handling
        def main_content_focus_in(event):
            QWidget.focusInEvent(self.main_content_widget, event)
            # Only move focus to the thumbnail/list canvas when that view is active.
            # In browse mode the thumbnail stack page is hidden; focusing it breaks keys and
            # QAction shortcuts (e.g. A for actual size) because focus lands on a hidden widget.
            mode = getattr(self, 'current_view_mode', None)
            if mode == 'thumbnail' and getattr(self, 'thumbnail_container', None):
                self.thumbnail_container.setFocus()
            elif mode == 'list' and getattr(self, 'list_view_container', None):
                if hasattr(self.list_view_container, 'canvas'):
                    self.list_view_container.canvas.setFocus()
        
        self.main_content_widget.focusInEvent = main_content_focus_in

        # Install event filter to catch F2 for thumbnail rename (main_content_widget receives key events when it has focus)
        self.main_content_widget.installEventFilter(self)
        
        self.main_content_layout = QVBoxLayout(self.main_content_widget)
        self.main_content_layout.setContentsMargins(0, 0, 0, 0)
        
        # Tab order will be set later after both widgets are in the layout
        
        
        self.stacked_widget = QStackedWidget()
        # ========================================================================
        # CRITICAL: Set NoFocus to prevent stacked_widget from being in tab order
        # ========================================================================
        # DO NOT CHANGE THIS! The stacked_widget must have NoFocus policy
        # to prevent it from being in the tab order. Only tree_container and
        # main_content_widget should be in the tab order.
        # ========================================================================
        self.stacked_widget.setFocusPolicy(Qt.NoFocus)
        self.main_content_layout.addWidget(self.stacked_widget)
        
        # Create right_sidebar combined widget (Organize + Information + Jobs)
        self.right_sidebar = RightSidebarCombinedWidget(self, self)
        self.right_sidebar.set_jobs_widget(self.sidebar_jobs_widget)
        self.right_sidebar.widget_resized.connect(self._on_sidebar_resized)
        self.right_sidebar.visibility_changed.connect(self._apply_right_sidebar_visibility)
        self.right_sidebar_visible = (
            self.right_sidebar.is_information_visible()
            or self.right_sidebar.is_shortcuts_visible()
            or self.right_sidebar.is_jobs_visible()
        )

        # Add widgets to splitter: left sidebar, main content, right sidebar
        self.main_splitter.addWidget(self.combined_sidebar)
        self.main_splitter.addWidget(self.main_content_widget)
        self.main_splitter.addWidget(self.right_sidebar)
        
        # Set splitter sizes IMMEDIATELY after adding widgets to prevent Qt from calculating default sizes
        # Use a large initial width estimate - will be corrected once window is shown
        estimated_width = 1920  # Reasonable default for most screens
        left_width = self.sidebar_width if self._any_left_sidebar_pane_visible() else 0
        right_width = self.right_sidebar_width if self.right_sidebar_visible else 0
        main_width = estimated_width - left_width - right_width
        self._set_splitter_sizes_safe([left_width, main_width, right_width])
        
        # ========================================================================
        # CRITICAL TAB ORDER FIX - DO NOT MODIFY WITHOUT PERMISSION
        # ========================================================================
        # This tab order setup is CRITICAL for proper keyboard navigation.
        # ONLY the tree_container and main_content_widget should be in the tab order.
        # 
        # WARNING: DO NOT ADD ANY OTHER WIDGETS TO THE TAB ORDER!
        # WARNING: DO NOT CHANGE THE FOCUS POLICIES OF THESE WIDGETS!
        # WARNING: DO NOT ADD setTabOrder() CALLS FOR OTHER WIDGETS!
        # 
        # The tab key should ONLY cycle between:
        # 1. combined_sidebar (file tree and preview)
        # 2. main_content_widget (canvas/browse area)
        # 
        # All other widgets (stacked_widget, thumbnail_container, file_tree, etc.) have
        # NoFocus policy to prevent them from being in the tab order.
        # 
        # If you need to add new widgets, make sure they have NoFocus policy
        # unless they are specifically meant to be part of the tab order.
        # ========================================================================
        self.tree_container.setFocusPolicy(Qt.NoFocus)
        self.preview_widget.setFocusPolicy(Qt.NoFocus)
        # Set NoFocus on all direct children of combined_sidebar that support setFocusPolicy
        for child in self.combined_sidebar.findChildren(QWidget):
            if hasattr(child, 'setFocusPolicy'):
                child.setFocusPolicy(Qt.NoFocus)
        self.tree_container.setFocusPolicy(Qt.StrongFocus)
 
        self.combined_sidebar.setFocusPolicy(Qt.NoFocus)
        self.main_content_widget.setFocusPolicy(Qt.StrongFocus)
        self.setTabOrder(self.combined_sidebar, self.main_content_widget)
        
        # Install event filter to catch keyboard events since main window has NoFocus
        self.installEventFilter(self)
        
        # Install app-level filter for shift-cmd-E so it works immediately (before menu shown or view switch)
        self._shortcut_event_filter = ShiftCmdEShortcutFilter(self)
        QApplication.instance().installEventFilter(self._shortcut_event_filter)

        # F4 toggle chrome (sidebars + status bar)
        self._chrome_toggle_filter = ChromeToggleShortcutFilter(self)
        QApplication.instance().installEventFilter(self._chrome_toggle_filter)
        
        # Install app-level filter for status bar peek (catch MouseMove from any child widget)
        self._status_bar_peek_filter = StatusBarPeekFilter(self)
        QApplication.instance().installEventFilter(self._status_bar_peek_filter)

        self._chrome_saved_layout = None
        self._chrome_suppressed = False
        
        # Set initial focus to canvas area
        QTimer.singleShot(200, self._set_initial_focus)
        
        # Temporarily disconnect visibility change handlers to prevent them from
        # overriding the saved width during initialization
        self.combined_sidebar.tree_visibility_changed.disconnect()
        self.combined_sidebar.preview_visibility_changed.disconnect()
        
        # Set initial splitter sizes based on sidebar visibility
        # Use a timer to ensure the splitter has been properly sized
        def set_initial_sizes():
            total_width = self.main_splitter.width()
            if total_width == 0:
                # Splitter not ready yet, try again
                QTimer.singleShot(50, set_initial_sizes)
                return
            
            left_width = 0
            right_width = 0
            
            # Calculate left sidebar width using saved width
            if self._any_left_sidebar_pane_visible():
                left_width = self.sidebar_width
            
            # Calculate right sidebar width
            if self.right_sidebar_visible:
                right_width = self.right_sidebar_width
            
            # Ensure at least one column of thumbnails is visible
            min_thumb_width = 200
            available_width = total_width - left_width - right_width
            if available_width < min_thumb_width:
                if right_width > 0:
                    right_width = max(0, total_width - left_width - min_thumb_width)
                    self.right_sidebar_width = right_width
            
            # Set splitter sizes: [left_sidebar, main_content, right_sidebar]
            main_width = total_width - left_width - right_width
            self._set_splitter_sizes_safe([left_width, main_width, right_width])
            
            # Update right sidebar visibility
            if self.right_sidebar_visible:
                self.right_sidebar.show()
                self.right_sidebar.show_info()
            else:
                self.right_sidebar.hide()
                self.right_sidebar.hide_info()
            
            # Set visibility states (handlers are disconnected so they won't override sizes)
            self.combined_sidebar.set_tree_visible(self.file_tree_visible)
            self.combined_sidebar.set_preview_visible(self.preview_visible)
            self.right_sidebar.set_jobs_visible(self.jobs_visible)
            self.right_sidebar_visible = (
                self.right_sidebar.is_information_visible()
                or self.right_sidebar.is_shortcuts_visible()
                or self.right_sidebar.is_jobs_visible()
            )
            
            # Update preview widget's internal visibility flag
            self.preview_widget.preview_visible = self.preview_visible
            
            # Initialize tree if it should be visible at startup
            if self.file_tree_visible:
                self.ensure_tree_initialized()
            
            # Update preview if it should be visible at startup
            if self.preview_visible:
                self.preview_widget.update_preview()
            
            # Reconnect visibility change handlers
            self.combined_sidebar.tree_visibility_changed.connect(self._on_tree_visibility_changed)
            self.combined_sidebar.preview_visibility_changed.connect(self._on_preview_visibility_changed)
            
            # Enforce saved width after initialization completes
            def enforce_saved_width():
                if self.main_splitter.width() > 0:
                    total_width = self.main_splitter.width()
                    left_width = self.sidebar_width if self._any_left_sidebar_pane_visible() else 0
                    right_width = self.right_sidebar_width if self.right_sidebar_visible else 0
                    main_width = total_width - left_width - right_width
                    self._set_splitter_sizes_safe([left_width, main_width, right_width])
            
            QTimer.singleShot(150, enforce_saved_width)
        
        QTimer.singleShot(100, set_initial_sizes)
        
        # Initialize sidebar visibility for thumbnail mode
        QTimer.singleShot(200, lambda: self.manage_sidebar_visibility_for_view_mode('thumbnail'))
        
        self.main_splitter.setCollapsible(0, True)  # Make left sidebar collapsible
        self.main_splitter.setCollapsible(2, True)  # Make right sidebar collapsible
        self.main_splitter.setStretchFactor(0, 0)  # Left sidebar doesn't stretch
        self.main_splitter.setStretchFactor(1, 1)  # Main content stretches to fill
        self.main_splitter.setStretchFactor(2, 0)  # Right sidebar doesn't stretch
        self.main_splitter.setHandleWidth(get_active_theme().view_border_width_px)
        
        # Flag to prevent splitterMoved from overriding saved width during programmatic changes
        self._suppress_splitter_moved = False
        
        # Style the splitter handle to make it more visible
        self.main_splitter.setStyleSheet(get_active_theme().main_splitter_stylesheet())
        
        # Connect splitter resize to update thumbnail layout
        self.main_splitter.splitterMoved.connect(self._on_splitter_moved)
        
        # Setup thumbnail and browse views
        self.view_manager.setup_thumbnail_view()
        self.view_manager.setup_browse_view()
        self.view_manager.setup_list_view()
        
        # Setup status bar
        self.status_bar = QStatusBar()
        # Completely disable the default message area
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setFocusPolicy(Qt.NoFocus)
        self.status_bar.setContentsMargins(0, 0, 0, 0)
        # Set a custom style to remove any reserved space for messages
        self.status_bar.setStyleSheet(get_active_theme().main_status_bar_chrome_stylesheet())
        self.setStatusBar(self.status_bar)
        self.status_bar.setMinimumHeight(0)  # Allow shrink for slide animation
        
        self._status_bar_anim = QPropertyAnimation(self.status_bar, b"maximumHeight")
        self._status_bar_anim.setDuration(STATUS_BAR_ANIM_MS)
        self._status_bar_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._status_bar_anim.finished.connect(self._on_status_bar_anim_finished)
        self._status_bar_anim.valueChanged.connect(self._on_status_bar_anim_value_changed)
        self._status_bar_anim_callback = None  # Optional callback when anim finishes (for toggle)
        
        # Set initial visibility based on config
        status_bar_config = self.config.load_settings().get('status_bar_visible', True)
        if not status_bar_config:
            self.status_bar.hide()
        
        # Create progress bar as standalone widget at bottom of screen
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(20)
        # Set window flags to ensure it stays on top
        self.progress_bar.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.progress_bar.setParent(self)  # Ensure it's a child of main window
        self.progress_bar.setStyleSheet(get_active_theme().floating_progress_bar_stylesheet())
        
        
        # Position progress bar at bottom of screen, full width
        self._position_progress_bars()
        
        # Initialize progress bar with default values
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("")
        
        self.thumbnail_status_label = QLabel()
        self.thumbnail_status_label.setStyleSheet(get_active_theme().thumbnail_status_label_stylesheet())
        self.thumbnail_status_label.hide()
        
        # File count is now handled by the status bar manager
        
        # Initialize enhanced status bar manager
        self.status_bar_manager = StatusBarManager(self.status_bar)
        self.status_bar_manager.main_window = self
        self.status_bar_manager.set_main_window(self)
        

    #
    # Action Matrix:
    # | Action             | Thumbnail   | Fullscreen   | Slideshow   | Notes                                   |
    # |--------------------|-------------|-------------|-------------|-----------------------------------------|
    # | toggle_file_tree   | T           | F           | F           | (cmd-t)                                 |
    # | toggle_preview     | T           | F           | F           | (cmd-p)                                 |
    # | toggle_status_bar  | T           | T           | T           | (b)                                     |
    # | fullscreen         | T           | T           | T           | (f)                                     |
    # | edit_in_editor     | T / !msel   | T           | F / !msel   | (cmd-e), visible except in msel/ss mode |
    # | native_fullscreen  | T           | T           | T           | (cmd-ctrl-f)                            |
    # | exit_fullscreen    | T           | T           | T           | (f)                                     |
    # | toggle_filename    | T           | F           | T           | (cmd-n)                                 |
    # | wallpaper          | T           | T           | T           | (cmd-shift-w)                           |
    # | actual_size        | F           | F           | F           | (a)                                     |
    # | similarity         | T           | T           | F           | (cmd-k)                                 |
     #
    # Legend:
    #   T      = True (enabled/visible)
    #   F      = False (disabled/hidden)
    #   !msel  = only if not in multi_select_mode

    def update_view_menu_enabled_states(self):
        """Update the enabled states of the view menu actions"""
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_view_menu_enabled_states()

    def _wire_settings_dialog_signals(self):
        """Connect settings dialog signals once per dialog instance (avoids disconnect warnings)."""
        dlg = self.settings_dialog
        if dlg is None or getattr(dlg, "_main_window_signals_wired", False):
            return
        dlg.settings_changed.connect(self.on_settings_changed)
        dlg.accepted.connect(self._schedule_post_settings_menu_refresh)
        dlg._main_window_signals_wired = True

    def _schedule_post_settings_menu_refresh(self):
        """Refresh File>Favorites, Move menu shortcuts, and sidebar after settings dialog closes.

        Deferred so macOS can finish tearing down the modal menu bar before we rebuild menus.
        Called from on_settings_changed and from SettingsDialog.accepted as a backup.
        """
        QTimer.singleShot(100, self._refresh_menus_after_settings)

    def _refresh_menus_after_settings(self):
        """Apply favorite_directories and move_destinations from disk to menus and key bindings."""
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_file_menu_favorites()
            self.menu_manager.update_edit_menu_states()
        if getattr(self, 'keyboard_handler_manager', None):
            self.keyboard_handler_manager.refresh_favorite_bindings()
        if (
            getattr(self, 'right_sidebar', None)
            and hasattr(self.right_sidebar, 'shortcuts_widget')
            and self.right_sidebar.shortcuts_widget
            and self.right_sidebar.is_shortcuts_visible()
        ):
            self.right_sidebar.shortcuts_widget.refresh_shortcuts()

    def update_edit_menu_states(self):
        """Update the enabled states and text of edit menu actions based on view mode and last drop location"""
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_edit_menu_states()

    def move_to_last_drop_location(self, copy_only=None):
        """Move or copy selected files (or active file) to the last drop location"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.move_to_last_drop_location(copy_only=copy_only)

    def move_to_destination(self, destination_index: int, copy_only=None):
        """Move or copy selected files to the specified destination (1-9)"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.move_to_destination(destination_index, copy_only=copy_only)

    def move_work_files(self):
        """Move files from current directory to a newly named directory"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
        from PySide6.QtCore import Qt
        
        # Get current directory
        current_dir = None
        if getattr(self, 'current_directory', None):
            current_dir = self.current_directory
        elif getattr(self, 'displayed_images', None):
            current_dir = os.path.dirname(self.displayed_images[0])
        
        if not current_dir:
            show_styled_critical(self, "Error", "No current directory found.")
            return
        
        # Normalize the path to ensure it's correct (remove trailing slashes, resolve .., etc.)
        current_dir = os.path.normpath(os.path.abspath(current_dir))
        # Ensure no trailing slash (important for os.path.dirname to work correctly)
        current_dir = current_dir.rstrip('/')
        
        # Check if directory still exists
        if not os.path.exists(current_dir) or not os.path.isdir(current_dir):
            show_styled_critical(self, "Error", f"The directory no longer exists:\n\n{current_dir}")
            return
        
        # Verify that "work" directory exists as either a sibling or child of current directory
        parent_dir = os.path.dirname(current_dir)
        work_dir_sibling = os.path.join(parent_dir, 'work')
        work_dir_child = os.path.join(current_dir, 'work')
        
        work_dir_path = None
        if os.path.exists(work_dir_sibling) and os.path.isdir(work_dir_sibling):
            work_dir_path = work_dir_sibling
        elif os.path.exists(work_dir_child) and os.path.isdir(work_dir_child):
            work_dir_path = work_dir_child
        
        if not work_dir_path:
            show_styled_critical(self, "Error", 
                               f"A 'work' directory must exist as either a sibling or child of the current directory.\n\n"
                               f"Current directory: {current_dir}\n"
                               f"Checked sibling: {work_dir_sibling}\n"
                               f"Checked child: {work_dir_child}\n\n"
                               f"Neither 'work' directory exists.")
            return
        
        # Determine the parent directory of work (where destination will be created)
        work_parent_dir = os.path.dirname(work_dir_path)
        
        # Get all image files in the work directory (excluding hidden and non-image files)
        try:
            files_to_move = []
            image_extensions = get_image_extensions()
            for entry in os.scandir(work_dir_path):
                if entry.is_file():
                    # Skip hidden files (files starting with .)
                    filename = entry.name
                    if filename.startswith('.'):
                        continue
                    
                    # Check if file is an image file
                    _, ext = os.path.splitext(filename)
                    if ext.lower() in image_extensions:
                        files_to_move.append(entry.path)
        except Exception as e:
            show_styled_critical(self, "Error", f"Cannot read work directory:\n\n{str(e)}")
            return
        
        if not files_to_move:
            show_styled_information(self, "Information", f"No files to move in the work directory:\n\n{work_dir_path}")
            return
        
        # Create custom input dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("Move files")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Label
        label = QLabel("Enter directory name (will be created at same level as 'work' directory):")
        layout.addWidget(label)
        
        # Input field
        input_field = QLineEdit()
        input_field.setPlaceholderText("Directory name")
        layout.addWidget(input_field)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Cancel button (left, default)
        cancel_button = QPushButton("Cancel")
        cancel_button.setDefault(True)
        cancel_button.clicked.connect(dialog.reject)
        
        # Move button (right)
        move_button = QPushButton("Move")
        move_button.setEnabled(False)  # Initially disabled
        move_button.clicked.connect(dialog.accept)
        
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(move_button)
        layout.addLayout(button_layout)
        
        # Validation function
        def validate_name(text):
            """Validate directory name and enable/disable Move button"""
            text = text.strip()
            if not text:
                move_button.setEnabled(False)
                return False
            
            # Check for invalid characters (on macOS, / is the main concern)
            if '/' in text or text in ['.', '..']:
                move_button.setEnabled(False)
                return False
            
            # Check if name is valid (not empty after strip)
            move_button.setEnabled(True)
            return True
        
        # Connect text changed signal for live validation
        input_field.textChanged.connect(validate_name)
        
        # Handle Enter key in input field
        def on_enter_pressed():
            if move_button.isEnabled():
                dialog.accept()
        input_field.returnPressed.connect(on_enter_pressed)
        
        # Set focus on input field
        input_field.setFocus()
        
        # Execute dialog
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        # Get the directory name
        new_dir_name = input_field.text().strip()
        if not validate_name(new_dir_name):
            return
        
        # Create destination at the same level as the work directory
        new_dir_path = os.path.join(work_parent_dir, new_dir_name)
        
        # Verify the target path exists and is a directory (or create it)
        if os.path.exists(new_dir_path):
            if not os.path.isdir(new_dir_path):
                show_styled_critical(self, "Error", f"Target path exists but is not a directory:\n\n{new_dir_path}")
                return
        else:
            # Create the new directory if it doesn't exist
            try:
                os.makedirs(new_dir_path, exist_ok=True)
            except Exception as e:
                show_styled_critical(self, "Error", f"Cannot create directory:\n\n{str(e)}")
                return
        
        # Initialize file move handler if needed
        if not hasattr(self, 'file_move_handler') or self.file_move_handler is None:
            self.file_move_handler = FileMoveHandler(self)
        
        # Move files with conflict resolution
        # Check for Photos Library operations
        from utils import is_inside_photos_library, show_styled_warning
        
        # Check if target directory is a Photos Library
        if is_inside_photos_library(new_dir_path):
            show_styled_warning(
                self,
                "Operation Not Allowed",
                "Adding files to macOS Photos Library is not allowed.\n\n"
                "Please use the Photos app to add files to your Photos Library."
            )
            return
        
        # Check if any source files are in Photos Library (prevent moving within library)
        photos_library_files = [f for f in files_to_move if is_inside_photos_library(f)]
        if photos_library_files:
            show_styled_warning(
                self,
                "Operation Not Allowed",
                "Moving files within macOS Photos Library is not allowed.\n\n"
                "Photos Library files cannot be moved, renamed, or modified within the library.\n"
                "You can drag files OUT of the Photos Library to other locations."
            )
            return
        
        # Show progress dialog for > 10 files
        progress_dialog = None
        if len(files_to_move) > 10:
            from utils import create_file_operation_progress_dialog
            progress_dialog = create_file_operation_progress_dialog(
                self, "Moving Files", len(files_to_move)
            )
        
        moved_count = 0
        skipped_count = 0
        errors = []
        
        for idx, source_path in enumerate(files_to_move):
            # Update progress if dialog is shown
            if progress_dialog:
                progress_dialog.setValue(idx)
                progress_dialog.setLabelText(f"Moving file {idx + 1} of {len(files_to_move)}")
                QApplication.processEvents()
            # Generate unique target path (handles conflicts automatically)
            source_filename = os.path.basename(source_path)
            target_path = os.path.join(new_dir_path, source_filename)
            
            # Check if target exists and generate unique name if needed
            if os.path.exists(target_path):
                # Use FileMoveHandler's generate_renamed_path to create unique name
                target_path = self.file_move_handler.generate_renamed_path(new_dir_path, source_filename)
                if target_path is None:
                    errors.append(f"Cannot generate unique name for: {source_filename}")
                    skipped_count += 1
                    continue
            
            # Move the file
            try:
                shutil.copy2(source_path, target_path)
                os.remove(source_path)
                moved_count += 1
            except Exception as e:
                errors.append(f"Error moving {source_filename}: {str(e)}")
                skipped_count += 1
                # Remove copied file if move failed
                if os.path.exists(target_path):
                    try:
                        os.remove(target_path)
                    except Exception:
                        pass
        
        # Close progress dialog if it was shown
        if progress_dialog:
            progress_dialog.setValue(len(files_to_move))
            progress_dialog.close()
        
        # Show result message
        if errors:
            error_msg = "\n".join(errors[:10])  # Show first 10 errors
            if len(errors) > 10:
                error_msg += f"\n... and {len(errors) - 10} more errors"
            show_styled_warning(self, "Move Completed with Errors", 
                              f"Moved {moved_count} {file_string(moved_count)}, skipped {skipped_count} {file_string(skipped_count)}.\n\nErrors:\n{error_msg}")
        elif moved_count > 0:
            show_styled_information(self, "Move Completed", 
                                   f"Successfully moved {moved_count} {file_string(moved_count)} to '{new_dir_name}'.")
        
        # Refresh the directory view
        if moved_count > 0:
            # Remove moved files from displayed images
            if hasattr(self, 'remove_thumbnails_for_files'):
                self.thumbnail_display_manager.remove_thumbnails_for_files(files_to_move)
            
            # Refresh directory
            if hasattr(self, 'refresh_directory'):
                self.refresh_directory()

    def update_file_menu_recent_directories(self):
        """
        Update the File menu's Recent Directories submenu.
        Assumes the File menu is always present and valid.
        No recreation or deletion logic.
        """
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_file_menu_recent_directories()

    def open_directory(self, directory: str):
        """Open a directory"""
        # Clear any pending highlight when directory changes
        if hasattr(self, '_pending_highlight'):
            self._pending_highlight = None
        
        # Save current state before opening new directory (for ESC navigation)
        try:
            self.directory_stack_history_handler.save_current_state("image_browser_window.open_directory", delay=0.0)
        except Exception:
            pass
        self.load_directory(directory, external_load=True)

    def open_favorite(self, index: int):
        """Open favorite at index (0-8 for Ctrl+1 through Ctrl+9). Same behavior as keyboard shortcut."""
        settings = self.config.load_settings()
        favorites = (settings.get('favorite_directories', [None] * 9) + [None] * 9)[:9]
        if 0 <= index < len(favorites) and favorites[index]:
            favorite_path = favorites[index].strip()
            if favorite_path and os.path.exists(favorite_path):
                try:
                    self.directory_stack_history_handler.save_current_state(
                        "image_browser_window.open_favorite", delay=0.0)
                except Exception:
                    pass
                is_directory = os.path.isdir(favorite_path)
                is_image_file = False
                if not is_directory and os.path.isfile(favorite_path):
                    _, ext = os.path.splitext(favorite_path)
                    is_image_file = ext.lower() in get_image_extensions()
                if is_directory:
                    if hasattr(self, 'file_tree_handler') and self.file_tree_handler:
                        try:
                            self.file_tree_handler.request_directory_opening(favorite_path)
                        except Exception:
                            self.load_directory(favorite_path, external_load=True)
                    else:
                        self.load_directory(favorite_path, external_load=True)
                elif is_image_file and hasattr(self, 'load_specific_files'):
                    self.load_specific_files([favorite_path], external_load=True)

    def toggle_file_tree(self):
        """Toggle the visibility of the file tree and resize canvas accordingly"""
        self._chrome_suppressed = False
        return self.sidebar_manager.toggle_file_tree()
    
    def toggle_rename_status(self):
        """Toggle rename status checking"""
        return self.sidebar_manager.toggle_rename_status()
    
    def update_rename_status_for_directory(self, directory: str):
        """Update rename status for a specific directory and refresh its checkmark without rebuilding tree."""
        return self.sidebar_manager.update_rename_status_for_directory(directory)
    
    def update_rename_status(self, full_scan=False):
        """Update rename status for visible directories in tree. full_scan=True scans all relevant dirs."""
        return self.sidebar_manager.update_rename_status(full_scan=full_scan)
    
    def toggle_list_view(self):
        """Toggle list view mode"""
        if self.current_view_mode == 'list':
            # Already in list view, switch back to thumbnail view
            # Convert FILESIZE mode back to SIZE mode (FILESIZE is list-view specific)
            from sort_mode import SortMode
            if getattr(self, 'current_sort_mode', None) == SortMode.FILESIZE:
                self.current_sort_mode = SortMode.SIZE
                if hasattr(self, 'sorting_manager'):
                    self.sorting_manager.save_sorting_settings()
            
            self.stacked_widget.setCurrentIndex(0)
            self.current_view_mode = 'thumbnail'
            self._emit_view_mode_changed()
            if hasattr(self, 'list_view_action'):
                self.list_view_action.setChecked(False)
            # Restore sidebar visibility
            self.manage_sidebar_visibility_for_view_mode('thumbnail')
            # Prime and enable menu keys for view change
            if hasattr(self, 'menu_manager'):
                self.menu_manager.prime_menu_keys_for_view_change()
            # CRITICAL: Reset focus to thumbnail canvas to ensure keyboard events work properly
            # This prevents list view from intercepting keyboard events after switching back
            QTimer.singleShot(100, self.focus_canvas)
            # CRITICAL: Refresh highlight and status bar to ensure UI is in sync after switching views
            QTimer.singleShot(50, self.highlight_image)
        else:
            # Switch to list view
            if not hasattr(self, 'list_view_container') or not self.list_view_container:
                # List view not initialized yet, initialize it
                self.view_manager.setup_list_view()
            
            # Update list view with current images
            self.view_manager.update_list_view()
            
            # Switch to list view
            self.stacked_widget.setCurrentIndex(2)  # List view is index 2
            self.current_view_mode = 'list'
            self._emit_view_mode_changed()
            if hasattr(self, 'list_view_action'):
                self.list_view_action.setChecked(True)
            
            # Manage sidebar visibility for list view (same as thumbnail view)
            self.manage_sidebar_visibility_for_view_mode('list')
            
            # Prime and enable menu keys for view change
            if hasattr(self, 'menu_manager'):
                self.menu_manager.prime_menu_keys_for_view_change()
            
            # Give focus to canvas so keyboard events work
            if getattr(self, 'list_view_container', None):
                QTimer.singleShot(100, lambda: self.list_view_container.canvas.setFocus())

    def show_jobs_pane(self) -> bool:
        """Show the jobs pane in the right combined sidebar (idempotent)."""
        if hasattr(self, "right_sidebar"):
            self.right_sidebar.set_jobs_visible(True)
            return self.right_sidebar.is_jobs_visible()
        return False

    def toggle_jobs(self):
        """Toggle the jobs pane in the right combined sidebar."""
        self._chrome_suppressed = False
        if hasattr(self, "sidebar_manager"):
            return self.sidebar_manager.toggle_jobs()
        if hasattr(self, "right_sidebar"):
            self.right_sidebar.set_jobs_visible(
                not self.right_sidebar.is_jobs_visible()
            )
            return self.right_sidebar.is_jobs_visible()
        return False

    def toggle_preview(self):
        """Toggle the visibility of the preview widget and resize canvas accordingly"""
        self._chrome_suppressed = False
        if hasattr(self, 'sidebar_manager'):
            return self.sidebar_manager.toggle_preview()
        if hasattr(self, 'combined_sidebar'):
            self.combined_sidebar.set_preview_visible(not self.combined_sidebar.is_preview_visible())
            return self.combined_sidebar.is_preview_visible()
        else:
            # Fallback to old behavior if combined sidebar not available
            if not hasattr(self, 'preview_widget'):
                return False
                
            # Hide tree if it's visible (they can't both be shown at the same time)
            if self.tree_container.isVisible():
                self.tree_container.hide()
                self.file_tree_visible = False
                if hasattr(self, 'toggle_file_tree_action'):
                    self.toggle_file_tree_action.setChecked(False)
                    self.toggle_file_tree_action.setText('Show File Tree')
                
                # Handle browse mode - resize image container when tree view is hidden
                if self.current_view_mode == 'browse':
                    if hasattr(self, 'image_container'):
                        old_w = self.cached_container_width
                        old_h = self.cached_container_height
                        available_size = self.get_effective_display_size()
                        self.image_container.resize(available_size)
                        self._handle_browse_viewport_resize_after_container_change(old_w, old_h)
            
            # Toggle preview visibility
            was_visible = self.preview_widget.is_visible()
            preview_visible = self.preview_widget.toggle_visibility()
            
            if preview_visible:
                # Show preview widget
                self.preview_widget.show()
                # Set splitter sizes to give sidebar space
                total_width = self.main_splitter.width()
                self._set_splitter_sizes_safe([self.sidebar_width, total_width - self.sidebar_width])
                # Save the width setting since setSizes doesn't trigger splitterMoved
                self.config.update_setting('sidebar_width', self.sidebar_width)
                # If transitioning from hidden to visible, force reload to ensure image is up to date
                if not was_visible:
                    # Clear cached pixmap to force reload
                    self.preview_widget.current_pixmap = None
                    self.preview_widget.current_image_path = None
                    # Force update with reload
                    self.preview_widget.update_preview(force=True)
                else:
                    # Update preview with current image
                    self.preview_widget.update_preview()
            else:
                # Hide preview widget
                self.preview_widget.hide()
                # Hide sidebar if no components are visible
                total_width = self.main_splitter.width()
                if not self._any_left_sidebar_pane_visible():
                    self._set_splitter_sizes_safe([0, total_width])
                else:
                    self._set_splitter_sizes_safe([self.sidebar_width, total_width - self.sidebar_width])
            
            # Update MAX_THUMBNAIL_SIZE based on new container dimensions
            QTimer.singleShot(50, self.update_max_thumbnail_size)
            
            # Force canvas to recalculate layout after toggle
            QTimer.singleShot(100, self.update_layout_after_splitter_resize)
            
            return preview_visible
    
    def toggle_preview_fit_mode(self):
        """Toggle the preview widget between fit and actual size modes"""
        if not hasattr(self, 'preview_widget') or not self.preview_widget.is_visible():
            return False
            
        self.preview_widget.toggle_fit_mode()
        return True
    
    def _is_file_tree_showing(self):
        """Check if file tree is visible using state variable (isVisible() was unreliable)."""
        if getattr(self, 'file_tree_visible', False):
            return True
        if getattr(self, 'combined_sidebar', None) and self.combined_sidebar.is_tree_visible():
            return True
        return False

    def update_preview_if_visible(self):
        """Update the preview widget if it's currently visible"""
        if getattr(self, 'preview_widget', None) and self.preview_widget.is_visible():
            self.preview_widget.update_preview()
    
    def manage_sidebar_visibility_for_view_mode(self, view_mode):
        """Manage sidebar visibility based on current view mode"""
        if getattr(self, '_chrome_suppressed', False):
            total_width = self.main_splitter.width()
            if total_width > 0:
                self._set_splitter_sizes_safe([0, total_width, 0])
            if hasattr(self, 'combined_sidebar'):
                self.combined_sidebar.hide()
            if hasattr(self, 'right_sidebar'):
                self.right_sidebar.hide()
            return
        if view_mode == 'list':
            # Show sidebars in list view (same as thumbnail view)
            # Use the same sidebar visibility logic as thumbnail view
            if not hasattr(self, 'combined_sidebar'):
                return
            
            total_width = self.main_splitter.width()
            if total_width == 0:
                return
            
            # Get current splitter sizes to check if sidebar width is already correct
            current_sizes = self.main_splitter.sizes()
            current_left_width = current_sizes[0] if len(current_sizes) > 0 else 0
            
            left_width = 0
            right_width = 0
            
            # Show left sidebar if any combined pane is visible
            if self._any_left_sidebar_pane_visible():
                left_width = self.sidebar_width if current_left_width == 0 else current_left_width
                self.combined_sidebar.show()
            else:
                self.combined_sidebar.hide()
            
            # Show right sidebar if Information sidebar is visible
            if self.right_sidebar_visible:
                right_width = self.right_sidebar_width
                if hasattr(self, 'right_sidebar'):
                    self.right_sidebar.show()
            else:
                if hasattr(self, 'right_sidebar'):
                    self.right_sidebar.hide()
            
            # Calculate main content width
            main_width = total_width - left_width - right_width
            
            # Set splitter sizes
            if total_width > 0:
                self._set_splitter_sizes_safe([left_width, main_width, right_width])
            return
        if not hasattr(self, 'combined_sidebar'):
            return
        
        total_width = self.main_splitter.width()
        if total_width == 0:
            return
        
        # Get current splitter sizes to check if sidebar width is already correct
        current_sizes = self.main_splitter.sizes()
        current_left_width = current_sizes[0] if len(current_sizes) > 0 else 0
        
        left_width = 0
        right_width = 0
        
        if view_mode == 'list':
            # Hide sidebars in list view (similar to browse view)
            self.combined_sidebar.hide()
            if hasattr(self, 'right_sidebar'):
                self.right_sidebar.hide()
            # Set splitter sizes to give full width to list view
            self._set_splitter_sizes_safe([0, total_width, 0])
            return
        
        if view_mode == 'thumbnail':
            if self._any_left_sidebar_pane_visible():
                self.combined_sidebar.show()
                # Ensure tree is initialized when showing sidebar (critical when exiting browse mode)
                if self.file_tree_visible or self.combined_sidebar.is_tree_visible():
                    self.ensure_tree_initialized()
                left_width = self.sidebar_width
            else:
                self.combined_sidebar.hide()
            
            # Restore right sidebar visibility if it was saved before slideshow
            if getattr(self, '_right_sidebar_visible_before_slideshow', None) is not None:
                self.right_sidebar_visible = self._right_sidebar_visible_before_slideshow
                self._right_sidebar_visible_before_slideshow = None
            
            if getattr(self, 'right_sidebar_visible', None):
                if hasattr(self, 'right_sidebar'):
                    self.right_sidebar.show()
                    self.right_sidebar.show_info()
                right_width = self.right_sidebar_width
            else:
                if hasattr(self, 'right_sidebar'):
                    self.right_sidebar.hide()
                    self.right_sidebar.hide_info()
            
            # Only update splitter sizes if they need to change
            if current_left_width != left_width or current_sizes[2] != right_width:
                # Ensure at least one column of thumbnails is visible
                min_thumb_width = 200
                available_width = total_width - left_width - right_width
                if available_width < min_thumb_width:
                    if right_width > 0:
                        right_width = max(0, total_width - left_width - min_thumb_width)
                        self.right_sidebar_width = right_width
                        self.config.update_setting('right_sidebar_width', self.right_sidebar_width)
                
                # Set splitter sizes using saved sidebar_width
                main_width = total_width - left_width - right_width
                self._set_splitter_sizes_safe([left_width, main_width, right_width])
                self.config.update_setting('sidebar_width', self.sidebar_width)
        elif view_mode in ['slideshow', 'slideshow2', 'slideshow3']:
            # In slideshow modes, hide both sidebars
            if self.combined_sidebar.isVisible():
                # Hide the entire left sidebar
                self.combined_sidebar.hide()
            
            # Save current right sidebar visibility state before hiding it
            if not hasattr(self, '_right_sidebar_visible_before_slideshow') or self._right_sidebar_visible_before_slideshow is None:
                self._right_sidebar_visible_before_slideshow = self.right_sidebar_visible if hasattr(self, 'right_sidebar_visible') else False
            
            # Hide right sidebar (Information sidebar) during slideshow
            if hasattr(self, 'right_sidebar'):
                self.right_sidebar.hide()
                self.right_sidebar.hide_info()
            
            # Set splitter sizes: [left_sidebar, main_content, right_sidebar]
            main_width = total_width
            self._set_splitter_sizes_safe([0, main_width, 0])
        else:
            # In browse mode, hide left sidebar but show right sidebar if it was visible
            if self.combined_sidebar.isVisible():
                # Hide the entire left sidebar
                self.combined_sidebar.hide()
            
            # Restore right sidebar visibility if it was saved before slideshow
            if getattr(self, '_right_sidebar_visible_before_slideshow', None) is not None:
                self.right_sidebar_visible = self._right_sidebar_visible_before_slideshow
                self._right_sidebar_visible_before_slideshow = None
            
            # Show right sidebar if it was visible
            if getattr(self, 'right_sidebar_visible', None):
                if hasattr(self, 'right_sidebar'):
                    self.right_sidebar.show()
                    self.right_sidebar.show_info()
                right_width = self.right_sidebar_width
            else:
                if hasattr(self, 'right_sidebar'):
                    self.right_sidebar.hide()
                    self.right_sidebar.hide_info()
            
            # Set splitter sizes: [left_sidebar, main_content, right_sidebar]
            main_width = total_width - right_width
            self._set_splitter_sizes_safe([0, main_width, right_width])
        
        # Update menu action states based on view mode
        self.menu_manager.update_sidebar_menu_actions_for_view_mode(view_mode)

    def update_sidebar_menu_actions_for_view_mode(self, view_mode):
        """Update sidebar menu actions enabled state based on view mode"""
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_sidebar_menu_actions_for_view_mode(view_mode)

    def ensure_tree_initialized(self):
        """Ensure the tree view is initialized and added to the container"""
        if not self.file_tree_handler.is_tree_initialized():
            # Initialize the tree
            self.file_tree_handler.ensure_tree_initialized()
            # Add the tree widget to the container layout
            tree_layout = self.tree_container.layout()
            if tree_layout and tree_layout.count() == 0:  # Only add if not already added
                tree_widget = self.file_tree_handler.get_widget()
                if tree_widget:
                    tree_layout.addWidget(tree_widget)
                    tree_widget.show()
                    # Enforce saved width after adding widget to prevent Qt from recalculating
                    if self.main_splitter.width() > 0:
                        total_width = self.main_splitter.width()
                        left_width = self.sidebar_width if self._any_left_sidebar_pane_visible() else 0
                        right_width = self.right_sidebar_width if self.right_sidebar_visible else 0
                        main_width = total_width - left_width - right_width
                        self._set_splitter_sizes_safe([left_width, main_width, right_width])
            
            # Synchronize tree with current state after initialization
            self._synchronize_tree_with_current_state()
            
            # Force a refresh of the tree view to ensure it's properly displayed
            if hasattr(self.file_tree_handler, 'file_tree') and self.file_tree_handler.file_tree:
                self.file_tree_handler.file_tree.viewport().update()
                # Also ensure the tree is properly shown
                self.file_tree_handler.file_tree.show()

    def _synchronize_tree_with_current_state(self):
        """Synchronize the tree with the current application state after initialization"""
        # Ensure tree is initialized before synchronizing
        if not self.file_tree_handler.is_tree_initialized():
            self.file_tree_handler.ensure_tree_initialized()
            
        try:
            # Apply current filter pattern
            if hasattr(self, 'filter_pattern'):
                self.file_tree_handler.apply_filter_pattern(self.filter_pattern)
            
            # Apply filtered_tree setting
            if hasattr(self, 'filtered_tree'):
                self.file_tree_handler.apply_filtered_tree(self.filtered_tree)
            
            # Update tree root directory if we have a current directory
            if getattr(self, 'current_directory', None):
                # Add a small delay to ensure the tree model has time to load
                # Call directly - tree should be initialized by now
                if self.file_tree_handler.is_tree_initialized():
                    self.file_tree_handler.update_root_directory(self.current_directory)
            
            # Highlight current file/directory with delay to ensure thumbnails are loaded if tree was initialized early
            # CRITICAL: Skip if user-requested directory is set (user is opening a directory)
            # Only schedule highlighting if tree is visible (if not visible, highlighting will be handled by visibility change handler)
            def highlight_after_sync():
                # Check if tree is visible before highlighting
                if (hasattr(self.file_tree_handler, 'file_tree') and 
                    self.file_tree_handler.file_tree and 
                    self.file_tree_handler.file_tree.isVisible()):
                    # Don't override user-requested directory selection
                    if not self.file_tree_handler.user_requested_directory:
                        if getattr(self, 'current_image_path', None):
                            self.file_tree_handler.highlight_current_file()
                        elif getattr(self, 'current_directory', None):
                            self.file_tree_handler.highlight_current_directory()
            QTimer.singleShot(200, highlight_after_sync)
                
        except Exception:
            # Don't fail on synchronization errors
            pass

    def focus_tree(self):
        """Give focus to the tree container and tree widget"""
        if getattr(self, 'tree_container', None) and self.tree_container.isVisible():
            self.tree_container.setFocus()
            # Combined sidebar: tree header focus color is driven by tree_container focusInEvent;
            # do not call file_tree.setFocus() or focus moves to CustomTreeView and the title bar
            # reads unfocused. Keys still reach the tree via tree_container keyPressEvent forwarding.
            if not getattr(self, "combined_sidebar", None):
                if (hasattr(self, 'file_tree_handler') and 
                    self.file_tree_handler.is_tree_initialized() and 
                    hasattr(self.file_tree_handler, 'file_tree') and 
                    self.file_tree_handler.file_tree):
                    self.file_tree_handler.file_tree.setFocus()
    
    def focus_canvas(self):
        """Give focus to the canvas area"""
        if hasattr(self, 'main_content_widget'):
            self.main_content_widget.setFocus()
    
    def _set_initial_focus(self):
        """Set initial focus - always give focus to canvas area on startup"""
        self.focus_canvas()
    
    def _set_splitter_sizes_safe(self, sizes):
        """Set splitter sizes while suppressing splitterMoved signals to prevent Qt from overriding saved width"""
        self.ui_layout_manager.set_splitter_sizes_safe(sizes)
    
    def _on_splitter_moved(self, pos, index):
        """Handle splitter resize to update thumbnail layout when sidebar width changes"""
        return self.ui_layout_manager._on_splitter_moved(pos, index)
    
    def _immediate_splitter_update(self):
        """Provide immediate visual feedback during splitter dragging"""
        self.ui_layout_manager._immediate_splitter_update()
    
    def update_layout_after_splitter_resize(self):
        """Update thumbnail layout after splitter resize is complete"""
        return self.ui_layout_manager.update_layout_after_splitter_resize()
    
    def update_max_thumbnail_size(self):
        """Update MAX_THUMBNAIL_SIZE based on container dimensions"""
        return self.ui_layout_manager.update_max_thumbnail_size()
    
    def force_resize_event(self):
        """Force a resize event to trigger layout updates"""
        # Create a fake resize event to trigger the resizeEvent handler
        current_size = self.size()
        fake_event = QResizeEvent(current_size, current_size)
        self.resizeEvent(fake_event)
    
    def _any_left_sidebar_pane_visible(self) -> bool:
        if self.file_tree_visible or self.preview_visible:
            return True
        if getattr(self, "combined_sidebar", None):
            return (
                self.combined_sidebar.is_tree_visible()
                or self.combined_sidebar.is_preview_visible()
            )
        return False

    def _on_tree_visibility_changed(self, visible):
        """Handle tree visibility changes from combined sidebar"""
        self.file_tree_visible = visible

        if self.current_view_mode == "browse":
            if hasattr(self, "toggle_file_tree_action"):
                self.toggle_file_tree_action.setChecked(visible)
                self.toggle_file_tree_action.setText(
                    "Hide File Tree" if visible else "Show File Tree"
                )
            self.config.update_setting("file_tree_visible", visible)
            if hasattr(self, "combined_sidebar"):
                self.combined_sidebar.hide()
            return
        
        # Ensure tree is initialized when it becomes visible
        if visible:
            self.ensure_tree_initialized()
            # Give focus to the tree when shown (matches view_manager.toggle_file_tree).
            # Defer with singleShot(0) so CombinedSidebarWidget._update_overall_visibility() runs first
            # when the whole sidebar was hidden (tree+preview); otherwise tree_container may still be
            # effectively invisible and focus_tree() would no-op.
            QTimer.singleShot(0, self.focus_tree)
            QTimer.singleShot(150, self.focus_tree)
            
            # Highlight current directory/file after tree is shown (delay to ensure tree is ready)
            # CRITICAL: Skip if user-requested directory is set (user is opening a directory)
            def highlight_current():
                if (hasattr(self, 'file_tree_handler') and 
                    self.file_tree_handler and 
                    self.file_tree_handler.is_tree_initialized()):
                    # Don't override user-requested directory selection
                    if not self.file_tree_handler.user_requested_directory:
                        if getattr(self, 'current_image_path', None):
                            self.file_tree_handler.highlight_current_file()
                        elif getattr(self, 'current_directory', None):
                            self.file_tree_handler.highlight_current_directory()
            QTimer.singleShot(200, highlight_current)
        
        if hasattr(self, 'toggle_file_tree_action'):
            self.toggle_file_tree_action.setChecked(visible)
            self.toggle_file_tree_action.setText('Hide File Tree' if visible else 'Show File Tree')
        
        # Update splitter sizes
        total_width = self.main_splitter.width()
        if total_width == 0:
            return
        
        current_sizes = self.main_splitter.sizes()
        right_width = current_sizes[2] if len(current_sizes) > 2 else (self.right_sidebar_width if getattr(self, 'right_sidebar_visible', None) else 0)
        
        if visible or self.combined_sidebar.is_preview_visible():
            left_width = self.sidebar_width
            main_width = total_width - left_width - right_width
            self._set_splitter_sizes_safe([left_width, main_width, right_width])
        else:
            left_width = 0
            main_width = total_width - right_width
            self._set_splitter_sizes_safe([left_width, main_width, right_width])
        
        # Handle browse mode - resize image container when tree visibility changes
        if self.current_view_mode == 'browse':
            QTimer.singleShot(100, self._resize_browse_view_image_container)
        
        # Save settings
        self.config.update_setting('file_tree_visible', visible)
        self.config.update_setting('sidebar_width', self.sidebar_width)
        
        # Update canvas layout
        QTimer.singleShot(50, self.update_max_thumbnail_size)
    
    def _on_preview_visibility_changed(self, visible):
        """Handle preview visibility changes from combined sidebar"""
        # Check if transitioning from hidden to visible
        was_visible = getattr(self, '_preview_was_visible', False)
        transitioning_to_visible = not was_visible and visible
        
        # Update the preview widget's internal visibility flag
        self.preview_widget.preview_visible = visible
        self.preview_visible = visible

        if self.current_view_mode == "browse":
            if hasattr(self, "toggle_preview_action"):
                self.toggle_preview_action.setChecked(visible)
                self.toggle_preview_action.setText(
                    "Hide Preview" if visible else "Show Preview"
                )
            self.config.update_setting("preview_visible", visible)
            self._preview_was_visible = visible
            if hasattr(self, "combined_sidebar"):
                self.combined_sidebar.hide()
            return
        
        if visible:
            if transitioning_to_visible:
                self.preview_widget.current_pixmap = None
                self.preview_widget.current_image_path = None
                self.preview_widget.update_preview(force=True)
                # Trigger a resize update after image loads to ensure proper sizing on first show
                # This handles cases where resize events fire before preview_visible flag is set
                def trigger_resize_update():
                    if (self.preview_widget.current_pixmap and 
                        self.preview_widget.isVisible() and
                        hasattr(self, 'combined_sidebar') and 
                        self.combined_sidebar.is_preview_visible()):
                        self.preview_widget._update_image_display()
                QTimer.singleShot(50, trigger_resize_update)
            else:
                self.preview_widget.update_preview()
        
        # Update menu action
        if hasattr(self, 'toggle_preview_action'):
            self.toggle_preview_action.setChecked(visible)
            self.toggle_preview_action.setText('Hide Preview' if visible else 'Show Preview')
        
        # Update splitter sizes
        total_width = self.main_splitter.width()
        if total_width == 0:
            return
        
        current_sizes = self.main_splitter.sizes()
        right_width = current_sizes[2] if len(current_sizes) > 2 else (self.right_sidebar_width if getattr(self, 'right_sidebar_visible', None) else 0)
        
        # Capture current left_width before calculating new one
        current_left_width = current_sizes[0] if len(current_sizes) > 0 else 0
        
        # Calculate new left_width
        if visible or self.combined_sidebar.is_tree_visible():
            new_left_width = self.sidebar_width
            main_width = total_width - new_left_width - right_width
            self._set_splitter_sizes_safe([new_left_width, main_width, right_width])
        else:
            new_left_width = 0
            main_width = total_width - right_width
            self._set_splitter_sizes_safe([new_left_width, main_width, right_width])
        
        # Check if sidebar width actually changed
        sidebar_width_changed = (current_left_width != new_left_width)
        
        # Handle browse mode - resize image container when preview visibility changes
        # Delay to allow Qt to finish updating the layout before recalculating fit-to-screen
        # Longer delay needed when showing/hiding widgets vs just resizing
        if self.current_view_mode == 'browse':
            QTimer.singleShot(100, self._resize_browse_view_image_container)
        
        # Save settings
        self.config.update_setting('preview_visible', visible)
        self.config.update_setting('sidebar_width', self.sidebar_width)
        
        # Update sidebar state tracking
        self._preview_was_visible = visible
        
        # Update canvas layout only if sidebar width changed (to avoid unnecessary thumbnail refresh)
        if sidebar_width_changed:
            QTimer.singleShot(50, self.update_max_thumbnail_size)

    def _calculate_max_sidebar_width(self):
        """Calculate the maximum sidebar width to allow one column of thumbnails, accounting for right sidebar"""
        return self.ui_layout_manager._calculate_max_sidebar_width()
    
    def _on_sidebar_resized(self):
        """Handle sidebar resize events"""
        return self.sidebar_manager._on_sidebar_resized()
    
    def setup_file_tree_callbacks(self):
        """Setup callbacks for the file tree handler"""
        self.file_tree_handler.set_callbacks(
            on_directory_selected=self.on_directory_selected,
            on_file_selected=self.on_file_selected,
            on_file_double_clicked=self.on_file_double_clicked,
            get_current_image=self.get_current_image_path,
            get_displayed_images=self.get_displayed_images
        )

    def on_directory_selected(self, directory_path: str):
        """Handle directory selection from file tree"""
        self.load_directory(directory_path, external_load=True)

    def on_file_selected(self, file_path: str):
        """Handle file selection from file tree"""
        directory = os.path.dirname(file_path)
        
        # If the directory is different from current, load it
        if directory != self.current_directory:
            self.load_directory(directory, external_load=True)
            # If in browse mode, wait for directory to load then open the image
            if self.current_view_mode == 'browse':
                QTimer.singleShot(200, lambda: self._open_image_after_directory_load(file_path))
                return
        
        # Navigate the file tree to show the file's directory (without changing root)
        if self.file_tree_handler.is_tree_initialized():
            self.file_tree_handler.navigate_to_file_directory(file_path)
        
        # Find and highlight/display the specific file
        if file_path in self.displayed_images:
            try:
                file_index = self.displayed_images.index(file_path)
                self.highlight_index = self.image_indices.index(file_index)
                self.current_index = file_index
                # Set current image path before opening browse view
                self.configuration_sync_manager._set_current_image_path_with_sync(file_path)
                
                # If in browse mode, display the image
                if self.current_view_mode == 'browse':
                    self.view_mode_manager.open_browse_view(self.highlight_index)
                else:
                    # In thumbnail mode, just highlight the image
                    self.highlight_image()
                    
            except (ValueError, IndexError):
                pass
        else:
            # File not in current displayed images, try to load it directly
            self.load_specific_files([file_path], external_load=True)
            if self.current_view_mode == 'browse':
                # Use a timer to ensure the file is loaded before opening browse
                QTimer.singleShot(100, lambda: self.view_mode_manager.open_browse_view(0))

    def on_file_double_clicked(self, file_path: str):
        """Handle file double-click from file tree - open file directly"""
        # Use the existing configuration system to open the file
        configuration = {'files': [file_path]}
        
        # Use a timer to ensure the configuration is applied after any current operations
        QTimer.singleShot(50, lambda: self.refresh_from_configuration(configuration))

    def get_current_image_path(self) -> Optional[str]:
        """Get the path of the currently displayed image (FileDataModel is source of truth)."""
        if not getattr(self, "file_data_model", None):
            return None
        displayed = self.file_data_model.get_displayed_images()
        if not displayed:
            return None
        path = self.file_data_model.get_current_image_path()
        if path and path in displayed:
            return path
        if not (0 <= self.highlight_index < len(displayed)):
            return None
        self._sync_highlight_index_from_current_image_path(displayed)
        path = self.file_data_model.get_current_image_path()
        if path:
            return path
        if 0 <= self.highlight_index < len(displayed):
            path = displayed[self.highlight_index]
            self._set_current_image_path_with_sync(path)
            return path
        return None
    
    def _tree_has_focus(self) -> bool:
        """Check if the tree has focus by checking tree widget focus and header color.
        
        Returns:
            True if tree has focus and is visible, False otherwise.
        """
        # Check if tree is visible
        has_combined_sidebar = bool(getattr(self, 'combined_sidebar', None))
        tree_visible = False
        if has_combined_sidebar:
            tree_visible = getattr(self.combined_sidebar, 'tree_visible', False)
        
        if not (has_combined_sidebar and tree_visible):
            return False
        
        # Check if tree widget has focus
        if has_combined_sidebar and hasattr(self.combined_sidebar, 'tree_widget'):
            tree_widget = self.combined_sidebar.tree_widget
            if tree_widget and tree_widget.hasFocus():
                return True
        
        # Also check tree header color as backup indicator
        if has_combined_sidebar and hasattr(self.combined_sidebar, 'tree_header'):
            tree_header = self.combined_sidebar.tree_header
            if tree_header:
                header_style_sheet = tree_header.styleSheet()
                if header_style_sheet and TREE_HEADER_FOCUS_BG_HEX in header_style_sheet:
                    return True
        return False
    
    def get_current_search_directory(self) -> Optional[str]:
        """Get the current directory for search operations (CNN, CLIP, etc.).
        
        This method prioritizes the highlighted tree directory when tree has focus,
        then self.current_directory (the thumbnail directory shown in status bar)
        over get_current_image_path() to ensure consistency when there are no images in the view.
        This matches the behavior shown in the status bar.
        
        Returns:
            Directory path string, or None if no directory is available.
        """
        # Priority 0: If tree had focus when invoked (stored by menu handler), get selected directory from tree
        # This flag is set by menu handlers BEFORE they move focus, allowing context-aware behavior
        tree_had_focus = getattr(self, '_tree_had_focus_when_invoked', False)
        
        if tree_had_focus:
            if (getattr(self, 'file_tree_handler', None) and
                hasattr(self.file_tree_handler, 'file_tree') and self.file_tree_handler.file_tree):
                tree = self.file_tree_handler.file_tree
                selection = tree.selectionModel().selectedIndexes()
                if selection:
                    index = selection[0]
                    model = tree.model()
                    if model:
                        source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                        selected_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                        
                        if selected_path:
                            if os.path.isdir(selected_path):
                                return selected_path
                            # File selected: use its containing directory
                            dir_path = os.path.dirname(selected_path)
                            if dir_path and os.path.isdir(dir_path):
                                return dir_path
        
        # Priority 1: Use current_directory (thumbnail directory) - same as status bar
        # Check for both None and empty string to ensure we use current_directory when available
        if getattr(self, 'current_directory', None) and self.current_directory.strip():
            return self.current_directory
        
        # Do NOT fallback to get_current_image_path() when current_directory is not set
        # This ensures we use the thumbnail directory (which may have no images) rather than
        # the last known active image from a different directory
        
        # Priority 2: Fallback to directory of first displayed image (if available)
        # This is safer than using get_current_image_path() which might point to a different directory
        displayed = self.get_displayed_images()
        if displayed and len(displayed) > 0:
            directory_path = os.path.dirname(displayed[0])
            if directory_path and os.path.exists(directory_path):
                return directory_path
        
        # Priority 3: Last resort fallback to directory of current image path (if available)
        # Only use this if current_directory is not set AND there are no displayed images
        current_image_path = self.get_current_image_path()
        if current_image_path:
            directory_path = os.path.dirname(current_image_path)
            if directory_path and os.path.exists(directory_path):
                return directory_path
        return None

    def _find_best_clip_match(self, images: List[str]) -> Optional[str]:
        """Find the best match for CLIP search highlighting.
        
        Returns the first unlocked file if locked files exist, otherwise the first file.
        This ensures the best match (highest similarity) is highlighted after locked files.
        
        Args:
            images: List of image paths (sorted by similarity, best first)
            
        Returns:
            Path to best match (first unlocked file), or None if no images
        """
        if not images:
            return None
        
        # Check if locked files exist in the directory
        if getattr(self, 'lock_manager', None):
            directory = os.path.dirname(images[0])
            locked_files = self.lock_manager.get_locked_files(directory)
            
            if locked_files:
                # Find first unlocked file (best match after locked files)
                locked_set = set(locked_files)
                for path in images:
                    if os.path.exists(path):
                        filename = os.path.basename(path)
                        if filename not in locked_set:
                            return path
                # All files are locked, return first file
                return images[0] if images else None
        
        # No locked files, return first result (best match)
        return images[0] if images else None
    
    def set_current_image_by_path(self, image_path: Optional[str], fallback_index: Optional[int] = None):
        """Set the current image by file path (the source of truth).
        
        This method ALWAYS uses the file path as the source of truth and derives
        highlight_index and current_index from it by finding the path in displayed_images.
        
        Args:
            image_path: The file path to set as current (source of truth)
            fallback_index: Optional index to use if image_path is not found in displayed_images
        """
        if image_path:
            self.configuration_sync_manager._set_current_image_path_with_sync(image_path)
            # Derive highlight_index and current_index from the file path
            displayed = self.get_displayed_images()
            if displayed and image_path in displayed:
                try:
                    new_index = displayed.index(image_path)
                    self.highlight_index = new_index
                    self.current_index = new_index
                except (ValueError, IndexError):
                    # Path not found - use fallback if provided
                    if fallback_index is not None and 0 <= fallback_index < len(displayed):
                        self.highlight_index = fallback_index
                        self.current_index = fallback_index
                        self.configuration_sync_manager._set_current_image_path_with_sync(displayed[fallback_index])
                    elif displayed:
                        # Default to first image if no fallback
                        self.highlight_index = 0
                        self.current_index = 0
                        self.configuration_sync_manager._set_current_image_path_with_sync(displayed[0])
            elif fallback_index is not None:
                # Path not in displayed_images, use fallback
                displayed = self.get_displayed_images()
                if displayed and 0 <= fallback_index < len(displayed):
                    self.highlight_index = fallback_index
                    self.current_index = fallback_index
                    # Use sync method to ensure status bar updates
                    self._set_current_image_path_with_sync(displayed[fallback_index])
        elif fallback_index is not None:
            # No path provided, use fallback index
            displayed = self.get_displayed_images()
            if displayed and 0 <= fallback_index < len(displayed):
                self.highlight_index = fallback_index
                self.current_index = fallback_index
                # Use sync method to ensure status bar updates
                self._set_current_image_path_with_sync(displayed[fallback_index])
            elif displayed:
                # Default to first image
                self.highlight_index = 0
                self.current_index = 0
                # Use sync method to ensure status bar updates
                self._set_current_image_path_with_sync(displayed[0])

    def _sync_highlight_index_from_current_image_path(self, displayed=None):
        """Sync highlight_index and current_index from current_image_path (the source of truth).
        
        This should be called whenever displayed_images changes to ensure highlight_index
        stays in sync with current_image_path.
        
        CRITICAL: Uses _set_current_image_path_with_sync to ensure status bar updates
        whenever current_image_path changes.
        
        Args:
            displayed: Optional cached list of displayed images to avoid redundant call.
                      If None, will call get_displayed_images(). File path remains source of truth.
        """
        # PERFORMANCE: Use cached displayed list if provided, otherwise fetch it
        if displayed is None:
            displayed = self.get_displayed_images()
        
        if getattr(self, 'current_image_path', None):
            if displayed and self.current_image_path in displayed:
                try:
                    new_index = displayed.index(self.current_image_path)
                    self.highlight_index = new_index
                    self.current_index = new_index
                except (ValueError, IndexError):
                    # Path not found - default to first image
                    if displayed:
                        self.highlight_index = 0
                        self.current_index = 0
                        # Use sync method to ensure status bar updates
                        self._set_current_image_path_with_sync(displayed[0])
            elif displayed:
                # Current image not in displayed_images - default to first
                self.highlight_index = 0
                self.current_index = 0
                # Use sync method to ensure status bar updates
                self._set_current_image_path_with_sync(displayed[0])
        else:
            # No current_image_path set - default to first image
            if displayed:
                self.highlight_index = 0
                self.current_index = 0
                # Use sync method to ensure status bar updates
                self._set_current_image_path_with_sync(displayed[0])

    def setup_actions(self):
        """Setup menu bar and toolbar actions"""
        self.menu_manager.setup_actions()



    class _RefreshEmitter(QObject):
        refresh = Signal(str)
        load_thumbnails_requested = Signal()

    def setup_connections(self):
        """Setup signal connections"""
        if hasattr(self, 'event_bus') and self.event_bus:
            from event_bus import DIRECTORY_LOADED
            self.event_bus.subscribe(DIRECTORY_LOADED, self._on_directory_loaded)
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.handle_application_quit)
            self.RefreshEmitter = self._RefreshEmitter()
            self.RefreshEmitter.load_thumbnails_requested.connect(
                self.start_background_thumbnail_loading_if_needed, Qt.QueuedConnection
            )
    
    def _sync_to_file_data_model(self):
        """Sync current state to FileDataModel for consistency"""
        return self.configuration_sync_manager._sync_to_file_data_model()
    
    def _set_displayed_images_with_sync(self, images: List[str], sync: bool = True):
        """Set displayed_images and optionally sync with FileDataModel."""
        from window_sync import set_displayed_images_for_window

        set_displayed_images_for_window(self, images, sync)

    def _set_current_image_path_with_sync(self, path: Optional[str], sync: bool = True):
        """Set current_image_path and optionally sync with FileDataModel."""
        from window_sync import set_current_image_path_for_window

        set_current_image_path_for_window(self, path, sync)

    def _set_current_directory_with_sync(self, directory: Optional[str], sync: bool = True):
        """Set current_directory and optionally sync with FileDataModel."""
        from window_sync import set_current_directory_for_window

        set_current_directory_for_window(self, directory, sync)
    
    def _on_displayed_images_changed(self, images: List[str]):
        """Handle displayed_images change from FileDataModel - update main_window and sync tree view"""
        self.displayed_images = images
        # Check for pending highlight from show_image_in_directory
        if getattr(self, '_pending_highlight', None) is not None:
            target_directory, saved_selections = self._pending_highlight
            self._pending_highlight = None  # Clear immediately
            try:
                current_dir = getattr(self, 'current_directory', None)
                if current_dir == target_directory and images:
                    self._perform_pending_highlight(saved_selections)
            except (AttributeError, RuntimeError):
                pass
        return self.configuration_sync_manager._on_displayed_images_changed(images)
    
    def _on_current_image_changed(self, image_path: str):
        """Handle current_image_path change from FileDataModel - sync tree view"""
        return self.configuration_sync_manager._on_current_image_changed(image_path)

    def _on_directory_loaded(self, directory, displayed_count=None, external_load=None):
        """Handle DIRECTORY_LOADED event - reset tracking, activate window, start cache loader, simulate refresh"""
        self.reset_browse_view_exit_tracking()
        self.activateWindow()
        self.raise_()
        if (hasattr(self, 'cache_manager') and self.cache_manager and
            hasattr(self.cache_manager, 'background_loader') and self.cache_manager.background_loader and
            not self.cache_manager.background_loader.isRunning()):
            self.cache_manager.background_loader.start()
        user_requested = (hasattr(self, 'file_tree_handler') and self.file_tree_handler and
                         getattr(self.file_tree_handler, 'user_requested_directory', None))
        if (self.current_view_mode == 'thumbnail' and not getattr(self, 'restoring_from_history', False) and not user_requested):
            try:
                QTimer.singleShot(200, self.simulate_browse_view_exit_for_refresh)
            except Exception:
                pass
    
    def _on_directory_changed(self, directory: str):
        """Handle directory change from FileDataModel - sync tree view"""
        return self.configuration_sync_manager._on_directory_changed(directory)

    def apply_dark_theme(self):
        """Backward compatibility: delegates to refresh_theme_styles."""
        self.refresh_theme_styles()

    def refresh_thumbnail_theme_styles(self):
        """Repaint thumbnail grid after thumbnail-only palette changes (no global QSS)."""
        if getattr(self, "thumbnail_container", None) and hasattr(self.thumbnail_container, "canvas"):
            canvas = self.thumbnail_container.canvas
            if canvas:
                if canvas._is_reference_graph_mode():
                    canvas._calculate_reference_graph_layout()
                canvas.update()

    def refresh_theme_styles(self):
        """Re-apply theme-dependent widget styles after global palette change."""
        theme = get_active_theme()
        if hasattr(self, "main_splitter") and self.main_splitter:
            self.main_splitter.setHandleWidth(theme.view_border_width_px)
            self.main_splitter.setStyleSheet(theme.main_splitter_stylesheet())
        if hasattr(self, "status_bar") and self.status_bar:
            self.status_bar.setStyleSheet(theme.main_status_bar_chrome_stylesheet())
        if hasattr(self, "progress_bar") and self.progress_bar:
            self.progress_bar.setStyleSheet(theme.floating_progress_bar_stylesheet())
        if hasattr(self, "thumbnail_status_label") and self.thumbnail_status_label:
            self.thumbnail_status_label.setStyleSheet(theme.thumbnail_status_label_stylesheet())
        if hasattr(self, "view_manager") and self.view_manager:
            self.view_manager.refresh_browse_theme_styles()
        if hasattr(self, "status_bar_manager") and self.status_bar_manager:
            self.status_bar_manager.refresh_theme_styles()
        if hasattr(self, "file_tree_handler") and self.file_tree_handler:
            self.file_tree_handler.refresh_theme_styles()
        if hasattr(self, "right_sidebar") and self.right_sidebar:
            if hasattr(self.right_sidebar, "refresh_theme_styles"):
                self.right_sidebar.refresh_theme_styles()
            elif hasattr(self.right_sidebar, "shortcuts_widget") and self.right_sidebar.shortcuts_widget:
                self.right_sidebar.shortcuts_widget.refresh_theme_styles()
                if hasattr(self.right_sidebar, "information_widget") and self.right_sidebar.information_widget:
                    self.right_sidebar.information_widget.refresh_theme_styles()

        if hasattr(self, "combined_sidebar") and self.combined_sidebar:
            if hasattr(self.combined_sidebar, "refresh_theme_styles"):
                self.combined_sidebar.refresh_theme_styles()

        if getattr(self, "thumbnail_container", None) and hasattr(self.thumbnail_container, "canvas"):
            canvas = self.thumbnail_container.canvas
            if canvas:
                if canvas._is_reference_graph_mode():
                    canvas._calculate_reference_graph_layout()
                canvas.update()
        if getattr(self, "canvas_manager", None) and hasattr(self.canvas_manager, "refresh_theme_styles"):
            self.canvas_manager.refresh_theme_styles()
        if getattr(self, "preview_widget", None) and hasattr(self.preview_widget, "refresh_theme_styles"):
            self.preview_widget.refresh_theme_styles()

    def open_directory_dialog(self):
        """Open directory selection dialog"""
        directory = self.file_operations_manager.open_directory_dialog()
        if directory:
            # Save current state BEFORE closing browse - so ESC restores browse session
            self.directory_stack_history_handler.save_current_state("image_browser_window.open_directory_dialog")
            # If we're in browse mode, exit browse after successful directory selection
            if self.current_view_mode == 'browse':
                self.view_manager.close_browse_view()
            
            old_filter = self.filter_pattern
            if old_filter:
                # self.filter_pattern = "" # DGN testing not clearing this
                self.config.update_setting('filter_pattern', self.filter_pattern)
                if self.status_notification:
                    self.status_notification.show_message("New directory opened, filter cleared")
            
            # Reset limit to show all images when opening directory via Ctrl+O
            self.limit = 99999
            
            configuration = {
                'directory': directory,
                'files': None,
                'highlight_file': None,
            }
            self.refresh_from_configuration(configuration)
            # Update file tree root when opening directory via dialog
            # Ensure tree is initialized if visible
            if self.file_tree_visible or (getattr(self, 'combined_sidebar', None) and self.combined_sidebar.is_tree_visible()):
                self.ensure_tree_initialized()
            if self.file_tree_handler.is_tree_initialized():
                self.file_tree_handler.update_root_directory(directory)

    def open_home_directory(self):
        """Open the user's home directory (~). Same flow as open directory dialog."""
        directory = os.path.expanduser("~")
        if not directory or not os.path.isdir(directory):
            return
        self.directory_stack_history_handler.save_current_state("image_browser_window.open_home_directory")
        if self.current_view_mode == 'browse':
            self.view_manager.close_browse_view()

        old_filter = self.filter_pattern
        if old_filter:
            self.config.update_setting('filter_pattern', self.filter_pattern)
            if self.status_notification:
                self.status_notification.show_message("New directory opened, filter cleared")

        self.limit = 99999

        configuration = {
            'directory': directory,
            'files': None,
            'highlight_file': None,
        }
        self.refresh_from_configuration(configuration)
        if self.file_tree_visible or (getattr(self, 'combined_sidebar', None) and self.combined_sidebar.is_tree_visible()):
            self.ensure_tree_initialized()
        if self.file_tree_handler.is_tree_initialized():
            self.file_tree_handler.update_root_directory(directory)

    def open_file_dialog(self):
        """Open file selection dialog"""
        file_path = self.file_operations_manager.open_file_dialog()
        
        if file_path:
            # Save current state BEFORE closing browse - so ESC restores browse session
            self.directory_stack_history_handler.save_current_state("image_browser_window.open_file_dialog")
            # If we're in browse mode, exit browse after successful file selection
            if self.current_view_mode == 'browse':
                self.view_manager.close_browse_view()
            
            old_filter = self.filter_pattern
            if old_filter:
                # self.filter_pattern = "" # DGN testing not clearing this
                self.config.update_setting('filter_pattern', self.filter_pattern)
                if self.status_notification:
                    self.status_notification.show_message("New file opened, filter cleared")
            
            # Reset limit to show all images when opening file via Ctrl+O
            self.limit = 99999
            
            if isinstance(file_path, list) and len(file_path) > 1:
                # If multiple files are selected, treat as specific files mode
                self.load_specific_files(file_path)
            else:
                # If a single file is selected, open its directory and highlight the file
                if isinstance(file_path, list):
                    file_path = file_path[0]
                directory = os.path.dirname(file_path)
                self.load_directory(directory)
                # Highlight the selected file in the loaded directory
                if file_path in self.displayed_images:
                    # Use configuration to control highlight and view mode
                    configuration = {
                        'files': [file_path],
                        'directory': directory,
                        'highlight_file': file_path,
                    }
                    self.refresh_from_configuration(configuration)
            # Update file tree root when opening file via dialog
            if self.file_tree_handler.is_tree_initialized():
                self.file_tree_handler.update_root_directory(os.path.dirname(file_path))
                
    def find_exact_duplicates(self):
        """Set duplicate mode - shows only duplicate files sorted by hash (like random mode)"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.find_exact_duplicates()
    
    def find_exact_duplicates_recursive(self):
        """Find exact duplicates in current directory and all subdirectories"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.find_exact_duplicates_recursive()

    def find_similar_image_files(self):
        """Find visually similar images in the current directory view (128px-wide compare)."""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.find_similar_image_files()

    def find_similar_image_files_recursive(self):
        """Find visually similar images recursively from the current directory."""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.find_similar_image_files_recursive()

    def find_similar_image_files_in_directory(self, directory_path: str) -> None:
        """Find visually similar images under a folder recursively; e.g. tree context menu."""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.find_similar_image_files_in_directory(directory_path)

    def load_directory(self, directory: str, external_load: bool = False, refresh_mode: bool = False):
        """Request directory load via event bus. DirectoryLoader subscribes and performs the load."""
        from event_bus import DIRECTORY_REQUESTED
        self.event_bus.emit(DIRECTORY_REQUESTED, (directory, external_load, refresh_mode))
                    
    def _open_image_after_directory_load(self, file_path):
        """Open a specific image after directory has been loaded"""
        if file_path in self.displayed_images:
            try:
                file_index = self.displayed_images.index(file_path)
                self.highlight_index = self.image_indices.index(file_index)
                self.current_index = file_index
                self.view_mode_manager.open_browse_view(self.highlight_index)
            except (ValueError, IndexError):
                pass
    
    def show_image_in_directory(self):
        """Show the current image in its directory with the image highlighted"""
        # Get selected files if multiple are selected, otherwise use current image
        selected_files = getattr(self, 'selected_files', set())
        
        # If multiple files are selected, check if they all belong to the same directory
        if len(selected_files) > 1:
            directories = {os.path.dirname(f) for f in selected_files if os.path.exists(f)}
            if len(directories) > 1:
                show_styled_warning(
                    self,
                    "Multiple Directories",
                    "Cannot show images in directory: Selected files belong to different directories.\n\nPlease select files from the same directory.",
                )
                return
            directory = directories.pop() if directories else None
            saved_selections = set(selected_files)
        else:
            # Single file or no selection - use current image
            current_image_path = getattr(self, 'current_image_path', None)
            if not current_image_path or not os.path.exists(current_image_path):
                return
            
            directory = os.path.dirname(current_image_path)
            if not directory or not os.path.isdir(directory):
                return
            
            saved_selections = set()
            if current_image_path:
                saved_selections.add(current_image_path)
        
        if not directory or not os.path.isdir(directory):
            return
        
        # CRITICAL: Change sort mode to NAME (a-z) before opening directory
        # This ensures the resulting thumb list is sorted by name, not retaining duplicate list layout
        self.current_sort_mode = SortMode.NAME
        self.is_reversed = False
        
        # Open the directory (this will switch to thumbnail mode if not already in it)
        self.open_directory(directory)
        
        # Store pending highlight for signal-based approach (replaces timer)
        # This ensures highlighting happens when directory loading completes
        self._pending_highlight = (directory, saved_selections)
        
        # Optimization: If directory is already loaded, perform highlight immediately
        try:
            current_dir = getattr(self, 'current_directory', None)
            if current_dir == directory and getattr(self, 'displayed_images', None):
                self._pending_highlight = None
                self._perform_pending_highlight(saved_selections)
        except (AttributeError, RuntimeError):
            pass
    
    def _perform_pending_highlight(self, saved_selections: set):
        """Perform highlighting for pending show_image_in_directory request"""
        try:
            if not hasattr(self, 'displayed_images') or not self.displayed_images:
                return
            
            # Ensure indices arrays are populated before highlighting
            if hasattr(self, 'populate_indices_arrays'):
                self.populate_indices_arrays()
            
            # Restore selections if multiple files were selected
            if len(saved_selections) > 1:
                # Restore all selected files that are in the displayed images
                self.selected_files = {path for path in saved_selections if path in self.displayed_images}
                
                # Highlight the first selected file
                if self.selected_files:
                    first_selected = next(iter(self.selected_files))
                    if first_selected in self.displayed_images:
                        try:
                            file_index = self.displayed_images.index(first_selected)
                            self.highlight_index = self.image_indices.index(file_index) if hasattr(self, 'image_indices') and file_index < len(self.image_indices) else file_index
                            self.current_index = file_index
                            self.current_image_path = first_selected
                            self.highlight_image()
                            self._emit_selection_changed()
                            # Scroll to make highlighted image visible after thumbnails render
                            QTimer.singleShot(50, self.ensure_highlighted_visible)
                        except (ValueError, IndexError):
                            pass
            elif len(saved_selections) == 1:
                # Single file - highlight it
                file_path = next(iter(saved_selections))
                if file_path in self.displayed_images:
                    try:
                        file_index = self.displayed_images.index(file_path)
                        self.highlight_index = self.image_indices.index(file_index) if hasattr(self, 'image_indices') and file_index < len(self.image_indices) else file_index
                        self.current_index = file_index
                        self.current_image_path = file_path
                        self.highlight_image()
                        # Scroll to make highlighted image visible after thumbnails render
                        QTimer.singleShot(50, self.ensure_highlighted_visible)
                    except (ValueError, IndexError):
                        pass
        except (AttributeError, RuntimeError, ValueError, IndexError):
            pass

    def load_specific_files(self, file_paths: List[str], external_load: bool = False, force_specific_files_grid: bool = False):
        """Load specific image files instead of scanning a directory"""
        return self.directory_loader.load_specific_files(file_paths, external_load, force_specific_files_grid)

    def open_specific_file(self, file_path: str):
        """Open a specific file when received from macOS file association"""
        return self.directory_loader.open_specific_file(file_path)
        
    def _prune_browse_image_history(self) -> None:
        if not getattr(self, 'browse_image_history', None):
            self.browse_image_history = []
            return
        self.browse_image_history = [
            p for p in self.browse_image_history
            if p and os.path.isfile(p)
        ]

    def touch_browse_image_history(self, path: str) -> None:
        """Record path as the most recently browsed image (unique list, newest first; cap in thumbnail_constants)."""
        if not path:
            return
        try:
            ap = os.path.abspath(path)
        except OSError:
            return
        if not os.path.isfile(ap):
            return
        hist = self.browse_image_history
        if ap in hist:
            hist.remove(ap)
        hist.insert(0, ap)
        del hist[BROWSE_IMAGE_HISTORY_MAX:]
        if getattr(self, 'current_view_mode', None) == 'browse' and hasattr(self, 'menu_manager'):
            self.menu_manager.update_file_menu_last_image_action()

    def _cancel_browse_image_history_debounce(self) -> None:
        """Stop pending browse image history add (e.g. user left browse or switched image before debounce elapsed)."""
        if self._browse_image_history_debounce_timer.isActive():
            self._browse_image_history_debounce_timer.stop()
        self._browse_image_history_debounce_pending_path = None

    def _on_browse_image_history_debounce_timeout(self) -> None:
        pending = self._browse_image_history_debounce_pending_path
        self._browse_image_history_debounce_pending_path = None
        if not pending:
            return
        if self.current_view_mode != 'browse':
            return
        cur = self.get_current_image_path()
        if not cur:
            return
        try:
            if os.path.abspath(cur) != pending:
                return
        except OSError:
            return
        self.touch_browse_image_history(pending)

    def _schedule_browse_image_history_record(self, path: str) -> None:
        """Queue adding path to browse image history after configured delay in browse mode."""
        self._cancel_browse_image_history_debounce()
        if not path:
            return
        try:
            ap = os.path.abspath(path)
        except OSError:
            return
        if not os.path.isfile(ap):
            return
        ms = max(0, min(5000, int(getattr(self, 'browse_image_history_save_after_ms', 3000))))
        if ms <= 0:
            self.touch_browse_image_history(ap)
            return
        self._browse_image_history_debounce_pending_path = ap
        self._browse_image_history_debounce_timer.start(ms)

    def open_browse_image_history(self) -> None:
        """Open a specific-files thumbnail level listing recent browse images (Esc returns)."""
        if self.current_view_mode not in ('browse', 'thumbnail'):
            return
        self._prune_browse_image_history()
        hist = self.browse_image_history
        paths = [p for p in hist[:BROWSE_IMAGE_HISTORY_MAX] if p and os.path.isfile(p)]
        if not paths:
            return
        handler = getattr(self, 'directory_stack_history_handler', None)
        if handler:
            current_state = handler.capture_current_state()
            if current_state and not handler.is_duplicate_state(current_state):
                handler.backward_stack.append(current_state)
                handler.forward_stack.clear()
        configuration = {
            'files': paths,
            'sort_mode': 'custom',
            'prevent_browse_view': True,
            'force_specific_files_grid': len(paths) == 1,
        }
        self.clear_selection()
        self.refresh_from_configuration(configuration)

    def swap_browse_image_history_first_two_and_show(self) -> None:
        """Swap F3 browse image history [0] and [1], then show the new first image (browse mode)."""
        if self.current_view_mode != 'browse':
            return
        self._prune_browse_image_history()
        hist = self.browse_image_history
        if len(hist) < 2:
            return
        hist[0], hist[1] = hist[1], hist[0]
        new_first = hist[0]
        if not new_first or not os.path.isfile(new_first):
            return
        self.load_file_with_directory_thumbnails(new_first)

    def load_file_with_directory_thumbnails(self, target_file: str, limit: Optional[int] = None, external_load: bool = False):
        """Load a specific file in browse while building thumbnails from its directory in the background"""
        if not target_file or not os.path.exists(target_file):
            show_styled_warning(self, "Invalid File", 
                              f"File does not exist: {target_file}")
            return
        
        # Switch to browse view immediately to prevent showing thumbnails first
        # This ensures single file loads go directly to browse without flashing thumbnails
        switch_to_browse_view = self.current_view_mode != 'browse'
        if switch_to_browse_view:
            self.stacked_widget.setCurrentIndex(1)  # Switch to browse view
            self.current_view_mode = 'browse'
            self._emit_view_mode_changed()
            # Hide sidebar visually for clean browse view - NEVER show in browse view
            # Don't change the saved state, just hide it visually
            if hasattr(self, 'combined_sidebar'):
                self.combined_sidebar.hide()
            # Also ensure splitter gives full width to canvas
            if hasattr(self, 'main_splitter'):
                total_width = self.main_splitter.width()
                self._set_splitter_sizes_safe([0, total_width])
            self.manage_sidebar_visibility_for_view_mode('browse')
            # Set up browse view state immediately
            self.browse_view_action.setEnabled(False)
            if hasattr(self, 'image_container'):
                available_size = self.get_effective_display_size()
                self.image_container.resize(available_size)
            if hasattr(self, 'view_manager'):
                self.view_manager._setup_cursor_manager()
            
            # Prime and enable menu keys for view change
            if hasattr(self, 'menu_manager'):
                self.menu_manager.prime_menu_keys_for_view_change()
        
        # Single-file browse with directory thumbnails is not specific-files mode or window mode
        self.specific_files_active = False
        self.window_size = None
        self.window_target_file = None

        # Normalize limit parameter: None or 0 becomes 99999
        if limit is None or limit == 0:
            limit = 99999
        # Use the provided limit parameter, or fall back to self.limit if limit is unlimited
        if limit == 99999:
            effective_limit = self.limit
        else:
            self.limit = limit
            effective_limit = limit
        
        directory = os.path.dirname(target_file)
        self.current_directory = directory
        
        self.setWindowTitle(f"Prowser - {os.path.basename(target_file)}")
        
        all_images = self._scan_directory_efficiently(directory)
        
        # Preserve name sorting and other modes across directory navigation
        
        if not all_images:
            return
        
        if self.filter_pattern:
            all_images = self.sorting_manager.filter_images_by_pattern(all_images)
            if not all_images:
                self.status_bar_manager.show_message(f"No images found matching pattern '{self.filter_pattern}' in directory {directory}")
                return
        
        if not all_images:
            self.status_bar_manager.show_message("No images found in directory")
            return
        
        # Apply correct sorting based on saved settings
        # Handle random mode by restoring to date sorting as requested
        if self.current_sort_mode == SortMode.RANDOM:
            # Restore random to date sorting as requested
            # Clear random mode - handled by setting current_sort_mode
            self.save_sorting_settings()
        
        # Handle duplicate mode by restoring to date sorting when loading new directory
        if self.current_sort_mode == SortMode.DUPLICATES:
            # Restore duplicate mode to date sorting when loading new directory
            # Clear duplicates mode - handled by setting current_sort_mode
            self.save_sorting_settings()
        
        # Apply sorting if it's the default setting
        if self.current_sort_mode == SortMode.CUSTOM:
            # Apply custom sort if enabled
            directory = os.path.dirname(all_images[0]) if all_images else None
            if directory:
                all_images, saved_is_reversed = self.sorting_manager._apply_custom_sort(directory, all_images)
                # Restore the reversed state from the .prsort file
                self.is_reversed = saved_is_reversed
        elif self.current_sort_mode == SortMode.NAME:
            # Sort by name case-insensitively
            all_images.sort(key=lambda path: path.lower(), reverse=self.is_reversed)
        elif self.current_sort_mode == SortMode.SIZE:
            # Size sorting - sort by width × height, then by width for same area, then by path
            def get_size_sort_key(path):
                try:
                    cache_key = self.cache_manager.get_cache_key(path)
                    if cache_key in self.cache_manager.metadata_cache:
                        metadata = self.cache_manager.metadata_cache[cache_key]
                        if metadata and hasattr(metadata, 'width') and hasattr(metadata, 'height'):
                            if metadata.width > 0 and metadata.height > 0:
                                area = metadata.width * metadata.height
                                if self.is_reversed:
                                    return (area, -metadata.width, path.lower())  # Smallest first: negate width so wider comes first
                                else:
                                    return (area, metadata.width, path.lower())  # Largest first: wider comes first naturally
                    dimensions = get_image_dimensions_fast_metadata(path)
                    if dimensions and len(dimensions) == 2:
                        width, height = dimensions
                        if width > 0 and height > 0:
                            area = width * height
                            if self.is_reversed:
                                return (area, -width, path.lower())  # Smallest first: negate width so wider comes first
                            else:
                                return (area, width, path.lower())  # Largest first: wider comes first naturally
                    return (0, 0, path.lower())
                except Exception:
                    return (0, 0, path.lower())
            try:
                all_images.sort(key=get_size_sort_key, reverse=not self.is_reversed)
            except Exception:
                all_images.sort(key=lambda p: p.lower())
        else:
            # Date sorting - respect the is_reversed flag
            # is_reversed=False means newest first (descending), is_reversed=True means oldest first (ascending)
            # Ensure that when date sorting is active, other sort modes are disabled
            # Clear random and duplicate modes - handled by setting current_sort_mode
            try:
                all_images.sort(key=self.get_sort_key, reverse=not self.is_reversed)
            except Exception:
                # If date sorting fails completely, fallback to alphabetical
                all_images.sort(key=lambda p: p.lower())
        
        if target_file not in all_images:
            all_images.insert(0, target_file)
        
        # Use windowing if we have more images than the limit
        if len(all_images) > effective_limit:
            # Create window around target file manually (windowing system is for recalculating existing windows)
            target_index = all_images.index(target_file)
            half_window = effective_limit // 2
            start_index = max(0, target_index - half_window)
            end_index = min(len(all_images), start_index + effective_limit)
            
            if end_index - start_index < effective_limit and start_index > 0:
                start_index = max(0, end_index - effective_limit)
            
            # Set the windowed displayed_images
            self.displayed_images = all_images[start_index:end_index]
        else:
            # No limit, show all images
            self.displayed_images = all_images
        
        self.populate_indices_arrays()
        
        # Handle target file positioning after windowing
        try:
            target_image_index = self.displayed_images.index(target_file)
            self.highlight_index = self.image_indices.index(target_image_index)
            self.current_index = target_image_index
            # Set current_image_path for future windowing operations
            # Use sync method to ensure proper synchronization with FileDataModel
            self.configuration_sync_manager._set_current_image_path_with_sync(target_file)
        except (ValueError, IndexError):
            self.highlight_index = 0
            self.current_index = 0
            target_image_index = 0
        
        # If we switched to browse view, display the image immediately to prevent showing thumbnails
        if switch_to_browse_view and self.current_view_mode == 'browse':
            # Display the image immediately without waiting for open_browse_view
            self.show_image(self.current_image_path, self.current_index)
        
        # Refresh the thumbnail display after windowing changes
        # Defer thumbnail building until after browse view is shown to avoid showing thumbnail view
        # This speeds up initial display when opening a specific file
        # self._refresh_partial_thumbnail_list() #DGN WINDOW1
        self.update_status_bar_sections()
        
        # Update file tree highlighting when specific file is loaded
        if self.file_tree_handler.is_tree_initialized():
            self.file_tree_handler.highlight_current_file()
            # Apply current filter pattern to file tree
            self.file_tree_handler.apply_filter_pattern(self.filter_pattern)
            
            # Update file tree root to show the directory of the target file
            self.file_tree_handler.update_root_directory(directory)
        
        # Pre-load the target image into cache to avoid 5-second delay
        # Only pre-load when opening browse view, not thumbnail view
        # This prevents loading large full images into memory when only viewing thumbnails
        if (getattr(self, 'cache_manager', None) and 
            self.current_view_mode == 'browse'):
            try:
                # Pre-load the target image with EXIF correction into cache
                ignore_exif = getattr(self, 'ignore_exif_rotation', False)
                pixmap = load_image_with_exif_correction(target_file, ignore_exif=ignore_exif)
                if pixmap and not pixmap.isNull():
                    # Cache it if not too large (limit to reasonable memory usage)
                    if pixmap.width() * pixmap.height() < 8000000:  # ~8MP limit
                        self.cache_manager.cache_fullimage_sync(target_file, pixmap)
            except Exception:
                pass  # Ignore cache pre-loading errors
        
        # For external loads (from tree), go directly to browse without delay
        # to avoid showing thumbnail view briefly
        if external_load:
            self.view_mode_manager.open_browse_view(target_image_index)
        else:
            QTimer.singleShot(50, lambda: self.view_mode_manager.open_browse_view(target_image_index))
        
        # Don't steal focus - let Qt handle tab navigation naturally
        self.activateWindow()
        self.raise_()

    def exclude_files_from_view(self):
        """Exclude files matching checked strings from the current thumbnail view"""
        # Only work in thumbnail view
        if self.current_view_mode != 'thumbnail':
            return
        
        # Get exclude directories from config
        settings = self.config.load_settings()
        exclude_dirs = settings.get('exclude_directories', [])
        if not isinstance(exclude_dirs, list):
            exclude_dirs = []
        
        # Get checked strings (those with enabled=True)
        checked_strings = []
        for exclude_dir in exclude_dirs:
            if isinstance(exclude_dir, dict):
                path = exclude_dir.get('path')
                enabled = exclude_dir.get('enabled', False)
                if enabled and path and path.strip():
                    checked_strings.append(path.strip())
        
        if not checked_strings:
            # No strings checked, nothing to do
            return
        
        # Get current displayed images
        if not hasattr(self, 'displayed_images') or not self.displayed_images:
            return
        
        # Filter out files that contain any of the checked strings anywhere in their path
        filtered_images = []
        for image_path in self.displayed_images:
            if not os.path.exists(image_path):
                continue
            # Get the full absolute path as a string
            full_path = os.path.abspath(image_path)
            # Check if any of the checked strings appear anywhere in the full path
            should_exclude = False
            for exclude_string in checked_strings:
                if exclude_string in full_path:
                    should_exclude = True
                    break
            if not should_exclude:
                filtered_images.append(image_path)
        
        # Check if exclusion would leave an empty list
        if not filtered_images:
            show_styled_warning(
                self,
                "Cannot Exclude",
                "Excluding these directories would leave no images to display.",
            )
            return
        
        # Update displayed_images and regenerate thumbnails
        self.displayed_images = filtered_images
        
        # Update highlight_index if it's now out of bounds
        if self.highlight_index >= len(self.displayed_images):
            self.highlight_index = max(0, len(self.displayed_images) - 1)
        
        # CRITICAL: Don't filter selections here - only remove files that no longer exist on disk
        # Filtering based on displayed_images can incorrectly remove selections if displayed_images
        # changes format or gets rebuilt. Selections should persist unless files are actually deleted.
        # Only filter out files that don't exist on disk
        if getattr(self, 'selected_files', None):
            # Only remove files that don't exist on disk (not files missing from displayed_images)
            filtered = {path for path in self.selected_files if os.path.exists(path)}
            self.selected_files = filtered
        
        # Regenerate thumbnails
        self.generate_thumbnails(force_refresh=True)

    def scan_for_faces(self, recursive: bool = True, max_depth: Optional[int] = None, after_scan=None, paths_to_scan: Optional[list] = None, directory_override: Optional[str] = None):
        """Scan current directory (optionally recursively) for faces and fill face cache. Runs in background thread.
        When recursive=False and paths_to_scan is provided, scans only those paths (ensures displayed images get cache).
        directory_override: when set (e.g. from tree), use this dir instead of get_current_search_directory.
        Uses same directory resolution and get_image_list as cmd-P (filter_by_person) for identical cache scope."""
        try:
            from face_engine import is_available
            if not is_available():
                from utils import show_styled_warning
                show_styled_warning(self, "Face recognition unavailable", "Install face_recognition (pip install face_recognition) to use this feature.")
                return
        except ImportError:
            from utils import show_styled_warning
            show_styled_warning(self, "Face recognition unavailable", "Install face_recognition to use this feature.")
            return
        # Same directory resolution as cmd-P (filter_by_person)
        current_directory = (directory_override if directory_override and os.path.isdir(directory_override) else
                            self.get_current_search_directory() or getattr(self, 'current_directory', None) or
                            (os.path.dirname(self.get_displayed_images()[0]) if self.get_displayed_images() else None))
        if not current_directory or not os.path.exists(current_directory):
            from utils import show_styled_warning
            show_styled_warning(self, "No directory", "No current directory to scan.")
            return
        settings = self.config.load_settings()
        if max_depth is None:
            max_depth = int(settings.get('search_depth', 4))
        if not recursive:
            # "Only current directory": avoid recursing into subdirectories.
            # max_depth=0: at root (depth 0), depth < 0 is False, so no subdirs are added.
            max_depth = 0
        from PySide6.QtWidgets import QProgressDialog, QApplication, QLabel
        from PySide6.QtCore import QObject, Signal, QTimer
        from face_scan_runner import get_image_list, run_scan
        from face_cache import normalize_path_for_face_cache, has_cached_faces

        filter_pattern = self.filter_pattern if hasattr(self, 'filter_pattern') else None
        if not recursive and paths_to_scan:
            # Normalize paths so cache keys match cmd-= directory scan
            image_paths = [normalize_path_for_face_cache(p) for p in paths_to_scan]
        else:
            image_paths = get_image_list(current_directory, max_depth, filter_pattern=filter_pattern)
        total = len(image_paths)
        if total == 0:
            from utils import show_styled_information
            show_styled_information(self, "Scan for faces", "No images found in this directory (and subdirs to depth {}).".format(max_depth))
            return

        # Derive unique directories in order of first appearance (for "x of y" dir indicator)
        _seen_dirs: set = set()
        _unique_dirs_ordered: List[str] = []
        for p in image_paths:
            d = os.path.normpath(os.path.dirname(p))
            if d not in _seen_dirs:
                _seen_dirs.add(d)
                _unique_dirs_ordered.append(d)
        _total_dirs = len(_unique_dirs_ordered)
        _dir_to_index = {d: i + 1 for i, d in enumerate(_unique_dirs_ordered)}

        # Ensure background face gathering is fully stopped and flushed before foreground starts.
        # Foreground has priority; buffers must be flushed before either can run.
        if hasattr(self, 'background_clip_controller') and self.background_clip_controller and self.background_clip_controller.is_process_running():
            self.background_clip_controller.flush_and_pause_process()
            self.background_clip_controller.wait_for_flush_and_pause(timeout=90.0)

        from face_gathering_coordinator import set_foreground_face_scan_active

        # Cache home once to avoid RecursionError in expanduser when progress fires rapidly
        try:
            _scan_home = os.path.expanduser("~")
        except RecursionError:
            _scan_home = "/"  # avoid os.environ which can also recurse

        def _dir_display(path: str) -> str:
            """Last 2 path qualifiers of dir, normalized (sub ~)."""
            try:
                path = str(path) if path is not None else ""
            except Exception:
                return ""
            if not path:
                return ""
            # If path has extension, treat as file and use its directory
            dir_path = os.path.dirname(path) if os.path.splitext(path)[1] else path
            if not dir_path:
                return "."
            try:
                expanded = os.path.expanduser(dir_path)
            except RecursionError:
                expanded = dir_path
            home = _scan_home
            if expanded == home:
                normalized = "~"
            elif expanded.startswith(home + os.sep):
                normalized = "~" + expanded[len(home):]
            else:
                normalized = expanded
            parts = [p for p in normalized.replace("\\", "/").split("/") if p]
            return "/".join(parts[-2:]) if parts else dir_path

        _init_dir = _dir_display(current_directory) if current_directory else ""
        def _format_progress_html(lines: list) -> str:
            return "".join(f'<p style="margin:0 0 0.5em 0">{html.escape(line)}</p>' for line in lines)

        def _prescan_label(examined: int, all_n: int, missing_running: int) -> str:
            _idl = f"Directory: {_init_dir}"
            if _total_dirs > 0:
                _idl = f"Directory: {_init_dir} (1 of {_total_dirs})"
            lines = [
                "Checking face cache…",
                _idl,
                f"Examined {examined} of {all_n} files",
                f"Images needing face detection: {missing_running}",
            ]
            return _format_progress_html(lines)

        progress_label = QLabel(_prescan_label(0, total, 0))
        progress_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        progress_label.setTextFormat(Qt.TextFormat.RichText)
        progress = QProgressDialog("", "Cancel", 0, total, self)
        progress.setLabel(progress_label)
        progress.setWindowTitle("Scan for faces")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.resize(500, 200)  # Make the dialog wider
        progress.show()
        QApplication.processEvents()

        cancel_flag = []
        progress.canceled.connect(lambda: cancel_flag.append(True))

        missing_total = 0
        for px, pth in enumerate(image_paths):
            if cancel_flag:
                progress.close()
                return
            if not has_cached_faces(normalize_path_for_face_cache(pth)):
                missing_total += 1
            if px == 0 or (px + 1) % 256 == 0 or (px + 1) == len(image_paths):
                progress_label.setText(_prescan_label(px + 1, total, missing_total))
                progress.setValue(px + 1)
                QApplication.processEvents()
        if cancel_flag:
            progress.close()
            return
        if missing_total == 0:
            progress.close()
            if callable(after_scan):
                try:
                    after_scan()
                except Exception:
                    pass
            if not callable(after_scan):
                from utils import show_styled_information
                show_styled_information(
                    self, "Scan for faces",
                    f"All {total} images already have face data in the cache (including images with no faces found).",
                )
            return

        progress.setMaximum(missing_total)
        progress.setValue(0)

        progress_slot = [progress]
        last_path_slot = [None]
        full_visit_slot = [0, total]
        missing_done_slot = [0]
        current_progress_slot = [0, missing_total]  # work done / work total — timer reads for UI
        import time
        start_ts = time.time()
        last_processed_ts = [start_ts]
        processed_durations: List[float] = []

        def _progress_label(
            work_done: int,
            work_tot: int,
            path: Optional[str] = None,
            visited_i: int = 0,
            visited_tot: int = 0,
        ) -> str:
            dir_part = _dir_display(path or last_path_slot[0] or "")
            remaining = _format_remaining(work_done, work_tot)
            dir_line = f"Directory: {dir_part}"
            if _total_dirs > 0:
                p = path or last_path_slot[0] or ""
                if p:
                    d = os.path.normpath(os.path.dirname(p))
                    idx = _dir_to_index.get(d, 0)
                    if idx > 0:
                        dir_line = f"Directory: {dir_part} ({idx} of {_total_dirs})"
            lines = [
                "Scanning for faces...",
                dir_line,
                f"Face detection: {work_done} of {work_tot} (not in cache)",
                f"Visited: {visited_i} of {visited_tot} files",
                f"Remaining: {remaining}" if remaining else "Remaining: --",
            ]
            return _format_progress_html(lines)

        def _format_remaining(work_done: int, work_tot: int) -> str:
            """Remaining time from uncached work only; avg from last processed images."""
            if work_tot <= 0 or work_done <= 0:
                return ""
            remaining_items = max(0, work_tot - work_done)
            if not processed_durations:
                return ""
            avg_sec = sum(processed_durations) / len(processed_durations)
            remaining_seconds = int(remaining_items * avg_sec)
            hrs, remainder = divmod(remaining_seconds, 3600)
            mins, secs = divmod(remainder, 60)
            if hrs > 0:
                return f"{hrs}:{mins:02d}:{secs:02d}"
            return f"{mins}:{secs:02d}"

        def _tick_time_left():
            prog = progress_slot[0] if progress_slot else None
            if not prog:
                return
            wd, wt = current_progress_slot[0], current_progress_slot[1]
            vi, vt = full_visit_slot[0], full_visit_slot[1]
            prog.setValue(min(wd, prog.maximum()))
            progress_label.setText(_progress_label(wd, wt, None, vi, vt))

        tick_timer = QTimer(self)
        tick_timer.setInterval(1000)
        tick_timer.timeout.connect(_tick_time_left)
        tick_timer.start()
        progress_label.setText(_progress_label(0, missing_total, None, 0, total))

        def on_finished(count):
            set_foreground_face_scan_active(False)  # Always clear; foreground scan done (complete or cancelled)
            try:
                if progress_slot and progress_slot[0]:
                    prog = progress_slot[0]
                    try:
                        prog.canceled.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    prog.close()
                    progress_slot[0] = None
                try:
                    tick_timer.stop()
                except Exception:
                    pass
            except Exception:
                pass
            if cancel_flag:
                return
            # Run after_scan first so the view updates before any blocking dialog.
            if callable(after_scan):
                try:
                    after_scan()
                except Exception:
                    pass
            from utils import show_styled_information
            # Skip info dialog when after_scan ran (e.g. filter-by-person) - results are the feedback.
            had_after_scan = callable(after_scan)
            if not had_after_scan:
                if count >= 0:
                    show_styled_information(self, "Scan for faces", "Checked for new images. {} newly scanned images had at least one face.".format(count))
                elif count == -2:
                    show_styled_information(self, "Scan for faces", "Scan encountered an error.")

        class FaceScanWorkerWithProgress(QThread):
            progress_signal = Signal(int, int, str, bool)
            finished_with_count = Signal(int)

            def run(self):
                cancel_flag_ref = cancel_flag
                prog_sig = self.progress_signal
                def report(i, tot, p, was_processed):
                    prog_sig.emit(i, tot, p, was_processed)
                def cancel():
                    return bool(cancel_flag_ref)
                override = image_paths if (not recursive and paths_to_scan) else None
                try:
                    n = run_scan(current_directory, max_depth, report, cancel, image_paths_override=override)
                    self.finished_with_count.emit(n)
                except Exception:
                    self.finished_with_count.emit(-2)

        def on_scan_progress(i, tot, path="", was_processed=False):
            MAX_NUMBER_OF_TIMINGS = 20
            prog = progress_slot[0] if progress_slot else None
            if not prog:
                return
            last_path_slot[0] = path
            full_visit_slot[0], full_visit_slot[1] = i, tot
            if was_processed:
                missing_done_slot[0] += 1
                current_progress_slot[0] = min(missing_done_slot[0], missing_total)
                now = time.time()
                dur = now - last_processed_ts[0]
                last_processed_ts[0] = now
                processed_durations.append(dur)
                if len(processed_durations) > MAX_NUMBER_OF_TIMINGS:
                    processed_durations.pop(0)
            # Progress bar and label updated by tick_timer (1 second intervals)
            # Throttle processEvents during skips to avoid deep recursion when dir cache
            # causes many rapid callbacks; still allow Cancel by processing every 100th.
            if was_processed or (i % 100) == 0:
                QApplication.processEvents()

        set_foreground_face_scan_active(True)  # Foreground has priority; blocks background face extraction
        worker = FaceScanWorkerWithProgress(self)
        worker.progress_signal.connect(on_scan_progress)
        worker.finished_with_count.connect(on_finished)
        worker.start()

    def show_filter_by_person_dialog(self, directory_override=None):
        """Show a dialog to pick a known person, then filter view to images containing that person.
        Uses same scope controls as cmd-K (directory checkbox, browse, recursive).
        When directory_override is provided (e.g. from tree context menu), pre-fills the directory
        field with that path (checked) and uses existing recursion setting."""
        try:
            from known_faces_manager import list_subjects
            subjects = list_subjects()
        except Exception:
            subjects = []
        if not subjects:
            from utils import show_styled_information
            show_styled_information(
                self, "Search by person",
                "No known people. Add people and face samples in Settings > Faces, then try again."
            )
            return
        subjects_sorted = sorted(subjects, key=lambda s: (s.get("name") or "Unnamed").lower())
        names = [s.get("name") or "Unnamed" for s in subjects_sorted]
        ids = [s.get("id") or "" for s in subjects_sorted]
        # Up to 4 (path, embedding) tuples per subject — same order as names/ids for dialog thumbs
        samples_per_subject = []
        for s in subjects_sorted:
            row = []
            for samp in (s.get("samples") or [])[:4]:
                p = samp.get("path") or ""
                e = samp.get("embedding")
                row.append((p, e if isinstance(e, list) else None))
            samples_per_subject.append(row)

        self._ensure_cnn_ui_helper_initialized()
        settings = self.config.load_settings() or {}
        saved_recursive = bool(settings.get("find_person_recursive", False))
        saved_subject_id = settings.get("find_person_subject_id") or ""
        current_dir = self.get_current_search_directory()
        if directory_override and os.path.isdir(directory_override):
            saved_dir_enabled = True
            saved_dir_path = directory_override
        else:
            saved_dir_enabled = bool(settings.get("find_person_dir_enabled", False))
            saved_dir_path = settings.get("find_person_dir") or ""

        dialog = self.cnn_similarity_ui_helper.create_person_search_dialog(
            names=names,
            ids=ids,
            saved_subject_id=saved_subject_id,
            saved_recursive=saved_recursive,
            saved_dir_enabled=saved_dir_enabled,
            saved_dir_path=saved_dir_path,
            directory=directory_override or current_dir,
            samples_per_subject=samples_per_subject,
        )

        tree_had_focus = getattr(self, '_tree_had_focus_when_invoked', False)
        dir_to_prefill = directory_override if (directory_override and os.path.isdir(directory_override)) else (current_dir if tree_had_focus and current_dir and os.path.isdir(current_dir) else None)
        if dir_to_prefill:
            if hasattr(dialog, 'dir_checkbox'):
                dialog.dir_checkbox.setChecked(True)
            if hasattr(dialog, 'dir_input'):
                dialog.dir_input.setText(dir_to_prefill)

        if saved_subject_id and saved_subject_id in ids:
            dialog.combo.setCurrentIndex(ids.index(saved_subject_id))

        if not dialog.exec():
            return

        idx = dialog.combo.currentIndex()
        selected_id = dialog.ids[idx]
        recursive = dialog.recursive_checkbox.isChecked()
        dir_checkbox_checked = dialog.dir_checkbox.isChecked() if hasattr(dialog, 'dir_checkbox') else False
        search_directory = dialog.dir_input.text().strip() if dir_checkbox_checked and hasattr(dialog, 'dir_input') else None

        try:
            self.config.update_setting("find_person_subject_id", selected_id)
            self.config.update_setting("find_person_recursive", recursive)
            self.config.update_setting("find_person_dir_enabled", dir_checkbox_checked)
            self.config.update_setting("find_person_dir", dialog.dir_input.text().strip() if hasattr(dialog, 'dir_input') else "")
        except Exception:
            pass

        self.filter_by_person(selected_id, recursive=recursive, search_directory=search_directory)

    def filter_by_person(
        self,
        subject_id: str,
        recursive: bool = False,
        search_directory: Optional[str] = None,
        _skip_autoscan: bool = False,
        _prebuilt_displayed: Optional[List[str]] = None,
    ):
        """Filter current view to images that contain the given person (by subject id from known faces).
        Uses same scope rules as cmd-K: search_directory (when dir checkbox checked), recursive, displayed files.
        _prebuilt_displayed: when set, skip collecting paths (e.g. after face scan) to avoid a second directory walk."""
        from known_faces_manager import get_subject

        subject = get_subject(subject_id) if subject_id else None
        if not subject or not subject.get("samples"):
            from utils import show_styled_warning
            show_styled_warning(self, "Search by person", "No face samples found for this person.")
            return
        known_encodings = [s["embedding"] for s in subject.get("samples", []) if s.get("embedding")]
        if not known_encodings:
            from utils import show_styled_warning
            show_styled_warning(self, "Search by person", "No face encodings for this person.")
            return

        if _prebuilt_displayed is not None:
            QApplication.processEvents()
            self._person_search_run_after_paths_ready(
                subject_id,
                subject,
                known_encodings,
                list(_prebuilt_displayed),
                recursive,
                search_directory,
                _skip_autoscan,
                None,
            )
            return

        current_displayed = self.get_displayed_images() or []
        current_dir = self.get_current_search_directory()
        if not current_dir and current_displayed:
            current_dir = os.path.dirname(current_displayed[0])
        if not current_dir:
            current_dir = getattr(self, 'current_directory', None) or os.path.expanduser('~')

        filter_pattern = self.filter_pattern if hasattr(self, 'filter_pattern') else None
        settings = self.config.load_settings() or {}
        max_depth = int(settings.get('search_depth', 4))

        if recursive:
            resolved_sd = (
                os.path.expanduser(search_directory.strip())
                if (search_directory and search_directory.strip())
                else None
            )
            if resolved_sd and os.path.isdir(resolved_sd):
                search_dir = resolved_sd
            else:
                search_dir = current_dir
            from utils import is_root_or_system_volume, show_styled_warning
            if is_root_or_system_volume(search_dir):
                if search_dir == '/':
                    show_styled_warning(self, "Action Not Available", "Recursive search is not available on the root directory.")
                else:
                    show_styled_warning(self, "Action Not Available", "Recursive search is not available on system volumes.")
                return

        QApplication.processEvents()

        self._person_search_prep_seq = getattr(self, '_person_search_prep_seq', 0) + 1
        prep_seq = self._person_search_prep_seq

        prev_cancel = getattr(self, '_person_face_match_cancel', None)
        if prev_cancel is not None:
            prev_cancel.set()
        old_prog = getattr(self, '_person_face_search_progress', None)
        if old_prog is not None:
            try:
                old_prog.close()
                old_prog.deleteLater()
            except Exception:
                pass
            self._person_face_search_progress = None
            QApplication.processEvents()

        progress = QProgressDialog(
            "Gathering images to search…",
            None,
            0,
            0,
            self,
        )
        progress.setWindowTitle("Search by person")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setRange(0, 0)
        self._person_face_search_progress = progress
        progress.show()
        progress.raise_()
        progress.activateWindow()
        QApplication.processEvents()

        prep_worker = PersonSearchPrepWorker(
            recursive,
            search_directory,
            current_dir,
            list(current_displayed),
            filter_pattern,
            max_depth,
            self,
        )
        prep_worker.finished.connect(prep_worker.deleteLater)
        self._person_search_prep_ctx = {
            'prep_seq': prep_seq,
            'progress': progress,
            'prep_worker': prep_worker,
            'subject_id': subject_id,
            'subject': subject,
            'known_encodings': known_encodings,
            'recursive': recursive,
            'search_directory': search_directory,
            '_skip_autoscan': _skip_autoscan,
        }
        prep_worker.finished_paths.connect(
            self._on_person_search_prep_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        prep_worker.start()

    @Slot(object)
    def _on_person_search_prep_finished(self, displayed_paths):
        ctx = getattr(self, '_person_search_prep_ctx', None)
        if not ctx:
            return
        prep_seq = ctx['prep_seq']
        if prep_seq != self._person_search_prep_seq:
            try:
                ctx['progress'].close()
                ctx['progress'].deleteLater()
            except Exception:
                pass
            if getattr(self, '_person_face_search_progress', None) is ctx['progress']:
                self._person_face_search_progress = None
            return

        progress = ctx['progress']
        subject_id = ctx['subject_id']
        subject = ctx['subject']
        known_encodings = ctx['known_encodings']
        recursive = ctx['recursive']
        search_directory = ctx['search_directory']
        _skip_autoscan = ctx['_skip_autoscan']
        self._person_search_prep_ctx = None

        displayed = list(displayed_paths) if displayed_paths else []
        self._person_search_run_after_paths_ready(
            subject_id,
            subject,
            known_encodings,
            displayed,
            recursive,
            search_directory,
            _skip_autoscan,
            progress,
        )

    def _person_search_run_after_paths_ready(
        self,
        subject_id: str,
        subject,
        known_encodings: List,
        displayed: List[str],
        recursive: bool,
        search_directory: Optional[str],
        _skip_autoscan: bool,
        prep_progress: Optional[Any],
    ):
        from face_cache import get_encodings
        from PySide6.QtWidgets import QPushButton

        person_label = subject.get("name") or "this person"

        if not displayed:
            if prep_progress is not None:
                try:
                    prep_progress.close()
                    prep_progress.deleteLater()
                except Exception:
                    pass
                self._person_face_search_progress = None
            from utils import show_styled_information
            show_styled_information(self, "Search by person", "No images found in the current search space.")
            return

        if not _skip_autoscan:
            try:
                sample_paths = displayed[:30]
                any_missing_cache = False
                for path in sample_paths:
                    try:
                        enc = get_encodings(path)
                        if not enc:
                            any_missing_cache = True
                            break
                    except Exception:
                        any_missing_cache = True
                        break

                if any_missing_cache:
                    if prep_progress is not None:
                        try:
                            prep_progress.close()
                            prep_progress.deleteLater()
                        except Exception:
                            pass
                        self._person_face_search_progress = None
                    displayed_copy = list(displayed)
                    self.scan_for_faces(
                        recursive=False,
                        after_scan=lambda: self.filter_by_person(
                            subject_id,
                            recursive=recursive,
                            search_directory=search_directory,
                            _skip_autoscan=True,
                            _prebuilt_displayed=displayed_copy,
                        ),
                        paths_to_scan=displayed,
                    )
                    return
            except Exception:
                pass

        # After autoscan: same coordination as scan_for_faces — pause background CLIP before heavy face_cache reads.
        # (Do not flush before autoscan's scan_for_faces branch, or we would return without resuming the worker.)
        self._person_search_paused_background_clip = False
        try:
            if getattr(self, 'background_clip_controller', None) and self.background_clip_controller.enabled:
                if self.background_clip_controller.is_process_running():
                    self.background_clip_controller.flush_and_pause_process()
                    self.background_clip_controller.wait_for_flush_and_pause(timeout=90.0)
                    self._person_search_paused_background_clip = True
        except Exception:
            pass

        QApplication.processEvents()

        progress = prep_progress
        if progress is None:
            progress = QProgressDialog(
                "Searching images for \"{}\"…".format(person_label),
                "Cancel",
                0,
                0,
                self,
            )
            progress.setWindowTitle("Search by person")
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setMinimumDuration(0)
            progress.setAutoClose(False)
            progress.setAutoReset(False)
            progress.setRange(0, 0)
            progress.show()
            progress.raise_()
            progress.activateWindow()
            QApplication.processEvents()
        else:
            progress.setLabelText("Searching images for \"{}\"…".format(person_label))
            progress.setCancelButton(QPushButton("Cancel"))

        self._person_face_search_progress = progress

        self._person_face_search_seq = getattr(self, '_person_face_search_seq', 0) + 1
        seq = self._person_face_search_seq
        prev_cancel = getattr(self, '_person_face_match_cancel', None)
        if prev_cancel is not None:
            prev_cancel.set()
        cancel_event = threading.Event()
        self._person_face_match_cancel = cancel_event

        worker = PersonFaceMatchWorker(displayed, known_encodings, cancel_event, self)
        self._person_face_match_worker = worker
        self._person_face_search_ctx = {
            'seq': seq,
            'progress': progress,
            'cancel_event': cancel_event,
            'worker': worker,
            'person_label': person_label,
            'subject': subject,
        }

        progress.canceled.connect(cancel_event.set)
        worker.finished_ok.connect(
            self._person_face_search_on_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished_canceled.connect(
            self._person_face_search_on_canceled,
            Qt.ConnectionType.QueuedConnection,
        )
        QApplication.processEvents()
        QTimer.singleShot(0, worker.start)

    def _person_face_search_clear_ctx(self, ctx):
        if getattr(self, '_person_face_search_ctx', None) is ctx:
            self._person_face_search_ctx = None
        prog = ctx.get('progress')
        w = ctx.get('worker')
        ev = ctx.get('cancel_event')
        if getattr(self, '_person_face_search_progress', None) is prog:
            self._person_face_search_progress = None
        if getattr(self, '_person_face_match_worker', None) is w:
            self._person_face_match_worker = None
        if getattr(self, '_person_face_match_cancel', None) is ev:
            self._person_face_match_cancel = None
        if w is not None:
            w.deleteLater()

    def _person_search_resume_background_clip_if_needed(self):
        """After person search, resume background CLIP if we flushed/paused for coordination."""
        if not getattr(self, '_person_search_paused_background_clip', False):
            return
        self._person_search_paused_background_clip = False
        try:
            bc = getattr(self, 'background_clip_controller', None)
            if bc and bc.enabled:
                bc.resume_process(priority_directory=getattr(self, 'current_directory', None))
        except Exception:
            pass

    @Slot(object)
    def _person_face_search_on_finished(self, matching_with_dist_raw):
        try:
            ctx = getattr(self, '_person_face_search_ctx', None)
            if not ctx:
                return
            seq = ctx['seq']
            progress = ctx['progress']
            cancel_event = ctx['cancel_event']
            person_label = ctx['person_label']
            subject = ctx['subject']

            if seq != self._person_face_search_seq:
                try:
                    progress.close()
                    progress.deleteLater()
                except Exception:
                    pass
                self._person_face_search_clear_ctx(ctx)
                return

            was_canceled = cancel_event.is_set() or progress.wasCanceled()
            try:
                progress.close()
                progress.deleteLater()
            except Exception:
                pass
            self._person_face_search_clear_ctx(ctx)

            if was_canceled:
                if getattr(self, 'status_bar_manager', None):
                    self.status_bar_manager.show_message("Person search canceled")
                return

            try:
                matching_with_dist = list(matching_with_dist_raw)
            except (TypeError, ValueError):
                matching_with_dist = []
            matching_with_dist.sort(key=lambda x: x[1])
            matching = [p for p, _ in matching_with_dist]
            if not matching:
                from utils import show_styled_information
                show_styled_information(
                    self,
                    "Search by person",
                    "No images in the current search space contain \"{}\".".format(person_label)
                )
                return

            # Successful search: show results in the thumbnail grid (same as cmd-K similarity flow)
            if self.current_view_mode == 'list':
                self.toggle_list_view()
                QApplication.processEvents()
            if self.current_view_mode == 'browse':
                self.close_browse_view()
                QApplication.processEvents()

            try:
                if hasattr(self, 'directory_stack_history_handler'):
                    current_state = self.directory_stack_history_handler.capture_current_state()
                    if current_state:
                        # Do not set specific_files to the full directory listing here.
                        # capture_current_state() already records [] for directory mode and the
                        # true list when specific_files_active; forcing prev_displayed into
                        # specific_files makes ESC restore load_specific_files() and leaves
                        # specific_files_active True after returning to a directory view.
                        self.directory_stack_history_handler.backward_stack.append(current_state)
                        self.directory_stack_history_handler.forward_stack.clear()
            except Exception:
                pass

            preserve = self.get_current_image_path()
            if preserve not in matching:
                preserve = None
            self.current_sort_mode = SortMode.CUSTOM
            self.is_reversed = False
            if hasattr(self, "load_specific_files"):
                self.load_specific_files(matching, external_load=True)
            else:
                self.configuration_sync_manager._set_displayed_images_with_sync(matching, sync=True)
                self.generate_thumbnails(force_refresh=False)

            if preserve and preserve in matching:
                self.set_current_image_by_path(preserve, fallback_index=0)
            elif matching:
                self.set_current_image_by_path(matching[0], fallback_index=0)
            self.populate_indices_arrays()
            self._sync_highlight_index_from_current_image_path(matching)
            self.highlight_image()
            self.update_status_bar_sections()
            if getattr(self, 'status_bar_manager', None):
                self.status_bar_manager.show_message("Showing images containing {}".format(subject.get("name") or "person"))
        finally:
            self._person_search_resume_background_clip_if_needed()

    @Slot()
    def _person_face_search_on_canceled(self):
        try:
            ctx = getattr(self, '_person_face_search_ctx', None)
            if not ctx:
                return
            seq = ctx['seq']
            progress = ctx['progress']
            if seq != self._person_face_search_seq:
                try:
                    progress.close()
                    progress.deleteLater()
                except Exception:
                    pass
                self._person_face_search_clear_ctx(ctx)
                return
            try:
                progress.close()
                progress.deleteLater()
            except Exception:
                pass
            self._person_face_search_clear_ctx(ctx)
            if getattr(self, 'status_bar_manager', None):
                self.status_bar_manager.show_message("Person search canceled")
        finally:
            self._person_search_resume_background_clip_if_needed()

    def generate_thumbnails(self, force_refresh=False):
        """Create responsive thumbnail grid with canvas-based display"""
        return self.thumbnail_display_manager.generate_thumbnails(force_refresh)

    def _start_throttled_thumbnail_loading(self, images_to_process):
        """Start loading thumbnails using background worker to avoid blocking UI"""
        if not images_to_process:
            return
        
        # Cancel any existing worker FIRST, before creating a new one
        # Store reference to old worker to avoid race conditions with delayed cleanup
        old_worker = None
        if getattr(self, 'thumbnail_worker', None):
            try:
                if self.thumbnail_worker.isRunning():
                    self.thumbnail_worker.cancel()
                    # Store reference for delayed cleanup
                    old_worker = self.thumbnail_worker
                    # Clear reference immediately so new worker can be created
                    self.thumbnail_worker = None
                else:
                    # Worker not running, just clear reference
                    old_worker = self.thumbnail_worker
                    self.thumbnail_worker = None
            except Exception:
                # If anything goes wrong, clear reference and continue
                try:
                    old_worker = self.thumbnail_worker
                except:
                    pass
                self.thumbnail_worker = None
        
        # Schedule cleanup of old worker (if any) after a delay
        # This prevents blocking but doesn't interfere with new worker creation
        if old_worker:
            def cleanup_old_worker():
                try:
                    # Wait for old worker to finish (with timeout to avoid blocking)
                    if old_worker and old_worker.isRunning():
                        old_worker.wait(100)  # Wait up to 100ms for graceful shutdown
                except Exception:
                    pass
            QTimer.singleShot(100, cleanup_old_worker)
        
        # Create and start the background worker IMMEDIATELY
        # Don't wait for cleanup - start loading thumbnails right away
        self.thumbnail_worker = ThumbnailLoadingWorker(
            self.cache_manager, 
            images_to_process, 
            self.current_thumbnail_size, 
            self
        )
        
        # Connect signals
        self.thumbnail_worker.thumbnail_loaded.connect(self._on_thumbnail_loaded_from_worker)
        self.thumbnail_worker.finished.connect(self._on_thumbnail_worker_finished)
        self.thumbnail_worker.error.connect(self._on_thumbnail_worker_error)
        self.thumbnail_worker.progress_updated.connect(self._on_thumbnail_progress_updated)
        
        # Start immediately - don't wait for cleanup
        self.thumbnail_worker.start()

    def populate_indices_arrays(self):
        """Populate the image indices arrays for navigation"""
        return self.thumbnail_display_manager.populate_indices_arrays()

    def clear_thumbnails(self):
        """Clear all thumbnail widgets and reset state"""
        # Clear canvas thumbnails
        if self.thumbnail_container:
            self.thumbnail_container.clear_thumbnails()

        # CRITICAL: Don't clear selections in clear_thumbnails() - this is called during refresh
        # and should preserve selections. Selections should only be cleared explicitly by user actions.

    def get_image_info(self, image_path: str) -> tuple[str, int, int]:
        """Get image file name and dimensions using cache with EXIF correction"""
        try:
            # Try to get metadata from cache first (synchronous)
            metadata = self.cache_manager.get_metadata_sync(image_path)
            if metadata and metadata.width > 0 and metadata.height > 0:
                return metadata.filename, metadata.width, metadata.height
            
            # If metadata doesn't have dimensions, try to get them quickly
            try:
                dimensions = get_image_dimensions_fast_metadata(image_path)
                if dimensions:
                    width, height = dimensions
                    return os.path.basename(image_path), width, height
            except ImportError:
                pass
            
            # Fallback to direct QPixmap loading (slowest)
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                return os.path.basename(image_path), 0, 0
            
            result = os.path.basename(image_path), pixmap.width(), pixmap.height()
            return result
        except Exception:
            return os.path.basename(image_path), 0, 0

    def get_widget_count(self) -> int:
        """Get total number of widgets (single source of truth for count)"""
        return len(self.displayed_images)
    
    def find_thumbnail_index_by_path(self, path):
        """Find thumbnail index by image path"""
        if self.displayed_images:
            try:
                return self.displayed_images.index(path)
            except ValueError:
                return None
        return None
    
    # @entry_debug_wrapper(dump_stack=True, showParms=True, printval="highlight_index")
    @safe_refresh_wrapper # DGN works fine w/o this but testing for possible hangs
    def highlight_image(self):
        """Highlight the current image."""
        result = self.image_display_manager.highlight_image()
        # Update separator bold states for EXIF date mode
        if (hasattr(self, 'thumbnail_container') and 
            hasattr(self.thumbnail_container, 'canvas') and
            hasattr(self.thumbnail_container.canvas, 'update_separator_bold_states')):
            self.thumbnail_container.canvas.update_separator_bold_states()
        return result

    def select_all_thumbnails(self):
        """Select all thumbnails in thumbnail mode"""
        return self.selection_manager.select_all_thumbnails()
    
    def clear_selection(self, hilite=True):
        """Clear all selected thumbnails"""
        return self.selection_manager.clear_selection(hilite)

    def _get_selected_indices_for_display(self) -> set:
        """Convert selected_files to indices for visual display only"""
        indices = set()
        if not self.displayed_images:
            return indices
        for i, image_path in enumerate(self.displayed_images):
            if image_path in self.selected_files:
                indices.add(i)
        return indices

    def _emit_selection_changed(self, highlight_index: Optional[int] = None):
        """Emit SELECTION_CHANGED event - subscribers (SelectionManager, MenuManager) react.
        Payload: (selected_files: Set[str], highlight_index: Optional[int])"""
        from event_bus import SELECTION_CHANGED
        selected = set(getattr(self, 'selected_files', set()))
        self.event_bus.emit(SELECTION_CHANGED, (selected, highlight_index))

    def _emit_view_mode_changed(self):
        """Emit VIEW_MODE_CHANGED event - subscribers (UILayoutManager, SidebarManager, etc.) react."""
        if hasattr(self, 'event_bus') and self.event_bus:
            from event_bus import VIEW_MODE_CHANGED
            mode = getattr(self, 'current_view_mode', 'thumbnail')
            self.event_bus.emit(VIEW_MODE_CHANGED, mode)

    def update_canvas_selection(self, highlight_index: Optional[int] = None):
        """Centralized method to update canvas selection state"""
        return self.selection_manager.update_canvas_selection(highlight_index)
 
    def select_thumbnail(self, index: int, add_to_selection: bool = False):
        """Optimized selection logic for thumbnails."""
        if not (0 <= index < len(self.displayed_images)):
            return

        # Get the file path for this index
        file_path = self.displayed_images[index]

        # Alias for state resets below -- avoids repeated statements
        def reset_cmd_multi_state():
            self.cmd_multi_origin_index = None
            self.cmd_multi_axis = None
            self.cmd_multi_sign = 0

        # Save previous current image path before updating (needed for multi-select logic)
        previous_current_path = self.get_current_image_path()
        
        # CRITICAL: Set current image by path (source of truth) - this derives highlight_index
        self.set_current_image_by_path(file_path)
        
        if add_to_selection:
            # If multi-selection is empty, add the previous current image first (if different from clicked file)
            # This ensures the current image is part of a multiple selection when starting a new multi-selection
            if (len(self.selected_files) == 0 and
                previous_current_path and 
                previous_current_path != file_path and 
                previous_current_path not in self.selected_files):
                self.selected_files.add(previous_current_path)
            
            if (
                file_path == self.get_current_image_path()
                and not self.selected_files
                and not self.multi_select_mode
            ):
                # Start multi-select mode with initial selection
                self.selected_files.add(file_path)
                self._emit_selection_changed()
            elif file_path in self.selected_files and len(self.selected_files) > 1:
                # Deselect if already selected in multi-select mode
                self.selected_files.remove(file_path)
                self._emit_selection_changed()
                reset_cmd_multi_state()
                self.highlight_image()
            else:
                # Add to selection (multi-select)
                self.selected_files.add(file_path)
                self._emit_selection_changed()
                reset_cmd_multi_state()
                self.highlight_image()
        else:
            # Single selection only
            self.selected_files.clear()
            self.selected_files.add(file_path)
            self._emit_selection_changed()
            self.highlight_image()
            self.image_display_manager.display_current_image()

    def delete_selected_files(self, force_confirmation=False):
        """Delete all selected files"""     
        if self.current_view_mode == 'browse':
            self.file_operations_manager.delete_selected_files(force_confirmation)
        elif self.current_view_mode == 'thumbnail':
            self.file_operations_manager.delete_selected_files(force_confirmation)
            QTimer.singleShot(300, self.sequential_refresh_after_browse) 



    def _ensure_fullscreen_focus(self):
        """Ensure proper focus for browse keyboard event handling"""
        self.browse_view_handler.ensure_browse_view_focus()

    def open_current_browse_view(self):
        """Open the currently highlighted image in browse, or selected images as a group"""
        return self.view_manager.open_current_browse_view()

    def reset_image_label_for_fullscreen(self):
        """Reset the image label for browse display"""
        self.browse_view_handler.reset_image_label_for_browse_view()

    def set_name_sort(self, reverse: bool = False):
        """Set name sort mode with specified direction"""
        return self.sorting_manager.set_name_sort(reverse)

    def set_date_sort(self, reverse: bool = False, *, notify: bool = True):
        """Set date sort mode with specified direction"""
        return self.sorting_manager.set_date_sort(reverse, notify=notify)

    def set_exif_date_sort(self, reverse: bool = False):
        """Set EXIF date sort mode with specified direction"""
        return self.sorting_manager.set_exif_date_sort(reverse)

    def set_exif_year_sort(self, reverse: bool = False):
        """Set EXIF year sort mode with specified direction"""
        return self.sorting_manager.set_exif_year_sort(reverse)

    def set_size_sort(self, reverse: bool = False):
        """Set size sort mode with specified direction"""
        return self.sorting_manager.set_size_sort(reverse)

    def set_dimensions_sort(self, reverse: bool = False):
        """Set dimensions sort mode with specified direction"""
        return self.sorting_manager.set_dimensions_sort(reverse)

    def simple_reverse_image_order(self):
        """Simple reverse: toggle the current sort direction without changing sort mode"""
        return self.sorting_manager.simple_reverse_image_order()

    def set_custom_sort(self):
        """Set custom sort mode, loading from .prsort file if available"""
        
        if self.current_view_mode == 'slideshow2':
            self.slideshow2_manager.stop_slideshow2()

        if self.current_view_mode == 'slideshow':
            self.keyboard_handler_manager.handlers['slideshow']._handle_c_key(None, None)
            return

        displayed = self.get_displayed_images()
        if not displayed:
            return
        
        # Reset other sort modes
        if self.current_sort_mode == SortMode.RANDOM:
            self.reset_to_original_order()
            # Continue to set custom sort mode (don't return early)
        
        # Check if all files are from the same directory
        directories = set(os.path.dirname(path) for path in displayed)
        if len(directories) != 1:
            if self.status_notification:
                self.status_notification.show_message("Custom sort requires all files from the same directory")
            return
        
        # Use unified sort method
        self.set_sort_mode(SortMode.CUSTOM)
        
        # Show status message
        directory = os.path.dirname(displayed[0])
        prsort_exists = os.path.exists(self.sorting_manager._get_prsort_file_path(directory))
        if prsort_exists:
            # self.status_notification.show_message("Sort mode set to Custom")
            pass # DGN
        else:
            self.status_notification.show_message("Sort mode set to Custom (no saved order - Used drop or ⌘-S)")

    def update_sort_menu_checkmarks(self):
        """Update the checkmarks on sort menu items based on current sort state"""
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_sort_menu_checkmarks()







    def reset_to_original_order(self):
        """Reset to original sequential order"""
        displayed = self.get_displayed_images()
        if not displayed:
            return
        
        # Save current image path to preserve selection
        # CRITICAL: Use current_image_path as source of truth, not highlight_index
        current_image_path = self.get_current_image_path()
        
        # Re-sort images by date to restore original order
        def get_sort_key(path):
            try:
                # Quick check for cached metadata first
                cache_key = self.cache_manager.get_cache_key(path)
                if cache_key in self.cache_manager.metadata_cache:
                    metadata = self.cache_manager.metadata_cache[cache_key]
                    if metadata and hasattr(metadata, 'modified_time') and metadata.modified_time:
                        return metadata.modified_time
                # Fallback to file system stat
                mtime = os.path.getmtime(path)
                return mtime
            except (OSError, AttributeError):
                # Fallback to name sorting if stat fails
                return 0  # Will be sorted to beginning
        
        try:
            # Sort by date, newest first (reverse=True)
            displayed.sort(key=get_sort_key, reverse=True)
            # Update displayed_images to new sorted order
            self.displayed_images = displayed
        except Exception:
            # If date sorting fails completely, ignore the error
            pass
        
        # Reset all sorting flags and set to date mode
        self.current_sort_mode = SortMode.DATE
        self.is_reversed = False
        
        # Find where the current image ended up in the new order and update indices
        if current_image_path:
            try:
                new_index = self.displayed_images.index(current_image_path)
                self.highlight_index = new_index
                self.current_index = new_index
            except (ValueError, IndexError):
                # If not found, clamp both indices
                max_idx = max(0, len(self.displayed_images) - 1)
                self.highlight_index = min(self.highlight_index, max_idx)
                self.current_index = min(self.current_index, max_idx)
        
        # Ensure we have basic sequential indices
        if not hasattr(self, 'image_indices') or not self.image_indices:
            self.image_indices = list(range(len(self.displayed_images)))
        
        # Update canvas selection to reflect selections in new order
        # Since selected_files uses file paths, selections persist automatically
        self._emit_selection_changed()
        
        # Reorder the existing thumbnails without regenerating
        self.thumbnail_display_manager.reorder_thumbnail_layout()
        
        # After reordering, ensure the highlight is on the correct image
        # and scroll to show it (highlight_image already does scroll_to_highlighted)
        self.highlight_image()
        
        if self.status_notification:
            self.status_notification.show_message("Reset to sequential order")
        
        # Update UI
        self.update_status_bar_sections()
        self.update_sort_menu_checkmarks()


    def get_scrollbar_width(self):
        """Get the actual scrollbar width from Qt style"""
        try:
            
            # Get the application instance
            app = QApplication.instance()
            if app:
                # Get the scrollbar extent from the current style
                return app.style().pixelMetric(QStyle.PM_ScrollBarExtent)
            else:
                # Fallback if no application instance
                return 15  # Default macOS value
        except (ImportError, AttributeError):
            # Fallback if PySide6 is not available or method doesn't exist
            return 15  # Default macOS value

    def debounce_refresh_directory(self):
        """Debounce refresh directory"""
        # CRITICAL: Reuse existing timer instead of creating a new one to avoid GIL deadlock.
        # Creating a new QTimer and connecting signals requires dropping the GIL, which can
        # deadlock when called from within a timer callback while worker threads are waiting.
        if not hasattr(self, '_refresh_directory_timer'):
            # Initialize timer if it doesn't exist (shouldn't happen, but be safe)
            self._refresh_directory_timer = QTimer()
            self._refresh_directory_timer.setSingleShot(True)
            self._refresh_directory_timer.timeout.connect(self.refresh_directory)
        
        self._refresh_directory_timer.stop()
        # Stop any thumbnail loading in progress before refreshing directory (non-blocking)
        if getattr(self, 'thumbnail_worker', None):
            try:
                if self.thumbnail_worker.isRunning():
                    self.thumbnail_worker.requestInterruption()
                    # Use non-blocking cleanup instead of blocking wait
                    self.cleanup_worker_thread('thumbnail_worker', delete_after=False)
            except Exception:
                pass
        self._refresh_directory_timer.start(260)

    def set_thumbnail_size(self, size: int):
        """Set thumbnail size and recalculate layout"""
        self.thumbnail_operations_manager.set_thumbnail_size(size)
        self.debounce_refresh_directory()

    @safe_thumbnail_wrapper
    def start_background_thumbnail_loading_if_needed(self):
        """Start loading thumbnails in the background if they're not loaded yet"""
        if not self.displayed_images:
            return
        
        # Check if thumbnails actually need loading before starting worker
        # This avoids unnecessary progress bars when thumbnails are already loaded
        if getattr(self, 'thumbnail_container', None):
            if hasattr(self.thumbnail_container, 'canvas') and self.thumbnail_container.canvas:
                canvas = self.thumbnail_container.canvas
                with QMutexLocker(canvas.mutex):
                    # If no thumbnails exist yet, we need to load them
                    if not hasattr(canvas, 'thumbnails') or not canvas.thumbnails or len(canvas.thumbnails) == 0:
                        # Thumbnails don't exist yet - need to load them
                        pass  # Continue to start worker
                    else:
                        # Check if any thumbnails are missing pixmaps
                        needs_loading = False
                        for thumbnail in canvas.thumbnails:
                            if thumbnail.pixmap is None or thumbnail.pixmap.isNull():
                                needs_loading = True
                                break
                        
                        # Only skip worker if all thumbnails already have pixmaps
                        if not needs_loading:
                            return
        
        # Start loading thumbnails - cancel any existing worker and start a new one
        self._start_throttled_thumbnail_loading(self.displayed_images)
    
    def set_dynamic_thumbnail_size(self):
        """Set thumbnail size dynamically based on available space"""
        # Don't override manual size settings
        if self.manual_thumbnail_size:
            return
            
        optimal_size = self.thumbnail_operations_manager.calculate_optimal_thumbnail_size()
        # Force size update even if it's the same to ensure layout is correct
        self._force_thumbnail_size_update(optimal_size)
    
    def _force_thumbnail_size_update(self, size: int):
        """Force thumbnail size update even if size hasn't changed"""
        # Only enforce bounds if not manually set by user
        if not self.manual_thumbnail_size:
            # Single image: size comes from viewport-based calculation, do not cap at MAX_THUMBNAIL_SIZE
            if len(self.displayed_images) > 1:
                size = max(MIN_THUMBNAIL_SIZE, min(MAX_THUMBNAIL_SIZE, size))
            else:
                size = max(MIN_THUMBNAIL_SIZE, size)
        else:
            # For manual sizing, only enforce maximum bound to prevent UI issues
            size = min(MAX_THUMBNAIL_SIZE, size)
        
        # Check if size actually changed to avoid unnecessary refreshes
        size_changed = self.current_thumbnail_size != size
        
        # Update current thumbnail size
        self.current_thumbnail_size = size
        
        # Only update canvas if thumbnails exist
        canvas = self.thumbnail_container.canvas
        if self.displayed_images:
            # Update the canvas thumbnail size
            canvas.thumbnail_size = size
            
            if size_changed:
                # Size changed - need full reorder with grid recalculation
                canvas.reorder_thumbnails(self.displayed_images, force_recalculate_grid=True)
                # Ensure current image stays on screen after layout shift (e.g. overlay 1→2 lines)
                QTimer.singleShot(50, self.ensure_highlighted_visible)
            else:
                # Size hasn't changed but viewport might have - recalculate grid layout efficiently
                # Check if columns would actually change before recalculating to minimize flashing
                old_columns = canvas.columns
                # Temporarily calculate new columns to see if they'd change
                from thumbnail_constants import BASE_MARGIN, THUMBNAIL_SPACING, BORDER_SPACE
                viewport_width = canvas.get_viewport_width()
                available_width = viewport_width - (BASE_MARGIN * 2)
                if available_width > 0:
                    cell_width = canvas.thumbnail_size + BORDER_SPACE + THUMBNAIL_SPACING
                    new_columns = max(1, available_width // cell_width)
                    if new_columns != old_columns:
                        # Columns changed - need to recalculate grid
                        canvas.calculate_grid_layout()
                        canvas.update()
                        # Ensure current image stays on screen after layout shift
                        QTimer.singleShot(50, self.ensure_highlighted_visible)
                    # If columns didn't change, no need to recalculate - avoids flash
 
    def get_displayed_images(self) -> List[str]:
        """Get the list of images currently being displayed"""
        # Use FileDataModel as source of truth, but fall back to displayed_images for compatibility
        try:
            if getattr(self, 'file_data_model', None):
                model_images = self.file_data_model.get_displayed_images()
                if model_images:
                    return model_images
        except Exception:
            # If FileDataModel not ready or error, fall back to displayed_images
            pass
        # Fallback to displayed_images attribute (always available)
        return self.displayed_images if getattr(self, 'displayed_images', None) else []
    
    def show_help_test(self):
        """Show help dialog in a modal window"""
        return self.help_dialog.show_help()
    def on_known_faces_external_update(self):
        """Known faces JSON or face-sample thumbnails changed outside Settings (e.g. Quick Person Search)."""
        dlg = getattr(self, "settings_dialog", None)
        if dlg is not None and hasattr(dlg, "refresh_faces_from_disk_if_ready"):
            dlg.refresh_faces_from_disk_if_ready()

    def refresh_open_imagegen_lora_combos(self) -> None:
        """Update LoRA pulldowns on open Create/Expand/Infill dialogs after catalog edits."""
        from PySide6.QtWidgets import QApplication

        for widget in QApplication.topLevelWidgets():
            refresh = getattr(widget, "refresh_mflux_lora_combo", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass

    def show_settings(self, tab_index=None, focus_widget=None, auto_extract_faces=False):
        """Show settings dialog
        
        Args:
            tab_index: Optional tab index to navigate to (0 = General)
            focus_widget: Optional widget to focus on after showing dialog
            auto_extract_faces: If True, open on Faces tab and trigger Examine current image when ready
        """
        current_theme_id = getattr(get_active_theme(), "theme_id", "dark")
        if (
            self.settings_dialog
            and getattr(self.settings_dialog, "_applied_theme_id", "dark") != current_theme_id
        ):
            self.settings_dialog.close()
            self.settings_dialog.deleteLater()
            self.settings_dialog = None

        if not self.settings_dialog:
            self.settings_dialog = SettingsDialog(self)
            self._wire_settings_dialog_signals()
        else:
            # Reload settings every time dialog is shown to ensure original_settings is up to date
            self.settings_dialog.load_current_settings()
        
        # Refresh match count to use current directory
        if hasattr(self.settings_dialog, 'update_match_count'):
            self.settings_dialog.update_match_count(self.settings_dialog.filter_pattern_input.text())
        
        # Navigate to specified tab if provided, or Faces tab when auto_extract_faces
        if auto_extract_faces:
            dlg = self.settings_dialog
            faces_idx = dlg.tab_widget.indexOf(dlg.faces_tab)
            if faces_idx >= 0:
                dlg.request_extract_faces_when_faces_ready()
                # Already on Faces: setCurrentIndex no-ops so on_tab_changed won't schedule examine.
                prev_tab_index = dlg.tab_widget.currentIndex()
                dlg.tab_widget.setCurrentIndex(faces_idx)
                # Only schedule if on_tab_changed did not already consume _auto_extract_faces
                # (setCurrentIndex can still emit currentChanged on some platforms when index unchanged).
                if (
                    prev_tab_index == faces_idx
                    and getattr(dlg, '_faces_tab_setup_done', False)
                    and getattr(dlg, '_auto_extract_faces', False)
                ):
                    dlg._auto_extract_faces = False
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(0, dlg._faces_examine_current_image)
        elif tab_index is not None:
            self.settings_dialog.tab_widget.setCurrentIndex(tab_index)
        
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()
        
        # Focus on specified widget if provided
        if focus_widget:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: focus_widget.setFocus())

    def show_about(self):
        """Show about dialog with build information"""
        if not hasattr(self, 'about_dialog'):
            self.about_dialog = AboutDialog(self)
        self.about_dialog.show()
        self.about_dialog.raise_()
        self.about_dialog.activateWindow()

    def show_why_written(self):
        """Show 'Why was this written?' dialog with HTML-formatted content"""
        if not hasattr(self, 'why_written_dialog'):
            self.why_written_dialog = WhyWasThisWrittenDialog(self)
        self.why_written_dialog.show()
        self.why_written_dialog.raise_()
        self.why_written_dialog.activateWindow()

    def show_api_help(self):
        """Show API documentation dialog with HTML-formatted content"""
        if not hasattr(self, 'api_documentation_dialog'):
            self.api_documentation_dialog = APIDocumentationDialog(self)
        self.api_documentation_dialog.show()
        self.api_documentation_dialog.raise_()
        self.api_documentation_dialog.activateWindow()

    def show_command_line_help(self):
        """Show command line help dialog with HTML-formatted content"""
        if not hasattr(self, 'command_line_help_dialog'):
            self.command_line_help_dialog = CommandLineHelpDialog(self)
        self.command_line_help_dialog.show()
        self.command_line_help_dialog.raise_()
        self.command_line_help_dialog.activateWindow()

    def show_pf_help(self):
        """Show PF (function) key usage dialog."""
        if not hasattr(self, 'pf_keys_help_dialog'):
            self.pf_keys_help_dialog = PFKeysHelpDialog(self)
        self.pf_keys_help_dialog.show()
        self.pf_keys_help_dialog.raise_()
        self.pf_keys_help_dialog.activateWindow()

    def show_downloading_models_help(self):
        """Show help for downloading AI image-generation models."""
        if not hasattr(self, "downloading_models_help_dialog"):
            self.downloading_models_help_dialog = DownloadingAIModelsHelpDialog(self)
        self.downloading_models_help_dialog.show()
        self.downloading_models_help_dialog.raise_()
        self.downloading_models_help_dialog.activateWindow()

    def on_settings_changed(self, new_settings):
        """Handle settings changes"""
        if hasattr(self, 'event_bus') and self.event_bus:
            from event_bus import SETTINGS_CHANGED
            self.event_bus.emit(SETTINGS_CHANGED, dict(new_settings))
        # Check if we need to refresh thumbnails (only for limit/filter changes)
        limit_or_filter_changed = new_settings.pop('_limit_or_filter_changed', False)

        if (
            'ui_theme' in new_settings
            or 'user_theme_colors' in new_settings
            or 'dark_theme_colors' in new_settings
            or 'light_theme_colors' in new_settings
        ):
            from theme_service import apply_theme

            tid = new_settings.get('ui_theme', 'dark')
            apply_theme(
                tid,
                app=QApplication.instance(),
                main_window=self,
                persist=False,
                config=self.config,
            )
            if getattr(self, 'theme_dark_action', None):
                from theme_service import sync_view_theme_menu_actions

                sync_view_theme_menu_actions(self, tid)

        if 'debug_mode' in new_settings:
            self.debug_mode = new_settings['debug_mode']
            if self.debug_mode:
                set_popup_callback(self.show_key_popup)
            else:
                set_popup_callback(None)
            # Notify background worker about debug mode change
            if getattr(self, 'background_clip_controller', None):
                self.background_clip_controller.update_debug_mode()
        
        if 'confirm_delete' in new_settings:
            self.confirm_delete = new_settings['confirm_delete']
        
        if 'browse_view_actual_size' in new_settings:
            self.is_actual_size = new_settings['browse_view_actual_size']
        
        if 'browse_image_history_save_after_ms' in new_settings:
            try:
                self.browse_image_history_save_after_ms = max(
                    0, min(5000, int(new_settings['browse_image_history_save_after_ms']))
                )
            except (TypeError, ValueError):
                pass
        
        if 'wrap_around' in new_settings:
            self.wrap_around = new_settings['wrap_around']
        
        if 'drag_drop_auto_date_change' in new_settings:
            self.drag_drop_auto_date_change = new_settings['drag_drop_auto_date_change']
        
        if 'allow_thumbnail_locking' in new_settings:
            self.allow_thumbnail_locking = new_settings['allow_thumbnail_locking']
            # Update menu visibility/enabled state when setting changes
            if getattr(self, 'menu_manager', None):
                self.menu_manager.update_tools_menu_states()
        
        if 'allow_quick_mass_rename' in new_settings:
            self.allow_quick_mass_rename = new_settings['allow_quick_mass_rename']
            # Update menu enabled state when setting changes
            if getattr(self, 'menu_manager', None):
                self.menu_manager.update_tools_menu_states()
        
        if 'show_extensions' in new_settings:
            self.show_extensions = new_settings['show_extensions']
            # Recalculate grid layout if filenames are visible (row heights may change)
            if getattr(self, 'thumbnail_container', None):
                if hasattr(self.thumbnail_container, 'canvas'):
                    canvas = self.thumbnail_container.canvas
                    if canvas._filename_overlay_visible:
                        canvas.calculate_grid_layout()
                    canvas.update()
        
        if 'thumbnail_filename_visible' in new_settings:
            self.thumbnail_filename_visible = new_settings['thumbnail_filename_visible']
            # Refresh the canvas to show/hide filename overlays
            # set_filename_overlay_visible now handles layout recalculation and scroll position preservation
            if getattr(self, 'thumbnail_container', None):
                self.thumbnail_container.set_filename_overlay_visible(self.thumbnail_filename_visible)
            # Recalculate thumbnail size when overlay changes (row height affects fit)
            if self.current_view_mode == 'thumbnail':
                QTimer.singleShot(50, self.set_dynamic_thumbnail_size)
        
        if 'show_image_size' in new_settings:
            self.show_image_size = new_settings['show_image_size']
            # Refresh the canvas to update overlay display
            # Need to recalculate layout when size display changes (row heights may change)
            if getattr(self, 'thumbnail_container', None):
                if hasattr(self.thumbnail_container, 'canvas'):
                    canvas = self.thumbnail_container.canvas
                    # Find scroll area to preserve scroll position
                    scroll_area = None
                    if hasattr(canvas, 'scroll_area'):
                        scroll_area = canvas.scroll_area
                    if not scroll_area:
                        scroll_area = canvas.parent()
                        while scroll_area and not hasattr(scroll_area, 'verticalScrollBar'):
                            scroll_area = scroll_area.parent()
                    if not scroll_area and hasattr(canvas, 'parent') and callable(canvas.parent):
                        container = canvas.parent()
                        if hasattr(container, 'scroll_area'):
                            scroll_area = container.scroll_area
                    
                    # Save the top visible thumbnail index and its position relative to viewport
                    top_thumbnail_index = None
                    top_thumbnail_offset = 0
                    if scroll_area and hasattr(scroll_area, 'verticalScrollBar') and canvas.thumbnails:
                        scroll_bar = scroll_area.verticalScrollBar()
                        viewport = scroll_area.viewport()
                        viewport_top = scroll_bar.value()
                        
                        # Find the topmost visible thumbnail (using current overlay height)
                        from PySide6.QtCore import QMutexLocker
                        with QMutexLocker(canvas.mutex):
                            for thumbnail in canvas.thumbnails:
                                if thumbnail.rect:
                                    thumb_top = thumbnail.rect.y()
                                    thumb_bottom = thumbnail.rect.y() + thumbnail.rect.height()
                                    # Calculate overlay height for this specific thumbnail
                                    overlay_height = canvas._get_overlay_height_for_thumbnail(thumbnail, thumbnail.rect.width())
                                    thumb_bottom += overlay_height
                                    
                                    # Check if thumbnail is visible in viewport
                                    if thumb_bottom >= viewport_top and thumb_top <= viewport_top + viewport.height():
                                        top_thumbnail_index = thumbnail.index
                                        top_thumbnail_offset = thumb_top - viewport_top
                                        break
                    
                    # Recalculate grid layout (with NEW overlay height - row-by-row)
                    canvas.calculate_grid_layout()
                    
                    # Restore scroll position to keep top thumbnail in same visual position
                    if scroll_area and hasattr(scroll_area, 'verticalScrollBar') and top_thumbnail_index is not None:
                        scroll_bar = scroll_area.verticalScrollBar()
                        with QMutexLocker(canvas.mutex):
                            if 0 <= top_thumbnail_index < len(canvas.thumbnails):
                                thumbnail = canvas.thumbnails[top_thumbnail_index]
                                if thumbnail.rect:
                                    # Calculate new scroll position to keep thumbnail at same offset from viewport top
                                    new_thumb_top = thumbnail.rect.y()
                                    target_scroll = new_thumb_top - top_thumbnail_offset
                                    max_scroll = scroll_bar.maximum()
                                    target_scroll = max(0, min(target_scroll, max_scroll))
                                    scroll_bar.setValue(int(target_scroll))
                    
                    canvas.update()
                    # Ensure current image stays on screen after overlay layout recalc
                    QTimer.singleShot(50, self.ensure_highlighted_visible)
            # Recalculate thumbnail size when overlay changes (row height affects fit)
            if self.current_view_mode == 'thumbnail':
                QTimer.singleShot(50, self.set_dynamic_thumbnail_size)
            # Update menu text
            self.update_filename_menu_text()
        
        if 'ignore_exif_rotation' in new_settings:
            old_setting = getattr(self, 'ignore_exif_rotation', False)
            self.ignore_exif_rotation = new_settings['ignore_exif_rotation']
            
            # If the setting actually changed, clear caches and invalidate loaded thumbnails
            if old_setting != self.ignore_exif_rotation:
                # Update cache manager's setting immediately to ensure cache keys use new setting
                # This must happen BEFORE clearing caches to prevent race conditions
                if getattr(self, 'cache_manager', None):
                    # Update the cache manager's setting so cache keys use the new value
                    self.cache_manager.update_exif_setting(self.ignore_exif_rotation)
                    
                    # Stop any ongoing thumbnail loading to prevent race conditions
                    if hasattr(self.cache_manager, 'background_loader') and self.cache_manager.background_loader:
                        # Clear the load queue to stop processing pending requests
                        with QMutexLocker(self.cache_manager.background_loader.queue_mutex):
                            self.cache_manager.background_loader.load_queue.clear()
                        # Ensure background loader is running to process new requests
                        if not self.cache_manager.background_loader.isRunning():
                            self.cache_manager.background_loader.start()
                    
                    # Clear all in-memory caches (update_exif_setting already cleared them, but be explicit)
                    with QMutexLocker(self.cache_manager.cache_mutex):
                        self.cache_manager.thumbnail_cache.clear()
                        self.cache_manager.fullimage_cache.clear()
                    
                    # Clear all disk cache entries (old entries with different EXIF setting won't be used anyway)
                    # This frees up disk space and ensures no stale cache entries
                    try:
                        thumbnail_files = self.cache_manager.get_thumbnail_dir_listing(force_refresh=True)
                        for filename in thumbnail_files:
                            if filename.endswith('.jpg'):
                                try:
                                    os.unlink(os.path.join(self.cache_manager.thumbnail_cache_dir, filename))
                                except Exception:
                                    pass
                        self.cache_manager.invalidate_thumbnail_dir_cache()
                    except Exception:
                        pass
                
                # Invalidate thumbnails in canvas to force reload with new EXIF setting
                # This is critical - without this, thumbnails already loaded won't be reloaded
                if getattr(self, 'thumbnail_container', None):
                    if hasattr(self.thumbnail_container, 'canvas'):
                        # Invalidate all thumbnails - clear pixmaps and mark as loading
                        self.thumbnail_container.canvas.invalidate_thumbnails()
                        
                        # Force regenerate thumbnails with new EXIF setting
                        # Use a delay to ensure cache clearing and invalidation complete first
                        def force_thumbnail_reload():
                            if getattr(self, 'displayed_images', None):
                                # Request thumbnails again - they will be regenerated with new EXIF setting
                                # force_refresh=True ensures we don't just reorder, but actually reload
                                # generate_thumbnails will call clear_thumbnails() internally, so don't call it here
                                self.generate_thumbnails(force_refresh=True)
                                
                                # Explicitly request thumbnails to be loaded for all displayed images
                                # This ensures they're reloaded with the new EXIF setting
                                # Use a small delay to ensure generate_thumbnails has created the thumbnail entries
                                def request_thumbnails():
                                    if getattr(self, 'cache_manager', None):
                                        # Ensure background loader is running
                                        if not self.cache_manager.background_loader.isRunning():
                                            self.cache_manager.background_loader.start()
                                        
                                        for image_path in self.displayed_images:
                                            # Request thumbnail with high priority to force reload
                                            # The cache key will automatically use the new EXIF setting
                                            self.cache_manager.get_thumbnail_async(
                                                image_path,
                                                self.current_thumbnail_size,
                                                priority=10  # High priority
                                            )
                                QTimer.singleShot(50, request_thumbnails)  # Small delay to ensure thumbnails are created
                        QTimer.singleShot(200, force_thumbnail_reload)  # Delay to ensure cache is cleared
            
            # Refresh thumbnails and current image display when EXIF setting changes
            # This will trigger regeneration with new cache keys that include the current EXIF setting
            if getattr(self, 'thumbnail_container', None):
                if hasattr(self.thumbnail_container, 'canvas'):
                    # Refresh thumbnails - they will be regenerated with new cache keys
                    if old_setting == self.ignore_exif_rotation:
                        # Only do directory refresh if setting didn't change (already handled above)
                        QTimer.singleShot(100, lambda: self.refresh_directory_intelligently() if hasattr(self, 'refresh_directory_intelligently') else self.refresh_directory())
            # Refresh current image if in browse or preview
            if self.current_view_mode == 'browse' and self.current_image_path:
                QTimer.singleShot(100, self.update_image_display)
            if getattr(self, 'preview_widget', None) and self.preview_widget.is_visible():
                QTimer.singleShot(100, self.preview_widget.update_preview)
        
        if 'filtered_tree' in new_settings:
            filtered_tree_setting = new_settings['filtered_tree']
            # Convert boolean to string for backward compatibility
            if isinstance(filtered_tree_setting, bool):
                self.filtered_tree = 'use_filter' if filtered_tree_setting else 'images'
            else:
                self.filtered_tree = filtered_tree_setting
            # Apply filtered_tree setting to file tree
            if hasattr(self, 'file_tree_handler'):
                if self.file_tree_handler.is_tree_initialized():
                    self.file_tree_handler.apply_filtered_tree(self.filtered_tree)
        
        if 'image_extensions' in new_settings:
            # Clear the cache for get_image_extensions() when extensions change
            clear_image_extensions_cache()
            # Invalidate find command cache in file tree handler when extensions change
            if hasattr(self, 'file_tree_handler'):
                if hasattr(self.file_tree_handler, '_find_cmd_base'):
                    delattr(self.file_tree_handler, '_find_cmd_base')
                # Refresh file tree to reflect new extensions
                if self.file_tree_handler.is_tree_initialized():
                    if hasattr(self.file_tree_handler, 'filter_proxy') and self.file_tree_handler.filter_proxy:
                        self.file_tree_handler.filter_proxy.invalidateFilter()
                        self.file_tree_handler.filter_proxy.layoutChanged.emit()
            # Refresh current directory to show/hide files based on new extensions
            if hasattr(self, 'refresh_directory_intelligently'):
                QTimer.singleShot(100, self.refresh_directory_intelligently)
            elif hasattr(self, 'efficient_directory_refresh'):
                QTimer.singleShot(100, self.efficient_directory_refresh)
            elif hasattr(self, 'refresh_directory'):
                QTimer.singleShot(100, self.refresh_directory)
        
        if 'search_depth' in new_settings:
            # Clear cache and invalidate filter when search depth changes
            # This ensures directories are re-evaluated with the new depth
            if hasattr(self, 'file_tree_handler'):
                if self.file_tree_handler.is_tree_initialized():
                    if hasattr(self.file_tree_handler, 'filter_proxy') and self.file_tree_handler.filter_proxy:
                        # Clear the cache so directories are re-evaluated with new depth
                        self.file_tree_handler.filter_proxy.has_images_cache.clear()
                        # Invalidate filter to rebuild tree with new depth
                        self.file_tree_handler.filter_proxy.invalidateFilter()
                        self.file_tree_handler.filter_proxy.layoutChanged.emit()
        
        if 'similarity_metric' in new_settings:
            # Update similarity metric config (sorter will be recreated lazily on next use)
            similarity_metric = new_settings.get('similarity_metric', self.config.load_settings().get('similarity_metric', 'cosine'))
            # Ensure we're not using CLIP (shouldn't be possible, but be safe)
            if similarity_metric == 'clip':
                similarity_metric = 'cosine'
            # Update stored config for lazy initialization
            self._similarity_metric = similarity_metric
            # If sorter already exists, recreate it with new metric
            if self.cnn_image_similarity_sorter is not None:
                # Lazy import CNN modules
                CNNImageSimilaritySorter, _ = _import_cnn_modules()
                cache_dir = self.config.image_recognition_cache_dir
                settings = self.config.load_settings()
                clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
                resnet_model = settings.get('resnet_model', 'resnet18')
                self.cnn_image_similarity_sorter = CNNImageSimilaritySorter(
                    similarity_metric=similarity_metric,
                    cache_dir=cache_dir,
                    clip_model_name=clip_model_name,
                    resnet_model=resnet_model
                )
            # Search mode: always image for cmd-K (CLIP uses shift-cmd-K)
            self.similarity_search_mode = 'image'
        
        # Handle background CLIP extraction setting changes
        if 'background_clip_enabled' in new_settings:
            background_clip_enabled = new_settings.get('background_clip_enabled', False)
            if hasattr(self, 'background_clip_controller'):
                self.background_clip_controller.set_enabled(background_clip_enabled)
                if background_clip_enabled:
                    if hasattr(self, 'idle_detector'):
                        self.idle_detector.start()
                    if hasattr(self, 'background_cache_importer'):
                        self.background_cache_importer.start()
                else:
                    if hasattr(self, 'idle_detector'):
                        self.idle_detector.stop()
                    if hasattr(self, 'background_cache_importer'):
                        self.background_cache_importer.stop()
                    self.background_clip_controller.stop_process()
        
        # Handle background CLIP extraction setting changes
        if 'background_clip_enabled' in new_settings:
            background_clip_enabled = new_settings.get('background_clip_enabled', False)
            if hasattr(self, 'background_clip_controller'):
                self.background_clip_controller.set_enabled(background_clip_enabled)
                if background_clip_enabled:
                    if hasattr(self, 'idle_detector'):
                        self.idle_detector.start()
                    if hasattr(self, 'background_cache_importer'):
                        self.background_cache_importer.start()
                else:
                    if hasattr(self, 'idle_detector'):
                        self.idle_detector.stop()
                    if hasattr(self, 'background_cache_importer'):
                        self.background_cache_importer.stop()
                    self.background_clip_controller.stop_process()
        
        # Handle CLIP model name changes
        if 'clip_model_name' in new_settings:
            clip_model_name = new_settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
            # If sorter already exists, recreate it with new model name
            if self.cnn_image_similarity_sorter is not None:
                # Lazy import CNN modules
                CNNImageSimilaritySorter, _ = _import_cnn_modules()
                cache_dir = self.config.image_recognition_cache_dir
                settings = self.config.load_settings()
                similarity_metric = settings.get('similarity_metric', 'cosine')
                if similarity_metric == 'clip':
                    similarity_metric = 'cosine'
                resnet_model = settings.get('resnet_model', 'resnet18')
                self.cnn_image_similarity_sorter = CNNImageSimilaritySorter(
                    similarity_metric=similarity_metric,
                    cache_dir=cache_dir,
                    clip_model_name=clip_model_name,
                    resnet_model=resnet_model
                )
        
        # Handle ResNet model name changes
        if 'resnet_model' in new_settings:
            resnet_model = new_settings.get('resnet_model', 'resnet18')
            # If sorter already exists, recreate it with new model name
            if self.cnn_image_similarity_sorter is not None:
                # Lazy import CNN modules
                CNNImageSimilaritySorter, _ = _import_cnn_modules()
                cache_dir = self.config.image_recognition_cache_dir
                settings = self.config.load_settings()
                similarity_metric = settings.get('similarity_metric', 'cosine')
                if similarity_metric == 'clip':
                    similarity_metric = 'cosine'
                clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
                self.cnn_image_similarity_sorter = CNNImageSimilaritySorter(
                    similarity_metric=similarity_metric,
                    cache_dir=cache_dir,
                    clip_model_name=clip_model_name,
                    resnet_model=resnet_model
                )
        
        # Handle CLIP similarity threshold changes
        # Note: Threshold is only used for filtering results, not for feature computation
        # So changing it should NOT invalidate any caches
        
        # Track if any tree-related settings changed
        tree_settings_changed = False
        show_hidden_value = None
        
        if 'root_directories' in new_settings:
            tree_settings_changed = True
        
        if 'show_hidden_directories' in new_settings:
            show_hidden_value = new_settings['show_hidden_directories']
            tree_settings_changed = True
        
        if 'always_show_work' in new_settings:
            tree_settings_changed = True
        
        if 'follow_symlinks' in new_settings:
            follow_symlinks_value = new_settings['follow_symlinks']
            tree_settings_changed = True
            # Invalidate filter immediately when follow_symlinks changes
            if hasattr(self, 'file_tree_handler'):
                if self.file_tree_handler.is_tree_initialized():
                    if hasattr(self.file_tree_handler, 'filter_proxy') and self.file_tree_handler.filter_proxy:
                        # Clear any caches that might affect symlink filtering
                        if hasattr(self.file_tree_handler.filter_proxy, 'has_images_cache'):
                            self.file_tree_handler.filter_proxy.has_images_cache.clear()
                        # Refresh cached follow_symlinks value
                        if hasattr(self.file_tree_handler.filter_proxy, '_refresh_follow_symlinks_cache'):
                            self.file_tree_handler.filter_proxy._refresh_follow_symlinks_cache()
                        self.file_tree_handler.filter_proxy.invalidateFilter()
                        self.file_tree_handler.filter_proxy.layoutChanged.emit()
        
        if 'ignore_directories' in new_settings:
            tree_settings_changed = True
        
        # If any tree settings changed, completely rebuild the tree
        if tree_settings_changed and hasattr(self, 'file_tree_handler'):
            if self.file_tree_handler.is_tree_initialized():
                # Use a timer to ensure the rebuild happens after the dialog closes
                # Pass show_hidden_value directly to avoid reading stale config
                # If show_hidden_value is None (setting wasn't changed), read from config
                def rebuild_tree():
                    if show_hidden_value is None:
                        # Read from config if not explicitly set
                        show_hidden = self.config.get_setting('show_hidden_directories', False)
                    else:
                        show_hidden = show_hidden_value
                    self.file_tree_handler.rebuild_tree(show_hidden=show_hidden)
                QTimer.singleShot(300, rebuild_tree)
        
        if 'space_key_mode' in new_settings:
            self.space_key_mode = new_settings['space_key_mode']
        
        if 'similarity_mode' in new_settings:
            self.similarity_mode = new_settings['similarity_mode']
        
        if 'multimodal_hash' in new_settings:
            self.multimodal_hash = new_settings['multimodal_hash']
        
        # Reload similarity multipliers if any changed
        # Handle max_images setting (limit)
        if 'max_images' in new_settings:
            new_limit = new_settings['max_images']
            if new_limit == 0:  # 0 means unlimited
                new_limit = 99999
            self.limit = new_limit
        
        # Handle filter_pattern setting
        # Track if we stopped the background loader so we can restart it if needed
        background_loader_was_stopped = False
        if 'filter_pattern' in new_settings:
            # Check if filter_pattern actually changed before stopping loader
            old_filter_pattern = getattr(self, 'filter_pattern', None)
            old_filter_pattern = ImageBrowserConfig.normalize_filter_pattern(old_filter_pattern) if old_filter_pattern else ""
            new_filter_pattern = ImageBrowserConfig.normalize_filter_pattern(new_settings['filter_pattern']) if new_settings['filter_pattern'] else ""
            filter_pattern_changed = old_filter_pattern != new_filter_pattern
            
            # Only stop thumbnail generation when filter pattern actually changes
            if filter_pattern_changed and getattr(self, 'cache_manager', None) and hasattr(self.cache_manager, 'background_loader') and self.cache_manager.background_loader:
                self.cache_manager.background_loader.stop()
                background_loader_was_stopped = True
            
            # Normalize filter pattern for storage (remove trailing asterisk)
            self.filter_pattern = ImageBrowserConfig.normalize_filter_pattern(new_settings['filter_pattern'])
            # Update status bar immediately to reflect filter change
            if hasattr(self, 'status_bar_manager'):
                self.status_bar_manager._update_filter_section(self)
            # Apply filter pattern to file tree (same normalized pattern as main window)
            if hasattr(self, 'file_tree_handler'):
                if self.file_tree_handler.is_tree_initialized():
                    self.file_tree_handler.apply_filter_pattern(self.filter_pattern)
        
        # Only refresh if limit or filter actually changed (defer until after settings dialog closes)
        if limit_or_filter_changed and self.current_directory:
            if self.current_view_mode == 'thumbnail':
                def _refresh_after_limit_filter_change():
                    self.refresh_directory(force=True)
                    if getattr(self, 'cache_manager', None) and hasattr(self.cache_manager, 'background_loader') and self.cache_manager.background_loader:
                        self.cache_manager.background_loader.start()
                    self.start_background_thumbnail_loading_if_needed()

                QTimer.singleShot(0, _refresh_after_limit_filter_change)
            elif self.current_view_mode == 'browse':
                # Settings changed in browse mode - mark for refresh when exiting browse
                self._settings_changed_in_browse = True
        else:
            # CRITICAL FIX: If we stopped the background loader due to filter_pattern handling,
            # restart it even if limit_or_filter_changed is False
            # This fixes the bug where resetting to defaults stops the loader but doesn't restart it
            if background_loader_was_stopped and getattr(self, 'cache_manager', None) and hasattr(self.cache_manager, 'background_loader') and self.cache_manager.background_loader:
                if not self.cache_manager.background_loader.isRunning():
                    self.cache_manager.background_loader.start()
        
        # Update slideshow managers with new settings
        if getattr(self, 'slideshow_manager', None):
            self.slideshow_manager.update_slideshow_settings(new_settings)
        
        if getattr(self, 'slideshow2_manager', None):
            self.slideshow2_manager.update_slideshow2_settings(new_settings)
        
        if getattr(self, 'slideshow3_manager', None):
            self.slideshow3_manager.update_slideshow3_settings(new_settings)
        
        # Favorites (Ctrl+number / File>Favorites) and move destinations (Move menu / ⌘+number)
        # must reload from disk after the settings dialog closes — see _schedule_post_settings_menu_refresh.
        if (
            'favorite_directories' in new_settings
            or 'move_destinations' in new_settings
            or 'destination_menu_action' in new_settings
            or 'move_keys_mode' in new_settings
        ):
            self._schedule_post_settings_menu_refresh()
        
        # Handle image_editor_app setting - update Tools menu text
        if 'image_editor_app' in new_settings:
            if getattr(self, 'menu_manager', None):
                self.menu_manager.update_tools_menu_states()
        
        # Browse transparency / checkerboard is per ui_theme; refresh viewer when it or theme changes
        if (
            'browse_transparency_settings' in new_settings
            or 'ui_theme' in new_settings
        ):
            if self.current_view_mode == 'browse':
                if getattr(self, 'browse_view_handler', None):
                    self.update_image_display()
        
        if self.status_notification:
            self.status_notification.show_message("Settings updated")

    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard events using the centralized keyboard handler system"""
        log_key_event(event)
        
        # Handle cmd-return and shift-cmd-return for EXIF section collapse/expand
        if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
            modifiers = event.modifiers()
            cmd_pressed = modifiers & (Qt.ControlModifier | Qt.MetaModifier)
            shift_pressed = modifiers & Qt.ShiftModifier
            
            if cmd_pressed:
                # Check if we should handle EXIF section collapse/expand
                # Conditions: not tree view focus, thumbnail view active, EXIF sort mode active
                focused_widget = QApplication.focusWidget()
                tree_has_focus = False
                if getattr(self, 'file_tree_handler', None):
                    if hasattr(self.file_tree_handler, 'file_tree') and self.file_tree_handler.file_tree:
                        tree_has_focus = (focused_widget == self.file_tree_handler.file_tree or 
                                        (hasattr(self.file_tree_handler, 'tree_container') and 
                                         focused_widget == self.file_tree_handler.tree_container))
                
                current_view_mode = getattr(self, 'current_view_mode', 'NOT_SET')
                thumbnail_view_active = (current_view_mode == 'thumbnail')
                
                has_sort_mode = hasattr(self, 'current_sort_mode')
                sort_mode_str = 'NOT_SET'
                if has_sort_mode:
                    try:
                        sort_mode_str = str(self.current_sort_mode)
                    except:
                        sort_mode_str = 'ERROR'
                
                # Check EXIF sort mode - sort_mode_str will be like "SortMode.EXIF_DATE"
                exif_mode_active = (has_sort_mode and 
                                  ('EXIF_DATE' in sort_mode_str or sort_mode_str == 'SortMode.EXIF_DATE' or 'EXIF_YEAR' in sort_mode_str or sort_mode_str == 'SortMode.EXIF_YEAR') and
                                  hasattr(self, 'exif_date_sections') and 
                                  bool(self.exif_date_sections))
                
                if not tree_has_focus and thumbnail_view_active and exif_mode_active:
                    # Handle EXIF section collapse/expand via thumbnail canvas
                    thumbnail_canvas = None
                    if getattr(self, 'thumbnail_container', None):
                        if hasattr(self.thumbnail_container, 'canvas'):
                            thumbnail_canvas = self.thumbnail_container.canvas
                    elif getattr(self, 'canvas_manager', None):
                        if hasattr(self.canvas_manager, 'thumbnail_canvas'):
                            thumbnail_canvas = self.canvas_manager.thumbnail_canvas
                    elif hasattr(self, 'thumbnail_canvas'):
                        thumbnail_canvas = self.thumbnail_canvas
                    
                    if thumbnail_canvas:
                        if shift_pressed:
                            thumbnail_canvas.expand_all_sections()
                            event.accept()
                            return True
                        else:
                            thumbnail_canvas.collapse_all_sections(scroll_to_top=True)
                            event.accept()
                            return True
        
        # Note: cmd-shift-return is handled in event() method before shortcuts are processed
        # This prevents Qt from intercepting it. This is a fallback in case event() didn't catch it.
        if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
            modifiers = event.modifiers()
            cmd_shift = (modifiers & Qt.ShiftModifier) and (modifiers & (Qt.ControlModifier | Qt.MetaModifier))
            if cmd_shift:
                # Handle cmd-shift-return directly: expand file tree
                if getattr(self, 'file_tree_handler', None):
                    self.file_tree_handler.expand_file_tree()
                    event.accept()
                    return True
        
        # Check if help dialog is visible - if so, let it handle keyboard events
        if (getattr(self, 'help_dialog', None) and 
            self.help_dialog.isVisible() and self.help_dialog.dialog):
            # Forward the event to the dialog
            focused_widget = QApplication.focusWidget()
            if focused_widget == self.help_dialog.dialog or focused_widget is None:
                # Let the dialog handle the event
                if hasattr(self.help_dialog.dialog, 'keyPressEvent'):
                    self.help_dialog.dialog.keyPressEvent(event)
                    return True
            # If dialog has focus, don't process here
            if focused_widget and self.help_dialog.dialog.isAncestorOf(focused_widget):
                super().keyPressEvent(event)
                return True
        
        # Check which widget has focus and route events appropriately
        focused_widget = QApplication.focusWidget()
        
        # Tab key - let Qt handle navigation
        if event.key() == Qt.Key_Tab:
            super().keyPressEvent(event)
            return True
        
        # Handle Cmd+Z (Undo) directly to ensure it works before menu is shown
        # This matches how Cmd+C works - Qt processes it even if menu hasn't been shown
        # Trigger undo directly regardless of action enabled state (action disabled state is just for menu display)
        if (event.key() == Qt.Key_Z and 
            (event.modifiers() & Qt.ControlModifier) and
            not (event.modifiers() & Qt.ShiftModifier) and
            not (event.modifiers() & Qt.AltModifier)):
            # Call undo_file_operation directly instead of triggering the action
            # This works even when the action is disabled (disabled state is just for menu display)
            if getattr(self, 'file_operations_manager', None):
                self.undo_file_operation()
                event.accept()
                return True
        
        # Route keyboard events based on which widget has focus
        if focused_widget == self.tree_container:
            # Route keyboard events to the tree view
            if (hasattr(self, 'file_tree_handler') and 
                self.file_tree_handler.is_tree_initialized() and 
                hasattr(self.file_tree_handler, 'file_tree')):
                self.file_tree_handler.file_tree.keyPressEvent(event)
                # Check if the tree view handled the event (event.accepted())
                if event.isAccepted():
                    return True
                # If tree view didn't handle it, continue to keyboard handler manager
        # Handle arrow keys and Enter/Return in list view mode - route to list view handler
        # Check both current_view_mode and stacked_widget index, as current_view_mode might be stale
        stacked_index = self.stacked_widget.currentIndex() if hasattr(self, 'stacked_widget') else None
        is_list_view = (getattr(self, 'current_view_mode', None) == 'list') or (stacked_index == 2)
        
        # Handle list view keyboard events (canvas-based)
        # For list view, allow keyboard_handler_manager to handle ALL keys even when canvas has focus
        # This enables full keyboard functionality in list view similar to thumbnail view
        # CRITICAL: Only consider list view focused if we're actually in list view mode
        # This prevents stale focus from interfering when switching back to thumbnail view
        is_list_view_focused = (is_list_view and 
                               hasattr(self, 'list_view_container') and 
                               self.list_view_container and
                               (focused_widget == self.list_view_container or 
                                focused_widget == self.list_view_container.canvas or
                                focused_widget == self.list_view_container.scroll_area))
        
        # If in list view and list view has focus, allow keyboard_handler_manager to handle ALL keys
        # This ensures Enter, H, E, Space, F, and all other keys work in list view
        if is_list_view and is_list_view_focused:
            if getattr(self, 'keyboard_handler_manager', None):
                if self.keyboard_handler_manager.handle_key_event(event):
                    event.accept()
                    return True
                # If keyboard handler didn't handle the event, ensure it's not accepted
                # so QAction shortcuts can work
                event.setAccepted(False)
        
        # Only process with keyboard_handler_manager if focus is NOT on tree_container, file_tree, or list_view_container
        # (list_view_container is handled above, so we exclude it here)
        if not (
            focused_widget == getattr(self, 'tree_container', None) or
            (hasattr(self, 'file_tree_handler') and 
             self.file_tree_handler.is_tree_initialized() and 
             hasattr(self.file_tree_handler, 'file_tree') and 
             focused_widget == self.file_tree_handler.file_tree) or
            is_list_view_focused
        ):
            if getattr(self, 'keyboard_handler_manager', None):
                if self.keyboard_handler_manager.handle_key_event(event):
                    event.accept()
                    return True
                # If keyboard handler didn't handle the event, ensure it's not accepted
                # so QAction shortcuts can work
                event.setAccepted(False)

        # Fallback to parent implementation if no handler processed the event
        super().keyPressEvent(event)
        return False
    
    def copy_file_path_to_clipboard(self):
        """Always copy the full file path to clipboard (cmd-c behavior)"""
        # Check if tree has focus first - if so, copy from tree instead
        if self._tree_has_focus():
            # Tree has focus - copy from tree selection
            if (getattr(self, 'file_tree_handler', None) and
                hasattr(self.file_tree_handler, 'file_tree') and self.file_tree_handler.file_tree):
                tree = self.file_tree_handler.file_tree
                selection = tree.selectionModel().selectedIndexes()
                if selection:
                    index = selection[0]
                    model = tree.model()
                    if model:
                        source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                        selected_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                        
                        if selected_path and os.path.exists(selected_path):
                            try:
                                display_path = normalize_path_for_display(selected_path)
                                clipboard = QApplication.clipboard()
                                clipboard.setText(display_path)
                                if hasattr(self, 'status_notification'):
                                    self.status_notification.show_message(
                                        f"Copied to clipboard: {os.path.basename(selected_path)}")
                                return
                            except Exception:
                                # If copy fails, continue to fallback
                                pass
        
        # In thumbnail mode, if multiple files are selected, copy their full paths as comma-delimited string
        if getattr(self, 'current_view_mode', None) == 'thumbnail':
            selected_files = self.selection_manager.get_selected_files()
            if len(selected_files) > 1:
                # Multiple files selected: copy full paths as single-quoted, space-delimited string
                copy_data = " ".join(
                    f"[{normalize_path_for_display(f)}]" for f in selected_files
                ).strip()
                clipboard = QApplication.clipboard()
                clipboard.setText(copy_data)
                if self.status_notification:
                    self.status_notification.show_message(f"Copied {len(selected_files)} file paths to clipboard")
                return
        
        # Single file or non-thumbnail mode: always copy full path
        current_image_path = self.get_current_image_path()
        
        if current_image_path:
            copy_data = normalize_path_for_display(current_image_path)
            clipboard = QApplication.clipboard()
            clipboard.setText(copy_data)
            if self.status_notification:
                self.status_notification.show_message(f"Copied to clipboard: {os.path.basename(copy_data)}")
        else:
            self.status_notification.show_message("No file to copy")

    def copy_image_to_clipboard(self):
        """Copy the current image content to clipboard for paste into graphics programs (ctrl-C on macOS)"""
        current_image_path = self.get_current_image_path()
        if not current_image_path or not os.path.isfile(current_image_path):
            if self.status_notification:
                self.status_notification.show_message("No image to copy")
            return
        try:
            from exif_image_loader import load_image_with_exif_correction
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            ignore_exif = settings.get('ignore_exif_rotation', False)
            pixmap = load_image_with_exif_correction(current_image_path, ignore_exif=ignore_exif)
        except ImportError:
            pixmap = QPixmap(current_image_path)
        if pixmap is None or pixmap.isNull():
            if self.status_notification:
                self.status_notification.show_message("Could not load image for clipboard")
            return
        clipboard = QApplication.clipboard()
        clipboard.setPixmap(pixmap)
        if self.status_notification:
            self.status_notification.show_message(f"Copied image to clipboard: {os.path.basename(current_image_path)}")

    def copy_user_comment_to_clipboard(self):
        """Copy the full decoded EXIF UserComment text for the current image to the clipboard."""
        image_path = None
        if self.current_view_mode == 'browse':
            image_path = self.get_current_image_path()
        elif self.current_view_mode == 'thumbnail':
            if hasattr(self, 'selection_manager') and self.selection_manager:
                selected_files = self.selection_manager.get_selected_files()
                if selected_files and len(selected_files) == 1:
                    image_path = selected_files[0]

        if not image_path or not os.path.isfile(image_path):
            QMessageBox.warning(self, "Cannot copy user comment", "No image selected.")
            return

        ext = os.path.splitext(image_path)[1].lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}:
            QMessageBox.warning(
                self,
                "Cannot copy user comment",
                "This image format does not support EXIF user comments.",
            )
            return

        from exif_utils import get_usercomment_from_path, decode_usercomment

        raw_bytes = get_usercomment_from_path(image_path)
        if raw_bytes is None:
            QMessageBox.warning(
                self,
                "Cannot copy user comment",
                "No EXIF user comment was found for this image.",
            )
            return

        text = decode_usercomment(raw_bytes)
        QApplication.clipboard().setText(text)
        if self.status_notification:
            self.status_notification.show_message("User comment copied to clipboard")

    def _compute_next_index(self, current_index: int, axis: str, step_sign: int) -> int:
        """Compute next index for grid navigation."""
        return self.navigation_manager.compute_next_index(current_index, axis, step_sign)

    def _toggle_index(self, idx: int):
        """Toggle selection state of an index."""
        if not (0 <= idx < len(self.displayed_images)):
            return
        file_path = self.displayed_images[idx]
        if file_path in self.selected_files:
            self.selected_files.remove(file_path)
        else:
            self.selected_files.add(file_path)
        
        # multi_select_mode is now automatically derived from selected_files
        
        self._emit_selection_changed()

    def ensure_multi_mode(self):
        """Ensure multi-select mode is active."""
        # multi_select_mode is now a property, so we just need to ensure we have selections
        if not self.selected_files and 0 <= self.highlight_index < self.get_widget_count():
            if 0 <= self.highlight_index < len(self.displayed_images):
                self.selected_files.add(self.displayed_images[self.highlight_index])
        self._emit_selection_changed()

    def toggle_fullscreen(self):
        """Toggle browse mode"""
        self.browse_view_handler.toggle_fullscreen()

    def toggle_maximized(self):
        """Toggle maximized mode"""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def enter_true_fullscreen(self):
        """Enter true fullscreen mode"""
        self.browse_view_handler.enter_true_fullscreen()

    def open_map_for_current_image(self):
        """Open map application with GPS location from current image's EXIF data"""
        from map_manager import open_map_for_image, open_map_for_images
        from config import get_config
        
        # Get map application preference from settings
        config = get_config()
        settings = config.load_settings()
        preferred_app = settings.get('map_application', 'apple_maps')
        
        # Check if there are selected images
        if self.selected_files and len(self.selected_files) > 0:
            # Use all selected images
            image_paths = list(self.selected_files)
            # Try to open map with all selected images
            success, error_code, error_message = open_map_for_images(image_paths, preferred_app)
            
            # If no GPS data found in any images, show message and skip opening map
            if not success and error_code == "NO_GPS_DATA":
                show_styled_warning(
                    self,
                    "No GPS Data",
                    error_message or "No GPS location data found in the selected images."
                )
                return
        else:
            # Get current image path based on view mode
            current_image_path = None
            
            if self.current_view_mode == 'browse':
                # In fullscreen mode, use current_image_path
                if getattr(self, 'current_image_path', None):
                    current_image_path = self.current_image_path
            elif self.current_view_mode == 'thumbnail':
                # In thumbnail mode, use highlighted image
                if (hasattr(self, 'highlight_index') and 
                    self.highlight_index is not None and 
                    0 <= self.highlight_index < len(self.displayed_images)):
                    current_image_path = self.displayed_images[self.highlight_index]
            
            if not current_image_path:
                show_styled_warning(
                    self,
                    "No Image Selected",
                    "Please select an image first."
                )
                return
            
            # Try to open map with single image
            success, error_code, error_message = open_map_for_image(current_image_path, preferred_app)
            
            # If no GPS data found, show message and skip opening map
            if not success and error_code == "NO_GPS_DATA":
                show_styled_warning(
                    self,
                    "No GPS Data",
                    error_message or "No GPS location data found in the image."
                )
                return
        
        if not success:
            show_styled_critical(
                self,
                "Map Error",
                error_message or "Failed to open map application."
            )

    def create_screen_size_copy(self, fit_method: Optional[str] = None):
        """Create a copy of the current image(s) resized to the physical screen size
        
        Supports single or multiple selection. Always shows a confirmation dialog with
        file count, borders on copy, preserve dates, and delete originals checkboxes.
        Checkbox values are persisted across sessions.
        
        Args:
            fit_method: One of 'contain', 'cover', 'width', 'height', or None to use last used.
                - 'contain': Fits within screen bounds, no overflow
                - 'cover': Fills screen, may overflow (default)
                - 'width': Matches screen width exactly
                - 'height': Matches screen height exactly
        """
        from screen_size_copy import create_screen_size_copy as do_create_screen_size_copy, check_image_needs_resize, would_downsize
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton, QProgressDialog, QComboBox
        from PySide6.QtCore import Qt

        # Resolve fit_method from last used setting if not specified
        if fit_method is None:
            _settings = self.config.load_settings()
            fit_method = _settings.get('last_used_screen_copy_fit_method', 'cover')

        # Checkable QActions are not mutually exclusive: Qt toggles the clicked item before
        # triggered fires, so the previous mode can stay checked. Sync immediately so exactly
        # one aspect ratio appears selected (including after cancel / early return).
        self.update_screen_copy_menu_checkmarks(fit_method)

        # Get files to process: selected files (if any) or current image
        files_to_process = []
        if getattr(self, 'selected_files', None):
            files_to_process = [f for f in self.selection_manager.get_selected_files() if os.path.exists(f)]
        if not files_to_process:
            image_path = self.get_current_image_path()
            if image_path and os.path.exists(image_path):
                files_to_process = [image_path]

        if not files_to_process:
            show_styled_information(
                self,
                "Create screen size copy",
                "No image selected. Select an image or ensure one is displayed."
            )
            return

        # Show confirmation dialog (same for single and multiple selection)
        settings = self.config.load_settings()
        default_preserve = settings.get('screen_copy_preserve_dates', True)
        default_delete = settings.get('screen_copy_delete_originals', False)
        default_borders = settings.get('screen_copy_borders_on_copy', True)

        # Pre-scan for dialog label (uses saved borders default; recomputed after user confirms)
        files_needing_resize_preview = [
            f for f in files_to_process if check_image_needs_resize(f, fit_method, default_borders)
        ]
        count_preview = len(files_needing_resize_preview)

        if count_preview == 0:
            show_styled_information(
                self,
                "Create screen size copy",
                f"All {len(files_to_process)} {file_string(len(files_to_process))} already at target size — nothing to do"
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Create screen size copy")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumWidth(360)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        label_text = f"Create screen-sized copies for {count_preview} {file_string(count_preview)}?"
        if count_preview < len(files_to_process):
            label_text += f" ({len(files_to_process) - count_preview} already at target size)"
        label = QLabel(label_text)
        layout.addWidget(label)

        _screen_copy_fit_order = ('contain', 'cover', 'width', 'height')
        _screen_copy_fit_labels = {
            'contain': 'Fit (Contain)',
            'cover': 'Fill (Cover)',
            'width': 'Fit to Width',
            'height': 'Fit to Height',
        }
        fit_mode_row = QHBoxLayout()
        fit_mode_row.addWidget(QLabel("Fit mode:"))
        fit_mode_combo = QComboBox(dialog)
        for _key in _screen_copy_fit_order:
            fit_mode_combo.addItem(_screen_copy_fit_labels[_key], _key)
        try:
            _fit_idx = _screen_copy_fit_order.index(fit_method)
        except ValueError:
            _fit_idx = 1  # cover
        fit_mode_combo.setCurrentIndex(_fit_idx)
        fit_mode_row.addWidget(fit_mode_combo, 1)
        layout.addLayout(fit_mode_row)

        preserve_dates_cb = QCheckBox("Preserve dates (copy original modification date to new files)")
        preserve_dates_cb.setChecked(default_preserve)
        layout.addWidget(preserve_dates_cb)

        delete_cb = QCheckBox("Delete originals after creating copies")
        delete_cb.setChecked(default_delete)
        layout.addWidget(delete_cb)

        borders_cb = QCheckBox("Add borders to pad the image to the screen size")
        borders_cb.setChecked(default_borders)
        borders_cb.setToolTip(
            "Create Screen Size Copy will add borders to pad the image to the screen size "
            "for images with a different aspect ratio than the screen"
        )
        layout.addWidget(borders_cb)

        def refresh_screen_copy_dialog_preview():
            fm = fit_mode_combo.currentData()
            if fm is None:
                fm = fit_method
            b = borders_cb.isChecked()
            prev_list = [f for f in files_to_process if check_image_needs_resize(f, fm, b)]
            cp = len(prev_list)
            lt = f"Create screen-sized copies for {cp} {file_string(cp)}?"
            if cp < len(files_to_process):
                lt += f" ({len(files_to_process) - cp} already at target size)"
            label.setText(lt)

        fit_mode_combo.currentIndexChanged.connect(lambda _i: refresh_screen_copy_dialog_preview())
        borders_cb.toggled.connect(lambda _c: refresh_screen_copy_dialog_preview())
        refresh_screen_copy_dialog_preview()

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        no_btn = QPushButton("No")
        no_btn.setDefault(True)
        no_btn.clicked.connect(dialog.reject)
        yes_btn = QPushButton("Yes")
        yes_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(no_btn)
        button_layout.addWidget(yes_btn)
        layout.addLayout(button_layout)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        fit_method = fit_mode_combo.currentData()
        if fit_method is None:
            fit_method = 'cover'

        delete_originals = delete_cb.isChecked()
        preserve_dates = preserve_dates_cb.isChecked()
        borders_on_copy = borders_cb.isChecked()

        files_needing_resize = [
            f for f in files_to_process if check_image_needs_resize(f, fit_method, borders_on_copy)
        ]

        # Persist dialog choices on Yes (including fit mode for Tools submenu and last-used shortcut)
        settings = self.config.load_settings()
        settings['screen_copy_preserve_dates'] = preserve_dates
        settings['screen_copy_delete_originals'] = delete_originals
        settings['screen_copy_borders_on_copy'] = borders_on_copy
        settings['last_used_screen_copy_fit_method'] = fit_method
        self.config.save_settings(settings)
        self.update_screen_copy_menu_checkmarks(fit_method)

        if not files_needing_resize:
            show_styled_information(
                self,
                "Create screen size copy",
                f"All {len(files_to_process)} {file_string(len(files_to_process))} already at target size — nothing to do"
            )
            return

        # Process files (EXIF is always copied when available)
        from utils import is_inside_photos_library
        _import_appkit_modules()

        total_count = len(files_needing_resize)
        progress = None
        if total_count > 2:
            progress = QProgressDialog("Creating screen-sized copies...", "Cancel", 0, total_count, self)
            progress.setWindowTitle("Create screen size copy")
            progress.setWindowModality(Qt.WindowModality.ApplicationModal)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            QApplication.processEvents()

        error_count = 0
        success_paths = []
        skipped_count = 0
        cancelled = False
        # None = not yet decided; True = proceed for all; False = skip all
        downsize_all_decision = None
        for i, image_path in enumerate(files_needing_resize):
            if progress:
                progress.setValue(i)
                QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True
                    break

            # Skip images that already have the required dimensions
            if not check_image_needs_resize(image_path, fit_method, borders_on_copy):
                skipped_count += 1
                continue

            # Warn before downsizing (reducing resolution)
            ds_check = would_downsize(image_path, fit_method, borders_on_copy)
            if ds_check:
                if downsize_all_decision is False:
                    skipped_count += 1
                    continue
                elif downsize_all_decision is None:
                    # Show per-file confirmation dialog
                    ds_dialog = QDialog(self)
                    ds_dialog.setWindowTitle("Downsize warning")
                    ds_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
                    ds_dialog.setMinimumWidth(420)
                    ds_layout = QVBoxLayout(ds_dialog)
                    ds_layout.setSpacing(12)
                    ds_layout.setContentsMargins(20, 20, 20, 20)

                    # Top row: text on left, thumbnail on right
                    top_row = QHBoxLayout()
                    top_row.setSpacing(14)
                    text_label = QLabel(
                        f"<b>{os.path.basename(image_path)}</b><br><br>"
                        "This image is larger than the screen. Creating a copy will "
                        "<b>reduce</b> its resolution."
                    )
                    text_label.setWordWrap(True)
                    top_row.addWidget(text_label, 1)

                    thumb_label = QLabel()
                    thumb_label.setFixedSize(96, 96)
                    thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    try:
                        from exif_image_loader import load_thumbnail_with_exif_correction
                        ignore_exif = getattr(self, 'ignore_exif_rotation', False)
                        px = load_thumbnail_with_exif_correction(image_path, 96, ignore_exif=ignore_exif)
                        if px and not px.isNull():
                            thumb_label.setPixmap(px)
                    except Exception:
                        pass
                    top_row.addWidget(thumb_label)
                    ds_layout.addLayout(top_row)

                    apply_all_cb = QCheckBox("Apply to all files")
                    apply_all_cb.setChecked(False)
                    ds_layout.addWidget(apply_all_cb)
                    ds_btn_layout = QHBoxLayout()
                    ds_btn_layout.addStretch()
                    skip_btn = QPushButton("Skip")
                    skip_btn.setDefault(True)
                    skip_btn.clicked.connect(ds_dialog.reject)
                    continue_btn = QPushButton("Continue")
                    continue_btn.clicked.connect(ds_dialog.accept)
                    ds_btn_layout.addWidget(skip_btn)
                    ds_btn_layout.addWidget(continue_btn)
                    ds_layout.addLayout(ds_btn_layout)
                    accepted = ds_dialog.exec() == QDialog.DialogCode.Accepted
                    if apply_all_cb.isChecked():
                        downsize_all_decision = True if accepted else False
                    if not accepted:
                        skipped_count += 1
                        continue
                # downsize_all_decision is True → fall through and process

            result_path = do_create_screen_size_copy(
                image_path, fit_method, preserve_dates=preserve_dates, borders_on_copy=borders_on_copy
            )
            if result_path:
                if delete_originals:
                    # Trash original and rename new file to original name
                    can_delete = (
                        os.path.exists(image_path)
                        and os.access(image_path, os.W_OK)
                        and not is_inside_photos_library(image_path)
                        and not (getattr(self, 'lock_manager', None)
                                 and self.lock_manager.is_file_locked(image_path))
                    )
                    if can_delete:
                        try:
                            if _NSWorkspace and _NSWorkspaceRecycleOperation:
                                workspace = _NSWorkspace.sharedWorkspace()
                                workspace.performFileOperation_source_destination_files_tag_(
                                    _NSWorkspaceRecycleOperation,
                                    os.path.dirname(image_path), "", [os.path.basename(image_path)], None
                                )
                                if not os.path.exists(image_path):
                                    os.rename(result_path, image_path)
                                    result_path = image_path
                                    self.remove_thumbnails_for_files([image_path], None)
                        except Exception as e:
                            print(f"Error replacing original with screen-size copy: {e}")
                            error_count += 1
                success_paths.append((image_path, result_path))
            else:
                error_count += 1

        if progress:
            progress.setValue(total_count)

        # Invalidate metadata cache for all processed files (originals + new) so status bar shows correct dimensions
        paths_to_clear = set()
        for orig, result in success_paths:
            paths_to_clear.add(orig)
            if result != orig:
                paths_to_clear.add(result)
        for p in paths_to_clear:
            if getattr(self, 'cache_manager', None):
                self.cache_manager.clear_cache_for_file(p)
            if getattr(self, 'thumbnail_container', None) and getattr(self.thumbnail_container, 'canvas', None):
                self.thumbnail_container.canvas.invalidate_thumbnails_for_paths([p])

        # Refresh directory view if we created files in current directory
        if success_paths and getattr(self, 'current_directory', None):
            first_orig = success_paths[0][0]
            if os.path.dirname(first_orig) == self.current_directory and self.current_view_mode == 'thumbnail':
                self.load_directory(self.current_directory, external_load=True)

        # Show result only if errors occurred
        fit_name = {'contain': 'Fit', 'cover': 'Fill', 'width': 'Fit to Width', 'height': 'Fit to Height'}.get(fit_method, 'Screen Size')
        if error_count > 0:
            show_styled_warning(
                self,
                "Create screen size copy",
                f"{error_count} error(s) occurred while creating {fit_name} copies."
            )
        elif success_paths and getattr(self, 'status_notification', None):
            parts = []
            if len(success_paths) == 1:
                parts.append(f"Created {fit_name} copy: {os.path.basename(success_paths[0][1])}")
            else:
                parts.append(f"Created {len(success_paths)} {fit_name} copies")
            if skipped_count:
                parts.append(f"{skipped_count} already correct size")
            if cancelled:
                parts.append("cancelled")
            self.status_notification.show_message(", ".join(parts))
        elif skipped_count and not success_paths and getattr(self, 'status_notification', None):
            self.status_notification.show_message(f"{skipped_count} {file_string(skipped_count)} already correct size — nothing to do")
    
    def on_wallpaper_use_zoomed_display_toggled(self, checked: bool):
        """Persist whether wallpaper uses visible browse pixels (zoom/pan) vs original file."""
        settings = self.config.load_settings()
        settings['wallpaper_use_zoomed_display'] = bool(checked)
        self.config.save_settings(settings)

    def sync_wallpaper_zoomed_display_menu_from_settings(self):
        """Apply saved wallpaper_use_zoomed_display to the menu checkbox without firing toggled."""
        if not hasattr(self, 'wallpaper_current_display_action'):
            return
        settings = self.config.load_settings()
        use_zoom = bool(settings.get('wallpaper_use_zoomed_display', False))
        act = self.wallpaper_current_display_action
        act.blockSignals(True)
        try:
            act.setChecked(use_zoom)
        finally:
            act.blockSignals(False)

    def _resolve_wallpaper_source_path_and_transformation(
        self,
    ) -> Tuple[Optional[str], Optional[tuple], Optional[str]]:
        """Return (image_path, transformation_or_None, temp_file_to_delete_or_None).

        When wallpaper_use_zoomed_display is on and we're in browse mode, the pixmap is the
        visible portion (transformations already baked in); transformation is None for the manager.
        Otherwise uses the current file path and per-file transformation.
        """
        settings = self.config.load_settings()
        use_zoom = bool(settings.get('wallpaper_use_zoomed_display', False))
        if (
            use_zoom
            and self.current_view_mode == 'browse'
            and getattr(self, 'browse_view_handler', None)
            and self.current_pixmap
        ):
            rect = self.browse_view_handler.get_visible_source_rect()
            if rect:
                source_pixmap = self.temp_transformed_pixmap
                if source_pixmap is None:
                    source_pixmap = self.apply_transformations_to_pixmap(self.current_pixmap)
                x, y, w, h = rect
                cropped = source_pixmap.copy(x, y, w, h)
                if not cropped.isNull():
                    from prowser_temp_files import prowser_mkstemp_path
                    temp_path = prowser_mkstemp_path(
                        suffix='.png', prefix='prowser_wallpaper_zoom_'
                    )
                    if cropped.save(temp_path, 'PNG'):
                        return (temp_path, None, temp_path)
                    try:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    except Exception:
                        pass
        current_image_path = None
        if self.current_view_mode == 'browse' and getattr(self, 'current_image_path', None):
            current_image_path = self.current_image_path
        elif self.displayed_images and 0 <= self.highlight_index < len(self.displayed_images):
            current_image_path = self.displayed_images[self.highlight_index]
        transformation = None
        if current_image_path and hasattr(self, 'image_transformations') and current_image_path in self.image_transformations:
            transformation = self.image_transformations[current_image_path]
        return (current_image_path, transformation, None)

    def set_current_image_as_desktop_background(self, fit_method: Optional[str] = None):
        """Set the current image as the desktop background
        
        Args:
            fit_method: Optional fit method ('contain', 'cover', 'width', 'height').
                       If None, uses the last used fit method from settings (default: 'contain')
        """
        if not getattr(self, 'wallpaper_manager', None):
            return
        # INSERT_YOUR_CODE
        # Check if we are in macOS Spaces (true OS fullscreen) mode and deny if so
        try:
            from AppKit import NSApplication
            app = NSApplication.sharedApplication()
            # 4 == NSApplicationPresentationFullScreen (macOS Spaces fullscreen)
            # See: https://developer.apple.com/documentation/appkit/nsapplicationpresentationoptions/nsapplicationpresentationfullscreen
            if hasattr(app, 'presentationOptions') and app.presentationOptions() & 4:
                show_styled_warning(self, "Cannot Set Wallpaper", "Cannot set wallpaper while in OS fullscreen mode.")
                return
        except Exception:
            pass
        
        # Get fit method from parameter or settings
        if fit_method is None:
            settings = self.config.load_settings()
            fit_method = settings.get('last_used_wallpaper_fit_method', 'contain')
            if fit_method == 'current_display':
                fit_method = 'cover'
        
        current_image_path, transformation, temp_wallpaper_path = self._resolve_wallpaper_source_path_and_transformation()
        if not current_image_path:
            if self.status_notification:
                self.status_notification.show_error_message("No current image available")
            if temp_wallpaper_path:
                try:
                    if os.path.exists(temp_wallpaper_path):
                        os.remove(temp_wallpaper_path)
                except Exception:
                    pass
            return
        try:
            success = self.wallpaper_manager.set_image_as_desktop_background(
                current_image_path, transformation, fit_method
            )
            if success:
                settings = self.config.load_settings()
                settings['last_used_wallpaper_fit_method'] = fit_method
                self.config.save_settings(settings)
                self.update_wallpaper_menu_checkmarks(fit_method)
                if hasattr(self, 'update_edit_menu_states'):
                    self.update_edit_menu_states()
        except Exception as e:
            self.status_notification.show_error_message(f"Failed to set wallpaper: {str(e)}")
        finally:
            if temp_wallpaper_path:
                try:
                    if os.path.exists(temp_wallpaper_path):
                        os.remove(temp_wallpaper_path)
                except Exception:
                    pass

    def update_wallpaper_menu_checkmarks(self, fit_method: str):
        """Update wallpaper fit-method checkmarks (not the zoomed-source toggle)."""
        if not hasattr(self, 'wallpaper_contain_action'):
            return
        self.wallpaper_contain_action.setChecked(False)
        self.wallpaper_cover_action.setChecked(False)
        self.wallpaper_width_action.setChecked(False)
        self.wallpaper_height_action.setChecked(False)
        if fit_method == 'contain':
            self.wallpaper_contain_action.setChecked(True)
        elif fit_method == 'cover':
            self.wallpaper_cover_action.setChecked(True)
        elif fit_method == 'width':
            self.wallpaper_width_action.setChecked(True)
        elif fit_method == 'height':
            self.wallpaper_height_action.setChecked(True)

    def resize_window_to_screen_aspect_ratio(self):
        """Resize the window so the browse image area matches the active screen's aspect ratio (windowed mode)."""
        MAX_ITERS = 10
        TOLERANCE = 0.002
        if getattr(self, 'image_display_manager', None) and self.current_view_mode != 'browse':
            self.image_display_manager.display_current_image()
            QApplication.processEvents()
        if self.current_view_mode != 'browse':
            show_styled_information(
                self,
                "Browse Mode",
                "Open an image in browse mode first (Space or F), then try again.",
            )
            return
        if not getattr(self, 'current_pixmap', None):
            show_styled_information(self, "No Image", "Load an image first.")
            return
        if not hasattr(self, 'image_container') or not self.image_container:
            return
        if self.isFullScreen():
            self.showNormal()
        QApplication.processEvents()
        for _ in range(4):
            if not is_macos_spaces_fullscreen():
                break
            self.showNormal()
            QApplication.processEvents()
        screen = QGuiApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        sg = screen.geometry()
        R = sg.width() / max(1, sg.height())
        ag = screen.availableGeometry()
        for i in range(MAX_ITERS):
            QApplication.processEvents()
            cw = max(1, self.image_container.width())
            ch = max(1, self.image_container.height())
            ratio = cw / ch
            if abs(ratio - R) < TOLERANCE:
                if getattr(self, 'status_notification', None):
                    self.status_notification.show_message("Image area matches screen aspect ratio")
                return
            area = max(1, cw * ch)
            tw = int(round((area * R) ** 0.5))
            th = int(round(tw / R))
            dw = tw - cw
            dh = th - ch
            if abs(dw) < 1 and abs(dh) < 1:
                break
            new_w = self.width() + dw
            new_h = self.height() + dh
            new_w = max(self.minimumWidth(), min(new_w, ag.width()))
            new_h = max(self.minimumHeight(), min(new_h, ag.height()))
            self.resize(new_w, new_h)
            gx = self.x()
            gy = self.y()
            fw = self.frameGeometry().width()
            fh = self.frameGeometry().height()
            if gx + fw > ag.right():
                gx = ag.right() - fw
            if gy + fh > ag.bottom():
                gy = ag.bottom() - fh
            if gx < ag.left():
                gx = ag.left()
            if gy < ag.top():
                gy = ag.top()
            if gx != self.x() or gy != self.y():
                self.move(gx, gy)
            QApplication.processEvents()
        QApplication.processEvents()
        cw = max(1, self.image_container.width())
        ch = max(1, self.image_container.height())
        if abs(cw / ch - R) < TOLERANCE:
            if getattr(self, 'status_notification', None):
                self.status_notification.show_message("Image area matches screen aspect ratio")
        elif getattr(self, 'status_notification', None):
            self.status_notification.show_message(
                "Resize stopped after adjustments; image area may still differ slightly from screen aspect."
            )
        # Resize can move focus; keep main content focused so browse shortcuts (e.g. A) keep working.
        QTimer.singleShot(0, self.focus_canvas)

    def update_screen_copy_menu_checkmarks(self, fit_method: str):
        """Update screen copy menu checkmarks based on the current fit method"""
        if not hasattr(self, 'create_screen_copy_contain_action'):
            return
        self.create_screen_copy_contain_action.setChecked(False)
        self.create_screen_copy_cover_action.setChecked(False)
        self.create_screen_copy_width_action.setChecked(False)
        self.create_screen_copy_height_action.setChecked(False)
        if fit_method == 'contain':
            self.create_screen_copy_contain_action.setChecked(True)
        elif fit_method == 'cover':
            self.create_screen_copy_cover_action.setChecked(True)
        elif fit_method == 'width':
            self.create_screen_copy_width_action.setChecked(True)
        elif fit_method == 'height':
            self.create_screen_copy_height_action.setChecked(True)

    def rename_with_custom_prefix(self):
        """Rename displayed images with a custom prefix (prompted from user)"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.rename_with_custom_prefix()
    
    def quick_mass_rename(self):
        """Quick mass rename: Select all thumbnails and rename with preset options (no dialog)"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.quick_mass_rename()
    
    def lock_selected_files(self):
        """Lock selected files"""
        if not hasattr(self, 'lock_manager') or not self.lock_manager:
            return
        # Check if locking is allowed
        if not getattr(self, 'allow_thumbnail_locking', False):
            return
        
        # Handle browse mode - lock the current image
        if self.current_view_mode == 'browse':
            if not hasattr(self, 'current_image_path') or not self.current_image_path:
                self.status_notification.show_message("No image to lock")
                return
            
            if not os.path.exists(self.current_image_path):
                self.status_notification.show_message("Image file not found")
                return
            
            success = self.lock_manager.lock_files([self.current_image_path])
            if success:
                self.status_notification.show_message("Locked image")
                # Force repaint to show lock icon
                if getattr(self, 'image_label', None):
                    self.image_label.update()
            else:
                self.status_notification.show_message("Failed to lock image")
            return
        
        # Thumbnail mode - lock selected files
        if getattr(self.main_window, 'specific_files_active', False):
            return
        selected_files = self.selection_manager.get_selected_files()
        if not selected_files:
            self.status_notification.show_message("No files selected")
            return
        
        # Check limit - must be unlimited (99999)
        if getattr(self, 'limit', 99999) and self.limit < 99999:
            # Auto-adjust limit to unlimited
            from PySide6.QtWidgets import QMessageBox

            reply = show_styled_question(
                self,
                "Limit Adjustment Required",
                f"Locking files requires unlimited display (limit=0).\n\n"
                f"Current limit: {self.limit}\n\n"
                f"Would you like to set limit to unlimited and refresh?",
                default_no=False,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.limit = 99999
                if hasattr(self, 'debounce_refresh_directory'):
                    self.debounce_refresh_directory()
                return
            else:
                return
        
        # CRITICAL: Switch to CUSTOM mode to preserve locked files in their current positions
        # This ensures locked files don't move until the user manually changes sort mode
        from sort_mode import SortMode
        was_custom_mode = (self.current_sort_mode == SortMode.CUSTOM)
        if not was_custom_mode:
            # Switch to CUSTOM mode to preserve current order (locked files stay in place)
            self.current_sort_mode = SortMode.CUSTOM
            if hasattr(self, 'save_sorting_settings'):
                self.save_sorting_settings()
        
        success = self.lock_manager.lock_files(selected_files)
        if success:
            count = len(selected_files)
            self.status_notification.show_message(f"Locked {count} {file_string(count)}")
            # CRITICAL: Do NOT refresh directory - that would reorder files!
            # Just force a repaint to show locked files with gray background
            # The thumbnails already have the correct order - just need visual update
            if getattr(self, 'thumbnail_container', None):
                canvas = self.thumbnail_container.canvas
                if canvas:
                    # Force repaint to show locked state (gray background)
                    if hasattr(canvas, 'update'):
                        canvas.update()
                    # Also update selection display
                    if hasattr(self, '_emit_selection_changed'):
                        self._emit_selection_changed()
        else:
            self.status_notification.show_message("Failed to lock files")
    
    def unlock_selected_files(self):
        """Unlock selected files"""
        if not hasattr(self, 'lock_manager') or not self.lock_manager:
            return
        
        # Check if locking is allowed
        if not getattr(self, 'allow_thumbnail_locking', False):
            return
        
        # Handle browse mode - unlock the current image
        if self.current_view_mode == 'browse':
            if not hasattr(self, 'current_image_path') or not self.current_image_path:
                self.status_notification.show_message("No image to unlock")
                return
            
            if not os.path.exists(self.current_image_path):
                self.status_notification.show_message("Image file not found")
                return
            
            success = self.lock_manager.unlock_files([self.current_image_path])
            if success:
                self.status_notification.show_message("Unlocked image")
                # Force repaint to remove lock icon
                if getattr(self, 'image_label', None):
                    self.image_label.update()
            else:
                self.status_notification.show_message("Failed to unlock image")
            return
        
        # Thumbnail mode - unlock selected files
        if getattr(self.main_window, 'specific_files_active', False):
            return
        
        selected_files = self.selection_manager.get_selected_files()
        if not selected_files:
            self.status_notification.show_message("No files selected")
            return
        
        success = self.lock_manager.unlock_files(selected_files)
        if success:
            count = len(selected_files)
            self.status_notification.show_message(f"Unlocked {count} {file_string(count)}")
            # CRITICAL: Do NOT refresh directory - that would reorder files!
            # Just force a repaint to remove locked visual state (gray background)
            # The thumbnails already have the correct order - just need visual update
            if getattr(self, 'thumbnail_container', None):
                canvas = self.thumbnail_container.canvas
                if canvas:
                    # Force repaint to remove locked state (gray background)
                    if hasattr(canvas, 'update'):
                        canvas.update()
                    # Also update selection display
                    if hasattr(self, '_emit_selection_changed'):
                        self._emit_selection_changed()
        else:
            self.status_notification.show_message("Failed to unlock files")
    
    def reset_date_to_exif(self):
        """Reset modification dates of selected images to match their EXIF data"""
        # Check if we're in thumbnail mode and not in specific files mode
        if self.current_view_mode != 'thumbnail':
            self.status_notification.show_message("This feature is only available in thumbnail mode")
            return
        
        if getattr(self, 'specific_files_active', False):
            self.status_notification.show_message("This feature is not available in specific files mode")
            return
        
        # Get selected files
        selected_files = self.selection_manager.get_selected_files()
        if not selected_files:
            self.status_notification.show_message("No files selected")
            return
        
        # First confirmation dialog (default Cancel)
        # reply = QMessageBox.question(
        #     self,
        #     "Reset Date to EXIF",
        #     f"Scan {len(selected_files)} selected {file_string(len(selected_files))} for EXIF date data?\n\n"
        #     f"This will identify files that need their modification dates reset.",
        #     QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        #     QMessageBox.StandardButton.Cancel
        # )
        
        # if reply != QMessageBox.StandardButton.Ok:
        #     return
        
        # Scan selected images for EXIF data
        files_to_change = []
        for file_path in selected_files:
            if not os.path.exists(file_path):
                continue
            
            try:
                # Get current modification time
                current_mtime = os.path.getmtime(file_path)
                
                # Get EXIF date/time
                result = get_image_dimensions_and_exif_date(file_path)
                if result:
                    _, exif_timestamp = result
                    if exif_timestamp is not None:
                        # Check if dates already match (within 1 second tolerance)
                        if abs(current_mtime - exif_timestamp) > 1:
                            files_to_change.append((file_path, current_mtime, exif_timestamp))
            except Exception:
                # Skip files that can't be processed
                continue
        
        if not files_to_change:
            show_styled_information(self, "Reset Date to EXIF", "No files need date changes (all match EXIF or have no EXIF data)")
            return
        
        # Show confirmation dialog with list of files
        if not ResetDateDialog.show_confirmation(files_to_change, self):
            return
        
        # Reset dates
        success_count = 0
        error_count = 0
        
        for file_path, current_mtime, exif_timestamp in files_to_change:
            try:
                # Set both atime and mtime to the EXIF timestamp
                os.utime(file_path, (exif_timestamp, exif_timestamp))
                
                # Verify the date was set correctly
                actual_mtime = os.path.getmtime(file_path)
                if abs(actual_mtime - exif_timestamp) > 1:
                    # Date wasn't set correctly - try again
                    os.utime(file_path, (exif_timestamp, exif_timestamp))
                    actual_mtime = os.path.getmtime(file_path)
                    if abs(actual_mtime - exif_timestamp) > 1:
                        error_count += 1
                        continue
                
                success_count += 1
            except Exception:
                error_count += 1
                continue
        
        # Show result message
        if success_count > 0:
            if error_count > 0:
                self.status_notification.show_message(
                    f"Reset dates for {success_count} {file_string(success_count)}, {error_count} error(s)"
                )
            else:
                self.status_notification.show_message(
                    f"Successfully reset dates for {success_count} {file_string(success_count)}"
                )
            
            # Refresh directory to update displayed dates
            if hasattr(self, 'debounce_refresh_directory'):
                self.debounce_refresh_directory()
            
            # Update Information sidebar if visible and showing current image
            if getattr(self, 'right_sidebar', None) and getattr(self, 'right_sidebar_visible', None):
                if getattr(self, 'current_image_path', None):
                    # Check if current image was one of the files that was modified
                    if any(self.current_image_path == file_path for file_path, _, _ in files_to_change):
                        self.right_sidebar.show_image_info_overlay()
        else:
            self.status_notification.show_message(f"Failed to reset dates for {error_count} {file_string(error_count)}")

    def reset_exif_to_file_date(self):
        """Reset EXIF date/time of selected images to match their file modification dates"""
        # Check if we're in thumbnail mode and not in specific files mode
        if self.current_view_mode != 'thumbnail':
            self.status_notification.show_message("This feature is only available in thumbnail mode")
            return
        
        if getattr(self, 'specific_files_active', False):
            self.status_notification.show_message("This feature is not available in specific files mode")
            return
        
        # Get selected files
        selected_files = self.selection_manager.get_selected_files()
        if not selected_files:
            self.status_notification.show_message("No files selected")
            return
        
        # Scan selected images to check which ones can be updated and which already have EXIF date/time
        files_to_update = []
        files_with_existing_exif = 0
        
        for file_path in selected_files:
            if not os.path.exists(file_path):
                continue
            
            try:
                # Get file modification time
                file_mtime = os.path.getmtime(file_path)
                
                # Check if file has existing EXIF date/time
                result = get_image_dimensions_and_exif_date(file_path)
                old_exif_timestamp = None
                if result:
                    _, exif_timestamp = result
                    if exif_timestamp is not None:
                        old_exif_timestamp = exif_timestamp
                        
                        # Check if EXIF date already matches file date (within 1 second tolerance)
                        if abs(file_mtime - exif_timestamp) <= 1:
                            # Dates already match, skip this file
                            continue
                        
                        # Only count files that will actually be updated
                        files_with_existing_exif += 1
                
                # Add to list of files to update with old EXIF timestamp (or None)
                files_to_update.append((file_path, file_mtime, old_exif_timestamp))
            except Exception:
                # Skip files that can't be processed
                continue
        
        if not files_to_update:
            show_styled_information(self, "Reset EXIF to File Date", "No files need updating (all EXIF dates already match file dates or have no EXIF data)")
            return
        
        # Show warning dialog with Cancel as default
        if not ResetExifDialog.show_confirmation(files_to_update, files_with_existing_exif, self):
            return
        
        # Update EXIF date/time for each file
        success_count = 0
        error_count = 0
        
        for file_path, file_mtime, old_exif_timestamp in files_to_update:
            temp_path = None
            try:
                # Safety check: Verify file date hasn't changed and EXIF date doesn't already match
                # (file might have been modified between scan and update)
                current_file_mtime = os.path.getmtime(file_path)
                if abs(current_file_mtime - file_mtime) > 1:
                    # File modification time changed, skip this file
                    continue
                
                # Double-check EXIF date doesn't already match (safety check)
                if old_exif_timestamp is not None:
                    if abs(current_file_mtime - old_exif_timestamp) <= 1:
                        # EXIF date already matches file date, skip this file
                        continue
                
                # Convert file modification time to EXIF date format: "YYYY:MM:DD HH:MM:SS"
                file_datetime = datetime.fromtimestamp(current_file_mtime)
                exif_date_str = file_datetime.strftime("%Y:%m:%d %H:%M:%S")
                
                # Determine format from file extension
                file_ext = os.path.splitext(file_path)[1].lower()
                is_webp = file_ext == '.webp'
                is_jpeg = file_ext in ['.jpg', '.jpeg']
                is_tiff = file_ext in ['.tiff', '.tif']
                is_png = file_ext == '.png'
                is_heic = file_ext in ['.heic', '.heif']
                
                # Try using piexif first for JPEG and WebP (formats it supports), fall back to PIL for others
                try:
                    import piexif
                    
                    # piexif only supports JPEG and WebP
                    if is_webp or is_jpeg:
                        # Load existing EXIF data or create new structure
                        img = Image.open(file_path)
                        exif_dict = None
                        try:
                            exif_bytes = get_exif_bytes_from_pil_raw(img)
                            if exif_bytes:
                                exif_dict = piexif.load(exif_bytes)
                            else:
                                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
                        except Exception:
                            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
                        
                        # Set date/time fields
                        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_date_str.encode("utf-8")
                        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = exif_date_str.encode("utf-8")
                        exif_dict["0th"][piexif.ImageIFD.DateTime] = exif_date_str.encode("utf-8")
                        
                        # Convert back to bytes
                        exif_bytes = piexif.dump(exif_dict)
                        
                        # Save to temporary file first
                        temp_path = file_path + ".tmp"
                        
                        if is_webp:
                            # For WebP files, use piexif.insert() which handles WebP metadata correctly
                            # This preserves the WebP structure and avoids corruption
                            piexif.insert(exif_bytes, file_path, temp_path)
                            img.close()
                        else:
                            # For JPEG, use PIL's save method with explicit format
                            img.save(temp_path, 'JPEG', exif=exif_bytes, quality=95)
                            img.close()
                    else:
                        # For formats piexif doesn't support (PNG, TIFF, HEIC), use PIL's method
                        raise ImportError("piexif doesn't support this format")
                    
                except ImportError:
                    # piexif not available or format not supported by piexif, use PIL's method
                    with Image.open(file_path) as img:
                        # Get existing EXIF data
                        exif = img.getexif()
                        if exif is None:
                            # Create new EXIF object
                            exif = {}
                        
                        # Set date/time fields using tag IDs
                        exif[306] = exif_date_str  # DateTime
                        exif[36867] = exif_date_str  # DateTimeOriginal
                        exif[36868] = exif_date_str  # DateTimeDigitized
                        
                        # Save to temporary file first
                        temp_path = file_path + ".tmp"
                        
                        if is_jpeg:
                            img.save(temp_path, 'JPEG', exif=exif, quality=95)
                        elif is_tiff:
                            img.save(temp_path, 'TIFF', exif=exif)
                        elif is_png:
                            # PNG supports EXIF via eXIf chunk (Pillow 6.0+)
                            img.save(temp_path, 'PNG', exif=exif)
                        elif is_webp:
                            # For WebP, explicitly specify format
                            # Note: webpmux support check removed as it causes warnings
                            # PIL will handle it if available
                            try:
                                img.save(temp_path, 'WEBP', exif=exif, quality=95, method=6)
                            except Exception:
                                # Fallback: save without EXIF if webpmux not available
                                img.save(temp_path, 'WEBP', quality=95, method=6)
                        elif is_heic:
                            # HEIC/HEIF requires pillow_heif plugin
                            try:
                                # Check if pillow_heif is registered (it should be at module level)
                                img.save(temp_path, 'HEIC', exif=exif, quality=90)
                            except Exception:
                                # If HEIC save fails, try HEIF format
                                try:
                                    img.save(temp_path, 'HEIF', exif=exif, quality=90)
                                except Exception:
                                    # If both fail, skip EXIF for HEIC
                                    img.save(temp_path, 'HEIC', quality=90)
                        else:
                            # For other formats, try to preserve format if possible
                            # Otherwise fall back to JPEG (but this may lose quality/transparency)
                            try:
                                # Try to detect format from image
                                img_format = img.format
                                if img_format:
                                    img.save(temp_path, img_format, exif=exif)
                                else:
                                    # Unknown format, fall back to JPEG
                                    img.save(temp_path, 'JPEG', exif=exif, quality=95)
                            except Exception:
                                # If format-specific save fails, try JPEG as last resort
                                img.save(temp_path, 'JPEG', exif=exif, quality=95)
                
                # Replace original file with updated version
                os.replace(temp_path, file_path)
                temp_path = None  # Mark as successfully replaced
                
                # Preserve file modification time (it might have changed during save)
                os.utime(file_path, (file_mtime, file_mtime))
                
                success_count += 1
            except Exception:
                error_count += 1
                # Clean up temp file if it exists
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                continue
        
        # Show result message
        if success_count > 0:
            if error_count > 0:
                self.status_notification.show_message(
                    f"Updated EXIF dates for {success_count} {file_string(success_count)}, {error_count} error(s)"
                )
            else:
                self.status_notification.show_message(
                    f"Successfully updated EXIF dates for {success_count} {file_string(success_count)}"
                )
            
            # Refresh directory to update displayed dates
            if hasattr(self, 'debounce_refresh_directory'):
                self.debounce_refresh_directory()
            
            # Update Information sidebar if visible and showing current image
            if getattr(self, 'right_sidebar', None) and getattr(self, 'right_sidebar_visible', None):
                if getattr(self, 'current_image_path', None):
                    # Check if current image was one of the files that was modified
                    if any(self.current_image_path == file_path for file_path, _, _ in files_to_update):
                        self.right_sidebar.show_image_info_overlay()
        else:
            self.status_notification.show_message(f"Failed to update EXIF dates for {error_count} {file_string(error_count)}")

    def delete_exif_date(self):
        """Delete EXIF date/time data from selected images"""
        # Check if we're in thumbnail mode and not in specific files mode
        if self.current_view_mode != 'thumbnail':
            self.status_notification.show_message("This feature is only available in thumbnail mode")
            return
        
        if getattr(self, 'specific_files_active', False):
            self.status_notification.show_message("This feature is not available in specific files mode")
            return
        
        # Get selected files
        selected_files = self.selection_manager.get_selected_files()
        if not selected_files:
            self.status_notification.show_message("No files selected")
            return
        
        # Scan selected images to check which ones have EXIF date/time data
        files_to_delete = []
        
        for file_path in selected_files:
            if not os.path.exists(file_path):
                continue
            
            try:
                # Check if file has existing EXIF date/time
                result = get_image_dimensions_and_exif_date(file_path)
                exif_timestamp = None
                if result:
                    _, exif_timestamp = result
                
                # Only add files that have EXIF date data
                if exif_timestamp is not None:
                    files_to_delete.append((file_path, exif_timestamp))
            except Exception:
                # Skip files that can't be processed
                continue
        
        if not files_to_delete:
            show_styled_information(self, "Delete EXIF Date", "No files have EXIF date/time data to delete")
            return
        
        # Show warning dialog with Cancel as default
        if not DeleteExifDialog.show_confirmation(files_to_delete, self):
            return
        
        # Delete EXIF date/time for each file
        success_count = 0
        error_count = 0
        
        for file_path, exif_timestamp in files_to_delete:
            temp_path = None
            try:
                # Preserve file modification time before processing
                file_mtime = os.path.getmtime(file_path)
                
                # Determine format from file extension
                file_ext = os.path.splitext(file_path)[1].lower()
                is_webp = file_ext == '.webp'
                is_jpeg = file_ext in ['.jpg', '.jpeg']
                is_tiff = file_ext in ['.tiff', '.tif']
                is_png = file_ext == '.png'
                is_heic = file_ext in ['.heic', '.heif']
                
                # Try using piexif first for JPEG and WebP (formats it supports), fall back to PIL for others
                try:
                    import piexif
                    
                    # piexif only supports JPEG and WebP
                    if is_webp or is_jpeg:
                        # Load existing EXIF data
                        img = Image.open(file_path)
                        exif_dict = None
                        try:
                            exif_bytes = get_exif_bytes_from_pil_raw(img)
                            if exif_bytes:
                                exif_dict = piexif.load(exif_bytes)
                            else:
                                # No EXIF data, skip
                                img.close()
                                continue
                        except Exception:
                            # Can't load EXIF, skip
                            img.close()
                            continue
                        
                        # Remove date/time fields
                        if "Exif" in exif_dict:
                            exif_dict["Exif"].pop(piexif.ExifIFD.DateTimeOriginal, None)
                            exif_dict["Exif"].pop(piexif.ExifIFD.DateTimeDigitized, None)
                        if "0th" in exif_dict:
                            exif_dict["0th"].pop(piexif.ImageIFD.DateTime, None)
                        
                        # Check if there's any EXIF data left (other than empty dicts)
                        has_data = False
                        for ifd in ["0th", "Exif", "GPS", "1st"]:
                            if ifd in exif_dict and exif_dict[ifd]:
                                has_data = True
                                break
                        
                        # Save to temporary file first
                        temp_path = file_path + ".tmp"
                        
                        if has_data:
                            # Convert back to bytes if there's still data
                            exif_bytes = piexif.dump(exif_dict)
                            
                            if is_webp:
                                # For WebP files, use piexif.insert() which handles WebP metadata correctly
                                piexif.insert(exif_bytes, file_path, temp_path)
                                img.close()
                            else:
                                # For JPEG, use PIL's save method with explicit format
                                img.save(temp_path, 'JPEG', exif=exif_bytes, quality=95)
                                img.close()
                        else:
                            # No EXIF data left, save without EXIF
                            if is_webp:
                                # For WebP, save without EXIF
                                img.save(temp_path, 'WEBP', quality=95, method=6)
                                img.close()
                            else:
                                # For JPEG, save without EXIF
                                img.save(temp_path, 'JPEG', quality=95)
                                img.close()
                    else:
                        # For formats piexif doesn't support (PNG, TIFF, HEIC), use PIL's method
                        raise ImportError("piexif doesn't support this format")
                    
                except ImportError:
                    # piexif not available or format not supported by piexif, use PIL's method
                    with Image.open(file_path) as img:
                        # Save to temporary file first
                        temp_path = file_path + ".tmp"
                        
                        # Handle PNG files specially - need to properly remove EXIF
                        if is_png:
                            # Ensure image is fully loaded
                            img.load()
                            
                            # Get EXIF data
                            exif_dict = get_exif_dict_from_pil(img)
                            if not exif_dict:
                                # No EXIF data found, skip this file
                                continue
                            
                            # Check if we need to preserve any non-date EXIF fields
                            date_field_ids = {306, 36867, 36868}  # DateTime, DateTimeOriginal, DateTimeDigitized
                            has_non_date_exif = any(tag_id not in date_field_ids for tag_id in exif_dict.keys())
                            
                            # Create a completely fresh image copy to strip all metadata
                            # This is the most reliable way to remove EXIF from PNG
                            # Method: Copy pixel data to a new image - this strips ALL metadata
                            # Convert to a standard mode first to ensure pixel data copy works
                            if img.mode == 'P':
                                # Palette mode - convert to RGBA to preserve transparency
                                if 'transparency' in img.info:
                                    temp_img = img.convert('RGBA')
                                else:
                                    temp_img = img.convert('RGB')
                            else:
                                temp_img = img
                            
                            # Now copy pixel data to completely fresh image
                            img_data = list(temp_img.getdata())
                            new_img = Image.new(temp_img.mode, temp_img.size)
                            new_img.putdata(img_data)
                            
                            # Clean up temp image if we created one
                            if img.mode == 'P' and temp_img != img:
                                temp_img.close()
                            
                            # Get original EXIF bytes if available (for piexif to modify while preserving non-date fields)
                            original_exif_bytes = get_exif_bytes_from_pil_raw(img)
                            
                            # If we need to preserve non-date EXIF fields, modify EXIF bytes
                            if has_non_date_exif and original_exif_bytes:
                                try:
                                    import piexif
                                    # Parse EXIF bytes using piexif (works even for PNG)
                                    exif_dict_bytes = piexif.load(original_exif_bytes)
                                    
                                    # Remove date/time fields from piexif dict structure
                                    if "Exif" in exif_dict_bytes:
                                        exif_dict_bytes["Exif"].pop(piexif.ExifIFD.DateTimeOriginal, None)
                                        exif_dict_bytes["Exif"].pop(piexif.ExifIFD.DateTimeDigitized, None)
                                    if "0th" in exif_dict_bytes:
                                        exif_dict_bytes["0th"].pop(piexif.ImageIFD.DateTime, None)
                                    
                                    # Convert back to bytes
                                    modified_exif_bytes = piexif.dump(exif_dict_bytes)
                                    
                                    # Save with modified EXIF bytes (date fields removed, non-date fields preserved)
                                    new_img.save(temp_path, 'PNG', exif=modified_exif_bytes)
                                except Exception:
                                    # If piexif fails, fall back to saving without EXIF
                                    new_img.save(temp_path, 'PNG')
                            else:
                                # Only date fields in EXIF, or no EXIF bytes found - save without any EXIF
                                new_img.save(temp_path, 'PNG')
                            
                            # Close the new image
                            new_img.close()
                        else:
                            # For non-PNG files, use getexif()
                            exif = img.getexif()
                            if exif is None or len(exif) == 0:
                                # No EXIF data, skip
                                continue
                            
                            # Remove date/time fields using tag IDs
                            exif.pop(306, None)  # DateTime
                            exif.pop(36867, None)  # DateTimeOriginal
                            exif.pop(36868, None)  # DateTimeDigitized
                            
                            # Check if there's any EXIF data left
                            if len(exif) > 0:
                                # Save with remaining EXIF data
                                if is_jpeg:
                                    img.save(temp_path, 'JPEG', exif=exif, quality=95)
                                elif is_tiff:
                                    img.save(temp_path, 'TIFF', exif=exif)
                                elif is_webp:
                                    try:
                                        img.save(temp_path, 'WEBP', exif=exif, quality=95, method=6)
                                    except Exception:
                                        # Fallback: save without EXIF if webpmux not available
                                        img.save(temp_path, 'WEBP', quality=95, method=6)
                                elif is_heic:
                                    # HEIC/HEIF requires pillow_heif plugin
                                    try:
                                        img.save(temp_path, 'HEIC', exif=exif, quality=90)
                                    except Exception:
                                        # If HEIC save fails, try HEIF format
                                        try:
                                            img.save(temp_path, 'HEIF', exif=exif, quality=90)
                                        except Exception:
                                            # If both fail, skip EXIF for HEIC
                                            img.save(temp_path, 'HEIC', quality=90)
                                else:
                                    # For other formats, try to preserve format if possible
                                    try:
                                        img_format = img.format
                                        if img_format:
                                            img.save(temp_path, img_format, exif=exif)
                                        else:
                                            img.save(temp_path, 'JPEG', exif=exif, quality=95)
                                    except Exception:
                                        img.save(temp_path, 'JPEG', exif=exif, quality=95)
                            else:
                                # No EXIF data left, save without EXIF
                                if is_jpeg:
                                    img.save(temp_path, 'JPEG', quality=95)
                                elif is_tiff:
                                    img.save(temp_path, 'TIFF')
                                elif is_webp:
                                    try:
                                        img.save(temp_path, 'WEBP', quality=95, method=6)
                                    except Exception:
                                        img.save(temp_path, 'WEBP', quality=95, method=6)
                                elif is_heic:
                                    try:
                                        img.save(temp_path, 'HEIC', quality=90)
                                    except Exception:
                                        try:
                                            img.save(temp_path, 'HEIF', quality=90)
                                        except Exception:
                                            img.save(temp_path, 'HEIC', quality=90)
                                else:
                                    try:
                                        img_format = img.format
                                        if img_format:
                                            img.save(temp_path, img_format)
                                        else:
                                            img.save(temp_path, 'JPEG', quality=95)
                                    except Exception:
                                        img.save(temp_path, 'JPEG', quality=95)
                
                # Replace original file with updated version
                if temp_path and os.path.exists(temp_path):
                    os.replace(temp_path, file_path)
                    temp_path = None  # Mark as successfully replaced
                    
                    # Restore file modification time (preserved from before processing)
                    os.utime(file_path, (file_mtime, file_mtime))
                else:
                    # No temp file was created - this shouldn't happen
                    raise Exception("No temp file was created during processing")
                
                # Verify that EXIF date fields were actually removed
                verification_failed = False
                diagnostic_info = []
                
                try:
                    # Reopen the saved file and check for EXIF date fields
                    with Image.open(file_path) as verify_img:
                        verify_img.load()
                        
                        # Check for EXIF using both methods
                        verify_exif_dict = None
                        if hasattr(verify_img, '_getexif') and verify_img._getexif():
                            verify_exif_dict = verify_img._getexif()
                        elif hasattr(verify_img, 'getexif'):
                            try:
                                verify_exif_obj = verify_img.getexif()
                                if verify_exif_obj and len(verify_exif_obj) > 0:
                                    verify_exif_dict = {}
                                    for tag_id in verify_exif_obj:
                                        verify_exif_dict[tag_id] = verify_exif_obj[tag_id]
                            except:
                                pass
                        
                        if verify_exif_dict:
                            # Check for date fields
                            date_field_ids = {306: "DateTime", 36867: "DateTimeOriginal", 36868: "DateTimeDigitized"}
                            found_date_fields = []
                            
                            for tag_id, field_name in date_field_ids.items():
                                if tag_id in verify_exif_dict:
                                    found_date_fields.append(f"{field_name} (tag {tag_id}): {verify_exif_dict[tag_id]}")
                            
                            if found_date_fields:
                                verification_failed = True
                                diagnostic_info.append(f"File: {os.path.basename(file_path)}")
                                diagnostic_info.append(f"Path: {file_path}")
                                diagnostic_info.append("")
                                diagnostic_info.append("EXIF date fields still present after deletion:")
                                diagnostic_info.extend(found_date_fields)
                                diagnostic_info.append("")
                                
                                # Add info about what EXIF fields remain
                                remaining_fields = []
                                for tag_id, value in verify_exif_dict.items():
                                    if tag_id not in date_field_ids:
                                        remaining_fields.append(f"Tag {tag_id}: {value}")
                                
                                if remaining_fields:
                                    diagnostic_info.append(f"Other EXIF fields present ({len(remaining_fields)}):")
                                    diagnostic_info.extend(remaining_fields[:10])  # Limit to first 10
                                    if len(remaining_fields) > 10:
                                        diagnostic_info.append(f"... and {len(remaining_fields) - 10} more")
                                
                                # Check img.info for EXIF-related keys
                                exif_info_keys = [k for k in verify_img.info.keys() if 'exif' in k.lower()]
                                if exif_info_keys:
                                    diagnostic_info.append("")
                                    diagnostic_info.append(f"EXIF-related keys in img.info: {', '.join(exif_info_keys)}")
                                
                                # Check if file has EXIF bytes in info
                                if 'exif' in verify_img.info:
                                    exif_bytes_len = len(verify_img.info['exif']) if isinstance(verify_img.info['exif'], bytes) else 'N/A'
                                    diagnostic_info.append(f"EXIF bytes in img.info['exif']: {exif_bytes_len} bytes")
                            
                except Exception as verify_error:
                    # Verification check failed, but file was saved
                    verification_failed = True
                    diagnostic_info.append(f"File: {os.path.basename(file_path)}")
                    diagnostic_info.append(f"Path: {file_path}")
                    diagnostic_info.append("")
                    diagnostic_info.append(f"Verification check failed with error: {str(verify_error)}")
                
                if verification_failed:
                    # Show diagnostic information
                    diagnostic_text = "\n".join(diagnostic_info)
                    show_styled_warning(
                        self,
                        "EXIF Deletion Verification Failed",
                        f"EXIF date deletion verification failed for:\n\n{diagnostic_text}\n\n"
                        f"The file was saved, but EXIF date fields may still be present.\n\n"
                        f"Please check the file manually to confirm.",
                    )
                    error_count += 1
                else:
                    success_count += 1
            except Exception:
                error_count += 1
                # Clean up temp file if it exists
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                continue
        
        # Show result message
        if success_count > 0:
            if error_count > 0:
                self.status_notification.show_message(
                    f"Deleted EXIF dates from {success_count} {file_string(success_count)}, {error_count} error(s)"
                )
            else:
                self.status_notification.show_message(
                    f"Successfully deleted EXIF dates from {success_count} {file_string(success_count)}"
                )
            
            # Refresh directory to update displayed dates
            if hasattr(self, 'debounce_refresh_directory'):
                self.debounce_refresh_directory()
            
            # Update Information sidebar if visible and showing current image
            if getattr(self, 'right_sidebar', None) and getattr(self, 'right_sidebar_visible', None):
                if getattr(self, 'current_image_path', None):
                    # Check if current image was one of the files that was modified
                    if any(self.current_image_path == file_path for file_path, _ in files_to_delete):
                        self.right_sidebar.show_image_info_overlay()
        else:
            self.status_notification.show_message(f"Failed to delete EXIF dates from {error_count} {file_string(error_count)}")

    def edit_exif_usercomment(self):
        """Open a dialog to view and edit the EXIF UserComment for the current image."""
        # Determine the target image path
        image_path = None
        if self.current_view_mode == 'browse':
            image_path = self.get_current_image_path()
        elif self.current_view_mode == 'thumbnail':
            selected_files = self.selection_manager.get_selected_files()
            if selected_files and len(selected_files) == 1:
                image_path = selected_files[0]

        if not image_path or not os.path.exists(image_path):
            self.status_notification.show_message("No image selected")
            return

        ext = os.path.splitext(image_path)[1].lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}:
            self.status_notification.show_message("This image format does not support EXIF user comments")
            return

        from exif_utils import get_usercomment_from_path, decode_usercomment, encode_usercomment, restore_usercomment_to_file
        from edit_exif_usercomment_dialog import EditExifUserCommentDialog

        raw_bytes = get_usercomment_from_path(image_path)
        original_text = decode_usercomment(raw_bytes) if raw_bytes else ""

        dialog = EditExifUserCommentDialog(image_path, original_text, parent=self)
        if dialog.exec() != EditExifUserCommentDialog.DialogCode.Accepted:
            return

        new_text = dialog.get_text()
        if new_text == original_text:
            return

        encoded = encode_usercomment(new_text)
        success = restore_usercomment_to_file(image_path, encoded)
        if success:
            self.status_notification.show_message("EXIF user comment saved")
            # Refresh Information sidebar if open
            if getattr(self, 'right_sidebar', None) and getattr(self, 'right_sidebar_visible', False):
                if getattr(self, 'current_image_path', None) == image_path:
                    self.right_sidebar.show_image_info_overlay()
        else:
            self.status_notification.show_message("Failed to save EXIF user comment")

    def convert_selected_images(self):
        """Convert selected images to a different format"""
        # Check if we're in thumbnail view
        if self.current_view_mode != 'thumbnail':
            self.status_notification.show_message("Convert Selected is only available in thumbnail view")
            return
        
        # Get selected files
        selected_files = self.selection_manager.get_selected_files()
        if not selected_files:
            self.status_notification.show_message("No files selected")
            return
        
        # Import and call the conversion function
        from convert_format import convert_selected_images
        convert_selected_images(self, selected_files)

    def resize_images(self):
        """Edit > Resize: thumbnail (≥1 selection) or browse (current image)."""
        files = []
        if self.current_view_mode == "thumbnail":
            if hasattr(self, "selection_manager") and self.selection_manager:
                files = [f for f in self.selection_manager.get_selected_files() if os.path.exists(f)]
            if not files:
                if getattr(self, "status_notification", None):
                    self.status_notification.show_message("Select at least one image to resize")
                return
        elif self.current_view_mode == "browse":
            cur = self.get_current_image_path() if hasattr(self, "get_current_image_path") else None
            if cur and os.path.exists(cur):
                files = [cur]
            if not files and getattr(self, "status_notification", None):
                self.status_notification.show_message("No image to resize")
                return
        else:
            if getattr(self, "status_notification", None):
                self.status_notification.show_message("Resize is only available in thumbnail or browse view")
            return

        from resize_images import resize_selected_images

        resize_selected_images(self, files)

    def get_physical_screen_size(self):
        """Get the physical screen size for actual size calculations"""
        return self.browse_view_handler.get_physical_screen_size()

    def get_effective_display_size(self):
        """Get the effective display size, accounting for status bar visibility and file tree"""
        return self.browse_view_handler.get_effective_display_size()

    def _resize_browse_view_image_container(self):
        """Resize the image container in fullscreen mode to account for sidebar changes"""
        self.browse_view_handler.resize_browse_view_image_container()

    def get_actual_grid_info(self):
        """Get the actual grid information"""
        if not self.displayed_images:
            return {"columns": 1, "rows": 1}
        
        # For canvas implementation, get grid info from canvas
        if hasattr(self, 'thumbnail_container') and hasattr(self.thumbnail_container, 'get_grid_info'):
            return self.thumbnail_container.get_grid_info()
        
        # Fallback calculation for non-canvas implementation
        # Use main content widget width to account for file tree space
        available_width = self.main_content_widget.width() - 40
        
        if available_width <= 0:
            return {"columns": 1, "rows": 1}
        
        # Use proper spacing constants from ThumbnailContainer
        # Add border space to thumbnail size calculation
        border_space = 4  # Border space for highlighting
        columns = max(1, available_width // (self.current_thumbnail_size + border_space + self.thumbnail_container.HORIZONTAL_SPACING))
        rows = (len(self.displayed_images) + columns - 1) // columns
        
        return {"columns": columns, "rows": rows}

    def calculate_page_scroll_info(self):
        """Calculate page scroll information for thumbnails"""
        if not hasattr(self, 'current_thumbnail_size') or not hasattr(self, 'thumbnail_container'):
            return 1, 100  # Fallback values
        
        # Calculate thumbnail row height based on current thumbnail size and spacing
        thumbnail_height = self.current_thumbnail_size
        # Use the same calculation as _set_container_size_for_grid
        border_space = 4  # Border space for highlighting
        vertical_spacing = getattr(self, 'VERTICAL_SPACING', 9)
        vertical_spacing -= 1
        
        # Row height is thumbnail height plus border space plus vertical spacing
        row_height = thumbnail_height + border_space + vertical_spacing
        
        # Calculate how many rows fit in the viewport
        # Use viewport height but account for the container's top margin
        viewport_height = self.scroll_area.viewport().height()
        # The container has a 10px top margin, so the first row starts 10px down
        # We need to subtract this from the viewport height to get the effective content area
        effective_viewport_height = viewport_height - 10
        rows_per_page = max(1, effective_viewport_height // row_height)
        
        return rows_per_page, row_height

    def connect_scroll_signals(self):
        """Connect scroll area signals to handle scroll-aware thumbnail loading"""
        if not self.scroll_area:
            return

        # Connect vertical scroll bar value changed signal
        v_scroll_bar = self.scroll_area.verticalScrollBar()
        if v_scroll_bar:
            v_scroll_bar.valueChanged.connect(self.on_scroll_changed)

        # Connect horizontal scroll bar value changed signal
        h_scroll_bar = self.scroll_area.horizontalScrollBar()
        if h_scroll_bar:
            h_scroll_bar.valueChanged.connect(self.on_scroll_changed)

    def on_scroll_changed(self):
        """Handle scroll events with debouncing to prioritize visible thumbnails"""
        # Only handle if we're in thumbnail view
        if self.current_view_mode != 'thumbnail':
            return
        
        # Skip scroll-based restarts during initial thumbnail load to prevent recursive loops
        # This is especially important after opening new levels (e.g., similarity search)
        if getattr(self, '_initial_thumbnail_load', False):
            return
        
        # Restart the debounce timer - this will cancel any previous timer
        self._scroll_debounce_timer.stop()
        self._scroll_debounce_timer.start(100)  # 100ms debounce delay

    def _on_scroll_debounced(self):
        """Handle debounced scroll events to prioritize visible thumbnails"""
        # Only handle if we're in thumbnail view
        if self.current_view_mode != 'thumbnail':
            return
        
        # Prevent recursive restarts - if we're already restarting, skip this call
        if self._restarting_thumbnails:
            return

        # Don't cancel the worker - let it finish queuing all items.
        # Just restart thumbnail loading for visible items to prioritize them.
        # The BackgroundImageLoader will process all queued items regardless of priority.
        QTimer.singleShot(200, self._restart_thumbnail_loading_for_visible)

    def _interrupt_thumbnail_loading(self):
        """Interrupt any ongoing thumbnail loading before directory load."""
        # ThumbnailLoadingWorker: cancel and wait for exit (blocking wait, no processEvents)
        if getattr(self, 'thumbnail_worker', None):
            try:
                if self.thumbnail_worker.isRunning():
                    self.thumbnail_worker.cancel()
                    self.thumbnail_worker.wait(2000)
                if hasattr(self, 'thumbnail_worker'):
                    delattr(self, 'thumbnail_worker')
            except Exception:
                try:
                    if hasattr(self, 'thumbnail_worker'):
                        delattr(self, 'thumbnail_worker')
                except Exception:
                    pass

        # Background loader: clear queue (workers filter stale callbacks via directory validation)
        if getattr(self, 'cache_manager', None):
            if hasattr(self.cache_manager, 'background_loader') and self.cache_manager.background_loader:
                background_loader = self.cache_manager.background_loader
                background_loader.should_stop[0] = True
                try:
                    with QMutexLocker(background_loader.queue_mutex):
                        background_loader.load_queue.clear()
                except Exception:
                    pass
                background_loader.should_stop[0] = False

            # Disconnect and reconnect to interrupt pending requests
            try:
                self.cache_manager.thumbnail_ready.disconnect(self.on_thumbnail_ready)
            except (TypeError, RuntimeError):
                # Signal not connected or object already deleted - this is OK
                pass
            self.cache_manager.thumbnail_ready.connect(self.on_thumbnail_ready, Qt.QueuedConnection)

            # Clear lower priority requests from background loader queue
            if hasattr(self.cache_manager, 'background_loader') and self.cache_manager.background_loader:
                self._clear_low_priority_thumbnail_requests()

    def _clear_low_priority_thumbnail_requests(self, min_priority: int = 2):
        """Clear thumbnail requests with priority lower than min_priority from background loader queue"""
        if not hasattr(self.cache_manager, 'background_loader'):
            return

        background_loader = self.cache_manager.background_loader
        if not hasattr(background_loader, 'load_queue') or not hasattr(background_loader, 'queue_mutex'):
            return

        try:
            with QMutexLocker(background_loader.queue_mutex):
                # Keep only high priority requests (visible thumbnails have priority 3)
                background_loader.load_queue = [
                    req for req in background_loader.load_queue
                    if not (len(req) >= 5 and req[0] == 'thumbnail' and req[3] < min_priority)
                ]
        except Exception:
            pass

    def _restart_thumbnail_loading_for_visible(self):
        """Restart thumbnail loading focused on currently visible thumbnails"""
        if self.current_view_mode != 'thumbnail':
            return

        # Canvas approach - use canvas-specific visible detection
        # This method already queues requests via get_thumbnail_async, so we don't need
        # to call _start_throttled_thumbnail_loading which would duplicate the work


        # # Stop any running thumbnail worker/background loader threads before reloading
        # DO NOT REENABLE THIS - IT CAUSES THE THUMBNAIL LOADING TO STOP AND NOT RESTART
        # HOWEVER, this is a start of a fix for the issue of deep recursion (scroll handler, 200ms debounce error, etc)

        # if hasattr(self.cache_manager, "background_loader"):
        #     background_loader = self.cache_manager.background_loader
        #     # Set should_stop flag to True if it exists to signal workers to stop
        #     if hasattr(background_loader, "should_stop") and isinstance(background_loader.should_stop, (list, tuple)) and background_loader.should_stop:
        #         background_loader.should_stop[0] = True
        #     # Also try to stop the thread if 'stop' method exists
        #     if hasattr(background_loader, "stop") and callable(background_loader.stop):
        #         background_loader.stop()
        #     # Wait for worker thread to finish if 'wait' method exists
        #     if hasattr(background_loader, "wait") and callable(background_loader.wait):
        #         background_loader.wait(1000)


        self._restart_canvas_thumbnail_loading_for_visible()
        # Removed duplicate call to _start_throttled_thumbnail_loading - it was causing
        # duplicate requests and multiple worker threads
        return

    def _restart_canvas_thumbnail_loading_for_visible(self):
        """Restart thumbnail loading for canvas approach, prioritizing visible thumbnails"""
        
        # Re-entrancy guard: prevent recursive calls
        if self._restarting_thumbnails:
            return
        
        self._restarting_thumbnails = True
        try:
            canvas = self.thumbnail_container.canvas
            if not hasattr(canvas, 'thumbnails') or not canvas.thumbnails:
                return

            # Get visible thumbnail indices using canvas-specific method
            visible_indices = self._get_canvas_visible_thumbnail_indices()
            
            if not visible_indices:
                # Retry after a short delay if no visible thumbnails found
                QTimer.singleShot(50, self._restart_canvas_thumbnail_loading_for_visible)
                return

            # Priority levels: 0=background, 1=default, 2=near-visible, 3=visible
            visible_priority = 3
            near_visible_priority = 2
            background_priority = 0

            # Collect all requests
            all_requests = []

            # Add visible thumbnails (highest priority)
            for idx in visible_indices:
                if idx < len(canvas.thumbnails):
                    thumbnail = canvas.thumbnails[idx]
                    all_requests.append((thumbnail.image_path, visible_priority, idx))

            # Add near-visible thumbnails (medium priority)
            near_visible_indices = self._get_canvas_near_visible_indices(visible_indices)
            for idx in near_visible_indices:
                if idx < len(canvas.thumbnails):
                    thumbnail = canvas.thumbnails[idx]
                    all_requests.append((thumbnail.image_path, near_visible_priority, idx))

            # Sort requests by priority (descending), then by index (ascending)
            all_requests.sort(key=lambda x: (-x[1], x[2]))

            # Request visible and near-visible thumbnails first (prioritized)
            from thumbnail_constants import THUMBNAIL_QUEUE_BATCH_SIZE
            
            batch_size = THUMBNAIL_QUEUE_BATCH_SIZE
            
            for i, (path, priority, idx) in enumerate(all_requests):
                self.cache_manager.get_thumbnail_async(path, self.current_thumbnail_size, priority=priority)
                # Avoid processEvents - runs inside timer callback; nested loop + singleShot causes GIL deadlock

            # Queue background thumbnails AFTER visible ones are queued
            # This ensures visible thumbs load first, then background loading continues
            # CRITICAL: Limit background thumbnail queuing to prevent overwhelming the async queue
            # Only queue a reasonable batch at a time to avoid performance issues
            background_indices = self._get_canvas_background_indices(visible_indices)
            if background_indices:
                # Limit background thumbnail queuing to prevent performance issues
                # Queue max 200 thumbnails at a time, then queue more in batches
                MAX_BACKGROUND_BATCH = 200
                background_batch = background_indices[:MAX_BACKGROUND_BATCH]
                remaining_indices = background_indices[MAX_BACKGROUND_BATCH:]
                
                # Queue background thumbnails with low priority (0) so they load after visible ones
                # Use a delayed call to ensure visible thumbnails are queued first
                def queue_background_thumbnails_batch(indices_to_queue, remaining):
                    queued_count = 0
                    for idx in indices_to_queue:
                        if idx < len(canvas.thumbnails):
                            thumbnail = canvas.thumbnails[idx]
                            # Only queue if thumbnail doesn't have a pixmap yet
                            if thumbnail.pixmap is None or thumbnail.pixmap.isNull():
                                self.cache_manager.get_thumbnail_async(
                                    thumbnail.image_path, 
                                    self.current_thumbnail_size, 
                                    priority=background_priority
                                )
                                queued_count += 1
                    
                    # If there are more thumbnails to queue, schedule the next batch
                    # Use a longer delay between batches to avoid overwhelming the queue
                    if remaining:
                        next_batch = remaining[:MAX_BACKGROUND_BATCH]
                        next_remaining = remaining[MAX_BACKGROUND_BATCH:]
                        QTimer.singleShot(500, lambda: queue_background_thumbnails_batch(next_batch, next_remaining))
                
                # Queue first batch after a short delay to ensure visible ones are processed first
                QTimer.singleShot(100, lambda: queue_background_thumbnails_batch(background_batch, remaining_indices))
        finally:
            self._restarting_thumbnails = False

    def _get_canvas_visible_thumbnail_indices(self) -> List[int]:
        """Get indices of thumbnails currently visible in the canvas viewport"""
        if not hasattr(self, 'thumbnail_container') or not hasattr(self.thumbnail_container, 'canvas'):
            return []
            
        canvas = self.thumbnail_container.canvas
        if not hasattr(canvas, 'thumbnails') or not canvas.thumbnails:
            return []

        visible_indices = []
        
        # Get the scroll area and viewport
        # Try multiple ways to find the scroll area
        scroll_area = None
        
        # Method 1: Check if thumbnail_container has a scroll_area attribute
        if hasattr(self.thumbnail_container, 'scroll_area'):
            scroll_area = self.thumbnail_container.scroll_area
        # Method 2: Check parent hierarchy
        else:
            scroll_area = self.thumbnail_container.parent()
            while scroll_area and not hasattr(scroll_area, 'verticalScrollBar'):
                scroll_area = scroll_area.parent()
        
        # Method 3: Use the main window's scroll area
        if not scroll_area or not hasattr(scroll_area, 'verticalScrollBar'):
            scroll_area = self.scroll_area
            
        if not scroll_area or not hasattr(scroll_area, 'verticalScrollBar'):
            # Fallback: use the main window's scroll area directly
            if getattr(self, 'scroll_area', None):
                scroll_area = self.scroll_area
            else:
                return []

        scroll_bar = scroll_area.verticalScrollBar()
        viewport = scroll_area.viewport()
        
        # Get current scroll position and viewport bounds
        current_scroll = scroll_bar.value()
        viewport_top = current_scroll
        viewport_bottom = current_scroll + viewport.height()
        
        # Check each thumbnail to see if it's visible
        for i, thumbnail in enumerate(canvas.thumbnails):
            if not thumbnail.rect:
                continue
                
            thumbnail_top = thumbnail.rect.y()
            thumbnail_bottom = thumbnail.rect.y() + thumbnail.rect.height()
            
            # Check if thumbnail intersects with viewport
            if thumbnail_bottom >= viewport_top and thumbnail_top <= viewport_bottom:
                visible_indices.append(i)
        
        return visible_indices

    def _get_canvas_near_visible_indices(self, visible_indices: List[int]) -> List[int]:
        """Get indices of thumbnails near visible ones for canvas approach"""
        if not visible_indices:
            return []
            
        canvas = self.thumbnail_container.canvas
        if not hasattr(canvas, 'thumbnails') or not canvas.thumbnails:
            return []

        near_visible = set()
        columns = canvas.columns
        
        for idx in visible_indices:
            # Add thumbnails in adjacent rows (above and below)
            row = idx // columns
            for offset in [-1, 1]:  # One row above and below
                target_row = row + offset
                if 0 <= target_row < (len(canvas.thumbnails) + columns - 1) // columns:
                    start_idx = target_row * columns
                    end_idx = min(start_idx + columns, len(canvas.thumbnails))
                    for i in range(start_idx, end_idx):
                        if i not in visible_indices:
                            near_visible.add(i)
            
            # Add thumbnails in adjacent columns (left and right)
            col = idx % columns
            for offset in [-1, 1]:  # One column left and right
                target_col = col + offset
                if 0 <= target_col < columns:
                    target_idx = row * columns + target_col
                    if 0 <= target_idx < len(canvas.thumbnails) and target_idx not in visible_indices:
                        near_visible.add(target_idx)
        
        return list(near_visible)

    def _get_canvas_background_indices(self, visible_indices: List[int]) -> List[int]:
        """Get indices of background thumbnails for canvas approach"""
        if not visible_indices:
            return []
            
        canvas = self.thumbnail_container.canvas
        if not hasattr(canvas, 'thumbnails') or not canvas.thumbnails:
            return []

        # Get all indices that are not visible or near-visible
        near_visible = set(self._get_canvas_near_visible_indices(visible_indices))
        visible_set = set(visible_indices)
        
        background = []
        for i in range(len(canvas.thumbnails)):
            if i not in visible_set and i not in near_visible:
                background.append(i)
        
        return background

    def toggle_thumbnail_filename_overlay(self):
        """Cycle through filename/size overlay modes on thumbnails (Cmd+I): None -> Name -> Size -> Both -> None"""
        if self.current_view_mode == 'browse':
            self.toggle_information_display()
            return

        # Determine current state
        current_filename = self.thumbnail_filename_visible
        current_size = self.show_image_size
        
        # Cycle through 4 states:
        # 0: No name, no size
        # 1: Name only
        # 2: Size only
        # 3: Both name and size
        if not current_filename and not current_size:
            # State 0 -> State 1: Name only
            new_filename = True
            new_size = False
        elif current_filename and not current_size:
            # State 1 -> State 2: Size only
            new_filename = False
            new_size = True
        elif not current_filename and current_size:
            # State 2 -> State 3: Both
            new_filename = True
            new_size = True
        else:  # both True
            # State 3 -> State 0: None
            new_filename = False
            new_size = False
        
        # Update settings
        self.thumbnail_filename_visible = new_filename
        self.show_image_size = new_size
        
        # Save settings to config
        self.config.update_setting('thumbnail_filename_visible', new_filename)
        self.config.update_setting('show_image_size', new_size)
        
        # Refresh the canvas to show/hide overlays
        if getattr(self, 'thumbnail_container', None):
            self.thumbnail_container.set_filename_overlay_visible(new_filename)
            # Trigger layout recalculation for image size setting change
            if hasattr(self.thumbnail_container, 'canvas'):
                canvas = self.thumbnail_container.canvas
                # Find scroll area to preserve scroll position
                scroll_area = None
                if hasattr(canvas, 'scroll_area'):
                    scroll_area = canvas.scroll_area
                if not scroll_area:
                    scroll_area = canvas.parent()
                    while scroll_area and not hasattr(scroll_area, 'verticalScrollBar'):
                        scroll_area = scroll_area.parent()
                if not scroll_area and hasattr(canvas, 'parent') and callable(canvas.parent):
                    container = canvas.parent()
                    if hasattr(container, 'scroll_area'):
                        scroll_area = container.scroll_area
                
                # Save the top visible thumbnail index and its position relative to viewport
                top_thumbnail_index = None
                top_thumbnail_offset = 0
                if scroll_area and hasattr(scroll_area, 'verticalScrollBar') and canvas.thumbnails:
                    scroll_bar = scroll_area.verticalScrollBar()
                    viewport = scroll_area.viewport()
                    viewport_top = scroll_bar.value()
                    
                    # Find the topmost visible thumbnail
                    from PySide6.QtCore import QMutexLocker
                    with QMutexLocker(canvas.mutex):
                        for thumbnail in canvas.thumbnails:
                            if thumbnail.rect:
                                thumb_top = thumbnail.rect.y()
                                thumb_bottom = thumbnail.rect.y() + thumbnail.rect.height()
                                # Calculate overlay height for this specific thumbnail
                                overlay_height = canvas._get_overlay_height_for_thumbnail(thumbnail, thumbnail.rect.width())
                                thumb_bottom += overlay_height
                                
                                # Check if thumbnail is visible in viewport
                                if thumb_bottom >= viewport_top and thumb_top <= viewport_top + viewport.height():
                                    top_thumbnail_index = thumbnail.index
                                    top_thumbnail_offset = thumb_top - viewport_top
                                    break
                
                # Recalculate grid layout (with NEW overlay height - row-by-row)
                canvas.calculate_grid_layout()
                
                # Restore scroll position to keep top thumbnail in same visual position
                if scroll_area and hasattr(scroll_area, 'verticalScrollBar') and top_thumbnail_index is not None:
                    scroll_bar = scroll_area.verticalScrollBar()
                    with QMutexLocker(canvas.mutex):
                        if 0 <= top_thumbnail_index < len(canvas.thumbnails):
                            thumbnail = canvas.thumbnails[top_thumbnail_index]
                            if thumbnail.rect:
                                # Calculate new scroll position to keep thumbnail at same offset from viewport top
                                new_thumb_top = thumbnail.rect.y()
                                target_scroll = new_thumb_top - top_thumbnail_offset
                                max_scroll = scroll_bar.maximum()
                                target_scroll = max(0, min(target_scroll, max_scroll))
                                scroll_bar.setValue(int(target_scroll))
                
                canvas.update()
        
        # Recalculate optimal thumbnail size when overlay changes (row height affects fit)
        if self.current_view_mode == 'thumbnail':
            QTimer.singleShot(50, self.set_dynamic_thumbnail_size)
        
        # Update menu text
        self.update_filename_menu_text()
    
    def update_filename_menu_text(self):
        """Update the filename toggle menu text and enabled state"""
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_filename_menu_text()

    def toggle_space_bar_behavior(self):
        """Toggle space bar behavior"""
        if self.space_key_mode == 'exit':
            self.space_key_mode = 'advance'
            if self.status_notification:
                self.status_notification.show_message("Space key mode: Advance to next image")
        else:
            self.space_key_mode = 'exit'
            if self.status_notification:
                self.status_notification.show_message("Space key mode: Exit fullscreen")
        
        # Persist the setting
        try:
            self.config.update_setting('space_key_mode', self.space_key_mode)
        except ImportError:
            # Fallback if config module is not available
            pass

    def reorder_thumbnail_layout(self):
        """Reorder thumbnail layout without recreating widgets"""
        # CRITICAL: Use displayed_images directly (source of truth) instead of get_displayed_images()
        # get_displayed_images() might trigger a refresh that re-applies sort order
        # After drag/drop, we've already updated displayed_images with the new order
        displayed = self.displayed_images if hasattr(self, 'displayed_images') else []
        # DON'T call set_thumbnails() as it clears all loaded pixmaps!
        # Instead, just reorder the existing thumbnails in the canvas
        
        # ALWAYS use displayed_images order - this is the source of truth
        # Even if counts don't match, we should still reorder to match displayed_images
        if displayed:
            self.thumbnail_container.canvas.reorder_thumbnails(displayed, force_recalculate_grid=True)
        else:
            # If no displayed images, clear thumbnails
            self.thumbnail_container.canvas.reorder_thumbnails([], force_recalculate_grid=True)

    def ensure_highlighted_visible(self):
        """Ensure the highlighted thumbnail is visible (scroll into view if needed)"""
        displayed = getattr(self, 'displayed_images', None) or []
        if not displayed or not (0 <= self.highlight_index < len(displayed)):
            return
        if hasattr(self, 'thumbnail_container') and hasattr(self.thumbnail_container, 'scroll_to_highlighted'):
            # Sync canvas highlighted_index from source of truth before scrolling
            if hasattr(self.thumbnail_container, 'set_highlighted_index'):
                self.thumbnail_container.set_highlighted_index(self.highlight_index)
            self.thumbnail_container.scroll_to_highlighted()
            return

    def _calculate_grid_dimensions_for_size(self, thumbnail_size: int, num_images: int) -> tuple:
        """Calculate grid dimensions for a given thumbnail size and number of images"""
        if num_images == 0:
            return 1, 1
        
        # Get effective display size
        display_size = self.get_effective_display_size()
        available_width = display_size.width()
        available_height = display_size.height()
        
        if available_width <= 0 or available_height <= 0:
            return 1, 1
        
        # Account for scrollbar width
        scrollbar_width = self.get_scrollbar_width()
        available_width -= scrollbar_width
        
        # Account for canvas margins
        available_width -= (BASE_MARGIN * 2)
        
        # Calculate cell size
        cell_size = thumbnail_size + BORDER_SPACE + THUMBNAIL_SPACING
        
        # Calculate columns and rows
        columns = max(1, available_width // cell_size)
        rows = max(1, (num_images + columns - 1) // columns)  # Ceiling division
        
        return columns, rows

    def show_key_popup(self, msg: str):
        """Show key popup"""
        self.key_popup_label.setText(msg)
        self.key_popup_label.adjustSize()
        label_size = self.key_popup_label.size()
        # Use effective display size to position relative to main content area
        display_size = self.get_effective_display_size()
        x = display_size.width() - label_size.width() - 24
        y = display_size.height() - label_size.height() - 24
        self.key_popup_label.move(x, y)
        self.key_popup_label.setVisible(True)
        self.key_popup_label.raise_()
        self.key_popup_timer.start(2000)

    def hide_key_popup(self):
        """Hide key popup"""
        self.key_popup_label.setVisible(False)

    def show_image(self, image_path: str, index: int):
        """Show image in fullscreen"""
        if not os.path.exists(image_path):
            self._show_missing_image_placeholder(image_path, index)
            return
        
        try:
            # Try to load from cache first, then fall back to direct loading
            pixmap = None
            
            # Check if we have a cache manager available
            if getattr(self, 'cache_manager', None):
                try:
                    # Try to get from full image cache
                    pixmap = self.cache_manager.load_fullimage_sync(image_path)
                except Exception:
                    pass
            
            # If cache loading failed, try EXIF-corrected loading
            if not pixmap or pixmap.isNull():
                try:
                    ignore_exif = getattr(self, 'ignore_exif_rotation', False)
                    pixmap = load_image_with_exif_correction(image_path, ignore_exif=ignore_exif)
                except ImportError:
                    # Fallback to direct loading if exif_image_loader not available
                    pixmap = QPixmap(image_path)
            
            # If direct loading failed and it's a WebP file, try PIL fallback
            if (pixmap.isNull() and image_path.lower().endswith('.webp')):
                try:
                    
                    # Load with PIL and convert to QPixmap
                    with Image.open(image_path) as img:
                        # Convert to RGB if necessary
                        if img.mode in ('RGBA', 'LA', 'P'):
                            # Create white background for transparent images
                            background = Image.new('RGB', img.size, (255, 255, 255))
                            if img.mode == 'P':
                                img = img.convert('RGBA')
                            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                            img = background
                        elif img.mode != 'RGB':
                            img = img.convert('RGB')
                        
                        # Convert PIL image to QImage then to QPixmap
                        img_data = img.tobytes('raw', img.mode)
                        qimage = QImage(img_data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
                        pixmap = QPixmap.fromImage(qimage)
                        
                except Exception:
                    pass
            
            if pixmap.isNull():
                self._show_missing_image_placeholder(image_path, index)
                return
            
            self.current_pixmap = pixmap
            self.current_image_path = image_path
            self.current_index = index
            self.browse_zoom_pinned = False
            
            # Defer file tree to next tick so image displays instantly (like slideshow)
            # Slideshow skips file_tree entirely; deferring makes browse feel instant too
            if (hasattr(self, 'file_tree_handler') and 
                self.file_tree_handler.is_tree_initialized() and 
                self.current_view_mode != 'slideshow'):
                QTimer.singleShot(0, self.file_tree_handler.highlight_current_file)
            
            self.apply_current_display_mode()
            self.update_image_display()
            if self.current_view_mode == 'browse':
                ds = self.browse_view_handler.get_browse_paint_viewport_size()
                self.cached_container_width = ds.width()
                self.cached_container_height = ds.height()
            # Refresh overlays for the newly shown image
            self.update_filename_for_new_image()
            self.update_number_overlay()
            
            # Update status bar sections with current image info
            self.update_status_bar_current_image()
            
            # Update preview widget if visible
            self.update_preview_if_visible()
            
            if self.current_view_mode == 'browse' and image_path and os.path.isfile(image_path):
                self._schedule_browse_image_history_record(image_path)
            
        except Exception:
            pass

    def _show_missing_image_placeholder(self, image_path: str, index: int):
        """Show a missing image placeholder when the file doesn't exist"""
        try:
            # Create a missing image placeholder using inline data
            missing_image_pixmap = self._create_missing_image_placeholder(image_path)
            
            if missing_image_pixmap and not missing_image_pixmap.isNull():
                self.current_pixmap = missing_image_pixmap
                self.current_image_path = image_path
                self.current_index = index
                self.browse_zoom_pinned = False
                
                # Defer file tree to next tick only when tree is showing (state variable)
                if (self._is_file_tree_showing() and hasattr(self, 'file_tree_handler') and 
                    self.file_tree_handler.is_tree_initialized() and 
                    self.current_view_mode != 'slideshow'):
                    QTimer.singleShot(0, self.file_tree_handler.highlight_current_file)
                
                self.apply_current_display_mode()
                self.update_image_display()
                if self.current_view_mode == 'browse':
                    ds = self.browse_view_handler.get_browse_paint_viewport_size()
                    self.cached_container_width = ds.width()
                    self.cached_container_height = ds.height()
                # Refresh overlays for the newly shown image
                self.update_filename_for_new_image()
                self.update_number_overlay()
                
                # Update status bar sections with current image info
                self.update_status_bar_current_image()
                
                # Update preview widget if visible
                self.update_preview_if_visible()
        except Exception:
            pass

    def _create_missing_image_placeholder(self, image_path: str = None):
        """Create a missing image placeholder using inline data"""
        try:
            # Get the effective display size to match the current available display area
            display_size = self.get_effective_display_size()
            # Use full dimensions for better message display
            width = display_size.width()
            height = display_size.height()
            # Ensure minimum size for readability
            width = max(width, 400)
            height = max(height, 300)
            
            # Create message with file path if provided
            if image_path:
                display_path = normalize_path_for_display(image_path)
                if os.path.exists(image_path):
                    message = f"File {display_path} can not be read"
                else:
                    message = f"File {display_path} no longer exists"
            else:
                message = "File no longer exists"
            
            # Use common utility function to create pixmap with message and icon
            return create_message_pixmap(message, width, height)
            
        except Exception:
            # Fallback: return a simple dark colored pixmap
            try:
                display_size = self.get_effective_display_size()
                width = max(display_size.width(), 400)
                height = max(display_size.height(), 300)
            except:
                width = 800  # Ultimate fallback
                height = 600
            return create_message_pixmap("File no longer exists", width, height)

    def _handle_browse_viewport_resize_after_container_change(self, old_w, old_h):
        """Container already resized; refit zoom unless user pinned manual zoom (then adjust pan)."""
        if not self.current_pixmap or self.current_view_mode != 'browse':
            return
        new_size = self.browse_view_handler.get_browse_paint_viewport_size()
        if getattr(self, 'browse_zoom_pinned', False):
            if old_w is not None and old_h is not None:
                self.scroll_x -= (new_size.width() - old_w) / 2.0
                self.scroll_y -= (new_size.height() - old_h) / 2.0
            self.update_image_display()
        else:
            self.apply_current_display_mode()
        self.cached_container_width = new_size.width()
        self.cached_container_height = new_size.height()

    def _browse_after_chrome_layout_change(self):
        """Status bar / peek changed layout; refresh browse view preserving pinned zoom when set."""
        if self.current_view_mode != 'browse' or not self.current_pixmap:
            return
        old_w = self.cached_container_width
        old_h = self.cached_container_height
        if hasattr(self, 'image_container'):
            self.image_container.resize(self.get_effective_display_size())
        self._handle_browse_viewport_resize_after_container_change(old_w, old_h)

    def apply_current_display_mode(self):
        """Apply the current display mode (actual size or fit-to-window) to the loaded image"""
        if not self.current_pixmap:
            return
        
        if self.is_actual_size:
            # For actual size, we want true 1:1 pixel ratio
            # This means each pixel in the image should be displayed as one pixel on screen
            self.scale_factor = 1.0
            
            # Reset pan offset when switching to actual size
            self.scroll_x = 0
            self.scroll_y = 0
        else:
            # Fit to window mode - calculate scale to fit image within available space
            if self.current_view_mode == 'browse' and getattr(self, 'browse_view_handler', None):
                available_size = self.browse_view_handler.get_browse_paint_viewport_size()
            else:
                available_size = self.get_effective_display_size()
            
            # Get the transformed pixmap dimensions for scale calculation
            # This ensures scale factor accounts for rotations that change dimensions
            transformed_pixmap = self.apply_transformations_to_pixmap(self.current_pixmap)
            
            # Calculate scale factors for both dimensions using transformed dimensions
            scale_x = available_size.width() / transformed_pixmap.width()
            scale_y = available_size.height() / transformed_pixmap.height()
            
            # Use the smaller scale to ensure image fits completely
            self.scale_factor = min(scale_x, scale_y)  # Allow scaling up for fit-to-window
            
            # Reset pan offset when switching to fit-to-window mode
            self.scroll_x = 0
            self.scroll_y = 0
        
        self.update_image_display()
        if self.filename_visible:          
            self.right_sidebar.show_image_info_overlay() 

    def update_image_display(self):
        """Update the image display with current transformations"""
        if not self.current_pixmap:
            return
        
        # Skip updating if slideshow2 is active to prevent interference
        if (hasattr(self, 'image_label') and hasattr(self.image_label, 'slideshow2_active') 
            and self.image_label.slideshow2_active):
            return
        
        # Clean up any existing temporary transformed pixmap
        if self.temp_transformed_pixmap:
            self.temp_transformed_pixmap = None
        
        # Apply transformations to the current pixmap
        transformed_pixmap = self.apply_transformations_to_pixmap(self.current_pixmap)
        
        # Store the transformed pixmap temporarily for panning calculations
        self.temp_transformed_pixmap = transformed_pixmap
        
        # Check if panning is needed (image larger than viewport)
        # This handles both zoomed images and large images at actual size (1.0 scale)
        can_pan = (getattr(self, 'browse_view_handler', None) and 
                   self.browse_view_handler.can_pan_image())
        
        if can_pan:
            # Use apply_pan_offset to handle panning for both zoomed and actual-size images
            self.apply_pan_offset()
        elif self.scale_factor == 1.0:
            # When scale factor is 1.0 and image fits in viewport, just display directly
            if hasattr(self, 'image_label'):
                # Apply transparency color handling even when image fits
                self._apply_transparency_color_to_pixmap(transformed_pixmap)
        else:
            # Scale factor != 1.0 but image fits in viewport (fit-to-window mode)
            # Display scaled image directly without panning
            if hasattr(self, 'image_label'):
                
                # Calculate exact target dimensions
                target_width = int(transformed_pixmap.width() * self.scale_factor)
                target_height = int(transformed_pixmap.height() * self.scale_factor)
                
                # Use IgnoreAspectRatio since we've already calculated the correct proportions
                # This prevents Qt from "correcting" our dimensions and interfering with rotation
                scaled_pixmap = transformed_pixmap.scaled(
                    QSize(target_width, target_height),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                # Apply transparency color handling
                self._apply_transparency_color_to_pixmap(scaled_pixmap)
        
        # Update number overlay position/content if visible
        self.update_number_overlay()

    def update_number_overlay(self):
        """Update the number overlay visibility, content, and position."""
        # Ensure attributes exist
        if not hasattr(self, 'number_overlay_label'):
            return

        # Only in browse with a current image
        if self.current_view_mode != 'browse' or not self.current_image_path:
            self.number_overlay_shadow_label.hide()
            self.number_overlay_label.hide()
            return

        # Determine overlay text and font size based on filename pattern
        match = self._extract_imagegen_digits(self.current_image_path)
        show_overlay = self.number_overlay_visible
        use_digits = match is not None

        if not show_overlay:
            self.number_overlay_shadow_label.hide()
            self.number_overlay_label.hide()
            return

        if use_digits:
            overlay_text = match
            font_size = 196
        else:
            # Show basename (with extension), font size 25% of original (rounded down)
            overlay_text = os.path.basename(self.current_image_path)
            font_size = max(1, int(196 * 0.25))

        # Configure font
        font = QFont("Impact")
        font.setPointSize(font_size)
        font.setBold(True)

        # Set font and text for both labels
        self.number_overlay_shadow_label.setFont(font)
        self.number_overlay_label.setFont(font)
        self.number_overlay_shadow_label.setText(overlay_text)
        self.number_overlay_label.setText(overlay_text)
        self.number_overlay_shadow_label.adjustSize()
        self.number_overlay_label.adjustSize()

        # Recalculate margin/shadow offset (keep them the same regardless of overlay)
        margin = 20
        shadow_offset_x = 6
        shadow_offset_y = 6

        # Use effective display size to position relative to main content area
        if self.current_view_mode == 'browse' and getattr(self, 'browse_view_handler', None):
            display_size = self.browse_view_handler.get_browse_paint_viewport_size()
        else:
            display_size = self.get_effective_display_size()
        label_size = self.number_overlay_label.size()
        x = max(0, display_size.width() - label_size.width() - margin)
        y = margin

        self.number_overlay_shadow_label.move(x - shadow_offset_x, y + shadow_offset_y)
        self.number_overlay_label.move(x, y)
        self.number_overlay_shadow_label.raise_()
        self.number_overlay_label.raise_()
        self.number_overlay_shadow_label.show()
        self.number_overlay_label.show()

    def _extract_imagegen_digits(self, image_path: Optional[str]) -> Optional[str]:
        """Extract 4-digit code from filenames like imagegen-0123.ext. Returns digits or None."""
        try:
            if not image_path:
                return None
            basename = os.path.basename(image_path)
            m = re.match(r"imagegen-(\d{4})\.(webp|png|jpg|jpeg)$", basename, re.IGNORECASE)
            if m:
                return m.group(1)
            return None
        except Exception:
            return None

    def _apply_image_transformation(self, rotation_delta=0, flip_horizontal=False, flip_vertical=False, status_message=None):
        """Apply a parameterized transformation to the current image."""
        if not self.current_image_path:
            return

        # Get current transformation or create default
        current_transform = self.image_transformations.get(self.current_image_path, (0, False, False))
        rotation, h_flip, v_flip = current_transform

        # Apply rotation
        if rotation_delta != 0:
            rotation = (rotation + rotation_delta) % 360

        # Apply flips
        if flip_horizontal:
            h_flip = not h_flip
        if flip_vertical:
            v_flip = not v_flip

        # Update transformation
        self.image_transformations[self.current_image_path] = (rotation, h_flip, v_flip)
        
        # Refresh display only if we're in browse view mode
        # For thumbnail mode, we'll just refresh the thumbnails
        if self.current_view_mode == 'browse':
            self.update_image_display()

        # Refresh thumbnails to show transformation
        self.refresh_thumbnails_for_transformation()

        # Update preview widget if it exists (force update even if temporarily hidden)
        if hasattr(self, 'preview_widget'):
            self.preview_widget.update_preview(force=True)

        # Show status notification
        if self.status_notification and status_message:
            self.status_notification.show_message(status_message, duration=1500)

    def rotate_image_clockwise(self):
        """Rotate current image 90 degrees clockwise"""
        self._apply_image_transformation(rotation_delta=90, status_message="Rotated 90° clockwise")

    def rotate_image_counterclockwise(self):
        """Rotate current image 90 degrees counter-clockwise"""
        self._apply_image_transformation(rotation_delta=-90, status_message="Rotated 90° counter-clockwise")

    def flip_image_horizontal(self):
        """Flip current image horizontally"""
        self._apply_image_transformation(flip_horizontal=True, status_message="Flipped horizontally")

    def flip_image_vertical(self):
        """Flip current image vertically"""
        self._apply_image_transformation(flip_vertical=True, status_message="Flipped vertically")

    def show_next_image(self):
        """Show next image, handling specific-files mode as well as normal mode."""
        displayed = self.get_displayed_images()
        if not displayed:
            return

        # --- Determine active mode and source of truth for global list ---
        specific_files_active = getattr(self, "specific_files_active", False)

        all_images = displayed

        # Handle windowed wrap logic (thumbnails-in-browse or limited views)
        # Only use windowed wrap if we're in browse and have a reasonable limit
        use_windowed_wrap = (self.current_view_mode == 'browse' and not specific_files_active)

        # --- Specific-files mode navigation: always use displayed_images as bases ---
        if specific_files_active:
            try:
                current_idx = displayed.index(self.current_image_path)
            except (ValueError, AttributeError):
                current_idx = 0

            # Next index, with wrap
            if current_idx < len(displayed) - 1:
                next_idx = current_idx + 1
            elif self.wrap_around:
                next_idx = 0
            else:
                next_idx = current_idx

            next_image_path = displayed[next_idx]
            # Set current image by path (source of truth) - this derives highlight_index
            self.set_current_image_by_path(next_image_path)
            self.current_index = next_idx  # In specific-files mode, this is local to displayed_images

            self.show_image(next_image_path, self.current_index)
            # Status bar already updated by set_current_image_by_path (config sync); show_image also updates
            self.image_display_manager.update_window_title_for_active_image()
            if hasattr(self, 'preview_widget'):
                self.preview_widget.update_preview(force=True)
            return

        # --- Windowed wrap for limited mode in fullscreen ---
        if use_windowed_wrap:
            try:
                current_displayed_index = displayed.index(self.current_image_path)
            except (ValueError, AttributeError):
                current_displayed_index = 0

            if current_displayed_index < len(displayed) - 1:
                next_displayed_index = current_displayed_index + 1
            elif self.wrap_around:
                next_displayed_index = 0
            else:
                next_displayed_index = current_displayed_index

            next_image_path = displayed[next_displayed_index]
            # Set current image by path (source of truth) - this derives highlight_index
            self.set_current_image_by_path(next_image_path)
            # Update current_index to the global index in all_images
            try:
                self.current_index = all_images.index(next_image_path)
            except (ValueError, AttributeError):
                self.current_index = 0

            self.show_image(next_image_path, self.current_index)
            # Status bar already updated by set_current_image_by_path (config sync); show_image also updates
            self.image_display_manager.update_window_title_for_active_image()
            if hasattr(self, 'preview_widget'):
                self.preview_widget.update_preview(force=True)
            return

        # --- Standard navigation for directory mode, not limited ---
        try:
            current_global_index = all_images.index(self.current_image_path)
        except (ValueError, AttributeError):
            current_global_index = 0

        # Move to next image, with wrap-around if enabled
        if current_global_index < len(all_images) - 1:
            next_global_index = current_global_index + 1
        elif self.wrap_around:
            next_global_index = 0
        else:
            next_global_index = current_global_index

        next_image_path = all_images[next_global_index]
        self.current_index = next_global_index

        # If the next image is not in the currently displayed window, update windowing
        if self.current_view_mode == 'browse':
            if not hasattr(self, 'displayed_images') or not self.displayed_images or next_image_path not in self.displayed_images:
                self._update_windowing_if_needed(next_image_path)
            # After windowing update, sync highlight_index from current_image_path
            displayed = self.get_displayed_images()

        # Set current image by path (source of truth) - this derives highlight_index
        self.set_current_image_by_path(next_image_path)
        self.show_image(next_image_path, self.current_index)
        # Status bar already updated by set_current_image_by_path (config sync); show_image also updates
        self.image_display_manager.update_window_title_for_active_image()
        if hasattr(self, 'preview_widget'):
            self.preview_widget.update_preview(force=True)
    def show_previous_image(self):
        """Show previous image - supports both directory and specific files modes"""
        displayed = self.get_displayed_images()
        if not displayed:
            return

        # --- Determine navigation mode ---
        specific_mode = getattr(self, "specific_files_active", False)
        images_list = displayed  # DGN seems like an incomplete change to new image (above)

        # Windowed wrap logic applies only in fullscreen mode with limit, and not in specific files mode
        # Only use windowed wrap if we have a reasonable limit
        use_windowed_wrap = bool(self.current_view_mode == 'browse' and not specific_mode)

        if use_windowed_wrap:
            # Only wrap within the displayed images in fullscreen mode with limit
            try:
                current_displayed_index = displayed.index(self.current_image_path)
            except (ValueError, AttributeError):
                current_displayed_index = 0

            if current_displayed_index > 0:
                prev_displayed_index = current_displayed_index - 1
            elif self.wrap_around:
                prev_displayed_index = len(displayed) - 1
            else:
                prev_displayed_index = current_displayed_index

            prev_image_path = displayed[prev_displayed_index]
            # Set current image by path (source of truth) - this derives highlight_index
            self.set_current_image_by_path(prev_image_path)
            # Update current_index to the global index in images_list
            try:
                self.current_index = images_list.index(prev_image_path)
            except (ValueError, AttributeError):
                self.current_index = 0

            self.show_image(prev_image_path, self.current_index)
            # Status bar already updated by set_current_image_by_path (config sync); show_image also updates
            self.image_display_manager.update_window_title_for_active_image()
            if hasattr(self, 'preview_widget'):
                self.preview_widget.update_preview(force=True)
            return

        # --- Standard navigation for non-windowed or unlimited mode OR specific files mode ---
        try:
            current_global_index = images_list.index(self.current_image_path)
        except (ValueError, AttributeError):
            current_global_index = 0

        if current_global_index > 0:
            prev_global_index = current_global_index - 1
        elif self.wrap_around:
            prev_global_index = len(images_list) - 1
        else:
            prev_global_index = current_global_index

        prev_image_path = images_list[prev_global_index]
        self.current_index = prev_global_index

        # If in browse and image would not be visible, update the window
        if self.current_view_mode == 'browse' and not specific_mode:
            if not hasattr(self, 'displayed_images') or not self.displayed_images or prev_image_path not in self.displayed_images:
                self._update_windowing_if_needed(prev_image_path)
            # After windowing update, sync highlight_index from current_image_path
            displayed = self.get_displayed_images()

        # Set current image by path (source of truth) - this derives highlight_index
        self.set_current_image_by_path(prev_image_path)
        self.show_image(prev_image_path, self.current_index)
        # Status bar already updated by set_current_image_by_path (config sync); show_image also updates
        self.image_display_manager.update_window_title_for_active_image()
        if hasattr(self, 'preview_widget'):
            self.preview_widget.update_preview(force=True)

    def zoom_in(self):
        """Zoom in on the image"""
        if getattr(self, 'browse_view_handler', None):
            self.browse_view_handler.zoom_in()

    def zoom_out(self):
        """Zoom out from the image"""
        if getattr(self, 'browse_view_handler', None):
            self.browse_view_handler.zoom_out()

    def toggle_actual_size(self):
        """Toggle between actual size and fit-to-window display"""
        if getattr(self, 'browse_view_handler', None):
            self.browse_view_handler.toggle_actual_size()

    def open_browse_view(self, index: int):
        """Open image in browse view mode"""
        return self.view_manager.open_browse_view(index)

    def close_browse_view(self):
        """Close browse mode"""
        return self.view_manager.close_browse_view()

    def close_browse_view_action(self):
        """Close browse mode"""
        return self.view_manager.close_browse_view_action()

    def shift_thumbnail_window(self, direction: int) -> bool:
        """Shift the thumbnail window by one limit amount in the specified direction.
        
        Args:
            direction: -1 for left (towards index 0), +1 for right (towards end)
        
        Returns:
            True if window was shifted, False otherwise
        """
        # Only work in thumbnail view
        if ( self.current_view_mode != 'thumbnail' 
              or getattr(self, 'specific_files_active', False) 
              or self.current_sort_mode == SortMode.RANDOM
              ):
            return False
        
        # Only work if limit is set and we have more files than the limit
        if not hasattr(self, 'limit') or self.limit >= 99999:
            return False
        
        # Get the full sorted/filtered list
        all_images = self.get_full_sorted_filtered_list()
        if len(all_images) <= self.limit:
            # All images are already shown, no windowing needed
            return False
        
        # Get the current file
        current_file = self.get_current_image_path()
        if not current_file or current_file not in all_images:
            return False
        
        # Find the current file's index in the full list
        current_index_in_full = all_images.index(current_file)
        
        # Calculate the new target index
        # Use limit-1 so that the first image moves to last (left) and last moves to first (right)
        delta = self.limit - 1
        if direction < 0:  # Shift left
            new_index_in_full = max(0, current_index_in_full - delta)
        else:  # Shift right
            new_index_in_full = min(len(all_images) - 1, current_index_in_full + delta)
        
        # If we're already at the boundary, don't shift
        if new_index_in_full == current_index_in_full:
            return False
        
        # Get the new target file
        new_target_file = all_images[new_index_in_full]
        
        # Calculate the window around the new target
        # Try to keep the same relative position in the window as before
        # Find the current file's offset within the displayed window
        old_offset_in_window = 0
        if self.displayed_images and current_file in self.displayed_images:
            try:
                old_offset_in_window = self.displayed_images.index(current_file)
            except ValueError:
                old_offset_in_window = 0
        
        # Calculate new window start/end so that new_index_in_full is at old_offset_in_window position
        # start_index + old_offset_in_window = new_index_in_full
        # So: start_index = new_index_in_full - old_offset_in_window
        start_index = max(0, new_index_in_full - old_offset_in_window)
        end_index = min(len(all_images), start_index + self.limit)
        
        # Adjust if we're near the boundaries
        if end_index - start_index < self.limit:
            # If window is too small, adjust start_index
            start_index = max(0, end_index - self.limit)
        
        # Ensure we don't go out of bounds
        if start_index < 0:
            start_index = 0
        if end_index > len(all_images):
            end_index = len(all_images)
        if end_index - start_index > self.limit:
            end_index = start_index + self.limit
        
        # Update displayed_images
        self.displayed_images = all_images[start_index:end_index]
        
        # Update highlight_index to point to the new target file in the displayed window
        new_highlight_index = new_index_in_full - start_index
        # Ensure it's within bounds
        if new_highlight_index < 0:
            new_highlight_index = 0
        elif new_highlight_index >= len(self.displayed_images):
            new_highlight_index = len(self.displayed_images) - 1
        
        self.highlight_index = new_highlight_index
        self.current_index = new_highlight_index
        self.current_image_path = new_target_file
        
        # Update the display
        self.populate_indices_arrays()
        self.create_immediate_placeholders()
        self.start_background_thumbnail_loading_if_needed()
        self.highlight_image()
        
        return True

    def update_windowing_if_needed(self, target_file: str = None):
        """Update windowing context if we're in window mode (limit is specified) and allow rewindow when new files appear at the start."""

        # Use the provided target file or the current active file
        if target_file is None:
            if getattr(self, 'displayed_images', None) and hasattr(self, 'highlight_index'):
                if 0 <= self.highlight_index < len(self.displayed_images):
                    target_file = self.displayed_images[self.highlight_index]
                else:
                    return False
            else:
                return False

        if not target_file or not os.path.exists(target_file):
            return False

        try:
            # Use the current displayed_images as the source for windowing
            # (already sorted/filtered)
            all_images = self.displayed_images.copy() if self.displayed_images else []

            if not all_images or target_file not in all_images:
                return False

            target_index = all_images.index(target_file)
            num_files = len(all_images)

            # --- Additional criterion for files added at the beginning ---
            # If the total number of images fits within limit (all are shown), always show all
            if num_files <= self.limit:
                if self.displayed_images != all_images:
                    self.displayed_images = all_images
                    self.populate_indices_arrays()
                    self.highlight_index = target_index
                    self.current_index = target_index
                    self.create_immediate_placeholders()
                    self.start_background_thumbnail_loading_if_needed()
                return True

            # If target fits within the first `limit` images, show the first window
            if target_index < self.limit:
                first_window = all_images[:self.limit]
                if self.displayed_images != first_window:
                    self.displayed_images = first_window
                    self.populate_indices_arrays()
                    self.highlight_index = target_index
                    self.current_index = target_index
                    self.create_immediate_placeholders()
                    self.start_background_thumbnail_loading_if_needed()
                return True

            # --- Existing logic: handle normal centered windowing ---

            # Check if the target file is already visible in the current window
            target_visible = (
                getattr(self, 'displayed_images', None) and
                target_file in self.displayed_images
            )

            if target_visible:
                try:
                    expected_start = max(0, target_index - self.limit // 2)
                    expected_end = min(len(all_images), expected_start + self.limit)
                    if expected_end - expected_start < self.limit and expected_start > 0:
                        expected_start = max(0, expected_end - self.limit)
                    expected_window = all_images[expected_start:expected_end]
                    current_window = self.displayed_images
                    if expected_window == current_window:
                        return True
                except ValueError:
                    pass
                # Fall through to recalculate window

            # Look for overlap with current window images in new order (for resort)
            current_window_images_in_new_order = []
            if getattr(self, 'displayed_images', None):
                for img in self.displayed_images:
                    if img in all_images:
                        current_window_images_in_new_order.append(img)

            if current_window_images_in_new_order:
                indices = [all_images.index(img) for img in current_window_images_in_new_order]
                min_index = min(indices)
                max_index = max(indices)
                if min_index <= target_index <= max_index:
                    start_index = max(0, target_index - self.limit // 2)
                    end_index = min(len(all_images), start_index + self.limit)
                    if end_index - start_index < self.limit:
                        start_index = max(0, end_index - self.limit)
                else:
                    start_index = max(0, target_index - self.limit // 2)
                    end_index = min(len(all_images), start_index + self.limit)
                    if end_index - start_index < self.limit:
                        start_index = max(0, end_index - self.limit)
            else:
                half_window = self.limit // 2
                start_index = max(0, target_index - half_window)
                end_index = min(len(all_images), start_index + self.limit)
                if end_index - start_index < self.limit and start_index > 0:
                    start_index = max(0, end_index - self.limit)

            new_displayed_images = all_images[start_index:end_index]
            self.displayed_images = new_displayed_images
            self.populate_indices_arrays()
            new_target_index = target_index - start_index
            self.highlight_index = new_target_index
            self.current_index = target_index
            self.create_immediate_placeholders()
            self.start_background_thumbnail_loading_if_needed()
            return True

        except Exception:
            return False

    def sequential_refresh_after_browse(self):
        """Minimal refresh after browse to sync thumbnails efficiently."""
        return self.refresh_manager.sequential_refresh_after_browse()

    # @safe_refresh_wrapper
    def _sequential_refresh_after_browse_impl(self):
        """Implementation of the sequential refresh after browse."""
        # If settings changed while in browse mode, do a full refresh
        if getattr(self, '_settings_changed_in_browse', False):
            self._settings_changed_in_browse = False
            self.refresh_directory(force=True)
            return
        
        # Use the existing efficient refresh method which is designed to be smooth
        # This will detect new files and update the display efficiently without flashing
        self.efficient_directory_refresh()
        
    def refresh_directory(self, force=False):
        """
        Request directory refresh via event bus. RefreshManager subscribes and performs the refresh.
        When called via cmd-R, this does a full refresh preserving current state.
        """
        from event_bus import REFRESH_REQUESTED
        self.event_bus.emit(REFRESH_REQUESTED, force)

    def _simple_refresh_with_limit(self, preserve_current_image=None):
        """
        Simple refresh that just honors the current limit - no complex windowing logic
        
        Args:
            preserve_current_image: Optional path to preserve as current image during refresh
        """
        if not self.current_directory:
            return
        
        # Use preserved current image if provided, otherwise get current
        if preserve_current_image is None:
            preserve_current_image = self.get_current_image_path()
        
        # Clear any cached state that might prevent new files from being detected
        if hasattr(self, '_cached_grid_columns'):
            delattr(self, '_cached_grid_columns')
        if hasattr(self, '_cached_thumbnail_size'):
            delattr(self, '_cached_thumbnail_size')
        self.cached_container_width = None
        self.cached_container_height = None
        
        # Get all files in the directory
        current_files = self._get_current_directory_files()
        if not current_files:
            # Clear displayed images if no files found
            self.displayed_images = []
            self.populate_indices_arrays()
            self.clear_thumbnails()
            return
        
        original_displayed_images = self.displayed_images.copy()
        # Convert to list and sort
        current_files_list = list(current_files)
        
        # Preserve random order (marked by is_browsing_at_random) - don't re-sort
        # BUT: Always filter out files that no longer exist on disk
        if self.current_sort_mode == SortMode.RANDOM and original_displayed_images:
            # Keep the random order - just filter and update if needed
            current_files_list = original_displayed_images.copy()
            # CRITICAL: Filter out files that no longer exist on disk (not just in current_files set)
            current_files_list = [f for f in current_files_list if os.path.exists(f) and f in current_files]
            # Add any new files that weren't in the original list (append to end)
            new_files = [f for f in current_files if f not in current_files_list]
            current_files_list.extend(new_files)
        elif self.current_sort_mode == SortMode.CUSTOM and original_displayed_images:
            # Preserve custom sort order - don't re-sort
            # BUT: Always filter out files that no longer exist on disk
            current_files_list = original_displayed_images.copy()
            # CRITICAL: Filter out files that no longer exist on disk (not just in current_files set)
            current_files_list = [f for f in current_files_list if os.path.exists(f) and f in current_files]
            # Add any new files that weren't in the original list (append to end)
            new_files = [f for f in current_files if f not in current_files_list]
            current_files_list.extend(new_files)
        elif self.current_sort_mode == SortMode.NAME:
            current_files_list.sort(key=lambda path: path.lower(), reverse=self.is_reversed)
        elif self.current_sort_mode == SortMode.SIZE:
            # Size sorting - sort by width × height, then by width for same area, then by path
            def get_size_sort_key(path):
                try:
                    cache_key = self.cache_manager.get_cache_key(path)
                    if cache_key in self.cache_manager.metadata_cache:
                        metadata = self.cache_manager.metadata_cache[cache_key]
                        if metadata and hasattr(metadata, 'width') and hasattr(metadata, 'height'):
                            if metadata.width > 0 and metadata.height > 0:
                                area = metadata.width * metadata.height
                                if self.is_reversed:
                                    return (area, -metadata.width, path.lower())  # Smallest first: negate width so wider comes first
                                else:
                                    return (area, metadata.width, path.lower())  # Largest first: wider comes first naturally
                    dimensions = get_image_dimensions_fast_metadata(path)
                    if dimensions and len(dimensions) == 2:
                        width, height = dimensions
                        if width > 0 and height > 0:
                            area = width * height
                            if self.is_reversed:
                                return (area, -width, path.lower())  # Smallest first: negate width so wider comes first
                            else:
                                return (area, width, path.lower())  # Largest first: wider comes first naturally
                    return (0, 0, path.lower())
                except Exception:
                    return (0, 0, path.lower())
            try:
                current_files_list.sort(key=get_size_sort_key, reverse=not self.is_reversed)
            except Exception:
                current_files_list.sort(key=lambda p: p.lower())
        else:
            try:
                current_files_list.sort(key=self.get_sort_key, reverse=not self.is_reversed)
            except Exception:
                current_files_list.sort(key=lambda path: path.lower())
        
        # CRITICAL: Filter out files that no longer exist on disk before applying other filters
        # This ensures deleted files are removed even if they're in the current_files set
        current_files_list = [f for f in current_files_list if os.path.exists(f)]
        
        # CRITICAL: Filter out files that no longer exist on disk before applying other filters
        # This ensures deleted files are removed even if they're in the current_files set
        current_files_list = [f for f in current_files_list if os.path.exists(f)]
        
        # Apply filter
        if self.filter_pattern:
            current_files_list = self.sorting_manager.filter_images_by_pattern(current_files_list)
        
        # Check for pending rename path first - use it instead of current_image_path if present
        if getattr(self, 'pending_rename_path', None):
            current_image_path = self.pending_rename_path
            # Clear it so it's only used once
            delattr(self, 'pending_rename_path')
        else:
            # Use preserved current image if provided, otherwise get current
            current_image_path = preserve_current_image if preserve_current_image else self.get_current_image_path()
        try:
            limit = self.limit
            index_in_list = current_files_list.index(current_image_path)

            # Try to avoid changing the current window if current_image_path is in the already-active window
            # Find the current window: computed before as displayed_images (original_displayed_images)
            prev_start_index = None
            prev_end_index = None
            try:
                if original_displayed_images:
                    first = original_displayed_images[0]
                    last = original_displayed_images[-1]
                    prev_start_index = current_files_list.index(first)
                    prev_end_index = current_files_list.index(last) + 1  # end-exclusive
            except Exception:
                prev_start_index = None
                prev_end_index = None

            # If current_image_path is in previous window, preserve window; else, center
            # Optimize: remove the 'if False and ...' block (never runs), condense logic.

            # If the active image was in the same position in the previous window, preserve its position;
            # otherwise, center it in the new window

            if (
                original_displayed_images
                and current_image_path in original_displayed_images[:limit]
            ):
                # Windowing logic for positioning the current image in the limit window
                prev_pos = original_displayed_images.index(current_image_path)

                # By default, retain previous visible window positioning for the active image.
                start_index = max(0, index_in_list - prev_pos)
                end_index = min(len(current_files_list), start_index + limit)
                start_index = max(0, end_index - limit)  # In case near end

                # Enhancement: If it's possible to fit the first file AND the current image in the window, 
                # shift the window so the first file is also visible unless the window would shift past the end.
                first_file_index = 0
                if (
                    first_file_index < index_in_list and
                    index_in_list - first_file_index < limit
                    and end_index == start_index + limit  # window at full size
                ):
                    # Shift the window so it starts at the first file if it doesn't push us past the end
                    if len(current_files_list) >= limit:
                        tentative_start = 0
                        tentative_end = limit
                    else:
                        tentative_start = 0
                        tentative_end = len(current_files_list)
                    # Make sure the current image still fits within the window
                    if tentative_end > index_in_list:
                        start_index = tentative_start
                        end_index = tentative_end

                self.displayed_images = current_files_list[start_index:end_index]
                self.highlight_index = index_in_list - start_index
                index_in_list = self.highlight_index
                self.skip_images_change = False # must be false to make getattr() work
            else:
                # Center the active image in the window if possible, so it's in the middle of the windowed images,
                # unless near the start/end of the list.

                half_limit = limit // 2
                start_index = index_in_list - half_limit
                end_index = start_index + limit

                if start_index < 0:
                    start_index = 0
                    end_index = min(limit, len(current_files_list))
                elif end_index > len(current_files_list):
                    end_index = len(current_files_list)
                    start_index = max(0, end_index - limit)

                # Enhancement: shift window to show first file if possible (when showing the current image doesn't push window past end)
                if (
                    start_index > 0
                    and index_in_list < limit  # current image is in first 'limit' images
                ):
                    start_index = 0
                    end_index = min(limit, len(current_files_list))

                # Use sync helper to ensure FileDataModel consistency
                self.configuration_sync_manager._set_displayed_images_with_sync(current_files_list[start_index:end_index], sync=True)
                self.highlight_index = index_in_list - start_index

                self.skip_images_change = False # must be false to make getattr() work

            self.current_index = index_in_list
            self.current_image_path = current_image_path
            # Sync with FileDataModel to ensure consistency
            try:
                self._sync_to_file_data_model()
            except Exception:
                # Don't let sync errors break refresh
                pass
        except ValueError:
            # import traceback; print(f"{RED}ValueError: {e}{RESET}"); traceback.print_exc()
            """ 
               TBD: we can reach this point when the command line (or api?) passes a nonexistent file
               in which case the current_file_name will be none and will crapped out on looking for it 
               in the current_files_list. Dunno. sometimes it gets an unable to start app error.
                
               Look for a good UI response to this situation.
            """
            # File not found by exact match - try normalized path comparison
            # assert True, "Check this ValueError - it should not happen"
            index_in_list = None
            try:
                # Check if current_image_path is None before trying to normalize it
                if current_image_path is None:
                    # If no current image path, just use the first image or keep index_in_list as None
                    index_in_list = 0 if current_files_list else None
                else:
                    current_image_path_normalized = os.path.normpath(os.path.realpath(current_image_path))
                    for idx, img_path in enumerate(current_files_list):
                        try:
                            img_path_normalized = os.path.normpath(os.path.realpath(img_path))
                        except (OSError, ValueError):
                            img_path_normalized = os.path.normpath(img_path)
                        if img_path_normalized == current_image_path_normalized or img_path == current_image_path:
                            index_in_list = idx
                            break
            except (OSError, ValueError):
                pass
            
            if index_in_list is not None:
                # Found via normalized comparison - use same logic as above
                limit = self.limit
                prev_start_index = None
                prev_end_index = None
                try:
                    if original_displayed_images:
                        first = original_displayed_images[0]
                        last = original_displayed_images[-1]
                        prev_start_index = current_files_list.index(first)
                        prev_end_index = current_files_list.index(last) + 1
                except Exception:
                    prev_start_index = None
                    prev_end_index = None
                
                if prev_start_index is not None and prev_end_index is not None \
                        and prev_start_index <= index_in_list < prev_end_index:
                    self.displayed_images = current_files_list[prev_start_index:prev_start_index + limit]
                    self.highlight_index = index_in_list - prev_start_index
                    current_files_list = self.displayed_images # DGN <-- 11/15/2025 use original displayed_images list
                else:
                    start_index = max(0, index_in_list - limit // 2)
                    end_index = min(len(current_files_list), start_index + limit)
                    start_index = max(0, end_index - limit)
                    self.displayed_images = current_files_list[start_index:end_index]
                    self.highlight_index = index_in_list - start_index
                self.current_index = index_in_list
                self.current_image_path = current_image_path
                # Sync with FileDataModel to ensure consistency
                try:
                    self._sync_to_file_data_model()
                except Exception:
                    # Don't let sync errors break refresh
                    pass
            else:
                # Still not found - fall back to 0
                self.highlight_index = 0
                self.current_index = 0
                self.current_image_path = None
                # Sync with FileDataModel
                try:
                    self._sync_to_file_data_model()
                except Exception:
                    pass
                self.displayed_images = current_files_list

        # if self.limit is not None and len(current_files_list) > self.limit:
        #     if self.is_reversed:
        #         self.displayed_images = current_files_list[-self.limit:]
        #     else:
        #         self.displayed_images = current_files_list[:self.limit]
        # else:
        if getattr(self, 'skip_images_change', True):
            self.displayed_images = current_files_list
        
        # Skip early return if sort mode changed - we need to update even if files are the same
        # Only skip if files are identical AND order is identical (not just same files)
        # This check should not prevent sort mode changes from updating the display
        # Note: List comparison checks both content and order, so if order changed, this won't match
        if (len(self.displayed_images) == len(original_displayed_images) and
            len(self.displayed_images) > 0 and
            all(a == b for a, b in zip(self.displayed_images, original_displayed_images))):
            # Files and order are identical - skip refresh
            # But don't skip if we're applying a sort (sort changes order even if files are same)
            if not getattr(self, '_applying_sort', False):
                return


        # Update indices
        self.populate_indices_arrays()
        
        # Clear existing thumbnails to ensure fresh display
        self.clear_thumbnails()
        
        # Generate thumbnails
        self.generate_thumbnails(force_refresh=True)
        
        # Start background loading
        self.start_background_thumbnail_loading_if_needed()

    def simulate_browse_view_exit_for_refresh(self):
        """Refresh directory - same behavior as Apply button in settings"""
        # Skip refresh if we're currently restoring from directory history
        # This prevents clearing selections that are being restored
        if getattr(self, 'restoring_from_history', False):
            return
        
        # Skip rebuild if directory was opened from tree view - tree is already expanded correctly
        # This prevents unnecessary rebuilds when user clicks leaf nodes or presses Enter
        if (getattr(self, 'file_tree_handler', None) and 
            getattr(self.file_tree_handler, 'user_requested_directory', None)):
            # Still do thumbnail refresh, just skip tree rebuild
            if (getattr(self, 'cache_manager', None) and 
                self.cache_manager.background_loader):
                self.cache_manager.background_loader.stop()
            # Check if we're in partial thumbnail mode - if so, refresh the partial list
            if self._is_in_partial_thumbnail_mode():
                self._refresh_partial_thumbnail_list()
                # Restart thumbnail generation after refresh
                if (getattr(self, 'cache_manager', None) and 
                    self.cache_manager.background_loader):
                    self.cache_manager.background_loader.start()
                if hasattr(self, 'start_background_thumbnail_loading_if_needed'):
                    self.start_background_thumbnail_loading_if_needed()
            else:
                # Force refresh of the directory (same as apply_filter_now does)
                def refresh_and_restart():
                    if hasattr(self, 'refresh_directory_intelligently'):
                        # Use intelligent refresh that preserves valid thumbnails
                        self.refresh_directory_intelligently()
                    else:
                        self.refresh_directory(force=True)
                    # Restart thumbnail generation after refresh completes
                    if (getattr(self, 'cache_manager', None) and 
                        self.cache_manager.background_loader):
                        self.cache_manager.background_loader.start()
                    if hasattr(self, 'start_background_thumbnail_loading_if_needed'):
                        self.start_background_thumbnail_loading_if_needed()
                refresh_and_restart()
            return
        
        # Stop thumbnail generation when refresh is triggered (same as apply_filter_now)
        if (getattr(self, 'cache_manager', None) and 
            self.cache_manager.background_loader):
            self.cache_manager.background_loader.stop()
        
        # Reload treeview from scratch
        if getattr(self, 'file_tree_handler', None):
            if self.file_tree_handler.is_tree_initialized():
                self.file_tree_handler.rebuild_tree()
                QApplication.processEvents()
        
        # Check if we're in partial thumbnail mode - if so, refresh the partial list
        if self._is_in_partial_thumbnail_mode():
            self._refresh_partial_thumbnail_list()
            # Restart thumbnail generation after refresh
            if (getattr(self, 'cache_manager', None) and 
                self.cache_manager.background_loader):
                self.cache_manager.background_loader.start()
            if hasattr(self, 'start_background_thumbnail_loading_if_needed'):
                self.start_background_thumbnail_loading_if_needed()
            return
        
        # Force refresh of the directory (same as apply_filter_now does)
        def refresh_and_restart():
            if hasattr(self, 'refresh_directory_intelligently'):
                # Use intelligent refresh that preserves valid thumbnails
                self.refresh_directory_intelligently()
            elif hasattr(self, 'efficient_directory_refresh'):
                self.efficient_directory_refresh()
            else:
                # Fallback to regular refresh if efficient method not available
                self.refresh_directory()
            # Update rename status if enabled
            if hasattr(self, 'update_rename_status'):
                self.sidebar_manager.update_rename_status()
            # Restart thumbnail generation after refresh completes
            if (getattr(self, 'cache_manager', None) and 
                self.cache_manager.background_loader):
                self.cache_manager.background_loader.start()
            if hasattr(self, 'start_background_thumbnail_loading_if_needed'):
                self.start_background_thumbnail_loading_if_needed()
        QTimer.singleShot(100, refresh_and_restart)
        
        # Update Move menu items to reflect newly mounted/created directories
        # This ensures keyboard shortcuts (cmd-1 through cmd-9) are available
        # after refresh without needing to view the menu first
        self.update_edit_menu_states()
    
    def _is_in_partial_thumbnail_mode(self):
        """Check if we're currently showing a partial thumbnail list (selected files only)"""
        if not self.current_directory or not self.displayed_images:
            return False
        
        # Check if we're in specific files mode (manually selected images)
        if getattr(self, 'specific_files_active', None):
            return True
        
        # If we're not in specific files mode, we're not in partial mode
        # This is the key fix - only consider it partial mode if we're actually showing selected files
        return False
    
    def _refresh_partial_thumbnail_list(self):
        """Refresh the current partial thumbnail list without resetting to full directory"""
        if not self.displayed_images:
            return
        
        # Check if we can preserve existing thumbnails with pixmaps to avoid flashing
        canvas = self.thumbnail_container.canvas
        if canvas.thumbnails and len(canvas.thumbnails) > 0:
            current_paths = [thumb.image_path for thumb in canvas.thumbnails]
            # If the image list matches, use reorder_thumbnails which preserves pixmaps
            if current_paths == self.displayed_images:
                canvas.thumbnail_size = self.current_thumbnail_size
                canvas.reorder_thumbnails(self.displayed_images, force_recalculate_grid=True)
                
                # Mark thumbnails without pixmaps as needing loading
                with QMutexLocker(canvas.mutex):
                    for thumbnail in canvas.thumbnails:
                        if thumbnail.pixmap is None or thumbnail.pixmap.isNull():
                            thumbnail.is_loading = True
                
                # Set highlight
                if self.displayed_images:
                    if not (0 <= self.highlight_index < len(self.displayed_images)):
                        self.highlight_index = 0
                    self.thumbnail_container.set_highlighted_index(self.highlight_index)
                
                # Start background loading for thumbnails that don't have pixmaps
                self.start_background_thumbnail_loading_if_needed()
                return
        
        # If image list changed or thumbnails don't exist, do full rebuild
        # This will clear and recreate thumbnails, but only when necessary
        self.generate_thumbnails(force_refresh=True)
        
        # Start background loading for the partial list
        self.start_background_thumbnail_loading_if_needed()
    
    def _refresh_specific_files_list(self, force=False):
        """Refresh specific files list - removes deleted files and updates thumbnails while preserving specific files mode"""
        if not self.displayed_images:
            return
        
        # Preserve current image path
        current_image_path = self.get_current_image_path()
        
        # Filter out files that no longer exist on disk
        original_displayed = self.displayed_images.copy()
        valid_files = [f for f in self.displayed_images if os.path.exists(f)]
        
        # Find deleted files before updating displayed_images
        deleted_files = set(original_displayed) - set(valid_files)
        
        # If no valid files remain, clear everything but keep specific files mode
        if not valid_files:
            self.displayed_images = []
            self.populate_indices_arrays()
            self.clear_thumbnails()
            self.update_status_bar_sections()
            return
        
        # Remove deleted files using the existing method (which handles thumbnail removal and UI updates)
        if deleted_files:
            self.thumbnail_display_manager.remove_thumbnails_for_files(deleted_files, active_file_path=current_image_path)
            # After removal, displayed_images is already updated, but verify it matches valid_files
            # (remove_thumbnails_for_files should have removed all deleted files)
            if set(self.displayed_images) != set(valid_files):
                # If there's a mismatch, update to valid_files (preserve order)
                self.displayed_images = valid_files
                self.populate_indices_arrays()
                # Update list view if in list mode
                if getattr(self, 'current_view_mode', None) == 'list':
                    if getattr(self, 'view_manager', None):
                        self.view_manager.update_list_view()
        
        # Preserve current image if it still exists, otherwise select first valid file
        if current_image_path and current_image_path in self.displayed_images:
            self.set_current_image_by_path(current_image_path, fallback_index=0)
        elif self.displayed_images:
            self.set_current_image_by_path(self.displayed_images[0], fallback_index=0)
        
        # Update list view if in list mode (after all updates)
        if getattr(self, 'current_view_mode', None) == 'list':
            if getattr(self, 'view_manager', None):
                self.view_manager.update_list_view()
        
        # Sync highlight index
        self._sync_highlight_index_from_current_image_path()
        
        # Update thumbnails - invalidate cache for files that may have changed
        if force:
            # Force refresh all thumbnails
            for image_path in self.displayed_images:
                try:
                    # Invalidate cache if file was modified
                    file_mtime = os.path.getmtime(image_path)
                    metadata = self.cache_manager.get_metadata_sync(image_path)
                    if metadata and hasattr(metadata, 'modified_time'):
                        cached_mtime = metadata.modified_time
                        if cached_mtime is not None and float(cached_mtime) != float(file_mtime):
                            self.cache_manager.clear_cache_for_file(image_path)
                            if getattr(self, 'thumbnail_container', None) and self.thumbnail_container.canvas:
                                self.thumbnail_container.canvas.invalidate_thumbnails_for_paths([image_path])
                except Exception:
                    pass
            
            # Regenerate thumbnails
            self.generate_thumbnails(force_refresh=True)
        else:
            # Just refresh thumbnails that need updating
            if getattr(self, 'thumbnail_container', None) and self.thumbnail_container.canvas:
                # Reorder thumbnails to match current list
                self.thumbnail_container.canvas.reorder_thumbnails(self.displayed_images, force_recalculate_grid=False)
            
            # Mark thumbnails without pixmaps as needing loading
            canvas = self.thumbnail_container.canvas
            with QMutexLocker(canvas.mutex):
                for thumbnail in canvas.thumbnails:
                    if thumbnail.pixmap is None or thumbnail.pixmap.isNull():
                        thumbnail.is_loading = True
            
            # Start background loading
            self.start_background_thumbnail_loading_if_needed()
        
        # Update highlight
        self.highlight_image()
        
        # Update status bar
        self.update_status_bar_sections()

    def restore_multiple_files_from_trash_(self, deleted_files_batch):
        """Restore multiple files from trash"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.restore_multiple_files_from_trash_(deleted_files_batch)

    def undo_move_operation_(self, moved_files_info):
        """Undo move operation - move files back to their original locations"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.undo_move_operation(moved_files_info)

    def mousePressEvent(self, event):
        """Optimized: handle mouse press for dragging/panning and browse mode management"""
        super().mousePressEvent(event)
        # Only process cursor logic and panning in browse mode
        if getattr(self, 'browse_view_handler', None):
            if self.browse_view_handler.handle_mouse_press(event):
                return
    
    def mouseMoveEvent(self, event):
        """Handle mouse movement for dragging panned images"""
        # Handle browse mode panning/dragging
        if getattr(self, 'browse_view_handler', None):
            if self.browse_view_handler.handle_mouse_move(event):
                super().mouseMoveEvent(event)
                return
        
        # Show appropriate cursor when hovering over pannable image
        if (self.current_view_mode == 'browse' and not self.is_dragging):
            if (getattr(self, 'browse_view_handler', None) and 
                self.browse_view_handler.can_pan_image()):
                if self.cursor_manager:
                    self.cursor_manager.set_cursor(Qt.OpenHandCursor)
                else:
                    self.setCursor(Qt.OpenHandCursor)
            else:
                if self.cursor_manager:
                    self.cursor_manager.set_cursor(Qt.ArrowCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release to stop dragging"""
        # Handle browse mode mouse release
        if getattr(self, 'browse_view_handler', None):
            if self.browse_view_handler.handle_mouse_release(event):
                super().mouseReleaseEvent(event)
                return
                    
        super().mouseReleaseEvent(event)
    
    
    def gestureEvent(self, event: QGestureEvent):
        """Handle gesture events, particularly pinch gestures for trackpad zoom"""
        if getattr(self, 'browse_view_handler', None):
            if self.browse_view_handler.handle_gesture_event(event):
                return True
        
        # QMainWindow doesn't have gestureEvent, so just return False to let Qt handle it
        return False

    def _apply_transparency_color_to_pixmap(self, pixmap):
        """Composite transparent pixels; letterbox uses browse border color from settings."""
        s = self.config.load_settings()
        transparency_color_rgb, use_diamonds = effective_browse_transparency(s)
        transparency_color = QColor(transparency_color_rgb[0], transparency_color_rgb[1], transparency_color_rgb[2])
        
        # Get available display size (browse: match image_container after layout to avoid jump during resize)
        if self.current_view_mode == 'browse' and getattr(self, 'browse_view_handler', None):
            available_size = self.browse_view_handler.get_browse_paint_viewport_size()
        else:
            available_size = self.get_effective_display_size()
        
        border_rgb = effective_browse_border_color(s)
        border_color = QColor(border_rgb[0], border_rgb[1], border_rgb[2])
        display_pixmap = QPixmap(available_size)
        display_pixmap.fill(border_color)
        
        
        # Create composited pixmap - SIZE OF THE IMAGE (not screen size)
        # Fill with black first so pattern is visible
        composited_pixmap = QPixmap(pixmap.size())
        composited_pixmap.fill(QColor(0, 0, 0))
        
        # Fill with diamond pattern or transparency color for transparent areas within the image
        if use_diamonds:
            # Import diamond pattern function from browse_view_handler
            from browse_view_handler import _draw_diamond_pattern
            _draw_diamond_pattern(composited_pixmap)
        else:
            composited_pixmap.fill(transparency_color)
        
        # Draw the image on top - transparent pixels will show diamond pattern or transparency_color
        composite_painter = QPainter(composited_pixmap)
        composite_painter.setRenderHint(QPainter.Antialiasing)
        composite_painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        composite_painter.drawPixmap(0, 0, pixmap)
        composite_painter.end()
        
        # Calculate destination position (center the image if smaller than display area)
        dst_x = max(0, (available_size.width() - pixmap.width()) // 2)
        dst_y = max(0, (available_size.height() - pixmap.height()) // 2)
        
        # Paint the composited pixmap onto the display pixmap (margins use browse border color)
        painter = QPainter(display_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.drawPixmap(dst_x, dst_y, composited_pixmap)
        painter.end()
        
        # Set the resulting pixmap to the label
        self.image_label.setPixmap(display_pixmap)
    
    def apply_pan_offset(self):
        """Apply pan offset to image position by redrawing the visible portion"""
        if getattr(self, 'browse_view_handler', None):
            self.browse_view_handler.apply_pan_offset()

    def zoom_at_point(self, new_scale: float, zoom_point: QPointF):
        """
        Zoom the image while keeping the pixel under zoom_point stationary.
        """
        if getattr(self, 'browse_view_handler', None):
            self.browse_view_handler.zoom_at_point(new_scale, zoom_point)

    def _animate_status_bar_show(self, on_finished=None):
        """Animate status bar sliding up into view (500ms)."""
        self._status_bar_anim.stop()
        self._status_bar_anim_callback = on_finished
        self.status_bar.setMaximumHeight(0)
        self.status_bar.show()
        self._status_bar_anim.setStartValue(0)
        self._status_bar_anim.setEndValue(STATUS_BAR_ANIM_HEIGHT)
        self._status_bar_anim.start()

    def _animate_status_bar_hide(self, on_finished=None):
        """Animate status bar sliding down out of view (500ms)."""
        self._status_bar_anim.stop()
        self._status_bar_anim_callback = on_finished
        start_h = self.status_bar.height() or STATUS_BAR_ANIM_HEIGHT
        self._status_bar_anim.setStartValue(start_h)
        self._status_bar_anim.setEndValue(0)
        self._status_bar_anim.start()

    def _on_status_bar_anim_finished(self):
        """Called when status bar slide animation completes."""
        if self.status_bar.maximumHeight() == 0:
            self.status_bar.hide()
        if self._status_bar_anim_callback:
            cb = self._status_bar_anim_callback
            self._status_bar_anim_callback = None
            cb()

    def _on_status_bar_anim_value_changed(self, _value):
        """Rescale browse fit-to-window image as the status bar height animates."""
        if self.current_view_mode != 'browse' or not self.current_pixmap:
            return
        if self.is_actual_size or getattr(self, 'browse_zoom_pinned', False):
            return
        if not getattr(self, 'image_container', None):
            return
        self.image_container.resize(self.get_effective_display_size())
        self.apply_current_display_mode()
        sz = self.browse_view_handler.get_browse_paint_viewport_size()
        self.cached_container_width = sz.width()
        self.cached_container_height = sz.height()

    def _peek_layout_update(self):
        """Layout update after status bar peek show/hide animation."""
        QTimer.singleShot(10, self.force_resize_recalculation)
        if hasattr(self, 'thumbnail_container') and hasattr(self.thumbnail_container, 'force_canvas_size_update'):
            QTimer.singleShot(20, self.thumbnail_container.force_canvas_size_update)
        if self.current_view_mode == 'browse' and self.current_pixmap:
            QTimer.singleShot(50, self._browse_after_chrome_layout_change)

    def _is_main_window_key_context(self) -> bool:
        """True when app-wide shortcuts should target the main window (not a popup/dialog)."""
        active = QApplication.activeWindow()
        if active is None:
            return False
        if active == self:
            return True
        w = active
        while w:
            if w == self:
                return True
            w = w.parentWidget() if hasattr(w, 'parentWidget') else None
        return False

    def _is_any_chrome_visible(self) -> bool:
        if getattr(self, 'status_bar', None) and self.status_bar.isVisible():
            return True
        if getattr(self, 'combined_sidebar', None) and self.combined_sidebar.isVisible():
            return True
        if getattr(self, 'right_sidebar', None) and self.right_sidebar.isVisible():
            return True
        return False

    def _capture_chrome_layout(self) -> dict:
        cs = self.combined_sidebar
        rs = self.right_sidebar
        sizes = self.main_splitter.sizes()
        left_sizes = cs.splitter.sizes() if hasattr(cs, 'splitter') else []
        right_sizes = rs.splitter.sizes() if hasattr(rs, 'splitter') else []
        return {
            'status_bar_visible': self.status_bar.isVisible(),
            'left_tree_visible': cs.is_tree_visible(),
            'left_preview_visible': cs.is_preview_visible(),
            'left_splitter_sizes': (
                list(cs.saved_splitter_sizes)
                if cs.saved_splitter_sizes
                else list(left_sizes)
            ),
            'sidebar_width': self.sidebar_width,
            'right_information_visible': rs.is_information_visible(),
            'right_shortcuts_visible': rs.is_shortcuts_visible(),
            'right_jobs_visible': rs.is_jobs_visible(),
            'right_splitter_sizes': (
                list(rs.saved_splitter_sizes)
                if rs.saved_splitter_sizes
                else list(right_sizes)
            ),
            'right_sidebar_width': self.right_sidebar_width,
            'main_splitter_sizes': list(sizes) if len(sizes) >= 3 else None,
        }

    def _hide_all_chrome(self):
        self._chrome_suppressed = True
        self._status_bar_peek_active = False
        if getattr(self, '_status_bar_anim', None):
            self._status_bar_anim.stop()
        if getattr(self, 'status_bar', None):
            self.status_bar.setMaximumHeight(0)
            self.status_bar.hide()
        if getattr(self, 'combined_sidebar', None):
            self.combined_sidebar.hide()
        if getattr(self, 'right_sidebar', None):
            self.right_sidebar.hide()
            self.right_sidebar.hide_info()
        total_width = self.main_splitter.width()
        if total_width > 0:
            self._set_splitter_sizes_safe([0, total_width, 0])
        self._update_chrome_menu_actions()
        self._peek_layout_update()

    def _restore_chrome_layout(self, layout: dict):
        self._chrome_suppressed = False
        cs = self.combined_sidebar
        rs = self.right_sidebar
        self.sidebar_width = layout.get('sidebar_width', self.sidebar_width)
        self.right_sidebar_width = layout.get('right_sidebar_width', self.right_sidebar_width)
        left_sizes = layout.get('left_splitter_sizes')
        if left_sizes and len(left_sizes) >= 2:
            cs.saved_splitter_sizes = list(left_sizes)
        right_sizes = layout.get('right_splitter_sizes')
        if right_sizes and len(right_sizes) >= 3:
            rs.saved_splitter_sizes = list(right_sizes)
        cs.set_tree_visible(layout.get('left_tree_visible', False))
        cs.set_preview_visible(layout.get('left_preview_visible', False))
        rs.set_information_visible(layout.get('right_information_visible', False))
        rs.set_shortcuts_visible(layout.get('right_shortcuts_visible', False))
        rs.set_jobs_visible(layout.get('right_jobs_visible', False))
        self.file_tree_visible = cs.is_tree_visible()
        self.preview_visible = cs.is_preview_visible()
        self.jobs_visible = rs.is_jobs_visible()
        self.manage_sidebar_visibility_for_view_mode(self.current_view_mode)
        saved_main = layout.get('main_splitter_sizes')
        if saved_main and len(saved_main) == 3 and sum(saved_main) > 0:
            self._set_splitter_sizes_safe(saved_main)
        self._status_bar_peek_active = False
        if layout.get('status_bar_visible'):
            if self.status_bar.isVisible():
                self._update_chrome_menu_actions()
                self._peek_layout_update()
            else:
                self._animate_status_bar_show(self._after_chrome_status_restore)
        else:
            self._update_chrome_menu_actions()
            self._peek_layout_update()

    def _after_chrome_status_restore(self):
        self._update_chrome_menu_actions()
        self._peek_layout_update()

    def _show_default_chrome(self):
        self._chrome_suppressed = False
        cs = self.combined_sidebar
        rs = self.right_sidebar
        cs.set_tree_visible(True)
        cs.set_preview_visible(True)
        rs.set_information_visible(True)
        rs.set_shortcuts_visible(True)
        rs.set_jobs_visible(True)
        self.file_tree_visible = True
        self.preview_visible = True
        self.jobs_visible = True
        self.right_sidebar_visible = True
        self._status_bar_peek_active = False
        self.manage_sidebar_visibility_for_view_mode(self.current_view_mode)
        if not self.status_bar.isVisible():
            self._animate_status_bar_show(self._after_chrome_status_restore)
        else:
            self._update_chrome_menu_actions()
            self._peek_layout_update()

    def _update_chrome_menu_actions(self):
        if hasattr(self, 'toggle_status_bar_action'):
            vis = self.status_bar.isVisible()
            self.toggle_status_bar_action.setChecked(vis)
            self.toggle_status_bar_action.setText(
                'Hide Status Bar' if vis else 'Show Status Bar'
            )
        if hasattr(self, 'combined_sidebar'):
            if hasattr(self, 'toggle_file_tree_action'):
                tree_vis = self.combined_sidebar.is_tree_visible()
                self.toggle_file_tree_action.setChecked(tree_vis)
                self.toggle_file_tree_action.setText(
                    'Hide File Tree' if tree_vis else 'Show File Tree'
                )
            if hasattr(self, 'toggle_preview_action'):
                preview_vis = self.combined_sidebar.is_preview_visible()
                self.toggle_preview_action.setChecked(preview_vis)
                self.toggle_preview_action.setText(
                    'Hide Preview' if preview_vis else 'Show Preview'
                )
        if hasattr(self, 'right_sidebar'):
            if hasattr(self, 'toggle_information_sidebar_action'):
                info_vis = self.right_sidebar.is_information_visible()
                self.toggle_information_sidebar_action.setChecked(info_vis)
                self.toggle_information_sidebar_action.setText(
                    'Hide Information Sidebar' if info_vis else 'Show Information Sidebar'
                )
            if hasattr(self, 'toggle_shortcuts_sidebar_action'):
                shortcuts_vis = self.right_sidebar.is_shortcuts_visible()
                self.toggle_shortcuts_sidebar_action.setChecked(shortcuts_vis)
                self.toggle_shortcuts_sidebar_action.setText(
                    'Hide Organize Sidebar' if shortcuts_vis else 'Show Organize Sidebar'
                )
            if hasattr(self, 'toggle_jobs_action'):
                jobs_vis = self.right_sidebar.is_jobs_visible()
                self.toggle_jobs_action.setChecked(jobs_vis)
                self.toggle_jobs_action.setText(
                    'Hide Jobs' if jobs_vis else 'Show Jobs'
                )

    def toggle_chrome(self):
        """F4: save and hide all chrome, or restore saved/default layout."""
        if self._is_any_chrome_visible():
            self._chrome_saved_layout = self._capture_chrome_layout()
            self._hide_all_chrome()
        elif self._chrome_saved_layout is not None:
            self._restore_chrome_layout(self._chrome_saved_layout)
        else:
            self._show_default_chrome()

    def toggle_status_bar(self):
        """Toggle status bar visibility and resize image display accordingly"""
        self._chrome_suppressed = False
        # Clear any active peek state so the user's explicit choice takes precedence
        self._status_bar_peek_active = False
        
        def _after_toggle_anim():
            self.config.update_setting('status_bar_visible', self.status_bar_visible)
            if hasattr(self, 'toggle_status_bar_action'):
                self.toggle_status_bar_action.setChecked(self.status_bar_visible)
                if self.status_bar_visible:
                    self.toggle_status_bar_action.setText('Hide Status Bar')
                else:
                    self.toggle_status_bar_action.setText('Show Status Bar')
            QTimer.singleShot(10, self.force_resize_recalculation)
            if hasattr(self, 'thumbnail_container') and hasattr(self.thumbnail_container, 'force_canvas_size_update'):
                QTimer.singleShot(20, self.thumbnail_container.force_canvas_size_update)
            if self.current_view_mode == 'browse' and self.current_pixmap:
                QTimer.singleShot(50, self._browse_after_chrome_layout_change)
        
        if self.status_bar.isVisible():
            self._animate_status_bar_hide(_after_toggle_anim)
        else:
            self._animate_status_bar_show(_after_toggle_anim)

    def _apply_right_sidebar_visibility(self):
        """Apply right sidebar visibility based on Organize, Information, or Jobs panes."""
        self.jobs_visible = self.right_sidebar.is_jobs_visible()
        self.right_sidebar_visible = (
            self.right_sidebar.is_information_visible()
            or self.right_sidebar.is_shortcuts_visible()
            or self.right_sidebar.is_jobs_visible()
        )
        self.filename_visible = self.right_sidebar_visible  # Keep for backward compatibility

        sizes = self.main_splitter.sizes()
        total_width = sum(sizes)
        left_width = sizes[0]

        if self.right_sidebar_visible:
            right_width = self.right_sidebar_width
            min_thumb_width = 200
            available_width = total_width - left_width - right_width
            if available_width < min_thumb_width:
                right_width = max(0, total_width - left_width - min_thumb_width)
                self.right_sidebar_width = right_width
            main_width = total_width - left_width - right_width
            self._set_splitter_sizes_safe([left_width, main_width, right_width])
            self.right_sidebar.show()
            if self.right_sidebar.is_information_visible():
                self.right_sidebar.show_info()
                if self.current_image_path:
                    self.right_sidebar.show_image_info_overlay()
            else:
                self.right_sidebar.hide_info()
        else:
            main_width = total_width - left_width
            self._set_splitter_sizes_safe([left_width, main_width, 0])
            self.right_sidebar.hide()
            self.right_sidebar.hide_info()

        self.config.update_setting('right_sidebar_visible', self.right_sidebar_visible)
        self.config.update_setting('right_sidebar_width', self.right_sidebar_width)

        if hasattr(self, 'toggle_information_sidebar_action'):
            self.toggle_information_sidebar_action.setChecked(self.right_sidebar.is_information_visible())
            self.toggle_information_sidebar_action.setText(
                'Hide Information Sidebar' if self.right_sidebar.is_information_visible() else 'Show Information Sidebar')
        if hasattr(self, 'toggle_shortcuts_sidebar_action'):
            self.toggle_shortcuts_sidebar_action.setChecked(self.right_sidebar.is_shortcuts_visible())
            self.toggle_shortcuts_sidebar_action.setText(
                'Hide Organize Sidebar' if self.right_sidebar.is_shortcuts_visible() else 'Show Organize Sidebar')
        if hasattr(self, 'toggle_jobs_action'):
            self.toggle_jobs_action.setChecked(self.jobs_visible)
            self.toggle_jobs_action.setText('Hide Jobs' if self.jobs_visible else 'Show Jobs')
        self.config.update_setting('jobs_visible', self.jobs_visible)

        if self.current_view_mode == 'browse':
            QTimer.singleShot(50, self._resize_browse_view_image_container)
        if self.current_view_mode == 'thumbnail':
            self.ui_layout_manager._immediate_splitter_update()
            self.ui_layout_manager.update_max_thumbnail_size()
            if not hasattr(self, '_splitter_resize_timer'):
                self._splitter_resize_timer = QTimer()
                self._splitter_resize_timer.setSingleShot(True)
                self._splitter_resize_timer.timeout.connect(self.update_layout_after_splitter_resize)
            self._splitter_resize_timer.stop()
            self._splitter_resize_timer.start(50)

    def toggle_information_display(self):
        """Toggle Information sidebar only (I key). visibility_changed triggers _apply_right_sidebar_visibility."""
        self._chrome_suppressed = False
        if hasattr(self.right_sidebar, 'set_information_visible'):
            self.right_sidebar.set_information_visible(not self.right_sidebar.is_information_visible())

    def toggle_shortcuts_display(self):
        """Toggle Shortcuts sidebar only (O key). visibility_changed triggers _apply_right_sidebar_visibility."""
        self._chrome_suppressed = False
        if hasattr(self.right_sidebar, 'set_shortcuts_visible'):
            self.right_sidebar.set_shortcuts_visible(not self.right_sidebar.is_shortcuts_visible())

    def update_filename_for_new_image(self):
        """Update detailed image info overlay for new image when toggled on."""
        if self.right_sidebar_visible and self.current_image_path:
            # Only update information overlay when Information section is visible
            if hasattr(self.right_sidebar, 'is_information_visible') and self.right_sidebar.is_information_visible():
                self.right_sidebar.show_image_info_overlay()
        # Refresh number overlay when image changes
        self.update_number_overlay()


    def reset_image_transformations(self):
        """Reset all image transformations"""
        if not self.current_image_path:
            return
        
        # Store current image path before clearing transformations
        image_path_to_refresh = self.current_image_path
        
        # Clear transformations for current image
        if self.current_image_path in self.image_transformations:
            del self.image_transformations[self.current_image_path]
        
        # Reset display
        self.scale_factor = 1.0
        self.scroll_x = 0
        self.scroll_y = 0
        self.update_image_display()
        
        # Refresh thumbnail for the current image (even though transformation was removed)
        # This ensures the thumbnail reflects the reset transformation
        if hasattr(self, 'thumbnail_container') and hasattr(self.thumbnail_container, 'canvas'):
            canvas = self.thumbnail_container.canvas
            # Find the thumbnail for the current image
            for thumbnail in canvas.thumbnails:
                if thumbnail.image_path == image_path_to_refresh:
                    # Clear cache for this image to force fresh thumbnail generation
                    if getattr(self, 'cache_manager', None):
                        self.cache_manager.clear_thumbnails_for_file(image_path_to_refresh)
                    
                    # Reset loading state and clear pixmap
                    thumbnail.is_loading = True
                    thumbnail.pixmap = None
                    
                    # Request new thumbnail (will be loaded without transformations)
                    if getattr(self, 'cache_manager', None):
                        self.cache_manager.get_thumbnail_async(
                            image_path_to_refresh,
                            self.current_thumbnail_size,
                            priority=1
                        )
                    break
        
        # Also call the general refresh method for any other transformed thumbnails
        self.refresh_thumbnails_for_transformation()
        
        # Update preview widget if it exists (force update even if temporarily hidden)
        if hasattr(self, 'preview_widget'):
            self.preview_widget.update_preview(force=True)
        
        if self.status_notification:
            self.status_notification.show_message("Image transformations reset")

    def apply_transformations_to_pixmap(self, pixmap: QPixmap, image_path: str = None) -> QPixmap:
        """Apply stored transformations to a pixmap"""
        # Use provided image_path or fall back to current_image_path
        target_path = image_path or self.current_image_path
        if not target_path or target_path not in self.image_transformations:
            return pixmap
        
        rotation, flip_h, flip_v = self.image_transformations[target_path]
        
        # Apply transformations
        transform = QTransform()
        
        if rotation != 0:
            transform.rotate(rotation)
        
        if flip_h:
            transform.scale(-1, 1)
        
        if flip_v:
            transform.scale(1, -1)
        
        if not transform.isIdentity():
            result = pixmap.transformed(transform, Qt.SmoothTransformation)
            return result
        
        return pixmap

    def _handle_resize(self):
        """Handle resize after delay"""
        if self.current_view_mode == 'thumbnail':
            # Skip thumbnail rebuild if we're in the middle of a fullscreen exit
            # The highlight should already be set correctly by the time this is called
            # CRITICAL: Reset the flag here to avoid needing another timer call (which causes GIL deadlock)
            if getattr(self, 'browse_view_exit_in_progress', False):
                self.browse_view_exit_in_progress = False
                return
                
            # Always recalculate thumbnail size on resize to ensure proper dynamic sizing
            # This fixes the core issue where thumbnails don't resize properly
            self.set_dynamic_thumbnail_size()
            # Set resize in progress flag to preserve loaded thumbnails during resize
            self._resize_in_progress = True
            self.generate_thumbnails(force_refresh=False)

            # Schedule completion callback
            QTimer.singleShot(200, self._on_resize_complete)
        elif self.current_view_mode == 'browse':
            # Update fullscreen display
            self.update_image_display()
            # Ensure overlays reposition correctly on resize
            self.update_number_overlay()
    
    def force_resize_recalculation(self):
        """Force a resize recalculation regardless of current state"""
        if self.current_view_mode == 'thumbnail' and self.thumbnail_container.canvas.thumbnails:
            # Set resize in progress flag
            self._resize_in_progress = True
            # Regenerate thumbnails with new grid layout
            # Don't use force_refresh=True to preserve loaded pixmaps during resize
            self.generate_thumbnails(force_refresh=False)
            # Schedule completion callback
            QTimer.singleShot(200, self._on_resize_complete)
        elif self.current_view_mode == 'browse' and self.current_pixmap:
            # Handle fullscreen mode resize - force recalculation of image display
            old_w = self.cached_container_width
            old_h = self.cached_container_height
            if hasattr(self, 'image_container'):
                available_size = self.get_effective_display_size()
                self.image_container.resize(available_size)
            self._handle_browse_viewport_resize_after_container_change(old_w, old_h)
            return
        
        # Cache container dimensions after any resize recalculation
        display_size = self.get_effective_display_size()
        self.cached_container_width = display_size.width()
        self.cached_container_height = display_size.height()


    def changeEvent(self, event):
        """Handle window state changes, including fullscreen transitions"""
        super().changeEvent(event)
        
        # Handle transition to/from OS fullscreen mode
        if event.type() == QEvent.WindowStateChange:
            # Update macOS fullscreen checkbox state
            self.menu_manager.update_native_fullscreen_checkbox()
            
            if self.isFullScreen() and self.current_view_mode == 'browse':
                # Window just entered OS fullscreen mode, but window size and layout may not be updated yet
                # Ensure sidebars are hidden and layout is updated before recalculating
                def update_image_for_fullscreen():
                    if self.isFullScreen() and self.current_view_mode == 'browse':
                        # Ensure sidebars are properly hidden for browse mode
                        if hasattr(self, 'combined_sidebar'):
                            self.combined_sidebar.hide()
                        self.manage_sidebar_visibility_for_view_mode('browse')
                        
                        # Force layout update to ensure splitter and widgets have correct sizes
                        if hasattr(self, 'main_splitter'):
                            self.main_splitter.updateGeometry()
                        if hasattr(self, 'main_content_widget'):
                            self.main_content_widget.updateGeometry()
                        
                        # NOTE: processEvents() was removed here because calling it inside a QTimer
                        # callback creates a nested event loop. If another pending timer fires inside
                        # that nested loop and calls QTimer.singleShot() with a Python lambda while
                        # ThumbnailWorkerThreads are contending for the GIL, drop_gil() in
                        # PySide::qobjectConnectCallback deadlocks against take_gil() in all workers.
                        # The 200ms delay above is sufficient for Qt's layout system to have updated;
                        # get_effective_display_size() reads self.size() directly in fullscreen mode.
                        
                        # Now get the effective display size after layout has updated
                        if hasattr(self, 'image_container'):
                            available_size = self.get_effective_display_size()
                            self.image_container.resize(available_size)
                        old_w = self.cached_container_width
                        old_h = self.cached_container_height
                        self._handle_browse_viewport_resize_after_container_change(old_w, old_h)
                
                # Delay to ensure window has finished transitioning to fullscreen size
                # Use longer delay to allow sidebar hiding and layout updates to complete
                QTimer.singleShot(200, update_image_for_fullscreen)

    def resizeEvent(self, event):
        """Handle window resize events"""
        super().resizeEvent(event)
        # Skip redundant work when size unchanged (e.g. force_resize_event during browse exit).
        # Layout was already updated by _immediate_splitter_update from VIEW_MODE_CHANGED.
        if event.size() == event.oldSize():
            if getattr(self, 'browse_view_exit_in_progress', False):
                self.browse_view_exit_in_progress = False
            return
        # Update MAX_THUMBNAIL_SIZE based on new container dimensions
        self.ui_layout_manager.update_max_thumbnail_size()
        
        # Reposition progress bars on resize
        self._position_progress_bars()
        
        # Handle browse mode resize immediately for responsive behavior
        if self.current_view_mode == 'browse' and self.current_pixmap:
            old_w = self.cached_container_width
            old_h = self.cached_container_height
            if hasattr(self, 'image_container'):
                available_size = self.get_effective_display_size()
                self.image_container.resize(available_size)
            self._handle_browse_viewport_resize_after_container_change(old_w, old_h)
            return  # Skip the delayed resize handling for browse mode
        
        # Delay resize handling to avoid multiple rapid calls for thumbnail mode
        if hasattr(self, '_resize_timer'):
            self._resize_timer.stop()
        else:
            self._resize_timer = QTimer()
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._handle_resize)
        
        # Use longer delay for larger numbers of files to avoid overwhelming the system
        delay = 100 if len(self.displayed_images) <= 100 else 300
        self._resize_timer.start(delay)
    
    def wheelEvent(self, event):
        """Handle mouse wheel events with cursor-aware zoom and trackpad panning"""
        if self.current_view_mode == 'browse':
            # Check if Control key is held (Cmd on macOS)
            modifiers = event.modifiers()
            if modifiers & Qt.ControlModifier:
                # Perform cursor-aware zoom
                delta = event.angleDelta().y()
                if delta != 0:
                    # Calculate zoom factor based on wheel delta
                    zoom_factor = 1.15 if delta > 0 else (1.0 / 1.15)
                    new_scale = max(0.1, min(8.0, self.scale_factor * zoom_factor))
                    
                    # Get mouse position and convert to coordinates relative to the image content
                    mouse_pos = event.position()
                    zoom_point = self._convert_cursor_to_image_coordinates(mouse_pos)
                    
                    # Apply cursor-aware zoom
                    self.zoom_at_point(new_scale, zoom_point)
                    
                    # Show status notification for zoom level
                    if self.status_notification:
                        zoom_percent = int(self.scale_factor * 100)
                        self.status_notification.show_message(f"Zoom: {zoom_percent}%", duration=1000)
                    
                    event.accept()
                    return
            elif (getattr(self, 'browse_view_handler', None) and 
                  self.browse_view_handler.can_pan_image()):
                # Handle trackpad panning when displayed image is larger than viewport (no modifier keys)
                # On macOS, trackpad pan gestures generate wheel events
                # Prefer pixelDelta for smoother trackpad panning, fallback to angleDelta
                pixel_delta = event.pixelDelta()
                if not pixel_delta.isNull():
                    # Use pixelDelta for precise trackpad panning
                    delta_x = pixel_delta.x()
                    delta_y = pixel_delta.y()
                else:
                    # Fallback to angleDelta for mouse wheel or older trackpads
                    delta_x = event.angleDelta().x()
                    delta_y = event.angleDelta().y()
                
                # Only handle panning if there's actual delta
                if delta_x != 0 or delta_y != 0:
                    # Apply pan offset based on wheel delta
                    # Invert the delta to match natural panning direction
                    pan_speed = 1.0  # Adjust this multiplier if panning feels too fast/slow
                    self.scroll_x -= delta_x * pan_speed
                    self.scroll_y -= delta_y * pan_speed
                    
                    # Update image position
                    if getattr(self, 'browse_view_handler', None):
                        self.browse_view_handler.apply_pan_offset()
                    
                    event.accept()
                    return
        else:
            # Pass through to parent for non-browse modes
            super().wheelEvent(event)

    def event(self, event):
        """Handle general events including gesture events and key events before shortcuts"""
        if hasattr(event, 'type') and event.type() == QEvent.Gesture:
            return self.gestureEvent(event)
        
        # Intercept E, H, PageUp, and PageDown keys before Qt processes QAction shortcuts
        if event.type() == QEvent.KeyPress and isinstance(event, QKeyEvent):
            # Handle Control+number keys for favorites (Ctrl+1 through Ctrl+9)
            # On macOS, Qt.MetaModifier is the actual Control key (not Command)
            # Qt.ControlModifier is the Command key (⌘) on macOS
            modifiers = event.modifiers()
            has_meta = bool(modifiers & Qt.MetaModifier)
            has_control = bool(modifiers & Qt.ControlModifier)
            has_shift = bool(modifiers & Qt.ShiftModifier)
            has_alt = bool(modifiers & Qt.AltModifier)
            key = event.key()
            
            # Only handle if MetaModifier (Control) is pressed and no other modifiers
            if has_meta and not has_control and not has_shift and not has_alt:
                # Check if it's a number key (1-9)
                if key in (Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4, Qt.Key_5, 
                          Qt.Key_6, Qt.Key_7, Qt.Key_8, Qt.Key_9):
                    # Try to handle through keyboard handler
                    if getattr(self, 'keyboard_handler_manager', None):
                        result = self.keyboard_handler_manager.handle_key_event(event)
                        if result:
                            return True  # Event handled
            
            if event.key() in (Qt.Key_E, Qt.Key_H, Qt.Key_PageUp, Qt.Key_PageDown) and event.modifiers() == Qt.NoModifier:
                # Check if we're in thumbnail or list mode and should handle these keys
                current_view_mode = getattr(self, 'current_view_mode', None)
                stacked_index = self.stacked_widget.currentIndex() if hasattr(self, 'stacked_widget') else None
                is_list_view = (current_view_mode == 'list') or (stacked_index == 2)
                is_thumbnail_view = (current_view_mode == 'thumbnail')
                
                if ((is_thumbnail_view or is_list_view) and
                    getattr(self, 'keyboard_handler_manager', None)):
                    # Try to handle the event through our keyboard handler
                    result = self.keyboard_handler_manager.handle_key_event(event)
                    if result:
                        return True  # Event handled, don't process shortcuts

            # Shift+H = select from first to current (before QAction shortcuts; same as Shift+Home)
            if event.key() == Qt.Key_H and has_shift and not has_control and not has_meta and not has_alt:
                current_view_mode = getattr(self, 'current_view_mode', None)
                stacked_index = self.stacked_widget.currentIndex() if hasattr(self, 'stacked_widget') else None
                is_list_view = (current_view_mode == 'list') or (stacked_index == 2)
                is_thumbnail_view = (current_view_mode == 'thumbnail')
                if ((is_thumbnail_view or is_list_view) and
                    getattr(self, 'keyboard_handler_manager', None)):
                    result = self.keyboard_handler_manager.handle_key_event(event)
                    if result:
                        return True
            
            # Handle cmd-shift-return BEFORE shortcuts are processed
            # This prevents Qt from intercepting it as a shortcut
            if event.key() in [Qt.Key_Return, Qt.Key_Enter]:
                cmd_shift = (has_shift and (has_control or has_meta))
                if cmd_shift:
                    # Handle cmd-shift-return directly: expand file tree
                    if getattr(self, 'file_tree_handler', None):
                        self.file_tree_handler.expand_file_tree()
                        return True  # Event handled, stop propagation")
                    # Don't return True - let it propagate to keyPressEvent handlers
                    # The tree or thumbnail canvas will handle it
            
            # Handle shift-cmd-L (unlock) BEFORE shortcuts are processed
            # This ensures unlock always works via keyboard handler, even when menu item is hidden
            if event.key() == Qt.Key_L and has_shift and (has_control or has_meta) and not has_alt:
                if (getattr(self, 'keyboard_handler_manager', None) and
                    getattr(self, 'current_view_mode', None) == 'thumbnail'):
                    result = self.keyboard_handler_manager.handle_key_event(event)
                    if result:
                        return True  # Event handled, stop propagation
            
            # Handle cmd-shift-D (toggle debug mode) BEFORE shortcuts are processed
            # This prevents Qt from intercepting it as a shortcut
            if event.key() == Qt.Key_D and has_shift and (has_control or has_meta) and not has_alt:
                self.toggle_debug_mode()
                return True  # Event handled, stop propagation
            
            # Handle cmd-C (copy path) when tree has focus BEFORE shortcuts are processed
            if event.key() == Qt.Key_C and (has_control or has_meta) and not has_shift and not has_alt:
                # Check if tree has focus using the helper method
                if self._tree_has_focus():
                    # Tree has focus - get selected path from tree selection model
                    if (getattr(self, 'file_tree_handler', None) and
                        hasattr(self.file_tree_handler, 'file_tree') and self.file_tree_handler.file_tree):
                        tree = self.file_tree_handler.file_tree
                        selection = tree.selectionModel().selectedIndexes()
                        if selection:
                            index = selection[0]
                            model = tree.model()
                            if model:
                                source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                                selected_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                                
                                if selected_path and os.path.exists(selected_path):
                                    # Copy path to clipboard
                                    try:
                                        display_path = normalize_path_for_display(selected_path)
                                        clipboard = QApplication.clipboard()
                                        clipboard.setText(display_path)
                                        if hasattr(self, 'status_notification'):
                                            self.status_notification.show_message(
                                                f"Copied to clipboard: {os.path.basename(selected_path)}")
                                        return True  # Event handled, stop propagation
                                    except Exception:
                                        # If copy fails, let Qt handle it normally
                                        pass
        
        return super().event(event)
    
    def _position_progress_bars(self):
        """Position progress bar at bottom right 50% of screen with 25px margin from bottom"""
        if not hasattr(self, 'progress_bar'):
            return
            
        # Get window dimensions
        window_width = self.width()
        window_height = self.height()
        
        # Calculate positions with 25px margin from bottom
        bottom_margin = 25
        progress_height = 20
        
        # Position progress bar on right 50% of screen
        progress_width = window_width // 2
        progress_x = window_width - progress_width  # Start from right side
        
        self.progress_bar.resize(progress_width, progress_height)
        self.progress_bar.move(progress_x, window_height - bottom_margin - progress_height)
        
        # Ensure progress bar is on top
        if self.progress_bar.isVisible():
            self.progress_bar.raise_()
    
    def _on_resize_complete(self):
        """Called when resize processing is complete"""
        self._resize_in_progress = False
        
    def enable_macos_fullscreen_button(self):
        """Enable macOS native fullscreen button"""
        self.browse_view_handler.enable_macos_fullscreen_button()

    def reset_browse_view_exit_tracking(self):
        """Reset fullscreen exit tracking state"""
        self.browse_view_handler.reset_browse_view_exit_tracking()

















    def _center_image_label(self):
        """Center the image label in the container"""
        self.browse_view_handler.center_image_label()

    def _convert_cursor_to_image_coordinates(self, cursor_pos: QPointF) -> QPointF:
        """
        Convert cursor position from main window coordinates to coordinates relative to the image content.
        The cursor position is relative to the main window, but we need coordinates relative to the main content area.
        """
        return self.browse_view_handler.convert_cursor_to_image_coordinates(cursor_pos)



    def _refresh_browse_view_display(self):
        """Refresh fullscreen display"""
        self.browse_view_handler.refresh_browse_view_display()

    def on_metadata_ready(self, path: str, metadata):
        """Handle metadata ready event"""
        # Find and update corresponding widget
        widget = self.find_widget_by_path(path)
        if widget and hasattr(widget, 'on_metadata_ready'):
            widget.on_metadata_ready(metadata)

    def on_fullimage_ready(self, path: str):
        """Handle full image ready event"""
        # Update fullscreen display if this is the current image
        if (self.current_view_mode == 'browse' and 
            self.current_image_path == path):
            self.update_image_display()

    def on_thumbnail_ready(self, path: str, pixmap: QPixmap, size: int):
        """Handle thumbnail ready event - forward to canvas if available"""
        # Validate that this path is still in displayed_images to prevent stale callbacks
        # This is the primary check - works for both directory mode and specific files mode
        try:
            if not hasattr(self, 'displayed_images') or path not in self.displayed_images:
                return  # Path is no longer relevant, ignore this callback
        except (AttributeError, RuntimeError):
            # displayed_images might be in inconsistent state during directory switch
            # Let the canvas handle the validation as it has better context
            pass
        
        # Additional validation: directory match check (only for normal directory mode)
        # Skip this check in specific_files_active mode since files can be from multiple directories
        try:
            if (not getattr(self, 'specific_files_active', False) and 
                getattr(self, 'current_directory', None)):
                path_dir = os.path.dirname(os.path.abspath(path))
                current_dir = os.path.abspath(self.current_directory)
                if path_dir != current_dir:
                    return  # Path is from a different directory, ignore this stale callback
        except (AttributeError, RuntimeError, OSError):
            # If we can't validate directory, continue - displayed_images check above is sufficient
            pass
        
        # Forward to canvas for canvas-based thumbnail system
        # The canvas will do additional validation against its thumbnails list
        if hasattr(self, 'thumbnail_container') and hasattr(self.thumbnail_container, 'canvas'):
            self.thumbnail_container.canvas.on_thumbnail_loaded(path, pixmap, size)

    def refresh_thumbnails_for_transformation(self):
        """Refresh thumbnails to show transformations"""
        # Handle canvas-based thumbnail system
        if self.thumbnail_container.canvas.thumbnails:
            self._refresh_canvas_thumbnails_for_transformation()
    
    def _refresh_canvas_thumbnails_for_transformation(self):
        """Refresh canvas thumbnails to show session transforms (same logic as browse view)."""
        canvas = self.thumbnail_container.canvas
        cache_manager = getattr(self, 'cache_manager', None)
        if not cache_manager:
            return

        thumbnails_to_refresh = [
            t for t in canvas.thumbnails
            if t.image_path in self.image_transformations
        ]
        if not thumbnails_to_refresh:
            return

        size = self.current_thumbnail_size
        updated = False
        for thumbnail in thumbnails_to_refresh:
            base = cache_manager.get_thumbnail_sync(thumbnail.image_path, size)
            if base is None or base.isNull():
                thumbnail.is_loading = True
                thumbnail.pixmap = None
                cache_manager.get_thumbnail_async(thumbnail.image_path, size, priority=1)
                continue
            thumbnail.pixmap = self.apply_transformations_to_pixmap(
                base, thumbnail.image_path
            )
            thumbnail.is_loading = False
            updated = True

        if updated:
            canvas.needs_repaint = True
            canvas.update()

    def debug_cache_status(self):
        """Debug cache status"""
        if self.cache_manager:
            try:
                cache_info = self.cache_manager.get_cache_info()
                if cache_info:
                    # Format the cache info for display
                    thumbnail_count = cache_info.get('thumbnail_count', 0)
                    metadata_count = cache_info.get('metadata_count', 0)
                    fullimage_count = cache_info.get('fullimage_count', 0)
                    
                    # Get hit rates from stats
                    stats = cache_info.get('stats', {})
                    thumbnail_hit_rate = stats.get('thumbnail_hit_rate', 'N/A')
                    
                    status_msg = f"Cache: {thumbnail_count} thumbnails, {metadata_count} metadata, {fullimage_count} full images, Hit rate: {thumbnail_hit_rate}"
                    
                    if self.status_notification:
                        self.status_notification.show_message(status_msg)
                else:
                    if self.status_notification:
                        self.status_notification.show_message("Cache status: No info available")
            except Exception as e:
                if self.status_notification:
                    self.status_notification.show_message(f"Cache status error: {str(e)}")

    def toggle_debug_mode(self):
        """Toggle debug mode"""
        self.debug_mode = not self.debug_mode
        if self.debug_mode:
            set_popup_callback(self.show_key_popup)
        else:
            set_popup_callback(None)
            self.key_popup_label.setVisible(False)
        
        self.config.update_setting('debug_mode', self.debug_mode)
        
        # Notify background worker about debug mode change
        if getattr(self, 'background_clip_controller', None):
            self.background_clip_controller.update_debug_mode()
        
        if self.status_notification:
            status = "enabled" if self.debug_mode else "disabled"
            self.status_notification.show_message(f"Debug mode {status}")

    def undo_file_operation(self):
        """Undo last file operation (file deletion or wallpaper change)"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.undo_file_operation()
        
    
    def _handle_successful_restore(self, original_path, original_position=None):
        """Handle successful file restoration from AppleScript fallback"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager._handle_successful_restore(original_path, original_position)

    def restore_file_from_trash_(self, original_path, original_position=None, show_status=True):
        """Restore file from trash (undo operation)"""
        if getattr(self, 'file_operations_manager', None):
            return self.file_operations_manager.restore_file_from_trash_(original_path, original_position, show_status)
        return False

    def _on_thumbnail_loaded_from_worker(self, path, pixmap):
        """Handle thumbnail loaded signal from background worker"""
        self.thumbnail_display_manager.on_thumbnail_loaded_from_worker(path, pixmap)

    def _on_thumbnail_worker_finished(self):
        """Handle thumbnail loading finished signal from background worker"""
        self.thumbnail_display_manager.on_thumbnail_worker_finished()

    def _on_thumbnail_worker_error(self):
        """Handle thumbnail loading error signal from background worker"""
        self.thumbnail_display_manager.on_thumbnail_worker_error()

    def _on_thumbnail_progress_updated(self, completed, total, _):
        """Handle thumbnail loading progress updates"""
        self.thumbnail_display_manager.on_thumbnail_progress_updated(completed, total, _)


    def create_immediate_placeholders(self):
        """Create placeholder thumbnails immediately for instant UI response when exiting fullscreen"""
        if not self.displayed_images:
            return
        
        num_images = len(self.displayed_images)
        
        # Check if canvas already exists and has thumbnails
        canvas = self.thumbnail_container.canvas
        
        if canvas.thumbnails and len(canvas.thumbnails) > 0:
            # Check if paths match - if so, skip all expensive work
            current_paths = [thumb.image_path for thumb in canvas.thumbnails]
            if current_paths == self.displayed_images:
                # Paths match - canvas is already correct, just update highlight and return
                # This makes returning from browse mode instant when canvas already exists
                if self.displayed_images:
                    if not (0 <= self.highlight_index < len(self.displayed_images)):
                        self.highlight_index = 0
                    self.thumbnail_container.set_highlighted_index(self.highlight_index)
                    self.ensure_highlighted_visible()
                return
            
            # Paths don't match - use reorder_thumbnails to preserve loaded pixmaps
            # Use canvas approach if canvas is available (regardless of image count)
            self.current_thumbnail_size, _, _ = self.thumbnail_operations_manager.calculate_grid_for_images(num_images)
            # Don't force grid recalculation unless necessary - let the smart rebuild logic decide
            canvas.reorder_thumbnails(self.displayed_images, force_recalculate_grid=False)
        else:
            # Canvas is empty - set thumbnails on canvas (this creates placeholders immediately)
            self.current_thumbnail_size, _, _ = self.thumbnail_operations_manager.calculate_grid_for_images(num_images)
            self.thumbnail_container.set_thumbnails(self.displayed_images, self.current_thumbnail_size)
            
        # Set initial highlight - preserve existing highlight_index if it's valid
        if self.displayed_images:
            if not (0 <= self.highlight_index < len(self.displayed_images)):
                self.highlight_index = 0
            self.thumbnail_container.set_highlighted_index(self.highlight_index)
            
            # Ensure the highlighted thumbnail is visible after placeholders are created
            self.ensure_highlighted_visible()
            
            # Start background loading
            self.start_background_thumbnail_loading_if_needed()
            
            return
        
        # For large numbers of images, use a more efficient approach
        if num_images > 1000:
            # Use the existing canvas system which is optimized for large numbers
            self.current_thumbnail_size, _, _ = self.thumbnail_operations_manager.calculate_grid_for_images(num_images)
            
            # Check if canvas already has thumbnails - if so, use reorder_thumbnails to preserve loaded pixmaps
            canvas = self.thumbnail_container.canvas
            
            if canvas.thumbnails and len(canvas.thumbnails) > 0:
                # Use reorder_thumbnails to preserve existing loaded thumbnails
                # Don't force grid recalculation unless necessary - let the smart rebuild logic decide
                canvas.reorder_thumbnails(self.displayed_images, force_recalculate_grid=False)
            else:
                # Set thumbnails on canvas (this creates placeholders immediately)
                self.thumbnail_container.set_thumbnails(self.displayed_images, self.current_thumbnail_size)
            
        # Set initial highlight - preserve existing highlight_index if it's valid
        if self.displayed_images:
            if not (0 <= self.highlight_index < len(self.displayed_images)):
                self.highlight_index = 0
            self.thumbnail_container.set_highlighted_index(self.highlight_index)
            
            # Ensure the highlighted thumbnail is visible after placeholders are created
            self.ensure_highlighted_visible()
            
            # Start background loading
            self.start_background_thumbnail_loading_if_needed()
            return
        
        # For smaller sets, use the traditional widget approach
        
        # Clear any existing thumbnails
        self.clear_thumbnails()
        
        # Calculate grid layout
        self.current_thumbnail_size, _, _ = self.thumbnail_operations_manager.calculate_grid_for_images(num_images)
        
        # Create all placeholder widgets immediately (no batching delays)
 
         
        # Start background thumbnail loading immediately (no delays)
        self.start_background_thumbnail_loading_if_needed()
        
        # Set initial highlight
        if self.displayed_images:
            self.highlight_index = 0
            self.highlight_image()
            # Ensure the highlighted thumbnail is visible after placeholders are created
            self.ensure_highlighted_visible()

    def _check_and_open_last_known_directory(self):
        """Check if we should automatically open the last known directory when no thumbnails are displayed"""
        # Only proceed if we're in thumbnail mode
        if self.current_view_mode != 'thumbnail':
            return
        
        # Get the last known directory from the most recently highlighted image
        last_known_directory = self._get_last_known_directory()
        if not last_known_directory:
            return
        
        # Check if the directory exists and has image files
        if not os.path.exists(last_known_directory):
            return
        
        # Check if there are image files in the directory
        try:
            files = os.listdir(last_known_directory)
            image_extensions = get_image_extensions()
            image_files = [f for f in files if os.path.splitext(f.lower())[1] in image_extensions]
            if not image_files:
                return
        except (OSError, PermissionError):
            return
        
        # Add a small delay to prevent infinite loops and allow UI to settle
        QTimer.singleShot(100, lambda: self._open_last_known_directory(last_known_directory))
    
    def _get_last_known_directory(self):
        """Get the last known directory from the currently highlighted file"""
        return self._current_highlighted_file_directory
    
    def _open_last_known_directory(self, directory):
        """Open the last known directory (simulate cmd-O)"""
        # Prevent infinite loops by checking if we're already in the process of opening a directory
        if getattr(self, '_opening_last_directory', None):
            return
        
        # Set flag to prevent loops
        self._opening_last_directory = True
        
        try:
            # Save current state before opening new directory
            self.directory_stack_history_handler.save_current_state("image_browser_window._open_last_known_directory")
            
            # Preserve current limits and filters (don't clear them)
            # Load the directory with current settings
            self.load_directory(directory)
            
            # Update file tree root
            if self.file_tree_handler.is_tree_initialized():
                self.file_tree_handler.update_root_directory(directory)
                
        except Exception:
            pass
        finally:
            # Clear the flag after a delay to allow the directory loading to complete
            QTimer.singleShot(1000, lambda: setattr(self, '_opening_last_directory', False))
    def browse_trash_images(self):
        """Browse images in macOS Trash (~/.Trash/)"""
        if getattr(self, 'file_operations_manager', None):
            self.file_operations_manager.browse_trash_images()

    def update_file_menu_can_view_trash(self):
        """Update the File menu to show/hide the Trash action based on whether trash images can be viewed"""
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_file_menu_can_view_trash()



    # def mouseReleaseEvent(self, event):
    #     """Emit clicked only if no drag occurred."""
    #     print(f"{RED}USED Module: {RESET}: {RED}image_browser_window.mouseReleaseEvent{RESET} called from {GREEN}{inspect.stack()[1].function}{RESET}") 
    #     if event.button() == Qt.LeftButton:
    #         if False and (not hasattr(self, '_dragging') or not self._dragging):
    #             modifiers = QApplication.keyboardModifiers()
    #             # Check for both Control and Meta modifiers for cmd-click support
    #             # ControlModifier and MetaModifier both work on macOS
    #             cmd_pressed = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))
    #             shift_pressed = bool(modifiers & Qt.ShiftModifier)
    #             self.clicked.emit(self.index, cmd_pressed, shift_pressed)
    #         self._dragging = False
    #         self._drag_start_pos = None
    #         event.accept()
    #     elif event.button() == Qt.RightButton:
    #         print(f"{RED} RIGHT CLICK RELEASED image_browser_window.mouseReleaseEvent{RESET}")
    #         self.view_manager.close_browse_view()
    #     else:
    #         super().mouseReleaseEvent(event)

    # def mouseMoveEvent(self, event):
    #     """Initiate internal drag when movement exceeds threshold."""
    #     if not hasattr(self, '_drag_start_pos') or self._drag_start_pos is None:
    #         return
        
    #     # Check for modifier keys - be more permissive for cmd/ctrl clicks
    #     mods = event.modifiers()
    #     cmd_pressed = bool(mods & (Qt.ControlModifier | Qt.MetaModifier))
    #     shift_pressed = bool(mods & (Qt.ShiftModifier))
        
    #     # Use a higher threshold when modifier keys are pressed to allow for modifier clicks
    #     if cmd_pressed or shift_pressed:
    #         threshold = max(10, QApplication.startDragDistance() + 5)
    #     else:
    #         threshold = max(3, QApplication.startDragDistance() - 2)
        
    #     current = event.position() if hasattr(event, 'position') else event.pos()
    #     try:
    #         # QPointF - QPointF supports subtraction for manhattanLength via toPoint
    #         distance = (current - self._drag_start_pos).manhattanLength()
    #     except Exception:
    #         delta = current.toPoint() - self._drag_start_pos.toPoint() if hasattr(current, 'toPoint') else current - self._drag_start_pos
    #         distance = abs(delta.x()) + abs(delta.y())
        
    #     if distance < threshold:
    #          return
    #     # Begin drag
    #     if not self._dragging:
    #         self.grabMouse()
    #     self._start_internal_drag()
    #     self._dragging = False
    #     self.releaseMouse()
    #     event.accept()

    def _start_internal_drag(self):
        """Start internal drag with MIME data compatible with container."""
        # Prepare MIME
        mime = QMimeData()
        # Determine selection context from main window if available
        main_window = self.parent()
        while main_window and not hasattr(main_window, 'multi_select_mode'):
            main_window = main_window.parent()
        
        mime.setData('application/x-imagebrowser-path', self.image_path.encode('utf-8'))
        # Execute drag
        drag = QDrag(self)
        drag.setMimeData(mime)
        try:
            if self.pixmap and not self.pixmap.isNull():
                drag.setPixmap(self.pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                drag.setHotSpot(QPoint(32, 32))
        except Exception:
            pass
        drag.exec(Qt.MoveAction)
    
    
    def eventFilter(self, obj, event):
        """Event filter to catch keyboard events when main window has NoFocus, and F2 for thumbnail rename"""
        
        if event.type() == QEvent.KeyPress:
            # Handle F2 for thumbnail rename when main_content_widget has focus (thumbnail view)
            if obj == getattr(self, 'main_content_widget', None):
                if (isinstance(event, QKeyEvent) and event.key() == Qt.Key_F2 and not event.modifiers() and
                    getattr(self, 'current_view_mode', None) == 'thumbnail' and
                    getattr(self, 'thumbnail_container', None) and
                    hasattr(self.thumbnail_container, 'canvas')):
                    canvas = self.thumbnail_container.canvas
                    index = None
                    if getattr(self, 'highlight_index', None) is not None:
                        index = self.highlight_index
                    elif hasattr(canvas, 'highlighted_index') and 0 <= canvas.highlighted_index < len(canvas.thumbnails):
                        index = canvas.highlighted_index
                    if index is not None and 0 <= index < len(canvas.thumbnails):
                        canvas._start_inline_rename(index)
                        return True  # Event handled

            # Only handle keyboard events if the main window doesn't have focus
            # This prevents double processing when the main window receives the event normally
            has_focus = self.hasFocus()
            if not has_focus:
                result = self.keyPressEvent(event)
                if result:
                    return True  # Event handled
                else:
                    return super().eventFilter(obj, event)
            else:
                return super().eventFilter(obj, event)
        return super().eventFilter(obj, event)
    
    def focusInEvent(self, event):
        super().focusInEvent(event)
    
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
    
    def showEvent(self, event):
        """Handle window show event"""
        super().showEvent(event)
        # Ensure proper focus when window is shown - set immediately and also after short delay
        # This ensures menu keys work right away
        self._ensure_proper_focus()
        QTimer.singleShot(50, self._ensure_proper_focus)
    
    def _ensure_proper_focus(self):
        """Ensure proper focus is set after window is shown - always prefer canvas"""
        # Ensure menu states are initialized
        if hasattr(self, 'menu_manager'):
            try:
                self.menu_manager.initialize_menu_states()
            except Exception:
                pass
        
        # Ensure undo action shortcut is registered after window is shown
        # This fixes the issue where Cmd+Z doesn't work until menu is shown
        if getattr(self, 'undo_action', None):
            # Re-register shortcut to ensure it's active (matches copy_path_action behavior)
            self.undo_action.setShortcut(QKeySequence("Ctrl+Z"))
            self.undo_action.setEnabled(True)
        
        # Ensure quick mass rename action shortcut is registered after window is shown
        # This fixes the issue where Ctrl+Shift+M doesn't work until menu is shown
        if getattr(self, 'quick_mass_rename_action', None):
            # Re-register shortcut to ensure it's active
            self.quick_mass_rename_action.setShortcut(QKeySequence("Ctrl+Shift+M"))
            self.quick_mass_rename_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            # Respect the setting - enabled state is managed by update_tools_menu_states()
            if getattr(self, 'menu_manager', None):
                self.menu_manager.update_tools_menu_states()
        # Ensure screen copy shortcut is registered (app-level filter also handles it when action disabled)
        if getattr(self, 'screen_copy_last_used_action', None):
            self.screen_copy_last_used_action.setShortcut(QKeySequence("Ctrl+Shift+U"))
            self.screen_copy_last_used_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if getattr(self, 'menu_manager', None):
            self.menu_manager.update_tools_menu_states()
        
        # Set focus on main content widget (thumbnail or browse mode)
        focused_widget = QApplication.focusWidget()
        if not focused_widget or focused_widget != self.main_content_widget:
            self.focus_canvas()
        
        # Ensure window has focus so menu shortcuts work
        self.activateWindow()
        self.raise_()
    
    

