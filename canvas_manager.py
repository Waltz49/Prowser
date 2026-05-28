#!/usr/bin/env python3
"""
Canvas Manager for Image Browser
Manages the canvas-based thumbnail display and integrates with the existing image browser system
"""

# Standard library imports
import os
from typing import List, Optional, Set

# Third-party imports
from PySide6.QtCore import QMutexLocker, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

# Local imports
from thumbnail_canvas import ThumbnailCanvas
from theme_service import get_active_theme
from utils import entry_debug_wrapper
from event_bus import THUMBNAIL_CLICKED
# Configurable sizing constants for the overlay
OVERLAY_HEIGHT = 8  # Height of the overlay band in pixels
 

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

    def _sync_thumbnail_chrome_colors(self):
        """Match top band + scroll viewport to the canvas paint background (ThumbnailCanvas paintEvent fillRect)."""
        th = get_active_theme()
        # Must use default_background_color_hex, not default_image_*: paintEvent fills the canvas with
        # tc.DEFAULT_BACKGROUND_COLOR; default_image_background applies only inside non-current cell rects.
        bg_hex = th.default_background_color_hex
        bg = QColor(bg_hex)
        self.black_overlay.setStyleSheet(
            f"QWidget {{ background-color: {bg_hex}; border: none; }}"
        )
        vp = self.scroll_area.viewport()
        if vp is not None:
            pal = vp.palette()
            pal.setColor(QPalette.ColorRole.Window, bg)
            pal.setColor(QPalette.ColorRole.Base, bg)
            vp.setPalette(pal)
            vp.setAutoFillBackground(True)

    def refresh_theme_styles(self):
        """Reapply top band color and repaint canvas after global theme change."""
        self._sync_thumbnail_chrome_colors()
        self._update_black_overlay()
        if getattr(self, "canvas", None):
            self.canvas.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_black_overlay()
        
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
