#!/usr/bin/env python3
"""
Centralized constants for thumbnail layout calculations.
All hardcoded layout values should be defined here to ensure consistency.
"""

from typing import Set, List
import os

from cache.idle_and_cache_constants import (
    BACKGROUND_CLIP_IDLE_TIMEOUT_SECONDS,
    FEATURE_CACHE_UNLOAD_TIMEOUT_SECONDS,
)
from files.image_extensions_helpers import (
    MIN_THUMBNAIL_SIZE,
    IMAGE_EXTENSIONS,
    clear_image_extensions_cache,
    get_image_extensions,
)

# macOS keyboard symbols (UI labels, shortcuts sidebar, help dialog, settings, etc.)
CMD_SYMBOL = "⌘"
OPTION_SYMBOL = "⌥"
ALT_SYMBOL = OPTION_SYMBOL
CTRL_SYMBOL = "⌃"
SHIFT_SYMBOL = "⇧"
ENTER_SYMBOL = "↩"
RETURN_SYMBOL = ENTER_SYMBOL
COPY_SYMBOL = "⧉"

MODIFIER_SYMBOLS = {
    "Cmd": CMD_SYMBOL,
    "Shift": SHIFT_SYMBOL,
    "Ctrl": CTRL_SYMBOL,
    "Control": CTRL_SYMBOL,
    "Alt": ALT_SYMBOL,
    "Option": OPTION_SYMBOL,
}

# Thumbnail sizing constraints
MAX_THUMBNAIL_SIZE = 450  # Default value, will be dynamically updated based on container size

# Parallel thumbnail generation
# Cap at 4 to reduce GIL contention; 7+ worker threads competing for GIL can deadlock
# when main thread drops GIL during Qt signal connections (e.g. QTimer.singleShot)
THUMBNAIL_GENERATION_THREADS = min(4, max(1, (os.cpu_count() or 2) - 1))

# Batch processing constants for UI responsiveness
THUMBNAIL_QUEUE_BATCH_SIZE = 50  # Number of thumbnails to queue before calling processEvents
THUMBNAIL_QUEUE_BATCH_PAUSE_MS = 10  # Milliseconds to pause between batches (allows UI to process events)
THUMBNAIL_WORKER_BATCH_SIZE = 10  # Number of thumbnails worker thread processes before pausing
THUMBNAIL_WORKER_BATCH_PAUSE_MS = 5  # Milliseconds worker thread pauses between batches

# Spacing constants for grid layout
THUMBNAIL_SPACING = 4  # Space between thumbnails (both horizontal and vertical)
HORIZONTAL_SPACING = THUMBNAIL_SPACING  # Legacy alias
VERTICAL_SPACING = THUMBNAIL_SPACING    # Legacy alias

# Margin constants for layout calculations
BASE_MARGIN = 20  # Base margin for thumbnail container

# Border and spacing constants for individual thumbnails
BORDER_SPACE = 4  # Space around each thumbnail for borders/highlighting
HIGHLIGHT_BORDER_WIDTH = 5  # Width of highlight border for selected thumbnails

# Overlay text (filename/size) constants for row height calculation
# Used by thumbnail_operations_manager for fast size calculation - no QFontMetrics
# Must match canvas QFontMetrics for Arial 14pt (~16px on macOS)
OVERLAY_LINE_HEIGHT = 16
OVERLAY_SPACING = 4  # Space between image and overlay box
OVERLAY_PADDING = 4  # Padding inside overlay box (2px top/bottom)

# Canvas layout margins
CANVAS_TOP_MARGIN = 10  # Top margin for canvas
CANVAS_BOTTOM_MARGIN = 10  # Bottom margin for canvas
CANVAS_TOP_BORDER = 10  # Top border space

# Calculated margin constants (derived from above)
CANVAS_TOTAL_TOP_MARGIN = CANVAS_TOP_MARGIN + BORDER_SPACE  # 14px
CANVAS_TOTAL_BOTTOM_MARGIN = CANVAS_BOTTOM_MARGIN  # 10px
CANVAS_TOTAL_HEIGHT_MARGINS = CANVAS_TOTAL_TOP_MARGIN + CANVAS_TOTAL_BOTTOM_MARGIN  # 24px
CANVAS_TOTAL_WIDTH_MARGINS = BASE_MARGIN * 2  # 40px

# Border width constants
SQUARE_IMAGE_BORDER_WIDTH = 7  # Legacy - not currently used
REGULAR_BORDER_WIDTH = 2       # Legacy default; live value is IMAGE_BORDER_WIDTH_PX from theme
# Theme sliders / stored border widths (px); strokes are drawn inset inside the cell rect
MAX_THEME_BORDER_WIDTH_PX = 10

# Main-window chrome: splitter handles + status bar top edge (synced from active theme)
MIN_VIEW_CHROME_BORDER_WIDTH_PX = 0
MAX_VIEW_CHROME_BORDER_WIDTH_PX = 8
VIEW_BORDER_WIDTH_PX = 2

# Auto-scroll during drag operations
# Table of (distance_from_edge_px, scroll_speed_percent_of_screen_per_second)
# Distance is measured in pixels from the top or bottom edge of the viewport
# Speed is percentage of viewport height to scroll per second
# Entries should be ordered from largest distance to smallest (for proper interpolation)
DRAG_AUTO_SCROLL_SPEEDS = [
    (100, 25.6),   # 100px from edge -> 25.6% scroll speed
    (90, 51.2),    # 90px from edge  -> 51.2% scroll speed
    (80, 76.8),    # 80px from edge  -> 76.8% scroll speed
    (70, 102.4),   # 70px from edge  -> 102.4% scroll speed
    (60, 128.0),   # 60px from edge  -> 128.0% scroll speed
    (50, 153.6),   # 50px from edge  -> 153.6% scroll speed
    (40, 179.2),   # 40px from edge  -> 179.2% scroll speed
    (30, 204.8),   # 30px from edge  -> 204.8% scroll speed
    (20, 230.4),   # 20px from edge  -> 230.4% scroll speed
    (10, 256.0),   # 10px from edge  -> 256.0% scroll speed
]

# Browse image history: in-memory recent browse images (File ▸ Image History / F3 specific-files view)
BROWSE_IMAGE_HISTORY_MAX = 60
# Debounce delay is user-configurable (Settings ▸ General ▸ Browse Settings: "Save to history after ms")

# Tree view auto-scroll during drag - narrow band (less than one node height), slow speeds
TREE_DRAG_AUTO_SCROLL_TIMER_MS = 20  # ms - timer interval for auto-scroll of tree during drag

TREE_DRAG_AUTO_SCROLL_SPEEDS: List[tuple] = [
    (30, 1.5),    # 30px from edge -> 1.5% scroll speed
    (20, 3.0),    # 20px from edge -> 3.0% scroll speed
    (10, 8.0),     # 10px from edge  -> 8.0% scroll speed
    # (6, 3.2),    # 6px from edge  -> 3.2% scroll speed
    # (4, 4.0),     # 4px from edge  -> 4% scroll speed
    # (2, 4.8),     # 2px from edge  -> 4.8% scroll speed (max)
]

# Face scanning (face_engine): max dimension; larger images are downscaled for faster detection
FACE_SCANNING_DOWNSCALE_THRESHOLD = 2000

# Chat LM Studio: apology/refusal phrases that trigger response retry (case-insensitive match)
CHAT_REJECTED_RESPONSE_PHRASES: List[str] = [
    "an AI"
    "I'm sorry",
    "I apologize",
    "I'm unable",
    "I am unable",
    "i cannot",
    "I can not",
    "I cannot",
    "I won't",
    "I can't",
    "I will not",
    "not comply",
    "harmful",
    "ethical",
    "guidelines",
    "norms",
    "standards",
]

# File tree constants
EXPANSION_LEVELS = 5          # Number of levels to expand the file tree
TREE_UPDATE_DEBOUNCE_TIMER = 130  # ms - debounce when holding scroll key to coalesce rapid updates

# Excluded file extensions (system/bundle files that should not be shown in file tree)
EXCLUDED_EXTENSIONS: Set[str] = {
    '.app', '.pxd', '.framework', '.bundle', '.plugin', '.component',
    '.pkg', '.egg', '.pages', '.whl', '.ipa', '.apk', '.deb', '.rpm'
}

# Skipped patterns for find command (excluded bundle/filetypes to skip)
SKIPPED_PATTERNS: List[str] = [
    '*.app', '*.framework', '*.bundle',
    '*.pkg', '*.pages'
]

# Color constants for thumbnails (populated from active theme; default = dark)
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor

from theme.theme_base import asset_path, asset_file_url, asset_url as _asset_url

from theme.dark_theme_definitions import DEFAULT_DARK_THEME
from theme.theme_service import get_dark_theme_stylesheet, sync_to_thumbnail_constants


def inset_rect_for_stroke(rect: QRect, border_width: int) -> QRect:
    """Inset rect so a pen stroke of width border_width lies fully inside rect."""
    if border_width <= 0:
        return rect
    h = border_width // 2
    r = border_width - h
    return rect.adjusted(h, h, -r, -r)


def inset_corner_radius(base_radius: int, border_width: int) -> int:
    """Corner radius for an inset stroke so corners stay inside the cell."""
    return max(0, base_radius - border_width // 2)

# Legacy module-level names — single source of truth is the active theme dataclass; sync keeps these updated.
CURRENT_IMAGE_BACKGROUND_COLOR_HEX = ""
CURRENT_IMAGE_BACKGROUND_COLOR = QColor()
CURRENT_IMAGE_BORDER_COLOR_HEX = ""
CURRENT_IMAGE_BORDER_COLOR = QColor()
DEFAULT_IMAGE_BORDER_WIDTH_PX = 1
CURRENT_IMAGE_BORDER_WIDTH_PX = 2
MULTISELECT_BORDER_WIDTH_PX = 2
IMAGE_BORDER_WIDTH_PX = 2  # legacy alias for current/highlight width
MULTISELECT_BACKGROUND_COLOR_HEX = ""
MULTISELECT_BACKGROUND_COLOR = QColor()
MULTISELECT_BORDER_COLOR_HEX = ""
MULTISELECT_BORDER_COLOR = QColor()
DEFAULT_BACKGROUND_COLOR_HEX = ""
DEFAULT_BACKGROUND_COLOR = QColor()
THUMBNAIL_GRID_BACKGROUND_COLOR_HEX = ""
THUMBNAIL_GRID_BACKGROUND_COLOR = QColor()
DEFAULT_BORDER_COLOR_HEX = ""
DEFAULT_BORDER_COLOR = QColor()
DEFAULT_IMAGE_BACKGROUND_COLOR_HEX = ""
DEFAULT_IMAGE_BACKGROUND_COLOR = QColor()
DEFAULT_IMAGE_COLOR_HEX = ""
DEFAULT_IMAGE_COLOR = QColor()
TEXT_COLOR_HEX = ""
TEXT_COLOR = QColor()
THUMBNAIL_TEXT_COLOR_HEX = ""
THUMBNAIL_TEXT_COLOR = QColor()
QMENU_DEFAULT_STYLE_SHEET = ""
TAB_BUTTON_FOCUS_BACKGROUND_COLOR_HEX = ""
TAB_BUTTON_FOCUS_BORDER_COLOR_HEX = ""
HEADING_COLOR = QColor()
HEADING_COLOR_HEX = ""
DIALOG_TEXT_COLOR = QColor()
DIALOG_TEXT_COLOR_HEX = ""
DIALOG_BACKGROUND_HEX = ""
DIALOG_INPUT_BACKGROUND_HEX = ""
WIDGET_BG_HOVER_HEX = ""
WIDGET_BG_PRESSED_HEX = ""
WIDGET_BG_DISABLED_HEX = ""
TEXT_DISABLED_HEX = ""
BORDER_DEFAULT_HEX = ""
BORDER_HOVER_HEX = ""
CHROME_BORDER_HEX = ""
BUTTON_BG_DEFAULT_HEX = ""
BUTTON_TEXT_DEFAULT_HEX = ""
BUTTON_BORDER_DEFAULT_HEX = ""
BUTTON_BG_HOVER_HEX = ""
BUTTON_TEXT_HOVER_HEX = ""
BUTTON_BORDER_HOVER_HEX = ""
BUTTON_BG_PRESSED_HEX = ""
BUTTON_FOCUS_TEXT_HEX = ""
BUTTON_DEFAULT_BG_HEX = ""
BUTTON_DEFAULT_BORDER_HEX = ""
SIDEBAR_HEADER_BG_HEX = ""
SIDEBAR_HEADER_BORDER_HEX = ""
SIDEBAR_HEADER_TEXT_HEX = ""
SIDEBAR_SPLITTER_HANDLE_HEX = ""
TREE_HEADER_FOCUS_BG_HEX = ""
ERROR_COLOR_HEX = ""
VALIDATION_SUCCESS_COLOR_HEX = ""
ACCENT_COLOR_HEX = ""
TAB_BUTTON_HOVER_BG_HEX = ""
LOCKED_FILE_BACKGROUND_COLOR = QColor()
TREE_FOLDER_WITH_IMAGES_COLOR = QColor()

# Thumbnail canvas paint extras (synced from active theme in theme_service)
THUMBNAIL_FILENAME_OVERLAY_BOX_COLOR = QColor()
THUMBNAIL_EMPTY_FILTER_BTN_BG = QColor()
THUMBNAIL_EMPTY_FILTER_BTN_BG_HOVER = QColor()
THUMBNAIL_EMPTY_FILTER_BTN_BORDER = QColor()
THUMBNAIL_EMPTY_FILTER_BTN_BORDER_HOVER = QColor()
THUMBNAIL_EMPTY_FILTER_BTN_TEXT_HOVER = QColor()

sync_to_thumbnail_constants(DEFAULT_DARK_THEME)

RED = "\033[91m"
RESET = "\033[0m"
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
GRAY = "\033[90m"
LIGHT_GRAY = "\033[37m"
DARK_GRAY = "\033[90m"
LIGHT_RED = "\033[91m"
LIGHT_GREEN = "\033[92m"
LIGHT_YELLOW = "\033[93m"
LIGHT_MAGENTA = "\033[95m"
LIGHT_CYAN = "\033[96m"
ORANGE = "\033[38;5;208m"
AMBER = "\033[38;5;208m"
YELLOW = "\033[38;5;226m"
LIME = "\033[38;5;118m"
GREEN = "\033[38;5;118m"
TEAL = "\033[38;5;38m"
CYAN = "\033[38;5;51m"
BLUE = "\033[38;5;21m"
INDIGO = "\033[38;5;63m"
VIOLET = "\033[38;5;99m"
PINK = "\033[38;5;205m"
ROSE = "\033[38;5;198m"
BEIGE = "\033[38;5;187m"

#### Notes - do not delete below this line ###

# current_func = inspect.currentframe().f_code.co_name
# print(f"{CYAN}{current_func}{RESET}")
# print("\n".join([("   " * (i+1)) + f"{CYAN}{frame.function}{RESET}" for i, frame in enumerate(inspect.stack())]))

