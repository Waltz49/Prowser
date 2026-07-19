#!/usr/bin/env python3
"""
Image Display Manager
Handles image display, highlighting, and navigation
"""

import os
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
        """Highlight the current image.
        
        CRITICAL: This method ALWAYS derives highlight_index from current_image_path (the source of truth).
        It never uses highlight_index as a source of truth - it syncs highlight_index FROM current_image_path.
        """
        # PERFORMANCE OPTIMIZATION: Cache these values at the start to avoid redundant calls
        # File path remains the source of truth - we're just caching the lookup results
        displayed = self.main_window.get_displayed_images()
        current_image_path = self.main_window.get_current_image_path()
        
        # CRITICAL: First, sync highlight_index from current_image_path (the source of truth)
        # This ensures highlight_index is always derived from the file path, never the other way around
        # Pass cached displayed list to avoid redundant call
        self.main_window._sync_highlight_index_from_current_image_path(displayed)
        
        # Only add directory to history if directory changed and not in specific files mode
        if current_image_path and not getattr(self.main_window, 'specific_files_active', False):
            current_dir = os.path.dirname(current_image_path)
            last_dir = getattr(self.main_window, '_last_directory_in_history', None)
            if current_dir != last_dir:
                self.main_window.directory_history_handler_for_menu.add_directory(current_image_path)
                self.main_window._last_directory_in_history = current_dir
        
        if self.main_window.browse_view_exit_in_progress:
            # During fullscreen exit, still allow highlighting but skip status bar updates
            # Update canvas highlighting based on view mode
            if self.main_window.current_view_mode == 'list':
                if hasattr(self.main_window, 'list_view_container') and self.main_window.list_view_container:
                    self.main_window.list_view_container.set_highlighted_index(self.main_window.highlight_index)
            else:
                if self.main_window.thumbnail_container:
                    self.main_window.thumbnail_container.set_highlighted_index(self.main_window.highlight_index)
            
            # Use a timer to delay scrolling until thumbnails are fully laid out
            if self.main_window.current_view_mode != 'list':
                QTimer.singleShot(100, self.main_window.ensure_highlighted_visible)
            
            # CRITICAL: Still sync UI components when exiting browse view
            # This ensures tree, preview, and Information sidebar stay in sync when returning to thumbnail mode
            if current_image_path:
                # Update preview widget if visible
                if hasattr(self.main_window, 'update_preview_if_visible'):
                    self.main_window.update_preview_if_visible()
                
                # Update file tree highlighting (but not during slideshow, only when tree is showing)
                if (self.main_window.current_view_mode != 'slideshow' and 
                    self.main_window._is_file_tree_showing() and
                    hasattr(self.main_window, 'file_tree_handler') and 
                    self.main_window.file_tree_handler.is_tree_initialized()):
                    self.main_window.file_tree_handler.highlight_current_file()
            return
        
        # Update canvas highlighting based on view mode
        if self.main_window.current_view_mode == 'list':
            # Update list view highlighting
            if hasattr(self.main_window, 'list_view_container') and self.main_window.list_view_container:
                self.main_window.list_view_container.set_highlighted_index(self.main_window.highlight_index)
                # Don't scroll in list view - let user control scrolling manually
                # Scrolling is handled by scroll_to_highlighted() when explicitly needed (e.g., clicks)
        else:
            # Update thumbnail view highlighting
            if self.main_window.thumbnail_container:
                self.main_window.thumbnail_container.set_highlighted_index(self.main_window.highlight_index)
        
        # Use cached current_image_path instead of calling get_current_image_path() again
        if current_image_path:
            self.main_window._current_highlighted_file_directory = os.path.dirname(current_image_path)
        
        # CRITICAL: Sync all UI components with current image state
        # Update these components in a consistent order to ensure proper synchronization
        
        # 1. Update status bar with current image info
        # Skip if already updated by set_current_image_by_path (config sync) - avoids duplicate
        # metadata loading (_ensure_metadata_exists, get_image_info) which causes slowness
        if not getattr(self.main_window, 'browse_view_exit_in_progress', False):
            if current_image_path:
                last_updated = getattr(self.main_window, '_last_status_bar_image_path', None)
                if last_updated != current_image_path:
                    self.main_window.update_status_bar_current_image(current_image_path, displayed)
                    self.main_window._last_status_bar_image_path = current_image_path
        
        # 2. Update preview widget if visible
        if hasattr(self.main_window, 'update_preview_if_visible'):
            self.main_window.update_preview_if_visible()
        
        # 3. Update file tree highlighting (but not during slideshow, only when tree is showing)
        if current_image_path and self.main_window.current_view_mode != 'slideshow':
            if (self.main_window._is_file_tree_showing() and 
                hasattr(self.main_window, 'file_tree_handler') and 
                self.main_window.file_tree_handler.is_tree_initialized()):
                self.main_window.file_tree_handler.highlight_current_file()
        
        # Only handle thumbnail scrolling when in thumbnail view (not browse/slideshow - those don't show thumbnails)
        # Slideshow is fast because it skips this; browse was doing unnecessary scroll work
        if (self.main_window.current_view_mode == 'thumbnail' and 
            displayed and (0 <= self.main_window.highlight_index < len(displayed))):
            # Check if the thumbnail is fully visible in the viewport
            if (hasattr(self.main_window, 'thumbnail_container') and 
                self.main_window.thumbnail_container):
                thumbnail_rect = self.main_window.thumbnail_container.get_thumbnail_rect(self.main_window.highlight_index)
                if thumbnail_rect:
                    # For canvas implementation, use canvas scroll method with proper status bar accounting
                    self.main_window.thumbnail_container.canvas.scroll_to_highlighted()
                    # Do NOT call on_scroll_changed() here - when scroll_to_highlighted actually scrolls,
                    # scroll_bar.setValue() triggers valueChanged which is already connected to on_scroll_changed.
                    # Calling it unconditionally caused _restart_thumbnail_loading_for_visible on every image
                    # change (even when thumbnail already visible), causing major slowness.
                    if hasattr(self.main_window, 'scroll_area') and self.main_window.scroll_area:
                        self.main_window.scroll_area.viewport().update()

        self.update_window_title_for_active_image()
    
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
    
    def toggle_thumbnail_filename_overlay(self):
        """Toggle thumbnail filename overlay"""
        if hasattr(self.main_window, 'browse_view_handler') and self.main_window.browse_view_handler:
            self.main_window.browse_view_handler.toggle_filename_overlay()
    
    def toggle_information_display(self):
        """Toggle Information sidebar display"""
        if hasattr(self.main_window, 'toggle_information_display'):
            self.main_window.toggle_information_display()
    
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
