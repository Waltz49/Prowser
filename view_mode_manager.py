#!/usr/bin/env python3
"""
View Mode Manager
Handles view mode switching (thumbnail, browse, slideshow, fullscreen)
"""

from PySide6.QtCore import QTimer


class ViewModeManager:
    """Manages view mode switching and transitions"""
    
    def __init__(self, main_window):
        """
        Initialize the view mode manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
    
    def toggle_viewer(self):
        """Toggle between thumbnail and browse viewer (same as F key behavior)"""
        if self.main_window.current_view_mode == 'browse':
            # In browse mode, close it and return to thumbnails
            self.main_window.close_browse_view()
        elif self.main_window.current_view_mode == 'slideshow2':
            # In slideshow2 mode, stop it and transition to browse view properly
            # Get actual index from highlight_index before stopping
            if hasattr(self.main_window.slideshow2_manager, 'image_indices') and self.main_window.slideshow2_manager.image_indices and 0 <= self.main_window.slideshow2_manager.highlight_index < len(self.main_window.slideshow2_manager.image_indices):
                actual_index = self.main_window.slideshow2_manager.image_indices[self.main_window.slideshow2_manager.highlight_index]
            else:
                actual_index = self.main_window.slideshow2_manager.highlight_index
            # Stop slideshow2 and transition to browse mode
            self.main_window.slideshow2_manager.stop_slideshow2(target_mode='browse')
            # Reset image label after stopping slideshow2 to ensure clean transition
            self.main_window.slideshow2_manager.reset_image_label_for_fullscreen()
            # Open browse view with the current image
            self.main_window.slideshow2_manager.open_browse_view(actual_index)
        elif self.main_window.current_view_mode == 'slideshow3':
            # In slideshow3 mode, stop it and transition to browse view properly
            displayed = self.main_window.get_displayed_images() if hasattr(self.main_window, 'get_displayed_images') else []
            if displayed and hasattr(self.main_window, 'highlight_index'):
                if 0 <= self.main_window.highlight_index < len(displayed):
                    actual_index = self.main_window.highlight_index
                    # Stop slideshow3
                    self.main_window.slideshow3_manager.stop_slideshow3()
                    # Open browse view with the current image
                    QTimer.singleShot(100, lambda: self.open_browse_view(actual_index))
        else:
            # In thumbnail mode (or other modes), open browse
            self.main_window.open_current_browse_view()
    
    def toggle_slideshow(self):
        """Toggle slideshow mode"""
        
        # If other slideshows are running, stop them first
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()
        
        if self.main_window.current_view_mode == 'slideshow':
            self.main_window.slideshow_manager.stop_slideshow()
        else:
            self.main_window.slideshow_manager.start_slideshow()
    
    def reset_image_label_for_fullscreen(self):
        """Reset the image label for browse display"""
        self.main_window.browse_view_handler.reset_image_label_for_browse_view()
    
    def set_random_mode(self):
        """Set random mode - always reshuffles, never toggles"""
        current_mode = getattr(self.main_window, 'current_view_mode', '')
        # If in list view, exit to thumbnail view first
        if current_mode == 'list':
            self.main_window.stacked_widget.setCurrentIndex(0)
            self.main_window.current_view_mode = 'thumbnail'
            if hasattr(self.main_window, 'list_view_action'):
                self.main_window.list_view_action.setChecked(False)
            self.main_window.manage_sidebar_visibility_for_view_mode('thumbnail')
            if hasattr(self.main_window, 'menu_manager'):
                self.main_window.menu_manager.prime_menu_keys_for_view_change()
        
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        from sort_mode import SortMode
        
        # Preserve current image path BEFORE reshuffling
        current_image_path = self.main_window.get_current_image_path()
        
        # Always set random mode and reshuffle (don't toggle)
        # If already in random mode, we still want to reshuffle
        was_random = self.main_window.current_sort_mode == SortMode.RANDOM
        
        # Set random mode (this will reshuffle)
        self.main_window.set_sort_mode(SortMode.RANDOM)
        
        # Verify current image was preserved
        final_image_path = self.main_window.get_current_image_path()
        if current_image_path and current_image_path != final_image_path:
            # Try to restore it
            displayed_after = self.main_window.get_displayed_images()
            if current_image_path in displayed_after:
                self.main_window.set_current_image_by_path(current_image_path, fallback_index=0)
                self.main_window.highlight_image()
        
        # Show status message
        if self.main_window.status_notification:
            if was_random:
                self.main_window.status_notification.show_message("Random Sort (reshuffled)")
            else:
                self.main_window.status_notification.show_message("Random Sort")
    
    def open_browse_view(self, index: int):
        """Open image in browse mode"""
        # Prevent opening browse view when loading a directory
        if getattr(self.main_window, '_loading_directory_mode', False):
            return
        return self.main_window.view_manager.open_browse_view(index)
    
    def open_current_browse_view(self):
        """Open current image in browse view"""
        if not (0 <= self.main_window.highlight_index < len(self.main_window.displayed_images)):
            return
        self.open_browse_view(self.main_window.highlight_index)
    
    def _ensure_cursor_manager_inactive_in_thumbnail(self):
        """Ensure cursor manager is inactive when in thumbnail view"""
        if (self.main_window.cursor_manager and 
            self.main_window.current_view_mode not in ['browse', 'slideshow', 'slideshow2', 'slideshow3'] and 
            self.main_window.cursor_manager.is_active()):
            self.main_window.cursor_manager.hide_cursor()
    
    def _ensure_fullscreen_focus(self):
        """Ensure proper focus in fullscreen mode"""
        if self.main_window.current_view_mode == 'browse':
            if hasattr(self.main_window, 'image_container'):
                self.main_window.image_container.setFocus()
    
    def _ensure_fullscreen_focus(self):
        """Ensure proper focus in fullscreen mode"""
        if self.main_window.current_view_mode == 'browse':
            if hasattr(self.main_window, 'image_container'):
                self.main_window.image_container.setFocus()
    
    def toggle_fullscreen(self):
        """Toggle fullscreen mode"""
        self.main_window.view_manager.toggle_fullscreen()
    
    def toggle_maximized(self):
        """Toggle maximized window"""
        if self.main_window.isMaximized():
            self.main_window.showNormal()
        else:
            self.main_window.showMaximized()
    
    def enter_true_fullscreen(self):
        """Enter true macOS fullscreen"""
        if hasattr(self.main_window, 'view_manager'):
            self.main_window.view_manager.enter_true_fullscreen()
    
    def toggle_actual_size(self):
        """Toggle actual size display mode"""
        if hasattr(self.main_window, 'browse_view_handler') and self.main_window.browse_view_handler:
            self.main_window.browse_view_handler.toggle_actual_size()
    
    def update_windowing_if_needed(self, target_file: str = None):
        """Update windowing context if we're in window mode (limit is specified)"""
        # Delegate to main window method
        return self.main_window.update_windowing_if_needed(target_file)
