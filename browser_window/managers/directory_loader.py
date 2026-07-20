#!/usr/bin/env python3
"""
Directory Loader Manager
Handles directory scanning, file loading, and directory navigation
"""

import os
from typing import List, Optional, Set
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from thumbnails.thumbnail_constants import get_image_extensions
from utils import (
    get_file_extension,
    should_preserve_window_focus,
    show_styled_question,
    show_styled_warning,
)
from sort_mode import SortMode
from event_bus import DIRECTORY_REQUESTED, DIRECTORY_LOADED
from file_data_model import normalize_file_path


def normalize_restore_image_path(path: Optional[str]) -> Optional[str]:
    """Absolute path for a saved restore file, or None if not a file."""
    if not path:
        return None
    try:
        abs_path = os.path.abspath(os.path.expanduser(path))
    except Exception:
        return None
    return abs_path if os.path.isfile(abs_path) else None


def index_of_path_in_displayed(
    images: List[str], path: Optional[str]
) -> Optional[int]:
    """Index in displayed_images for path, matching absolute or list entry form."""
    if not images or not path:
        return None
    normalized = normalize_restore_image_path(path)
    if normalized is None:
        try:
            normalized = os.path.abspath(os.path.expanduser(path))
        except Exception:
            return None
    if normalized in images:
        return images.index(normalized)
    for i, img in enumerate(images):
        try:
            if os.path.abspath(img) == normalized:
                return i
        except Exception:
            continue
    return None


def resolve_directory_active_path(
    images: List[str],
    *,
    last_file: Optional[str] = None,
    target_file: Optional[str] = None,
) -> Optional[str]:
    """Pick the image path that should be active before the first thumbnail build."""
    if not images:
        return None
    idx = index_of_path_in_displayed(images, last_file)
    if idx is not None:
        return images[idx]
    idx = index_of_path_in_displayed(images, target_file)
    if idx is not None:
        return images[idx]
    return images[0]


def resolve_restore_image_index(
    images: List[str],
    *,
    last_file: Optional[str] = None,
    target_file: Optional[str] = None,
    current_index: int = 0,
    image_indices: Optional[List[int]] = None,
) -> int:
    """Index of the image to show when restoring browse or view mode at startup."""
    if not images:
        return 0
    idx = index_of_path_in_displayed(images, last_file)
    if idx is not None:
        return idx
    idx = index_of_path_in_displayed(images, target_file)
    if idx is not None:
        return idx
    if image_indices:
        try:
            return image_indices.index(current_index)
        except (ValueError, AttributeError, TypeError):
            pass
    if 0 <= current_index < len(images):
        return current_index
    return min(max(current_index, 0), len(images) - 1)


class DirectoryLoader:
    """Manages directory loading and file scanning operations"""
    
    def __init__(self, main_window):
        """
        Initialize the directory loader
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
        # Subscribe to directory load requests via event bus
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            main_window.event_bus.subscribe(DIRECTORY_REQUESTED, self._on_directory_requested)
    
    def _scan_directory_efficiently(self, directory: str) -> List[str]:
        """Scan directory efficiently using os.scandir instead of os.listdir"""
        if not os.path.exists(directory) or not os.path.isdir(directory):
            return []

        image_files = []

        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_file():
                        if get_file_extension(entry.name) in get_image_extensions():
                            image_files.append(normalize_file_path(entry.path))
        except PermissionError:
            raise
        except OSError as e:
            # macOS Desktop/Documents often return EPERM without Full Disk Access
            if getattr(e, "errno", None) in (1, 13):
                raise PermissionError(directory) from e
            return []

        return image_files

    def _get_current_directory_files(self) -> Optional[Set[str]]:
        """Get current image files in directory efficiently"""
        if not self.main_window.current_directory or not os.path.exists(self.main_window.current_directory):
            return None

        try:
            image_files = self._scan_directory_efficiently(self.main_window.current_directory)
            return set(image_files)
        except PermissionError:
            return None
        except Exception:
            return None

    def _handle_directory_listing_denied(self, directory: str) -> None:
        """Empty UI with a clear message when macOS blocks directory listing (e.g. Desktop)."""
        self.main_window._directory_listing_denied = True
        self.main_window.displayed_images = []
        self.main_window.clear_thumbnails()
        self.main_window.populate_indices_arrays()
        self.main_window._current_highlighted_file_directory = self.main_window.current_directory
        self.main_window.update_status_bar_sections()
        self.main_window.status_bar_manager.show_message(
            "Access denied — enable Full Disk Access in System Settings → Privacy & Security",
            duration=8000,
        )
        show_styled_warning(
            self.main_window,
            "Folder Access Denied",
            f"macOS prevented Prowser from listing images in:\n\n{directory}\n\n"
            "Grant Full Disk Access to the app you use to launch Prowser "
            "(Prowser.app, Terminal, or iTerm) under "
            "System Settings → Privacy & Security → Full Disk Access, then reopen this folder.",
        )
    
    def count_total_files_in_directory(self, directory: str) -> int:
        """Count total image files in directory that match the current filter pattern"""
        if not directory or not os.path.exists(directory):
            return 0
        
        total_count = 0
        
        try:
            image_files = self._scan_directory_efficiently(directory)
            
            # Apply filter pattern if one is active
            if hasattr(self.main_window, 'filter_pattern') and self.main_window.filter_pattern:
                from config import ImageBrowserConfig
                match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(self.main_window.filter_pattern)
                import fnmatch
                for image_file in image_files:
                    filename = os.path.basename(image_file)
                    if fnmatch.fnmatch(filename.lower(), match_pattern.lower()):
                        total_count += 1
            else:
                total_count = len(image_files)
        except Exception:
            total_count = 0
        
        return total_count
    
    def get_full_sorted_filtered_list(self) -> List[str]:
        """Get the full list of files in current directory, sorted and filtered according to current settings.
        This is the complete list before any limit is applied."""
        if not self.main_window.current_directory:
            return []
        
        current_files = self._get_current_directory_files()
        if current_files is None:
            return []
        
        current_files_list = list(current_files)
        
        # CRITICAL: Always use centralized display ordering to ensure locked files are at top
        if self.main_window.current_sort_mode == SortMode.RANDOM and self.main_window.displayed_images:
            current_files_list = self.main_window.displayed_images.copy()
            current_files_list = [f for f in current_files_list if os.path.exists(f) and f in current_files]
            new_files = [f for f in current_files if f not in current_files_list]
            current_files_list.extend(new_files)
        else:
            current_files_list = self.main_window.sorting_manager.apply_display_order(
                current_files_list,
                self.main_window.current_directory,
            )
        
        if hasattr(self.main_window, 'filter_pattern') and self.main_window.filter_pattern:
            current_files_list = self.main_window.sorting_manager.filter_images_by_pattern(current_files_list)
        
        return current_files_list
    
    def _browse_restore_image_index(self) -> int:
        """Index of the image to show when restoring browse at startup."""
        images = getattr(self.main_window, 'displayed_images', None) or []
        return resolve_restore_image_index(
            images,
            last_file=getattr(self.main_window, '_startup_restore_last_file', None),
            target_file=getattr(self.main_window, 'target_file', None),
            current_index=getattr(self.main_window, 'current_index', 0),
            image_indices=getattr(self.main_window, 'image_indices', None),
        )

    def _resolve_directory_active_path(self, current_files_list: List[str]) -> Optional[str]:
        """Pick the image that should be active before the first thumbnail build."""
        return resolve_directory_active_path(
            current_files_list,
            last_file=getattr(self.main_window, '_startup_restore_last_file', None),
            target_file=getattr(self.main_window, 'target_file', None),
        )

    def _on_directory_requested(self, path, external_load=False, refresh_mode=False):
        """Handle DIRECTORY_REQUESTED event - performs the actual directory load"""
        self._do_load_directory(path, external_load, refresh_mode)

    def load_directory(self, directory: str, external_load: bool = False, refresh_mode: bool = False):
        """Request directory load via event bus. Subscribers (including self) will handle it."""
        if hasattr(self.main_window, 'event_bus') and self.main_window.event_bus:
            self.main_window.event_bus.emit(DIRECTORY_REQUESTED, (directory, external_load, refresh_mode))
        else:
            self._do_load_directory(directory, external_load, refresh_mode)

    def _do_load_directory(self, directory: str, external_load: bool = False, refresh_mode: bool = False):
        """Load images from directory with ULTRA-FAST startup"""
        
        # Interrupt any ongoing thumbnail loading before loading new directory
        if hasattr(self.main_window, '_interrupt_thumbnail_loading'):
            self.main_window._interrupt_thumbnail_loading()

        if getattr(self.main_window, 'convert_conflict_context', None):
            self.main_window.convert_conflict_context = None
            if hasattr(self.main_window, 'update_convert_conflict_auto_rename_button'):
                self.main_window.update_convert_conflict_auto_rename_button()
        
        if not os.path.exists(directory) or not os.path.isdir(directory):
            show_styled_warning(self.main_window, "Invalid Directory", 
                              f"Directory does not exist: {directory}")
            return
        
        if external_load:
            # Restart background CLIP process with this directory as priority
            if hasattr(self.main_window, 'background_clip_controller') and self.main_window.background_clip_controller:
                if self.main_window.background_clip_controller.enabled:
                    self.main_window.background_clip_controller.restart_with_priority_directory(directory)
            
            # Set flag in file_tree_handler to skip rebuild when opening externally
            # Note: The flag will be cleared by the timer in request_directory_opening
            # We don't set a timer here to avoid GIL deadlock from multiple QTimer.singleShot calls
            if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
                self.main_window.file_tree_handler.user_requested_directory = directory
            # If we're not in thumbnail mode and loading a directory externally (e.g., from tree click),
            # exit the current mode first so the user can see the thumbnails
            # Note: Preserve list view mode - don't exit it
            if (
                not getattr(self.main_window, '_defer_browse_restore', False)
                and self.main_window.current_view_mode != 'thumbnail'
                and self.main_window.current_view_mode != 'list'
            ):
                if self.main_window.current_view_mode == 'browse':
                    self.main_window.view_manager.close_browse_view()
                elif self.main_window.current_view_mode == 'slideshow':
                    self.main_window.slideshow_manager.stop_slideshow()
                elif self.main_window.current_view_mode == 'slideshow2':
                    self.main_window.slideshow2_manager.stop_slideshow2()
                elif self.main_window.current_view_mode == 'slideshow3':
                    self.main_window.slideshow3_manager.stop_slideshow3()
            # When loading a directory externally, clear target_file to prevent browse view from opening
            # This ensures directories always open in thumbnail mode, not browse mode
            if getattr(self.main_window, '_loading_directory_mode', False):
                self.main_window.target_file = None

        # Directory browsing deactivates specific-files mode and window mode
        self.main_window.specific_files_active = False
        self.main_window.clear_reference_graph_presentation()
        self.main_window.window_size = None
        self.main_window.window_target_file = None
        
        self.main_window.current_directory = directory
        self.main_window._directory_listing_denied = False
        self.main_window.setWindowTitle(f"Prowser - {os.path.basename(directory)}")
        
        current_files = self._get_current_directory_files()
        if current_files is None:
            try:
                self._scan_directory_efficiently(directory)
            except PermissionError:
                self._handle_directory_listing_denied(directory)
                return
            # Handle error reading directory: set displayed_images to empty and update status bar
            self.main_window.displayed_images = []
            self.main_window.populate_indices_arrays()
            self.main_window._current_highlighted_file_directory = self.main_window.current_directory
            self.main_window.update_status_bar_sections()
            self.main_window.status_bar_manager.show_message(f"Error reading directory {directory}")
            return
        
        self.main_window._full_directory_files = current_files
        
        current_files_list = list(current_files)
        
        # Clean up orphaned lock entries
        if hasattr(self.main_window, 'lock_manager') and self.main_window.lock_manager:
            self.main_window.lock_manager.cleanup_orphaned_locks(directory)
        
        # Check if .prsort file exists - only use it if custom sort flag is already set
        prsort_path = self.main_window.sorting_manager._get_prsort_file_path(directory)
        prsort_exists = os.path.exists(prsort_path)
        
        # Use centralized display ordering function
        current_files_list = self.main_window.sorting_manager.apply_display_order(current_files_list, directory)
        
        # Leaving duplicate/similar grouped view: a normal directory load is not a duplicate search
        if self.main_window.current_sort_mode == SortMode.DUPLICATES:
            self.main_window.current_sort_mode = SortMode.DATE
            self.main_window.is_reversed = False
            self.main_window.save_sorting_settings()
        
        # Apply filter pattern - if no files match, keep empty list
        if hasattr(self.main_window, 'filter_pattern') and self.main_window.filter_pattern:
            current_files_list = self.main_window.sorting_manager.filter_images_by_pattern(current_files_list)
        
        self.main_window._batch_directory_load = True
        try:
            self.main_window.file_data_model.set_displayed_images(
                current_files_list, notify=True, validate_exists=False
            )

            # Clear thumbnails if we have no images to ensure empty state is shown
            if not self.main_window.displayed_images:
                self.main_window.clear_thumbnails()

            # Track the directory of the first displayed file for auto-open fallback
            if self.main_window.displayed_images:
                self.main_window._current_highlighted_file_directory = os.path.dirname(
                    self.main_window.displayed_images[0]
                )
            else:
                # When directory is empty, track the current directory itself
                self.main_window._current_highlighted_file_directory = self.main_window.current_directory

            self.main_window.populate_indices_arrays()

            active_path = self._resolve_directory_active_path(current_files_list)
            if active_path and active_path in self.main_window.displayed_images:
                try:
                    target_image_index = self.main_window.displayed_images.index(active_path)
                    self.main_window.highlight_index = self.main_window.image_indices.index(
                        target_image_index
                    )
                    self.main_window.current_index = target_image_index
                    self.main_window._set_current_image_path_with_sync(active_path)
                except (ValueError, IndexError):
                    self.main_window.highlight_index = 0
                    self.main_window.current_index = 0
                    self.main_window._set_current_image_path_with_sync(
                        self.main_window.displayed_images[0]
                    )
            elif self.main_window.displayed_images:
                self.main_window.highlight_index = 0
                self.main_window.current_index = 0
                self.main_window._set_current_image_path_with_sync(
                    self.main_window.displayed_images[0]
                )
        finally:
            self.main_window._batch_directory_load = False

        try:
            self.main_window.generate_thumbnails(force_refresh=refresh_mode)
        except Exception:
            import traceback

            traceback.print_exc()

        if getattr(self.main_window, '_defer_browse_restore', False):
            self.main_window._loading_directory_mode = False
            image_index = self._browse_restore_image_index()
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager.finish_browse_startup_restore(image_index)
        
        # If in list view mode, ensure list view is updated and visible
        if self.main_window.current_view_mode == 'list':
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager.update_list_view()
            # Ensure list view is visible in stacked widget
            if hasattr(self.main_window, 'stacked_widget'):
                # List view is index 2
                self.main_window.stacked_widget.setCurrentIndex(2)
        
        # Emit DIRECTORY_LOADED - subscribers handle status bar, menu, tree, cache, etc.
        displayed_count = len(self.main_window.displayed_images) if self.main_window.displayed_images else 0
        if hasattr(self.main_window, 'event_bus') and self.main_window.event_bus:
            self.main_window.event_bus.emit(DIRECTORY_LOADED, (directory, displayed_count, external_load))
    
    def _check_and_open_last_known_directory(self):
        """Check if we should automatically open the last known directory when no thumbnails are displayed"""
        # Only proceed if we're in thumbnail mode
        if self.main_window.current_view_mode != 'thumbnail':
            return
        
        # Get the last known directory from the most recently highlighted image
        last_known_directory = self._get_last_known_directory()
        if not last_known_directory:
            return
        
        # Check if the directory exists and has image files
        if not os.path.exists(last_known_directory):
            return
        
        # Check if there are image files in the directory
        try:
            files = os.listdir(last_known_directory)
            image_extensions = get_image_extensions()
            image_files = [f for f in files if get_file_extension(f) in image_extensions]
            if not image_files:
                return
        except (OSError, PermissionError):
            return
        
        # Add a small delay to prevent infinite loops and allow UI to settle
        QTimer.singleShot(100, lambda: self._open_last_known_directory(last_known_directory))
    
    def _get_last_known_directory(self):
        """Get the last known directory from the currently highlighted file"""
        return getattr(self.main_window, '_current_highlighted_file_directory', None)
    
    def _open_last_known_directory(self, directory):
        """Open the last known directory (simulate cmd-O)"""
        # Prevent infinite loops by checking if we're already in the process of opening a directory
        if hasattr(self.main_window, '_opening_last_directory') and self.main_window._opening_last_directory:
            return
        
        # Set flag to prevent loops
        self.main_window._opening_last_directory = True
        
        try:
            # Save current state before opening new directory
            self.main_window.directory_stack_history_handler.save_current_state("directory_loader._open_last_known_directory")
            
            # Preserve current limits and filters (don't clear them)
            # Load the directory with current settings
            self._do_load_directory(directory)
            
            # Update file tree root
            if self.main_window.file_tree_handler.is_tree_initialized():
                self.main_window.file_tree_handler.update_root_directory(directory)
                
        except Exception as e:
            pass
        finally:
            # Clear the flag after a delay to allow the directory loading to complete
            QTimer.singleShot(1000, lambda: setattr(self.main_window, '_opening_last_directory', False))
    
    def load_specific_files(
        self,
        file_paths: List[str],
        external_load: bool = False,
        force_specific_files_grid: bool = False,
        skip_filter_pattern: bool = False,
    ):
        """Load specific image files instead of scanning a directory.
        When force_specific_files_grid is True with a single file, load as a one-item specific-files thumbnail grid
        (instead of directory-window browse via load_file_with_directory_thumbnails).
        When skip_filter_pattern is True, show every requested path even if it does not match filter_pattern."""
        if not file_paths:
            return

        # Interrupt any ongoing thumbnail loading before loading new files (same as directory load)
        if hasattr(self.main_window, '_interrupt_thumbnail_loading'):
            self.main_window._interrupt_thumbnail_loading()

        # CRITICAL: If loading files from multiple directories and sort mode is EXIF/other, force CUSTOM mode
        # This handles CNN recursive search where sort mode might not be set correctly
        if len(file_paths) > 1:
            directories = set(os.path.dirname(path) for path in file_paths if os.path.exists(path))
            if len(directories) > 1:
                # Multiple directories - this is likely CNN recursive search
                current_mode = getattr(self.main_window, 'current_sort_mode', None)
                if current_mode and current_mode not in (SortMode.RANDOM, SortMode.CUSTOM, SortMode.DUPLICATES):
                    self.main_window.current_sort_mode = SortMode.CUSTOM
                    # Clear EXIF and duplicate sections
                    if hasattr(self.main_window, 'exif_date_sections'):
                        self.main_window.exif_date_sections = []
                    if hasattr(self.main_window, 'exif_section_expanded'):
                        self.main_window.exif_section_expanded = {}
                    if hasattr(self.main_window, 'duplicate_sections'):
                        self.main_window.duplicate_sections = []
                    if hasattr(self.main_window, 'deleted_file_placeholders'):
                        self.main_window.deleted_file_placeholders.clear()
                        if hasattr(self.main_window, '_emit_deleted_placeholders_changed'):
                            self.main_window._emit_deleted_placeholders_changed()
        
        # Clear any existing windowing context when loading new files
        # This prevents the old windowing state from interfering with the new files
        if hasattr(self.main_window, 'window_target_file'):
            self.main_window.window_target_file = None
        if hasattr(self.main_window, 'window_size'):
            self.main_window.window_size = None
        
        base_directory = os.path.dirname(file_paths[0])
        self.main_window.current_directory = base_directory
        
        if len(file_paths) == 1 and not force_specific_files_grid:
            # Use the windowing logic for single file loads
            target_file = file_paths[0]
            self.main_window.clear_reference_graph_presentation()
            self.load_file_with_directory_thumbnails(
                target_file,
                external_load=external_load,
                skip_filter_pattern=skip_filter_pattern,
            )
            return
        
        # Non-reference specific-files loads clear graph presentation unless already set
        if not getattr(self.main_window, 'reference_graph_active', False):
            self.main_window.clear_reference_graph_presentation()
        
        # Activate specific-files mode when multiple explicit files are provided (or single-file forced grid)
        # Clear window mode when loading specific files (not window mode)
        self.main_window.specific_files_active = len(file_paths) > 1 or force_specific_files_grid
        self.main_window.window_size = None
        self.main_window.window_target_file = None

        if len(file_paths) == 1:
            title = f"Prowser - {os.path.basename(file_paths[0])}"
        else:
            title = f"Prowser - {len(file_paths)} images"
        self.main_window.setWindowTitle(title)
        
        self.main_window.clear_thumbnails()
        
        self.main_window.displayed_images = file_paths.copy()
        
        # Don't override name sorting - respect user's sort settings
        
        if (
            not skip_filter_pattern
            and hasattr(self.main_window, 'filter_pattern')
            and self.main_window.filter_pattern
        ):
            self.main_window.displayed_images = self.main_window.sorting_manager.filter_images_by_pattern(self.main_window.displayed_images)
            if not self.main_window.displayed_images:
                # Handle no matching images: set displayed_images to empty and update status bar
                self.main_window.displayed_images = []
                self.main_window.populate_indices_arrays()
                self.main_window.update_status_bar_sections()
                self.main_window.status_bar_manager.show_message(f"No images found matching pattern '{self.main_window.filter_pattern}' in specified files")
                return
        
        # CRITICAL: Use centralized display ordering when from a single directory
        # Locked files must ALWAYS be at the top in their saved order, regardless of sort mode
        # BUT: Skip reordering for RANDOM, CUSTOM, and DUPLICATES modes (order is already correct)
        directories = set(os.path.dirname(path) for path in self.main_window.displayed_images)
        if len(directories) == 1:
            # Single directory: use centralized display ordering function
            # Skip for CUSTOM/RANDOM/DUPLICATES modes to preserve search result ordering
            if self.main_window.current_sort_mode not in (SortMode.RANDOM, SortMode.CUSTOM, SortMode.DUPLICATES):
                directory = directories.pop()
                self.main_window.displayed_images = self.main_window.sorting_manager.apply_display_order(
                    self.main_window.displayed_images, 
                    directory
                )
        else:
            # Multiple directories: can't apply locked file ordering across directories
            # But still use centralized display ordering for consistency
            # Skip sorting for RANDOM, CUSTOM, and DUPLICATES modes (order is already correct)
            if self.main_window.current_sort_mode not in (SortMode.RANDOM, SortMode.CUSTOM, SortMode.DUPLICATES):
                # Use centralized display ordering - it will handle locked files per directory
                # For multiple directories, locked files will be at top within their own directory
                directory = os.path.dirname(self.main_window.displayed_images[0]) if self.main_window.displayed_images else None
                if directory:
                    self.main_window.displayed_images = self.main_window.sorting_manager.apply_display_order(
                        self.main_window.displayed_images, 
                        directory
                    )
        
        # Update current_directory to reflect the directory of the first displayed image
        # This ensures current_directory matches displayed_images[0] after filtering/sorting
        if self.main_window.displayed_images:
            self.main_window.current_directory = os.path.dirname(self.main_window.displayed_images[0])

        if getattr(self.main_window, 'reference_graph_active', False):
            self.main_window.set_reference_graph_presentation(
                True, self.main_window.displayed_images
            )
        
        self.main_window.populate_indices_arrays()
        
        # CRITICAL: Preserve current_image_path if it exists in the new file list
        # This ensures the same image file is highlighted after search, not just index 0
        # HOWEVER: For CNN similarity searches (recursive), we skip this restoration because
        # the search code will set the active image to the first non-locked file after locked files are moved to top.
        # We detect CNN searches by checking if we're loading multiple files and sort mode is CUSTOM
        # (which is set before refresh_from_configuration for CNN searches)
        # Check conditions for CNN search detection
        has_multiple_files = len(file_paths) > 1
        has_sort_mode = hasattr(self.main_window, 'current_sort_mode')
        sort_mode_is_custom = has_sort_mode and self.main_window.current_sort_mode == SortMode.CUSTOM
        has_specific_files_flag = hasattr(self.main_window, 'specific_files_active')
        specific_files_is_active = has_specific_files_flag and self.main_window.specific_files_active
        
        is_cnn_search = (has_multiple_files and has_sort_mode and sort_mode_is_custom and 
                        has_specific_files_flag and specific_files_is_active)
        
        saved_current_image_path = self.main_window.get_current_image_path()
        
        if not is_cnn_search and saved_current_image_path and saved_current_image_path in self.main_window.displayed_images:
            # The original image is in the results - highlight it by setting path (source of truth)
            self.main_window.set_current_image_by_path(saved_current_image_path, fallback_index=0)
        else:
            # Original image not in results - default to first image
            self.main_window.highlight_index = 0
            self.main_window.current_index = 0
            if self.main_window.displayed_images:
                self.main_window._set_current_image_path_with_sync(self.main_window.displayed_images[0])
        
        # Preserve sort direction when restoring from history (state was restored before this call)
        if not getattr(self.main_window, 'restoring_from_history', False):
            self.main_window.is_reversed = False
        
        # Find the correct image to highlight and show
        target_image_index = 0
        if self.main_window.target_file and self.main_window.target_file in self.main_window.displayed_images:
            try:
                target_image_index = self.main_window.displayed_images.index(self.main_window.target_file)
                self.main_window.highlight_index = target_image_index
                self.main_window.current_index = target_image_index
                self.main_window.current_image_path = self.main_window.target_file
            except (ValueError, IndexError):
                pass
        
        # Set flag to prevent scroll-based thumbnail restarts during initial load
        # This prevents recursive loops after opening new levels (e.g., similarity search)
        self.main_window._initial_thumbnail_load = True
        
        self.main_window.generate_thumbnails(force_refresh=True)
        
        # Clear the flag after a delay to allow normal scroll-based restarts
        # Use a delay to ensure thumbnails are initialized before allowing scroll restarts
        QTimer.singleShot(500, lambda: setattr(self.main_window, '_initial_thumbnail_load', False))
        
        self.main_window.update_status_bar_sections()
        self.main_window.update_status_bar_sections()
        self.main_window.reset_browse_view_exit_tracking()
        
        # Update menu states to ensure shortcuts are properly enabled/disabled
        if hasattr(self.main_window, 'menu_manager'):
            self.main_window.menu_manager.update_search_menu_states()
        
        # Only auto-open browse view for single file if not loading a directory
        if (len(self.main_window.displayed_images) == 1 and not getattr(self.main_window, '_loading_directory_mode', False)
                and not force_specific_files_grid):
            QTimer.singleShot(50, lambda: self.main_window.view_mode_manager.open_browse_view(self.main_window.current_index))
        
        # Don't steal focus - let Qt handle tab navigation naturally
        self.main_window.activateWindow()
        self.main_window.raise_()
        
        # Update file tree highlighting when specific files are loaded
        if self.main_window.file_tree_handler.is_tree_initialized():
            # Use current_directory which should be set by now (this is called after load_directory completes)
            if hasattr(self.main_window, 'current_directory') and self.main_window.current_directory:
                self.main_window.file_tree_handler._highlight_directory_in_tree(self.main_window.current_directory)
            # Apply current filter pattern to file tree
            self.main_window.file_tree_handler.apply_filter_pattern(self.main_window.filter_pattern)
            
            # Update file tree root to show the directory of the first file
            if self.main_window.displayed_images:
                first_file_dir = os.path.dirname(self.main_window.displayed_images[0])
                self.main_window.file_tree_handler.update_root_directory(first_file_dir)
    
    def load_file_with_directory_thumbnails(
        self,
        target_file: str,
        external_load: bool = False,
        skip_filter_pattern: bool = False,
    ):
        """Load a specific file in browse while building thumbnails from its directory in the background"""
        if not target_file or not os.path.exists(target_file):
            show_styled_warning(self.main_window, "Invalid File", 
                              f"File does not exist: {target_file}")
            return
        
        # Switch to browse view immediately to prevent showing thumbnails first
        # This ensures single file loads go directly to browse without flashing thumbnails
        switch_to_browse_view = self.main_window.current_view_mode != 'browse'
        if switch_to_browse_view:
            self.main_window.stacked_widget.setCurrentIndex(1)  # Switch to browse view
            self.main_window.current_view_mode = 'browse'
            self.main_window.manage_sidebar_visibility_for_view_mode('browse')
            # Set up browse view state immediately
            self.main_window.browse_view_action.setEnabled(False)
            if hasattr(self.main_window, 'image_container'):
                available_size = self.main_window.get_effective_display_size()
                self.main_window.image_container.resize(available_size)
            if hasattr(self.main_window, 'view_manager'):
                self.main_window.view_manager._setup_cursor_manager()
            
            # Prime and enable menu keys for view change
            if hasattr(self.main_window, 'menu_manager'):
                self.main_window.menu_manager.prime_menu_keys_for_view_change()
        
        # Single-file browse with directory thumbnails is not specific-files mode or window mode
        self.main_window.specific_files_active = False
        self.main_window.window_size = None
        self.main_window.window_target_file = None

        directory = os.path.dirname(target_file)
        self.main_window.current_directory = directory
        
        self.main_window.setWindowTitle(f"Prowser - {os.path.basename(target_file)}")
        
        all_images = self._scan_directory_efficiently(directory)
        
        # Preserve name sorting and other modes across directory navigation
        
        if not all_images:
            return
        
        if (
            not skip_filter_pattern
            and hasattr(self.main_window, 'filter_pattern')
            and self.main_window.filter_pattern
        ):
            all_images = self.main_window.sorting_manager.filter_images_by_pattern(all_images)
            if not all_images:
                self.main_window.status_bar_manager.show_message(f"No images found matching pattern '{self.main_window.filter_pattern}' in directory {directory}")
                return
        
        if not all_images:
            self.main_window.status_bar_manager.show_message("No images found in directory")
            return
        
        # Apply correct sorting based on saved settings
        # Handle random mode by restoring to date sorting as requested
        if self.main_window.current_sort_mode == SortMode.RANDOM:
            # Restore random to date sorting as requested
            # Clear random mode - handled by setting current_sort_mode
            self.main_window.save_sorting_settings()
        
        # Leaving duplicate/similar grouped view when opening a file with directory thumbnails
        if self.main_window.current_sort_mode == SortMode.DUPLICATES:
            self.main_window.current_sort_mode = SortMode.DATE
            self.main_window.is_reversed = False
            self.main_window.save_sorting_settings()
        
        # Use centralized display ordering function
        directory_for_sort = os.path.dirname(all_images[0]) if all_images else None
        if directory_for_sort:
            all_images = self.main_window.sorting_manager.apply_display_order(all_images, directory_for_sort)
        
        if target_file not in all_images:
            all_images.insert(0, target_file)
        
        self.main_window.displayed_images = all_images
        self.main_window.populate_indices_arrays()
        
        # Handle target file positioning
        try:
            target_image_index = self.main_window.displayed_images.index(target_file)
            self.main_window.highlight_index = self.main_window.image_indices.index(target_image_index)
            self.main_window.current_index = target_image_index
            # Set current_image_path for future windowing operations
            # Use sync method to ensure proper synchronization with FileDataModel
            self.main_window._set_current_image_path_with_sync(target_file)
        except (ValueError, IndexError):
            self.main_window.highlight_index = 0
            self.main_window.current_index = 0
            target_image_index = 0
        
        # If we switched to browse view, display the image immediately to prevent showing thumbnails
        if switch_to_browse_view and self.main_window.current_view_mode == 'browse':
            # Display the image immediately without waiting for open_browse_view
            self.main_window.show_image(self.main_window.current_image_path, self.main_window.current_index)
        
        # Refresh the thumbnail display after windowing changes
        self.main_window.update_status_bar_sections()
        
        # Update file tree highlighting when specific file is loaded
        if self.main_window.file_tree_handler.is_tree_initialized():
            self.main_window.file_tree_handler.highlight_current_file()
            # Apply current filter pattern to file tree
            self.main_window.file_tree_handler.apply_filter_pattern(self.main_window.filter_pattern)
            
            # Update file tree root to show the directory of the target file
            self.main_window.file_tree_handler.update_root_directory(directory)
        
        # Pre-load the target image into cache to avoid 5-second delay
        # Only pre-load when opening browse view, not thumbnail view
        # This prevents loading large full images into memory when only viewing thumbnails
        if (hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager and 
            self.main_window.current_view_mode == 'browse'):
            try:
                # Pre-load the target image with EXIF correction into cache
                from exif.exif_image_loader import load_image_with_exif_correction
                ignore_exif = getattr(self.main_window, 'ignore_exif_rotation', False)
                pixmap = load_image_with_exif_correction(target_file, ignore_exif=ignore_exif)
                if pixmap and not pixmap.isNull():
                    # Cache it if not too large (limit to reasonable memory usage)
                    if pixmap.width() * pixmap.height() < 8000000:  # ~8MP limit
                        self.main_window.cache_manager.cache_fullimage_sync(target_file, pixmap)
            except Exception:
                pass  # Ignore cache pre-loading errors
        
        # For external loads (from tree), go directly to browse without delay
        # to avoid showing thumbnail view briefly
        if external_load:
            self.main_window.view_mode_manager.open_browse_view(target_image_index)
        else:
            QTimer.singleShot(50, lambda: self.main_window.view_mode_manager.open_browse_view(target_image_index))
        
        if not should_preserve_window_focus(self.main_window):
            self.main_window.activateWindow()
            self.main_window.raise_()
    
    def open_specific_file(self, file_path: str):
        """Open a specific file when received from macOS file association"""
        if not file_path or not os.path.exists(file_path):
            return
        
        # Check if it's an image file
        if get_file_extension(file_path) not in get_image_extensions():
            return
        
        # Clear any existing windowing context when opening a new file
        # This prevents the old windowing state from interfering with the new file
        if hasattr(self.main_window, 'window_target_file'):
            self.main_window.window_target_file = None
        if hasattr(self.main_window, 'window_size'):
            self.main_window.window_size = None
        
        # Load the specific file with directory thumbnails to keep tree/canvas in sync
        # This ensures the tree highlights and scrolls to the file as expected
        self.load_file_with_directory_thumbnails(file_path, external_load=True)
        
        if not should_preserve_window_focus(self.main_window):
            self.main_window.activateWindow()
            self.main_window.raise_()
