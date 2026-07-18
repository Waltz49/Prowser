#!/usr/bin/env python3
"""
View Manager for Image Browser
Handles browse view and thumbnail view modes, view switching, and display state
"""

import os
import stat
import warnings
from datetime import datetime
from typing import List, Optional, Set, Tuple

from PySide6.QtCore import QEvent, QObject, QMutexLocker, QPoint, Qt, QTimer, QSize, QRect
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QApplication,
    QTextEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QPushButton,
)
from PySide6.QtGui import (
    QPixmap, QPainter, QColor, QPen, QBrush, QStandardItemModel, QCursor,
    QMouseEvent, QFont, QPalette,
)

# Local imports
from exif.exif_image_loader import load_image_with_exif_correction
from theme.theme_base import asset_path
from theme.theme_service import get_active_theme
from thumbnails.thumbnail_canvas import ThumbnailCanvas
from thumbnails.list_canvas import ListCanvas
from sort_mode import SortMode
import thumbnails.thumbnail_constants as tc
from thumbnails.thumbnail_constants import BASE_MARGIN
from event_bus import THUMBNAIL_CLICKED
from utils import (
    entry_debug_wrapper,
    entry_debug,
    normalize_path_for_display,
    should_preserve_window_focus,
)


class CursorManager(QObject):
    """
    Manages cursor visibility based on mouse movement.
    
    Hides the cursor after a specified period of inactivity and shows it
    again when the mouse moves. Designed to be attached to any QWidget.
    Now uses a global event filter to catch all mouse events (for macOS compatibility).
    """
    
    def __init__(self, widget: QWidget, hide_delay_ms: int = 2000, parent=None):
        """
        Initialize the cursor manager.
        
        Args:
            widget: The widget to monitor for mouse events
            hide_delay_ms: Milliseconds to wait before hiding cursor (default: 2000)
            parent: Parent QObject
        """
        super().__init__(parent)
        
        self.widget = widget
        self.hide_delay_ms = hide_delay_ms
        self.is_cursor_hidden = False
        self._over_hide_zone = False
        self._paused = False
        
        # Timer for hiding cursor after inactivity
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._hide_cursor)
        
        # Store original cursor for restoration
        self.original_cursor = widget.cursor()
        
        # Install global event filter
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
    
    def _widget_under_cursor(self) -> QWidget | None:
        app = QApplication.instance()
        if app is None:
            return None
        return app.widgetAt(QCursor.pos())

    def _is_descendant_of(self, widget: QWidget | None, ancestor: QWidget) -> bool:
        w = widget
        while w is not None:
            if w is ancestor:
                return True
            w = w.parentWidget()
        return False

    def _exclusion_roots(self) -> tuple[QWidget, ...]:
        """Sidebars and status bar — never auto-hide the cursor here."""
        mw = self.parent()
        if mw is None:
            return ()
        roots: list[QWidget] = []
        for name in ("combined_sidebar", "right_sidebar", "status_bar"):
            w = getattr(mw, name, None)
            if w is not None:
                roots.append(w)
        return tuple(roots)

    def _is_over_excluded_zone(self) -> bool:
        w = self._widget_under_cursor()
        for root in self._exclusion_roots():
            if self._is_descendant_of(w, root):
                return True
        return False

    def _is_over_hide_zone(self) -> bool:
        """True when the cursor is over the browse canvas (self.widget) or its children."""
        if self._is_over_excluded_zone():
            return False
        widget = self.widget
        if widget is None or not widget.isVisible():
            return False
        return self._is_descendant_of(self._widget_under_cursor(), widget)

    def _clear_override_cursors(self):
        """Remove any application-wide override cursors (must not leak into sidebars)."""
        app = QApplication.instance()
        if app:
            while app.overrideCursor():
                app.restoreOverrideCursor()

    def _leave_hide_zone(self):
        """Restore cursor and stop auto-hide when pointer leaves the browse canvas."""
        if self._over_hide_zone:
            self._over_hide_zone = False
        self.hide_timer.stop()
        self._clear_override_cursors()
        if self.is_cursor_hidden:
            self.widget.setCursor(self.original_cursor)
            self.is_cursor_hidden = False

    def _update_hide_zone_state(self):
        """Track enter/leave of the hide zone; show cursor and stop timer on leave."""
        if self._is_over_excluded_zone():
            if self._over_hide_zone or self.is_cursor_hidden:
                self._leave_hide_zone()
            return
        over = self._is_over_hide_zone()
        if over != self._over_hide_zone:
            self._over_hide_zone = over
            if over:
                self.hide_timer.start(self.hide_delay_ms)
            else:
                self._leave_hide_zone()
        elif not over and self.is_cursor_hidden:
            self._show_cursor()

    def eventFilter(self, obj, event):
        """
        Event filter to catch mouse events and manage cursor visibility.
        
        Args:
            obj: The object that generated the event
            event: The event that occurred
            
        Returns:
            bool: True if event was handled, False to pass to parent
        """
        # Don't process events when paused
        if self._paused:
            return False
            
        # Listen for mouse movement and button events globally
        if event.type() in (
            QEvent.MouseMove,
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.Wheel,
            QEvent.Enter,
        ):
            self._update_hide_zone_state()
            if self._over_hide_zone:
                self._on_activity_in_zone()
        return super().eventFilter(obj, event)
    
    def _on_activity_in_zone(self):
        """Restart hide timer while the cursor is over the browse canvas."""
        if self.is_cursor_hidden:
            self._show_cursor()
        self.hide_timer.start(self.hide_delay_ms)

    def on_mouse_activity(self):
        """
        Manual method to trigger mouse activity (for use without event filter).
        Call this from mouse event handlers.
        """
        if self._paused:
            return
        self._update_hide_zone_state()
        if self._over_hide_zone:
            self._on_activity_in_zone()

    def refresh_for_pointer_location(self):
        """Reconcile hide/restore state for the current pointer position."""
        if self._paused:
            return
        self._update_hide_zone_state()
    
    def _hide_cursor(self):
        """Hide the cursor only while it remains over the browse canvas."""
        if not self._is_over_hide_zone():
            return
        if not self.is_cursor_hidden:
            # Widget-level only: app-wide override hides the cursor in sidebars too
            self.widget.setCursor(Qt.BlankCursor)
            self.is_cursor_hidden = True
    
    def _show_cursor(self):
        """Show the cursor using the original cursor."""
        if self.is_cursor_hidden:
            self._clear_override_cursors()
            self.widget.setCursor(self.original_cursor)
            self.is_cursor_hidden = False
    
    def set_cursor(self, cursor):
        """
        Set a specific cursor and update the original cursor reference.
        This allows the cursor manager to work with dynamic cursor changes.
        
        Args:
            cursor: The cursor to set
        """
        if self.is_cursor_hidden:
            self._clear_override_cursors()
            self.is_cursor_hidden = False
        self.widget.setCursor(cursor)
        # Update the original cursor reference so it can be restored later
        self.original_cursor = cursor
    
    def start(self):
        """Start cursor management (starts the hide timer when over the browse canvas)."""
        self._clear_override_cursors()
        self._over_hide_zone = self._is_over_hide_zone()
        if self._over_hide_zone:
            self.hide_timer.start(self.hide_delay_ms)
    
    def stop(self):
        """Stop cursor management and ensure cursor is visible."""
        self.hide_timer.stop()
        self._over_hide_zone = False
        if self.is_cursor_hidden:
            self._show_cursor()
        else:
            self._clear_override_cursors()
    
    def cleanup(self):
        """Clean up resources and restore original cursor."""
        self.stop()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
    
    def disable(self):
        """Completely disable cursor management and restore cursor."""
        self.stop()
        app = QApplication.instance()
        if app:
            app.removeEventFilter(self)
        self.is_cursor_hidden = False
        self._paused = True
OVERLAY_HEIGHT = 8  # Height of the overlay band in pixels
THUMBNAIL_SCROLL_AREA_OBJECT_NAME = "thumbnailScrollArea"
LIST_SCROLL_AREA_OBJECT_NAME = "listScrollArea"


def apply_thumbnail_scroll_area_chrome(
    scroll_area: QScrollArea,
    *,
    object_name: str = THUMBNAIL_SCROLL_AREA_OBJECT_NAME,
) -> None:
    """Grid-colored scroll shell; scrollbar track matches grid (no right-edge border strip)."""
    scroll_area.setObjectName(object_name)
    scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll_area.setLineWidth(0)
    scroll_area.setStyleSheet(
        get_active_theme().thumbnail_scroll_area_chrome_stylesheet(object_name)
    )
    vp = scroll_area.viewport()
    if vp is not None:
        bg = tc.THUMBNAIL_GRID_BACKGROUND_COLOR
        pal = vp.palette()
        pal.setColor(QPalette.ColorRole.Window, bg)
        pal.setColor(QPalette.ColorRole.Base, bg)
        vp.setPalette(pal)
        vp.setAutoFillBackground(True)


class CanvasManager(QWidget):
    """
    Manager for the canvas-based thumbnail display.
    Replaces the ThumbnailContainer and provides the same interface.
    """
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        
        # Create the canvas
        self.canvas = ThumbnailCanvas(main_window, self)
        
        # Create scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)  # Let canvas control its own size
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        
        # Set the canvas directly as the scroll area's widget to fill viewport
        self.scroll_area.setWidget(self.canvas)
        
        # Set minimum size for the canvas
        self.canvas.setMinimumSize(200, 200)
        
        # Set focus policy - let the main content widget handle focus
        self.setFocusPolicy(Qt.NoFocus)
        
        # Create main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll_area)
        
        # Create overlay widget to cover partial borders at top
        self.black_overlay = QWidget(self)
        self.black_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)  # Don't block mouse events
        
        # Set a fixed narrow band height (enough to cover partial borders)
        self.overlay_height = OVERLAY_HEIGHT  # Static height for the overlay band

        self._sync_thumbnail_chrome_colors()
        
        # Connect canvas signals to main window
        self._connect_signals()
        
        # Connect scroll signals to update black overlay
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._update_black_overlay)

        # Suggest Renames overlay (convert conflict view only)
        self.auto_rename_button = QPushButton("Suggest Renames...", self)
        self.auto_rename_button.setVisible(False)
        self.auto_rename_button.clicked.connect(self._on_auto_rename_clicked)
        from utils import get_button_style
        self.auto_rename_button.setStyleSheet(get_button_style())
        
        # Ensure overlay is positioned correctly when widget is first shown
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._update_black_overlay)
        
        # Spacing constants (same as ThumbnailContainer)
        self.HORIZONTAL_SPACING = 4
        self.VERTICAL_SPACING = 9
        self.BASE_MARGIN = 20
        self.HIGHLIGHT_BORDER_WIDTH = 5
        
    def _update_black_overlay(self):
        """Update the pink overlay to cover partial borders at the top"""
        # Always show the overlay as a static narrow band at the top of the scroll area
        self.black_overlay.setGeometry(
            0, 0, 
            self.scroll_area.width(), 
            self.overlay_height
        )
        # Ensure the overlay is above the canvas (higher z-index)
        self.black_overlay.raise_()
        self.black_overlay.show()
        self._update_auto_rename_button_geometry()

    def _on_auto_rename_clicked(self):
        if hasattr(self.main_window, "run_convert_conflict_auto_rename"):
            self.main_window.run_convert_conflict_auto_rename()

    def _update_auto_rename_button_geometry(self):
        if not getattr(self, "auto_rename_button", None):
            return
        if not self.auto_rename_button.isVisible():
            return
        margin = 10
        self.auto_rename_button.adjustSize()
        btn_w = self.auto_rename_button.width()
        btn_h = self.auto_rename_button.height()
        x = max(margin, self.scroll_area.width() - btn_w - margin)
        y = margin
        self.auto_rename_button.setGeometry(x, y, btn_w, btn_h)
        self.auto_rename_button.raise_()

    def update_convert_conflict_auto_rename_button(self):
        """Show Suggest Renames when viewing convert format conflicts in DUPLICATES mode."""
        btn = getattr(self, "auto_rename_button", None)
        if btn is None:
            return
        context = getattr(self.main_window, "convert_conflict_context", None)
        show = (
            context is not None
            and getattr(self.main_window, "current_sort_mode", None) == SortMode.DUPLICATES
            and getattr(self.main_window, "current_view_mode", None) == "thumbnail"
        )
        if show and context.get("has_name_conflicts"):
            btn.setEnabled(False)
            btn.setToolTip(
                "Unavailable: name conflicts exist where multiple sources "
                "share the same output filename."
            )
        elif show:
            btn.setEnabled(True)
            btn.setToolTip(
                "Suggest renames for conflicted source files based on similar images"
            )
        else:
            btn.setToolTip("")
        btn.setVisible(show)
        self._update_auto_rename_button_geometry()

    def _sync_thumbnail_chrome_colors(self):
        """Match top band + scroll viewport to the canvas paintEvent fill."""
        bg_hex = tc.THUMBNAIL_GRID_BACKGROUND_COLOR_HEX
        self.black_overlay.setStyleSheet(
            f"QWidget {{ background-color: {bg_hex}; border: none; }}"
        )
        apply_thumbnail_scroll_area_chrome(self.scroll_area)

    def refresh_theme_styles(self):
        """Reapply top band color and repaint canvas after global theme change."""
        self._sync_thumbnail_chrome_colors()
        self._update_black_overlay()
        if getattr(self, "auto_rename_button", None):
            from utils import get_button_style
            self.auto_rename_button.setStyleSheet(get_button_style())
        self._update_auto_rename_button_geometry()
        if getattr(self, "canvas", None):
            self.canvas.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_black_overlay()
        self._update_auto_rename_button_geometry()
        
    def _connect_signals(self):
        """Connect canvas signals to main window methods"""
        self.canvas.thumbnail_clicked.connect(self._on_thumbnail_clicked)
        self.canvas.thumbnail_double_clicked.connect(self._on_thumbnail_double_clicked)
        # self.canvas.thumbnail_hovered.connect(self._on_thumbnail_hovered)
        
        # Connect thumbnail loading signals from cache manager
        self.connect_cache_manager_signals()
    
    def connect_cache_manager_signals(self):
        """Connect to cache manager signals when available"""
        if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
            try:
                # Disconnect first to avoid duplicate connections
                # Check if signal has receivers before disconnecting to avoid RuntimeWarning
                signal = self.main_window.cache_manager.thumbnail_ready
                if signal.receivers() > 0:
                    try:
                        signal.disconnect(self.canvas.on_thumbnail_loaded)
                    except (TypeError, RuntimeError):
                        # Signal not connected to this specific slot - this is OK
                        pass
                # Connect with QueuedConnection for thread safety
                signal.connect(
                    self.canvas.on_thumbnail_loaded,
                    Qt.QueuedConnection
                )
            except Exception:
                pass
    
    def _on_thumbnail_clicked(self, index: int, cmd_pressed: bool, shift_pressed: bool, macos_ctrl_pressed: bool):
        """Handle thumbnail click from canvas - emit event for subscriber to handle"""
        if hasattr(self.main_window, 'event_bus') and self.main_window.event_bus:
            self.main_window.event_bus.emit(THUMBNAIL_CLICKED, (index, cmd_pressed, shift_pressed, macos_ctrl_pressed))
        elif hasattr(self.main_window, 'navigation_manager'):
            self.main_window.navigation_manager.handle_thumbnail_click(index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
    
    def _on_thumbnail_double_clicked(self, index: int):
        """Handle thumbnail double-click from canvas - open fullscreen when preview is showing"""
        # Only open fullscreen if preview is visible
        if hasattr(self.main_window, 'preview_widget') and self.main_window.preview_widget.isVisible():
            # Get the file path from the thumbnail to ensure we open the correct file
            # This is more reliable than trusting the index, especially after renames
            if (hasattr(self.main_window, 'displayed_images') and 
                self.main_window.displayed_images):
                # Get the thumbnail's file path (with mutex protection)
                thumbnail_path = None
                if (hasattr(self.canvas, 'thumbnails') and 
                    index is not None):
                    if hasattr(self.canvas, 'mutex'):
                        with QMutexLocker(self.canvas.mutex):
                            if 0 <= index < len(self.canvas.thumbnails):
                                thumbnail_path = self.canvas.thumbnails[index].image_path
                    else:
                        # Fallback if mutex doesn't exist
                        if 0 <= index < len(self.canvas.thumbnails):
                            thumbnail_path = self.canvas.thumbnails[index].image_path
                
                # Find the correct index in displayed_images using the file path
                correct_index = None
                if thumbnail_path:
                    try:
                        correct_index = self.main_window.displayed_images.index(thumbnail_path)
                    except (ValueError, AttributeError):
                        # Fallback to using the provided index if path not found
                        if index < len(self.main_window.displayed_images):
                            correct_index = index
                elif index is not None and index < len(self.main_window.displayed_images):
                    # Fallback to using the provided index if we can't get the path
                    correct_index = index
                
                if correct_index is not None:
                    # Match single-click behavior: clear selection first, then set indices
                    if hasattr(self.main_window, 'clear_selection'):
                        self.main_window.clear_selection(hilite=False)
                    # Set highlight_index and last_clicked_index before opening fullscreen
                    # This ensures the correct image is selected, matching single-click behavior
                    if hasattr(self.main_window, 'mvc_controller'):
                        self.main_window.mvc_controller.set_current_index(correct_index)
                    self.main_window.last_clicked_index = correct_index
                    if hasattr(self.main_window, 'view_mode_manager'):
                        self.main_window.view_mode_manager.open_browse_view(correct_index)
    
    # def _on_thumbnail_hovered(self, index: int):
    #     """Handle thumbnail hover from canvas"""
    #     # Don't change highlight when in browse mode - it can interfere with double-click
    #     # In browse mode, the displayed file should only change via explicit navigation
    #     if (hasattr(self.main_window, 'current_view_mode') and 
    #         self.main_window.current_view_mode == 'browse'):
    #         return
    #     if hasattr(self.main_window, 'set_highlighted_index'):
    #         self.main_window.set_highlighted_index(index)
    
    def focusInEvent(self, event):
        """Handle focus in events"""
        super().focusInEvent(event)
        # Don't steal focus from the container - let Qt handle tab navigation
    
    def set_thumbnails(self, image_paths: List[str], thumbnail_size: int):
        """Set the thumbnails to display on the canvas"""
        # Ensure canvas has a proper size before setting thumbnails
        if self.canvas.size().width() < 200:
            self.canvas.resize(800, 600)  # Set a reasonable default size
        
        self.canvas.set_thumbnails(image_paths, thumbnail_size)
    
    def set_thumbnail_loaded(self, index: int, pixmap):
        """Set a thumbnail as loaded"""
        self.canvas.set_thumbnail_loaded(index, pixmap)
    
    def set_highlighted_index(self, index: int):
        """Set the highlighted thumbnail index"""
        self.canvas.set_highlighted_index(index)
    
    def set_selected_indices(self, indices: Set[int]):
        """Set the selected thumbnail indices"""
        self.canvas.set_selected_indices(indices)
    
    def set_multi_select_mode(self, enabled: bool):
        """Set multi-select mode"""
        self.canvas.set_multi_select_mode(enabled)
    
    def set_filename_overlay_visible(self, visible: bool):
        """Set filename overlay visibility"""
        self.canvas.set_filename_overlay_visible(visible)
    
    def scroll_to_highlighted(self, index: int = None):
        """Scroll to the highlighted thumbnail"""
        self.canvas.scroll_to_highlighted(index)
    
    def clear_thumbnails(self):
        """Clear all thumbnails"""
        self.canvas.clear_thumbnails()
    
    def get_thumbnail_rect(self, index: int):
        """Get the rectangle for a specific thumbnail"""
        return self.canvas.get_thumbnail_rect(index)
    
    def get_visible_thumbnail_indices(self) -> List[int]:
        """Get indices of currently visible thumbnails"""
        return self.canvas.get_visible_thumbnail_indices()
    
    def force_canvas_size_update(self):
        """Force canvas size update (called when status bar is toggled)"""
        self.canvas.force_canvas_size_update()
    
    def get_grid_info(self) -> dict:
        """Get grid information (columns, rows) from the canvas"""
        return {
            "columns": self.canvas.columns,
            "rows": self.canvas.rows
        }
    
    def setFixedSize(self, width: int, height: int):
        """Set fixed size for the canvas"""
        self.canvas.setFixedSize(width, height)
    
    def updateGeometry(self):
        """Update geometry"""
        self.canvas.updateGeometry()
    
    def update(self):
        """Update the canvas"""
        self.canvas.update()
    
    def show(self):
        """Show the canvas manager"""
        super().show()
        self.canvas.show()
    
    def hide(self):
        """Hide the canvas manager"""
        super().hide()
        self.canvas.hide()
    
    # Compatibility methods for drag and drop
    def setAcceptDrops(self, enabled: bool):
        """Enable/disable drag and drop"""
        self.canvas.setAcceptDrops(enabled)
    
    def dragEnterEvent(self, event):
        """Handle drag enter events"""
        self.canvas.dragEnterEvent(event)
    
    def dragMoveEvent(self, event):
        """Handle drag move events"""
        self.canvas.dragMoveEvent(event)
    
    def dragLeaveEvent(self, event):
        """Handle drag leave events"""
        self.canvas.dragLeaveEvent(event)
    
    def dropEvent(self, event):
        """Handle drop events"""
        self.canvas.dropEvent(event)
    
    # Method to add vertical spacing to widgets (compatibility)

class ListHeaderWidget(QWidget):
    """Fixed header widget that doesn't scroll"""
    
    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        self.canvas = canvas
        # Use canvas row height for header height
        self.setFixedHeight(canvas.row_height)
        self.setFocusPolicy(Qt.NoFocus)
        # Enable mouse tracking for hover effects (optional)
        self.setMouseTracking(True)
    
    def _get_column_at_position(self, pos: QPoint) -> Optional[str]:
        """Get the column key at the given position"""
        # Get actual row width from canvas if available
        actual_row_width = None
        if self.canvas.rows:
            first_row = self.canvas.rows[0]
            if first_row.rect and first_row.rect.isValid():
                actual_row_width = first_row.rect.width()
        
        if actual_row_width is None or actual_row_width <= 0:
            canvas_width = self.width()
            if canvas_width <= 0:
                canvas_width = 1200
            actual_row_width = max(100, canvas_width - (BASE_MARGIN * 2))
        
        col_x = self.canvas._calculate_column_positions(row_width=actual_row_width)
        
        x = pos.x()
        
        # Check each column (in reverse order so name column is checked last)
        columns = ['name', 'dimensions', 'size', 'date', 'permissions', 'thumbnail']
        for col_key in columns:
            x_pos = col_x[col_key]
            if col_key == 'name':
                col_width = col_x.get('name_width', actual_row_width - (x_pos - BASE_MARGIN))
            else:
                col_width = self.canvas.column_widths[col_key]
            
            if x_pos <= x < x_pos + col_width:
                return col_key
        
        return None
    
    def _get_sort_mode_for_column(self, col_key: str) -> Optional[SortMode]:
        """Map column key to sort mode"""
        mapping = {
            'date': SortMode.DATE,
            'size': SortMode.FILESIZE,  # File size, not area
            'dimensions': SortMode.DIMENSIONS,
            'name': SortMode.NAME,
            'permissions': SortMode.PERMISSIONS,
        }
        return mapping.get(col_key)
    
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press events on header"""
        if event.button() == Qt.LeftButton:
            col_key = self._get_column_at_position(event.pos())
            if col_key:
                sort_mode = self._get_sort_mode_for_column(col_key)
                if sort_mode and hasattr(self.canvas, 'main_window'):
                    main_window = self.canvas.main_window
                    if hasattr(main_window, 'sorting_manager'):
                        # Check if this is the current sort mode
                        current_mode = main_window.sorting_manager.get_current_sort_mode()
                        toggle_reverse = (current_mode == sort_mode)
                        
                        # Set sort mode (will toggle if same column)
                        # This will call apply_current_sort() which updates the list view if needed
                        main_window.sorting_manager.set_sort_mode(sort_mode, toggle_reverse=toggle_reverse)
                        
                        # Update header to show sort indicator
                        self.update()
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def paintEvent(self, event):
        """Paint the header"""
        from PySide6.QtGui import QPainter, QColor, QFont, QPen
        from PySide6.QtCore import QRect
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        try:
            # Get the actual row width from canvas to ensure perfect alignment
            # The canvas has rows with rects that define the actual table width
            actual_row_width = None
            if self.canvas.rows:
                # Get row width from first row's rect if available
                first_row = self.canvas.rows[0]
                if first_row.rect and first_row.rect.isValid():
                    actual_row_width = first_row.rect.width()
            
            # Fallback to calculated width if rows not available yet
            if actual_row_width is None or actual_row_width <= 0:
                canvas_width = self.width()
                if canvas_width <= 0:
                    canvas_width = 1200
                actual_row_width = max(100, canvas_width - (BASE_MARGIN * 2))
            
            # Calculate column positions using the actual row width
            col_x = self.canvas._calculate_column_positions(row_width=actual_row_width)
            
            # Draw header background only for sortable columns
            # Background starts at the vertical line after thumbnail (not at permissions column start)
            # This line is at: col_x['thumbnail'] + column_widths['thumbnail']
            header_y = 0
            header_height = self.canvas.row_height
            
            # Start at the line position (where the vertical separator is drawn)
            sortable_start_x = col_x['thumbnail'] + self.canvas.column_widths['thumbnail']
            
            # End at the right border line position (rect.right() in rows)
            # This is BASE_MARGIN + row_width, which equals rect.right()
            sortable_end_x = BASE_MARGIN + actual_row_width
            
            # Draw background rectangle for sortable columns only
            bg_rect = QRect(sortable_start_x, header_y, sortable_end_x - sortable_start_x, header_height)
            painter.fillRect(bg_rect, QColor(50, 50, 50))
            
            # Get current sort mode and direction
            current_sort_mode = None
            is_reversed = False
            if hasattr(self.canvas, 'main_window'):
                main_window = self.canvas.main_window
                if hasattr(main_window, 'sorting_manager'):
                    current_sort_mode = main_window.sorting_manager.get_current_sort_mode()
                    is_reversed = main_window.sorting_manager.sort_direction_reversed
            
            # Map sort mode to column key
            sort_mode_to_col = {
                SortMode.DATE: 'date',
                SortMode.FILESIZE: 'size',
                SortMode.DIMENSIONS: 'dimensions',
                SortMode.NAME: 'name',
                SortMode.PERMISSIONS: 'permissions',
            }
            sorted_col_key = sort_mode_to_col.get(current_sort_mode)
            
            # Draw header text - white color
            painter.setPen(QColor(255, 255, 255))  # White text
            font = QFont("Arial", 13)
            font.setBold(True)
            painter.setFont(font)
            
            headers = [
                ('thumbnail', ''),
                ('permissions', 'Perm'),
                ('date', 'Date'),
                ('size', 'Size'),
                ('dimensions', 'Dim'),
                ('name', 'Name')
            ]
            
            # header_y and header_height already set above
            
            for col_key, header_text in headers:
                x_pos = col_x[col_key]
                if col_key == 'name':
                    col_width = col_x.get('name_width', actual_row_width - (x_pos - BASE_MARGIN))
                    align = Qt.AlignLeft | Qt.AlignVCenter
                else:
                    col_width = self.canvas.column_widths[col_key]
                    align = Qt.AlignCenter | Qt.AlignVCenter
                
                if col_width > 0:
                    # Ensure white pen is set before drawing each text
                    painter.setPen(QColor(255, 255, 255))  # White text
                    header_text_rect = QRect(x_pos, header_y, col_width, header_height)
                    
                    # Draw header text with sort indicator if this is the sorted column
                    if col_key == sorted_col_key:
                        # Calculate text width to position caret
                        font_metrics = painter.fontMetrics()
                        text_width = font_metrics.horizontalAdvance(header_text)
                        
                        # Position caret after text (with small spacing)
                        caret_x = x_pos
                        if align & Qt.AlignLeft:
                            # Left aligned: caret after text
                            caret_x = x_pos + text_width + 4
                        elif align & Qt.AlignCenter:
                            # Center aligned: caret after centered text
                            text_start_x = x_pos + (col_width - text_width) // 2
                            caret_x = text_start_x + text_width + 4
                        elif align & Qt.AlignRight:
                            # Right aligned: caret before text
                            caret_x = x_pos + col_width - text_width - 4
                        caret_x += 5
                        # Draw text first
                        painter.drawText(header_text_rect, align, header_text)
                        
                        # Draw sort indicator (caret)
                        caret_y = header_y + header_height // 2
                        caret_size = 6
                        
                        # Draw caret (^ for ascending, v for descending)
                        from PySide6.QtGui import QPen
                        pen = QPen(QColor(255, 255, 255))
                        pen.setWidth(2)  # Double the default line thickness (usually 1)
                        painter.setPen(pen)
                        narrower = caret_size - 1  # 2 px narrower (caret_size is 6; now becomes 5)
                        if is_reversed:
                            # Descending: draw v (down arrow)
                            painter.drawLine(caret_x - narrower, caret_y - caret_size // 2, 
                                             caret_x, caret_y + caret_size // 2)
                            painter.drawLine(caret_x, caret_y + caret_size // 2,
                                             caret_x + narrower, caret_y - caret_size // 2)
                        else:
                            # Ascending: draw ^ (up arrow)
                            painter.drawLine(caret_x - narrower, caret_y + caret_size // 2,
                                             caret_x, caret_y - caret_size // 2)
                            painter.drawLine(caret_x, caret_y - caret_size // 2,
                                             caret_x + narrower, caret_y + caret_size // 2)
                    painter.drawText(header_text_rect, align, header_text)
                    
                    # For name column, add directory notation (right-justified, small font)
                    if col_key == 'name':
                        # Get displayed images to determine directory
                        directory_text = None
                        if hasattr(self.canvas, 'main_window'):
                            main_window = self.canvas.main_window
                            if hasattr(main_window, 'displayed_images') and main_window.displayed_images:
                                displayed_images = main_window.displayed_images
                                # Get directories of all displayed files
                                directories = set()
                                import os
                                for image_path in displayed_images:
                                    if image_path:
                                        try:
                                            abs_path = os.path.abspath(os.path.expanduser(image_path))
                                            if os.path.exists(abs_path):
                                                file_dir = os.path.dirname(abs_path)
                                                directories.add(file_dir)
                                        except (OSError, ValueError):
                                            continue
                                
                                # If all files are from the same directory, show it
                                if len(directories) == 1:
                                    directory_path = directories.pop()
                                    # Use normalize_path_for_display to convert ~ for home dir
                                    from utils import normalize_path_for_display
                                    directory_text = normalize_path_for_display(directory_path)
                                else:
                                    directory_text = "Multiple directories"
                            
                            # Draw directory notation if available
                            if directory_text:
                                # Calculate space needed for "Name" text and caret (if sorted)
                                # Use the header font metrics to measure "Name" text width
                                header_font_metrics = painter.fontMetrics()
                                name_text_width = header_font_metrics.horizontalAdvance(header_text)
                                
                                # If this column is sorted, account for caret width
                                caret_width = 0
                                if col_key == sorted_col_key:
                                    # Caret is positioned after text with spacing
                                    # caret_x calculation: x_pos + text_width + 4 + 5, then caret_size (6) + some margin
                                    caret_width = 15  # Approximate: spacing (4+5) + caret size (6) + margin
                                
                                # Calculate available width: column width - name text - caret - right margin
                                right_margin = 30
                                left_space_needed = name_text_width + caret_width + 10  # 10px spacing between name and directory
                                directory_width = col_width - left_space_needed - right_margin
                                
                                # Ensure directory width is positive
                                if directory_width > 0:
                                    # Use smaller font for directory notation (increased from 10 to 11)
                                    small_font = QFont("Arial", 14)
                                    small_font.setBold(False)
                                    painter.setFont(small_font)
                                    # painter.setPen(QColor(200, 200, 200))  # Slightly dimmer than header text
                                    painter.setPen(QColor(200, 200, 250))  # Slightly dimmer than header text
                                    
                                    # Right-justified with 30px right margin, left-elided
                                    # Rectangle ends 30px before the right edge of the column
                                    directory_rect = QRect(x_pos, header_y, col_width - right_margin, header_height)
                                    small_font_metrics = painter.fontMetrics()
                                    # Elide from left if necessary, using the calculated available width
                                    elided_text = small_font_metrics.elidedText(directory_text, Qt.ElideLeft, directory_width)
                                    painter.drawText(directory_rect, Qt.AlignRight | Qt.AlignVCenter, elided_text)
                                    
                                    # Reset font and pen for next column
                                    painter.setFont(font)
                                    painter.setPen(QColor(255, 255, 255))
                    
                    # Draw vertical separator line after this column (except after thumbnail and name)
                    # Skip thumbnail column (first column) and name column (last column)
                    if col_key != 'name' and col_key != 'thumbnail':
                        line_x = x_pos + col_width
                        painter.setPen(QPen(tc.DEFAULT_BORDER_COLOR, 1))
                        painter.drawLine(line_x, header_y, line_x, header_y + header_height)
                        # Reset pen to white for next text
                        painter.setPen(QColor(255, 255, 255))
            
            # Left and right border lines removed per user request
        finally:
            painter.end()

class ListCanvasManager(QWidget):
    """
    Manager for the canvas-based list view display.
    Similar to CanvasManager but for list view.
    """
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        
        # Create the canvas (without header - header will be separate)
        self.canvas = ListCanvas(main_window, self)
        
        # Create fixed header widget
        self.header_widget = ListHeaderWidget(self.canvas, self)
        
        # Create scroll area (only for canvas, not header)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)  # Let canvas control its own size
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        
        # Override scroll area keyPressEvent to prevent arrow keys from scrolling
        # Arrow keys should be handled by canvas for navigation, not scrolling
        def scroll_area_keyPressEvent(event):
            key = event.key()
            # Don't let scroll area handle arrow keys - forward to canvas
            if key in [Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right]:
                # Forward to canvas which will forward to main window
                if self.canvas:
                    self.canvas.keyPressEvent(event)
                event.accept()
                return
            # Let scroll area handle other keys (like PageUp/PageDown for scrolling)
            QScrollArea.keyPressEvent(self.scroll_area, event)
        
        self.scroll_area.keyPressEvent = scroll_area_keyPressEvent
        
        # Set the canvas directly as the scroll area's widget
        self.scroll_area.setWidget(self.canvas)
        
        # Set minimum size for the canvas
        self.canvas.setMinimumSize(200, 200)
        
        # Set focus policy - allow canvas to receive focus for keyboard events
        self.setFocusPolicy(Qt.NoFocus)  # Manager itself doesn't need focus
        self.canvas.setFocusPolicy(Qt.ClickFocus)  # Canvas needs focus but not via Tab key
        
        # Create main layout with header on top
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header_widget)  # Fixed header
        layout.addWidget(self.scroll_area)  # Scrollable content
        
        # Connect canvas signals to main window
        self._connect_signals()
        
        # Connect scroll signals for lazy thumbnail loading
        self.scroll_area.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        
        # Connect horizontal scroll to sync header
        self.scroll_area.horizontalScrollBar().valueChanged.connect(self._sync_header_scroll)
        
        # Connect scroll area viewport resize to update list view
        self.scroll_area.viewport().installEventFilter(self)

        apply_thumbnail_scroll_area_chrome(
            self.scroll_area, object_name=LIST_SCROLL_AREA_OBJECT_NAME
        )
    
    def refresh_theme_styles(self):
        """Reapply list scroll chrome after theme border/grid color changes."""
        apply_thumbnail_scroll_area_chrome(
            self.scroll_area, object_name=LIST_SCROLL_AREA_OBJECT_NAME
        )
        if getattr(self, "canvas", None):
            self.canvas.update()
        if getattr(self, "header_widget", None):
            self.header_widget.update()
    
    def eventFilter(self, obj, event):
        """Filter events to handle viewport resize"""
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Resize:
            # Viewport was resized - update row rectangles and header
            QTimer.singleShot(10, self._handle_viewport_resize)
        return super().eventFilter(obj, event)
    
    def _handle_viewport_resize(self):
        """Handle viewport resize - update row rectangles and header"""
        if self.canvas.rows:
            # Clear cached column positions
            self.canvas._cached_col_x = None
            self.canvas._cached_row_width = None
            # Update row rectangles
            self.canvas._update_row_rectangles()
            # Update canvas and header
            self.canvas.update()
            self.header_widget.update()
    
    def resizeEvent(self, event):
        """Handle resize events - update row rectangles and header"""
        super().resizeEvent(event)
        # Delay update to allow Qt to finish layout updates
        QTimer.singleShot(10, self._handle_viewport_resize)
    
    def _sync_header_scroll(self):
        """Sync header horizontal scroll with canvas scroll"""
        # Header doesn't scroll horizontally - it's fixed
        # But we need to update it when canvas width changes
        self.header_widget.update()
    
    def _connect_signals(self):
        """Connect canvas signals to main window methods"""
        self.canvas.thumbnail_clicked.connect(self._on_row_clicked)
        self.canvas.thumbnail_double_clicked.connect(self._on_row_double_clicked)
        
        # Connect thumbnail loading signals from cache manager
        self.connect_cache_manager_signals()
    
    def connect_cache_manager_signals(self):
        """Connect to cache manager signals when available"""
        if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
            try:
                import warnings
                signal = self.main_window.cache_manager.thumbnail_ready
                # Disconnect first to avoid duplicates (try/catch handles case where not connected)
                # Suppress RuntimeWarning about failed disconnect
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    try:
                        signal.disconnect(self.canvas.on_thumbnail_loaded)
                    except (TypeError, RuntimeError):
                        # Signal not connected to this slot - this is OK
                        pass
                # Connect with QueuedConnection for thread safety
                signal.connect(self.canvas.on_thumbnail_loaded, Qt.QueuedConnection)
            except Exception:
                pass
    
    def _on_row_clicked(self, index: int, cmd_pressed: bool, shift_pressed: bool, macos_ctrl_pressed: bool):
        """Handle row click from canvas - emit event for subscriber to handle"""
        from event_bus import THUMBNAIL_CLICKED
        if hasattr(self.main_window, 'event_bus') and self.main_window.event_bus:
            self.main_window.event_bus.emit(THUMBNAIL_CLICKED, (index, cmd_pressed, shift_pressed, macos_ctrl_pressed))
        elif hasattr(self.main_window, 'navigation_manager'):
            self.main_window.navigation_manager.handle_thumbnail_click(index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
    
    def _on_row_double_clicked(self, index: int):
        """Handle row double-click from canvas"""
        # Get the file path from the row
        if (hasattr(self.main_window, 'displayed_images') and 
            self.main_window.displayed_images and
            0 <= index < len(self.main_window.displayed_images)):
            image_path = self.main_window.displayed_images[index]
            
            # Set current image path
            if hasattr(self.main_window, '_set_current_image_path_with_sync'):
                self.main_window._set_current_image_path_with_sync(image_path)
            else:
                self.main_window.current_image_path = image_path
            
            # CRITICAL: Set flag to return to list view since we're clicking from list view
            # This ensures we return to list mode after closing browse view
            self.main_window._return_to_list_view = True
            
            # Open browse view
            if hasattr(self.main_window, 'view_mode_manager'):
                self.main_window.view_mode_manager.open_browse_view(index)
    
    def _on_scroll_changed(self):
        """Handle scroll change - trigger lazy thumbnail loading"""
        if hasattr(self.canvas, '_load_visible_thumbnails'):
            self.canvas._load_visible_thumbnails()
    
    def set_rows(self, image_paths: List[str], row_data: List[Tuple[str, str, str, str, str]]):
        """Set the rows to display in list view"""
        # Ensure scroll area has a proper size before setting rows
        viewport = self.scroll_area.viewport()
        if viewport.width() < 200:
            # Try to get size from parent or use default
            parent_width = self.width() if self.width() > 0 else 800
            parent_height = self.height() if self.height() > 0 else 600
            viewport.resize(max(parent_width, 800), max(parent_height, 600))
        
        self.canvas.set_rows(image_paths, row_data)
        
        # Update header to match canvas width
        self.header_widget.update()
        
        # Force update after a short delay to ensure widget is visible and sized
        QTimer.singleShot(100, lambda: (
            self.canvas.show(),
            self.canvas.setVisible(True),
            self.canvas._update_row_rectangles(),
            self.canvas.update(),
            self.header_widget.update(),
            QApplication.processEvents()
        ))
        
        # Ensure cache manager signals are connected and trigger thumbnail loading
        QTimer.singleShot(300, lambda: (
            self.connect_cache_manager_signals(),
            self.canvas._load_visible_thumbnails()
        ))
    
    def set_highlighted_index(self, index: int):
        """Set the highlighted row index"""
        self.canvas.highlighted_index = index
        self.canvas.update()
    
    def set_selected_indices(self, indices: Set[int]):
        """Set the selected row indices"""
        if self.canvas.selected_indices != indices:
            self.canvas.selected_indices = indices.copy()
            self.canvas.update()
    
    def set_multi_select_mode(self, enabled: bool):
        """Set multi-select mode"""
        if self.canvas.multi_select_mode != enabled:
            self.canvas.multi_select_mode = enabled
            self.canvas.update()
    
    def scroll_to_highlighted(self, index: int = None, force: bool = False):
        """Scroll to the highlighted row only if it's not already fully visible
        
        Args:
            index: Row index to scroll to (defaults to highlighted_index)
            force: If True, always scroll even if row is already visible (useful for H/E keys)
        """
        if index is None:
            index = self.canvas.highlighted_index
        
        if index < 0 or index >= len(self.canvas.rows):
            return
        
        # Ensure row rectangles are updated before scrolling
        if hasattr(self.canvas, '_update_row_rectangles'):
            self.canvas._update_row_rectangles()
        
        row_item = self.canvas.rows[index]
        if not row_item.rect:
            # If rect is not set, try updating again after a short delay
            from PySide6.QtCore import QTimer
            QTimer.singleShot(10, lambda: self.scroll_to_highlighted(index, force))
            return
        
        scroll_bar = self.scroll_area.verticalScrollBar()
        if not scroll_bar:
            return
        
        # Get viewport dimensions
        viewport = self.scroll_area.viewport()
        viewport_height = viewport.height()
        viewport_top = scroll_bar.value()
        viewport_bottom = viewport_top + viewport_height
        
        # Get row position (relative to canvas)
        row_top = row_item.rect.y()
        row_bottom = row_top + row_item.rect.height()
        
        # Check if entire row is already fully visible in viewport (unless forcing scroll)
        if not force:
            # Row is fully visible if both top and bottom are within viewport bounds
            if row_top >= viewport_top and row_bottom <= viewport_bottom:
                # Row is already fully visible, no need to scroll
                return
        
        # Row is not fully visible or force scroll - scroll just enough to make it visible
        # Calculate how much we need to scroll
        if force:
            # Force scroll: scroll to show row at top with small margin
            margin = 5
            target_scroll = max(0, row_top - margin)
        elif row_top < viewport_top:
            # Row top is above viewport - scroll up just enough to show the top
            # Don't scroll to top of screen, just enough to make row visible
            target_scroll = max(0, row_top)
        elif row_bottom > viewport_bottom:
            # Row bottom is below viewport - scroll down just enough to show the bottom
            # Calculate scroll position so row bottom is at viewport bottom
            target_scroll = max(0, row_bottom - viewport_height)
        else:
            # This shouldn't happen if our visibility check is correct, but handle it
            return
        
        # Ensure we don't scroll beyond maximum
        max_scroll = scroll_bar.maximum()
        target_scroll = min(target_scroll, max_scroll)
        scroll_bar.setValue(target_scroll)
    
    def update(self):
        """Update the canvas"""
        self.canvas.update()
    
    def show(self):
        """Show the list canvas manager"""
        super().show()
        self.canvas.show()
        # Give focus to canvas so keyboard events work
        QTimer.singleShot(50, lambda: self.canvas.setFocus())
    
    def hide(self):
        """Hide the list canvas manager"""
        super().hide()
        self.canvas.hide()
    
    # Compatibility methods for drag and drop
    def setAcceptDrops(self, enabled: bool):
        """Enable/disable drag and drop"""
        self.canvas.setAcceptDrops(enabled)
    
    def dragEnterEvent(self, event):
        """Handle drag enter events"""
        self.canvas.dragEnterEvent(event)
    
    def dragMoveEvent(self, event):
        """Handle drag move events"""
        self.canvas.dragMoveEvent(event)
    
    def dragLeaveEvent(self, event):
        """Handle drag leave events"""
        self.canvas.dragLeaveEvent(event)
    
    def dropEvent(self, event):
        """Handle drop events"""
        self.canvas.dropEvent(event)

class BrowseImageLabel(QLabel):
    """QLabel subclass that displays lock icon overlay in browse mode"""
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._padlock_pixmap: Optional[QPixmap] = None
    
    def _load_padlock_pixmap(self) -> Optional[QPixmap]:
        """Load the padlock icon from assets folder"""
        if self._padlock_pixmap is not None:
            return self._padlock_pixmap
        
        padlock_path = asset_path("padlock.png")
        if os.path.exists(padlock_path):
            pixmap = QPixmap(padlock_path)
            if not pixmap.isNull():
                self._padlock_pixmap = pixmap
                return pixmap
        
        # Fallback: return None if image not found
        return None
    
    def paintEvent(self, event):
        """Override paintEvent to draw lock icon overlay"""
        super().paintEvent(event)
        
        # Only draw lock icon in browse mode and if locking is enabled
        if not hasattr(self.main_window, 'current_view_mode') or self.main_window.current_view_mode != 'browse':
            return
        
        if not getattr(self.main_window, 'allow_thumbnail_locking', False):
            return
        
        # Check if current image is locked
        if not hasattr(self.main_window, 'current_image_path') or not self.main_window.current_image_path:
            return
        
        if not hasattr(self.main_window, 'lock_manager') or not self.main_window.lock_manager:
            return
        
        if not self.main_window.lock_manager.is_file_locked(self.main_window.current_image_path):
            return
        
        # Draw lock icon - twice the size of thumbnail lock icon
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Icon size: twice the thumbnail size (thumbnail uses max(16, min(32, rect.width() // 8)))
        # For browse mode, use a fixed larger size
        icon_size = 64  # Twice the max thumbnail size of 32
        margin = 8
        
        # Position in upper-right corner
        padlock_x = self.width() - icon_size - margin
        padlock_y = margin
        
        # Try to load and use the padlock image
        padlock_pixmap = self._load_padlock_pixmap()
        if padlock_pixmap and not padlock_pixmap.isNull():
            # Scale the pixmap to the desired icon size
            scaled_pixmap = padlock_pixmap.scaled(
                icon_size, icon_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            # Draw the scaled padlock image
            painter.drawPixmap(int(padlock_x), int(padlock_y), scaled_pixmap)
            painter.end()
            return
        
        # Fallback: Draw a simple padlock icon using QPainter if image not found
        padlock_color = QColor(255, 215, 0)  # Gold color
        painter.setPen(QPen(padlock_color, 4))  # Thicker pen for larger icon
        painter.setBrush(QBrush(padlock_color))
        
        # Draw padlock body (rounded rectangle)
        body_width = icon_size * 0.6
        body_height = icon_size * 0.7
        body_x = padlock_x + (icon_size - body_width) / 2
        body_y = padlock_y + icon_size * 0.2
        
        # Draw rounded rectangle for padlock body
        painter.drawRoundedRect(
            int(body_x), int(body_y), 
            int(body_width), int(body_height),
            4, 4  # Larger radius for larger icon
        )
        
        # Draw padlock shackle (arch on top)
        shackle_width = icon_size * 0.5
        shackle_height = icon_size * 0.3
        shackle_x = padlock_x + (icon_size - shackle_width) / 2
        shackle_y = padlock_y + icon_size * 0.1
        
        # Draw arch (semi-circle on top)
        painter.setPen(QPen(padlock_color, 4))
        painter.setBrush(QBrush())
        # Draw arc for shackle
        painter.drawArc(
            int(shackle_x), int(shackle_y),
            int(shackle_width), int(shackle_height * 2),
            0, 180 * 16  # 180 degrees
        )
        
        painter.end()


class ViewManager:
    """Manages browse view and thumbnail view modes, view switching, and display state"""

    def __init__(self, main_window):
        self.main_window = main_window
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            from event_bus import DISPLAYED_IMAGES_CHANGED
            main_window.event_bus.subscribe(DISPLAYED_IMAGES_CHANGED, self._on_displayed_images_changed)
        # watch(self.main_window.displayed_images)

    def _on_displayed_images_changed(self, images):
        """Handle DISPLAYED_IMAGES_CHANGED - update list view when in list mode"""
        if getattr(self.main_window, 'current_view_mode', '') == 'list':
            self.update_list_view()

    def prepare_early_browse_view(self) -> bool:
        """Switch to browse shell before thumbnail grid work (startup restore)."""
        if self.main_window.current_view_mode == 'browse':
            return False
        if not hasattr(self.main_window, 'stacked_widget') or self.main_window.stacked_widget is None:
            return False
        self.main_window.stacked_widget.setCurrentIndex(1)
        self.main_window.current_view_mode = 'browse'
        self.main_window.manage_sidebar_visibility_for_view_mode('browse')
        if hasattr(self.main_window, 'browse_view_action') and self.main_window.browse_view_action:
            self.main_window.browse_view_action.setEnabled(False)
        return True

    def finish_browse_startup_restore(self, image_index: int) -> None:
        """Show the restored image in browse after directory load."""
        images = getattr(self.main_window, 'displayed_images', None) or []
        if not images or image_index < 0 or image_index >= len(images):
            return
        self.main_window.view_mode_manager.open_browse_view(image_index)
        self.main_window._defer_browse_restore = False
        self.main_window._browse_startup_restore_done = True

    def setup_browse_view(self):
        """Setup the browse view widget"""
        browse_view_widget = QWidget()
        browse_view_widget.setFocusPolicy(Qt.NoFocus)
        self.main_window._browse_view_root_widget = browse_view_widget
        browse_view_widget.setStyleSheet(get_active_theme().browse_view_shell_stylesheet())
        
        layout = QVBoxLayout(browse_view_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create a centering container for the image
        self.main_window.image_container = QWidget()
        self.main_window.image_container.setStyleSheet("background-color: transparent;")
        
        # Add centering layout to the image container
        self.main_window.image_layout = QHBoxLayout(self.main_window.image_container)
        self.main_window.image_layout.setContentsMargins(0, 0, 0, 0)
        self.main_window.image_layout.setSpacing(0)
        
        # Add stretch to center the image horizontally
        self.main_window.image_layout.addStretch()
        
        # Stretch so image_container fills browse_view_widget vertically during resize
        layout.addWidget(self.main_window.image_container, 1)
        
        self.main_window.image_label = BrowseImageLabel(self.main_window, self.main_window.image_container)
        self.main_window.image_label.setAlignment(Qt.AlignCenter)
        self.main_window.image_label.setMinimumSize(100, 100)
        self.main_window.image_label.setScaledContents(False)
        self.main_window.image_label.setFocusPolicy(Qt.NoFocus)
        self.main_window.image_label.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.main_window.image_label.setStyleSheet("background-color: transparent;")
        
        # Add image label to the centering layout (vertically centered so letterboxing matches during resize)
        self.main_window.image_layout.addWidget(self.main_window.image_label, 0, Qt.AlignVCenter)
        
        self.main_window.slideshow_next_label = QLabel(self.main_window.image_container)
        self.main_window.slideshow_next_label.setAlignment(Qt.AlignCenter)
        self.main_window.slideshow_next_label.setMinimumSize(100, 100)
        self.main_window.slideshow_next_label.setScaledContents(False)
        self.main_window.slideshow_next_label.setFocusPolicy(Qt.NoFocus)
        self.main_window.slideshow_next_label.setStyleSheet("background-color: transparent;")
        self.main_window.slideshow_next_label.hide()
        
        # Add slideshow label to the centering layout
        self.main_window.image_layout.addWidget(self.main_window.slideshow_next_label, 0, Qt.AlignVCenter)
        
        # Add stretch to complete the centering
        self.main_window.image_layout.addStretch()
        
        self.main_window.filename_label = QTextEdit(browse_view_widget)
        self.main_window.filename_label.setReadOnly(True)
        self.main_window.filename_label.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.main_window.filename_label.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.main_window.filename_label.setFocusPolicy(Qt.NoFocus)  # Don't receive keyboard events
        # Set minimum size to ensure widget is visible
        self.main_window.filename_label.setMinimumSize(200, 50)
        _theme = get_active_theme()
        self.main_window.filename_label.setStyleSheet(_theme.browse_filename_textedit_stylesheet())
        self.main_window.filename_label.hide()
        # Don't set WA_TransparentForMouseEvents - we need mouse events for scrolling
        # Set maximum height to enable scrolling without visible scrollbars
        self.main_window.filename_label.setMaximumHeight(500)
        # Enable mouse wheel scrolling
        self.main_window.filename_label.setAcceptRichText(True)
        # Ensure QTextEdit document is properly initialized
        self.main_window.filename_label.document().setDefaultStyleSheet(_theme.browse_filename_document_stylesheet())

        # Number overlay labels (top-right) for imagegen-#### codes: shadow + foreground
        self.main_window.number_overlay_shadow_label = QLabel(browse_view_widget)
        self.main_window.number_overlay_shadow_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.main_window.number_overlay_shadow_label.setStyleSheet("background-color: transparent; color: black;")
        self.main_window.number_overlay_shadow_label.hide()

        self.main_window.number_overlay_label = QLabel(browse_view_widget)
        self.main_window.number_overlay_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.main_window.number_overlay_label.setStyleSheet("background-color: transparent; color: white;")
        self.main_window.number_overlay_label.hide()

        # Image size line below name/sequence overlay (shadow + foreground)
        self.main_window.number_overlay_size_shadow_label = QLabel(browse_view_widget)
        self.main_window.number_overlay_size_shadow_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.main_window.number_overlay_size_shadow_label.setStyleSheet("background-color: transparent; color: black;")
        self.main_window.number_overlay_size_shadow_label.hide()

        self.main_window.number_overlay_size_label = QLabel(browse_view_widget)
        self.main_window.number_overlay_size_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.main_window.number_overlay_size_label.setStyleSheet("background-color: transparent; color: white;")
        self.main_window.number_overlay_size_label.hide()

        self.main_window.stacked_widget.addWidget(browse_view_widget)

    def refresh_browse_theme_styles(self):
        """Re-apply browse view shell and filename overlay styles when the app theme changes."""
        theme = get_active_theme()
        w = getattr(self.main_window, "_browse_view_root_widget", None)
        if w:
            w.setStyleSheet(theme.browse_view_shell_stylesheet())
        if hasattr(self.main_window, "filename_label") and self.main_window.filename_label:
            self.main_window.filename_label.setStyleSheet(theme.browse_filename_textedit_stylesheet())
            self.main_window.filename_label.document().setDefaultStyleSheet(theme.browse_filename_document_stylesheet())

    def setup_thumbnail_view(self):
        """Setup the thumbnail view widget"""
        thumbnail_widget = QWidget()
        thumbnail_widget.setFocusPolicy(Qt.NoFocus)  # Don't steal focus from tree
        
        layout = QVBoxLayout(thumbnail_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create canvas manager instead of thumbnail container
        self.main_window.thumbnail_container = CanvasManager(self.main_window, thumbnail_widget)
        
        # Set initial filename overlay visibility from config
        self.main_window.thumbnail_container.set_filename_overlay_visible(self.main_window.thumbnail_filename_visible)
        # ========================================================================
        # CRITICAL: Set NoFocus to prevent thumbnail_container from being in tab order
        # ========================================================================
        # DO NOT CHANGE THIS! The thumbnail_container must have NoFocus policy
        # to prevent it from being in the tab order. Only tree_container and
        # main_content_widget should be in the tab order.
        # ========================================================================
        self.main_window.thumbnail_container.setFocusPolicy(Qt.NoFocus)
        
        # Import spacing constants from CanvasManager
        self.main_window.HORIZONTAL_SPACING = self.main_window.thumbnail_container.HORIZONTAL_SPACING
        self.main_window.VERTICAL_SPACING = self.main_window.thumbnail_container.VERTICAL_SPACING
        
        # Get the scroll area from the canvas manager
        self.main_window.scroll_area = self.main_window.thumbnail_container.scroll_area
        
        # Connect scroll signals to handle scroll-aware thumbnail loading
        self.main_window.connect_scroll_signals()
        
        layout.addWidget(self.main_window.thumbnail_container)
        self.main_window.stacked_widget.addWidget(thumbnail_widget)

    def setup_list_view(self):
        """Setup the list view widget with canvas-based display"""
        list_view_widget = QWidget()
        list_view_widget.setFocusPolicy(Qt.NoFocus)
        
        layout = QVBoxLayout(list_view_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create list canvas manager instead of table widget
        self.main_window.list_view_container = ListCanvasManager(self.main_window, list_view_widget)
        
        # Set focus policy
        self.main_window.list_view_container.setFocusPolicy(Qt.NoFocus)
        
        # Get the scroll area from the list canvas manager
        self.main_window.list_view_scroll_area = self.main_window.list_view_container.scroll_area
        
        layout.addWidget(self.main_window.list_view_container)
        self.main_window.stacked_widget.addWidget(list_view_widget)
    
    def _on_list_item_clicked(self, row: int, column: int):
        """Handle single click on list item - no longer used with canvas view"""
        # Clicks are handled by the canvas itself now
        pass
    
    def _on_list_item_double_clicked(self, item: QTableWidgetItem):
        """Handle double-click on list item - no longer used with canvas view"""
        # Double-clicks are handled by the canvas itself now
        pass
    
    def _open_browse_from_list(self, row: int):
        """Open browse view for the image at the given row"""
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        if row < 0 or row >= len(self.main_window.displayed_images):
            return
        
        image_path = self.main_window.displayed_images[row]
        
        # Find the index in displayed_images
        try:
            index = self.main_window.displayed_images.index(image_path)
        except ValueError:
            index = row
        
        # Store that we're coming from list view
        self.main_window._return_to_list_view = True
        
        # Open browse view
        self.open_browse_view(index)
    
    def _format_permissions(self, file_path: str, file_stat=None) -> str:
        """Format file permissions in rwxrwxrwx format"""
        try:
            if file_stat is None:
                file_stat = os.stat(file_path)
            mode = file_stat.st_mode
            permissions = stat.filemode(mode)
            # Convert from -rwxrwxrwx format to rwxrwxrwx format
            if permissions.startswith('-'):
                return permissions[1:]
            return permissions
        except Exception:
            return "----------"
    
    def _format_file_size(self, file_path: str, file_stat=None, metadata=None) -> str:
        """Format file size in human-readable format, rounded to nearest KB with no decimal places"""
        try:
            # Use cached metadata if available (fastest - no file system call)
            if metadata and hasattr(metadata, 'file_size') and metadata.file_size:
                size_bytes = metadata.file_size
            elif file_stat:
                size_bytes = file_stat.st_size
            else:
                size_bytes = os.path.getsize(file_path)
            # Round to nearest KB (no decimal places)
            size_kb = round(size_bytes / 1024.0)
            return f"{size_kb} KB"
        except Exception:
            return "0 KB"
    
    def _format_date(self, file_path: str, file_stat=None, metadata=None) -> str:
        """Format file modification date"""
        try:
            # Use cached metadata if available (fastest - no file system call)
            if metadata and hasattr(metadata, 'modified_time') and metadata.modified_time:
                mtime = metadata.modified_time
            elif file_stat:
                mtime = file_stat.st_mtime
            else:
                mtime = os.path.getmtime(file_path)
            dt = datetime.fromtimestamp(mtime)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "0000-00-00 00:00:00"
    
    def _format_dimensions(self, file_path: str, metadata=None) -> str:
        """Format image dimensions - optimized to use cache first, skip slow loading for list view"""
        try:
            # Use cached metadata if available (fastest - no file system call)
            if metadata and hasattr(metadata, 'width') and hasattr(metadata, 'height'):
                if metadata.width > 0 and metadata.height > 0:
                    return f"{metadata.width}x{metadata.height}"
            
            # Try to get dimensions from metadata cache (if not passed in)
            if metadata is None and hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
                metadata = self.main_window.cache_manager.get_metadata_sync(file_path)
                if metadata and metadata.width > 0 and metadata.height > 0:
                    return f"{metadata.width}x{metadata.height}"
            
            # For list view, try fast metadata extraction but skip slow QPixmap loading
            # This avoids loading full images just for dimensions in list view
            try:
                from exif.exif_image_loader import get_image_dimensions_fast_metadata
                dimensions = get_image_dimensions_fast_metadata(file_path)
                if dimensions and len(dimensions) == 2:
                    width, height = dimensions
                    if width > 0 and height > 0:
                        return f"{width}x{height}"
            except (ImportError, Exception):
                pass
            
            # If cache and fast metadata both fail, return 0x0 rather than loading full image
            # This keeps list view loading fast - dimensions can be loaded later if needed
            return "0x0"
        except Exception:
            return "0x0"
    
    def _on_list_header_clicked(self, column: int):
        """Handle column header click for sorting - no longer used with canvas view"""
        # Header clicks are handled by the canvas itself now
        pass
    
    def _update_list_header_sort_indicators(self):
        """Update column header labels to show sort indicators - no longer used with canvas view"""
        # Headers are drawn by the canvas itself now
        pass
    
    def update_list_view(self):
        """Update the list view with current displayed images"""
        if not hasattr(self.main_window, 'list_view_container') or not self.main_window.list_view_container:
            return
        
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            self.main_window.list_view_container.set_rows([], [])
            return
        
        displayed_images = self.main_window.displayed_images
        num_images = len(displayed_images)
        
        # Check if all files are from the same directory
        # If files are from different directories, show full path in name column
        show_full_path = False
        if displayed_images:
            try:
                # Get directory of first file
                first_dir = os.path.dirname(os.path.abspath(displayed_images[0]))
                # Check if all other files are from the same directory
                for image_path in displayed_images[1:]:
                    try:
                        current_dir = os.path.dirname(os.path.abspath(image_path))
                        if current_dir != first_dir:
                            show_full_path = True
                            break
                    except Exception:
                        # If we can't determine directory, show full path to be safe
                        show_full_path = True
                        break
            except Exception:
                # If we can't determine first directory, show full path to be safe
                show_full_path = True
        
        # OPTIMIZATION: Pre-build path-to-metadata lookup for large lists
        # This avoids O(n*m) iteration through cache for each file
        metadata_lookup = {}
        use_large_list_optimization = num_images > 1000
        if use_large_list_optimization and hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
            cache_manager = self.main_window.cache_manager
            if len(cache_manager.metadata_cache) > 0:
                # Build reverse lookup: path -> metadata (one-time O(m) operation)
                for key, cached_metadata in cache_manager.metadata_cache.items():
                    # Extract path from cache key (cache keys contain the path)
                    # Cache keys are typically formatted as "path|mtime|extra"
                    if '|' in key:
                        path_part = key.split('|')[0]
                    else:
                        path_part = key
                    # Normalize path for lookup
                    try:
                        normalized_path = os.path.abspath(path_part)
                        metadata_lookup[normalized_path] = cached_metadata
                    except Exception:
                        pass
        
        # PHASE 1: Gather all data to memory first (no widget operations)
        # This separates data gathering from widget population for better performance
        row_data = []  # List of tuples: (perms_text, date_text, size_text, dims_text, name_text)
        
        for row, image_path in enumerate(displayed_images):
            # Process events periodically for responsiveness
            if row % 100 == 0:
                QApplication.processEvents()
            
            # MAJOR OPTIMIZATION: Try to get metadata from cache first
            # If cached, we can get size, date, and dimensions WITHOUT any file system calls!
            metadata = None
            file_stat = None
            
            # Fast path: Try to get metadata from cache
            # For large lists, use pre-built lookup dictionary (O(1) instead of O(m))
            if use_large_list_optimization and metadata_lookup:
                # Use pre-built lookup - O(1) operation
                try:
                    abs_path = os.path.abspath(image_path)
                    metadata = metadata_lookup.get(abs_path)
                except Exception:
                    metadata = None
            elif hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
                # For smaller lists, use normal cache key lookup
                cache_manager = self.main_window.cache_manager
                if len(cache_manager.metadata_cache) > 0:
                    try:
                        cache_key = cache_manager.get_cache_key(image_path)
                        if cache_key in cache_manager.metadata_cache:
                            metadata = cache_manager.metadata_cache[cache_key]
                    except Exception:
                        pass
            
            # Always get file_stat for permissions (even for large lists)
            # Permissions aren't in metadata cache, so we need os.stat()
            # But we can skip it if we already have it from metadata lookup
            if file_stat is None:
                try:
                    file_stat = os.stat(image_path)
                except Exception:
                    file_stat = None
            
            # Gather all text data for this row
            # Always format permissions - file_stat should be available now
            perms_text = self._format_permissions(image_path, file_stat) if file_stat else "----------"
            date_text = self._format_date(image_path, file_stat, metadata)
            size_text = self._format_file_size(image_path, file_stat, metadata)
            dims_text = self._format_dimensions(image_path, metadata)
            # Show full path if files are from different directories, otherwise just filename
            if show_full_path:
                # Use normalize_path_for_display to replace home directory with ~
                name_text = normalize_path_for_display(image_path)
            else:
                name_text = os.path.basename(image_path)
            
            # Store row data (no widget operations yet)
            row_data.append((perms_text, date_text, size_text, dims_text, name_text))
        
        # PHASE 2: Populate canvas all at once (fast batch operation)
        # Now that all data is gathered, populate the canvas efficiently
        # Set rows on canvas (this triggers painting)
        self.main_window.list_view_container.set_rows(displayed_images, row_data)
        
        # Highlight current image if available
        if hasattr(self.main_window, 'current_image_path') and self.main_window.current_image_path:
            try:
                current_index = displayed_images.index(self.main_window.current_image_path)
                self.main_window.list_view_container.set_highlighted_index(current_index)
                self.main_window.list_view_container.scroll_to_highlighted(current_index)
            except ValueError:
                pass
        
        # Trigger lazy loading of visible thumbnails after a short delay
        # Also ensure cache manager signals are connected
        if hasattr(self.main_window.list_view_container, 'connect_cache_manager_signals'):
            self.main_window.list_view_container.connect_cache_manager_signals()
        QTimer.singleShot(200, lambda: self.main_window.list_view_container.canvas._load_visible_thumbnails())
    
    def _on_list_scroll_changed(self):
        """Handle scroll events to load thumbnails for newly visible rows"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        # Debounce scroll events
        if hasattr(self.main_window, '_list_view_thumbnail_timer'):
            self.main_window._list_view_thumbnail_timer.stop()
            self.main_window._list_view_thumbnail_timer.start(150)  # 150ms debounce
    
    def _load_visible_thumbnails(self):
        """Trigger thumbnail loading for currently visible rows using existing thumbnail loading system"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        # Get visible row range
        viewport = self.main_window.list_view_table.viewport()
        visible_rect = viewport.visibleRegion().boundingRect() if hasattr(viewport, 'visibleRegion') else viewport.rect()
        
        # Get first and last visible rows
        first_row = self.main_window.list_view_table.rowAt(visible_rect.top())
        last_row = self.main_window.list_view_table.rowAt(visible_rect.bottom())
        
        if first_row < 0:
            first_row = 0
        if last_row < 0:
            last_row = self.main_window.list_view_table.rowCount() - 1
        
        # Expand range slightly to preload nearby rows
        preload_margin = 20
        first_row = max(0, first_row - preload_margin)
        last_row = min(self.main_window.list_view_table.rowCount() - 1, last_row + preload_margin)
        
        # Get image paths for visible rows
        visible_paths = []
        for row in range(first_row, last_row + 1):
            item = self.main_window.list_view_table.item(row, 0)
            if item:
                image_path = item.data(Qt.UserRole)
                if image_path:
                    visible_paths.append(image_path)
        
        # Use existing thumbnail loading system - request thumbnails at current thumbnail size
        # The system will use cached thumbnails and resize as needed
        if visible_paths and hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
            # Request thumbnails at the current thumbnail size (will be resized to 64x64 in signal handler)
            current_thumb_size = getattr(self.main_window, 'current_thumbnail_size', 200)
            for image_path in visible_paths:
                # Use the existing async loading system - it will use cached thumbnails
                self.main_window.cache_manager.get_thumbnail_async(image_path, current_thumb_size, priority=1)
    
    def _on_list_thumbnail_loaded(self, image_path: str, pixmap: QPixmap, size: int):
        """Handle thumbnail loaded signal - update list view table item"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        if not pixmap or pixmap.isNull():
            return
        
        # Find the row for this image path
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        try:
            row = self.main_window.displayed_images.index(image_path)
        except ValueError:
            return  # Image not in current displayed list
        
        # Update the thumbnail item
        item = self.main_window.list_view_table.item(row, 0)
        if item:
            # Resize thumbnail to 64x64 for list view (regardless of original size)
            thumbnail_size = 64
            if pixmap.width() != thumbnail_size or pixmap.height() != thumbnail_size:
                scaled_pixmap = pixmap.scaled(
                    thumbnail_size, thumbnail_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            else:
                scaled_pixmap = pixmap
            
            item.setData(Qt.DecorationRole, scaled_pixmap)
    
    def _page_down_list_view(self):
        """Page down in list view - scroll down by one viewport height"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        table = self.main_window.list_view_table
        if table.rowCount() == 0:
            return
        
        # Get current selected row
        selected_rows = table.selectedIndexes()
        current_row = selected_rows[0].row() if selected_rows else 0
        
        # Use QTableWidget's built-in page down behavior by scrolling the viewport
        # Get the visible rect to determine how many rows are visible
        viewport = table.viewport()
        visible_rect = viewport.visibleRegion().boundingRect() if hasattr(viewport, 'visibleRegion') else viewport.rect()
        
        # Get first and last visible rows
        first_visible = table.rowAt(visible_rect.top())
        last_visible = table.rowAt(visible_rect.bottom())
        
        if first_visible < 0:
            first_visible = 0
        if last_visible < 0:
            last_visible = table.rowCount() - 1
        
        # Calculate rows per page (number of visible rows)
        rows_per_page = max(1, last_visible - first_visible + 1)
        
        # Calculate new row (move down by one page from current selection)
        new_row = min(table.rowCount() - 1, current_row + rows_per_page)
        
        # Select and scroll to new row
        table.selectRow(new_row)
        table.scrollToItem(
            table.item(new_row, 0),
            QAbstractItemView.EnsureVisible
        )
        
        # Update current image path if needed
        if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images:
            if 0 <= new_row < len(self.main_window.displayed_images):
                image_path = self.main_window.displayed_images[new_row]
                if hasattr(self.main_window, '_set_current_image_path_with_sync'):
                    self.main_window._set_current_image_path_with_sync(image_path)
                else:
                    self.main_window.current_image_path = image_path
    
    def _sync_list_selection_after_key_navigation(self):
        """Sync list view selection after keyboard navigation (arrow keys)"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        # Get current row from the table
        current_row = self.main_window.list_view_table.currentRow()
        if current_row >= 0:
            self._sync_list_selection_to_current_image(current_row)
    
    def _sync_list_selection_to_current_image_from_path(self):
        """Sync list view selection to current image path (for left/right navigation)"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        if getattr(self.main_window, 'current_view_mode', None) != 'list':
            return
        
        # Get current image path from main window
        if not hasattr(self.main_window, 'current_image_path') or not self.main_window.current_image_path:
            return
        
        # Find the row index of the current image
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        try:
            current_image_path = self.main_window.current_image_path
            row_index = self.main_window.displayed_images.index(current_image_path)
            
            # Select the row and scroll to it
            if 0 <= row_index < self.main_window.list_view_table.rowCount():
                self.main_window.list_view_table.selectRow(row_index)
                self.main_window.list_view_table.scrollToItem(
                    self.main_window.list_view_table.item(row_index, 0),
                    QAbstractItemView.EnsureVisible
                )
                # Sync selection to update metadata, tree, and preview
                self._sync_list_selection_to_current_image(row_index)
        except (ValueError, AttributeError):
            # Image not found in displayed_images - ignore
            pass
    
    def _sync_list_selection_to_current_image(self, row: int):
        """Sync list view selection to current image path"""
        if not hasattr(self.main_window, 'displayed_images') or not self.main_window.displayed_images:
            return
        
        if 0 <= row < len(self.main_window.displayed_images):
            image_path = self.main_window.displayed_images[row]
            # Set current image by path - this will sync metadata, tree, and preview
            if hasattr(self.main_window, 'set_current_image_by_path'):
                self.main_window.set_current_image_by_path(image_path)
                # Update Information sidebar, preview, and tree (same as thumbnail view)
                if hasattr(self.main_window, 'update_filename_for_new_image'):
                    self.main_window.update_filename_for_new_image()
                # Update preview widget if visible
                if hasattr(self.main_window, 'update_preview_if_visible'):
                    self.main_window.update_preview_if_visible()
                # Update tree highlighting
                if (hasattr(self.main_window, 'file_tree_handler') and 
                    self.main_window.file_tree_handler.is_tree_initialized()):
                    self.main_window.file_tree_handler.highlight_current_file()
    
    def _page_up_list_view(self):
        """Page up in list view - scroll up by one viewport height"""
        if not hasattr(self.main_window, 'list_view_table') or not self.main_window.list_view_table:
            return
        
        table = self.main_window.list_view_table
        if table.rowCount() == 0:
            return
        
        # Get current selected row
        selected_rows = table.selectedIndexes()
        current_row = selected_rows[0].row() if selected_rows else 0
        
        # Use QTableWidget's built-in page up behavior by scrolling the viewport
        # Get the visible rect to determine how many rows are visible
        viewport = table.viewport()
        visible_rect = viewport.visibleRegion().boundingRect() if hasattr(viewport, 'visibleRegion') else viewport.rect()
        
        # Get first and last visible rows
        first_visible = table.rowAt(visible_rect.top())
        last_visible = table.rowAt(visible_rect.bottom())
        
        if first_visible < 0:
            first_visible = 0
        if last_visible < 0:
            last_visible = table.rowCount() - 1
        
        # Calculate rows per page (number of visible rows)
        rows_per_page = max(1, last_visible - first_visible + 1)
        
        # Calculate new row (move up by one page from current selection)
        new_row = max(0, current_row - rows_per_page)
        
        # Select and scroll to new row
        table.selectRow(new_row)
        table.scrollToItem(
            table.item(new_row, 0),
            QAbstractItemView.EnsureVisible
        )
        
        # Update current image path if needed
        if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images:
            if 0 <= new_row < len(self.main_window.displayed_images):
                image_path = self.main_window.displayed_images[new_row]
                if hasattr(self.main_window, '_set_current_image_path_with_sync'):
                    self.main_window._set_current_image_path_with_sync(image_path)
                else:
                    self.main_window.current_image_path = image_path

    def open_browse_view(self, index: int):
        # print(f"view_manager.py: ***** open_browse_view: index is {index}")
        """Open image in browse view mode"""
        # Get image path from displayed_images or thumbnail widgets
        if self.main_window.displayed_images and index < len(self.main_window.displayed_images):
            image_path = self.main_window.displayed_images[index]
        else:
            return
        
        # CRITICAL: Check if we should return to list view
        # The flag might be set by _open_browse_from_list or open_current_browse_view
        # But we also need to check if list_view_table exists and is visible, as current_view_mode
        # might have been reset to thumbnail by the time we get here
        return_to_list_before = getattr(self.main_window, '_return_to_list_view', False)
        
        if not return_to_list_before:
            # Check if list view table exists and is the current widget in stacked widget
            if (hasattr(self.main_window, 'list_view_table') and self.main_window.list_view_table and
                hasattr(self.main_window, 'stacked_widget') and self.main_window.stacked_widget):
                current_widget_index = self.main_window.stacked_widget.currentIndex()
                current_mode = getattr(self.main_window, 'current_view_mode', None)
                
                if current_widget_index == 2:  # List view is index 2
                    self.main_window._return_to_list_view = True
                else:
                    if current_mode == 'list':
                        self.main_window._return_to_list_view = True
        
        # Set current_image_path first - this is the source of truth
        # Use sync method to ensure proper synchronization with FileDataModel
        if hasattr(self.main_window, '_set_current_image_path_with_sync'):
            self.main_window._set_current_image_path_with_sync(image_path)
        else:
            self.main_window.current_image_path = image_path
        
        # ALWAYS derive both current_index and highlight_index from current_image_path by finding it in displayed_images
        # Never trust index variables - file path is the final truth
        try:
            if self.main_window.displayed_images:
                # Find the actual index of this file path in displayed_images
                actual_index = self.main_window.displayed_images.index(image_path)
                self.main_window.current_index = actual_index
                self.main_window.highlight_index = actual_index
            else:
                # Fallback only if displayed_images is empty
                self.main_window.current_index = index
                self.main_window.highlight_index = index
        except (ValueError, AttributeError):
            # If path not found, fallback to provided index
            self.main_window.current_index = index
            self.main_window.highlight_index = index
        
        # Update canvas highlighting - but don't call highlight_image() which might trigger navigation
        # Just update the canvas directly to avoid side effects
        if self.main_window.thumbnail_container:
            self.main_window.thumbnail_container.set_highlighted_index(self.main_window.highlight_index)
        
        if self.main_window.current_view_mode == 'browse':
            self.main_window.manage_sidebar_visibility_for_view_mode('browse')
            # Ensure image container is properly sized for current screen
            if hasattr(self.main_window, 'image_container'):
                available_size = self.main_window.get_effective_display_size()
                self.main_window.image_container.resize(available_size)
            self._setup_cursor_manager()
            self.main_window.show_image(self.main_window.current_image_path, self.main_window.current_index)
            self.main_window.start_background_thumbnail_loading_if_needed() # DGN Trying preloading thunbs in background

        else:
            # Reset fullscreen input ready flag initially
            self.main_window.browse_view_input_ready = False
            
            self.main_window.stacked_widget.setCurrentIndex(1)
            # Set browse mode after setting up the view
            self.main_window.current_view_mode = 'browse'
            if hasattr(self.main_window, '_emit_view_mode_changed'):
                self.main_window._emit_view_mode_changed()
            self.main_window.browse_view_action.setEnabled(False)
            
            # Update browse view widget background with current theme shell color
            if hasattr(self.main_window, 'stacked_widget') and self.main_window.stacked_widget.count() > 1:
                browse_view_widget = self.main_window.stacked_widget.widget(1)
                if browse_view_widget:
                    browse_view_widget.setStyleSheet(get_active_theme().browse_view_shell_stylesheet())
            
            # Manage sidebar visibility for browse mode (handles right sidebar too)
            self.main_window.manage_sidebar_visibility_for_view_mode('browse')
            
            # Ensure image container is properly sized for current screen
            if hasattr(self.main_window, 'image_container'):
                available_size = self.main_window.get_effective_display_size()
                self.main_window.image_container.resize(available_size)
            
            # Update status bar sections for browse mode
            self.main_window.update_status_bar_fit_mode()
            
            # Update filename menu text and enabled state
            self.main_window.update_filename_menu_text()
            
            # Prime and enable menu keys for view change (aboutToShow logic + shortcut registration)
            if hasattr(self.main_window, 'menu_manager'):
                self.main_window.menu_manager.prime_menu_keys_for_view_change()
            
            self._setup_cursor_manager()
            self.main_window.show_image(self.main_window.current_image_path, self.main_window.current_index)
            # show_image() already calls _update_status_bar_current_image(), but ensure it's called here too
            # to handle any edge cases where show_image might not complete
            self.main_window.update_status_bar_current_image()
            
            # Don't switch to OS fullscreen mode - just switch to fullscreen view
            # OS fullscreen is controlled by --fullscreen flag or Cmd+F toggle
            
            if should_preserve_window_focus(self.main_window):
                self.main_window.browse_view_input_ready = True
            else:
                self.main_window.activateWindow()
                QTimer.singleShot(50, self._ensure_fullscreen_focus)

        # No need to sync highlight_index here - we already set it correctly above based on the file path
        # The file path (current_image_path) is the source of truth, and we've already derived
        # both current_index and highlight_index from it

    def close_browse_view(self):
        """Close browse mode"""
        self.close_browse_view_action()
        
        # Check if container dimensions changed since last grid calculation
        if (hasattr(self.main_window, 'cached_container_width') and hasattr(self.main_window, 'cached_container_height') and
            self.main_window.cached_container_width is not None and self.main_window.cached_container_height is not None):
            
            current_display_size = self.main_window.get_effective_display_size()
            current_width = current_display_size.width()
            current_height = current_display_size.height()
            
            # If dimensions changed, recalculate grid layout but preserve loaded pixmaps.
            if (current_width != self.main_window.cached_container_width or 
                current_height != self.main_window.cached_container_height):
                if (self.main_window.displayed_images and
                        hasattr(self.main_window, 'thumbnail_container') and
                        self.main_window.thumbnail_container and
                        hasattr(self.main_window.thumbnail_container.canvas, 'reorder_thumbnails')):
                    self.main_window.current_thumbnail_size, _, _ = (
                        self.main_window.thumbnail_operations_manager.calculate_grid_for_images(
                            len(self.main_window.displayed_images)
                        )
                    )
                    canvas = self.main_window.thumbnail_container.canvas
                    canvas.thumbnail_size = self.main_window.current_thumbnail_size
                    canvas.reorder_thumbnails(
                        self.main_window.displayed_images, force_recalculate_grid=True)
                    self.main_window.cached_container_width = current_width
                    self.main_window.cached_container_height = current_height
                else:
                    self.main_window.refresh_directory()
        
        # Note: Removed duplicate _force_resize_event call here - it's already called in close_browse_view_action()

    def _delayed_browse_view_cleanup(self):
        """Batch delayed operations after closing browse view to avoid GIL deadlock.
        
        CRITICAL: This batches multiple delayed operations into a single QTimer.singleShot()
        call to prevent GIL contention when worker threads are active. Multiple QTimer.singleShot()
        calls each require dropping/reacquiring the GIL, which can deadlock when worker threads
        are waiting to acquire the GIL.
        """
        # Force update the preview if it should be visible
        if hasattr(self.main_window, 'preview_widget') and self.main_window.preview_widget:
            self.main_window.update_preview_if_visible()
        
        # Sync tree with current image when returning to thumbnail - ensures tree is expanded
        # and directory highlighted even if initial highlight_image ran before tree was ready
        if (self.main_window.current_view_mode == 'thumbnail' and
            hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler and
            self.main_window.file_tree_handler.is_tree_initialized() and
            self.main_window._is_file_tree_showing()):
            self.main_window.file_tree_handler.highlight_current_file()
        
        # Force a resize event to ensure proper layout update after fullscreen exit
        # The flag will be reset in _update_layout_after_splitter_resize when it's called
        # via the splitter resize timer, avoiding the need for another timer call here.
        self.main_window.force_resize_event()

    def close_browse_view_action(self):
        """Close browse mode"""
        if self.main_window.current_view_mode == 'browse':
            if hasattr(self.main_window, '_cancel_browse_image_history_debounce'):
                self.main_window._cancel_browse_image_history_debounce()
            # print(f"view_manager.py: close_browse_view_action: closing browse view and current image path is {self.main_window.current_image_path}")
            # Set flag to prevent status bar updates during fullscreen exit
            self.main_window.browse_view_exit_in_progress = True
            
            current_count = len(self.main_window.displayed_images) if hasattr(self.main_window, 'displayed_images') and self.main_window.displayed_images else 0
            
            # Reset fullscreen input ready flag
            self.main_window.browse_view_input_ready = False
            
            # Check if we should return to list view
            return_to_list = getattr(self.main_window, '_return_to_list_view', False)
            
            if return_to_list:
                self.main_window.stacked_widget.setCurrentIndex(2)  # List view is index 2
                self.main_window.current_view_mode = 'list'
                # Restore sidebar BEFORE emitting view mode changed (same as thumbnail branch)
                self.main_window.manage_sidebar_visibility_for_view_mode('list')
                if hasattr(self.main_window, '_emit_view_mode_changed'):
                    self.main_window._emit_view_mode_changed()
                self.main_window._return_to_list_view = False  # Reset flag
                # Update list view to highlight current image
                self.update_list_view()
            else:
                self.main_window.stacked_widget.setCurrentIndex(0)
                self.main_window.current_view_mode = 'thumbnail'
                # Restore sidebar BEFORE emitting view mode changed, so _immediate_splitter_update
                # sees correct layout (avoids refresh-then-resize double refresh when tree visible)
                self.main_window.manage_sidebar_visibility_for_view_mode('thumbnail')
                if hasattr(self.main_window, '_emit_view_mode_changed'):
                    self.main_window._emit_view_mode_changed()
                # Ensure thumbnails are populated when exiting browse mode
                if self.main_window.displayed_images:
                    canvas = (
                        self.main_window.thumbnail_container.canvas
                        if hasattr(self.main_window, 'thumbnail_container')
                        and self.main_window.thumbnail_container
                        else None
                    )
                    current_paths = (
                        [thumb.image_path for thumb in canvas.thumbnails]
                        if canvas and canvas.thumbnails
                        else None
                    )
                    if current_paths != self.main_window.displayed_images:
                        if hasattr(self.main_window, 'create_immediate_placeholders'):
                            self.main_window.create_immediate_placeholders()
                    elif canvas and canvas.thumbnails:
                        if not (0 <= self.main_window.highlight_index < len(self.main_window.displayed_images)):
                            idx = getattr(self.main_window, 'current_index', 0) or 0
                            self.main_window.highlight_index = min(
                                idx, len(self.main_window.displayed_images) - 1
                            )
                        self.main_window.thumbnail_container.set_highlighted_index(
                            self.main_window.highlight_index
                        )
                        self.main_window.ensure_highlighted_visible()
            self.main_window.browse_view_action.setEnabled(True)
            
            # Reset preview widget state to ensure it works properly after returning from browse mode
            if hasattr(self.main_window, 'preview_widget') and self.main_window.preview_widget:
                self.main_window.preview_widget.reset_state()
            
            # Don't apply layout during fullscreen exit - it clears all widgets!
            # The status bar layout should already be correct from the initial setup
            
            # Update filename menu text and enabled state
            self.main_window.update_filename_menu_text()
            
            # Prime and enable menu keys for view change (aboutToShow logic + shortcut registration)
            if hasattr(self.main_window, 'menu_manager'):
                self.main_window.menu_manager.prime_menu_keys_for_view_change()
            
            if self.main_window.cursor_manager:
                self.main_window.cursor_manager.disable()
                self.main_window.cursor_manager = None
            
            # Update status bar sections for thumbnail mode
            self.main_window.update_status_bar_sections()
            
            # Ensure highlight is properly set before making it visible
            self.main_window.highlight_image()
            
            # Update window title for active image
            self.main_window.image_display_manager.update_window_title_for_active_image()
            
            # CRITICAL: Check for file changes when exiting browse mode (in non-specific-files mode)
            # Only refresh if files actually changed to avoid unnecessary thumbnail flashing
            # Skip refresh in specific_files_active mode to avoid triggering state saves
            # that could interfere with stack navigation
            if not getattr(self.main_window, 'specific_files_active', False):
                # Use efficient refresh that only updates if files changed
                # Emit event for RefreshManager to handle
                if hasattr(self.main_window, 'event_bus') and self.main_window.event_bus:
                    from event_bus import FILES_CHANGED_ON_DISK
                    self.main_window.event_bus.emit(
                        FILES_CHANGED_ON_DISK,
                        getattr(self.main_window, 'current_directory', '') or ''
                    )
                else:
                    self.main_window._check_and_refresh_if_changed()
            
            # CRITICAL FIX: Batch all delayed operations into a single QTimer.singleShot() call
            # to prevent GIL deadlock. Multiple QTimer.singleShot() calls each require dropping
            # the GIL to connect signals, which can deadlock when worker threads are waiting
            # to acquire the GIL. Batching into a single call reduces GIL contention.
            QTimer.singleShot(100, self._delayed_browse_view_cleanup)

    def toggle_file_tree(self):
        """Toggle the visibility of the file tree and resize canvas accordingly"""
        if self.main_window.toggle_file_tree_action.isChecked():
            # Hide preview if it's visible (they can't both be shown at the same time)
            if hasattr(self.main_window, 'preview_widget') and self.main_window.preview_widget.is_visible():
                self.main_window.preview_widget.hide()
                self.main_window.preview_widget.preview_visible = False
            
            # Show file tree - initialize it if not already done
            self.main_window.ensure_tree_initialized()
            self.main_window.tree_container.show()
            
            # Restore splitter sizes using sidebar width
            # Preserve right sidebar width - only update left sidebar and main content
            total_width = self.main_window.main_splitter.width()
            current_sizes = self.main_window.main_splitter.sizes()
            right_width = current_sizes[2] if len(current_sizes) > 2 else (self.main_window.right_sidebar_width if hasattr(self.main_window, 'right_sidebar_visible') and self.main_window.right_sidebar_visible else 0)
            left_width = self.main_window.sidebar_width
            main_width = total_width - left_width - right_width
            self.main_window.main_splitter.setSizes([left_width, main_width, right_width])
            self.main_window.toggle_file_tree_action.setText('Hide File Tree')
            self.main_window.file_tree_visible = True
            # Give focus to the tree when it's shown - do this immediately and with a delay
            self.main_window.focus_tree()
            QTimer.singleShot(150, self.main_window.focus_tree)
            
            # Highlight current directory after tree is shown (delay to ensure tree is ready and thumbnails may be loaded)
            def highlight_current():
                if (hasattr(self.main_window, 'file_tree_handler') and 
                    self.main_window.file_tree_handler and 
                    self.main_window.file_tree_handler.is_tree_initialized()):
                    # CRITICAL: Don't override user-requested directory selection
                    if not self.main_window.file_tree_handler.user_requested_directory:
                        self.main_window.file_tree_handler.highlight_current_directory()
            QTimer.singleShot(200, highlight_current)
        else:
            # Hide file tree
            self.main_window.tree_container.hide()
            # Preserve right sidebar width - only update left sidebar and main content
            total_width = self.main_window.main_splitter.width()
            current_sizes = self.main_window.main_splitter.sizes()
            right_width = current_sizes[2] if len(current_sizes) > 2 else (self.main_window.right_sidebar_width if hasattr(self.main_window, 'right_sidebar_visible') and self.main_window.right_sidebar_visible else 0)
            main_width = total_width - right_width
            self.main_window.main_splitter.setSizes([0, main_width, right_width])
            self.main_window.toggle_file_tree_action.setText('Show File Tree')
            self.main_window.file_tree_visible = False
            # Give focus to the canvas when tree is hidden
            QTimer.singleShot(150, self.main_window.focus_canvas)
        
        # Save the setting
        self.main_window.config.update_setting('file_tree_visible', self.main_window.file_tree_visible)
        
        # Handle browse mode - resize image container when tree view visibility changes
        if self.main_window.current_view_mode == 'browse':
            if hasattr(self.main_window, 'image_container'):
                mw = self.main_window
                old_w = mw.cached_container_width
                old_h = mw.cached_container_height
                available_size = mw.get_effective_display_size()
                mw.image_container.resize(available_size)
                mw._handle_browse_viewport_resize_after_container_change(old_w, old_h)
        
        # Update MAX_THUMBNAIL_SIZE based on new container dimensions after tree show/hide
        QTimer.singleShot(50, self.main_window.update_max_thumbnail_size)
        
        # Force canvas to recalculate layout after toggle
        QTimer.singleShot(100, self.main_window.update_layout_after_splitter_resize)
        
        # Also force immediate update for better responsiveness
        self.main_window.main_content_widget.updateGeometry()
        self.main_window.main_content_widget.update()

    def _setup_cursor_manager(self):
        """Initialize and start cursor manager for browse mode"""
        # Clean up existing cursor manager if any
        if self.main_window.cursor_manager:
            self.main_window.cursor_manager.cleanup()
        
        # Hide cursor only over the image canvas, not sidebars/dialogs/status bar
        hide_widget = (
            getattr(self.main_window, 'image_container', None)
            or getattr(self.main_window, '_browse_view_root_widget', None)
            or self.main_window
        )
        self.main_window.cursor_manager = CursorManager(hide_widget, hide_delay_ms=2000, parent=self.main_window)
        # Start the cursor manager (starts the hide timer)
        self.main_window.cursor_manager.start()

    def open_current_browse_view(self):
        if not self.main_window.displayed_images:
            return
        
        # CRITICAL: Capture view mode BEFORE stopping slideshows, as stop_slideshow() changes current_view_mode to 'thumbnail'
        captured_view_mode = getattr(self.main_window, 'current_view_mode', None)
        captured_stacked_index = self.main_window.stacked_widget.currentIndex() if hasattr(self.main_window, 'stacked_widget') else None
        is_list_view_before_stop = (captured_view_mode == 'list') or (captured_stacked_index == 2)  # List view is index 2
        
        # Stop the slideshow if running (this may change current_view_mode to 'thumbnail')
        self.main_window.slideshow_manager.stop_slideshow()
        self.main_window.slideshow2_manager.stop_slideshow2()

        # Check if multiple files are selected - if so, view them as a group
        if len(self.main_window.selected_files) > 1:
            self.open_selected_files_fullscreen()
            return
        
        # If in list view, use highlight_index (which is already set correctly for canvas-based list view)
        # Use the CAPTURED values from before stop_slideshow() calls, as those methods change the view mode
        is_list_view = is_list_view_before_stop
        
        # For canvas-based list view, highlight_index is already correct, so we can proceed
        # The old QTableWidget-based list view check is no longer needed
        
        # Open the currently highlighted image in browse mode
        if 0 <= self.main_window.highlight_index < len(self.main_window.displayed_images):
            # Store previous view mode before opening browse
            # Use the CAPTURED values from before stop_slideshow() calls, as those methods change the view mode
            if is_list_view_before_stop:
                self.main_window._return_to_list_view = True
            self.open_browse_view(self.main_window.highlight_index)
    
    def open_selected_files_fullscreen(self):
        """Open all selected files in new level"""
        selected_files = self.main_window.selection_manager.get_selected_files()
        
        if not selected_files:
            if self.main_window.status_notification:
                self.main_window.status_notification.show_message("No files selected. Use ⌘+Shift+arrow keys or ⌘+click to select files first.")
            return
        
        if len(selected_files) == 1:
            # Find the index of the selected file
            displayed_images = self.main_window.displayed_images
            for idx, image_path in enumerate(displayed_images):
                if image_path == selected_files[0]:
                    self.open_browse_view(idx)
                    break
        else:
            # Save current state before switching to selected files view
            # This creates a new "pseudo directory" level that should be saved
            # We need to ensure the state is captured BEFORE switching to specific files mode
            if hasattr(self.main_window, 'directory_stack_history_handler'):
                # Force immediate state capture to avoid timing issues
                current_state = self.main_window.directory_stack_history_handler.capture_current_state()
                if current_state and not self.main_window.directory_stack_history_handler.is_duplicate_state(current_state):
                    self.main_window.directory_stack_history_handler.backward_stack.append(current_state)
                    self.main_window.directory_stack_history_handler.forward_stack.clear()  # Clear forward stack
            
            # Process multiple selected files as if they came from the API
            # This allows multi-selection to be used for viewing groups of images
            configuration = {'files': selected_files}
            self.main_window.refresh_from_configuration(configuration)
            self.main_window.clear_selection()

    def _ensure_fullscreen_focus(self):
        """Ensure proper focus for browse keyboard event handling"""
        if self.main_window.current_view_mode != 'browse':
            return
        if should_preserve_window_focus(self.main_window):
            self.main_window.browse_view_input_ready = True
            return
        self.main_window.raise_()
        self.main_window.browse_view_input_ready = True
