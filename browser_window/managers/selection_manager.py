#!/usr/bin/env python3
"""
Selection Manager
Handles thumbnail selection and multi-selection operations
"""

from typing import List, Optional, Set
from PySide6.QtCore import QTimer
from event_bus import SELECTION_CHANGED


class SelectionManager:
    """Manages selection operations for thumbnails"""
    
    def __init__(self, main_window):
        """
        Initialize the selection manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            main_window.event_bus.subscribe(SELECTION_CHANGED, self._on_selection_changed)

    def _on_selection_changed(self, selected: Set[str], highlight_index: Optional[int] = None):
        """Handle SELECTION_CHANGED event - update canvas selection display"""
        self.update_canvas_selection(highlight_index)
    
    def select_all_thumbnails(self):
        """Select all thumbnails in thumbnail mode"""
        if self.main_window.current_view_mode != 'thumbnail':
            return
        
        if not self.main_window.displayed_images:
            return
        
        # Select all displayed images
        self.main_window.selected_files = set(self.main_window.displayed_images)
        self.main_window._emit_selection_changed()
        
        # Update highlight to first item
        if self.main_window.displayed_images:
            self.main_window.highlight_index = 0
            self.main_window.highlight_image()
    
    def clear_selection(self, hilite=True):
        """Clear all selected thumbnails"""
        # Set highlight to the last selected item before clearing
        if hasattr(self.main_window, 'most_recent_selected_index'):
            self.main_window.highlight_index = self.main_window.most_recent_selected_index #DGN
            del self.main_window.most_recent_selected_index #DGN
        elif self.main_window.selected_files:
            # Find the index of the last selected file (preserve order from displayed_images)
            last_index = -1
            for i, image_path in enumerate(self.main_window.displayed_images):
                if image_path in self.main_window.selected_files:
                    last_index = i
            if last_index >= 0:
                self.main_window.highlight_index = last_index
        
        self.main_window.selected_files.clear()
        self.main_window.range_anchor_index = None
        self.main_window._emit_selection_changed()
        # Reset cmd+arrow multi-select state
        self.main_window.cmd_multi_origin_index = None
        self.main_window.cmd_multi_axis = None
        self.main_window.cmd_multi_sign = 0
        if hilite:
            self.main_window.highlight_image() #DGN: removal is test for extra scoll problems
    
    def _get_selected_indices_for_display(self) -> set:
        """Convert selected_files to indices for visual display only"""
        indices = set()
        if not self.main_window.displayed_images:
            return indices
        for i, image_path in enumerate(self.main_window.displayed_images):
            if image_path in self.main_window.selected_files:
                indices.add(i)
        return indices
    
    def update_canvas_selection(self, highlight_index: Optional[int] = None):
        """Centralized method to update canvas selection state on grid and list views."""
        display_indices = self._get_selected_indices_for_display()
        multi = self.main_window.multi_select_mode
        for attr in ("thumbnail_container", "list_view_container"):
            container = getattr(self.main_window, attr, None)
            if not container:
                continue
            if hasattr(container, "set_selected_indices"):
                container.set_selected_indices(display_indices)
            if hasattr(container, "set_multi_select_mode"):
                container.set_multi_select_mode(multi)
            if highlight_index is not None and hasattr(container, "set_highlighted_index"):
                container.set_highlighted_index(highlight_index)
    
    def select_thumbnail(self, index: int, add_to_selection: bool = False):
        """Optimized selection logic for thumbnails."""
        if not (0 <= index < len(self.main_window.displayed_images)):
            return

        # Get the file path for this index
        file_path = self.main_window.displayed_images[index]

        # Alias for state resets below -- avoids repeated statements
        def reset_cmd_multi_state():
            self.main_window.cmd_multi_origin_index = None
            self.main_window.cmd_multi_axis = None
            self.main_window.cmd_multi_sign = 0

        # Save previous current image path before updating (needed for multi-select logic)
        previous_current_path = self.main_window.get_current_image_path()
        
        # CRITICAL: Set current image by path (source of truth) - this derives highlight_index
        self.main_window.set_current_image_by_path(file_path)
        
        if add_to_selection:
            # If multi-selection is empty, add the previous current image first (if different from clicked file)
            # This ensures the current image is part of a multiple selection when starting a new multi-selection
            if (len(self.main_window.selected_files) == 0 and
                previous_current_path and 
                previous_current_path != file_path and 
                previous_current_path not in self.main_window.selected_files):
                self.main_window.selected_files.add(previous_current_path)
            
            if (
                file_path == self.main_window.get_current_image_path()
                and not self.main_window.selected_files
                and not self.main_window.multi_select_mode
            ):
                # Start multi-select mode with initial selection
                self.main_window.selected_files.add(file_path)
                self.main_window._emit_selection_changed()
            elif file_path in self.main_window.selected_files and len(self.main_window.selected_files) > 1:
                # Deselect if already selected in multi-select mode
                self.main_window.selected_files.remove(file_path)
                self.main_window._emit_selection_changed()
            else:
                # Add to selection
                self.main_window.selected_files.add(file_path)
                self.main_window._emit_selection_changed()
            
            # Reset cmd+arrow multi-select state
            reset_cmd_multi_state()
        else:
            # Single selection - clear existing selection
            self.main_window.selected_files.clear()
            self.main_window.selected_files.add(file_path)
            self.main_window._emit_selection_changed()
            
            # Reset cmd+arrow multi-select state
            reset_cmd_multi_state()
        
        # Update highlight
        self.main_window.highlight_image()
    
    def handle_thumbnail_click(self, image_index: int, cmd_pressed: bool, shift_pressed: bool, macos_ctrl_pressed: bool = False):
        """Handle thumbnail click with support for multiple selection and range selection."""
        self.main_window.navigation_manager.handle_thumbnail_click(image_index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
    
    def handle_range_selection(self, current_index: int, anchor: int = None):
        """Handle range selection between anchor and current index (for keyboard)"""
        # Use anchor parameter if provided, otherwise use range_anchor_index
        if anchor is None:
            anchor = self.main_window.range_anchor_index
        
        # Call navigation manager's handle_range_selection
        self.main_window.navigation_manager.handle_range_selection(current_index, anchor)
        
        # Sync highlight_index from current_image_path (source of truth)
        # Don't set highlight_index directly - it's already set by set_current_image_by_path
        self.main_window._sync_highlight_index_from_current_image_path()
        self.main_window.highlight_image()
    
    def get_selected_files(self) -> List[str]:
        """Get list of file paths for selected thumbnails."""
        if self.main_window.selected_files:
            # Return selected files, preserving order from displayed_images
            result = []
            for image_path in self.main_window.displayed_images:
                if image_path in self.main_window.selected_files:
                    result.append(image_path)
            return result
        elif self.main_window.highlight_index is not None and 0 <= self.main_window.highlight_index < len(self.main_window.displayed_images):
            # Fallback to highlighted file if no selection
            return [self.main_window.displayed_images[self.main_window.highlight_index]]
        return []
    
    def get_selected_indices(self) -> List[int]:
        """Get list of image indices for selected thumbnails (for compatibility/display purposes)"""
        return list(self._get_selected_indices_for_display())
    
    def ensure_multi_mode(self):
        """Ensure multi-select mode is enabled"""
        if not self.main_window.multi_select_mode:
            self.main_window.multi_select_mode = True
            if hasattr(self.main_window, 'menu_manager') and self.main_window.menu_manager:
                self.main_window.menu_manager.update_edit_menu_states()
    
    def _toggle_index(self, idx: int):
        """Toggle selection of thumbnail at index"""
        if not (0 <= idx < len(self.main_window.displayed_images)):
            return
        
        file_path = self.main_window.displayed_images[idx]
        if file_path in self.main_window.selected_files:
            self.main_window.selected_files.remove(file_path)
        else:
            self.main_window.selected_files.add(file_path)
        
        self.main_window._emit_selection_changed()
    
    def _compute_next_index(self, current_index: int, axis: str, step_sign: int) -> int:
        """Compute next index for navigation"""
        return self.main_window.navigation_manager._compute_next_index(current_index, axis, step_sign)
