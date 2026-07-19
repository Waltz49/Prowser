#!/usr/bin/env python3
"""
Sorting Manager
Handles all sorting operations and custom sort file management
"""

import os
import fnmatch
import random
from typing import List, Optional, Set, Tuple
from PySide6.QtCore import QTimer

from exif.exif_image_loader import get_image_dimensions_fast_metadata, get_image_dimensions_and_exif_date
from config import ImageBrowserConfig
from sort_mode import SortMode


class SortingManager:
    """Manages sorting and filtering operations"""
    
    def __init__(self, main_window):
        """
        Initialize the sorting manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window

    def _get_sort_metadata(self, image_path: str):
        """Return cached metadata, loading into cache on miss."""
        cache_manager = self.main_window.cache_manager
        metadata = cache_manager.get_metadata_sync(image_path)
        if metadata is None:
            cache_manager._ensure_metadata_exists(image_path)
            metadata = cache_manager.get_metadata_sync(image_path)
        return metadata

    def _get_exif_timestamp_for_sort(self, image_path: str) -> Optional[float]:
        metadata = self._get_sort_metadata(image_path)
        if metadata and metadata.exif_taken_time is not None:
            return metadata.exif_taken_time
        try:
            result = get_image_dimensions_and_exif_date(image_path)
            if result and len(result) >= 2:
                return result[1]
        except Exception:
            pass
        return None

    def _get_dimensions_for_sort(self, image_path: str):
        metadata = self._get_sort_metadata(image_path)
        if metadata and metadata.width > 0 and metadata.height > 0:
            return metadata.width, metadata.height
        dimensions = get_image_dimensions_fast_metadata(image_path)
        if dimensions and len(dimensions) == 2:
            width, height = dimensions
            if width > 0 and height > 0:
                return width, height
        return None

    def get_sort_key(self, path):
        """Get sort key for file sorting - consolidated from multiple duplicate functions"""
        try:
            metadata = self.main_window.cache_manager.get_metadata_sync(path)
            if metadata:
                return metadata.modified_time
            if not self.main_window.cache_manager.is_in_app_cache_directory(path):
                return os.stat(path).st_mtime
            return 0
        except Exception:
            return 0
    
    def get_current_sort_mode(self) -> SortMode:
        """Get the current sorting mode."""
        return getattr(self.main_window, '_current_sort_mode', SortMode.DATE)
    
    def set_current_sort_mode(self, mode: SortMode):
        """Set the current sorting mode."""
        self.main_window._current_sort_mode = mode
    
    @property
    def current_sort_mode(self) -> SortMode:
        """Property for current sort mode"""
        return self.get_current_sort_mode()
    
    @current_sort_mode.setter
    def current_sort_mode(self, mode: SortMode):
        """Property setter for current sort mode"""
        self.set_current_sort_mode(mode)
    
    @property
    def sort_direction_reversed(self) -> bool:
        """Whether the current sort direction is reversed."""
        return getattr(self.main_window, 'is_reversed', False)
    
    def save_sorting_settings(self):
        """Save current sorting scheme settings to config"""
        # Convert DUPLICATES to NAME before saving (duplicates mode should not be persisted)
        sort_mode_to_save = self.main_window.current_sort_mode
        if sort_mode_to_save == SortMode.DUPLICATES:
            sort_mode_to_save = SortMode.NAME
        self.main_window.config.update_setting('sort_mode', sort_mode_to_save.value)
        self.main_window.config.update_setting('sort_reversed', self.main_window.is_reversed)
    
    def set_sort_mode(self, mode: SortMode, toggle_reverse: bool = False):
        """Unified method to set sorting mode."""
        # CRITICAL: Preserve current image path BEFORE any mode changes
        # This ensures it's available even if get_current_image_path() fails later
        current_image_path = self.main_window.get_current_image_path()
        # Fallback: get from highlight_index if current_image_path is None
        if not current_image_path:
            displayed = self.main_window.get_displayed_images()
            if displayed and hasattr(self.main_window, 'highlight_index'):
                if 0 <= self.main_window.highlight_index < len(displayed):
                    current_image_path = displayed[self.main_window.highlight_index]
        
        if toggle_reverse and self.main_window.current_sort_mode == mode:
            # Toggle reverse order if same mode is already active
            self.main_window.is_reversed = not self.main_window.is_reversed
        else:
            # Set new mode with default order
            self.main_window.current_sort_mode = mode
            if mode == SortMode.SIZE or mode == SortMode.FILESIZE:
                self.main_window.is_reversed = False  # Default: largest first
            else:
                self.main_window.is_reversed = False  # Default: ascending/newest first
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images (will preserve current_image_path)
        self.apply_current_sort()
        
        # CRITICAL: Explicitly restore current image after sort, especially for random mode
        # This ensures the current image is always preserved even if apply_current_sort() had issues
        if current_image_path and mode == SortMode.RANDOM:
            displayed_after = self.main_window.get_displayed_images()
            if displayed_after and current_image_path in displayed_after:
                self.main_window.set_current_image_by_path(current_image_path, fallback_index=0)
                self.main_window.highlight_image()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()
    
    def apply_current_sort(self):
        """Apply the current sort mode to displayed images"""
        # CRITICAL: Use displayed_images directly, not get_displayed_images()
        # get_displayed_images() may return stale data from FileDataModel
        displayed = self.main_window.displayed_images if hasattr(self.main_window, 'displayed_images') else []
        if not displayed:
            return
        
        # Preserve current image path BEFORE sorting
        # CRITICAL: Get current_image_path from the source of truth
        current_image_path = self.main_window.get_current_image_path()
        
        # If no current image path, try to get it from highlight_index as fallback
        if not current_image_path and hasattr(self.main_window, 'highlight_index'):
            if 0 <= self.main_window.highlight_index < len(displayed):
                current_image_path = displayed[self.main_window.highlight_index]
        
        # CRITICAL: Preserve selected files BEFORE sorting (file paths are the source of truth)
        # selected_files is already a set of file paths, so we just need to filter it after sorting
        selected_files_before_sort = set()
        if hasattr(self.main_window, 'selected_files') and self.main_window.selected_files:
            selected_files_before_sort = self.main_window.selected_files.copy()
        
        # Use centralized display ordering function
        if displayed:
            directory = os.path.dirname(displayed[0])
            displayed = self.apply_display_order(displayed, directory)
        
        # Update displayed_images
        self.main_window._set_displayed_images_with_sync(displayed, sync=True)
        
        # Reorder thumbnails (same files, different order)
        if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
            if hasattr(self.main_window.thumbnail_container, 'canvas'):
                canvas = self.main_window.thumbnail_container.canvas
                
                # CRITICAL: Recalculate dynamic thumbnail size if not manually set
                # Use the sorted 'displayed' list directly to avoid reading stale data
                if (hasattr(self.main_window, 'thumbnail_operations_manager') and 
                    hasattr(self.main_window, 'manual_thumbnail_size') and 
                    not self.main_window.manual_thumbnail_size):
                    from thumbnails.thumbnail_constants import MIN_THUMBNAIL_SIZE, MAX_THUMBNAIL_SIZE
                    optimal_size = self.main_window.thumbnail_operations_manager.calculate_grid_for_images(len(displayed))[0]
                    if optimal_size != self.main_window.current_thumbnail_size:
                        # Single image: calculate_grid_for_images already uses viewport directly, no cap
                        if len(displayed) > 1:
                            optimal_size = max(MIN_THUMBNAIL_SIZE, min(MAX_THUMBNAIL_SIZE, optimal_size))
                        self.main_window.current_thumbnail_size = optimal_size
                        canvas.thumbnail_size = optimal_size
                
                # Reorder thumbnails with grid recalculation to apply new size
                canvas.reorder_thumbnails(displayed, force_recalculate_grid=True)
                
                # CRITICAL: Start background loading for thumbnails that don't have pixmaps yet
                if hasattr(self.main_window, 'start_background_thumbnail_loading_if_needed'):
                    self.main_window.start_background_thumbnail_loading_if_needed()
        
        # CRITICAL: Restore selected files after sorting (file paths are the source of truth)
        # Filter selected_files to only include files that are still in displayed_images after sorting
        if selected_files_before_sort:
            # Filter to only files that exist in the sorted displayed list
            self.main_window.selected_files = {
                path for path in selected_files_before_sort 
                if path in displayed
            }
        else:
            # No selections to preserve
            if hasattr(self.main_window, 'selected_files'):
                # Don't clear selections if they weren't set before - just filter existing ones
                if self.main_window.selected_files:
                    self.main_window.selected_files = {
                        path for path in self.main_window.selected_files 
                        if path in displayed
                    }
        
        # Restore current image (ensure it's still selected after sort)
        # CRITICAL: Always restore current_image_path if it exists in the sorted list
        if current_image_path and current_image_path in displayed:
            # Explicitly set current image by path - this is the source of truth
            self.main_window.set_current_image_by_path(current_image_path, fallback_index=0)
        elif displayed:
            # Fallback: use first image if no current image preserved
            self.main_window.set_current_image_by_path(displayed[0], fallback_index=0)
        
        # Update highlight - sync index and visually highlight
        self.main_window._sync_highlight_index_from_current_image_path()
        if hasattr(self.main_window, 'canvas') and self.main_window.canvas:
            self.main_window.canvas.set_highlight_index(self.main_window.highlight_index)
        
        # Update canvas selection to reflect preserved selections (file paths are source of truth)
        if hasattr(self.main_window, '_emit_selection_changed'):
            self.main_window._emit_selection_changed()
        
        # Update list view if in list view mode
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'list' and
            hasattr(self.main_window, 'view_manager')):
            self.main_window.view_manager.update_list_view()
        
        # When in slideshow, sync slideshow's image list from displayed_images
        # so sort mode changes affect both slideshow order and thumbnail view
        if (hasattr(self.main_window, 'current_view_mode') and 
            self.main_window.current_view_mode == 'slideshow' and
            hasattr(self.main_window, 'slideshow_manager') and self.main_window.slideshow_manager):
            self.main_window.slideshow_manager._sync_slideshow_images_from_displayed()
        
        # Visually highlight the current image (this updates the canvas highlight)
        self.main_window.highlight_image()

    def enforce_locked_first_in_thumbnail_view(self) -> bool:
        """Whether locked files should be pinned to the top of the thumbnail grid."""
        mw = self.main_window
        if mw.current_view_mode != 'thumbnail':
            return False
        if getattr(mw, 'specific_files_active', False):
            return False
        if not getattr(mw, 'allow_thumbnail_locking', False):
            return False
        # CUSTOM after in-place lock: positions stay until the user changes sort mode.
        if self.current_sort_mode == SortMode.CUSTOM:
            return False
        return True

    def needs_locked_files_first(self, images: List[str]) -> bool:
        """True when locked files exist but are not already at the top."""
        if not images or not self.enforce_locked_first_in_thumbnail_view():
            return False
        locked_paths, _ = self._separate_locked_unlocked(images)
        return bool(locked_paths) and images[: len(locked_paths)] != locked_paths

    def reorder_locked_files_first(self, images: List[str]) -> List[str]:
        """Move locked files to the top in .prsort order; preserve unlocked order."""
        if not images:
            return images
        locked_paths, unlocked_paths = self._separate_locked_unlocked(images)
        if not locked_paths:
            return images
        return locked_paths + unlocked_paths
    
    def _separate_locked_unlocked(self, images: List[str]) -> Tuple[List[str], List[str]]:
        """Separate images into locked and unlocked lists.
        
        CRITICAL RULES:
        1. .prsort is ONLY used to:
           - Determine which files are locked (via lock markers '*')
           - Get the ORDER of locked files (from .prsort file order)
        2. .prsort is NEVER used to order unlocked files!
        3. Unlocked files ALWAYS preserve their order from the input `images` list.
        
        This ensures:
        - Locked files appear in their saved order from .prsort (correct on startup)
        - Unlocked files maintain their current visual position (correct during operations)
        - Unlocked files are NEVER reordered based on .prsort
        
        Returns:
            Tuple of (locked_paths, unlocked_paths)
        """
        if not images:
            return ([], [])
        
        # Get lock manager
        lock_manager = getattr(self.main_window, 'lock_manager', None)
        if not lock_manager:
            return ([], images)
        
        directory = os.path.dirname(images[0])
        
        # CRITICAL: Read .prsort file ONLY to get:
        # 1. Which files are locked (via lock markers '*')
        # 2. The ORDER of locked files (from .prsort file order)
        # DO NOT use .prsort to order unlocked files!
        prsort_result = self._read_prsort_file(directory)
        locked_files = set()
        prsort_filenames = []
        
        if prsort_result:
            prsort_filenames, _, locked_files = prsort_result
        
        # If no .prsort file or no locked files in .prsort, try lock_manager as fallback
        if not locked_files:
            locked_files = lock_manager.get_locked_files(directory)
        
        # Build mapping of filename -> full path for fast lookup
        filename_to_path = {os.path.basename(path): path for path in images}
        
        # CRITICAL: Get locked files in their saved order from .prsort
        # This is the ONLY valid use of .prsort for ordering - locked files only!
        # NOTE: If a file is locked, it MUST be in .prsort with '*' prefix - that's the source of truth
        locked_paths = []
        locked_paths_set = set()  # For fast membership testing
        
        if prsort_result and prsort_filenames:
            # Iterate through .prsort filenames in order - this is the saved order
            # CRITICAL: Only process files that are marked as locked in .prsort
            for filename in prsort_filenames:
                if filename in locked_files and filename in filename_to_path:
                    path = filename_to_path[filename]
                    if path not in locked_paths_set:
                        locked_paths.append(path)
                        locked_paths_set.add(path)
        
        # Add any locked files not in .prsort at the end (shouldn't happen, but be safe)
        for path in images:
            filename = os.path.basename(path)
            if filename in locked_files and path not in locked_paths_set:
                locked_paths.append(path)
                locked_paths_set.add(path)
        
        # CRITICAL: Preserve order of unlocked files from input `images` list
        # DO NOT use .prsort to order unlocked files!
        # Unlocked files maintain their current visual position during operations
        # This is the key rule: unlocked files are NEVER reordered based on .prsort
        unlocked_paths = []
        for path in images:
            if path not in locked_paths_set:
                unlocked_paths.append(path)
        
        return (locked_paths, unlocked_paths)
    
    def apply_display_order(self, images: List[str], directory: Optional[str] = None, 
                            skip_locks: Optional[bool] = None) -> List[str]:
        """Centralized function to apply display ordering to a list of images.
        
        This function ensures consistent ordering across all display operations:
        - Locked files are always at the top in their saved order from .prsort (except when skip_locks)
        - Unlocked files are sorted according to the current sort mode
        - The result is: locked_paths + sorted_unlocked_paths (or just sorted images when skip_locks)
        
        Args:
            images: List of file paths to order
            directory: Optional directory path. If None, derived from first image path.
            skip_locks: If True, sort all images together (no lock separation). If None, inferred from
                        current_view_mode (list view and slideshow use skip_locks).
            
        Returns:
            Ordered list of file paths with locked files first, then unlocked files sorted.
            When skip_locks, returns sorted images without separating locked files.
        """
        if not images:
            return []
        
        try:
            # Determine directory if not provided
            if directory is None:
                if not images:
                    return []
                directory = os.path.dirname(images[0])
                # Validate directory exists
                if not directory or not os.path.exists(directory):
                    # If directory is invalid, return images as-is (fallback)
                    return images
            
            # Check if we should skip lock separation (sort all images together)
            # In list view: sort all files together
            # In slideshow: sort/randomize all files together (locks don't restrict slideshow order)
            if skip_locks is None:
                is_list_view = (hasattr(self.main_window, 'current_view_mode') and 
                              self.main_window.current_view_mode == 'list')
                is_slideshow = (hasattr(self.main_window, 'current_view_mode') and 
                              self.main_window.current_view_mode == 'slideshow')
                skip_locks = is_list_view or is_slideshow
            
            # Handle CUSTOM sort mode separately
            # Clear EXIF date sections if not in EXIF_DATE mode
            # Also clear duplicate sections if not in DUPLICATES mode
            if self.main_window.current_sort_mode not in (SortMode.EXIF_DATE, SortMode.EXIF_YEAR):
                if hasattr(self.main_window, 'exif_date_sections'):
                    self.main_window.exif_date_sections = []
                if hasattr(self.main_window, 'exif_section_expanded'):
                    self.main_window.exif_section_expanded = {}
            # Only clear duplicate_sections if they were actually set (transitioning FROM duplicates mode)
            if (self.main_window.current_sort_mode != SortMode.DUPLICATES and
                hasattr(self.main_window, 'duplicate_sections') and
                self.main_window.duplicate_sections):
                self.main_window.duplicate_sections = []

            if self.main_window.current_sort_mode == SortMode.CUSTOM:
                if skip_locks:
                    # In list view, don't separate locked files - just apply custom sort to all files
                    unlocked_paths, saved_is_reversed = self._apply_custom_sort_unlocked(directory, images)
                    self.main_window.is_reversed = saved_is_reversed
                    return unlocked_paths
                else:
                    # CRITICAL: Always separate locked and unlocked files first
                    # Locked files must ALWAYS be at the top in their saved order, even in CUSTOM mode
                    locked_paths, unlocked_paths = self._separate_locked_unlocked(images)
                    # Apply custom sort to unlocked files:
                    # - Unlocked files in .prsort (e.g., from similarity search) use .prsort order
                    # - Unlocked files NOT in .prsort preserve their input order (for drag/drop)
                    unlocked_paths, saved_is_reversed = self._apply_custom_sort_unlocked(directory, unlocked_paths)
                    # Update is_reversed flag from .prsort file
                    self.main_window.is_reversed = saved_is_reversed
                    # Combine: locked files first (in their saved order from .prsort), 
                    # then unlocked files (in .prsort order if present, otherwise input order)
                    return locked_paths + unlocked_paths
            else:
                if skip_locks:
                    # In list view, don't separate locked files - just sort all files together
                    sorted_images = images.copy()
                    if self.main_window.current_sort_mode == SortMode.NAME:
                        sorted_images = self._sort_by_name(sorted_images)
                    elif self.main_window.current_sort_mode == SortMode.SIZE:
                        sorted_images = self._sort_by_size(sorted_images)
                    elif self.main_window.current_sort_mode == SortMode.FILESIZE:
                        sorted_images = self._sort_by_file_size(sorted_images)
                    elif self.main_window.current_sort_mode == SortMode.RANDOM:
                        sorted_images = self._sort_by_random(sorted_images)
                    elif self.main_window.current_sort_mode == SortMode.EXIF_DATE:
                        sorted_images = self._sort_by_exif_date(sorted_images)
                    elif self.main_window.current_sort_mode == SortMode.EXIF_YEAR:
                        sorted_images = self._sort_by_exif_year(sorted_images)
                    elif self.main_window.current_sort_mode == SortMode.DIMENSIONS:
                        sorted_images = self._sort_by_dimensions(sorted_images)
                    elif self.main_window.current_sort_mode == SortMode.PERMISSIONS:
                        sorted_images = self._sort_by_permissions(sorted_images)
                    else:  # DATE or default
                        sorted_images = self._sort_by_date(sorted_images)
                    return sorted_images
                else:
                    # Separate locked and unlocked files for other sort modes
                    locked_paths, unlocked_paths = self._separate_locked_unlocked(images)
                    
                    # Sort unlocked files based on current sort mode
                    if self.main_window.current_sort_mode == SortMode.NAME:
                        unlocked_paths = self._sort_by_name(unlocked_paths)
                    elif self.main_window.current_sort_mode == SortMode.SIZE:
                        unlocked_paths = self._sort_by_size(unlocked_paths)
                    elif self.main_window.current_sort_mode == SortMode.FILESIZE:
                        unlocked_paths = self._sort_by_file_size(unlocked_paths)
                    elif self.main_window.current_sort_mode == SortMode.RANDOM:
                        # For random sort, shuffle unlocked files only
                        unlocked_paths = self._sort_by_random(unlocked_paths)
                    elif self.main_window.current_sort_mode == SortMode.EXIF_DATE:
                        unlocked_paths = self._sort_by_exif_date(unlocked_paths)
                    elif self.main_window.current_sort_mode == SortMode.EXIF_YEAR:
                        unlocked_paths = self._sort_by_exif_year(unlocked_paths)
                    elif self.main_window.current_sort_mode == SortMode.DIMENSIONS:
                        unlocked_paths = self._sort_by_dimensions(unlocked_paths)
                    elif self.main_window.current_sort_mode == SortMode.PERMISSIONS:
                        unlocked_paths = self._sort_by_permissions(unlocked_paths)
                    else:  # DATE or default
                        unlocked_paths = self._sort_by_date(unlocked_paths)
                    
                    # Combine: locked files first (in their saved order), then unlocked files
                    return locked_paths + unlocked_paths
        except Exception as e:
            # If anything goes wrong, return the original list to avoid losing files
            import traceback
            print(f"Error in apply_display_order: {e}")
            traceback.print_exc()
            return images
    
    def _apply_custom_sort_unlocked(self, directory: str, unlocked_files: List[str]) -> Tuple[List[str], bool]:
        """Apply custom sort order to unlocked files only.
        
        CRITICAL: Normally, DO NOT use .prsort to order unlocked files!
        .prsort should ONLY be used to:
        1. Determine which files are locked (via lock markers)
        2. Get the order of locked files
        
        EXCEPTION: When unlocked files are in .prsort (e.g., after similarity search),
        we SHOULD use .prsort order for those files to preserve search result order.
        Unlocked files NOT in .prsort preserve their input order (for drag/drop operations).
        """
        prsort_result = self._read_prsort_file(directory)
        if not prsort_result:
            return (unlocked_files, False)
        
        prsort_filenames, is_reversed, locked_files = prsort_result
        
        # Build mapping of filename -> full path for unlocked files
        filename_to_path = {os.path.basename(path): path for path in unlocked_files}
        
        # Separate unlocked files into two groups:
        # 1. Unlocked files that ARE in .prsort (e.g., from similarity search) - use .prsort order
        # 2. Unlocked files NOT in .prsort - preserve input order
        unlocked_in_prsort = []
        unlocked_in_prsort_set = set()
        unlocked_not_in_prsort = []
        
        # First, get unlocked files in .prsort order (files in .prsort but not locked)
        for filename in prsort_filenames:
            if filename not in locked_files and filename in filename_to_path:
                path = filename_to_path[filename]
                if path not in unlocked_in_prsort_set:
                    unlocked_in_prsort.append(path)
                    unlocked_in_prsort_set.add(path)
        
        # Then, get unlocked files NOT in .prsort (preserve their input order)
        for path in unlocked_files:
            if path not in unlocked_in_prsort_set:
                unlocked_not_in_prsort.append(path)
        
        # Combine: unlocked files from .prsort (in .prsort order) + unlocked files not in .prsort (input order)
        return (unlocked_in_prsort + unlocked_not_in_prsort, is_reversed)
    
    def _sort_by_date(self, images: List[str]) -> List[str]:
        """Sort images by date."""
        try:
            images.sort(key=self.get_sort_key, reverse=not self.main_window.is_reversed)
        except Exception:
            # If date sorting fails, fallback to alphabetical
            images.sort(key=lambda p: p.lower())
        return images

    def _sort_by_exif_date(self, images: List[str]) -> List[str]:
        """Sort images by EXIF date, grouping by month.
        
        Returns a flat list of images sorted by EXIF date.
        Section boundaries are stored in main_window.exif_date_sections
        for use by thumbnail canvas.
        """
        from datetime import datetime
        from collections import defaultdict
        
        # Group images by month based on EXIF date
        month_groups = defaultdict(list)  # {month_key: [file_paths]}
        undated_files = []  # Files without EXIF data
        
        for image_path in images:
            try:
                exif_timestamp = self._get_exif_timestamp_for_sort(image_path)
                if exif_timestamp is not None:
                    dt = datetime.fromtimestamp(exif_timestamp)
                    month_key = dt.strftime("%Y-%m")
                    month_groups[month_key].append((image_path, exif_timestamp))
                    continue
            except Exception:
                pass
            
            # No EXIF data - add to undated
            undated_files.append(image_path)
        
        # Sort months (newest first by default, or oldest first if reversed)
        sorted_months = sorted(month_groups.keys(), reverse=not self.main_window.is_reversed)
        
        # Sort images within each month by EXIF date
        result = []
        section_boundaries = []  # List of (start_index, month_key) tuples
        
        for month_key in sorted_months:
            # Sort files in this month by timestamp
            month_files = sorted(month_groups[month_key], 
                                    key=lambda x: x[1], 
                                    reverse=not self.main_window.is_reversed)
            
            # Store section boundary
            section_boundaries.append((len(result), month_key))
            
            # Add files to result
            result.extend([path for path, _ in month_files])
        
        # Add undated files at the end
        if undated_files:
            section_boundaries.append((len(result), "undated"))
            result.extend(undated_files)
        
        # Store section boundaries for thumbnail canvas
        # CRITICAL: Only set exif_date_sections if we're actually in EXIF_DATE mode
# This prevents stale data from being used when sort mode changes
        if self.main_window.current_sort_mode == SortMode.EXIF_DATE:
            self.main_window.exif_date_sections = section_boundaries
        else:
            # Clear exif_date_sections if not in EXIF_DATE mode (defensive)
            if hasattr(self.main_window, 'exif_date_sections'):
                self.main_window.exif_date_sections = []
        
        return result

    
    def _sort_by_exif_year(self, images: List[str]) -> List[str]:
        """Sort images by EXIF date, grouping by year.
        
        Returns a flat list of images sorted by EXIF date.
        Section boundaries are stored in main_window.exif_date_sections
        for use by thumbnail canvas.
        """
        from datetime import datetime
        from collections import defaultdict
        
        # Group images by year based on EXIF date
        year_groups = defaultdict(list)  # {year_key: [file_paths]}
        undated_files = []  # Files without EXIF data
        
        for image_path in images:
            try:
                exif_timestamp = self._get_exif_timestamp_for_sort(image_path)
                if exif_timestamp is not None:
                    dt = datetime.fromtimestamp(exif_timestamp)
                    year_key = dt.strftime("%Y")
                    year_groups[year_key].append((image_path, exif_timestamp))
                    continue
            except Exception:
                pass
            
            # No EXIF data - add to undated
            undated_files.append(image_path)
        
        # Sort years (newest first by default, or oldest first if reversed)
        sorted_years = sorted(year_groups.keys(), reverse=not self.main_window.is_reversed)
        
        # Sort images within each year by EXIF date
        result = []
        section_boundaries = []  # List of (start_index, year_key) tuples
        
        for year_key in sorted_years:
            # Sort files in this year by timestamp
            year_files = sorted(year_groups[year_key], 
                                    key=lambda x: x[1], 
                                    reverse=not self.main_window.is_reversed)
            
            # Store section boundary
            section_boundaries.append((len(result), year_key))
            
            # Add files to result
            result.extend([path for path, _ in year_files])
        
        # Add undated files at the end
        if undated_files:
            section_boundaries.append((len(result), "undated"))
            result.extend(undated_files)
        
        # Store section boundaries for thumbnail canvas
        # CRITICAL: Only set exif_date_sections if we're actually in EXIF_YEAR mode
        # This prevents stale data from being used when sort mode changes
        if self.main_window.current_sort_mode == SortMode.EXIF_YEAR:
            self.main_window.exif_date_sections = section_boundaries
        else:
            # Clear exif_date_sections if not in EXIF_YEAR mode (defensive)
            if hasattr(self.main_window, 'exif_date_sections'):
                self.main_window.exif_date_sections = []
        
        return result

    def _sort_by_name(self, images: List[str]) -> List[str]:
        """Sort images by name."""
        images.sort(key=lambda p: p.lower(), reverse=self.main_window.is_reversed)
        return images
    
    def _sort_by_size(self, images: List[str]) -> List[str]:
        """Sort images by size (width × height), then by width for same area, then by path."""
        def get_size_sort_key(path):
            try:
                dimensions = self._get_dimensions_for_sort(path)
                if dimensions:
                    width, height = dimensions
                    area = width * height
                    if self.main_window.is_reversed:
                        return (area, -width, path.lower())
                    return (area, width, path.lower())
                return (0, 0, path.lower())
            except Exception:
                return (0, 0, path.lower())
        
        images.sort(key=get_size_sort_key, reverse=not self.main_window.is_reversed)
        return images
    
    def _sort_by_file_size(self, images: List[str]) -> List[str]:
        """Sort images by file size (bytes on disk), then by path."""
        def get_file_size_sort_key(path):
            try:
                file_size_bytes = os.path.getsize(path)
                return (file_size_bytes, path.lower())
            except Exception:
                return (0, path.lower())  # Sort failed images to end
        
        images.sort(key=get_file_size_sort_key, reverse=not self.main_window.is_reversed)
        return images
    
    def _sort_by_dimensions(self, images: List[str]) -> List[str]:
        """Sort images by dimensions: width first (numeric), then height (numeric)."""
        def get_dimensions_sort_key(path):
            try:
                dimensions = self._get_dimensions_for_sort(path)
                if dimensions:
                    width, height = dimensions
                    return (width, height, path.lower())
                return (0, 0, path.lower())
            except Exception:
                return (0, 0, path.lower())
        
        images.sort(key=get_dimensions_sort_key, reverse=self.main_window.is_reversed)
        return images
    
    def _sort_by_permissions(self, images: List[str]) -> List[str]:
        """Sort images by permissions string (rwxrwxrwx format), then by path."""
        import stat
        
        def get_permissions_sort_key(path):
            try:
                # Get file permissions
                file_stat = os.stat(path)
                mode = file_stat.st_mode
                permissions = stat.filemode(mode)
                # Convert from -rwxrwxrwx format to rwxrwxrwx format (remove leading dash)
                if permissions.startswith('-'):
                    perms_str = permissions[1:]
                else:
                    perms_str = permissions
                # Return tuple: (permissions_string, path) for ASCII sorting
                return (perms_str, path.lower())
            except Exception:
                # If permissions unavailable, use default
                return ("----------", path.lower())
        
        images.sort(key=get_permissions_sort_key, reverse=self.main_window.is_reversed)
        return images
    
    
    def _sort_by_random(self, images: List[str]) -> List[str]:
        """Sort images randomly."""
        shuffled = images.copy()
        random.shuffle(shuffled)
        return shuffled
    
    def _get_prsort_file_path(self, directory: str) -> str:
        """Get the path to the .prsort file for a directory"""
        return os.path.join(directory, '.prsort')
    
    def _read_prsort_file(self, directory: str) -> Optional[Tuple[List[str], bool, Set[str]]]:
        """Read the custom sort order from .prsort file.
        
        Returns:
            Tuple of (filenames list, is_reversed bool, locked_files set) or None
        """
        prsort_path = self._get_prsort_file_path(directory)
        if not os.path.exists(prsort_path):
            return None
        
        try:
            from files.prsort_io import parse_custom_sort_file, read_prsort_lines

            lines = read_prsort_lines(prsort_path)
            if not lines:
                return None
            parsed = parse_custom_sort_file(lines)
            if parsed is None:
                return None
            return parsed
        except Exception as e:
            print(f"Error reading .prsort file: {e}")
            return None
    
    def save_custom_sort(self, show_message: bool = False):
        """Save the current thumbnail list and order to .prsort file"""
        # Only available in thumbnail mode
        if self.main_window.current_view_mode != 'thumbnail':
            return
        
        # Check if in specific files mode
        if getattr(self.main_window, 'specific_files_active', False):
            self.main_window.status_notification.show_message("Cannot save custom sort in specific files mode")
            return
        
        # Get current displayed images
        image_paths = self.main_window.get_displayed_images()
        if not image_paths:
            self.main_window.status_notification.show_message("No images to save")
            return
        
        # Check if images are from multiple directories
        directories = set()
        for image_path in image_paths:
            if os.path.exists(image_path):
                directories.add(os.path.dirname(image_path))
        if len(directories) > 1:
            self.main_window.status_notification.show_message("Cannot save custom sort when images are from multiple directories")
            return
        
        # Get directory from first image (all images are from same directory at this point)
        if not image_paths or not os.path.exists(image_paths[0]):
            self.main_window.status_notification.show_message("No valid images to save")
            return
        
        target_directory = os.path.dirname(image_paths[0])
        
        # Get is_reversed flag
        is_reversed = getattr(self.main_window, 'is_reversed', False)
        
        # Write to .prsort file (preserve locks)
        success = self.write_prsort_file(target_directory, image_paths, is_reversed, preserve_locks=True)
        
        if success:
            if show_message:
                self.main_window.status_notification.show_message("Custom sort order saved")
            # Switch to custom sort mode
            self.main_window.current_sort_mode = SortMode.CUSTOM
            # Update menu checkmarks
            if hasattr(self.main_window, 'menu_manager') and self.main_window.menu_manager:
                self.main_window.menu_manager.update_sort_menu_checkmarks()
        else:
            self.main_window.status_notification.show_message("Failed to save custom sort order")
    
    def write_prsort_file(self, directory: str, image_paths: List[str], is_reversed: bool = False, preserve_locks: bool = True) -> bool:
        """Write the custom sort order to .prsort file.
        
        Args:
            directory: Directory path
            image_paths: List of full file paths in desired order
            is_reversed: Whether sort is reversed
            preserve_locks: If True, preserve existing lock status from .prsort file
            
        Returns:
            True if successful, False otherwise
        """
        prsort_path = self._get_prsort_file_path(directory)
        
        try:
            # Get existing lock status if preserving locks
            locked_files = set()
            if preserve_locks:
                prsort_result = self._read_prsort_file(directory)
                if prsort_result:
                    _, _, locked_files = prsort_result
            
            # Extract just filenames from full paths
            filenames = [os.path.basename(path) for path in image_paths]
            
            # Reverse if needed
            if is_reversed:
                filenames = list(reversed(filenames))
            
            # Write to file with reversed flag header and lock markers
            with open(prsort_path, 'w', encoding='utf-8') as f:
                # CRITICAL WARNING: This file is ONLY for custom sort ordering and file locking
                # DO NOT use .prsort to order unlocked files - they preserve their visual order or use active sort mode
                f.write('# THIS FILE IS ONLY FOR CUSTOM SORT ORDERING AND FILE LOCKING\n')
                f.write('# DO NOT USE .prsort TO ORDER UNLOCKED FILES\n')
                # Write header with reversed flag
                f.write(f'#reversed:{str(is_reversed).lower()}\n')
                # Write filenames with lock prefix if locked
                for filename in filenames:
                    if filename in locked_files:
                        f.write(f'*{filename}\n')
                    else:
                        f.write(f'{filename}\n')
            return True
        except Exception as e:
            print(f"Error writing .prsort file: {e}")
            return False
    
    def _apply_custom_sort(self, directory: str, all_files: List[str]) -> Tuple[List[str], bool]:
        """Apply custom sort order from .prsort file."""
        prsort_result = self._read_prsort_file(directory)
        if not prsort_result:
            return (all_files, False)
        
        prsort_filenames, is_reversed, locked_files = prsort_result
        
        # Create a mapping of filename -> full path
        filename_to_path = {os.path.basename(path): path for path in all_files}
        
        # CRITICAL: Preserve the exact order from .prsort file (don't separate locked/unlocked)
        # This allows locked files to be manually reordered via drag/drop
        sorted_paths = []
        seen_filenames = set()
        
        # Add files in .prsort order (preserving their exact positions, including locked files)
        for filename in prsort_filenames:
            if filename in filename_to_path:
                path = filename_to_path[filename]
                sorted_paths.append(path)
                seen_filenames.add(filename)
        
        # Add files not in .prsort to the end (these are new files)
        for path in all_files:
            filename = os.path.basename(path)
            if filename not in seen_filenames:
                sorted_paths.append(path)
        
        return (sorted_paths, is_reversed)
    
    def filter_images_by_pattern(self, image_paths: List[str]) -> List[str]:
        """Filter image paths based on the filter_pattern glob pattern"""
        if not hasattr(self.main_window, 'filter_pattern') or not self.main_window.filter_pattern:
            return image_paths
        
        # Get pattern with trailing asterisk for fnmatch
        match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(self.main_window.filter_pattern)
        
        filtered_paths = []
        for image_path in image_paths:
            filename = os.path.basename(image_path)
            if fnmatch.fnmatch(filename.lower(), match_pattern.lower()):
                filtered_paths.append(image_path)
        
        return filtered_paths
    
    def set_name_sort(self, reverse: bool = False):
        """Set name sort mode with specified direction"""
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
        
        # Reset random sorting if active
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            self.main_window.reset_to_original_order()
        
        # Set sort mode with specified direction
        self.main_window.current_sort_mode = SortMode.NAME
        self.main_window.is_reversed = reverse
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images
        self.apply_current_sort()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()
        
        # Show status message
        direction = "Z to A" if reverse else "A to Z"
        self.main_window.status_notification.show_message(f"Sort mode set to Name ({direction})")
    
    def set_date_sort(self, reverse: bool = False, *, notify: bool = True):
        """Set date sort mode with specified direction"""
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
        elif current_mode not in ['thumbnail', 'browse']:
            return
        
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        mode_changed = (
            self.main_window.current_sort_mode != SortMode.DATE
            or self.main_window.is_reversed != reverse
        )

        # Reset random sorting if active (needs a displayed list)
        if self.main_window.current_sort_mode == SortMode.RANDOM and displayed:
            self.main_window.reset_to_original_order()

        # Persist sort mode even when the file list is empty (e.g. API refresh).
        self.main_window.current_sort_mode = SortMode.DATE
        self.main_window.is_reversed = reverse
        self.save_sorting_settings()

        if displayed:
            self.apply_current_sort()

        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()

        if notify and mode_changed:
            direction = "Oldest first" if reverse else "Newest first"
            self.main_window.status_notification.show_message(
                f"Sort mode set to Date ({direction})"
            )

    def set_exif_date_sort(self, reverse: bool = False):
        """Set EXIF date sort mode with specified direction"""
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
        elif current_mode not in ['thumbnail', 'browse']:
            return
        
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        # Reset random sorting if active
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            self.main_window.reset_to_original_order()
        
        # Set sort mode with specified direction
        self.main_window.current_sort_mode = SortMode.EXIF_DATE
        self.main_window.is_reversed = reverse
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images
        self.apply_current_sort()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()
        
        # Show status message
        direction = "Oldest first" if reverse else "Newest first"
        self.main_window.status_notification.show_message(f"Sort mode set to EXIF Date ({direction})")

    
    def set_exif_year_sort(self, reverse: bool = False):
        """Set EXIF year sort mode with specified direction"""
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
        elif current_mode not in ['thumbnail', 'browse']:
            return
        
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        # Reset random sorting if active
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            self.main_window.reset_to_original_order()
        
        # Set sort mode with specified direction
        self.main_window.current_sort_mode = SortMode.EXIF_YEAR
        self.main_window.is_reversed = reverse
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images
        self.apply_current_sort()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()
        
        # Show status message
        direction = "Oldest first" if reverse else "Newest first"
        self.main_window.status_notification.show_message(f"Sort mode set to EXIF Year ({direction})")

    def set_size_sort(self, reverse: bool = False):
        """Set size sort mode with specified direction"""
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
        elif current_mode not in ['thumbnail', 'browse']:
            return
        
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        # Reset random sorting if active
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            self.main_window.reset_to_original_order()
        
        # Set sort mode with specified direction
        self.main_window.current_sort_mode = SortMode.SIZE
        self.main_window.is_reversed = reverse
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images
        self.apply_current_sort()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()
        
        # Show status message
        direction = "Smallest first" if reverse else "Largest first"
        self.main_window.status_notification.show_message(f"Sort mode set to Size ({direction})")
    
    def set_dimensions_sort(self, reverse: bool = False):
        """Set dimensions sort mode with specified direction"""
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
        elif current_mode not in ['thumbnail', 'browse']:
            return
        
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        # Reset random sorting if active
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            self.main_window.reset_to_original_order()
        
        # Set sort mode with specified direction
        self.main_window.current_sort_mode = SortMode.DIMENSIONS
        self.main_window.is_reversed = reverse
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images
        self.apply_current_sort()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()
        
        # Show status message
        direction = "Smallest first" if reverse else "Largest first"
        self.main_window.status_notification.show_message(f"Sort mode set to Dimensions ({direction})")
    
    def simple_reverse_image_order(self):
        """Simple reverse: toggle the current sort direction without changing sort mode"""
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
        elif current_mode not in ['thumbnail', 'browse']:
            return
        
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        # Handle random sort reversal
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            # CRITICAL: Preserve selected files BEFORE reversing (file paths are the source of truth)
            # selected_files is already a set of file paths, so they persist automatically
            selected_files_before_reverse = set()
            if hasattr(self.main_window, 'selected_files') and self.main_window.selected_files:
                selected_files_before_reverse = self.main_window.selected_files.copy()
            
            # Reverse displayed_images directly
            displayed.reverse()
            self.main_window.displayed_images = displayed
            
            # Update displayed_images with sync
            self.main_window._set_displayed_images_with_sync(displayed, sync=True)
            
            # CRITICAL: Restore selected files after reversal (file paths are the source of truth)
            # Filter selected_files to only include files that are still in displayed_images
            if selected_files_before_reverse:
                self.main_window.selected_files = {
                    path for path in selected_files_before_reverse 
                    if path in displayed
                }
            elif hasattr(self.main_window, 'selected_files') and self.main_window.selected_files:
                # Filter existing selections if they weren't explicitly preserved
                self.main_window.selected_files = {
                    path for path in self.main_window.selected_files 
                    if path in displayed
                }
            
            # Reorder thumbnails
            if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
                if hasattr(self.main_window.thumbnail_container, 'canvas'):
                    self.main_window.thumbnail_container.canvas.reorder_thumbnails(displayed, force_recalculate_grid=False)
                    # CRITICAL: Start background loading for thumbnails that don't have pixmaps yet
                    if hasattr(self.main_window, 'start_background_thumbnail_loading_if_needed'):
                        self.main_window.start_background_thumbnail_loading_if_needed()
            
            # Update highlight index after reversal
            self.main_window._sync_highlight_index_from_current_image_path()
            if hasattr(self.main_window, 'canvas') and self.main_window.canvas:
                self.main_window.canvas.set_highlight_index(self.main_window.highlight_index)
            
            # Update canvas selection to reflect preserved selections (file paths are source of truth)
            if hasattr(self.main_window, '_emit_selection_changed'):
                self.main_window._emit_selection_changed()
            
            # Ensure the highlight is on the correct image and scroll to show it
            self.main_window.highlight_image()
            
            # Update UI
            self.main_window.update_status_bar_sections()
            self.main_window.update_sort_menu_checkmarks()
            
            # Show status message
            self.main_window.status_notification.show_message("Random sort order reversed")
            return
        
        # Handle custom sort reversal
            # Clear EXIF date sections if not in EXIF_DATE mode
            # Also clear duplicate sections if not in DUPLICATES mode
            if self.main_window.current_sort_mode not in (SortMode.EXIF_DATE, SortMode.EXIF_YEAR):
                if hasattr(self.main_window, 'exif_date_sections'):
                    self.main_window.exif_date_sections = []
                if hasattr(self.main_window, 'exif_section_expanded'):
                    self.main_window.exif_section_expanded = {}
            # Only clear duplicate_sections if they were actually set (transitioning FROM duplicates mode)
            if (self.main_window.current_sort_mode != SortMode.DUPLICATES and
                hasattr(self.main_window, 'duplicate_sections') and
                self.main_window.duplicate_sections):
                self.main_window.duplicate_sections = []

        if self.main_window.current_sort_mode == SortMode.CUSTOM:
            # CRITICAL: Preserve current image path BEFORE reversing (source of truth)
            current_image_path = self.main_window.get_current_image_path()
            
            # If no current image path, try to get it from highlight_index as fallback
            if not current_image_path and hasattr(self.main_window, 'highlight_index'):
                if 0 <= self.main_window.highlight_index < len(displayed):
                    current_image_path = displayed[self.main_window.highlight_index]
            
            # CRITICAL: Preserve selected files BEFORE reversing (file paths are the source of truth)
            # selected_files is already a set of file paths, so they persist automatically
            selected_files_before_reverse = set()
            if hasattr(self.main_window, 'selected_files') and self.main_window.selected_files:
                selected_files_before_reverse = self.main_window.selected_files.copy()
            
            # Toggle reverse order flag
            self.main_window.is_reversed = not self.main_window.is_reversed
            
            # Reverse displayed_images directly
            displayed.reverse()
            
            # Update displayed_images with sync
            self.main_window._set_displayed_images_with_sync(displayed, sync=True)
            
            # CRITICAL: Restore selected files after reversal (file paths are the source of truth)
            # Filter selected_files to only include files that are still in displayed_images
            if selected_files_before_reverse:
                self.main_window.selected_files = {
                    path for path in selected_files_before_reverse 
                    if path in displayed
                }
            elif hasattr(self.main_window, 'selected_files') and self.main_window.selected_files:
                # Filter existing selections if they weren't explicitly preserved
                self.main_window.selected_files = {
                    path for path in self.main_window.selected_files 
                    if path in displayed
                }
            
            # Reorder thumbnails (same files, different order)
            if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container:
                if hasattr(self.main_window.thumbnail_container, 'canvas'):
                    canvas = self.main_window.thumbnail_container.canvas
                    
                    # Reorder thumbnails with grid recalculation
                    canvas.reorder_thumbnails(displayed, force_recalculate_grid=False)
                    
                    # CRITICAL: Start background loading for thumbnails that don't have pixmaps yet
                    if hasattr(self.main_window, 'start_background_thumbnail_loading_if_needed'):
                        self.main_window.start_background_thumbnail_loading_if_needed()
            
            # Restore current image by path (source of truth)
            if current_image_path and current_image_path in displayed:
                # Explicitly set current image by path - this is the source of truth
                self.main_window.set_current_image_by_path(current_image_path, fallback_index=0)
            elif displayed:
                # Fallback: use first image if no current image preserved
                self.main_window.set_current_image_by_path(displayed[0], fallback_index=0)
            
            # Update highlight - sync index and visually highlight
            self.main_window._sync_highlight_index_from_current_image_path(displayed)
            if hasattr(self.main_window, 'canvas') and self.main_window.canvas:
                self.main_window.canvas.set_highlight_index(self.main_window.highlight_index)
            
            # Update canvas selection to reflect preserved selections (file paths are source of truth)
            if hasattr(self.main_window, '_emit_selection_changed'):
                self.main_window._emit_selection_changed()
            
            # Visually highlight the current image (this updates the canvas highlight)
            self.main_window.highlight_image()
            
            
            # Save the new custom sort order with updated reversed flag
            self.save_custom_sort()
            
            # Save settings to persist the reversed flag
            self.save_sorting_settings()
            
            # Update UI
            self.main_window.update_status_bar_sections()
            self.main_window.update_sort_menu_checkmarks()
            
            # Show status message
            self.main_window.status_notification.show_message("Custom sort order reversed")
            return
        
        # Toggle reverse order for non-custom sorts
        self.main_window.is_reversed = not self.main_window.is_reversed
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images
        self.apply_current_sort()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()
        
        # Show status message
        direction_desc = "reversed" if self.main_window.is_reversed else "normal"
        self.main_window.status_notification.show_message(f"Sort order: {direction_desc}")
    
    def set_custom_sort(self):
        """Set custom sort mode, loading from .prsort file if available"""
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

        if self.main_window.current_view_mode == 'slideshow':
            self.main_window.slideshow_manager.stop_slideshow()
        
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        # Reset random sorting if active
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            self.main_window.reset_to_original_order()
        
        # Set sort mode to CUSTOM
        self.main_window.current_sort_mode = SortMode.CUSTOM
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images
        self.apply_current_sort()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.main_window.update_sort_menu_checkmarks()
        
        # Show status message
        # self.main_window.status_notification.show_message("Sort mode set to Custom")
        pass # DGN
    
    def update_sort_menu_checkmarks(self):
        """Update menu checkmarks to reflect current sort mode"""
        if hasattr(self.main_window, 'menu_manager') and self.main_window.menu_manager:
            self.main_window.menu_manager.update_sort_menu_checkmarks()
    
    def reset_to_original_order(self):
        """Reset to original order (date sort)"""
        if self.main_window.current_view_mode == 'slideshow2':
            self.main_window.slideshow2_manager.stop_slideshow2()
        if self.main_window.current_view_mode == 'slideshow3':
            self.main_window.slideshow3_manager.stop_slideshow3()

        displayed = self.main_window.get_displayed_images()
        if not displayed:
            return
        
        # Set sort mode to DATE
        self.main_window.current_sort_mode = SortMode.DATE
        self.main_window.is_reversed = False
        
        # Save settings
        self.save_sorting_settings()
        
        # Apply the sort to current images
        self.apply_current_sort()
        
        # Update UI
        self.main_window.update_status_bar_sections()
        self.update_sort_menu_checkmarks()
        
        # Show status message
        self.main_window.status_notification.show_message("Sort mode set to Date (Newest first)")
