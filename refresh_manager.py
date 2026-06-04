#!/usr/bin/env python3
"""
Refresh Manager
Handles directory refresh logic and efficient updates

Refresh contract:
- Entry: refresh_directory(), REFRESH_REQUESTED / FILES_CHANGED_ON_DISK on EventBus.
- Guards: specific_files_active uses _refresh_specific_files_list; skip when sets match
  (and optional mtime pass for small sets); respect browse_view_exit_in_progress and
  main_window._refresh_in_progress / beachball_fix safe_refresh_wrapper for concurrency.
- displayed_images updates go through main_window._set_displayed_images_with_sync so
  FileDataModel and subscribers stay aligned.
"""

import os
from typing import List, Set, Optional
from PySide6.QtCore import QTimer

from exif_image_loader import get_image_dimensions_fast_metadata
from sort_mode import SortMode
from event_bus import FILES_CHANGED_ON_DISK, REFRESH_REQUESTED


class RefreshManager:
    """Manages directory refresh and efficient update operations"""
    
    def __init__(self, main_window):
        """
        Initialize the refresh manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
        # Subscribe to refresh events via event bus
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            main_window.event_bus.subscribe(REFRESH_REQUESTED, self._on_refresh_requested)
            main_window.event_bus.subscribe(FILES_CHANGED_ON_DISK, self._on_files_changed_on_disk)

    def _on_refresh_requested(self, force: bool = False):
        """Handle REFRESH_REQUESTED event"""
        self.refresh_directory(force=force)

    def _on_files_changed_on_disk(self, directory: str):
        """Handle FILES_CHANGED_ON_DISK event - run efficient refresh check"""
        if directory and directory == getattr(self.main_window, 'current_directory', None):
            self._check_and_refresh_if_changed()
    
    def _check_and_refresh_if_changed(self):
        """Check if directory files changed and only refresh if necessary - prevents unnecessary flashing"""
        # CRITICAL: In specific files mode, refresh only the specific files set
        if getattr(self.main_window, 'specific_files_active', False):
            if hasattr(self.main_window, '_refresh_specific_files_list'):
                self.main_window._refresh_specific_files_list(force=False)
            return
        
        if not self.main_window.current_directory or not os.path.exists(self.main_window.current_directory):
            return
        
        # Get current files from disk
        if hasattr(self.main_window, 'directory_loader'):
            current_files = self.main_window.directory_loader._get_current_directory_files()
        else:
            current_files = self.main_window._get_current_directory_files()
        if current_files is None:
            return
        
        # Get currently displayed files
        displayed_set = set(self.main_window.get_displayed_images() or [])
        
        # Quick check: if sets are identical, nothing changed - skip refresh
        if displayed_set == current_files:
            # CRITICAL: Skip mtime loop when exiting browse mode - it can invalidate thumbnails
            # while the worker is loading (race on network volumes like MiscFS), leaving placeholders empty
            if getattr(self.main_window, 'browse_view_exit_in_progress', False):
                return
            # OPTIMIZATION: Skip expensive mtime checks for large result sets
            # Only check mtime if we have a reasonable number of files (< 1000)
            # For larger sets (e.g., after cmd-K search), rely on cache manager's
            # built-in stale cache detection via mtime in get_cache_key()
            if len(displayed_set) < 1000:
                # Still check for file modifications (mtime changes) and invalidate cache if needed
                # This ensures thumbnails stay up to date without full rebuild
                for image_path in displayed_set:
                    try:
                        file_mtime = os.path.getmtime(image_path)
                        metadata = self.main_window.cache_manager.get_metadata_sync(image_path)
                        if metadata and hasattr(metadata, 'modified_time'):
                            cached_mtime = metadata.modified_time
                            if cached_mtime is not None and float(cached_mtime) != float(file_mtime):
                                # File changed - invalidate its thumbnail only
                                if hasattr(self.main_window, 'thumbnail_container') and self.main_window.thumbnail_container.canvas:
                                    self.main_window.thumbnail_container.canvas.invalidate_thumbnails_for_paths([image_path])
                                self.main_window.cache_manager.clear_thumbnails_for_file(image_path)
                    except Exception:
                        pass
            # For large sets, rely on cache manager's stale detection during thumbnail loading
            return
        
        # Files changed - do efficient refresh
        self._efficient_refresh_with_changes(current_files, displayed_set)
    
    def _efficient_refresh_with_changes(self, current_files: Set[str], displayed_set: Set[str]):
        """Efficiently refresh directory when files changed - only updates what's necessary"""
        current_files_list = list(current_files)
        displayed_images = self.main_window.get_displayed_images() or []
        
        # Find added and removed files
        added_files = current_files - displayed_set
        removed_files = displayed_set - current_files
        
        # If only files were removed, use efficient removal
        if removed_files and not added_files:
            self.main_window.remove_thumbnails_for_files(removed_files)
            return
        
        # If files were added or both added/removed, need to refresh with proper sorting
        # But only rebuild thumbnails if the displayed list actually changed
        preserve_current_image = self.main_window.get_current_image_path()
        
        # Apply sorting based on current mode using centralized display ordering
        # CRITICAL: For CUSTOM and RANDOM modes, preserve existing order when possible
        # but still ensure locked files are at top
        if self.main_window.current_sort_mode in (SortMode.CUSTOM, SortMode.RANDOM) and displayed_images:
            # For CUSTOM and RANDOM: preserve existing displayed order but ensure locked files at top
            # Filter out files that no longer exist and add new files
            displayed_filtered = [f for f in displayed_images if f in current_files]
            new_files = [f for f in current_files_list if f not in displayed_set]
            
            # Combine existing (filtered) and new files
            combined_files = displayed_filtered + new_files
            
            # Use centralized function to ensure locked files are at top
            # For CUSTOM mode, this will read from .prsort and apply correct order
            # For RANDOM mode, this will shuffle unlocked files (new files will be shuffled)
            if combined_files:
                directory = os.path.dirname(combined_files[0]) if combined_files else None
                new_list = self.main_window.sorting_manager.apply_display_order(combined_files, directory)
            else:
                new_list = []
        else:
            # For other sort modes: use centralized function on all current files
            if current_files_list:
                directory = os.path.dirname(current_files_list[0])
                new_list = self.main_window.sorting_manager.apply_display_order(current_files_list, directory)
            else:
                new_list = []
        
        # Apply filter if needed
        if hasattr(self.main_window, 'filter_pattern') and self.main_window.filter_pattern:
            new_list = self.main_window.sorting_manager.filter_images_by_pattern(new_list)
        
        # Check if list actually changed
        if set(new_list) == displayed_set and new_list == displayed_images:
            # Same files, same order - no refresh needed
            return
        
        # Update displayed_images - EventBus DISPLAYED_IMAGES_CHANGED triggers ThumbnailDisplayManager
        self.main_window._set_displayed_images_with_sync(new_list, sync=True)
        
        # Update list view if in list mode
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            if hasattr(self.main_window, 'view_manager') and self.main_window.view_manager:
                self.main_window.view_manager.update_list_view()
        
        # CRITICAL: Preserve current image using file path (source of truth)
        # This MUST happen before populate_indices_arrays() to ensure highlight_index is correct
        if preserve_current_image and preserve_current_image in new_list:
            self.main_window.set_current_image_by_path(preserve_current_image, fallback_index=0)
        elif new_list:
            self.main_window.set_current_image_by_path(new_list[0], fallback_index=0)
        
        # Populate indices arrays (doesn't modify highlight_index - it's derived from current_image_path)
        self.main_window.populate_indices_arrays()
        
        # CRITICAL: Ensure highlight_index is synced from current_image_path after all updates
        # This guarantees file path is always the source of truth
        self.main_window._sync_highlight_index_from_current_image_path(new_list)
        
        # Update UI to reflect the correct highlight
        self.main_window.highlight_image()
        
        self.main_window.update_status_bar_sections()
    
    def efficient_directory_refresh(self):
        """Efficiently refresh directory by detecting added/removed files and making minimal incremental changes"""
        if not self.main_window.current_directory or not os.path.exists(self.main_window.current_directory):
            return

        # OPTIMIZATION: Skip expensive mtime/size checks for large result sets
        # Only check if we have a reasonable number of files (< 1000)
        # For larger sets (e.g., after cmd-K search), rely on cache manager's
        # built-in stale cache detection during thumbnail loading
        displayed_images = self.main_window.get_displayed_images() or []
        if len(displayed_images) < 1000:
            # TESTING - remove metadata for displayed images if they have changed date or size
            for image_path in displayed_images:
                metadata = None
                try:
                    # Get file's current mtime and size
                    file_mtime = os.path.getmtime(image_path)
                    file_size = os.path.getsize(image_path)
                    # Get cached metadata (should include date/mtime and size)
                    metadata = self.main_window.cache_manager.get_metadata_sync(image_path)
                    cached_mtime = None
                    cached_size = None
                    if metadata:
                        # Try common keys for mtime in cache
                        cached_mtime = metadata.modified_time
                        cached_size = metadata.file_size
                    # Compare, and if different, remove cache entry
                    mtime_changed = cached_mtime is not None and float(cached_mtime) != float(file_mtime)
                    size_changed = cached_size is not None and int(cached_size) != int(file_size)
                    if mtime_changed or size_changed:
                        self.main_window.cache_manager.clear_cache_for_file(image_path)
                except Exception as e:
                    # If any error (file missing, cache missing, etc), skip
                    print(f"Error removing metadata for {image_path}: {e}")
                    continue

        if hasattr(self.main_window, 'directory_loader'):
            current_files = self.main_window.directory_loader._get_current_directory_files()
        else:
            current_files = self.main_window._get_current_directory_files()
        if current_files is None:
            return
        current_files_list = list(current_files)

        # CRITICAL: Always separate locked and unlocked files first
        # Locked files must be at the top in their saved order from .prsort, regardless of sort mode
        locked_paths, unlocked_paths = self.main_window.sorting_manager._separate_locked_unlocked(current_files_list)
        
        # Sorting (only unlocked files)
        if self.main_window.current_sort_mode == SortMode.NAME:
            unlocked_paths.sort(key=lambda path: path.lower(), reverse=self.main_window.is_reversed)
        else:
            try:
                unlocked_paths.sort(key=self.main_window.sorting_manager.get_sort_key, reverse=not self.main_window.is_reversed)
            except Exception:
                unlocked_paths.sort(key=lambda p: p.lower())
        
        # Combine: locked files first (in their saved order), then unlocked files
        current_files_list = locked_paths + unlocked_paths

        self.main_window.update_status_bar_sections()
    
    def refresh_directory(self, force=False):
        """
        Refresh directory - ensures UI reflects current data.
        
        When called via cmd-R, this does a full refresh preserving current state:
        - Current file (current_image_path) is preserved
        - Current directory is refreshed from disk
        - Thumbnails are regenerated
        - Tree view is synchronized
        """
        import traceback
        if not self.main_window.current_directory:
            return
        
        # Preserve current state before refresh (for cmd-R full refresh)
        current_image_path = self.main_window.get_current_image_path()
        
        # CRITICAL: Check for specific files mode FIRST - preserve it during refresh
        # In specific files mode, refresh only the files in the specific files set
        if getattr(self.main_window, 'specific_files_active', False):
            # Refresh specific files list (remove deleted files, update thumbnails)
            # This preserves specific files mode instead of switching to directory mode
            if hasattr(self.main_window, '_refresh_specific_files_list'):
                self.main_window._refresh_specific_files_list(force=force)
            return
        
        # Check if we're in a partial thumbnail list mode (showing only selected files)
        # This happens when user selects images and presses Enter to view them as a group
        if hasattr(self.main_window, '_is_in_partial_thumbnail_mode') and self.main_window._is_in_partial_thumbnail_mode() and not force:
            # Refresh the partial list instead of resetting to full directory
            # But if force=True (e.g., from settings change), do a full refresh
            if hasattr(self.main_window, '_refresh_partial_thumbnail_list'):
                self.main_window._refresh_partial_thumbnail_list()
            return
        
        # If we're in partial mode but force=True, exit partial mode first
        if hasattr(self.main_window, '_is_in_partial_thumbnail_mode') and self.main_window._is_in_partial_thumbnail_mode() and force:
            self.main_window.specific_files_active = False
            self.main_window.window_size = None
            self.main_window.window_target_file = None
        
        # Always do a simple, reliable refresh that shows current directory contents
        # This ensures new files are always detected and displayed
        # Preserve current image path for cmd-R full refresh
        self._simple_refresh_with_limit(preserve_current_image=current_image_path)
        
        # CRITICAL: Force regenerate thumbnails after refresh to ensure thumbnails match files
        # This fixes cases where thumbnails get out of sync with their file paths
        self.main_window.generate_thumbnails(force_refresh=True)
        
        # Update list view if in list mode (generate_thumbnails updates it, but ensure it's called)
        if hasattr(self.main_window, 'current_view_mode') and self.main_window.current_view_mode == 'list':
            if hasattr(self.main_window, 'view_manager') and self.main_window.view_manager:
                self.main_window.view_manager.update_list_view()

        # cmd-R: defer rename status rescan so it runs after thumbnails load (avoids interrupting)
        if hasattr(self.main_window, 'update_rename_status') and hasattr(self.main_window, 'rename_status_manager'):
            if self.main_window.rename_status_manager.is_enabled():
                QTimer.singleShot(1500, lambda: self.main_window.update_rename_status(full_scan=True))
    
    def _simple_refresh_with_limit(self, preserve_current_image=None):
        """
        Simple refresh that just honors the current limit - no complex windowing logic
        
        Args:
            preserve_current_image: Optional path to preserve as current image during refresh
        """
        if not self.main_window.current_directory:
            return
        
        # Use preserved current image if provided, otherwise get current
        if preserve_current_image is None:
            preserve_current_image = self.main_window.get_current_image_path()
        
        # Clear any cached state that might prevent new files from being detected
        if hasattr(self.main_window, '_cached_grid_columns'):
            delattr(self.main_window, '_cached_grid_columns')
        if hasattr(self.main_window, '_cached_thumbnail_size'):
            delattr(self.main_window, '_cached_thumbnail_size')
        self.main_window.cached_container_width = None
        self.main_window.cached_container_height = None
        
        # Get all files in the directory
        if hasattr(self.main_window, 'directory_loader'):
            current_files = self.main_window.directory_loader._get_current_directory_files()
        else:
            current_files = self.main_window._get_current_directory_files()
        if not current_files:
            # Clear displayed images if no files found
            self.main_window.displayed_images = []
            self.main_window.populate_indices_arrays()
            self.main_window.clear_thumbnails()
            return
        
        original_displayed_images = self.main_window.displayed_images.copy()
        # Convert to list and sort
        current_files_list = list(current_files)
        
        # Check if .prsort file exists - if so, we should preserve custom order
        prsort_exists = False
        if self.main_window.current_directory:
            prsort_path = self.main_window.sorting_manager._get_prsort_file_path(self.main_window.current_directory)
            prsort_exists = os.path.exists(prsort_path)
        
        # Preserve random order (marked by is_browsing_at_random) - don't re-sort
        # BUT: Always filter out files that no longer exist on disk
        if self.main_window.current_sort_mode == SortMode.RANDOM and original_displayed_images:
            # Keep the random order - just filter and update if needed
            current_files_list = original_displayed_images.copy()
            # CRITICAL: Filter out files that no longer exist on disk (not just in current_files set)
            current_files_list = [f for f in current_files_list if os.path.exists(f) and f in current_files]
            # Add any new files that weren't in the original list (append to end)
            new_files = [f for f in current_files if f not in current_files_list]
            current_files_list.extend(new_files)
        else:
            # CRITICAL: Always use centralized display ordering function to ensure locked files are at top
            # This works for all sort modes including CUSTOM - locked files are always at top
            if current_files_list:
                directory = os.path.dirname(current_files_list[0])
                current_files_list = self.main_window.sorting_manager.apply_display_order(current_files_list, directory)
        
        # CRITICAL: Filter out files that no longer exist on disk before applying other filters
        # This ensures deleted files are removed even if they're in the current_files set
        current_files_list = [f for f in current_files_list if os.path.exists(f)]
        
        # Apply filter
        if hasattr(self.main_window, 'filter_pattern') and self.main_window.filter_pattern:
            current_files_list = self.main_window.sorting_manager.filter_images_by_pattern(current_files_list)
        
        # Check for pending rename path first - use it instead of current_image_path if present
        if hasattr(self.main_window, 'pending_rename_path') and self.main_window.pending_rename_path:
            current_image_path = self.main_window.pending_rename_path
            # Clear it so it's only used once
            delattr(self.main_window, 'pending_rename_path')
        else:
            # Use preserved current image if provided, otherwise get current
            current_image_path = preserve_current_image if preserve_current_image else self.main_window.get_current_image_path()
        
        try:
            limit = self.main_window.limit
            index_in_list = current_files_list.index(current_image_path)

            # Try to avoid changing the current window if current_image_path is in the already-active window
            # Find the current window: computed before as displayed_images (original_displayed_images)
            prev_start_index = None
            prev_end_index = None
            try:
                if original_displayed_images:
                    first = original_displayed_images[0]
                    last = original_displayed_images[-1]
                    prev_start_index = current_files_list.index(first)
                    prev_end_index = current_files_list.index(last) + 1  # end-exclusive
            except Exception:
                prev_start_index = None
                prev_end_index = None

            # If current_image_path is in previous window, preserve window; else, center
            if (
                original_displayed_images
                and current_image_path in original_displayed_images[:limit]
            ):
                # Windowing logic for positioning the current image in the limit window
                prev_pos = original_displayed_images.index(current_image_path)

                # By default, retain previous visible window positioning for the active image.
                start_index = max(0, index_in_list - prev_pos)
                end_index = start_index + limit

                # Make sure the current image still fits within the window
                if end_index > index_in_list:
                    start_index = max(0, index_in_list - limit + 1)
                    end_index = start_index + limit

                # Make sure the current image still fits within the window
                if end_index <= index_in_list:
                    start_index = max(0, index_in_list - limit + 1)
                    end_index = start_index + limit

                self.main_window.displayed_images = current_files_list[start_index:end_index]
                self.main_window.highlight_index = index_in_list - start_index
                index_in_list = self.main_window.highlight_index
                self.main_window.skip_images_change = False # must be false to make getattr() work
            else:
                # Center the active image in the window if possible, so it's in the middle of the windowed images,
                # unless near the start/end of the list.

                half_limit = limit // 2
                start_index = index_in_list - half_limit
                end_index = start_index + limit

                if start_index < 0:
                    start_index = 0
                    end_index = min(limit, len(current_files_list))
                elif end_index > len(current_files_list):
                    end_index = len(current_files_list)
                    start_index = max(0, end_index - limit)

                # Enhancement: shift window to show first file if possible (when showing the current image doesn't push window past end)
                if (
                    start_index > 0
                    and index_in_list < limit  # current image is in first 'limit' images
                ):
                    start_index = 0
                    end_index = min(limit, len(current_files_list))

                # Use sync helper to ensure FileDataModel consistency
                self.main_window._set_displayed_images_with_sync(current_files_list[start_index:end_index], sync=True)
                self.main_window.highlight_index = index_in_list - start_index

                self.main_window.skip_images_change = False # must be false to make getattr() work

            self.main_window.current_index = index_in_list
            self.main_window.current_image_path = current_image_path
            # Sync with FileDataModel to ensure consistency
            try:
                self.main_window._sync_to_file_data_model()
            except Exception:
                # Don't let sync errors break refresh
                pass
        except ValueError as e:
            # File not found by exact match - try normalized path comparison
            index_in_list = None
            try:
                # Check if current_image_path is None before trying to normalize it
                if current_image_path is None:
                    # If no current image path, just use the first image or keep index_in_list as None
                    index_in_list = 0 if current_files_list else None
                else:
                    current_image_path_normalized = os.path.normpath(os.path.realpath(current_image_path))
                    for idx, img_path in enumerate(current_files_list):
                        try:
                            img_path_normalized = os.path.normpath(os.path.realpath(img_path))
                        except (OSError, ValueError):
                            img_path_normalized = os.path.normpath(img_path)
                        if img_path_normalized == current_image_path_normalized or img_path == current_image_path:
                            index_in_list = idx
                            break
            except (OSError, ValueError):
                pass
            
            if index_in_list is not None:
                # Found via normalized comparison - use same logic as above
                limit = self.main_window.limit
                prev_start_index = None
                prev_end_index = None
                try:
                    if original_displayed_images:
                        first = original_displayed_images[0]
                        last = original_displayed_images[-1]
                        prev_start_index = current_files_list.index(first)
                        prev_end_index = current_files_list.index(last) + 1
                except Exception:
                    prev_start_index = None
                    prev_end_index = None
                
                if prev_start_index is not None and prev_end_index is not None \
                        and prev_start_index <= index_in_list < prev_end_index:
                    self.main_window.displayed_images = current_files_list[prev_start_index:prev_start_index + limit]
                    self.main_window.highlight_index = index_in_list - prev_start_index
                    current_files_list = self.main_window.displayed_images # DGN <-- 11/15/2025 use original displayed_images list
                else:
                    start_index = max(0, index_in_list - limit // 2)
                    end_index = min(len(current_files_list), start_index + limit)
                    start_index = max(0, end_index - limit)
                    self.main_window.displayed_images = current_files_list[start_index:end_index]
                    self.main_window.highlight_index = index_in_list - start_index
                
                self.main_window.current_index = index_in_list
                self.main_window.current_image_path = current_image_path
                self.main_window.populate_indices_arrays()
            else:
                # No match found - use first image
                if current_files_list:
                    self.main_window.displayed_images = current_files_list[:limit]
                    self.main_window.highlight_index = 0
                    self.main_window.current_index = 0
                    if self.main_window.displayed_images:
                        self.main_window.current_image_path = self.main_window.displayed_images[0]
                    self.main_window.populate_indices_arrays()
                else:
                    self.main_window.displayed_images = []
                    self.main_window.populate_indices_arrays()
        
        # Sync highlight_index from current_image_path (source of truth)
        self.main_window._sync_highlight_index_from_current_image_path()
        
        # Update status bar
        self.main_window.update_status_bar_sections()
    
    def sequential_refresh_after_browse(self):
        """Minimal refresh after browse to sync thumbnails efficiently."""
        # Skip refresh only in random mode or specific-files mode to preserve the original specific files list
        # Allow refresh in 'specific files'' mode to detect new files added externally
        if self.main_window.current_sort_mode == SortMode.RANDOM \
           or getattr(self.main_window, 'specific_files_active', False):
            return
        
        # Use the beachball fix to prevent concurrent refresh operations
        self._sequential_refresh_after_browse_impl()

    def _sequential_refresh_after_browse_impl(self):
        """Implementation of the sequential refresh after browse."""
        # If settings changed while in browse mode, do a full refresh
        if getattr(self.main_window, '_settings_changed_in_browse', False):
            self.main_window._settings_changed_in_browse = False
            self.refresh_directory(force=True)
            return
        
        # Use the existing efficient refresh method which is designed to be smooth
        # This will detect new files and update the display efficiently without flashing
        self.efficient_directory_refresh()
