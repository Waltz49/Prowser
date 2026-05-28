# Standard library imports
import os
import time
from typing import List

# PySide6 imports
from PySide6.QtWidgets import QMessageBox
from utils import show_styled_warning, is_inside_photos_library

# External editor may be monitoring a file - notify when we change mtime so it doesn't restore
try:
    from external_editor import notify_mtime_changed_by_app
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
                from image_browser_window import SortMode
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
                from image_browser_window import SortMode
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
                from image_browser_window import SortMode
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
            from image_browser_window import SortMode
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
                from image_browser_window import SortMode
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
                from image_browser_window import SortMode
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
                from image_browser_window import SortMode
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