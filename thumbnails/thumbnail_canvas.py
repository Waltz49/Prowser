#!/usr/bin/env python3
"""
Canvas-based thumbnail display for Image Browser
Replaces QGridLayout with individual widgets for better performance with thousands of images
"""

# Standard library imports
import logging
import os
import stat
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

# Local imports
from utils import entry_debug, entry_debug_wrapper, normalize_path_for_display, show_styled_warning, is_inside_photos_library
import thumbnails.thumbnail_constants as tc

# Third-party imports
from PySide6.QtCore import (
    QEvent, QMimeData, QMutex, QMutexLocker, QPoint, QPointF, QRect, QTimer,
    Qt, QUrl, Signal
)
from PySide6.QtGui import (
    QBrush, QColor, QContextMenuEvent, QDrag, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent,
    QDropEvent, QFont, QFontMetrics, QKeyEvent, QMouseEvent, QPaintEvent, QPainter, QPainterPath,
    QPen, QPixmap, QTransform, QWheelEvent
)
from PySide6.QtWidgets import QWidget, QApplication, QStyle, QLineEdit, QMessageBox
# Import constants from centralized file
from thumbnails.thumbnail_constants import (
    THUMBNAIL_SPACING, BASE_MARGIN, HIGHLIGHT_BORDER_WIDTH, BORDER_SPACE,
    CANVAS_TOP_MARGIN, CANVAS_BOTTOM_MARGIN, CANVAS_TOP_BORDER,
    CANVAS_TOTAL_TOP_MARGIN, CANVAS_TOTAL_BOTTOM_MARGIN,
    HORIZONTAL_SPACING, VERTICAL_SPACING, MIN_THUMBNAIL_SIZE,  # Legacy constants for compatibility
    RED, RESET, GREEN, DRAG_AUTO_SCROLL_SPEEDS,
    inset_rect_for_stroke, inset_corner_radius,
)


# External editor may be monitoring a file - notify when we change mtime so it doesn't restore
try:
    from files.external_editor import notify_mtime_changed_by_app
except ImportError:
    def notify_mtime_changed_by_app(file_path: str, new_mtime: float) -> None:
        pass

class DragDropManager:
    """Handle drag-and-drop re-ordering of thumbnails.

    All file-system touching and list manipulation lives here so that
    `image_browser_window.py` stays smaller.  The manager operates on an
    `ImageBrowserWindow` instance passed at construction time.
    """

    def __init__(self, window):
        self.window = window
    
    def _is_date_sort_active(self) -> bool:
        """Check if date sort mode is currently active"""
        if hasattr(self.window, 'current_sort_mode'):
            try:
                from sort_mode import SortMode
                return self.window.current_sort_mode == SortMode.DATE
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------
    # Public API called by ThumbnailContainer
    # ------------------------------------------------------------------
    def handle_thumbnail_reorder(self, image_path: str, insertion_index: int) -> bool:
        """Re-order *image_path* to *insertion_index* inside the window's
        displayed images list and adjust modification times so the browser's
        normal date sort keeps the new order.  Returns True on success."""

        if getattr(self.window, 'reference_graph_active', False):
            return False

        # Prevent reordering within Photos Libraries
        if is_inside_photos_library(image_path):
            show_styled_warning(
                self.window,
                "Operation Not Allowed",
                "Reordering files within macOS Photos Library is not allowed.\n\n"
                "Photos Library files cannot be reordered, renamed, or modified."
            )
            return False

        # CRITICAL: Preserve selections BEFORE any operations (file paths are source of truth)
        selected_files_before_reorder = set()
        if hasattr(self.window, 'selected_files') and self.window.selected_files:
            selected_files_before_reorder = self.window.selected_files.copy()
        
        # CRITICAL: Work directly with displayed_images to ensure changes persist
        images = self.window.displayed_images
        if not images:
            return False

        try:
            current_idx = images.index(image_path)
        except ValueError:
            return False

        if current_idx < insertion_index:
            insertion_index -= 1  # account for pop

        if insertion_index == current_idx or not (0 <= insertion_index <= len(images)):
            return False

        # Check if the file being moved is locked - if so, we MUST use CUSTOM sort mode
        is_locked = False
        if hasattr(self.window, 'lock_manager') and self.window.lock_manager:
            is_locked = self.window.lock_manager.is_file_locked(image_path)
        
        # Check if we're in date sort mode and if auto date change is enabled
        is_date_sort = self._is_date_sort_active()
        auto_date_change = getattr(self.window, 'drag_drop_auto_date_change', False)
        # CRITICAL: Never update dates if file is locked - locked files must use CUSTOM sort mode
        should_update_dates = is_date_sort and auto_date_change and not is_locked
        
        # CRITICAL: If we're NOT updating dates OR if file is locked, switch to custom sort mode IMMEDIATELY BEFORE reordering
        # This prevents any code from re-sorting based on the old sort mode
        # Locked files MUST always use CUSTOM sort mode to preserve their manual order
        dates_were_updated = False
        if not should_update_dates or is_locked:
            # Switch to custom sort mode immediately to prevent re-sorting
            if hasattr(self.window, 'current_sort_mode'):
                from sort_mode import SortMode
                self.window.current_sort_mode = SortMode.CUSTOM
        
        # Re-order list first (always do this)
        images.pop(current_idx)
        images.insert(insertion_index, image_path)
        new_pos = images.index(image_path)
        
        # Update model with reordered list (single source of truth)
        if hasattr(self.window, 'file_data_model') and self.window.file_data_model:
            self.window.file_data_model.set_displayed_images(images, notify=True)
        
        # Only update file dates if auto date change is enabled and we're in date sort mode
        if should_update_dates:
            
            # Get original file date for comparison
            try:
                original_stat = os.stat(image_path)
                original_mtime = original_stat.st_mtime
            except Exception as e:
                original_mtime = None
            
            # Pre-check: Verify directory is writable before attempting date changes
            file_dir = os.path.dirname(image_path)
            if not os.access(file_dir, os.W_OK):
                # Revert list changes and update model
                images.pop(insertion_index)
                images.insert(current_idx, image_path)
                if hasattr(self.window, 'file_data_model') and self.window.file_data_model:
                    self.window.file_data_model.set_displayed_images(images, notify=True)
                show_styled_warning(
                    self.window,
                    "Permission Error",
                    f"Unable to reorder: Directory '{os.path.basename(file_dir)}' is not writable.\n\n"
                    "Please check directory permissions and try again."
                )
                return False

            # Compute new mtime between neighbours before any modification _____
            # The insertion_index is already adjusted for the pop operation.
            # It represents where the item will be inserted in the list AFTER removing it.
            # We need to find the neighbors that will be adjacent after insertion:
            # - prev_time: the item at insertion_index - 1 after removal
            # - next_time: the item at insertion_index after removal (which will shift to insertion_index + 1)
            prev_time = None
            next_time = None
            
            # Find the previous neighbor (item at insertion_index - 1 AFTER insertion)
            # Since we've already inserted the file, the previous neighbor is simply at insertion_index - 1
            if insertion_index > 0:
                prev_idx = insertion_index - 1
                # The file at prev_idx is the previous neighbor (we've already inserted, so indices are correct)
                if prev_idx < len(images) and images[prev_idx] != image_path:
                    try:
                        prev_time = os.stat(images[prev_idx]).st_mtime
                    except OSError as e:
                        pass
            
            # Find the next neighbor (item at insertion_index + 1 AFTER insertion)
            # Since we've already inserted the file, the next neighbor is simply at insertion_index + 1
            if insertion_index + 1 < len(images):
                next_idx = insertion_index + 1
                # The file at next_idx is the next neighbor (we've already inserted, so indices are correct)
                if images[next_idx] != image_path:
                    try:
                        next_time = os.stat(images[next_idx]).st_mtime
                    except OSError as e:
                        pass
                else:
                    pass
            else:
                pass

            # Determine sort direction: is_reversed=False means newest first (descending), 
            # is_reversed=True means oldest first (ascending)
            is_reversed = getattr(self.window, 'is_reversed', False)
            
            if prev_time is None and next_time is None:
                new_time = time.time()
            elif prev_time is None:
                new_time = time.time()
            elif next_time is None:
                # At end of list - make it older (descending) or newer (ascending) than prev
                new_time = prev_time - 1 if not is_reversed else prev_time + 1
            else:
                # Calculate gap and new_time based on sort direction
                if is_reversed:
                    # Oldest first (ascending): prev_time < next_time
                    # We want: prev_time < new_time < next_time
                    gap = next_time - prev_time
                    new_time = prev_time + gap / 2 if gap >= 2 else prev_time + 0.5
                else:
                    # Newest first (descending): prev_time > next_time
                    # We want: next_time < new_time < prev_time
                    gap = prev_time - next_time
                    new_time = prev_time - gap / 2 if gap >= 2 else prev_time - 0.5

            # Security check: Test if mtime can be set before making structural changes
            utime_test_ok = True
            try:
                st = os.stat(image_path)
                orig_atime, orig_mtime = st.st_atime, st.st_mtime
                os.utime(image_path, (new_time, new_time))
                # This second stat ensures the change took place (even if no error was raised)
                test_mtime = os.stat(image_path).st_mtime
                verified = abs(test_mtime - new_time) < 2
                # Revert mtime to original right away for safety
                os.utime(image_path, (orig_atime, orig_mtime))
                reverted_mtime = os.stat(image_path).st_mtime
                if not verified:
                    utime_test_ok = False
            except Exception as e:
                utime_test_ok = False

            if not utime_test_ok:
                # Revert list changes and update model
                images.pop(insertion_index)
                images.insert(current_idx, image_path)
                if hasattr(self.window, 'file_data_model') and self.window.file_data_model:
                    self.window.file_data_model.set_displayed_images(images, notify=True)
                self.window.status_notification.show_message(
                    "Unable to reorder: The application does not have permission to change file dates."
                )
                return False

            # Set mtime for the moved image (calculations already done above)
            try:
                os.utime(image_path, (new_time, new_time))
                notify_mtime_changed_by_app(image_path, new_time)
                if hasattr(self.window, 'cache_manager') and self.window.cache_manager:
                    self.window.cache_manager.clear_cache_for_file(image_path)
                # Verify the date change actually worked
                actual_mtime = os.stat(image_path).st_mtime
                if abs(actual_mtime - new_time) >= 1:
                    # Revert list changes and update model
                    images.pop(insertion_index)
                    images.insert(current_idx, image_path)
                    if hasattr(self.window, 'file_data_model') and self.window.file_data_model:
                        self.window.file_data_model.set_displayed_images(images, notify=True)
                    show_styled_warning(
                        self.window,
                        "Reorder Failed",
                        f"Unable to reorder: Failed to change date for '{os.path.basename(image_path)}'.\n\n"
                        "The file date could not be modified. Please check file permissions."
                    )
                    return False
            except Exception as e:
                # Revert list changes and update model
                images.pop(insertion_index)
                images.insert(current_idx, image_path)
                if hasattr(self.window, 'file_data_model') and self.window.file_data_model:
                    self.window.file_data_model.set_displayed_images(images, notify=True)
                show_styled_warning(
                    self.window,
                    "Reorder Failed",
                    f"Unable to reorder: Error changing date for '{os.path.basename(image_path)}'.\n\n"
                    f"Error: {str(e)}"
                )
                return False

            # Shift subsequent files to avoid duplicate mtimes
            # Direction depends on sort order: descending (newest first) shifts backward,
            # ascending (oldest first) shifts forward
            last = new_time
            shifted_count = 0
            for idx in range(insertion_index + 1, len(images)):
                p = images[idx]
                try:
                    # Pre-check directory writability for each file
                    p_dir = os.path.dirname(p)
                    if not os.access(p_dir, os.W_OK):
                        continue  # Skip files in non-writable directories
                    
                    t = os.stat(p).st_mtime
                    original_t = t
                    needs_shift = False
                    if is_reversed:
                        # Ascending: ensure subsequent files are newer (larger mtime)
                        if t <= last:
                            t = last + 1
                            needs_shift = True
                    else:
                        # Descending: ensure subsequent files are older (smaller mtime)
                        if t >= last:
                            t = last - 1
                            needs_shift = True
                    
                    if needs_shift: 
                        os.utime(p, (t, t))
                        notify_mtime_changed_by_app(p, t)
                        if hasattr(self.window, 'cache_manager') and self.window.cache_manager:
                            self.window.cache_manager.clear_cache_for_file(p)
                        # Verify the date change worked
                        actual_t = os.stat(p).st_mtime
                        if abs(actual_t - t) >= 1:
                            # Date change failed, but continue with other files
                            t = actual_t
                        else:
                            shifted_count += 1
                    last = t
                except OSError as e:
                    continue
            
            
            # Verify final date of moved file
            final_stat = os.stat(image_path)
            final_mtime = final_stat.st_mtime
            
            # Mark that dates were successfully updated
            dates_were_updated = True

        self.window.populate_indices_arrays()
        
        # CRITICAL: Set current image by path (source of truth) - this derives highlight_index
        if image_path in images:
            self.window.set_current_image_by_path(image_path, fallback_index=insertion_index)
        else:
            # Fallback to insertion index if path not found
            if 0 <= insertion_index < len(images):
                self.window.set_current_image_by_path(images[insertion_index], fallback_index=insertion_index)
        
        # CRITICAL: Restore selections after reordering (file paths are source of truth)
        # Filter selected_files to only include files that are still in displayed_images
        if selected_files_before_reorder:
            # Restore from preserved selections
            self.window.selected_files = {
                path for path in selected_files_before_reorder 
                if path in images
            }
        elif hasattr(self.window, 'selected_files') and self.window.selected_files:
            # Filter existing selections if they weren't explicitly preserved
            self.window.selected_files = {
                path for path in self.window.selected_files 
                if path in images
            }
        
        # Update canvas selection to reflect preserved selections
        if hasattr(self.window, 'selected_files') and self.window.selected_files:
            self.window._emit_selection_changed()
        
        # CRITICAL: Always save .prsort file after drag/drop to preserve the new order
        # This is especially important for locked files - their new positions must be saved
        # Even if dates were updated, we still need to save to .prsort so the order persists
        if dates_were_updated:
            # Keep date sort mode - dates were updated to maintain date ordering
            # But still save to .prsort to preserve order (especially for locked files)
            # CRITICAL: Save with current order including locked files in their new positions
            self._switch_to_custom_sort_and_save()
            # Then switch back to date sort mode (but .prsort is saved with new order)
            if hasattr(self.window, 'current_sort_mode'):
                from sort_mode import SortMode
                self.window.current_sort_mode = SortMode.DATE
            # Update status bar to reflect current sort mode
            if hasattr(self.window, 'update_status_bar_sections'):
                self.window.update_status_bar_sections()
        else:
            # Switch to custom sort mode and save .prsort file
            # This MUST happen before any operations that might check the sort mode
            # CRITICAL: Save with current order including locked files in their new positions
            self._switch_to_custom_sort_and_save()
            
            # Update status bar to show custom sort mode
            if hasattr(self.window, 'update_status_bar_sections'):
                self.window.update_status_bar_sections()
        
        self.window.reorder_thumbnail_layout()
        
        # CRITICAL: Ensure selections are still preserved after reorder_thumbnail_layout
        # Reorder might trigger updates that could affect selections, so restore them again
        if selected_files_before_reorder:
            self.window.selected_files = {
                path for path in selected_files_before_reorder 
                if path in images
            }
            # Update canvas selection again to ensure it's reflected
            if hasattr(self.window, '_emit_selection_changed'):
                self.window._emit_selection_changed()
        
        self.window.highlight_image()
        
        # CRITICAL: Delayed restore of selections to ensure they persist after any async operations
        # This handles cases where selections might be cleared by refresh or other operations
        if selected_files_before_reorder:
            from PySide6.QtCore import QTimer
            def restore_selections_delayed():
                if hasattr(self.window, 'displayed_images') and self.window.displayed_images:
                    current_images = self.window.displayed_images
                    restored = {
                        path for path in selected_files_before_reorder 
                        if path in current_images
                    }
                    if restored:
                        self.window.selected_files = restored
                        if hasattr(self.window, '_emit_selection_changed'):
                            self.window._emit_selection_changed()
            QTimer.singleShot(200, restore_selections_delayed)
        
        # Show status message
        if dates_were_updated:
            msg = "Thumbnail reordered (dates updated)"
        else:
            msg = "Thumbnail reordered (switched to custom sort)"
        self.window.status_notification.show_message(msg)
        
        return True
    
    def _switch_to_custom_sort_and_save(self):
        """Switch to custom sort mode and save .prsort file"""
        # CRITICAL: Work directly with displayed_images to ensure we're using the same list
        images = self.window.displayed_images
        if not images:
            return
        
        # Get directory from first image
        directory = os.path.dirname(images[0])
        
        # Switch to custom sort mode
        if hasattr(self.window, 'current_sort_mode'):
            from sort_mode import SortMode
            self.window.current_sort_mode = SortMode.CUSTOM

        # Save .prsort file IMMEDIATELY - this is critical to preserve the order
        # CRITICAL: preserve_locks=True ensures locked files are saved in their new positions
        is_reversed = getattr(self.window, 'is_reversed', False)
        save_result = self.window.sorting_manager.write_prsort_file(directory, images, is_reversed, preserve_locks=True)
        
        # Update menu checkmarks
        if hasattr(self.window, 'update_sort_menu_checkmarks'):
            self.window.update_sort_menu_checkmarks()
        
        # Save settings
        if hasattr(self.window, 'save_sorting_settings'):
            self.window.save_sorting_settings()

    def handle_multiple_thumbnail_reorder(self, image_paths: List[str], insertion_index: int) -> bool:
        """Re-order multiple *image_paths* to *insertion_index* inside the window's
        displayed images list and adjust modification times so the browser's
        normal date sort keeps the new order.  Returns True on success."""

        if getattr(self.window, 'reference_graph_active', False):
            return False

        # Prevent reordering within Photos Libraries
        photos_library_paths = [path for path in image_paths if is_inside_photos_library(path)]
        if photos_library_paths:
            show_styled_warning(
                self.window,
                "Operation Not Allowed",
                "Reordering files within macOS Photos Library is not allowed.\n\n"
                "Photos Library files cannot be reordered, renamed, or modified."
            )
            return False

        # CRITICAL: Preserve selections BEFORE any operations (file paths are source of truth)
        selected_files_before_reorder = set()
        if hasattr(self.window, 'selected_files') and self.window.selected_files:
            selected_files_before_reorder = self.window.selected_files.copy()
        
        # CRITICAL: Work directly with displayed_images to ensure changes persist
        images = self.window.displayed_images
        if not images:
            return False

        # Validate all paths exist in the images list
        valid_paths = []
        original_indices = []
        for path in image_paths:
            try:
                idx = images.index(path)
                valid_paths.append(path)
                original_indices.append(idx)
            except ValueError:
                continue

        if not valid_paths:
            return False

        # Check if any of the files being moved are locked - if so, we MUST use CUSTOM sort mode
        has_locked_files = False
        if hasattr(self.window, 'lock_manager') and self.window.lock_manager:
            for path in valid_paths:
                if self.window.lock_manager.is_file_locked(path):
                    has_locked_files = True
                    break
        
        # Check if we're in date sort mode and if auto date change is enabled
        is_date_sort = self._is_date_sort_active()
        auto_date_change = getattr(self.window, 'drag_drop_auto_date_change', False)
        # CRITICAL: Never update dates if any files are locked - locked files must use CUSTOM sort mode
        should_update_dates = is_date_sort and auto_date_change and not has_locked_files
        
        # CRITICAL: If we're NOT updating dates OR if any files are locked, switch to custom sort mode IMMEDIATELY BEFORE reordering
        # This prevents any code from re-sorting based on the old sort mode
        # Locked files MUST always use CUSTOM sort mode to preserve their manual order
        dates_were_updated = False
        if not should_update_dates or has_locked_files:
            # Switch to custom sort mode immediately to prevent re-sorting
            if hasattr(self.window, 'current_sort_mode'):
                from sort_mode import SortMode
                self.window.current_sort_mode = SortMode.CUSTOM

        # Sort original indices in descending order to avoid index shifting issues
        sorted_indices = sorted(original_indices, reverse=True)
        
        # Remove all files from their original positions
        for idx in sorted_indices:
            images.pop(idx)

        # Adjust insertion index based on removed items
        adjusted_insertion_index = insertion_index
        for idx in sorted_indices:
            if idx < insertion_index:
                adjusted_insertion_index -= 1

        # Insert all files at the new position
        for i, path in enumerate(valid_paths):
            insert_pos = adjusted_insertion_index + i
            if insert_pos <= len(images):
                images.insert(insert_pos, path)
        
        # Switch to custom sort mode immediately to prevent re-sorting (only once, not in loop)
        if not should_update_dates and hasattr(self.window, 'current_sort_mode'):
                from sort_mode import SortMode
                self.window.current_sort_mode = SortMode.CUSTOM
        
        # Update model with reordered list (single source of truth)
        if hasattr(self.window, 'file_data_model') and self.window.file_data_model:
            self.window.file_data_model.set_displayed_images(images, notify=True)
        
        # Get the reversed flag for date sorting
        is_reversed = getattr(self.window, 'is_reversed', False)
        
        # Only update file dates if auto date change is enabled and we're in date sort mode
        if should_update_dates:
            # Pre-check: Verify all directories are writable before attempting date changes
            directories_to_check = set()
            for path in valid_paths:
                directories_to_check.add(os.path.dirname(path))
            # Also check directories of files that will be shifted
            for idx in range(adjusted_insertion_index + len(valid_paths), len(images)):
                directories_to_check.add(os.path.dirname(images[idx]))
            
            non_writable_dirs = []
            for dir_path in directories_to_check:
                if not os.access(dir_path, os.W_OK):
                    non_writable_dirs.append(os.path.basename(dir_path))
            
            if non_writable_dirs:
                # Revert list changes and update model
                for path in reversed(valid_paths):
                    images.remove(path)
                for idx, path in zip(sorted_indices, image_paths):
                    images.insert(idx, path)
                if hasattr(self.window, 'file_data_model') and self.window.file_data_model:
                    self.window.file_data_model.set_displayed_images(images, notify=True)
                
                dir_list = ", ".join(non_writable_dirs[:5])
                if len(non_writable_dirs) > 5:
                    dir_list += f" and {len(non_writable_dirs) - 5} more"
                
                show_styled_warning(
                    self.window,
                    "Permission Error",
                    f"Unable to reorder: Directory(ies) not writable:\n{dir_list}\n\n"
                    "Please check directory permissions and try again."
                )
                return False

            # Compute new mtimes for all moved files
            # Get the time range between neighbours (files are already inserted, so neighbors are straightforward)
            prev_time = None
            next_time = None
            if adjusted_insertion_index > 0:
                try:
                    prev_time = os.stat(images[adjusted_insertion_index - 1]).st_mtime
                except OSError:
                    pass
            if adjusted_insertion_index + len(valid_paths) < len(images):
                try:
                    next_time = os.stat(images[adjusted_insertion_index + len(valid_paths)]).st_mtime
                except OSError:
                    pass

            # Calculate time spacing - ensure proper spacing between moved files
            # Preserve order: first item in valid_paths should maintain its relative position
            if prev_time is None and next_time is None:
                base_time = time.time()
                time_spacing = 1.0
            elif prev_time is None:
                # Dragging to the beginning of the list
                base_time = time.time()
                time_spacing = 1.0
            elif next_time is None:
                # At end of list
                if is_reversed:
                    # Ascending: make them newer than prev
                    base_time = prev_time + 1
                    time_spacing = 1.0
                else:
                    # Descending: make them older than prev
                    base_time = prev_time - len(valid_paths) - 1
                    time_spacing = 1.0
            else:
                # Between two neighbors
                if is_reversed:
                    # Ascending: prev_time < next_time, place between them
                    gap = next_time - prev_time
                    if gap >= len(valid_paths) + 2:
                        base_time = prev_time + gap / (len(valid_paths) + 1)
                        time_spacing = gap / (len(valid_paths) + 1)
                    else:
                        base_time = prev_time + 1
                        time_spacing = 1.0
                else:
                    # Descending: prev_time > next_time, place between them
                    gap = prev_time - next_time
                    if gap >= len(valid_paths) + 2:
                        base_time = prev_time - gap / (len(valid_paths) + 1)
                        time_spacing = gap / (len(valid_paths) + 1)
                    else:
                        base_time = prev_time - len(valid_paths) - 1
                        time_spacing = 1.0

            # Set mtimes for all moved files, preserving their order
            # For descending: first item gets largest mtime (base_time), subsequent items get smaller
            # For ascending: first item gets smallest mtime (base_time), subsequent items get larger
            failed_files = []
            for i, path in enumerate(valid_paths):
                if is_reversed:
                    # Ascending: add spacing for each subsequent item to maintain order
                    new_time = base_time + (i * time_spacing)
                else:
                    # Descending: subtract spacing for each subsequent item to maintain order
                    new_time = base_time - (i * time_spacing)
                try:
                    os.utime(path, (new_time, new_time))
                    notify_mtime_changed_by_app(path, new_time)
                    if hasattr(self.window, 'cache_manager') and self.window.cache_manager:
                        self.window.cache_manager.clear_cache_for_file(path)
                    # Verify the date change actually worked
                    actual_mtime = os.stat(path).st_mtime
                    if abs(actual_mtime - new_time) >= 1:
                        failed_files.append(os.path.basename(path))
                except Exception as e:
                    failed_files.append(os.path.basename(path))
            
            if failed_files:
                # Revert list changes and update model
                for path in reversed(valid_paths):
                    images.remove(path)
                for idx, path in zip(sorted_indices, image_paths):
                    images.insert(idx, path)
                if hasattr(self.window, 'file_data_model') and self.window.file_data_model:
                    self.window.file_data_model.set_displayed_images(images, notify=True)
                
                file_list = ", ".join(failed_files[:5])
                if len(failed_files) > 5:
                    file_list += f" and {len(failed_files) - 5} more"
                
                show_styled_warning(
                    self.window,
                    "Reorder Failed",
                    f"Unable to reorder: Failed to change dates for:\n{file_list}\n\n"
                    "The file dates could not be modified. Please check file permissions."
                )
                return False

            # Shift subsequent files to avoid duplicate mtimes
            # Calculate the last mtime assigned to the dragged items
            if is_reversed:
                # Ascending: last item has largest mtime
                last_time = base_time + (len(valid_paths) - 1) * time_spacing
            else:
                # Descending: last item has smallest mtime
                last_time = base_time - (len(valid_paths) - 1) * time_spacing
            
            for idx in range(adjusted_insertion_index + len(valid_paths), len(images)):
                p = images[idx]
                try:
                    t = os.stat(p).st_mtime
                    if is_reversed:
                        # Ascending: ensure subsequent files are newer (larger mtime)
                        if t <= last_time:
                            t = last_time + 1
                            os.utime(p, (t, t))
                            notify_mtime_changed_by_app(p, t)
                            if hasattr(self.window, 'cache_manager') and self.window.cache_manager:
                                self.window.cache_manager.clear_cache_for_file(p)
                            # Verify the date change worked
                            actual_t = os.stat(p).st_mtime
                            if abs(actual_t - t) >= 1:
                                # Date change failed, but continue with other files
                                t = actual_t
                    else:
                        # Descending: ensure subsequent files are older (smaller mtime)
                        if t >= last_time:
                            t = last_time - 1
                            os.utime(p, (t, t))
                            notify_mtime_changed_by_app(p, t)
                            if hasattr(self.window, 'cache_manager') and self.window.cache_manager:
                                self.window.cache_manager.clear_cache_for_file(p)
                            # Verify the date change worked
                            actual_t = os.stat(p).st_mtime
                            if abs(actual_t - t) >= 1:
                                # Date change failed, but continue with other files
                                t = actual_t
                    last_time = t
                except OSError:
                    continue
            
            # Mark that dates were successfully updated
            dates_were_updated = True

        # Refresh UI
        self.window.populate_indices_arrays()
        
        # CRITICAL: Restore selections after reordering (file paths are source of truth)
        # Filter selected_files to only include files that are still in displayed_images
        if selected_files_before_reorder:
            # Restore from preserved selections
            self.window.selected_files = {
                path for path in selected_files_before_reorder 
                if path in images
            }
        elif hasattr(self.window, 'selected_files') and self.window.selected_files:
            # Filter existing selections if they weren't explicitly preserved
            self.window.selected_files = {
                path for path in self.window.selected_files 
                if path in images
            }
        
        # Update canvas selection to reflect preserved selections
        if hasattr(self.window, 'selected_files') and self.window.selected_files:
            self.window._emit_selection_changed()
        
        # CRITICAL: Set current image by path (source of truth) - this derives highlight_index
        # Use the last moved file as the current image
        if valid_paths:
            last_file = valid_paths[-1]
            if last_file in images:
                self.window.set_current_image_by_path(last_file, fallback_index=adjusted_insertion_index)
            else:
                # Fallback to insertion index
                if 0 <= adjusted_insertion_index < len(images):
                    self.window.set_current_image_by_path(images[adjusted_insertion_index], fallback_index=adjusted_insertion_index)
        else:
            # No valid paths, use insertion index
            if 0 <= adjusted_insertion_index < len(images):
                self.window.set_current_image_by_path(images[adjusted_insertion_index], fallback_index=adjusted_insertion_index)
        
        # CRITICAL: Always save .prsort file after drag/drop to preserve the new order
        # This is especially important for locked files - their new positions must be saved
        # Even if dates were updated, we still need to save to .prsort so the order persists
        if dates_were_updated:
            # Keep date sort mode - dates were updated to maintain date ordering
            # But still save to .prsort to preserve order (especially for locked files)
            # CRITICAL: Save with current order including locked files in their new positions
            self._switch_to_custom_sort_and_save()
            # Then switch back to date sort mode (but .prsort is saved with new order)
            if hasattr(self.window, 'current_sort_mode'):
                from sort_mode import SortMode
                self.window.current_sort_mode = SortMode.DATE
            # Update status bar to reflect current sort mode
            if hasattr(self.window, 'update_status_bar_sections'):
                self.window.update_status_bar_sections()
        else:
            # Switch to custom sort mode and save .prsort file
            # This MUST happen before any operations that might check the sort mode
            # CRITICAL: Save with current order including locked files in their new positions
            self._switch_to_custom_sort_and_save()
            
            # Update status bar to show custom sort mode
            if hasattr(self.window, 'update_status_bar_sections'):
                self.window.update_status_bar_sections()
        
        self.window.reorder_thumbnail_layout()
        
        # CRITICAL: Ensure selections are still preserved after reorder_thumbnail_layout
        # Reorder might trigger updates that could affect selections, so restore them again
        if selected_files_before_reorder:
            self.window.selected_files = {
                path for path in selected_files_before_reorder 
                if path in images
            }
            # Update canvas selection again to ensure it's reflected
            if hasattr(self.window, '_emit_selection_changed'):
                self.window._emit_selection_changed()
        
        self.window.highlight_image()
        
        # CRITICAL: Delayed restore of selections to ensure they persist after any async operations
        # This handles cases where selections might be cleared by refresh or other operations
        if selected_files_before_reorder:
            from PySide6.QtCore import QTimer
            def restore_selections_delayed():
                if hasattr(self.window, 'displayed_images') and self.window.displayed_images:
                    current_images = self.window.displayed_images
                    restored = {
                        path for path in selected_files_before_reorder 
                        if path in current_images
                    }
                    if restored:
                        self.window.selected_files = restored
                        if hasattr(self.window, '_emit_selection_changed'):
                            self.window._emit_selection_changed()
            QTimer.singleShot(200, restore_selections_delayed)

        if dates_were_updated:
            self.window.status_notification.show_message(f"{len(valid_paths)} thumbnails reordered (dates updated)")
        else:
            self.window.status_notification.show_message(f"{len(valid_paths)} thumbnails reordered (switched to custom sort)")
        return True 
# Drag and drop logger
_drag_drop_logger = None

def get_drag_drop_logger():
    """Get or create the drag and drop logger"""
    global _drag_drop_logger
    if _drag_drop_logger is None:
        from config import ImageBrowserConfig
        config = ImageBrowserConfig()
        
        # Create logger
        _drag_drop_logger = logging.getLogger('drag_drop')
        
        # Remove any existing handlers
        for handler in _drag_drop_logger.handlers[:]:
            _drag_drop_logger.removeHandler(handler)
        
        # Create file handler
        file_handler = logging.FileHandler(config.drag_drop_log)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # Add handler to logger
        _drag_drop_logger.addHandler(file_handler)
        
        # Prevent propagation to root logger
        _drag_drop_logger.propagate = False
    
    return _drag_drop_logger

# String-based path helpers (avoid os.path in hot paths - macOS uses /)
def _path_dirname(path):
    i = path.rfind('/')
    return path[:i] if i >= 0 else ''
def _path_basename(path):
    i = path.rfind('/')
    return path[i+1:] if i >= 0 else path
def _path_basename_no_ext(path):
    base = _path_basename(path)
    dot = base.rfind('.')
    return base[:dot] if dot > 0 else base

# Color constants imported from thumbnail_constants.py

SQUARE_IMAGE_BORDER_WIDTH = 7
REGULAR_BORDER_RADIUS = 7
def draw_message_with_icon(painter: QPainter, message: str, width: int, height: int, 
                           font_size: int = 20, icon_size: int = 64, icon_spacing: int = 20):
    """
    Common utility function to draw a centered message with icon.
    
    Args:
        painter: QPainter to draw on
        message: Message text (can contain \n for line breaks)
        width: Width of the drawing area
        height: Height of the drawing area
        font_size: Font size in points (default: 20)
        icon_size: Size of the icon in pixels (default: 64)
        icon_spacing: Space between icon and text in pixels (default: 20)
    """
    # Load and scale icon (same as about dialog)
    icon_pixmap = None
    icon_path = os.path.join(os.path.dirname(__file__), "Prowser.icns")
    if os.path.exists(icon_path):
        icon_pixmap = QPixmap(icon_path)
        if not icon_pixmap.isNull():
            icon_pixmap = icon_pixmap.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    
    # Set font
    font = QFont("Arial", font_size)
    painter.setFont(font)
    painter.setPen(tc.TEXT_COLOR)
    
    # Calculate text dimensions
    font_metrics = painter.fontMetrics()
    # Split message into lines
    message_lines = message.split('\n')
    
    # Calculate text width (widest line)
    max_text_width = 0
    for line in message_lines:
        line_width = font_metrics.horizontalAdvance(line)
        max_text_width = max(max_text_width, line_width)
    
    # Calculate total content width (icon + spacing + text)
    icon_width = icon_pixmap.width() if icon_pixmap and not icon_pixmap.isNull() else 0
    total_content_width = icon_width + (icon_spacing if icon_pixmap else 0) + max_text_width
    
    # Calculate total text height
    line_height = font_metrics.height()
    total_text_height = len(message_lines) * line_height
    
    # Calculate starting positions (centered)
    start_x = (width - total_content_width) // 2
    start_y = (height - max(icon_size, total_text_height)) // 2
    
    # Draw icon if available
    if icon_pixmap and not icon_pixmap.isNull():
        icon_y = start_y + (max(icon_size, total_text_height) - icon_size) // 2
        painter.drawPixmap(start_x, icon_y, icon_pixmap)
        text_start_x = start_x + icon_width + icon_spacing
    else:
        text_start_x = start_x
    
    # Draw each line of text
    text_start_y = start_y + (max(icon_size, total_text_height) - total_text_height) // 2 + font_metrics.ascent()
    for i, line in enumerate(message_lines):
        y = text_start_y + (i * line_height)
        painter.drawText(text_start_x, y, line)

def create_message_pixmap(message: str, width: int, height: int, 
                          font_size: int = 20, icon_size: int = 64, icon_spacing: int = 20,
                          background_color: QColor = None) -> QPixmap:
    """
    Create a pixmap with a centered message and icon.
    
    Args:
        message: Message text (can contain \n for line breaks)
        width: Width of the pixmap
        height: Height of the pixmap
        font_size: Font size in points (default: 20)
        icon_size: Size of the icon in pixels (default: 64)
        icon_spacing: Space between icon and text in pixels (default: 20)
        background_color: Background color (default: dark gray QColor(30, 30, 30))
    
    Returns:
        QPixmap with the message and icon drawn on it
    """
    if background_color is None:
        background_color = tc.DEFAULT_BACKGROUND_COLOR
    
    pixmap = QPixmap(width, height)
    pixmap.fill(background_color)
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    try:
        draw_message_with_icon(painter, message, width, height, font_size, icon_size, icon_spacing)
    finally:
        painter.end()
    
    return pixmap

@dataclass
class ThumbnailItem:
    """Represents a single thumbnail item in the canvas"""
    image_path: str
    index: int
    pixmap: Optional[QPixmap] = None
    is_loading: bool = True
    rect: QRect = None
    is_highlighted: bool = False
    is_selected: bool = False
    filename_overlay_rect: QRect = None  # Rectangle where filename overlay is drawn

@dataclass(frozen=False)
class SectionSeparatorItem:
    """Represents a section separator for EXIF date grouping"""
    month_key: str  # e.g., "2024-09" or "undated"
    index: int  # Position in the combined list (thumbnails + separators)
    rect: QRect = None
    is_expanded: bool = True
    is_bold: bool = False  # True if this section contains the active image

class ThumbnailCanvas(QWidget):
    """
    Canvas-based thumbnail display that replaces QGridLayout with individual widgets.
    Handles thousands of thumbnails efficiently by drawing them directly on a canvas.
    """
    
    # Signals to maintain compatibility with existing code
    # On macOS: cmd_pressed=Command(⌘) for multiselect, macos_ctrl_pressed=Control(⌃) for context menu
    thumbnail_clicked = Signal(int, bool, bool, bool)  # index, cmd_pressed, shift_pressed, macos_ctrl_pressed
    thumbnail_double_clicked = Signal(int)  # index
    thumbnail_hovered = Signal(int)  # index
    
    # Custom MIME types for drag and drop (legacy, but no longer used for drag)
    MIME_TYPE = 'application/x-imagebrowser-path'
    MULTIPLE_MIME_TYPE = 'application/x-imagebrowser-multiple-paths'
    
    # Separator dash length in characters (before label)
    SEPARATOR_DASH_LENGTH = 4
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        
        # Thumbnail data
        self.thumbnails: List[ThumbnailItem] = []
        self.section_separators: List[SectionSeparatorItem] = []  # Section separators for EXIF date grouping
        self.thumbnail_size = MIN_THUMBNAIL_SIZE
        self.columns = 1
        self.rows = 1
        
        # Selection and highlighting
        self.highlighted_index = -1
        self.selected_indices: Set[int] = set()
        self.multi_select_mode = False
        
        # Row layout tracking for segmented displays (EXIF date, duplicates)
        # Maps thumbnail index -> row number (0-based)
        self._index_to_row: dict[int, int] = {}
        # Maps row number -> list of thumbnail indices in that row
        self._row_to_indices: dict[int, list[int]] = {}
        
        # Suggested filter buttons (for empty directory message)
        self.suggested_filters: List[str] = []
        self.filter_button_rects: List[Tuple[QRect, str]] = []  # List of (rect, filter_pattern) tuples
        self._hovered_button_index = -1  # Index of currently hovered button (-1 if none)
        self._has_images_in_folder = False  # Track if there are any images in the current folder
        
        # Mouse interaction
        self._drag_start_pos: Optional[QPoint] = None
        self._dragging = False
        self._separator_click_processed = False  # Track if separator click was just processed
        self._hovered_index = -1
        # Timer to delay single-click handling to allow double-click detection
        self._single_click_timer = QTimer()
        self._single_click_timer.setSingleShot(True)
        self._single_click_timer.timeout.connect(self._handle_delayed_single_click)
        self._pending_click_data = None  # (index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
        
        # For drag action type (default to move for macOS conventions)
        self._last_drag_intent = Qt.MoveAction
        # Track if drop was handled internally (for reordering)
        self._internal_drop_handled = False
        
        # Drag and drop
        self._show_drop_indicator = False
        self._current_insertion_index = None
        self._indicator_x = 0
        
        # Auto-scroll during drag
        self._reference_graph_edge_routes: List = []
        self._reference_graph_layout_result = None
        self._auto_scroll_timer = QTimer()
        self._auto_scroll_timer.timeout.connect(self._handle_auto_scroll)
        self._auto_scroll_direction = 0  # -1 for up, 1 for down, 0 for none
        self._auto_scroll_speed = 0.0  # Percentage of viewport height per second
        
        # Performance optimization
        self._visible_rect = QRect()
        self.needs_repaint = True
        
        # Thread safety
        self.mutex = QMutex()
        
        # Cache state tracking to avoid expensive rebuilds
        self._last_cache_update_time = 0.0
        self._last_rebuild_time = 0.0
        self._last_rebuild_params = None  # (image_paths, thumbnail_size, columns, rows)
        self._last_thumbnail_count = 0  # Track thumbnail count changes
        
        # Filename overlay state
        self._filename_overlay_visible = False
        # Cache for basenames that need extensions shown (to avoid O(n²) lookup during painting)
        self._basenames_needing_extensions: set = set()
        # Row heights cache (calculated in _update_thumbnail_rectangles)
        self._row_heights = []
        
        # Inline rename editor
        self._rename_editor: Optional[QLineEdit] = None
        self._editing_thumbnail_index: Optional[int] = None
        self._rename_canceled: bool = False  # Flag to track if rename was canceled
        
        # Padlock icon cache
        self._padlock_pixmap: Optional[QPixmap] = None
        # Cached QFontMetrics for overlay text (avoids ~1s+ per refresh when creating 1400+ times)
        self._overlay_font_metrics_cache: Optional[QFontMetrics] = None
        self._overlay_font_metrics_font_size = 14
        # Cache overlay height per (path, width, section_mode) - avoids ~1s recomputation when resize triggers 2nd _update_thumbnail_rectangles
        self._overlay_height_cache: Dict[Tuple[str, int, bool, bool, bool], int] = {}
        
        # Enable drag and drop
        self.setAcceptDrops(True)
        
        # Set focus policy - let the main content widget handle focus
        self.setFocusPolicy(Qt.NoFocus)
        
        # Set minimum size
        self.setMinimumSize(200, 200)
        
        # Connect to main window signals if available
        if hasattr(main_window, 'thumbnail_loaded'):
            main_window.thumbnail_loaded.connect(self.on_thumbnail_loaded)

        # Repaint when deleted placeholders change (formatted list restore)
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            from event_bus import DELETED_PLACEHOLDERS_CHANGED
            main_window.event_bus.subscribe(DELETED_PLACEHOLDERS_CHANGED, self.update)

    def set_thumbnails(self, image_paths: List[str], thumbnail_size: int):
        """Set the thumbnails to display"""
        self._overlay_height_cache.clear()
        # Ensure canvas has a proper size
        if self.size().width() < 200:
            self.resize(800, 600)
        
        with QMutexLocker(self.mutex):
            self.thumbnails.clear()
            for i, path in enumerate(image_paths):
                item = ThumbnailItem(
                    image_path=path,
                    index=i,
                    is_loading=True
                )
                self.thumbnails.append(item)
            
            self.thumbnail_size = thumbnail_size
        
        # Build cache of basenames that need extensions shown (for fast lookup during painting)
        self._build_basename_extension_cache(image_paths)
        
        self.calculate_grid_layout()
        self.needs_repaint = True
        self.update()
        
        # Update rebuild tracking
        current_time = time.time()
        self._last_rebuild_time = current_time
        self._last_rebuild_params = (image_paths.copy(), self.thumbnail_size, self.columns, self.rows)
        self._last_thumbnail_count = len(self.thumbnails)
        
        # Check if no files exist and show status message
        self.check_and_show_empty_directory_message(image_paths)
        
        # If no thumbnails, ensure canvas is properly sized and force repaint after a short delay
        # This handles cases where the widget might not be visible yet during startup
        if not image_paths:
            QTimer.singleShot(100, lambda: self.update() if not self.thumbnails else None)
    
    def check_and_show_empty_directory_message(self, image_paths: List[str]):
        """Check if directory is empty and show appropriate status message"""
        if not image_paths:
            # Get current directory from main window
            current_directory = getattr(self.main_window, 'current_directory', None)
            # Don't show message if no directory is set yet (during initialization)
            if current_directory is None:
                return
            
            # Check if there are any supported image files in the directory
            from thumbnails.thumbnail_constants import get_image_extensions
            from utils import determine_suggested_filters
            
            # Scan directory for supported image files
            supported_files = []
            if os.path.exists(current_directory) and os.path.isdir(current_directory):
                try:
                    with os.scandir(current_directory) as entries:
                        for entry in entries:
                            if entry.is_file():
                                _, ext = os.path.splitext(entry.name)
                                if ext.lower() in get_image_extensions():
                                    supported_files.append(entry.name)
                except Exception:
                    pass
            
            # Track if there are images in the folder (for showing filter buttons)
            self._has_images_in_folder = len(supported_files) > 0
            
            # Check if there's a filter pattern that resulted in no matches
            has_filter = hasattr(self.main_window, 'filter_pattern') and self.main_window.filter_pattern
            
            # If there are supported files and a filter is active, determine suggested filters
            if supported_files and has_filter:
                # Get basenames without extensions for prefix analysis
                basenames = [os.path.splitext(f)[0] for f in supported_files]
                suggested_prefixes = determine_suggested_filters(basenames)
                
                if suggested_prefixes:
                    # Store suggested filters for drawing on canvas
                    self.suggested_filters = suggested_prefixes
                else:
                    # No good suggestions, but keep empty list (will still show "All files(*)" button)
                    self.suggested_filters = []
            else:
                # No filter or no supported files
                self.suggested_filters = []
                # Note: _has_images_in_folder is already set above based on supported_files
            
            # Trigger repaint to show message and buttons
            self.update()
    
    def _build_basename_extension_cache(self, image_paths: List[str]):
        """Build cache of basenames that need extensions shown (for fast lookup during painting)
        
        This avoids O(n²) performance when painting filename overlays for large numbers of thumbnails.
        """
        from collections import Counter
        
        if not image_paths:
            self._basenames_needing_extensions = set()
            return
        
        # Count occurrences of each basename (without extension)
        basename_counts = Counter()
        for path in image_paths:
            if path:
                basename_counts[_path_basename_no_ext(path)] += 1
        
        # Store basenames that appear more than once (need extension shown)
        self._basenames_needing_extensions = {
            basename for basename, count in basename_counts.items() if count > 1
        }

    def reorder_thumbnails(self, image_paths: List[str], force_recalculate_grid=False):
        """Reorder thumbnails without losing loaded pixmaps"""
        self._overlay_height_cache.clear()
        # CRITICAL: Clear EXIF date sections if not in EXIF_DATE mode
        # This ensures sections aren't created from stale exif_date_sections data
        # Also clear duplicate sections if not in DUPLICATES mode
        if hasattr(self.main_window, 'current_sort_mode'):
            if hasattr(self.main_window.current_sort_mode, 'value'):
                if self.main_window.current_sort_mode.value not in ('exif_date', 'exif_year'):
                    if hasattr(self.main_window, 'exif_date_sections'):
                        self.main_window.exif_date_sections = []
                    if hasattr(self.main_window, 'exif_section_expanded'):
                        self.main_window.exif_section_expanded = {}
                # Only clear duplicate_sections if they were actually set (transitioning FROM duplicates mode)
                # This prevents clearing when CNN search or other modes are active
                if (self.main_window.current_sort_mode.value != 'duplicates' and
                    hasattr(self.main_window, 'duplicate_sections') and
                    self.main_window.duplicate_sections):
                    self.main_window.duplicate_sections = []
        
        current_time = time.time()
        
        # Check if we need to rebuild at all
        needs_rebuild = self._needs_rebuild(image_paths, force_recalculate_grid, current_time)
        if not needs_rebuild:
            # Still check for empty directory message if image_paths is empty
            # This ensures suggested filters are updated after operations like rename
            if not image_paths:
                self.check_and_show_empty_directory_message(image_paths)
            return
        
        with QMutexLocker(self.mutex):
            # Check if the order has actually changed
            current_paths = [thumb.image_path for thumb in self.thumbnails]
            # CRITICAL: Even if paths are the same, if order changed (e.g., drag-and-drop),
            # we MUST reorder. Only skip if paths AND order are identical AND not forcing rebuild
            if current_paths == image_paths and not force_recalculate_grid:
                # Paths and order are identical - skip expensive cache rebuild
                # The cache is already valid since paths are identical
                # Only rebuild cache if it doesn't exist (shouldn't happen, but be safe)
                if not hasattr(self, '_basenames_needing_extensions') or self._basenames_needing_extensions is None:
                    self._build_basename_extension_cache(image_paths)
                # Still need to update rectangles and repaint even if order is same
                self._update_thumbnail_rectangles()
                self.needs_repaint = True
                self.update()
                # Check for empty directory message if image_paths is empty
                # This ensures suggested filters are updated after operations like rename
                if not image_paths:
                    self.check_and_show_empty_directory_message(image_paths)
                return
            
            # Create a mapping of image_path -> ThumbnailItem to preserve loaded pixmaps
            # BUT: Only preserve pixmaps if the file still exists and hasn't changed
            thumbnail_map = {}
            for thumbnail in self.thumbnails:
                # Only preserve pixmap if file still exists (file might have been replaced)
                if os.path.exists(thumbnail.image_path):
                    thumbnail_map[thumbnail.image_path] = thumbnail
                else:
                    # File no longer exists - don't preserve pixmap
                    thumbnail.pixmap = None
                    thumbnail.is_loading = True
            
            # Clear and rebuild thumbnails in new order, preserving loaded pixmaps
            self.thumbnails.clear()
            for i, path in enumerate(image_paths):
                if path in thumbnail_map:
                    # Reuse existing thumbnail with loaded pixmap
                    # (thumbnail_map only contains paths that passed exists check when built)
                    existing_thumbnail = thumbnail_map[path]
                    existing_thumbnail.index = i  # Update index for new position
                    existing_thumbnail.rect = None  # Clear old rectangle to force recalculation
                    self.thumbnails.append(existing_thumbnail)
                else:
                    # Create new thumbnail if not found
                    item = ThumbnailItem(
                        image_path=path,
                        index=i,
                        is_loading=True
                    )
                    self.thumbnails.append(item)
            
            # Only recalculate grid layout if forced
            
            # Create section separators if in EXIF_DATE mode or DUPLICATES mode
            self.section_separators.clear()
            is_exif_mode = False
            is_duplicate_mode = False
            if not self._is_reference_graph_mode():
                # CRITICAL: Check sort mode FIRST - only create sections if actually in EXIF_DATE/DUPLICATES mode
                # This prevents sections from being created when sections still have old data
                # Check for EXIF_DATE mode
                is_exif_mode = (hasattr(self.main_window, 'current_sort_mode') and
                    hasattr(self.main_window.current_sort_mode, 'value') and
                    self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
                    hasattr(self.main_window, 'exif_date_sections') and
                    self.main_window.exif_date_sections and
                    len(self.main_window.exif_date_sections) > 0)
                # Check for DUPLICATES mode
                is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                    hasattr(self.main_window.current_sort_mode, 'value') and
                    self.main_window.current_sort_mode.value == 'duplicates' and
                    hasattr(self.main_window, 'duplicate_sections') and
                    self.main_window.duplicate_sections and
                    len(self.main_window.duplicate_sections) > 0)

            
            if is_exif_mode:
                from datetime import datetime
                # Get expand/collapse state (default to expanded)
                expanded_state = getattr(self.main_window, 'exif_section_expanded', {})
                # Get current image path to determine bold state
                current_image_path = getattr(self.main_window, 'current_image_path', None)
                
                separator_index = 0
                # Final safety check: ensure exif_date_sections is still valid before iterating
                if not self.main_window.exif_date_sections or len(self.main_window.exif_date_sections) == 0:
                    # exif_date_sections was cleared - skip section creation
                    pass
                else:
                    for start_idx, month_key in self.main_window.exif_date_sections:
                        # Check if current image is in this section
                        is_bold = False
                        if current_image_path:
                            # Find end index of this section
                            section_idx = None
                            for idx, (s_idx, m_key) in enumerate(self.main_window.exif_date_sections):
                                if s_idx == start_idx and m_key == month_key:
                                    section_idx = idx
                                    break
                            if section_idx is not None:
                                if section_idx + 1 < len(self.main_window.exif_date_sections):
                                    next_start_idx, _ = self.main_window.exif_date_sections[section_idx + 1]
                                    end_idx = next_start_idx
                                else:
                                    end_idx = len(image_paths)
                            # Check if current image is in this section
                            try:
                                current_idx = image_paths.index(current_image_path)
                                if start_idx <= current_idx < end_idx:
                                    is_bold = True
                            except ValueError:
                                pass  # current_image_path not in image_paths
                        separator = SectionSeparatorItem(
                            month_key=month_key,
                            index=separator_index,
                            is_expanded=expanded_state.get(month_key, True),
                            is_bold=is_bold
                        )
                        self.section_separators.append(separator)
                        separator_index += 1
            elif is_duplicate_mode:
                # Create separators for duplicate sections

                # Get current image path to determine bold state
                current_image_path = getattr(self.main_window, 'current_image_path', None)
                
                separator_index = 0
                # Final safety check: ensure duplicate_sections is still valid before iterating
                if not self.main_window.duplicate_sections or len(self.main_window.duplicate_sections) == 0:
                    # duplicate_sections was cleared - skip section creation

                    pass
                else:

                    for start_idx, file_hash in self.main_window.duplicate_sections:
                        # Check if current image is in this section
                        is_bold = False
                        if current_image_path:
                            # Find end index of this section
                            section_idx = None
                            for idx, (s_idx, f_hash) in enumerate(self.main_window.duplicate_sections):
                                if s_idx == start_idx and f_hash == file_hash:
                                    section_idx = idx
                                    break
                            if section_idx is not None:
                                if section_idx + 1 < len(self.main_window.duplicate_sections):
                                    next_start_idx, _ = self.main_window.duplicate_sections[section_idx + 1]
                                    end_idx = next_start_idx
                                else:
                                    end_idx = len(image_paths)
                            # Check if current image is in this section
                            try:
                                current_idx = image_paths.index(current_image_path)
                                if start_idx <= current_idx < end_idx:
                                    is_bold = True
                            except ValueError:
                                pass  # current_image_path not in image_paths
                        # For duplicates, use hash as month_key (for compatibility with SectionSeparatorItem)
                        # We'll use a special prefix to distinguish from EXIF sections
                        separator = SectionSeparatorItem(
                            month_key=f"duplicate_{file_hash}",  # Use hash as identifier
                            index=separator_index,
                            is_expanded=True,  # Duplicate sections are always expanded
                            is_bold=is_bold
                        )
                        self.section_separators.append(separator)
                        separator_index += 1
                # Debug output
                if self.main_window.debug_mode:
                    print(f"Created {len(self.section_separators)} duplicate section separators")
            if force_recalculate_grid:
                self.calculate_grid_layout()
            else:
                # Just update thumbnail rectangles without recalculating grid
                self._update_thumbnail_rectangles()
            
            # Update canvas size after creating/updating segmented displays
            if is_exif_mode or is_duplicate_mode:
                self._update_canvas_size()
            elif self._is_reference_graph_mode():
                pass  # graph layout sets canvas size in _calculate_reference_graph_layout
            
            self.needs_repaint = True
            self.update()
        
        # Build cache of basenames that need extensions shown (for fast lookup during painting)
        self._build_basename_extension_cache(image_paths)
        
        # Update rebuild tracking
        current_time = time.time()
        self._last_rebuild_time = current_time
        self._last_rebuild_params = (image_paths.copy(), self.thumbnail_size, self.columns, self.rows)
        self._last_thumbnail_count = len(self.thumbnails)
        
        # Check if no files exist and show status message with suggested filters
        # This ensures suggested filters are updated after operations like rename
        self.check_and_show_empty_directory_message(image_paths)

    def update_separator_bold_states(self):
        """Update bold states of separators based on current active image"""
        if not hasattr(self, 'section_separators') or not self.section_separators:
            return
        
        # Check if we're in EXIF_DATE mode or DUPLICATES mode
        is_exif_mode = (hasattr(self.main_window, 'current_sort_mode') and
                       hasattr(self.main_window.current_sort_mode, 'value') and
                       self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
                       hasattr(self.main_window, 'exif_date_sections') and
                       self.main_window.exif_date_sections)
        is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                            hasattr(self.main_window.current_sort_mode, 'value') and
                            self.main_window.current_sort_mode.value == 'duplicates' and
                            hasattr(self.main_window, 'duplicate_sections') and
                            self.main_window.duplicate_sections)
        
        # If not in a section mode, clear all bold states
        if not is_exif_mode and not is_duplicate_mode:
            for separator in self.section_separators:
                separator.is_bold = False
            self.update()
            return
        
        current_image_path = getattr(self.main_window, 'current_image_path', None)
        if not current_image_path:
            # Clear all bold states
            for separator in self.section_separators:
                separator.is_bold = False
            self.update()
            return
        
        # Get displayed images to find current index
        displayed_images = getattr(self.main_window, 'displayed_images', [])
        if not displayed_images:
            for separator in self.section_separators:
                separator.is_bold = False
            self.update()
            return
        
        try:
            current_idx = displayed_images.index(current_image_path)
        except ValueError:
            # Current image not in displayed images
            for separator in self.section_separators:
                separator.is_bold = False
            self.update()
            return
        
        # Update bold state for each separator
        for separator in self.section_separators:
            separator.is_bold = False  # Clear first
            if is_exif_mode and separator.index < len(self.main_window.exif_date_sections):
                start_idx, month_key = self.main_window.exif_date_sections[separator.index]
                # Find end index of this section
                if separator.index + 1 < len(self.main_window.exif_date_sections):
                    next_start_idx, _ = self.main_window.exif_date_sections[separator.index + 1]
                    end_idx = next_start_idx
                else:
                    end_idx = len(displayed_images)
                # Check if current image is in this section
                if start_idx <= current_idx < end_idx:
                    separator.is_bold = True
            elif is_duplicate_mode and separator.index < len(self.main_window.duplicate_sections):
                start_idx, file_hash = self.main_window.duplicate_sections[separator.index]
                # Find end index of this section
                if separator.index + 1 < len(self.main_window.duplicate_sections):
                    next_start_idx, _ = self.main_window.duplicate_sections[separator.index + 1]
                    end_idx = next_start_idx
                else:
                    end_idx = len(displayed_images)
                # Check if current image is in this section
                if start_idx <= current_idx < end_idx:
                    separator.is_bold = True
        
        self.update()
    

    def _needs_rebuild(self, image_paths: List[str], force_recalculate_grid: bool, current_time: float) -> bool:
        # Optimized early exit checks for rebuild necessity
        if force_recalculate_grid or not self._last_rebuild_params:
            return True
        last_paths, last_size, last_cols, last_rows = self._last_rebuild_params
        # Optimize by combining checks and returning early
        if (
            image_paths != last_paths or
            self.thumbnail_size != last_size or
            self.columns != last_cols or
            self.rows != last_rows
        ):
            return True
        current_thumbnail_count = len(self.thumbnails)
        if (self._last_cache_update_time > self._last_rebuild_time and 
            current_thumbnail_count != self._last_thumbnail_count):
            return True
        elif self._last_cache_update_time > self._last_rebuild_time:
            return False
        return False
    
    def _get_overlay_font_metrics(self):
        """Return cached QFontMetrics for overlay text. Avoids creating 1400+ instances per refresh."""
        if self._overlay_font_metrics_cache is None:
            font = QFont("Arial", self._overlay_font_metrics_font_size, QFont.Normal)
            self._overlay_font_metrics_cache = QFontMetrics(font)
        return self._overlay_font_metrics_cache
    
    def _get_max_text_width_for_thumbnail(self, thumbnail: ThumbnailItem) -> int:
        """Calculate the maximum text width needed for a thumbnail's overlay text.
        Returns the width needed to display the text without wrapping (for segmented layouts).
        """
        # Check what should be displayed
        show_filename = self._filename_overlay_visible
        show_image_size = False
        if getattr(self, 'main_window', None):
            show_image_size = getattr(self.main_window, 'show_image_size', False)
        
        # If nothing to show, return 0
        if not show_filename and not show_image_size:
            return 0
        
        font_metrics = self._get_overlay_font_metrics()
        
        max_width = 0
        
        # Calculate filename width if enabled
        if show_filename:
            # In duplicate mode, show full path instead of just filename
            is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                                 hasattr(self.main_window.current_sort_mode, 'value') and
                                 self.main_window.current_sort_mode.value == 'duplicates')
            
            if is_duplicate_mode:
                # Show directory path (with ~) and filename on separate lines for duplicates
                dir_path = _path_dirname(thumbnail.image_path)
                filename = _path_basename(thumbnail.image_path)
                home_dir = os.path.expanduser("~")
                if dir_path.startswith(home_dir):
                    dir_path = "~" + dir_path[len(home_dir):]
                max_width = max(max_width, font_metrics.horizontalAdvance(dir_path))
                max_width = max(max_width, font_metrics.horizontalAdvance(filename))
            else:
                filename = _path_basename(thumbnail.image_path)
                dot = filename.rfind('.')
                filename_without_ext = filename[:dot] if dot > 0 else filename
                extension = filename[dot:] if dot > 0 else ''
                
                # Check if show_extensions setting is enabled
                show_extensions_setting = False
                if getattr(self, 'main_window', None):
                    show_extensions_setting = getattr(self.main_window, 'show_extensions', False)
                
                # Check if we should show extension
                should_show_extension = show_extensions_setting
                if not should_show_extension:
                    basename_cache = getattr(self, '_basenames_needing_extensions', set())
                    should_show_extension = filename_without_ext in basename_cache
                
                display_filename = filename if should_show_extension else filename_without_ext
                max_width = max(max_width, font_metrics.horizontalAdvance(display_filename))
        
        # Add image size line if enabled
        if show_image_size:
            try:
                if getattr(self, 'main_window', None):
                    _, width, height = self.main_window.get_image_info(thumbnail.image_path)
                    if width > 0 and height > 0:
                        size_text = f"{width}x{height}"
                        max_width = max(max_width, font_metrics.horizontalAdvance(size_text))
            except (OSError, ValueError, AttributeError):
                pass  # Skip size if we can't get it
        
        # For sectioned view, limit max text width to 2 * thumbnail width (but not more than MAX_THUMBNAIL_SIZE)
        # Check if we're in sectioned view
        is_exif_mode = (hasattr(self.main_window, 'current_sort_mode') and
                       hasattr(self.main_window, 'exif_date_sections') and
                       self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
                       self.main_window.exif_date_sections)
        is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                            hasattr(self.main_window, 'duplicate_sections') and
                            self.main_window.current_sort_mode.value == 'duplicates' and
                            self.main_window.duplicate_sections)
        is_section_mode = is_exif_mode or is_duplicate_mode
        
        if is_section_mode:
            # Limit max width to min(thumbnail_size * 2, MAX_THUMBNAIL_SIZE)
            from thumbnails.thumbnail_constants import MAX_THUMBNAIL_SIZE
            max_allowed_width = min(self.thumbnail_size * 2, MAX_THUMBNAIL_SIZE)
            max_width = min(max_width, max_allowed_width)
        
        # Add 8px margin (4px on each side) to the text width
        return max_width + 8 if max_width > 0 else 0
    
    def _get_overlay_height_for_thumbnail(self, thumbnail: ThumbnailItem, thumbnail_width: int) -> int:
        """Calculate overlay height for a specific thumbnail - uses exact same logic as drawing code"""
        # Check what should be displayed (independent settings)
        show_filename = self._filename_overlay_visible
        show_image_size = False
        if getattr(self, 'main_window', None):
            show_image_size = getattr(self.main_window, 'show_image_size', False)
        
        # Check if we're in sectioned view (affects wrapping width)
        is_exif_mode = (hasattr(self.main_window, 'current_sort_mode') and
                       hasattr(self.main_window, 'exif_date_sections') and
                       self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
                       self.main_window.exif_date_sections)
        is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                            hasattr(self.main_window, 'duplicate_sections') and
                            self.main_window.current_sort_mode.value == 'duplicates' and
                            self.main_window.duplicate_sections)
        is_section_mode = is_exif_mode or is_duplicate_mode
        
        # Cache hit avoids recomputation when resize triggers 2nd _update_thumbnail_rectangles (~1s saved)
        # Key must include show_filename and show_image_size so toggling overlay settings invalidates correctly
        cache_key = None
        try:
            cache_key = (thumbnail.image_path, thumbnail_width, is_section_mode, show_filename, show_image_size)
            if cache_key in self._overlay_height_cache:
                return self._overlay_height_cache[cache_key]
        except TypeError:
            cache_key = None  # image_path can be list (unhashable)
        display_path = thumbnail.image_path[0] if (isinstance(thumbnail.image_path, list) and thumbnail.image_path) else thumbnail.image_path
        
        # If nothing to show, return 0
        if not show_filename and not show_image_size:
            if cache_key is not None:
                self._overlay_height_cache[cache_key] = 0
            return 0
        
        font_metrics = self._get_overlay_font_metrics()
        line_height = font_metrics.height()
        
        # Use rect.width() to match drawing code (thumbnail_width includes border space)
        rect_width = thumbnail_width  # thumbnail_width passed in is rect_size which includes BORDER_SPACE
        
        # Use exact same width calculation as drawing code
        available_width = rect_width - 8  # 4px margin on each side (matches drawing code)
        
        if available_width <= 0:
            if cache_key is not None:
                self._overlay_height_cache[cache_key] = 0
            return 0
        
        wrapped_lines = []  # Use same variable name as drawing code
        
        # Calculate filename lines if enabled - use EXACT same logic as drawing code
        if show_filename:
            # In duplicate mode, show full path instead of just filename
            is_duplicate_mode_for_display = (hasattr(self.main_window, 'current_sort_mode') and
                                 hasattr(self.main_window.current_sort_mode, 'value') and
                                 self.main_window.current_sort_mode.value == 'duplicates')
            
            if is_duplicate_mode_for_display:
                dir_path = _path_dirname(display_path)
                filename = _path_basename(display_path)
                home_dir = os.path.expanduser("~")
                if dir_path.startswith(home_dir):
                    dir_path = "~" + dir_path[len(home_dir):]
                separator = "─" * 10
                display_filename = f"{dir_path}\n{separator}\n{filename}"
            else:
                filename = _path_basename(display_path)
                dot = filename.rfind('.')
                filename_without_ext = filename[:dot] if dot > 0 else filename
                
                # Check if show_extensions setting is enabled
                show_extensions_setting = False
                if getattr(self, 'main_window', None):
                    show_extensions_setting = getattr(self.main_window, 'show_extensions', False)
                
                # Check if we should show extension
                should_show_extension = show_extensions_setting
                if not should_show_extension:
                    basename_cache = getattr(self, '_basenames_needing_extensions', set())
                    should_show_extension = filename_without_ext in basename_cache
                
                display_filename = filename if should_show_extension else filename_without_ext
            
            # Use EXACT same wrapping logic as drawing code
            if is_section_mode:
                from thumbnails.thumbnail_constants import MAX_THUMBNAIL_SIZE
                # Calculate max allowed width for wrapping - match drawing code exactly
                thumbnail_size = self.thumbnail_size  # Use thumbnail_size, not thumbnail_width
                max_allowed_width = min(thumbnail_size * 2, MAX_THUMBNAIL_SIZE)
                
                # Check if text needs wrapping - use the full text width (without newlines)
                text_width = font_metrics.horizontalAdvance(display_filename.replace('\n', ' '))
                if text_width > max_allowed_width:
                    # Allow wrapping up to max_allowed_width
                    filename_lines = self._wrap_filename_text(display_filename, max_allowed_width - 8, font_metrics)  # -8 for margins
                else:
                    # Split on explicit newlines only, no wrapping needed
                    filename_lines = display_filename.split('\n')
                    # Filter out empty lines
                    filename_lines = [line for line in filename_lines if line.strip()]
            else:
                # Calculate actual lines needed for this filename (with wrapping)
                filename_lines = self._wrap_filename_text(display_filename, available_width, font_metrics)
            wrapped_lines.extend(filename_lines)
        
        # Add image size line if setting is enabled - use 1-line placeholder for layout
        # (avoids 1400+ get_image_info/file reads per refresh; painting fetches dimensions when needed)
        if show_image_size:
            wrapped_lines.append("0x0")  # Placeholder: 1 line for size; actual dimensions at paint time
        
        # Calculate height using exact same formula as drawing code
        # Drawing: total_height = len(wrapped_lines) * line_height
        #          box_rect height = total_height + 4
        #          box_top = rect.bottom() + overlay_spacing (4)
        #          Total space = overlay_spacing + (len(wrapped_lines) * line_height) + 4
        overlay_spacing = 4  # Space between image and overlay
        padding = 4  # 2px margin top/bottom inside box (matches drawing code)
        
        num_lines = len(wrapped_lines)
        result = overlay_spacing + (num_lines * line_height) + padding
        if cache_key is not None:
            self._overlay_height_cache[cache_key] = result
        return result
    
    def _get_overlay_height(self) -> int:
        """Calculate the height needed for overlay below the image (legacy method for initial layout)
        Note: This is used for initial column calculation. Actual heights are calculated row-by-row."""
        # Check what should be displayed
        show_filename = self._filename_overlay_visible
        show_image_size = False
        if getattr(self, 'main_window', None):
            show_image_size = getattr(self.main_window, 'show_image_size', False)
        
        # If nothing to show, return 0
        if not show_filename and not show_image_size:
            return 0
        
        # Estimate minimum overlay height for column calculation
        # Use a conservative estimate (1 line for filename, 1 for size if enabled)
        font_metrics = self._get_overlay_font_metrics()
        line_height = font_metrics.height()
        
        num_lines = 1 if show_filename else 0  # Minimum 1 line for filename
        if show_image_size:
            num_lines += 1
        
        overlay_spacing = 4  # Space between image and overlay
        padding = 4  # 2px margin top/bottom inside box
        
        return overlay_spacing + (num_lines * line_height) + padding
    
    def _is_reference_graph_mode(self) -> bool:
        return bool(
            getattr(self.main_window, 'reference_graph_active', False)
            and getattr(self.main_window, 'reference_graph_data', None)
            and self.thumbnails
        )

    def _reference_graph_thumbnail_size(self) -> int:
        """Resolve thumb size: user setting when manual, else viewport-fit for the DAG."""
        mw = self.main_window
        if getattr(mw, 'manual_thumbnail_size', False):
            return getattr(mw, 'current_thumbnail_size', self.thumbnail_size)

        from search.reference_graph_layout import compute_reference_graph_dynamic_thumbnail_size

        graph = getattr(mw, 'reference_graph_data', None)
        if not graph:
            return self.thumbnail_size
        size = compute_reference_graph_dynamic_thumbnail_size(
            graph,
            self.get_viewport_width(),
            self.get_viewport_height(),
            self._get_overlay_height(),
        )
        if size != mw.current_thumbnail_size:
            mw.current_thumbnail_size = size
        return size

    def _calculate_reference_graph_layout(self) -> None:
        """Layout thumbnails as a dependency DAG (reference graph presentation)."""
        graph = getattr(self.main_window, 'reference_graph_data', None)
        if not graph or not self.thumbnails:
            return
        from search.reference_graph_layout import (
            compute_reference_graph_layout,
            reference_graph_edge_color_theme,
        )

        thumb_size = self._reference_graph_thumbnail_size()
        self.thumbnail_size = thumb_size

        overlay_h = self._get_overlay_height()
        fit_width = not getattr(self.main_window, 'manual_thumbnail_size', False)
        edge_color_theme = reference_graph_edge_color_theme(self.main_window)
        result = compute_reference_graph_layout(
            graph,
            self.get_viewport_width(),
            thumb_size,
            overlay_h,
            fit_to_viewport_width=fit_width,
            edge_color_theme=edge_color_theme,
        )
        self._reference_graph_layout_result = result
        self._reference_graph_edge_routes = result.edge_routes
        self.section_separators.clear()

        norm_rects = {}
        for path, rect in result.node_rects.items():
            norm_rects[os.path.normpath(path)] = rect

        for thumb in self.thumbnails:
            rect = result.node_rects.get(thumb.image_path)
            if rect is None:
                rect = norm_rects.get(os.path.normpath(thumb.image_path))
            if rect is not None:
                thumb.rect = rect

        self._final_y_offset = result.canvas_height
        self.columns = 1
        self.rows = max(1, len(graph.nodes))
        self.setFixedSize(result.canvas_width, result.canvas_height)
        self.updateGeometry()

    @staticmethod
    def _rounded_edge_path(
        points: List[QPointF], corner_radius: float, terminal: QPointF
    ) -> QPainterPath:
        """Orthogonal polyline with border-radius-style fillets at each bend."""
        import math

        path = QPainterPath()
        n = len(points)
        if n < 2:
            return path
        path.moveTo(points[0])
        if n == 2:
            path.lineTo(terminal)
            return path

        for i in range(1, n - 1):
            p_before = points[i - 1]
            corner = points[i]
            p_after = points[i + 1] if i + 1 < n else terminal

            v_in_x = corner.x() - p_before.x()
            v_in_y = corner.y() - p_before.y()
            v_out_x = p_after.x() - corner.x()
            v_out_y = p_after.y() - corner.y()
            len_in = math.hypot(v_in_x, v_in_y)
            len_out = math.hypot(v_out_x, v_out_y)
            if len_in < 0.5 or len_out < 0.5:
                path.lineTo(corner)
                continue

            r = min(corner_radius, len_in / 2.0, len_out / 2.0)
            if r < 1.0:
                path.lineTo(corner)
                continue

            entry = QPointF(
                corner.x() - v_in_x / len_in * r,
                corner.y() - v_in_y / len_in * r,
            )
            exit_pt = QPointF(
                corner.x() + v_out_x / len_out * r,
                corner.y() + v_out_y / len_out * r,
            )
            path.lineTo(entry)
            path.quadTo(corner, exit_pt)

        path.lineTo(terminal)
        return path

    @staticmethod
    def _arrow_incoming_at_target(
        pts: List[QPointF], min_seg_len: float = 6.0
    ) -> Optional[Tuple[QPointF, QPointF, float, float, float]]:
        """Last long segment into target attach (skips short border stubs for spine routes)."""
        import math

        if len(pts) < 2:
            return None
        tip = pts[-1]
        for i in range(len(pts) - 2, -1, -1):
            prev = pts[i]
            dx = tip.x() - prev.x()
            dy = tip.y() - prev.y()
            seg_len = math.hypot(dx, dy)
            if seg_len >= min_seg_len:
                return prev, tip, seg_len, dx, dy
        prev = pts[-2]
        dx = tip.x() - prev.x()
        dy = tip.y() - prev.y()
        seg_len = math.hypot(dx, dy)
        if seg_len < 0.5:
            return None
        return prev, tip, seg_len, dx, dy

    @staticmethod
    def _arrow_outgoing_from_source(
        pts: List[QPointF], min_seg_len: float = 6.0
    ) -> Optional[Tuple[QPointF, QPointF, float, float, float]]:
        """First long segment leaving source attach (skips short border stubs)."""
        import math

        if len(pts) < 2:
            return None
        origin = pts[0]
        for i in range(1, len(pts)):
            nxt = pts[i]
            dx = nxt.x() - origin.x()
            dy = nxt.y() - origin.y()
            seg_len = math.hypot(dx, dy)
            if seg_len >= min_seg_len:
                return origin, nxt, seg_len, dx, dy
        nxt = pts[1]
        dx = nxt.x() - origin.x()
        dy = nxt.y() - origin.y()
        seg_len = math.hypot(dx, dy)
        if seg_len < 0.5:
            return None
        return origin, nxt, seg_len, dx, dy

    @staticmethod
    def _draw_outward_tail_triangle(
        painter: QPainter,
        color: QColor,
        attach: QPointF,
        ux: float,
        uy: float,
        *,
        half_width: float = 5.0,
        tip_len: float = 8.0,
    ) -> None:
        """Flat base on *attach*; tip points outward along (ux, uy)."""
        from PySide6.QtGui import QPolygonF

        tip = QPointF(attach.x() + ux * tip_len, attach.y() + uy * tip_len)
        left = QPointF(attach.x() - uy * half_width, attach.y() + ux * half_width)
        right = QPointF(attach.x() + uy * half_width, attach.y() - ux * half_width)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([tip, left, right]))
        painter.restore()

    def _paint_reference_graph_edges(
        self,
        painter: QPainter,
        *,
        paths_only: bool = False,
        arrowheads_only: bool = False,
    ) -> None:
        """Draw graph edges: paths under thumbnails; arrowheads on top at the cell border."""
        import math

        from PySide6.QtGui import QPolygonF

        routes = getattr(self, '_reference_graph_edge_routes', None) or []
        if not routes:
            return

        corner_radius = 10.0
        arrow_len = 14.0
        arrow_half = 9.0
        tail_half = arrow_half - 1.0  # full width 2px less than arrowhead (16 vs 18)
        tail_tip_len = 8.0

        for route in routes:
            pts = route.points
            if len(pts) < 2:
                continue
            edge_color = QColor(getattr(route, "color", None) or "#0088FF")
            xs = [p.x() for p in pts]
            ys = [p.y() for p in pts]
            bbox = QRect(
                int(min(xs)) - 6,
                int(min(ys)) - 6,
                int(max(xs) - min(xs)) + 12,
                int(max(ys) - min(ys)) + 12,
            )
            if not self._visible_rect.intersects(bbox):
                continue

            incoming = self._arrow_incoming_at_target(pts)
            outgoing = self._arrow_outgoing_from_source(pts)

            line_end = pts[-1]
            if incoming is not None:
                _prev, tip, seg_len, dx, dy = incoming
                ux, uy = dx / seg_len, dy / seg_len
                shorten = min(arrow_len, max(2.0, seg_len * 0.4))
                line_end = QPointF(tip.x() - ux * shorten, tip.y() - uy * shorten)

            if not arrowheads_only:
                pen = QPen(edge_color, 3.0)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                path = self._rounded_edge_path(pts, corner_radius, line_end)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

            if not paths_only:
                if incoming is not None:
                    _prev, tip, seg_len, dx, dy = incoming
                    ux, uy = dx / seg_len, dy / seg_len
                    base_x = line_end.x()
                    base_y = line_end.y()
                    left = QPointF(base_x - uy * arrow_half, base_y + ux * arrow_half)
                    right = QPointF(base_x + uy * arrow_half, base_y - ux * arrow_half)
                    painter.save()
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(edge_color)
                    painter.drawPolygon(QPolygonF([tip, left, right]))
                    painter.restore()

                if outgoing is not None:
                    origin, _nxt, o_len, odx, ody = outgoing
                    oux, ouy = odx / o_len, ody / o_len
                    self._draw_outward_tail_triangle(
                        painter,
                        edge_color,
                        origin,
                        oux,
                        ouy,
                        half_width=tail_half,
                        tip_len=tail_tip_len,
                    )

    def calculate_grid_layout(self):
        """Calculate grid layout based on current thumbnail size and available space - optimized for square thumbnails"""
        if not self.thumbnails:
            self.columns = 1
            self.rows = 1
            # Ensure canvas has proper size for displaying empty message
            # Get viewport dimensions if available, otherwise use widget size
            viewport_width = self.get_viewport_width()
            viewport_height = self.get_viewport_height()
            if viewport_width <= 0 or viewport_height <= 0:
                viewport_width = max(self.width(), 800)
                viewport_height = max(self.height(), 600)
            self.setFixedSize(max(viewport_width, 800), max(viewport_height, 600))
            return

        if self._is_reference_graph_mode():
            self._calculate_reference_graph_layout()
            return
        
        # Get viewport width from the scroll area for proper centering
        viewport_width = self.get_viewport_width()
        
        # Get available width (accounting for margins)
        available_width = viewport_width - (BASE_MARGIN * 2)
        if available_width <= 0:
            available_width = 400  # Fallback
        
        # Simplified calculation for square thumbnails
        # Column calculation uses only width components (overlay height doesn't affect width)
        spacing = THUMBNAIL_SPACING  # Same spacing for both dimensions since thumbnails are square
        cell_width = self.thumbnail_size + BORDER_SPACE + spacing
        
        old_columns = self.columns
        self.columns = max(1, available_width // cell_width)
        
        # Calculate rows
        self.rows = (len(self.thumbnails) + self.columns - 1) // self.columns

        # Adjust row count for collapsed sections in EXIF date mode
        if (hasattr(self.main_window, 'current_sort_mode') and
            self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
            hasattr(self.main_window, 'exif_date_sections') and
            self.main_window.exif_date_sections and
            hasattr(self, 'section_separators') and
            self.section_separators):
            # Count only visible thumbnails (in expanded sections)
            visible_count = 0
            for thumbnail in self.thumbnails:
                # Find which section this thumbnail belongs to
                thumb_section_idx = None
                # Check EXIF sections
                if hasattr(self.main_window, 'exif_date_sections') and self.main_window.exif_date_sections:
                    for sep_idx, (start_idx, month_key) in enumerate(self.main_window.exif_date_sections):
                        if sep_idx + 1 < len(self.main_window.exif_date_sections):
                            next_start_idx, _ = self.main_window.exif_date_sections[sep_idx + 1]
                            end_idx = next_start_idx
                        else:
                            end_idx = len(self.thumbnails)
                        if start_idx <= thumbnail.index < end_idx:
                            thumb_section_idx = sep_idx
                            break
                # Check duplicate sections
                if thumb_section_idx is None and hasattr(self.main_window, 'duplicate_sections') and self.main_window.duplicate_sections:
                    for sep_idx, (start_idx, file_hash) in enumerate(self.main_window.duplicate_sections):
                        if sep_idx + 1 < len(self.main_window.duplicate_sections):
                            next_start_idx, _ = self.main_window.duplicate_sections[sep_idx + 1]
                            end_idx = next_start_idx
                        else:
                            end_idx = len(self.thumbnails)
                        if start_idx <= thumbnail.index < end_idx:
                            thumb_section_idx = sep_idx
                            break
                
                # Check if section is expanded
                if thumb_section_idx is not None and thumb_section_idx < len(self.section_separators):
                    separator = self.section_separators[thumb_section_idx]
                    if not separator.is_expanded:
                        continue  # Skip collapsed thumbnails
                visible_count += 1
            
            # Recalculate rows based on visible thumbnails
            if visible_count > 0:
                self.rows = (visible_count + self.columns - 1) // self.columns
            else:
                self.rows = 0
        
        # Update thumbnail rectangles (calculates row-by-row heights)
        self._update_thumbnail_rectangles()
        
        # Update canvas size to enable scrolling
        self._update_canvas_size()
    
    def _update_thumbnail_rectangles(self):
        """Update the rectangles for all thumbnails based on current grid layout with row-by-row height calculation.
        Properly handles collapsed sections by skipping their thumbnails entirely."""
        if not self.thumbnails:
            return
        if self._is_reference_graph_mode():
            self._calculate_reference_graph_layout()
            return
        
        # First, clear all thumbnail rects and separator rects
        for thumbnail in self.thumbnails:
            thumbnail.rect = None
        # Clear separator rects too (they'll be repositioned below)
        if getattr(self, 'section_separators', None):
            for separator in self.section_separators:
                separator.rect = None
        
        # Pre-calculate constants for square thumbnails
        spacing = THUMBNAIL_SPACING  # Same spacing for both dimensions
        rect_size = self.thumbnail_size + BORDER_SPACE
        cell_width = self.thumbnail_size + BORDER_SPACE + spacing
        
        # Get viewport dimensions for proper centering
        viewport_width = self.get_viewport_width()
        viewport_height = self.get_viewport_height()
        
        # Check if we're in EXIF_DATE mode or DUPLICATES mode and have separators
        is_exif_mode = (hasattr(self.main_window, 'current_sort_mode') and
                       hasattr(self.main_window, 'exif_date_sections') and
                       self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
                       self.main_window.exif_date_sections)
        is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                            hasattr(self.main_window, 'duplicate_sections') and
                            self.main_window.current_sort_mode.value == 'duplicates' and
                            self.main_window.duplicate_sections)
        # Combined check for any section mode
        is_section_mode = is_exif_mode or is_duplicate_mode
        
        # For segmented layouts, adjust cell_width to accommodate text width
        if is_section_mode:
            max_text_width = 0
            for thumbnail in self.thumbnails:
                text_width = self._get_max_text_width_for_thumbnail(thumbnail)
                max_text_width = max(max_text_width, text_width)
            
            # Ensure cell_width is at least as wide as needed for the text
            if max_text_width > 0:
                # cell_width should be at least: thumbnail_size + BORDER_SPACE + spacing
                # But also wide enough for the text
                min_cell_width_for_text = max_text_width + spacing
                cell_width = max(cell_width, min_cell_width_for_text)
            
            # Add 30px spacing between columns in sectioned view
            SECTIONED_COLUMN_SPACING = 30
            # Calculate extra margin needed for text that can extend up to 2x thumbnail width
            from thumbnails.thumbnail_constants import MAX_THUMBNAIL_SIZE
            max_text_width_for_margin = min(self.thumbnail_size * 2, MAX_THUMBNAIL_SIZE)
            # Text box is centered on thumbnail, so it extends (max_text_width - rect_size) / 2 to the left
            extra_margin = max(0, (max_text_width_for_margin - rect_size) // 2) + 10
            min_margin_for_sectioned = BASE_MARGIN + extra_margin
            
            # Recalculate columns based on adjusted cell_width with extra spacing
            # Account for extra margin needed for text overflow
            available_width_for_cols = viewport_width - (min_margin_for_sectioned * 2)
            # Account for spacing between columns: (columns - 1) * SECTIONED_COLUMN_SPACING
            # We need to solve: columns * cell_width + (columns - 1) * SECTIONED_COLUMN_SPACING <= available_width_for_cols
            # This simplifies to: columns * (cell_width + SECTIONED_COLUMN_SPACING) - SECTIONED_COLUMN_SPACING <= available_width_for_cols
            # So: columns <= (available_width_for_cols + SECTIONED_COLUMN_SPACING) / (cell_width + SECTIONED_COLUMN_SPACING)
            self.columns = max(1, int((available_width_for_cols + SECTIONED_COLUMN_SPACING) / (cell_width + SECTIONED_COLUMN_SPACING)))
        
        # Calculate grid dimensions for width
        if len(self.thumbnails) <= self.columns:
            actual_columns = len(self.thumbnails)
        else:
            actual_columns = self.columns
        
        # Calculate total grid width accounting for column spacing in sectioned view
        if is_section_mode:
            SECTIONED_COLUMN_SPACING = 30
            total_grid_width = actual_columns * cell_width + (actual_columns - 1) * SECTIONED_COLUMN_SPACING - spacing
        else:
            total_grid_width = actual_columns * cell_width - spacing
        
        # Calculate horizontal centering offset
        # For sectioned view, need extra margin to account for text that can extend up to 2x thumbnail width
        # Text box is centered on thumbnail center, so if text is wider than thumbnail, it extends to the left
        # For leftmost thumbnail at x_offset, text left edge is at: x_offset + rect_size/2 - max_text_width/2
        # We need this >= margin, so: x_offset >= margin - rect_size/2 + max_text_width/2
        if is_section_mode:
            from thumbnails.thumbnail_constants import MAX_THUMBNAIL_SIZE
            # Text can be up to min(thumbnail_size * 2, MAX_THUMBNAIL_SIZE) wide
            max_text_width = min(self.thumbnail_size * 2, MAX_THUMBNAIL_SIZE)
            # Calculate minimum x_offset needed: BASE_MARGIN + (max_text_width - rect_size)/2 + safety margin
            extra_margin_for_text = max(0, (max_text_width - rect_size) // 2) + 10
            min_margin = BASE_MARGIN + extra_margin_for_text
        else:
            min_margin = BASE_MARGIN
        
        x_offset = max(min_margin, (viewport_width - total_grid_width) // 2)
        
        # Calculate row-by-row positions with variable heights
        y_offset = CANVAS_TOTAL_TOP_MARGIN
        row_heights = []  # Store height of each row for canvas size calculation
        
        # Handle EXIF date separators - they take up full rows
        separator_height = 30  # Height of separator row
        
        # Build helper functions to determine section membership and visibility
        def get_thumbnail_section_index(thumb_index):
            """Get the section index for a thumbnail index, or None"""
            if not is_section_mode:
                return None
            # Check EXIF sections
            if is_exif_mode:
                for sep_idx, (start_idx, month_key) in enumerate(self.main_window.exif_date_sections):
                    if sep_idx + 1 < len(self.main_window.exif_date_sections):
                        next_start_idx, _ = self.main_window.exif_date_sections[sep_idx + 1]
                        end_idx = next_start_idx
                    else:
                        end_idx = len(self.thumbnails)
                    if start_idx <= thumb_index < end_idx:
                        return sep_idx
            # Check duplicate sections
            if is_duplicate_mode:
                for sep_idx, (start_idx, file_hash) in enumerate(self.main_window.duplicate_sections):
                    if sep_idx + 1 < len(self.main_window.duplicate_sections):
                        next_start_idx, _ = self.main_window.duplicate_sections[sep_idx + 1]
                        end_idx = next_start_idx
                    else:
                        end_idx = len(self.thumbnails)
                    if start_idx <= thumb_index < end_idx:
                        return sep_idx
            return None
        
        def is_thumbnail_visible(thumb_index):
            """Check if a thumbnail should be visible (its section is expanded)"""
            if not is_section_mode:
                return True
            section_idx = get_thumbnail_section_index(thumb_index)
            if section_idx is None:
                return True  # Not in any section, so visible
            if section_idx < len(self.section_separators):
                separator = self.section_separators[section_idx]
                return separator.is_expanded
            return True
        
        # Build a map of section start index to separator for quick lookup
        section_to_separator = {}
        if is_section_mode and self.section_separators:
            for separator in self.section_separators:
                if is_exif_mode and separator.index < len(self.main_window.exif_date_sections):
                    start_idx, month_key = self.main_window.exif_date_sections[separator.index]
                    section_to_separator[start_idx] = separator
                elif is_duplicate_mode and separator.index < len(self.main_window.duplicate_sections):
                    start_idx, file_hash = self.main_window.duplicate_sections[separator.index]
                    section_to_separator[start_idx] = separator
        # Process thumbnails: only add visible ones to rows, skip collapsed ones entirely
        # Initialize row tracking for segmented displays

        self._index_to_row.clear()
        self._row_to_indices.clear()
        current_row_number = 0
        current_row_thumbnails = []  # Only visible thumbnails in current row
        positioned_separator_indices = set()  # Track which separators we've positioned
        
        for thumb_idx, thumbnail in enumerate(self.thumbnails):
            # Check if this thumbnail starts a new section
            if is_section_mode and thumbnail.index in section_to_separator:
                separator = section_to_separator[thumbnail.index]
                if separator.index not in positioned_separator_indices:
                    # First, position any thumbnails we've accumulated in the current row
                    if current_row_thumbnails:
                        # Calculate max overlay height
                        max_row_overlay_height = 0
                        for thumb in current_row_thumbnails:
                            overlay_height = self._get_overlay_height_for_thumbnail(thumb, rect_size)
                            max_row_overlay_height = max(max_row_overlay_height, overlay_height)
                        
                        # Row height does NOT include spacing - spacing is added only between rows in same section
                        row_height = rect_size + max_row_overlay_height
                        row_heights.append(row_height)
                        
                        # Position thumbnails
                        for col, thumb in enumerate(current_row_thumbnails):
                            if is_section_mode:
                                # Add 30px spacing between columns in sectioned view
                                SECTIONED_COLUMN_SPACING = 30
                                x = x_offset + col * (cell_width + SECTIONED_COLUMN_SPACING)
                            else:
                                x = x_offset + col * cell_width
                            thumb.rect = QRect(x, y_offset, rect_size, rect_size)
                        
                        # Track row layout for navigation
                        if current_row_number not in self._row_to_indices:
                            self._row_to_indices[current_row_number] = []
                        for thumb in current_row_thumbnails:
                            self._index_to_row[thumb.index] = current_row_number
                            self._row_to_indices[current_row_number].append(thumb.index)

                        current_row_number += 1
                        y_offset += row_height
                        # No spacing added here - this is the last row before a separator
                        current_row_thumbnails = []
                    
                    # Position separator (always show separators, even for collapsed sections)
                    separator.rect = QRect(BASE_MARGIN, y_offset, viewport_width - (BASE_MARGIN * 2), separator_height)
                    positioned_separator_indices.add(separator.index)
                    y_offset += separator_height
            
            # Only add thumbnail to row if it's visible (section is expanded)
            if is_thumbnail_visible(thumbnail.index):
                current_row_thumbnails.append(thumbnail)
                
                # If row is full, position it and start a new row
                if len(current_row_thumbnails) >= self.columns:
                    # Calculate max overlay height
                    max_row_overlay_height = 0
                    for thumb in current_row_thumbnails:
                        overlay_height = self._get_overlay_height_for_thumbnail(thumb, rect_size)
                        max_row_overlay_height = max(max_row_overlay_height, overlay_height)
                    
                    # Row height does NOT include spacing - spacing is added only between rows in same section
                    row_height = rect_size + max_row_overlay_height
                    row_heights.append(row_height)
                    
                    # Position thumbnails
                    for col, thumb in enumerate(current_row_thumbnails):
                        if is_section_mode:
                            # Add 30px spacing between columns in sectioned view
                            SECTIONED_COLUMN_SPACING = 30
                            x = x_offset + col * (cell_width + SECTIONED_COLUMN_SPACING)
                        else:
                            x = x_offset + col * cell_width
                        thumb.rect = QRect(x, y_offset, rect_size, rect_size)
                    
                    # Track row layout for navigation
                    if current_row_number not in self._row_to_indices:
                        self._row_to_indices[current_row_number] = []
                    for thumb in current_row_thumbnails:
                        self._index_to_row[thumb.index] = current_row_number
                        self._row_to_indices[current_row_number].append(thumb.index)

                    current_row_number += 1
                    y_offset += row_height
                    
                    # Add spacing only between rows (not after last row of section)
                    if is_section_mode:
                        # In sectioned view, only add spacing if next row is in same section
                        next_thumb_idx = thumb_idx + 1
                        if next_thumb_idx < len(self.thumbnails):
                            next_thumb = self.thumbnails[next_thumb_idx]
                            # Check if next thumbnail starts a new section
                            is_next_section_start = (is_section_mode and 
                                                     next_thumb.index in section_to_separator)
                            # Check if next thumbnail is in same section (if visible)
                            if not is_next_section_start and is_thumbnail_visible(next_thumb.index):
                                current_section = get_thumbnail_section_index(thumbnail.index)
                                next_section = get_thumbnail_section_index(next_thumb.index)
                                if current_section == next_section:
                                    # Next row is in same section - add spacing
                                    y_offset += spacing
                    else:
                        # In non-sectioned view, always add spacing between rows
                        y_offset += spacing
                    
                    current_row_thumbnails = []
            # If thumbnail is not visible (collapsed section), skip it entirely
        
        # Handle remaining thumbnails in the last incomplete row
        if current_row_thumbnails:
            # Calculate max overlay height
            max_row_overlay_height = 0
            for thumb in current_row_thumbnails:
                overlay_height = self._get_overlay_height_for_thumbnail(thumb, rect_size)
                max_row_overlay_height = max(max_row_overlay_height, overlay_height)
            
            # Row height does NOT include spacing - this is the last row, so no spacing needed
            row_height = rect_size + max_row_overlay_height
            row_heights.append(row_height)
            
            # Position thumbnails
            for col, thumb in enumerate(current_row_thumbnails):
                if is_section_mode:
                    # Add 30px spacing between columns in sectioned view
                    SECTIONED_COLUMN_SPACING = 30
                    x = x_offset + col * (cell_width + SECTIONED_COLUMN_SPACING)
                else:
                    x = x_offset + col * cell_width
                thumb.rect = QRect(x, y_offset, rect_size, rect_size)
            
            # Track row layout for last incomplete row
            if current_row_number not in self._row_to_indices:
                self._row_to_indices[current_row_number] = []
            for thumb in current_row_thumbnails:
                self._index_to_row[thumb.index] = current_row_number
                self._row_to_indices[current_row_number].append(thumb.index)

            y_offset += row_height
            # No spacing added - this is the last row
        
        # Store row heights for canvas size calculation
        self._row_heights = row_heights
        # Store final y_offset for canvas size calculation (includes all spacing and separators)
        self._final_y_offset = y_offset
        
        # Also update separator positions to account for any row height changes
        # (Separators are already positioned above, but we need to ensure they're in the right place)
        
        # Calculate total grid height for vertical centering
        # y_offset already includes all row heights, spacing between rows, and separator heights
        # Subtract the starting offset to get the actual content height
        total_grid_height = y_offset - CANVAS_TOTAL_TOP_MARGIN
        
        # Vertical alignment: TOP for EXIF mode, CENTER for other modes
        # For EXIF mode, always align to top (no centering)
        # For other modes, center if the grid is smaller than the viewport
        if not is_exif_mode and total_grid_height < viewport_height - CANVAS_TOTAL_TOP_MARGIN - CANVAS_TOTAL_BOTTOM_MARGIN:
            centering_offset = (viewport_height - CANVAS_TOTAL_TOP_MARGIN - CANVAS_TOTAL_BOTTOM_MARGIN - total_grid_height) // 2
            # Adjust all thumbnail y positions by centering offset
            for thumbnail in self.thumbnails:
                if thumbnail.rect:
                    thumbnail.rect = QRect(thumbnail.rect.x(), thumbnail.rect.y() + centering_offset, 
                                         thumbnail.rect.width(), thumbnail.rect.height())
            # Also adjust separator positions (shouldn't happen in non-EXIF mode, but just in case)
            if is_exif_mode and self.section_separators:
                for separator in self.section_separators:
                    if separator.rect:
                        separator.rect = QRect(separator.rect.x(), separator.rect.y() + centering_offset,
                                             separator.rect.width(), separator.rect.height())

    def _update_canvas_size(self):
        """Update the canvas size to enable scrolling and centering (using row-by-row heights)"""
        if not self.thumbnails:
            return
        
        # Get effective viewport dimensions
        effective_viewport_width = self.get_viewport_width()
        effective_viewport_height = self.get_viewport_height()
        
        # Calculate required grid dimensions
        spacing = THUMBNAIL_SPACING
        cell_width = self.thumbnail_size + BORDER_SPACE + spacing
        
        # Calculate grid width
        total_grid_width = self.columns * cell_width - spacing
        
        # Calculate grid height using final y_offset (includes all spacing and separators)
        if hasattr(self, '_final_y_offset'):
            total_grid_height = self._final_y_offset - CANVAS_TOTAL_TOP_MARGIN
        elif getattr(self, '_row_heights', None):
            # Fallback: sum row heights (but this doesn't account for spacing between rows or separators)
            # Count separators if in section mode
            separator_count = 0
            separator_height = 30
            if getattr(self, 'section_separators', None):
                separator_count = len(self.section_separators)
            # Estimate: sum of row heights + spacing between rows + separator heights
            num_rows = len(self._row_heights)
            spacing_between_rows = spacing * max(0, num_rows - 1) if num_rows > 1 else 0
            total_grid_height = sum(self._row_heights) + spacing_between_rows + (separator_count * separator_height)
        else:
            # Fallback: use minimum overlay height estimate
            min_overlay_height = self._get_overlay_height()
            cell_height = self.thumbnail_size + BORDER_SPACE + spacing + min_overlay_height
            total_grid_height = self.rows * cell_height - spacing
        
        # Calculate canvas size to allow for centering
        # Canvas should be at least as large as the viewport, but can be larger for centering
        canvas_width = max(effective_viewport_width, total_grid_width + (BASE_MARGIN * 2))
        canvas_height = max(effective_viewport_height, total_grid_height + CANVAS_TOTAL_TOP_MARGIN + CANVAS_TOTAL_BOTTOM_MARGIN)
        
        # Set canvas size
        self.setFixedSize(canvas_width, canvas_height)
        # Notify parent scroll area that size has changed
        self.updateGeometry()

    def get_viewport_width(self):
        """Get the viewport width from the scroll area, accounting for scrollbars and file tree"""
        # Find the scroll area parent
        scroll_area = self.parent()
        while scroll_area and not hasattr(scroll_area, 'viewport'):
            scroll_area = scroll_area.parent()
        
        if scroll_area and hasattr(scroll_area, 'viewport'):
            # Get the actual viewport width from the scroll area
            viewport_width = scroll_area.viewport().width()
            
            # Add fudge factor to account for potential scrollbar space
            # Get the actual scrollbar width from Qt style
            scrollbar_fudge_factor = self._get_scrollbar_width()
            viewport_width -= scrollbar_fudge_factor
            
            return viewport_width
        
        # Fallback to canvas width if no scroll area found
        return self.width()
    
    def get_viewport_height(self):
        """Get the viewport height from the scroll area"""
        # Find the scroll area parent
        scroll_area = self.parent()
        while scroll_area and not hasattr(scroll_area, 'viewport'):
            scroll_area = scroll_area.parent()
        
        if scroll_area and hasattr(scroll_area, 'viewport'):
            # Get the actual viewport height from the scroll area
            return scroll_area.viewport().height()
        
        # Fallback to canvas height if no scroll area found
        return self.height()
    
    def _get_scrollbar_width(self):
        """Get the actual scrollbar width from Qt style"""
        # Cache the result to avoid repeated calls
        if not hasattr(self, '_cached_scrollbar_width'):
            try:
                # Get the application instance
                app = QApplication.instance()
                if app:
                    # Get the scrollbar extent from the current style
                    self._cached_scrollbar_width = app.style().pixelMetric(QStyle.PM_ScrollBarExtent)
                else:
                    # Fallback if no application instance
                    self._cached_scrollbar_width = 15  # Default macOS value
            except (AttributeError, RuntimeError):
                # Fallback if method doesn't exist or other issues
                self._cached_scrollbar_width = 15  # Default macOS value
        
        return self._cached_scrollbar_width
    
    def on_thumbnail_loaded(self, image_path: str, pixmap: QPixmap, size: int):
        """Handle thumbnail loaded signal from main window"""
        # Allow size mismatches within a reasonable range (e.g., 20px difference)
        # This handles transitions between thumbnail and browse modes
        # When size differs more (e.g. startup race: worker loads before layout finalizes),
        # scale the pixmap to canvas size instead of rejecting - ensures specific-files mode
        # shows thumbnails even when get_effective_display_size changes between load and display
        size_diff = abs(size - self.thumbnail_size)
        if size_diff > 20 and pixmap and not pixmap.isNull():
            pixmap = pixmap.scaled(
                self.thumbnail_size, self.thumbnail_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            size = self.thumbnail_size
        elif size_diff > 20:
            return
        
        with QMutexLocker(self.mutex):
            # Safety check: if thumbnails list is empty, skip update
            # This prevents race conditions when directory is switched during loading
            if not self.thumbnails:
                return
            
            # Primary validation: check if path is still in displayed_images
            # This works for both directory mode and specific files mode
            try:
                if (not hasattr(self.main_window, 'displayed_images') or 
                    image_path not in self.main_window.displayed_images):
                    return  # Path is no longer in displayed_images, ignore this callback
            except (AttributeError, RuntimeError):
                # Main window might be in inconsistent state during directory switch
                # Continue with thumbnails list check as fallback
                pass
            
            # Additional validation: directory match check (only for normal directory mode)
            # Skip this check in specific_files_active mode since files can be from multiple directories
            try:
                if (not getattr(self.main_window, 'specific_files_active', False) and 
                    hasattr(self.main_window, 'current_directory') and self.main_window.current_directory):
                    path_dir = _path_dirname(image_path)
                    current_dir = (self.main_window.current_directory or '').rstrip('/')
                    if path_dir != current_dir:
                        return  # Path is from a different directory, ignore this stale callback
            except (AttributeError, RuntimeError, OSError):
                pass
                
            # Find and update the thumbnail in a single pass
            # This is the authoritative check - if it's not in thumbnails, it's stale
            for thumbnail in self.thumbnails:
                if thumbnail.image_path == image_path:
                    # Check if pixmap is null or invalid - always update in that case
                    pixmap_is_valid = thumbnail.pixmap is not None and not thumbnail.pixmap.isNull()
                    
                    # CRITICAL: If thumbnail is marked as loading, always update (even if pixmap exists)
                    # This ensures force refresh works correctly - invalidate_thumbnails() marks as loading
                    # Also always update if current pixmap is null/invalid (blank thumbnail)
                    if pixmap_is_valid and not thumbnail.is_loading:
                        # Skip redundant loads; always refresh when session transform may differ
                        if image_path not in self.main_window.image_transformations:
                            return
                    
                    # Thumbnail is loading or has no pixmap - proceed with update
                    
                    # Validate incoming pixmap before applying
                    if pixmap is None or pixmap.isNull():
                        # Don't update with invalid pixmap, but mark as not loading
                        thumbnail.is_loading = False
                        return
                    
                    # Apply transformations if they exist for this image
                    # Add safety check to prevent accessing main_window during directory switch
                    try:
                        transformed_pixmap = self._apply_transformations_to_thumbnail(pixmap, image_path)
                    except (AttributeError, RuntimeError):
                        # Main window might be in inconsistent state during directory switch
                        # Use pixmap without transformations as fallback
                        transformed_pixmap = pixmap
                    
                    # Validate transformed pixmap
                    if transformed_pixmap is None or transformed_pixmap.isNull():
                        thumbnail.is_loading = False
                        return
                    
                    thumbnail.pixmap = transformed_pixmap
                    thumbnail.is_loading = False
                    self.needs_repaint = True
                    self.update()
                    
                    # Update cache tracking - only for content changes, not layout changes
                    # This will trigger a repaint but not a full rebuild unless layout changed
                    self._last_cache_update_time = time.time()
                    break
    
    def _apply_transformations_to_thumbnail(self, pixmap: QPixmap, image_path: str) -> QPixmap:
        """Apply stored transformations to a thumbnail pixmap"""
        # Get transformations from main window
        if image_path not in self.main_window.image_transformations:
            return pixmap
        
        rotation, flip_h, flip_v = self.main_window.image_transformations[image_path]
        
        # Apply transformations
        transform = QTransform()
        
        if rotation != 0:
            transform.rotate(rotation)
        
        if flip_h:
            transform.scale(-1, 1)
        
        if flip_v:
            transform.scale(1, -1)
        
        if not transform.isIdentity():
            return pixmap.transformed(transform, Qt.SmoothTransformation)
        
        return pixmap
    
    def set_thumbnail_loaded(self, index: int, pixmap: QPixmap):
        """Set a thumbnail as loaded (for external updates)"""
        if 0 <= index < len(self.thumbnails):
            with QMutexLocker(self.mutex):
                # Only skip if thumbnail already has a valid pixmap and is not loading
                # This allows reloading when pixmap was cleared or is invalid
                existing_pixmap = self.thumbnails[index].pixmap
                if existing_pixmap is not None and not existing_pixmap.isNull() and not self.thumbnails[index].is_loading:
                    return
                

                transformed_pixmap = self._apply_transformations_to_thumbnail(pixmap, self.thumbnails[index].image_path)
                # Apply transformations if they exist for this image
                
                self.thumbnails[index].pixmap = transformed_pixmap
                self.thumbnails[index].is_loading = False
                self.needs_repaint = True
                self.update()
                
                # Update cache tracking
                self._last_cache_update_time = time.time()
    
    def set_highlighted_index(self, index: int):
        """Set the highlighted thumbnail index"""
        if self.highlighted_index != index:
            self.highlighted_index = index
            self.needs_repaint = True
            self.update()
    
    def scroll_to_highlighted(self, index: int = None):
        """Scroll to the highlighted thumbnail only if it's not fully visible"""
        if not (0 <= self.highlighted_index < len(self.thumbnails)):
            return
        
        # Debounce rapid scroll calls to prevent jumping
        current_time = time.time()
        if hasattr(self, '_last_scroll_time') and current_time - self._last_scroll_time < 0.05:  # 50ms debounce
            return
        self._last_scroll_time = current_time
        
        index_to_use = index if index is not None else self.highlighted_index
        thumbnail = self.thumbnails[index_to_use]
        
        # Check if thumbnail is in a collapsed section (EXIF date mode or duplicate mode)
        is_exif_mode = (hasattr(self.main_window, 'current_sort_mode') and
                       self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
                       hasattr(self.main_window, 'exif_date_sections') and
                       self.main_window.exif_date_sections)
        is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                            self.main_window.current_sort_mode.value == 'duplicates' and
                            hasattr(self.main_window, 'duplicate_sections') and
                            self.main_window.duplicate_sections)
        if (is_exif_mode or is_duplicate_mode) and getattr(self, 'section_separators', None):
            # Find which section this thumbnail belongs to
            thumb_section_idx = None
            # Check EXIF sections
            if is_exif_mode:
                for sep_idx, (start_idx, month_key) in enumerate(self.main_window.exif_date_sections):
                    if sep_idx + 1 < len(self.main_window.exif_date_sections):
                        next_start_idx, _ = self.main_window.exif_date_sections[sep_idx + 1]
                        end_idx = next_start_idx
                    else:
                        end_idx = len(self.thumbnails)
                    if start_idx <= thumbnail.index < end_idx:
                        thumb_section_idx = sep_idx
                        break
            # Check duplicate sections
            if thumb_section_idx is None and is_duplicate_mode:
                for sep_idx, (start_idx, file_hash) in enumerate(self.main_window.duplicate_sections):
                    if sep_idx + 1 < len(self.main_window.duplicate_sections):
                        next_start_idx, _ = self.main_window.duplicate_sections[sep_idx + 1]
                        end_idx = next_start_idx
                    else:
                        end_idx = len(self.thumbnails)
                    if start_idx <= thumbnail.index < end_idx:
                        thumb_section_idx = sep_idx
                        break
            
            # Check if section is collapsed (duplicate sections are always expanded, but check anyway)
            if thumb_section_idx is not None and thumb_section_idx < len(self.section_separators):
                separator = self.section_separators[thumb_section_idx]
                if not separator.is_expanded and separator.rect:
                    # Scroll to separator instead of thumbnail
                    rect = separator.rect
                    # Find the scroll area using multiple strategies
                    scroll_area = None
                    # Try attribute on self (canvas' parent container)
                    if hasattr(self, 'scroll_area'):
                        scroll_area = self.scroll_area
                    # Try parent hierarchy
                    if not scroll_area:
                        scroll_area = self.parent()
                        while scroll_area and not hasattr(scroll_area, 'verticalScrollBar'):
                            scroll_area = scroll_area.parent()
                    # Last fallback: use parent's scroll_area if available (for multi-level nesting)
                    if not scroll_area and hasattr(self, 'parent') and callable(self.parent):
                        container = self.parent()
                        if hasattr(container, 'scroll_area'):
                            scroll_area = container.scroll_area
                    
                    if scroll_area and hasattr(scroll_area, 'verticalScrollBar'):
                        scroll_bar = scroll_area.verticalScrollBar()
                        viewport = scroll_area.viewport()
                        viewport_top = scroll_bar.value()
                        viewport_height = viewport.height()
                        viewport_bottom = viewport_top + viewport_height
                        separator_top = rect.y()
                        separator_bottom = rect.y() + rect.height()
                        
                        # Use proper margin constants for consistent spacing
                        top_margin = CANVAS_TOTAL_TOP_MARGIN  # 14px from constants
                        bottom_margin = CANVAS_TOTAL_BOTTOM_MARGIN  # 10px from constants
                        margin = 5  # Small margin to prevent constant micro-scrolling
                        
                        # Check if separator is already visible
                        if (separator_top >= viewport_top - margin and
                            separator_bottom <= viewport_bottom + margin):
                            return
                        
                        if separator_top < viewport_top:
                            # Separator is above viewport - scroll up to show it
                            target_scroll_position = max(0, separator_top - top_margin)
                        elif separator_bottom > viewport_bottom:
                            # Separator is below viewport - scroll down to show it
                            target_scroll_position = separator_bottom - viewport_height + bottom_margin
                            max_scroll = scroll_bar.maximum()
                            target_scroll_position = min(target_scroll_position, max_scroll)
                        else:
                            return
                        
                        scroll_bar.setValue(int(target_scroll_position))
                    return
        
        if not thumbnail.rect:
            return

        # Find the scroll area using multiple strategies (similar to file_context_0/_get_canvas_visible_thumbnail_indices)
        scroll_area = None
        # Try attribute on self (canvas' parent container)
        if hasattr(self, 'scroll_area'):
            scroll_area = self.scroll_area
        # Try parent hierarchy
        if not scroll_area:
            scroll_area = self.parent()
            while scroll_area and not hasattr(scroll_area, 'verticalScrollBar'):
                scroll_area = scroll_area.parent()
        # Last fallback: use parent's scroll_area if available (for multi-level nesting)
        if not scroll_area and hasattr(self, 'parent') and callable(self.parent):
            container = self.parent()
            if hasattr(container, 'scroll_area'):
                scroll_area = container.scroll_area

        if not (scroll_area and hasattr(scroll_area, 'verticalScrollBar')):
            return

        rect = thumbnail.rect
        scroll_bar = scroll_area.verticalScrollBar()
        viewport = scroll_area.viewport()

        # -- Find viewport_top using scroll bar value (as in context code) --
        # This is the Y-position of the visible top of the canvas inside the scrolled area.
        viewport_top = scroll_bar.value()
        viewport_height = viewport.height()
        viewport_bottom = viewport_top + viewport_height
        thumbnail_top = rect.y()
        # Include overlay height in thumbnail bottom for proper scrolling
        # Calculate overlay height for this specific thumbnail
        overlay_height = self._get_overlay_height_for_thumbnail(thumbnail, rect.width())
        thumbnail_bottom = rect.y() + rect.height() + overlay_height
        # Add some margin to the visibility check to prevent micro-adjustments
        margin = 5  # Small margin to prevent constant micro-scrolling
        if (thumbnail_top >= viewport_top - margin and
            thumbnail_bottom <= viewport_bottom + margin):
            return

        # Use proper margin constants for consistent spacing
        top_margin = CANVAS_TOTAL_TOP_MARGIN  # 14px from constants
        bottom_margin = CANVAS_TOTAL_BOTTOM_MARGIN  # 10px from constants

        if thumbnail_top < viewport_top:
            # Thumbnail is above viewport - scroll up to show it with proper top margin
            target_scroll_position = max(0, thumbnail_top - top_margin)
        elif thumbnail_bottom > viewport_bottom:
            # Thumbnail is below viewport - scroll down just enough to show it
            target_scroll_position = thumbnail_bottom - viewport_height + bottom_margin
            max_scroll = scroll_bar.maximum()
            target_scroll_position = min(target_scroll_position, max_scroll)
        else:
            # This shouldn't happen due to our visibility check above
            return

        max_scroll = scroll_bar.maximum()
        target_scroll_position = max(0, min(target_scroll_position, max_scroll))
        scroll_bar.setValue(target_scroll_position)
    
    def set_selected_indices(self, indices: Set[int]):
        """Set the selected thumbnail indices"""
        if self.selected_indices != indices:
            self.selected_indices = indices.copy()
            self.needs_repaint = True
            self.update()
    
    def get_row_for_index(self, index: int) -> Optional[int]:
        """Get the row number (0-based) for a given thumbnail index.
        Returns None if index is not in any row (e.g., collapsed section).
        """
        result = self._index_to_row.get(index)

        return result
    
    def get_indices_in_row(self, row_number: int) -> List[int]:
        """Get all thumbnail indices in a given row number (0-based).
        Returns empty list if row doesn't exist.
        """
        result = self._row_to_indices.get(row_number, []).copy()

        return result
    
    def get_total_rows(self) -> int:
        """Get the total number of rows in the current layout."""
        if not self._row_to_indices:
            return 0
        return max(self._row_to_indices.keys()) + 1 if self._row_to_indices else 0
    
    def is_segmented_layout(self) -> bool:
        """Check if we're in a segmented layout mode (EXIF date or duplicates)."""
        is_exif_mode = (hasattr(self.main_window, 'current_sort_mode') and
                       hasattr(self.main_window, 'exif_date_sections') and
                       self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
                       self.main_window.exif_date_sections)
        is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                            hasattr(self.main_window, 'duplicate_sections') and
                            self.main_window.current_sort_mode.value == 'duplicates' and
                            self.main_window.duplicate_sections)
        result = is_exif_mode or is_duplicate_mode

        return result

    def set_multi_select_mode(self, enabled: bool):
        """Set multi-select mode"""
        if self.multi_select_mode != enabled:
            self.multi_select_mode = enabled
            self.needs_repaint = True
            self.update()
    
    def set_filename_overlay_visible(self, visible: bool):
        """Set filename overlay visibility and recalculate layout while preserving top thumbnail position"""
        if self._filename_overlay_visible == visible:
            return
        
        # Save OLD overlay height before changing visibility
        old_overlay_height = self._get_overlay_height()
        
        # Find scroll area to preserve scroll position
        scroll_area = None
        if hasattr(self, 'scroll_area'):
            scroll_area = self.scroll_area
        if not scroll_area:
            scroll_area = self.parent()
            while scroll_area and not hasattr(scroll_area, 'verticalScrollBar'):
                scroll_area = scroll_area.parent()
        if not scroll_area and hasattr(self, 'parent') and callable(self.parent):
            container = self.parent()
            if hasattr(container, 'scroll_area'):
                scroll_area = container.scroll_area
        
        # Save the top visible thumbnail index and its position relative to viewport
        top_thumbnail_index = None
        top_thumbnail_offset = 0
        if scroll_area and hasattr(scroll_area, 'verticalScrollBar') and self.thumbnails:
            scroll_bar = scroll_area.verticalScrollBar()
            viewport = scroll_area.viewport()
            viewport_top = scroll_bar.value()
            viewport_height = viewport.height()
            
            # Find the topmost visible thumbnail (using OLD overlay height)
            with QMutexLocker(self.mutex):
                for thumbnail in self.thumbnails:
                    if thumbnail.rect:
                        thumb_top = thumbnail.rect.y()
                        thumb_bottom = thumbnail.rect.y() + thumbnail.rect.height()
                        # Calculate overlay height for this specific thumbnail
                        overlay_height = self._get_overlay_height_for_thumbnail(thumbnail, thumbnail.rect.width())
                        thumb_bottom += overlay_height
                        
                        # Check if thumbnail is visible in viewport
                        if thumb_bottom >= viewport_top and thumb_top <= viewport_top + viewport_height:
                            top_thumbnail_index = thumbnail.index
                            top_thumbnail_offset = thumb_top - viewport_top
                            break
        
        # Update visibility flag
        self._filename_overlay_visible = visible
        
        # Recalculate grid layout (this will update cell_size based on NEW overlay height)
        if self.thumbnails:
            self.calculate_grid_layout()
        
        # Restore scroll position to keep top thumbnail in same visual position
        if scroll_area and hasattr(scroll_area, 'verticalScrollBar') and top_thumbnail_index is not None:
            scroll_bar = scroll_area.verticalScrollBar()
            with QMutexLocker(self.mutex):
                if 0 <= top_thumbnail_index < len(self.thumbnails):
                    thumbnail = self.thumbnails[top_thumbnail_index]
                    if thumbnail.rect:
                        # Calculate new scroll position to keep thumbnail at same offset from viewport top
                        new_thumb_top = thumbnail.rect.y()
                        target_scroll = new_thumb_top - top_thumbnail_offset
                        max_scroll = scroll_bar.maximum()
                        target_scroll = max(0, min(target_scroll, max_scroll))
                        scroll_bar.setValue(int(target_scroll))
        
        # Ensure current image stays on screen (may have shifted when overlay 1→2 lines)
        if getattr(self, 'main_window', None) and hasattr(self.main_window, 'ensure_highlighted_visible'):
            QTimer.singleShot(50, self.main_window.ensure_highlighted_visible)
        
        self.needs_repaint = True
        self.update()
    
    def showEvent(self, event):
        """Handle show events - ensure message is displayed when widget becomes visible"""
        super().showEvent(event)
        # If no thumbnails, repaint to show empty message when widget becomes visible
        if not self.thumbnails:
            self.needs_repaint = True
            self.update()
    
    def resizeEvent(self, event):
        """Handle resize events"""
        super().resizeEvent(event)

        # If no thumbnails, always repaint to re-center the empty message
        if not self.thumbnails:
            self.needs_repaint = True
            self.update()
            return

        if self._is_reference_graph_mode():
            self._calculate_reference_graph_layout()
            self.needs_repaint = True
            self.update()
            return

        # Only recalculate if dimensions actually changed
        old_columns = self.columns
        self.calculate_grid_layout()
        
        if old_columns != self.columns:
            # Grid changed, need to update rectangles and canvas size
            self._update_thumbnail_rectangles()
            self._update_canvas_size()
            self.needs_repaint = True
            self.update()
            
            # Update rebuild tracking
            current_time = time.time()
            self._last_rebuild_time = current_time
            if self._last_rebuild_params:
                last_paths, last_size, last_cols, last_rows = self._last_rebuild_params
                self._last_rebuild_params = (last_paths, last_size, self.columns, self.rows)
                self._last_thumbnail_count = len(self.thumbnails)
    
    def paintEvent(self, event: QPaintEvent):
        """Paint the thumbnails on the canvas"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        try:
            # Check if any locked files exist - if so, paint canvas with non-black background
            has_locked_files = False
            if hasattr(self.main_window, 'lock_manager') and self.main_window.lock_manager:
                if hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
                    locked_files = self.main_window.lock_manager.get_locked_files(self.main_window.current_directory)
                    has_locked_files = len(locked_files) > 0
            
            # Paint canvas background
            if has_locked_files:
                # Use locked file background color for canvas
                painter.fillRect(event.rect(), tc.LOCKED_FILE_BACKGROUND_COLOR)
            else:
                # Default black background
                painter.fillRect(event.rect(), tc.DEFAULT_BACKGROUND_COLOR)
            
            # Get visible area for optimization
            self._visible_rect = event.rect()
            
            with QMutexLocker(self.mutex):
                # Check if no thumbnails exist and show message
                if not self.thumbnails:
                    current_directory = getattr(self.main_window, 'current_directory', None)
                    if current_directory is not None:
                        # Get filter pattern
                        filter_pattern = getattr(self.main_window, 'filter_pattern', None)
                        # Always show message when no thumbnails exist
                        if getattr(self.main_window, '_directory_listing_denied', False):
                            message = (
                                "macOS denied access to list images in\n\n"
                                f"{normalize_path_for_display(current_directory)}\n\n"
                                "Enable Full Disk Access for Prowser (or your terminal) under\n"
                                "System Settings → Privacy & Security"
                            )
                        elif filter_pattern and filter_pattern != '*':
                            # Show message about filter pattern
                            message = f"No Images matching filter pattern \"{filter_pattern}\" are available in\n\n{normalize_path_for_display(current_directory)}"
                        else:
                            # No filter pattern or pattern is '*', show generic message
                            message = f"No Images are available in\n\n{normalize_path_for_display(current_directory)}"
                        
                        # Draw centered message with suggested filter buttons if available
                        self._draw_empty_message(painter, message)
                    # No thumbnails and no directory - just paint black canvas
                    return

                if self._is_reference_graph_mode():
                    self._paint_reference_graph_edges(painter, paths_only=True)

                painted_count = 0
                for thumbnail in self.thumbnails:
                    if thumbnail.rect and self._visible_rect.intersects(thumbnail.rect):
                        self._paint_thumbnail(painter, thumbnail)
                        painted_count += 1

                if self._is_reference_graph_mode():
                    self._paint_reference_graph_edges(painter, arrowheads_only=True)
            
            # Paint section separators for EXIF date mode
            if getattr(self, 'section_separators', None):
                for separator in self.section_separators:
                    if separator.rect and self._visible_rect.intersects(separator.rect):
                        self._paint_separator(painter, separator)
            # Paint drop indicator if needed
            self.paintDropIndicator(painter)
        finally:
            painter.end()
    
    def _draw_empty_message(self, painter: QPainter, message: str):
        """Draw a centered message when no thumbnails are available, with suggested filter buttons if available"""
        # Use viewport dimensions for centering (accounts for tree/widget visibility and status bar)
        # This ensures message stays centered when viewport size changes
        canvas_width = self.get_viewport_width()
        canvas_height = self.get_viewport_height()
        
        # Ensure we have valid dimensions (fallback to widget size if viewport not ready)
        if canvas_width <= 0 or canvas_height <= 0:
            canvas_width = max(self.width(), 400)
            canvas_height = max(self.height(), 300)
        
        # Use common utility function to draw message with icon
        draw_message_with_icon(painter, message, canvas_width, canvas_height)
        
        # Draw suggested filter buttons if there are images in the folder
        # (will show at least "All files(*)" button even if no suggested filters)
        if self._has_images_in_folder:
            self._draw_filter_buttons(painter, canvas_width, canvas_height)
    
    def _draw_filter_buttons(self, painter: QPainter, canvas_width: int, canvas_height: int):
        """Draw suggested filter buttons below the empty message"""
        from PySide6.QtGui import QFontMetrics
        from config import ImageBrowserConfig
        
        # Clear previous button rects
        self.filter_button_rects = []
        
        # Calculate position below the message
        # The message is centered, so we'll place buttons centered below it
        font = QFont("Arial", 14)
        painter.setFont(font)
        font_metrics = painter.fontMetrics()
        
        # Button dimensions
        button_height = 32
        button_padding_h = 16
        button_padding_v = 8
        button_spacing = 8
        
        # Calculate button widths for each filter
        button_labels = []
        for prefix in self.suggested_filters:
            filter_pattern = f"{prefix}*"
            button_labels.append(filter_pattern)
        
        # Add "All files(*)" button
        button_labels.append("All files(*)")
        
        # Calculate total width needed
        button_widths = []
        for label in button_labels:
            text_width = font_metrics.horizontalAdvance(label)
            button_width = text_width + (button_padding_h * 2)
            button_widths.append(button_width)
        
        total_width = sum(button_widths) + (button_spacing * (len(button_widths) - 1))
        
        # Starting position (centered)
        start_x = (canvas_width - total_width) // 2
        start_y = (canvas_height // 2) + 120  # Position below the message
        
        # Draw "Suggested filters:" label
        label_font = QFont("Arial", 12)
        label_font.setBold(True)
        painter.setFont(label_font)
        label_metrics = painter.fontMetrics()
        label_text = "Suggested filters:"
        label_width = label_metrics.horizontalAdvance(label_text)
        label_x = (canvas_width - label_width) // 2
        label_y = start_y - 30
        painter.setPen(tc.TEXT_COLOR)
        painter.drawText(label_x, label_y, label_text)
        
        # Draw buttons
        current_x = start_x
        button_y = start_y
        
        for i, (label, width) in enumerate(zip(button_labels, button_widths)):
            button_rect = QRect(current_x, button_y, width, button_height)
            self.filter_button_rects.append((button_rect, label))
            
            # Draw button background (with hover effect if applicable)
            is_hovered = (self._hovered_button_index == i)
            if is_hovered:
                painter.setPen(QPen(tc.THUMBNAIL_EMPTY_FILTER_BTN_BORDER_HOVER, 1))
                painter.setBrush(QBrush(tc.THUMBNAIL_EMPTY_FILTER_BTN_BG_HOVER))
            else:
                painter.setPen(QPen(tc.THUMBNAIL_EMPTY_FILTER_BTN_BORDER, 1))
                painter.setBrush(QBrush(tc.THUMBNAIL_EMPTY_FILTER_BTN_BG))
            painter.drawRoundedRect(button_rect, 5, 5)
            
            # Draw button text
            painter.setFont(font)
            if is_hovered:
                painter.setPen(tc.THUMBNAIL_EMPTY_FILTER_BTN_TEXT_HOVER)
            else:
                painter.setPen(tc.TEXT_COLOR)
            text_x = current_x + button_padding_h
            text_y = button_y + button_height // 2 + font_metrics.ascent() // 2 - font_metrics.descent() // 2
            painter.drawText(text_x, text_y, label)
            
            current_x += width + button_spacing
    
    def _apply_filter_from_button(self, filter_pattern: str):
        """Apply a filter pattern from a button click"""
        from config import get_config, ImageBrowserConfig
        
        config = get_config()
        
        if filter_pattern == "All files(*)":
            normalized_pattern = '*'
        else:
            normalized_pattern = ImageBrowserConfig.normalize_filter_pattern(filter_pattern)
        
        self.main_window.filter_pattern = normalized_pattern
        config.update_setting('filter_pattern', normalized_pattern)
        
        if hasattr(self.main_window, 'status_bar_manager'):
            self.main_window.status_bar_manager._update_filter_section(self.main_window)
        
        if hasattr(self.main_window, 'refresh_directory'):
            self.main_window.refresh_directory()
        
        # Clear suggested filters since we're applying a new filter
        self.suggested_filters = []
        self.filter_button_rects = []
        self._hovered_button_index = -1
    
    def _is_file_locked(self, file_path: str) -> bool:
        """Check if a file is locked"""
        if not hasattr(self.main_window, 'lock_manager') or not self.main_window.lock_manager:
            return False
        return self.main_window.lock_manager.is_file_locked(file_path)
    
    def _paint_thumbnail(self, painter: QPainter, thumbnail: ThumbnailItem):
        """Paint a single thumbnail"""
        if not thumbnail.rect:
            return

        rect = thumbnail.rect

        # Safety check: ensure rectangle is valid and within reasonable bounds
        if rect.width() <= 0 or rect.height() <= 0 or rect.x() < -1000 or rect.y() < -1000:
            return

        # Common border radius for all backgrounds and outlines
        border_radius = REGULAR_BORDER_RADIUS

        # Determine if this thumbnail is highlighted or selected
        is_highlighted = thumbnail.index == self.highlighted_index
        is_selected = thumbnail.index in self.selected_indices
        
        # Check if file is locked
        is_locked = self._is_file_locked(thumbnail.image_path)

        # Draw background using rounded rectangle to honor border radius
        if is_highlighted or is_selected:
            if self.multi_select_mode and is_selected:
                # Multi-select highlight - gold background
                bg_color = tc.MULTISELECT_BACKGROUND_COLOR
            elif is_highlighted:
                # Current image highlight - light blue background
                bg_color = tc.CURRENT_IMAGE_BACKGROUND_COLOR
            elif is_selected:
                # Selected but not highlighted - gold background
                bg_color = tc.MULTISELECT_BACKGROUND_COLOR
        else:
            # Default non-current thumbnail cell background
            bg_color = tc.DEFAULT_IMAGE_BACKGROUND_COLOR

        # Fill the rounded rect for background
        background_rect = rect.adjusted(0, 0, -1, -1)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(background_rect, border_radius, border_radius)
        painter.setBrush(Qt.NoBrush)  # Reset after custom fill

        # Draw thumbnail image or loading text
        if thumbnail.pixmap and not thumbnail.pixmap.isNull():
            # Draw the thumbnail image
            inner_margin = 6
            inner_rect = rect.adjusted(inner_margin, inner_margin, -inner_margin, -inner_margin)

            # Scale pixmap to fit inner rect while maintaining aspect ratio
            scaled_pixmap = thumbnail.pixmap.scaled(
                inner_rect.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )

            # Center the pixmap
            x = inner_rect.x() + (inner_rect.width() - scaled_pixmap.width()) // 2
            y = inner_rect.y() + (inner_rect.height() - scaled_pixmap.height()) // 2
            painter.drawPixmap(x, y, scaled_pixmap)

            # Draw border if highlighted or selected (width 0 = none; per-border settings)
            if is_highlighted or is_selected:
                if self.multi_select_mode and is_selected:
                    pen_color = tc.MULTISELECT_BORDER_COLOR
                    border_width = int(getattr(tc, "MULTISELECT_BORDER_WIDTH_PX", 2))
                elif is_highlighted:
                    pen_color = tc.CURRENT_IMAGE_BORDER_COLOR
                    border_width = int(getattr(tc, "CURRENT_IMAGE_BORDER_WIDTH_PX", 2))
                else:
                    pen_color = tc.MULTISELECT_BORDER_COLOR
                    border_width = int(getattr(tc, "MULTISELECT_BORDER_WIDTH_PX", 2))

                if border_width > 0:
                    painter.setPen(QPen(pen_color, border_width))
                    ir = inset_rect_for_stroke(rect, border_width)
                    irad = inset_corner_radius(border_radius, border_width)
                    painter.drawRoundedRect(ir, irad, irad)
        else:
            # Draw loading text or placeholder
            painter.setPen(tc.TEXT_COLOR)
            painter.setFont(QFont("Arial", 8))
            text = f"Loading {thumbnail.index}" if thumbnail.is_loading else f"{thumbnail.index}"
            painter.drawText(rect, Qt.AlignCenter, text)

        # Draw subtle border when not highlighted (inactive cell frame)
        if not (is_highlighted or is_selected):
            _dw = int(getattr(tc, "DEFAULT_IMAGE_BORDER_WIDTH_PX", 1))
            if _dw > 0:
                painter.setPen(QPen(tc.DEFAULT_IMAGE_COLOR, _dw))
                _ir = inset_rect_for_stroke(rect, _dw)
                _irad = inset_corner_radius(border_radius, _dw)
                painter.drawRoundedRect(_ir, _irad, _irad)

        # Draw padlock icon overlay for locked files
        if is_locked and thumbnail.pixmap and not thumbnail.pixmap.isNull():
            self._draw_padlock_overlay(painter, rect)

        # Draw red X overlay for deleted files (formatted list placeholder)
        # Only draw if path in placeholders AND file does not exist (restore = file exists = no X)
        placeholders = getattr(self.main_window, 'deleted_file_placeholders', None)
        if placeholders and thumbnail.image_path in placeholders:
            if not os.path.exists(thumbnail.image_path):
                self._draw_deleted_overlay(painter, rect)

        # Draw filename/image size overlay if enabled (check both settings)
        show_filename = self._filename_overlay_visible
        show_image_size = False
        if getattr(self, 'main_window', None):
            show_image_size = getattr(self.main_window, 'show_image_size', False)
        if show_filename or show_image_size:
            self._draw_filename_overlay(painter, thumbnail, rect)
    

    def _paint_separator(self, painter: QPainter, separator: SectionSeparatorItem):
        """Paint a section separator"""
        if not separator.rect:
            return
        
        from datetime import datetime
        
        rect = separator.rect
        
        # Check if this is a duplicate section (line-only, no text)
        is_duplicate_section = (separator.month_key and 
                                separator.month_key.startswith('duplicate_'))
        
        if is_duplicate_section:
            # For duplicate sections, just draw a line (no text)
            painter.setPen(QPen(tc.TEXT_COLOR, 1))
            line_y = rect.y() + rect.height() // 2
            painter.drawLine(rect.x() + 10, line_y, rect.x() + rect.width() - 10, line_y)
            return
        
        # Format label (month or year based on sort mode)
        if separator.month_key == "undated":
            label = "Undated"
        else:
            # Check if we're in year mode (YYYY format) or month mode (YYYY-MM format)
            is_year_mode = (hasattr(self.main_window, 'current_sort_mode') and
                           hasattr(self.main_window.current_sort_mode, 'value') and
                           self.main_window.current_sort_mode.value == 'exif_year')
            
            if is_year_mode:
                # Year mode - just show the year
                label = separator.month_key
            else:
                # Month mode - parse YYYY-MM format
                try:
                    year, month = separator.month_key.split("-")
                    month_num = int(month)
                    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                    month_name = month_names[month_num - 1]
                    label = f"{separator.month_key} ({month_name} {year})"
                except Exception:
                    label = separator.month_key
        
        # Choose symbol based on expanded state
        symbol = "▽" if separator.is_expanded else "▷"
        
        # Set font (bold if contains active image)
        font = QFont("Arial", 16)
        if separator.is_bold:
            font.setBold(True)
        painter.setFont(font)
        
        # Draw separator line
        painter.setPen(QPen(tc.TEXT_COLOR, 1))
        
        # Calculate text width
        font_metrics = painter.fontMetrics()
        symbol_width = font_metrics.horizontalAdvance(symbol)
        text_width = font_metrics.horizontalAdvance(label)
        
        # Calculate fixed dash length based on character width
        char_width = font_metrics.horizontalAdvance("-")
        fixed_dash_length = char_width * self.SEPARATOR_DASH_LENGTH
        
        # Draw symbol and label
        x = rect.x() + 10
        y = rect.y() + rect.height() // 2 + font_metrics.ascent() // 2
        painter.drawText(x, y, symbol)
        
        # Draw dashes (fixed length before label)
        dash_start_x = x + symbol_width + 5
        dash_end_x = dash_start_x + fixed_dash_length
        dash_y = rect.y() + rect.height() // 2
        painter.drawLine(dash_start_x, dash_y, dash_end_x, dash_y)
        
        # Draw label (starts at same position for all labels)
        painter.drawText(dash_end_x + 5, y, label)
        
        # Draw remaining dashes to fill width
        remaining_start_x = dash_end_x + 5 + text_width + 5
        remaining_end_x = rect.x() + rect.width() - 10
        if remaining_start_x < remaining_end_x:
            painter.drawLine(remaining_start_x, dash_y, remaining_end_x, dash_y)

    def _load_padlock_pixmap(self) -> Optional[QPixmap]:
        """Load the padlock icon from assets folder"""
        if self._padlock_pixmap is not None:
            return self._padlock_pixmap
        
        # Try to load padlock image from assets folder
        padlock_path = os.path.join(os.path.dirname(__file__), "assets", "padlock.png")
        if os.path.exists(padlock_path):
            pixmap = QPixmap(padlock_path)
            if not pixmap.isNull():
                self._padlock_pixmap = pixmap
                return pixmap
        
        # Fallback: return None if image not found
        return None
    
    def _draw_padlock_overlay(self, painter: QPainter, rect: QRect):
        """Draw a padlock icon in the upper-right corner of the thumbnail"""
        # Padlock icon size (scaled with thumbnail size)
        icon_size = max(16, min(32, rect.width() // 8))
        margin = 4
        
        # Position in upper-right corner
        padlock_x = rect.x() + rect.width() - icon_size - margin
        padlock_y = rect.y() + margin
        
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
            return
        
        # Fallback: Draw a simple padlock icon using QPainter if image not found
        painter.save()
        
        # Set gold color for padlock
        padlock_color = QColor(255, 215, 0)  # Gold color
        painter.setPen(QPen(padlock_color, 2))
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
            2, 2
        )
        
        # Draw padlock shackle (arch on top)
        shackle_width = icon_size * 0.5
        shackle_height = icon_size * 0.3
        shackle_x = padlock_x + (icon_size - shackle_width) / 2
        shackle_y = padlock_y + icon_size * 0.1
        
        # Draw arch (semi-circle on top)
        painter.setPen(QPen(padlock_color, 2))
        painter.setBrush(Qt.NoBrush)
        # Draw arc for shackle
        painter.drawArc(
            int(shackle_x), int(shackle_y),
            int(shackle_width), int(shackle_height * 2),
            0, 180 * 16  # 180 degrees
        )
        
        painter.restore()

    def _draw_deleted_overlay(self, painter: QPainter, rect: QRect):
        """Draw red X corner-to-corner over thumbnail (deleted file placeholder in formatted list)"""
        painter.save()
        x_color = QColor(220, 50, 50)
        line_width = 2
        painter.setPen(QPen(x_color, line_width))
        painter.setBrush(Qt.NoBrush)
        margin = line_width
        shorten_factor = 5
        x1, y1 = rect.x() + margin + shorten_factor, rect.y() + margin + shorten_factor
        x2, y2 = rect.right() - margin - shorten_factor, rect.bottom() - margin - shorten_factor
        painter.drawLine(x1, y1, x2, y2)
        painter.drawLine(x2, y1, x1, y2)
        painter.restore()

    def _draw_filename_overlay(self, painter: QPainter, thumbnail: ThumbnailItem, rect: QRect):
        """Draw filename and/or image size overlay below the image (no border)"""
        # Check what should be displayed (independent settings)
        show_filename = self._filename_overlay_visible
        show_image_size = False
        if getattr(self, 'main_window', None):
            show_image_size = getattr(self.main_window, 'show_image_size', False)
        
        # If nothing to show, return early
        if not show_filename and not show_image_size:
            return
        
        FILENAME_TEXT_FONT_SIZE = 14
        font = QFont("Arial", FILENAME_TEXT_FONT_SIZE, QFont.Normal)
        painter.setFont(font)
        available_width = rect.width() - 8  # 4px margin on each side
        font_metrics = painter.fontMetrics()
        main_color = tc.TEXT_COLOR  # Theme-synced (status bar / sidebars)
        box_color = tc.THUMBNAIL_FILENAME_OVERLAY_BOX_COLOR
        
        wrapped_lines = []
        
        # Prepare filename lines if enabled
        if show_filename:
            # In duplicate mode, show full path instead of just filename
            is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                                 hasattr(self.main_window.current_sort_mode, 'value') and
                                 self.main_window.current_sort_mode.value == 'duplicates')
            
            if is_duplicate_mode:
                dir_path = _path_dirname(thumbnail.image_path)
                filename = _path_basename(thumbnail.image_path)
                home_dir = os.path.expanduser("~")
                if dir_path.startswith(home_dir):
                    dir_path = "~" + dir_path[len(home_dir):]
                separator = "─" * 10
                display_filename = f"{dir_path}\n{separator}\n{filename}"
            else:
                filename = _path_basename(thumbnail.image_path)
                dot = filename.rfind('.')
                filename_without_ext = filename[:dot] if dot > 0 else filename
                
                # Check if show_extensions setting is enabled
                show_extensions_setting = False
                if getattr(self, 'main_window', None):
                    show_extensions_setting = getattr(self.main_window, 'show_extensions', False)
                
                # Check if there are other files with the same basename but different extensions
                should_show_extension = show_extensions_setting
                if not should_show_extension:
                    basename_cache = getattr(self, '_basenames_needing_extensions', set())
                    should_show_extension = filename_without_ext in basename_cache
                
                # Use filename with or without extension based on the check
                display_filename = filename if should_show_extension else filename_without_ext
            
            # Check if we're in segmented layout mode (duplicates/month/year)
            is_exif_mode = (hasattr(self.main_window, 'current_sort_mode') and
                           hasattr(self.main_window, 'exif_date_sections') and
                           self.main_window.current_sort_mode.value in ('exif_date', 'exif_year') and
                           self.main_window.exif_date_sections)
            is_duplicate_mode = (hasattr(self.main_window, 'current_sort_mode') and
                                hasattr(self.main_window, 'duplicate_sections') and
                                self.main_window.current_sort_mode.value == 'duplicates' and
                                self.main_window.duplicate_sections)
            is_segmented_layout = is_exif_mode or is_duplicate_mode
            
            # For segmented layouts, allow wrapping if text exceeds min(font_width*2, MAX_THUMBNAIL_SIZE)
            if is_segmented_layout:
                # Calculate max allowed width for wrapping
                from thumbnails.thumbnail_constants import MAX_THUMBNAIL_SIZE
                # rect.width() is the thumbnail width (including border space)
                # We want to limit to 2 * thumbnail_size (not including border)
                thumbnail_width = self.thumbnail_size
                max_allowed_width = min(thumbnail_width * 2, MAX_THUMBNAIL_SIZE)
                
                # Check if text needs wrapping - use the full text width (without newlines)
                text_width = font_metrics.horizontalAdvance(display_filename.replace('\n', ' '))
                if text_width > max_allowed_width:
                    # Allow wrapping up to max_allowed_width
                    filename_lines = self._wrap_filename_text(display_filename, max_allowed_width - 8, font_metrics)  # -8 for margins
                else:
                    # Split on explicit newlines only, no wrapping needed
                    filename_lines = display_filename.split('\n')
                    # Filter out empty lines
                    filename_lines = [line for line in filename_lines if line.strip()]
            else:
                # Calculate actual lines needed for this filename (with wrapping)
                filename_lines = self._wrap_filename_text(display_filename, available_width, font_metrics)
            wrapped_lines.extend(filename_lines)
        
        # Add image size line if setting is enabled
        if show_image_size:
            try:
                # Get image dimensions
                if getattr(self, 'main_window', None):
                    _, width, height = self.main_window.get_image_info(thumbnail.image_path)
                    if width > 0 and height > 0:
                        size_text = f"{width}x{height}"
                        wrapped_lines.append(size_text)
            except (OSError, ValueError, AttributeError):
                pass  # Skip size if we can't get it

        if not wrapped_lines:
            return  # Nothing to draw
        
        line_height = font_metrics.height()
        total_height = len(wrapped_lines) * line_height
        # Use full thumbnail width for the box (minus margins)
        box_width = available_width  # Use full available width
        box_left = rect.center().x() - box_width // 2
        # Draw BELOW the image rect instead of on top
        overlay_spacing = 4  # Space between image and overlay
        box_top = rect.bottom() + overlay_spacing
        box_rect = QRect(box_left, box_top, box_width, total_height + 4)  # 2px margin top/bottom inside box

        # Draw black box WITHOUT border
        painter.setRenderHint(QPainter.Antialiasing, True)
        
        # Draw the filled box (no border)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(box_color))
        painter.drawRect(box_rect)

        # Store the overlay rect for click detection
        thumbnail.filename_overlay_rect = box_rect
        
        # Draw each line of text, centered in the box
        for i, line in enumerate(wrapped_lines):
            if line:  # Only draw non-empty lines
                line_width = font_metrics.horizontalAdvance(line)
                line_x = box_rect.center().x() - line_width // 2
                line_y = box_rect.top() + 2 + (i * line_height) + font_metrics.ascent()
                painter.setPen(main_color)
                painter.drawText(line_x, line_y, line)
    
    def _wrap_filename_text(self, filename: str, available_width: int, font_metrics) -> List[str]:
        """Wrap filename naturally to fit available width (no eliding, can wrap to multiple lines)"""
        # Handle explicit newlines first - split on \n and wrap each part separately
        if '\n' in filename:
            all_lines = []
            parts = filename.split('\n')
            for part in parts:
                wrapped = self._wrap_filename_text(part, available_width, font_metrics)
                all_lines.extend(wrapped)
            return all_lines
        
        # If the whole filename fits, return it as a single line
        if font_metrics.horizontalAdvance(filename) <= available_width:
            return [filename]
        
        # Split filename into name and extension
        name, ext = os.path.splitext(filename)
        
        lines = []
        current_line = ""
        
        # Try to wrap the name part naturally
        # Look for word boundaries (spaces, underscores, hyphens, dots)
        words = []
        current_word = ""
        
        for char in name:
            if char in [' ', '_', '-', '.']:
                if current_word:
                    words.append(current_word)
                    current_word = ""
                words.append(char)  # Keep separators as separate "words"
            else:
                current_word += char
        
        if current_word:
            words.append(current_word)
        
        # Build lines by adding words until they don't fit
        for word in words:
            test_line = current_line + word
            if font_metrics.horizontalAdvance(test_line) <= available_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    # Single word is too long, need to break it character by character
                    for char in word:
                        test_char_line = current_line + char
                        if font_metrics.horizontalAdvance(test_char_line) <= available_width:
                            current_line = test_char_line
                        else:
                            if current_line:
                                lines.append(current_line)
                            current_line = char
        
        if current_line:
            lines.append(current_line)
        
        # Add extension to the last line if it fits, otherwise on a new line
        if ext:
            if lines:
                last_line_with_ext = lines[-1] + ext
                if font_metrics.horizontalAdvance(last_line_with_ext) <= available_width:
                    lines[-1] = last_line_with_ext
                else:
                    lines.append(ext)
            else:
                lines.append(ext)
        
        return lines
    
    def _get_thumbnail_at_position(self, pos: QPoint) -> Optional[int]:
        """Get the thumbnail index at the given position (including overlay area)"""
        with QMutexLocker(self.mutex):
            for thumbnail in self.thumbnails:
                if thumbnail.rect:
                    # Calculate overlay height for this specific thumbnail
                    overlay_height = self._get_overlay_height_for_thumbnail(thumbnail, thumbnail.rect.width())
                    # Include overlay area in hit testing
                    extended_rect = QRect(
                        thumbnail.rect.x(),
                        thumbnail.rect.y(),
                        thumbnail.rect.width(),
                        thumbnail.rect.height() + overlay_height
                    )
                    if extended_rect.contains(pos):
                        return thumbnail.index
        return None
    
    def _get_filename_overlay_at_position(self, pos: QPoint) -> Optional[int]:
        """Get the thumbnail index if position is within filename overlay"""
        if not self._filename_overlay_visible:
            return None
        with QMutexLocker(self.mutex):
            for thumbnail in self.thumbnails:
                if (thumbnail.filename_overlay_rect and 
                    thumbnail.filename_overlay_rect.contains(pos)):
                    return thumbnail.index
        return None
    
    def _get_separator_at_position(self, pos: QPoint) -> Optional[SectionSeparatorItem]:
        """Get the section separator at the given position"""
        if not hasattr(self, 'section_separators') or not self.section_separators:
            return None
        with QMutexLocker(self.mutex):
            for separator in self.section_separators:
                if separator.rect and separator.rect.contains(pos):
                    return separator
        return None
    
    def collapse_all_sections(self, scroll_to_top=False):
        """Collapse all EXIF date sections"""
        if not hasattr(self, 'section_separators') or not self.section_separators:
            return
        if not hasattr(self.main_window, 'exif_section_expanded'):
            self.main_window.exif_section_expanded = {}
        with QMutexLocker(self.mutex):
            for separator in self.section_separators:
                separator.is_expanded = False
                self.main_window.exif_section_expanded[separator.month_key] = False
        self._update_thumbnail_rectangles()
        self._update_canvas_size()
        self.update()
        if scroll_to_top:
            self._scroll_to_top()
        else:
            self._ensure_something_visible()
    
    def expand_all_sections(self):
        """Expand all EXIF date sections"""
        if not hasattr(self, 'section_separators') or not self.section_separators:
            return
        if not hasattr(self.main_window, 'exif_section_expanded'):
            self.main_window.exif_section_expanded = {}
        with QMutexLocker(self.mutex):
            for separator in self.section_separators:
                separator.is_expanded = True
                self.main_window.exif_section_expanded[separator.month_key] = True
        self._update_thumbnail_rectangles()
        self._update_canvas_size()
        self.update()
    
    def _validate_macos_filename(self, name: str) -> Tuple[bool, str]:
        """Validate macOS filename - returns (is_valid, error_message)"""
        if not name or not name.strip():
            return False, "Filename cannot be empty"
        
        # macOS invalid characters: / : (forward slash and colon)
        invalid_chars = ['/', ':']
        for char in invalid_chars:
            if char in name:
                return False, f"Filename cannot contain '{char}'"
        
        # Check for control characters (0x00-0x1F except tab/newline)
        for char in name:
            code = ord(char)
            if code < 0x20 and code not in [0x09, 0x0A]:  # Allow tab and newline
                return False, "Filename contains invalid control characters"
        
        # # Check for reserved names (case-insensitive)
        # reserved_names = ['CON', 'PRN', 'AUX', 'NUL', 
        #                  'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        #                  'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']
        # if name.upper() in reserved_names:
        #     return False, f"'{name}' is a reserved name"
        
        return True, ""
    
    def _start_inline_rename(self, thumbnail_index: int):
        """Start inline rename editing for a thumbnail"""
        if thumbnail_index < 0 or thumbnail_index >= len(self.thumbnails):
            return
        
        thumbnail = self.thumbnails[thumbnail_index]
        # Ensure filename overlay is visible before starting rename (needed for F2 and for overlay_rect)
        if not self._filename_overlay_visible:
            # Scroll thumbnail into view first so it gets painted (and overlay_rect gets set)
            if hasattr(self.main_window, 'mvc_controller'):
                self.main_window.mvc_controller.set_current_index(thumbnail_index)
            if hasattr(self.main_window, 'ensure_highlighted_visible'):
                self.main_window.ensure_highlighted_visible()
            self.set_filename_overlay_visible(True)
            if hasattr(self.main_window, 'thumbnail_filename_visible'):
                self.main_window.thumbnail_filename_visible = True
            self.update()
            QTimer.singleShot(50, lambda idx=thumbnail_index: self._start_inline_rename(idx))
            return
        if not thumbnail.filename_overlay_rect:
            return
        
        # Cancel any existing editor (don't restore focus - we're about to show new editor)
        self._cancel_inline_rename(restore_focus=False)
        
        # Make this thumbnail the active/highlighted image before starting rename
        if hasattr(self.main_window, 'mvc_controller'):
            self.main_window.mvc_controller.set_current_index(thumbnail_index)
            self.main_window.mvc_controller.set_current_image_path(thumbnail.image_path)
        if hasattr(self.main_window, 'highlight_image'):
            self.main_window.highlight_image()
        if hasattr(self.main_window, 'ensure_highlighted_visible'):
            # Ensure the thumbnail is visible (scroll if needed)
            QTimer.singleShot(50, self.main_window.ensure_highlighted_visible)
        
        # Get current filename without extension
        filename = _path_basename(thumbnail.image_path)
        basename = _path_basename_no_ext(thumbnail.image_path)
        
        # Create inline editor
        self._rename_editor = QLineEdit(self)
        self._rename_editor.setText(basename)
        self._rename_editor.selectAll()
        
        # Position editor over filename overlay
        overlay_rect = thumbnail.filename_overlay_rect
        self._rename_editor.setGeometry(overlay_rect)
        
        # Style with skyblue border
        _ov = tc.THUMBNAIL_FILENAME_OVERLAY_BOX_COLOR
        self._rename_editor.setStyleSheet(f"""
            QLineEdit {{
                border: 2px solid #87CEEB;
                border-radius: 0px;
                background-color: rgba({_ov.red()}, {_ov.green()}, {_ov.blue()}, {_ov.alpha()});
                color: {tc.TEXT_COLOR_HEX};
                font-family: Arial;
                font-size: 13px;
                padding: 2px;
            }}
        """)
        
        # Connect signals
        self._rename_editor.editingFinished.connect(self._finish_inline_rename)
        self._rename_editor.textChanged.connect(self._validate_rename_text)
        self._rename_editor.installEventFilter(self)
        
        # Store editing state
        self._editing_thumbnail_index = thumbnail_index
        self._rename_canceled = False  # Reset canceled flag when starting new rename
        
        # Show and focus editor
        self._rename_editor.show()
        self._rename_editor.setFocus()
    
    def _cancel_inline_rename(self, restore_focus: bool = True):
        """Cancel inline rename editing"""
        # Set canceled flag to prevent _finish_inline_rename from executing
        self._rename_canceled = True
        
        if self._rename_editor is not None:
            try:
                # Disconnect signals with specific slots to avoid warnings
                # Only disconnect if actually connected
                try:
                    self._rename_editor.editingFinished.disconnect(self._finish_inline_rename)
                except (TypeError, RuntimeError):
                    pass  # Signal not connected or already disconnected
                try:
                    self._rename_editor.textChanged.disconnect(self._validate_rename_text)
                except (TypeError, RuntimeError):
                    pass  # Signal not connected or already disconnected
                # Remove event filter before deleting
                self._rename_editor.removeEventFilter(self)
                self._rename_editor.hide()
                self._rename_editor.deleteLater()
            except (AttributeError, RuntimeError, TypeError):
                pass  # Editor may already be deleted
            finally:
                self._rename_editor = None
        self._editing_thumbnail_index = None

        # Restore focus to canvas area (prevents focus jumping to tree when editor is removed)
        if restore_focus and self.main_window and hasattr(self.main_window, 'focus_canvas'):
            QTimer.singleShot(0, self.main_window.focus_canvas)
    
    def _validate_rename_text(self, text: str):
        """Validate rename text and update border color"""
        if not self._rename_editor:
            return
        
        is_valid, _ = self._validate_macos_filename(text)
        
        _ov = tc.THUMBNAIL_FILENAME_OVERLAY_BOX_COLOR
        if is_valid:
            # Skyblue border for valid
            self._rename_editor.setStyleSheet(f"""
                QLineEdit {{
                    border: 2px solid #87CEEB;
                    border-radius: 0px;
                    background-color: rgba({_ov.red()}, {_ov.green()}, {_ov.blue()}, {_ov.alpha()});
                    color: {tc.TEXT_COLOR_HEX};
                    font-family: Arial;
                    font-size: 13px;
                    padding: 2px;
                }}
            """)
        else:
            # Red border for invalid
            self._rename_editor.setStyleSheet(f"""
                QLineEdit {{
                    border: 2px solid #FF0000;
                    border-radius: 0px;
                    background-color: rgba({_ov.red()}, {_ov.green()}, {_ov.blue()}, {_ov.alpha()});
                    color: {tc.TEXT_COLOR_HEX};
                    font-family: Arial;
                    font-size: 13px;
                    padding: 2px;
                }}
            """)
    
    def _finish_inline_rename(self):
        """Finish inline rename and perform the rename operation"""
        # If rename was canceled, don't perform the rename
        if self._rename_canceled:
            self._rename_canceled = False
            # Still clean up the editor
            if self._rename_editor:
                try:
                    self._rename_editor.removeEventFilter(self)
                    self._rename_editor.hide()
                    self._rename_editor.deleteLater()
                except (AttributeError, RuntimeError):
                    pass
                finally:
                    self._rename_editor = None
            self._editing_thumbnail_index = None
            return
        
        if not self._rename_editor or self._editing_thumbnail_index is None:
            # Editor already cleaned up or not initialized - just ensure cleanup
            if self._rename_editor:
                try:
                    self._rename_editor.removeEventFilter(self)
                    self._rename_editor.hide()
                    self._rename_editor.deleteLater()
                except (AttributeError, RuntimeError):
                    pass
                finally:
                    self._rename_editor = None
            self._editing_thumbnail_index = None
            return
        
        thumbnail_index = self._editing_thumbnail_index
        if thumbnail_index < 0 or thumbnail_index >= len(self.thumbnails):
            self._cancel_inline_rename()
            return
        
        thumbnail = self.thumbnails[thumbnail_index]
        new_name = self._rename_editor.text().strip()
        
        # Validate filename
        is_valid, error_msg = self._validate_macos_filename(new_name)
        if not is_valid:
            # Keep editor open and show error in status bar
            self._show_rename_error(error_msg)
            # Keep editor focused so user can continue editing
            if self._rename_editor:
                self._rename_editor.setFocus()
                # Select all text to make it easy to retype
                self._rename_editor.selectAll()
            return
        
        # Get original path and extension
        original_path = thumbnail.image_path
        directory = _path_dirname(original_path)
        base = _path_basename(original_path)
        dot = base.rfind('.')
        extension = base[dot:] if dot > 0 else ''
        
        # Prevent rename operations within Photos Libraries
        from utils import is_inside_photos_library, show_styled_warning
        if is_inside_photos_library(original_path):
            self._cancel_inline_rename()
            show_styled_warning(
                self.main_window,
                "Operation Not Allowed",
                "Renaming files within macOS Photos Library is not allowed.\n\n"
                "Photos Library files cannot be renamed or modified."
            )
            return
        
        # Construct new path
        new_filename = new_name + extension
        new_path = f"{directory}/{new_filename}" if directory else new_filename
        
        # Check if the name hasn't changed - if so, treat like Escape (cancel)
        original_basename = _path_basename_no_ext(original_path)
        if new_name == original_basename:
            # Name unchanged - cancel rename (same as Escape)
            self._cancel_inline_rename()
            return
        
        # Check if file already exists (and it's not the same file)
        if os.path.exists(new_path) and new_path != original_path:
            self._show_rename_error(f"File '{new_filename}' already exists")
            # Keep editor open and focused so user can continue editing
            if self._rename_editor:
                self._rename_editor.setFocus()
                # Select all text to make it easy to retype
                self._rename_editor.selectAll()
            return
        
        # Perform rename
        try:
            os.rename(original_path, new_path)
            
            # Preserve lock status after rename - update .prsort file with new filename
            if (hasattr(self.main_window, 'lock_manager') and self.main_window.lock_manager and
                hasattr(self.main_window, 'sorting_manager') and self.main_window.sorting_manager):
                try:
                    # Check if the file is locked
                    old_basename = _path_basename(original_path)
                    new_basename = _path_basename(new_path)
                    locked_files = self.main_window.lock_manager.get_locked_files(directory)
                    
                    if old_basename in locked_files:
                        # File is locked - update .prsort file
                        prsort_result = self.main_window.sorting_manager._read_prsort_file(directory)
                        if prsort_result:
                            prsort_filenames, is_reversed, locked_files_set = prsort_result
                            
                            # Update the filename in the list while preserving order
                            updated_filenames = []
                            for filename in prsort_filenames:
                                if filename == old_basename:
                                    # Replace old filename with new filename
                                    updated_filenames.append(new_basename)
                                else:
                                    updated_filenames.append(filename)
                            
                            # Update locked_files_set
                            if old_basename in locked_files_set:
                                locked_files_set.remove(old_basename)
                                locked_files_set.add(new_basename)
                            
                            # Write updated .prsort file
                            prsort_path = f"{directory}/.prsort" if directory else ".prsort"
                            try:
                                with open(prsort_path, 'w', encoding='utf-8') as f:
                                    # Write header comments
                                    f.write('# THIS FILE IS ONLY FOR CUSTOM SORT ORDERING AND FILE LOCKING\n')
                                    f.write('# DO NOT USE .prsort TO ORDER UNLOCKED FILES\n')
                                    # Write reversed flag header
                                    f.write(f'#reversed:{str(is_reversed).lower()}\n')
                                    # Write filenames with lock prefix if locked
                                    for filename in updated_filenames:
                                        if filename in locked_files_set:
                                            f.write(f'*{filename}\n')
                                        else:
                                            f.write(f'{filename}\n')
                                
                                # Force file system sync to ensure .prsort file is written to disk
                                time.sleep(0.05)  # Small delay to ensure file is written
                            except Exception as e:
                                print(f"WARNING: Failed to write .prsort file with lock status after rename: {e}")
                except Exception as e:
                    print(f"WARNING: Failed to update .prsort file after rename: {e}")
            
            # Update thumbnail path
            thumbnail.image_path = new_path
            
            # Invalidate cache for both old and new paths
            if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
                self.main_window.cache_manager.clear_cache_for_file(original_path)
                self.main_window.cache_manager.clear_cache_for_file(new_path)
            
            # Store the new path to track after refresh
            renamed_path = new_path
            
            # Store renamed path on main_window so refresh can use it to set correct highlight_index
            self.main_window.pending_rename_path = renamed_path
            # Store old path for updating selected_files
            self.main_window.pending_rename_old_path = original_path
            
            # Update rename status checkmark for this directory (without rebuilding tree)
            directory = _path_dirname(new_path)
            if hasattr(self.main_window, 'update_rename_status_for_directory'):
                self.main_window.update_rename_status_for_directory(directory)
            
            # Refresh directory display
            if hasattr(self.main_window, 'debounce_refresh_directory'):
                self.main_window.debounce_refresh_directory()
            
            # Clean up editor (without cancel flag since rename succeeded)
            if self._rename_editor is not None:
                try:
                    self._rename_editor.removeEventFilter(self)
                    self._rename_editor.hide()
                    self._rename_editor.deleteLater()
                except (AttributeError, RuntimeError):
                    pass
                finally:
                    self._rename_editor = None
            self._editing_thumbnail_index = None
            self._rename_canceled = False
            
            # Update display
            self.needs_repaint = True
            self.update()
            
            # Ensure focus stays on canvas after rename (not tree view)
            if hasattr(self.main_window, 'focus_canvas'):
                QTimer.singleShot(50, self.main_window.focus_canvas)
            
            # After refresh completes, verify the renamed file is highlighted correctly
            # This serves as a backup in case the refresh didn't find it (shouldn't happen now)
            def verify_highlight_after_refresh(retry_count=0, max_retries=5):
                # Check if highlight_index already points to the renamed file
                if (hasattr(self.main_window, 'displayed_images') and 
                    hasattr(self.main_window, 'highlight_index') and
                    self.main_window.highlight_index is not None):
                    current_index = self.main_window.highlight_index
                    if (0 <= current_index < len(self.main_window.displayed_images) and
                        self.main_window.displayed_images[current_index] == renamed_path):
                        # Already correctly highlighted, nothing to do
                        return
                
                # Find the renamed file's new index
                if hasattr(self.main_window, 'find_thumbnail_index_by_path'):
                    new_index = self.main_window.find_thumbnail_index_by_path(renamed_path)
                    if new_index is not None:
                        # Update highlight_index to track the renamed file
                        if hasattr(self.main_window, 'mvc_controller'):
                            self.main_window.mvc_controller.set_current_index(new_index)
                            self.main_window.mvc_controller.set_current_image_path(renamed_path)
                        # Update the highlight display
                        if hasattr(self.main_window, 'highlight_image'):
                            self.main_window.highlight_image()
                    elif retry_count < max_retries:
                        # File not found yet, retry after a short delay
                        QTimer.singleShot(100, lambda: verify_highlight_after_refresh(retry_count + 1, max_retries))
            
            # Start checking after initial delay (debounce_refresh_directory has internal delays)
            QTimer.singleShot(300, lambda: verify_highlight_after_refresh())
            
        except Exception as e:
            error_msg = f"Failed to rename: {str(e)}"
            self._show_rename_error(error_msg)
            # Keep editor open and focused so user can continue editing
            if self._rename_editor:
                self._rename_editor.setFocus()
                # Select all text to make it easy to retype
                self._rename_editor.selectAll()
    
    def _show_rename_error(self, message: str):
        """Show rename error in status bar filename area"""
        if hasattr(self.main_window, 'status_bar_manager'):
            filename_widget = self.main_window.status_bar_manager.config.get_widget(
                self.main_window.status_bar_manager.config.SECTION_FILENAME
            )
            if filename_widget:
                filename_widget.setText(message)
        
        # Show status bar if hidden (but don't steal focus from editor)
        if hasattr(self.main_window, 'status_bar'):
            if not self.main_window.status_bar.isVisible():
                self.main_window.status_bar.show()
                # Ensure editor keeps focus after showing status bar
                if self._rename_editor and self._rename_editor.isVisible():
                    QTimer.singleShot(10, lambda: self._rename_editor.setFocus() if self._rename_editor else None)
    
    def eventFilter(self, obj, event):
        """Event filter to handle escape key and prevent event propagation during editing"""
        if obj == self._rename_editor and self._rename_editor is not None:
            if event.type() == QEvent.KeyPress:
                if isinstance(event, QKeyEvent):
                    if event.key() == Qt.Key_Escape:
                        # Cancel rename and prevent QLineEdit from processing Escape
                        event.accept()
                        # Set canceled flag BEFORE cleanup to prevent signal firing
                        self._rename_canceled = True
                        # Cancel and cleanup (this will disconnect signals)
                        self._cancel_inline_rename()
                        return True  # Event handled, don't propagate
                    elif event.key() in [Qt.Key_Return, Qt.Key_Enter]:
                        # Accept the event and prevent it from propagating to parent widgets
                        event.accept()
                        # Manually trigger editingFinished to handle the rename
                        # Use QTimer to ensure it happens after the event is fully processed
                        QTimer.singleShot(0, self._finish_inline_rename)
                        # Return True to prevent the event from reaching QLineEdit's default handler
                        # and from propagating to parent widgets (canvas/main window)
                        # This prevents fullscreen from opening when rename fails
                        return True
                    else:
                        # For all other keys, let QLineEdit handle them normally
                        # Return False so the event reaches QLineEdit
                        return False
        
        return super().eventFilter(obj, event)
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press events"""
        # Check if click is on a filter button
        if event.button() == Qt.LeftButton and self.filter_button_rects:
            for button_rect, filter_pattern in self.filter_button_rects:
                if button_rect.contains(event.pos()):
                    # Button clicked - apply filter
                    self._apply_filter_from_button(filter_pattern)
                    event.accept()
                    return
        
        # Check if click is on a section separator (EXIF date mode)
        if event.button() == Qt.LeftButton:
            separator = self._get_separator_at_position(event.pos())
            if separator:
                # Toggle expand/collapse state
                was_expanded = separator.is_expanded
                separator.is_expanded = not separator.is_expanded
                # Update main window's state dict
                if not hasattr(self.main_window, 'exif_section_expanded'):
                    self.main_window.exif_section_expanded = {}
                self.main_window.exif_section_expanded[separator.month_key] = separator.is_expanded
                # Update layout
                self._update_thumbnail_rectangles()
                self._update_canvas_size()
                self.update()
                # If we collapsed (was expanded, now not), ensure something is visible
                if was_expanded and not separator.is_expanded:
                    self._ensure_something_visible()
                self._separator_click_processed = True  # Mark that separator click was processed
                event.accept()
                return
        
        
        if self._rename_editor and self._rename_editor.isVisible():
            # Check if click is outside the editor
            editor_rect = self._rename_editor.geometry()
            if not editor_rect.contains(event.pos()):
                # Click is outside editor - finish the rename
                # Clear focus from editor to trigger editingFinished
                self._rename_editor.clearFocus()
                # Also explicitly call finish to ensure it happens
                QTimer.singleShot(0, self._finish_inline_rename)
            else:
                # Click is on editor - let editor handle it
                super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            # Check if click is on filename overlay
            overlay_index = self._get_filename_overlay_at_position(event.pos())
            if overlay_index is not None:
                # Start inline rename
                self._start_inline_rename(overlay_index)
                event.accept()
                return
            
            # Only set focus to canvas if tree doesn't have focus
            # This prevents stealing focus from tree during keyboard navigation
            # current_focus = QApplication.focusWidget()
            # tree_has_focus = False
            
            # # Check if tree or tree container has focus
            # if hasattr(self.main_window, 'file_tree_handler'):
            #     tree_handler = self.main_window.file_tree_handler
            #     if hasattr(tree_handler, 'file_tree') and tree_handler.file_tree:
            #         tree_has_focus = (current_focus == tree_handler.file_tree or 
            #                         (hasattr(tree_handler, 'tree_container') and current_focus == tree_handler.tree_container))
            
            # # Only steal focus if tree doesn't have it
            # if not tree_has_focus:
            #     self.setFocus()   
            self.setFocus()
            
            self._drag_start_pos = event.pos()
            self._dragging = False

            # Determine action user intends based on macOS conventions:
            # - Default: MoveAction (macOS will handle same/different volume detection)
            # - Option (Alt): Force CopyAction
            # - Command (Control/Meta): Force MoveAction
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.AltModifier:
                # Option key: force copy
                self._last_drag_intent = Qt.CopyAction
            elif modifiers & (Qt.ControlModifier | Qt.MetaModifier):
                # Command key: force move
                self._last_drag_intent = Qt.MoveAction
            else:
                # Default: MoveAction (macOS will handle volume detection)
                self._last_drag_intent = Qt.MoveAction
            event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release events"""
        # If editing, don't handle mouse events (let editor handle them)
        if self._rename_editor and self._rename_editor.isVisible():
            super().mouseReleaseEvent(event)
            return
        
        # Check if we just processed a separator click - if so, ignore thumbnail clicks
        # to prevent opening images after separator expand/collapse operations
        if event.button() == Qt.LeftButton:
            if self._separator_click_processed:
                # Separator click was just processed, don't process as thumbnail click
                self._separator_click_processed = False  # Clear flag
                self._dragging = False
                self._drag_start_pos = None
                event.accept()
                return
        
        
        if event.button() == Qt.LeftButton:
            if not self._dragging:
                # Delay single-click handling to allow double-click detection
                thumbnail_index = self._get_thumbnail_at_position(event.pos())
                if thumbnail_index is not None:
                    modifiers = QApplication.keyboardModifiers()
                    # On macOS: ControlModifier=Command(⌘) for multiselect, MetaModifier=Control(⌃) for context menu
                    cmd_pressed = bool(modifiers & Qt.ControlModifier)
                    shift_pressed = bool(modifiers & Qt.ShiftModifier)
                    macos_ctrl_pressed = bool(modifiers & Qt.MetaModifier)
                    # Store click data and start timer
                    self._pending_click_data = (thumbnail_index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
                    # Use Qt's double-click interval (typically 400ms) as delay
                    app = QApplication.instance()
                    interval = app.doubleClickInterval() if app else 400
                    # DGN: Change interval to 10ms to allow single click to chg index but then let doubleclick to fire and open browse mode
                    # DGN: THis is OK because if both fire, it is OK (just an extra highlight)
                    interval = 10
                    self._single_click_timer.start(interval)
            
            self._dragging = False
            self._drag_start_pos = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def _handle_delayed_single_click(self):
        """Handle single-click after delay, if double-click didn't occur"""
        # Don't handle clicks if rename editor is visible
        if self._rename_editor and self._rename_editor.isVisible():
            self._pending_click_data = None
            return
        # Don't handle if we're now in browse mode (double-click opened it)
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'browse'):
            self._pending_click_data = None
            return
        if self._pending_click_data is not None:
            thumbnail_index, cmd_pressed, shift_pressed, macos_ctrl_pressed = self._pending_click_data
            self._pending_click_data = None
            self.thumbnail_clicked.emit(thumbnail_index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move events"""
        # Check if mouse is over a filter button
        if self.filter_button_rects:
            hovered_index = -1
            for i, (button_rect, _) in enumerate(self.filter_button_rects):
                if button_rect.contains(event.pos()):
                    hovered_index = i
                    break
            
            if hovered_index != self._hovered_button_index:
                self._hovered_button_index = hovered_index
                self.update()  # Repaint to show hover effect
        
        if self._drag_start_pos is not None:
            if self._is_reference_graph_mode():
                self._drag_start_pos = None
                self._dragging = False
            else:
                # Check if we've moved enough to start dragging
                distance = (event.pos() - self._drag_start_pos).manhattanLength()
                if distance > 5:  # Drag threshold
                    self._dragging = True
                    self._start_internal_drag()
                    return
        
        # Handle hover
        thumbnail_index = self._get_thumbnail_at_position(event.pos())
        if thumbnail_index != self._hovered_index:
            self._hovered_index = thumbnail_index
            if thumbnail_index is not None:
                self.thumbnail_hovered.emit(thumbnail_index)
        
        super().mouseMoveEvent(event)
    
    def contextMenuEvent(self, event: QContextMenuEvent):
        """Handle right-click / Control+click (macOS) - show context menu only for Ctrl, not Cmd.
        Cmd+click (ControlModifier) = multiselect; Ctrl+click (MetaModifier) or right-click = context menu."""
        # On macOS: ControlModifier=Cmd - do NOT show context menu (reserved for multiselect)
        if event.modifiers() & Qt.ControlModifier:
            event.accept()
            return
        thumbnail_index = self._get_thumbnail_at_position(event.pos())
        if thumbnail_index is not None:
            # Right-click or Ctrl+click - request context menu (macos_ctrl_pressed=True)
            self.thumbnail_clicked.emit(thumbnail_index, False, False, True)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double click events - open browse when preview is showing"""
        if event.button() == Qt.LeftButton:
            # Cancel pending single-click to prevent it from firing
            self._single_click_timer.stop()
            self._pending_click_data = None
            
            thumbnail_index = self._get_thumbnail_at_position(event.pos())
            if thumbnail_index is not None:
                self.thumbnail_double_clicked.emit(thumbnail_index)
            # Accept the event to prevent further processing
            event.accept()
            return  # Explicitly return to prevent any further event handling
        else:
            super().mouseDoubleClickEvent(event)
    
    def wheelEvent(self, event: QWheelEvent):
        """Handle wheel events for scrolling"""
        # Forward wheel events to parent scroll area
        super().wheelEvent(event)
    
    def keyPressEvent(self, event):
        """Handle key press events"""
        # If editing, don't forward key events (let editor handle them)
        if self._rename_editor and self._rename_editor.isVisible():
            # Accept and ignore key events when editor is visible to prevent propagation
            # The eventFilter on the editor will handle them
            event.accept()
            return

        # Handle F2: initiate rename for highlighted thumbnail (simulate click on filename)
        if event.key() == Qt.Key_F2 and not event.modifiers():
            index = None
            if hasattr(self.main_window, 'highlight_index') and self.main_window.highlight_index is not None:
                index = self.main_window.highlight_index
            elif 0 <= self.highlighted_index < len(self.thumbnails):
                index = self.highlighted_index
            if index is not None and 0 <= index < len(self.thumbnails):
                self._start_inline_rename(index)
            event.accept()
            return

        # Forward key events to main window for navigation
        if hasattr(self.main_window, 'keyPressEvent'):
            self.main_window.keyPressEvent(event)
        else:
            super().keyPressEvent(event)
    
    def focusInEvent(self, event):
        """Handle focus in events"""
        super().focusInEvent(event)
        # Don't steal focus from the container - let Qt handle tab navigation
    
    def keyReleaseEvent(self, event):
        """Handle key release events"""
        # If editing, don't forward key events (let editor handle them)
        if self._rename_editor and self._rename_editor.isVisible():
            super().keyReleaseEvent(event)
            return
        
        # Forward key events to main window for navigation
        if hasattr(self.main_window, 'keyReleaseEvent'):
            self.main_window.keyReleaseEvent(event)
        else:
            super().keyReleaseEvent(event)
    
    # Drag and drop support
    @entry_debug_wrapper
    def dragEnterEvent(self, event: QDragEnterEvent):
        """Handle drag enter events"""
        logger = get_drag_drop_logger()
        logger.debug("dragEnterEvent called")
        logger.debug(f"MIME types: {[format for format in event.mimeData().formats()]}")
        logger.debug(f"has URLs: {event.mimeData().hasUrls()}")
        # Accept drag if it contains URLs (standard MIME type for files)
        if event.mimeData().hasUrls():
            logger.info("Drag detected (internal or external) with URLs - accepting drag")
            event.setDropAction(Qt.MoveAction)
            event.accept()
        else:
            logger.warning("Unknown drag type - ignoring")
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent):
        """Handle drag move events"""
        logger = get_drag_drop_logger()
        logger.debug("dragMoveEvent called")
        if event.mimeData().hasUrls():
            logger.info("Drag move detected with URLs")
            pos = event.pos()
            insertion_index, indicator_x = self._calculate_insertion_info(pos)

            if insertion_index is not None:
                self._current_insertion_index = insertion_index
                self._indicator_x = indicator_x
                self._show_drop_indicator = True
                self.update()
                # For internal reordering, MoveAction is appropriate
                # But we should still respect the proposed action for external compatibility
                # Internal reordering always uses MoveAction since files stay in same directory
                event.setDropAction(Qt.MoveAction)
                event.accept()
            else:
                self._show_drop_indicator = False
                self.update()
                event.ignore()
            
            # Check if we need to auto-scroll based on cursor position
            self._update_auto_scroll(pos)
        else:
            event.ignore()
            self._stop_auto_scroll()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        """Handle drag leave events"""
        self._show_drop_indicator = False
        self._current_insertion_index = None
        self._stop_auto_scroll()
        self.update()
        event.accept()

    def dropEvent(self, event: QDropEvent):
        """Handle drop events"""
        if self._is_reference_graph_mode():
            event.ignore()
            return
        self._show_drop_indicator = False
        self._stop_auto_scroll()
        self.update()

        if event.mimeData().hasUrls():
            # In both internal and external drops, we use URLs
            insertion_index = self._current_insertion_index
            if insertion_index is None:
                event.ignore()
                return

            # Clear the insertion index after we've captured it
            self._current_insertion_index = None

            # Lazily create drag_drop_manager if the window hasn't attached it yet
            if not hasattr(self.main_window, 'drag_drop_manager'):
                self.main_window.drag_drop_manager = DragDropManager(self.main_window)

            # Determine if this is an internal move: all URLs are files already in our list
            urls = event.mimeData().urls()
            image_paths = [url.toLocalFile() for url in urls if url.isLocalFile()]

            # Internal drag/drop reordering only if all files are inside our current image set
            known_paths = set(thumb.image_path for thumb in self.thumbnails)
            all_internal = all(path in known_paths for path in image_paths)

            if all_internal:
                # Internal reordering - mark as handled internally so we don't clear selections
                self._internal_drop_handled = True
                handler = getattr(self.main_window, 'drag_drop_manager', None)
                if handler:
                    if len(image_paths) > 1:
                        success = handler.handle_multiple_thumbnail_reorder(image_paths, insertion_index)
                    elif len(image_paths) == 1:
                        success = handler.handle_thumbnail_reorder(image_paths[0], insertion_index)
                    else:
                        success = False

                    if success:
                        event.acceptProposedAction()
                    else:
                        event.ignore()
                else:
                    event.ignore()
            else:
                # External drop: pass-through (e.g., for move to trash or copy elsewhere)
                self._internal_drop_handled = False
                event.acceptProposedAction()
        else:
            event.ignore()
    
    def _update_auto_scroll(self, pos: QPoint):
        """Update auto-scroll state based on cursor position during drag"""
        # Find the scroll area
        scroll_area = self._get_scroll_area()
        if not scroll_area:
            self._stop_auto_scroll()
            return
        
        viewport = scroll_area.viewport()
        viewport_height = viewport.height()
        viewport_width = viewport.width()
        
        # Get global position and convert to viewport coordinates
        # pos is relative to canvas, so we need to convert to viewport coordinates
        # First, convert canvas position to global coordinates
        global_pos = self.mapToGlobal(pos)
        # Then convert global to viewport coordinates
        viewport_pos = viewport.mapFromGlobal(global_pos)
        y_in_viewport = viewport_pos.y()
        x_in_viewport = viewport_pos.x()
        
        # Only auto-scroll if cursor is within viewport bounds
        if x_in_viewport < 0 or x_in_viewport > viewport_width or y_in_viewport < 0 or y_in_viewport > viewport_height:
            self._stop_auto_scroll()
            return
        
        # Calculate distance from top and bottom edges
        distance_from_top = y_in_viewport
        distance_from_bottom = viewport_height - y_in_viewport
        
        # Determine which edge is closer and calculate scroll speed
        scroll_direction = 0
        scroll_speed = 0.0
        
        if distance_from_top < distance_from_bottom:
            # Near top edge - scroll up
            if distance_from_top < DRAG_AUTO_SCROLL_SPEEDS[0][0]:  # Check if within max distance
                scroll_direction = -1
                scroll_speed = self._calculate_scroll_speed(distance_from_top)
        else:
            # Near bottom edge - scroll down
            if distance_from_bottom < DRAG_AUTO_SCROLL_SPEEDS[0][0]:  # Check if within max distance
                scroll_direction = 1
                scroll_speed = self._calculate_scroll_speed(distance_from_bottom)
        
        # Update auto-scroll state
        if scroll_direction != 0 and scroll_speed > 0:
            if self._auto_scroll_direction != scroll_direction or self._auto_scroll_speed != scroll_speed:
                self._auto_scroll_direction = scroll_direction
                self._auto_scroll_speed = scroll_speed
                # Start timer if not already running (update interval ~16ms for ~60fps)
                if not self._auto_scroll_timer.isActive():
                    self._auto_scroll_timer.start(16)
        else:
            self._stop_auto_scroll()
    
    def _calculate_scroll_speed(self, distance_from_edge: float) -> float:
        """Calculate scroll speed based on distance from edge using interpolation"""
        if not DRAG_AUTO_SCROLL_SPEEDS:
            return 0.0
        
        # Find the two closest entries for interpolation
        # DRAG_AUTO_SCROLL_SPEEDS is ordered from largest distance to smallest
        for i in range(len(DRAG_AUTO_SCROLL_SPEEDS)):
            dist, speed = DRAG_AUTO_SCROLL_SPEEDS[i]
            if distance_from_edge >= dist:
                # We're between this entry and the previous one (or at the edge)
                if i == 0:
                    # At or beyond the maximum distance - use first speed
                    return speed
                else:
                    # Interpolate between this entry and the previous one
                    prev_dist, prev_speed = DRAG_AUTO_SCROLL_SPEEDS[i - 1]
                    if prev_dist == dist:
                        return speed
                    # Linear interpolation
                    ratio = (distance_from_edge - dist) / (prev_dist - dist)
                    return speed + ratio * (prev_speed - speed)
        
        # Closer than the smallest distance - use maximum speed
        return DRAG_AUTO_SCROLL_SPEEDS[-1][1]
    
    def _handle_auto_scroll(self):
        """Handle auto-scroll timer callback - performs smooth scrolling"""
        if self._auto_scroll_direction == 0 or self._auto_scroll_speed == 0:
            self._stop_auto_scroll()
            return
        
        scroll_area = self._get_scroll_area()
        if not scroll_area:
            self._stop_auto_scroll()
            return
        
        scroll_bar = scroll_area.verticalScrollBar()
        viewport = scroll_area.viewport()
        viewport_height = viewport.height()
        
        # Check if we've reached the top or bottom
        current_value = scroll_bar.value()
        max_value = scroll_bar.maximum()
        
        if self._auto_scroll_direction < 0 and current_value <= 0:
            # Scrolling up but already at top
            self._stop_auto_scroll()
            return
        elif self._auto_scroll_direction > 0 and current_value >= max_value:
            # Scrolling down but already at bottom
            self._stop_auto_scroll()
            return
        
        # Calculate scroll amount: speed is percentage of viewport height per second
        # Timer runs at ~16ms intervals, so we scroll (speed * viewport_height / 100) * (16/1000) pixels
        scroll_amount = (self._auto_scroll_speed * viewport_height / 100.0) * (16.0 / 1000.0)
        
        # Apply scroll direction
        new_value = current_value + (self._auto_scroll_direction * scroll_amount)
        
        # Clamp to valid range
        new_value = max(0, min(new_value, max_value))
        
        # Use smooth scrolling
        scroll_bar.setValue(int(new_value))
    
    def _stop_auto_scroll(self):
        """Stop auto-scrolling"""
        if self._auto_scroll_timer.isActive():
            self._auto_scroll_timer.stop()
        self._auto_scroll_direction = 0
        self._auto_scroll_speed = 0.0
    
    def _get_scroll_area(self):
        """Get the scroll area parent widget"""
        scroll_area = None
        # Try attribute on self
        if hasattr(self, 'scroll_area'):
            scroll_area = self.scroll_area
        # Try parent hierarchy
        if not scroll_area:
            scroll_area = self.parent()
            while scroll_area and not hasattr(scroll_area, 'verticalScrollBar'):
                scroll_area = scroll_area.parent()
        # Last fallback: use parent's scroll_area if available
        if not scroll_area and hasattr(self, 'parent') and callable(self.parent):
            container = self.parent()
            if hasattr(container, 'scroll_area'):
                scroll_area = container.scroll_area
        return scroll_area if (scroll_area and hasattr(scroll_area, 'verticalScrollBar')) else None

    def _scroll_to_top(self):
        """Scroll the thumbnail canvas to the top"""
        scroll_area = self._get_scroll_area()
        if scroll_area and hasattr(scroll_area, 'verticalScrollBar'):
            scroll_bar = scroll_area.verticalScrollBar()
            scroll_bar.setValue(0)
    
    def _ensure_something_visible(self):
        """Ensure at least one thumbnail or separator is visible in the viewport"""
        scroll_area = self._get_scroll_area()
        if not scroll_area or not hasattr(scroll_area, 'verticalScrollBar'):
            return
        
        scroll_bar = scroll_area.verticalScrollBar()
        viewport = scroll_area.viewport()
        viewport_top = scroll_bar.value()
        viewport_height = viewport.height()
        viewport_bottom = viewport_top + viewport_height
        
        # Check if anything is currently visible
        margin = 5  # Small margin to prevent constant micro-scrolling
        with QMutexLocker(self.mutex):
            # Check thumbnails
            for thumbnail in self.thumbnails:
                if thumbnail.rect:
                    thumb_top = thumbnail.rect.y()
                    thumb_bottom = thumbnail.rect.y() + thumbnail.rect.height()
                    if (thumb_top >= viewport_top - margin and thumb_bottom <= viewport_bottom + margin):
                        return  # Something is visible
            
            # Check separators
            if getattr(self, 'section_separators', None):
                for separator in self.section_separators:
                    if separator.rect:
                        sep_top = separator.rect.y()
                        sep_bottom = separator.rect.y() + separator.rect.height()
                        if (sep_top >= viewport_top - margin and sep_bottom <= viewport_bottom + margin):
                            return  # Something is visible
        
        # Nothing is visible - find the first visible item and scroll to it
        first_visible_y = None
        
        with QMutexLocker(self.mutex):
            # Find first visible thumbnail
            for thumbnail in self.thumbnails:
                if thumbnail.rect:
                    first_visible_y = thumbnail.rect.y()
                    break
            
            # If no thumbnails, find first visible separator
            if first_visible_y is None and getattr(self, 'section_separators', None):
                for separator in self.section_separators:
                    if separator.rect:
                        first_visible_y = separator.rect.y()
                        break
        
        # Scroll to show the first visible item
        if first_visible_y is not None:
            top_margin = CANVAS_TOTAL_TOP_MARGIN
            target_scroll = max(0, first_visible_y - top_margin)
            scroll_bar.setValue(int(target_scroll))
        else:
            # No items at all - scroll to top
            scroll_bar.setValue(0)

    
    def _calculate_insertion_info(self, pos: QPoint) -> Tuple[Optional[int], int]:
        """Calculate insertion index and indicator position for drag and drop"""
        if not self.thumbnails:
            return 0, BASE_MARGIN
        
        # Find the insertion point based on position
        for i, thumbnail in enumerate(self.thumbnails):
            if thumbnail.rect:
                center_x = thumbnail.rect.x() + thumbnail.rect.width() // 2
                
                # If pointer is above this thumbnail's top edge, insert here
                if pos.y() < thumbnail.rect.top():
                    return i, thumbnail.rect.x()
                
                # If pointer is within this row, check horizontal position
                if thumbnail.rect.top() <= pos.y() <= thumbnail.rect.bottom():
                    if pos.x() < center_x:
                        return i, thumbnail.rect.x()
        
        # Insert after the last thumbnail
        if self.thumbnails:
            last_thumbnail = self.thumbnails[-1]
            if last_thumbnail.rect:
                return len(self.thumbnails), last_thumbnail.rect.right() + HORIZONTAL_SPACING
        
        return len(self.thumbnails), BASE_MARGIN
    
    def _start_internal_drag(self):
        """Start internal drag with standard MIME data (URLs) compatible with both internal & external targets.
        
        Default action follows macOS conventions:
        - Default: MoveAction (macOS handles same/different volume detection)
        - Option (Alt): Force CopyAction
        - Command (Control/Meta): Force MoveAction
        
        After successful move, selections are cleared.
        """
        if self._is_reference_graph_mode():
            return
        logger = get_drag_drop_logger()
        logger.info("_start_internal_drag called")

        # Get the thumbnail at the drag start position
        if self._drag_start_pos is None:
            logger.warning("No drag start position")
            return

        thumbnail_index = self._get_thumbnail_at_position(self._drag_start_pos)
        if thumbnail_index is None or thumbnail_index >= len(self.thumbnails):
            logger.warning(f"Invalid thumbnail index: {thumbnail_index}")
            return

        thumbnail = self.thumbnails[thumbnail_index]
        logger.info(f"Found thumbnail at index {thumbnail_index}: {thumbnail.image_path}")

        # Prepare QMimeData (STANDARD)
        mime = QMimeData()

        # Always use standard MIME types for internal and external DnD operations
        selected_files = []
        selected_urls = []
        if thumbnail_index in self.selected_indices and len(self.selected_indices) > 1:
            for idx in self.selected_indices:
                if idx < len(self.thumbnails):
                    file_path = self.thumbnails[idx].image_path
                    selected_files.append(file_path)
                    selected_urls.append(QUrl.fromLocalFile(file_path))
        else:
            selected_files = [thumbnail.image_path]
            selected_urls = [QUrl.fromLocalFile(thumbnail.image_path)]

        # Always set URLs (standard), text and uri-list for full compatibility
        mime.setUrls(selected_urls)
        file_paths_text = '\n'.join(selected_files)
        mime.setText(file_paths_text)
        uri_list = '\n'.join([f"file://{path}" for path in selected_files])
        mime.setData('text/uri-list', uri_list.encode('utf-8'))
        mime.setData('text/plain', file_paths_text.encode('utf-8'))

        # Choose preferred drag action based on shift key at drag start
        drag = QDrag(self)
        drag.setMimeData(mime)

        # Set drag pixmap if available
        if thumbnail.pixmap and not thumbnail.pixmap.isNull():
            drag.setPixmap(thumbnail.pixmap.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            drag.setHotSpot(QPoint(32, 32))

        intent = getattr(self, '_last_drag_intent', Qt.MoveAction)
        
        # Reset internal drop flag before drag
        self._internal_drop_handled = False
        
        # Execute drag allowing both actions so macOS can choose based on volume
        # The order matters: if intent is MoveAction, put it first; if CopyAction, put it first
        # macOS will use MoveAction for same volume, CopyAction for different volume
        # unless modifier keys override (Option=copy, Command=move)
        if intent == Qt.CopyAction:
            # User wants copy - allow both but prefer copy
            result = drag.exec(Qt.CopyAction | Qt.MoveAction)
        else:
            # Default: prefer move, but allow copy for different volumes
            result = drag.exec(Qt.MoveAction | Qt.CopyAction)
        
        # CRITICAL: Don't clear selections here - the file_tree_handler.dropEvent() already handles
        # removing moved files from selections. Clearing here would remove selections for files that
        # weren't even moved. Selections should only be removed for files that were actually moved.
        # This code path is for thumbnail canvas drops, but file_tree_handler handles file tree drops.
        # For thumbnail canvas drops, selections are already handled by the drag/drop handlers.
        
        # CRITICAL: For internal drops, don't refresh immediately - let the drag/drop handler manage it
        # The handler will refresh if needed, and selections are already preserved
        if not self._internal_drop_handled:
            # Only refresh for external drops
            QTimer.singleShot(100, self.main_window.debounce_refresh_directory)

    def paintDropIndicator(self, painter: QPainter):
        """Paint the drop indicator during drag operations"""
        if not self._show_drop_indicator or self._current_insertion_index is None:
            return
        
        # Draw a blue vertical line at the insertion point
        painter.setPen(QPen(QColor(40, 120, 250, 220), 1))
        
        # Calculate the vertical span
        if self.thumbnails and self._current_insertion_index < len(self.thumbnails):
            ref_thumbnail = self.thumbnails[self._current_insertion_index]
            if ref_thumbnail.rect:
                y = ref_thumbnail.rect.top()
                height = ref_thumbnail.rect.height()
            else:
                y = 10
                height = self.height() - 20
        else:
            y = 10
            height = self.height() - 20
        
        painter.drawLine(self._indicator_x - 2, y, self._indicator_x - 2, y + height)
    
    def get_thumbnail_rect(self, index: int) -> Optional[QRect]:
        """Get the rectangle for a specific thumbnail index"""
        if 0 <= index < len(self.thumbnails):
            rect = self.thumbnails[index].rect
            return rect
        return None
    
    def get_visible_thumbnail_indices(self) -> List[int]:
        """Get indices of thumbnails currently visible in the viewport"""
        visible_indices = []
        with QMutexLocker(self.mutex):
            for thumbnail in self.thumbnails:
                if thumbnail.rect and self._visible_rect.intersects(thumbnail.rect):
                    visible_indices.append(thumbnail.index)
        return visible_indices
    
    def clear_thumbnails(self):
        """Clear all thumbnails"""
        # Cancel any active rename editor
        self._cancel_inline_rename()
        
        with QMutexLocker(self.mutex):
            self.thumbnails.clear()
            self.highlighted_index = -1
            # CRITICAL: Don't clear selected_indices - it's just visual state
            # It will be restored by update_canvas_selection() after thumbnails are regenerated
            # Clearing it here causes selections to disappear during refresh
            # self.selected_indices.clear()  # REMOVED - preserve selection state
            self.needs_repaint = True
            self.update()
    
    def invalidate_thumbnails(self):
        """Invalidate all loaded thumbnails to force reload (e.g., when EXIF setting changes)"""
        with QMutexLocker(self.mutex):
            for thumbnail in self.thumbnails:
                # Clear pixmap and mark as loading to force reload
                thumbnail.pixmap = None
                thumbnail.is_loading = True
            self.needs_repaint = True
            self.update()
    
    def invalidate_thumbnails_for_paths(self, paths: List[str]):
        """Invalidate thumbnails for specific file paths to force reload"""
        with QMutexLocker(self.mutex):
            paths_set = set(paths)
            for thumbnail in self.thumbnails:
                if thumbnail.image_path in paths_set:
                    # Clear pixmap and mark as loading to force reload
                    thumbnail.pixmap = None
                    thumbnail.is_loading = True
            self.needs_repaint = True
            self.update()
    
    def force_canvas_size_update(self):
        """Force canvas size update (called when status bar is toggled)"""

        if self.thumbnails:
            self._update_canvas_size()
            self.needs_repaint = True
            self.update()
        else:
            # Even with no thumbnails, repaint to re-center the message when viewport changes
            self.needs_repaint = True
            self.update()