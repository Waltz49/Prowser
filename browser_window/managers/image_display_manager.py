#!/usr/bin/env python3
"""
Image Display Manager
Handles image display, highlighting, and navigation
"""

from typing import Optional
from PySide6.QtCore import QTimer


class ImageDisplayManager:
    """Manages image display and highlighting operations"""
    
    def __init__(self, main_window):
        """
        Initialize the image display manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
    
    def highlight_image(self):
        """Sync navigation state and apply highlight via event subscribers.

        Canvas highlight is handled by ThumbnailHighlightSubscriber.
        Status bar, preview, tree, and title use NavigationUiSubscriber.
        This method remains for legacy callers when model events do not re-fire.
        """
        displayed = self.main_window.get_displayed_images()
        self.main_window._sync_highlight_index_from_current_image_path(displayed)

        thumb_sub = getattr(self.main_window, "thumbnail_highlight_subscriber", None)
        if thumb_sub:
            scroll = (
                getattr(self.main_window, "current_view_mode", None) == "thumbnail"
                and not getattr(self.main_window, "browse_view_exit_in_progress", False)
            )
            thumb_sub.apply_from_window_state(scroll=scroll)
        elif getattr(self.main_window, "browse_view_exit_in_progress", False):
            if getattr(self.main_window, "current_view_mode", None) != "list":
                QTimer.singleShot(100, self.main_window.ensure_highlighted_visible)

        current_image_path = self.get_current_image_path()
        if current_image_path:
            nav_ui = getattr(self.main_window, "navigation_ui_subscriber", None)
            if nav_ui:
                nav_ui.apply_for_path(current_image_path, displayed)
    
    def display_current_image(self):
        """Display the current highlighted image in the main view"""
        # Prevent opening browse view when loading a directory
        if getattr(self.main_window, '_loading_directory_mode', False):
            return
        if not (0 <= self.main_window.highlight_index < len(self.main_window.displayed_images)):
            return
            
        # CRITICAL: Use current_image_path as source of truth, not highlight_index
        current_image_path = self.main_window.get_current_image_path()
        if current_image_path:
            # Load and display the image
            self.main_window.show_image(current_image_path, self.main_window.highlight_index)
            
            # Switch to main image view
            self.main_window.stacked_widget.setCurrentIndex(1)
            self.main_window.current_view_mode = 'browse'
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager._setup_cursor_manager()
            
            # Prime and enable menu keys for view change
            if hasattr(self.main_window, 'menu_manager'):
                self.main_window.menu_manager.prime_menu_keys_for_view_change()
            
            # Update the image display
            self.main_window.update_image_display()
    
    def get_current_image_path(self) -> Optional[str]:
        """Get the current image path (FileDataModel via main window)."""
        if hasattr(self.main_window, "get_current_image_path"):
            return self.main_window.get_current_image_path()
        if getattr(self.main_window, "file_data_model", None):
            return self.main_window.file_data_model.get_current_image_path()
        return None
    
    def set_current_image_by_path(self, image_path: Optional[str], fallback_index: Optional[int] = None):
        """Set current image by path (source of truth)"""
        self.main_window.set_current_image_by_path(image_path, fallback_index)
    
    def _sync_highlight_index_from_current_image_path(self, displayed=None):
        """Sync highlight_index from current_image_path (source of truth)"""
        self.main_window._sync_highlight_index_from_current_image_path(displayed)
    
    def ensure_highlighted_visible(self):
        """Ensure the highlighted thumbnail is visible in the viewport"""
        displayed = self.main_window.get_displayed_images()
        if displayed and (0 <= self.main_window.highlight_index < len(displayed)):
            # Check if the thumbnail is fully visible in the viewport
            thumbnail_rect = self.main_window.thumbnail_container.get_thumbnail_rect(self.main_window.highlight_index)
            if thumbnail_rect:
                # For canvas implementation, use canvas scroll method with proper status bar accounting
                self.main_window.thumbnail_container.canvas.scroll_to_highlighted()
                # Do NOT call on_scroll_changed() - scroll_bar.setValue() triggers valueChanged when we scroll
                self.main_window.scroll_area.viewport().update()
    
    def update_image_display(self):
        """Update the image display"""
        if hasattr(self.main_window, 'browse_view_handler') and self.main_window.browse_view_handler:
            self.main_window.browse_view_handler.update_image_display()
    
    def update_number_overlay(self):
        """Update the number overlay on the image"""
        if hasattr(self.main_window, 'browse_view_handler') and self.main_window.browse_view_handler:
            self.main_window.browse_view_handler.update_number_overlay()
    
    def update_filename_for_new_image(self):
        """Update filename display for new image"""
        if hasattr(self.main_window, 'browse_view_handler') and self.main_window.browse_view_handler:
            self.main_window.browse_view_handler.update_filename_for_new_image()
    
    def update_filename_menu_text(self):
        """Update filename menu text"""
        if hasattr(self.main_window, 'menu_manager') and self.main_window.menu_manager:
            self.main_window.menu_manager.update_filename_menu_text()
    
    def update_window_title_for_active_image(self):
        """Update the window title to show the full path of the active image"""
        # CRITICAL: Use current_image_path as source of truth, not highlight_index
        current_image_path = self.get_current_image_path()
        if current_image_path:
            self.main_window.setWindowTitle(f"Prowser - {current_image_path}")
