#!/usr/bin/env python3
"""
Navigation Manager for Image Browser
Handles grid navigation, selection, and highlighting logic
"""

# Standard library imports
from typing import List, Optional, Set

# Third-party imports
from PySide6.QtCore import QTimer


class NavigationManager:
    """Manages navigation, selection, and highlighting for the Image Browser"""
    
    def __init__(self, main_window):
        self.main_window = main_window
        # THUMBNAIL_CLICKED handled by BrowserController (command layer)
        
    def compute_next_index(self, current_index: int, axis: str, step_sign: int) -> int:
        """Compute next index for grid navigation."""

        total_count = self.main_window.get_widget_count()

        if axis == 'h':
            # horizontal left/right navigation
            if not self.main_window.wrap_around:
                next_index = current_index + step_sign
                if next_index < 0:
                    next_index = 0
                elif next_index >= total_count:
                    next_index = total_count - 1
            else:
                next_index = (current_index + step_sign) % total_count
            return next_index
        
        # vertical up/down navigation
        # Check if we're in segmented layout mode (EXIF date, duplicates)
        thumbnail_canvas = None
        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
            if hasattr(self.main_window.thumbnail_container, 'canvas'):
                thumbnail_canvas = self.main_window.thumbnail_container.canvas
        
        if thumbnail_canvas and thumbnail_canvas.is_segmented_layout():

            # Use actual row layout for segmented displays
            current_row = thumbnail_canvas.get_row_for_index(current_index)

            if current_row is None:
                # Current index is not in any row (collapsed section), can't navigate
                return current_index
            
            # Find column position within current row
            row_indices = thumbnail_canvas.get_indices_in_row(current_row)

            if not row_indices:

                return current_index
            
            try:
                col_position = row_indices.index(current_index)

            except ValueError:
                # Current index not in its row (shouldn't happen)

                return current_index
            
            # Calculate target row
            if step_sign < 0:
                target_row = current_row - 1
            else:
                target_row = current_row + 1

            # Check bounds
            total_rows = thumbnail_canvas.get_total_rows()

            if target_row < 0 or target_row >= total_rows:

                return current_index if not self.main_window.wrap_around else current_index
            
            # Get indices in target row
            target_row_indices = thumbnail_canvas.get_indices_in_row(target_row)

            if not target_row_indices:
                # Target row has no images (shouldn't happen, but handle gracefully)

                return current_index
            
            # Try to find index at same column position in target row
            if col_position < len(target_row_indices):
                target_index = target_row_indices[col_position]

            else:
                # Column position doesn't exist in target row - use last index in that row
                target_index = target_row_indices[-1]

            # Ensure target index is valid

            if 0 <= target_index < total_count:

                return target_index
            else:

                return current_index
        
        # Regular grid layout (non-segmented)

        grid_info = self.main_window.get_actual_grid_info()
        columns = grid_info["columns"] or 1
        row = current_index // columns
        col = current_index % columns

        if step_sign < 0:
            target_row = row - 1
        else:
            target_row = row + 1
            
        if target_row < 0:
            return current_index if not self.main_window.wrap_around else current_index  # no move when no wrap
            
        last_row = (total_count - 1) // columns
        if target_row > last_row:
            return current_index if not self.main_window.wrap_around else current_index  # no move when no wrap
            
        target_index = target_row * columns + col

        last_row_end = total_count - 1
        if target_index > last_row_end:
            target_index = last_row_end

        return target_index

    def toggle_index(self, idx: int):
        """Toggle selection for a file at the given index.
        
        CRITICAL: Sets current_image_path (source of truth) and derives highlight_index from it.
        """
        if not (0 <= idx < len(self.main_window.displayed_images)):
            return
        file_path = self.main_window.displayed_images[idx]
        if file_path in self.main_window.selected_files:
            self.main_window.selected_files.remove(file_path)
        else:
            self.main_window.selected_files.add(file_path)
        
        # multi_select_mode is now automatically derived from selected_files
        
        # CRITICAL: Set current image by path (source of truth) - this derives highlight_index
        self.main_window.set_current_image_by_path(file_path)
        
        self.main_window._emit_selection_changed()

    def handle_range_selection(self, current_index: int, anchor: int = None):
        """Handle range selection between anchor and current index.
        
        CRITICAL: Uses anchor parameter if provided, otherwise falls back to range_anchor_index or last_clicked_index.
        Always selects the full range from start to end index.
        """
        # Determine anchor - use parameter if provided, otherwise try range_anchor_index, then last_clicked_index
        if anchor is not None:
            anchor_index = anchor
        elif hasattr(self.main_window, 'range_anchor_index') and self.main_window.range_anchor_index is not None:
            anchor_index = self.main_window.range_anchor_index
        elif hasattr(self.main_window, 'last_clicked_index') and self.main_window.last_clicked_index is not None:
            anchor_index = self.main_window.last_clicked_index
        else:
            # No anchor available - just toggle current index
            self.toggle_index(current_index)
            self.main_window.last_clicked_index = current_index
            if hasattr(self.main_window, 'range_anchor_index'):
                self.main_window.range_anchor_index = current_index
            return
        
        # Calculate range from anchor to current
        start_index = min(anchor_index, current_index)
        end_index = max(anchor_index, current_index)
        
        # Clear existing selection and select range by file names
        self.main_window.selected_files.clear()
        displayed_images = self.main_window.displayed_images
        for i in range(start_index, end_index + 1):
            if 0 <= i < len(displayed_images):
                self.main_window.selected_files.add(displayed_images[i])
        self.main_window.most_recent_selected_index = current_index #DGN
        
        # CRITICAL: Don't set highlight_index directly - it should already be synced from current_image_path
        # The caller (handle_range_selection in image_browser_window) will sync it
        
        # Update last_clicked_index for next shift-click anchor
        self.main_window.last_clicked_index = current_index
        
        # CRITICAL: Preserve range_anchor_index for keyboard navigation
        # If anchor was provided as parameter, ensure range_anchor_index matches it
        # This ensures the anchor persists across multiple shift-arrow movements
        if hasattr(self.main_window, 'range_anchor_index'):
            if anchor is not None:
                # Anchor was explicitly provided - use it and update range_anchor_index
                self.main_window.range_anchor_index = anchor
            elif self.main_window.range_anchor_index is None:
                # No anchor was set and none was provided - set it to the anchor we determined
                self.main_window.range_anchor_index = anchor_index
            # Otherwise, keep the existing range_anchor_index (it's already set correctly)
        
        # multi_select_mode is now automatically derived from selected_files
        
        self.main_window._emit_selection_changed()
        
        # Note: highlight sync is via FileDataModel CURRENT_INDEX_CHANGED subscriber

    def handle_thumbnail_click(self, image_index: int, cmd_pressed: bool, shift_pressed: bool, macos_ctrl_pressed: bool):
        """Handle thumbnail click with support for multiple selection and range selection.

        On macOS: Cmd+click = multiselect, Ctrl+click = context menu only, Shift+click = range select.
        MAINTAINER: document changes in browser_window/dialogs/help_hidden_gems.py.
        Single-click opens browse mode (same as space or f keys).
        Double-click also opens browse mode.
        Drag operations are detected and do not trigger browse mode.
        
        File path is ALWAYS the source of truth - get it from the thumbnail itself.
        """
        
        # Get the file path directly from the thumbnail - this is the source of truth
        # Thumbnails store image_path directly, so use that instead of deriving from index
        image_path = None
        if (hasattr(self.main_window, 'thumbnail_container') and 
            hasattr(self.main_window.thumbnail_container, 'canvas') and
            hasattr(self.main_window.thumbnail_container.canvas, 'thumbnails')):
            canvas = self.main_window.thumbnail_container.canvas
            if 0 <= image_index < len(canvas.thumbnails):
                image_path = canvas.thumbnails[image_index].image_path
        
        # Fallback: if we can't get from thumbnail, use displayed_images
        if not image_path:
            if self.main_window.displayed_images and image_index < len(self.main_window.displayed_images):
                image_path = self.main_window.displayed_images[image_index]
            else:
                return
        
        # Find the actual index in displayed_images using the file path (source of truth)
        try:
            actual_index = self.main_window.displayed_images.index(image_path)
        except (ValueError, AttributeError):
            # If path not found, use the provided index as fallback
            actual_index = image_index
        
        # Set current_image_path FIRST - this is the source of truth
        # Use helper method to sync with FileDataModel
        if hasattr(self.main_window, '_set_current_image_path_with_sync'):
            self.main_window._set_current_image_path_with_sync(image_path)
        else:
            self.main_window.current_image_path = image_path
        
        # Now derive highlight_index from the file path
        thumbnail_index = actual_index
        
        if shift_pressed:
            self.handle_range_selection(thumbnail_index)
            self.main_window._sync_highlight_index_from_current_image_path()
            if hasattr(self.main_window, 'file_data_model'):
                self.main_window.file_data_model.set_current_index(thumbnail_index)
        elif cmd_pressed:
            if hasattr(self.main_window, 'selection_manager') and self.main_window.selection_manager:
                self.main_window.selection_manager.select_thumbnail(thumbnail_index, add_to_selection=True)
            else:
                self.main_window.highlight_index = thumbnail_index
                self.main_window.last_clicked_index = thumbnail_index
        elif macos_ctrl_pressed:
            self.main_window.highlight_index = thumbnail_index
            self.main_window.last_clicked_index = thumbnail_index
        else:
            # Regular click - clear selection and open fullscreen or highlight image
            self.main_window.clear_selection()
            self.main_window.highlight_index = thumbnail_index
            self.main_window.last_clicked_index = thumbnail_index
            # Open fullscreen on single click (same as space or f keys)
            if not self.main_window.preview_widget.isVisible():
                # CRITICAL: Capture view mode BEFORE opening browse view to preserve list mode
                # Check if we're in list view mode so we can return to it after closing browse
                captured_view_mode = getattr(self.main_window, 'current_view_mode', None)
                captured_stacked_index = self.main_window.stacked_widget.currentIndex() if hasattr(self.main_window, 'stacked_widget') else None
                is_list_view = (captured_view_mode == 'list') or (captured_stacked_index == 2)  # List view is index 2
                
                if is_list_view:
                    self.main_window._return_to_list_view = True
                
                # Use the file path to open fullscreen - it will find the correct index
                self.main_window.view_mode_manager.open_browse_view(thumbnail_index)
            else:
                self.main_window.update()

    def get_selected_files(self) -> List[str]:
        """Get list of selected file paths"""
        return self.main_window.selection_manager.get_selected_files()

    def get_selected_indices(self) -> List[int]:
        """Get list of selected indices (for compatibility/display purposes)"""
        return self.main_window.get_selected_indices()

    def clear_selection(self):
        """Clear current selection"""
        self.main_window.selected_files.clear()
        self.main_window._emit_selection_changed()
