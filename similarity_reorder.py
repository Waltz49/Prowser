#!/usr/bin/env python3
"""CNN similarity and CLIP reorder flows (moved from ImageBrowserWindow)."""

import fnmatch
import os

from PySide6.QtCore import QTimer

from path_exclusions import _get_excluded_paths, _is_excluded_path
from sort_mode import SortMode
from utils import (
    handle_filter_pattern_mismatch,
    show_styled_information,
    show_styled_warning,
    is_root_or_system_volume,
)


def reorder_images_by_similarity(mw):
    """Reorder images by similarity to the reference image(s), with a progress bar.
    If multiple images are selected, uses all selected images as the reference group.
    Otherwise, uses the current image as the reference.
    Always uses the similarity metric from settings (never CLIP)."""
    
    # Lazy initialize UI helper if needed
    mw._ensure_cnn_ui_helper_initialized()
    
    # Mark cache activity to reset unload timer
    if getattr(mw, 'cnn_image_similarity_sorter', None) and mw.cnn_image_similarity_sorter.feature_cache:
        mw.cnn_image_similarity_sorter.feature_cache.mark_cache_activity()
    
    # Ask user for recursive option FIRST (before loading torch/model)
    settings = mw.config.load_settings()
    saved_recursive = settings.get('cnn_recursive', False)
    current_dir = mw.get_current_search_directory()
    dialog = mw.cnn_similarity_ui_helper.create_similarity_search_dialog(
        directory=current_dir,
        recursive_default=saved_recursive
    )
    
    # If tree had focus when invoked and a directory was provided, check checkbox and set directory field
    tree_had_focus = getattr(mw, '_tree_had_focus_when_invoked', False)
    if tree_had_focus and current_dir and os.path.isdir(current_dir):
        if hasattr(dialog, 'dir_checkbox'):
            dialog.dir_checkbox.setChecked(True)
        if hasattr(dialog, 'dir_input'):
            dialog.dir_input.setText(current_dir)
    
    if not dialog.exec():
        # User canceled dialog - remain in current mode (browse or thumbnail)
        return
    
    # User accepted dialog - exit list view if in list mode (prevents hanging)
    if mw.current_view_mode == 'list':
        mw.toggle_list_view()  # Exit list view
        # Process events to ensure view switch completes
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
    
    # User accepted dialog - switch to thumbnail mode if in browse mode
    if mw.current_view_mode == 'browse':
        mw.close_browse_view()
        # Process events to ensure view switch completes
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
    
    recursive = dialog.recursive_checkbox.isChecked()
    dir_checkbox_checked = dialog.dir_checkbox.isChecked() if hasattr(dialog, 'dir_checkbox') else False
    search_directory = dialog.dir_input.text().strip() if dir_checkbox_checked and hasattr(dialog, 'dir_input') else None
    
    # Save the recursive setting and directory settings to config for next time
    mw.config.update_setting('cnn_recursive', recursive)
    if hasattr(dialog, 'dir_checkbox'):
        mw.config.update_setting('cnn_search_dir_enabled', dialog.dir_checkbox.isChecked())
    if hasattr(dialog, 'dir_input'):
        mw.config.update_setting('cnn_search_dir', dialog.dir_input.text().strip())
    
    # Get reference images BEFORE collecting search images
    # Use selected images if multiple are selected, otherwise use current image
    ref_image_path = None
    
    # CRITICAL: Ensure current_image_path is synchronized with highlight_index before using it
    if (getattr(mw, 'displayed_images', None) and 
        0 <= mw.highlight_index < len(mw.displayed_images)):
        expected_path = mw.displayed_images[mw.highlight_index]
        if mw.current_image_path != expected_path:
            mw.current_image_path = expected_path
    
    # Get reference images from current displayed images (before recursive search)
    current_displayed = mw.get_displayed_images()
    if mw.selected_files and len(mw.selected_files) > 1:
        # Filter selected files to only those that are valid images in displayed_images
        valid_selected = [
            path for path in mw.selected_files
            if path in current_displayed
            and os.path.exists(path)
            and path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
        ]
        if valid_selected:
            ref_image_path = valid_selected
        else:
            ref_image_path = mw.current_image_path
    else:
        ref_image_path = mw.current_image_path
    
    # Normalize reference image path(s) to ensure consistent path format
    # Use realpath to resolve symlinks and ensure consistent normalization
    if isinstance(ref_image_path, list):
        normalized_ref_paths = []
        for path in ref_image_path:
            if path and os.path.exists(path):
                try:
                    normalized = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
                    normalized_ref_paths.append(normalized)
                except (OSError, ValueError):
                    # If normalization fails, try without realpath
                    normalized = os.path.abspath(os.path.expanduser(path))
                    normalized_ref_paths.append(normalized)
        ref_image_path = normalized_ref_paths if normalized_ref_paths else ref_image_path
    else:
        if ref_image_path and os.path.exists(ref_image_path):
            try:
                ref_image_path = os.path.realpath(os.path.abspath(os.path.expanduser(ref_image_path)))
            except (OSError, ValueError):
                # If normalization fails, try without realpath
                ref_image_path = os.path.abspath(os.path.expanduser(ref_image_path))
    
    # Check if we have images to search against
    if not ref_image_path or (isinstance(ref_image_path, list) and not ref_image_path):
        show_styled_warning(
            mw,
            "No Images Selected",
            "No images selected to search against.\n\nPlease select one or more images to use as reference.",
        )
        return
    
    # Collect images to search
    if recursive:
        # Collect images recursively from selected directory or current directory
        from thumbnail_constants import get_image_extensions
        
        # Get depth from search_depth setting (defaults to 4)
        max_depth = settings.get('search_depth', 4)
        
        # Get excluded paths (prowser cache and Photos Library paths)
        excluded_paths = _get_excluded_paths(mw.config)
        
        # Use search_directory if provided and valid, otherwise use current_dir
        if search_directory and os.path.isdir(search_directory):
            search_dir = search_directory
            # When using custom directory, start with empty list (only reference images will be added)
            displayed_images = []
            displayed_images_set = set()
        else:
            search_dir = current_dir if current_dir else (mw.current_directory if getattr(mw, 'current_directory', None) else os.path.expanduser('~'))
            # When using current directory, start with current directory's displayed images (respects filters)
            displayed_images = [os.path.abspath(os.path.expanduser(p)) for p in current_displayed]
            displayed_images_set = set(displayed_images)
        
        # Check if directory is root or system volume
        if is_root_or_system_volume(search_dir):
            if search_dir == '/':
                show_styled_warning(mw, "Action Not Available", 
                                   "Recursive search is not available on the root directory.")
            else:
                show_styled_warning(mw, "Action Not Available", 
                                   "Recursive search is not available on system volumes.")
            return
        
        search_dir_resolved = os.path.realpath(search_dir)
        image_extensions = get_image_extensions()
        
        # Track source images (reference images) to ensure they're included
        # Normalize reference paths consistently (use realpath to match how paths are normalized in candidates)
        source_images_set = set()
        if isinstance(ref_image_path, list):
            for p in ref_image_path:
                if p and os.path.exists(p):
                    try:
                        normalized = os.path.realpath(os.path.abspath(os.path.expanduser(p)))
                        source_images_set.add(normalized)
                    except (OSError, ValueError):
                        normalized = os.path.abspath(os.path.expanduser(p))
                        source_images_set.add(normalized)
        else:
            if ref_image_path and os.path.exists(ref_image_path):
                try:
                    normalized = os.path.realpath(os.path.abspath(os.path.expanduser(ref_image_path)))
                    source_images_set.add(normalized)
                except (OSError, ValueError):
                    normalized = os.path.abspath(os.path.expanduser(ref_image_path))
                    source_images_set.add(normalized)
        
        # Add reference images to the set and list if not already present
        for source_img in source_images_set:
            if source_img not in displayed_images_set:
                displayed_images_set.add(source_img)
                displayed_images.append(source_img)
        
        # Track images that don't match filter pattern
        filter_pattern = mw.filter_pattern if hasattr(mw, 'filter_pattern') else None
        match_pattern = None
        if filter_pattern:
            from config import ImageBrowserConfig
            match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)
        non_matching_images = []
        
        # Get process hidden directories setting
        process_hidden = settings.get('show_hidden_directories', False)
        
        # Walk directories up to max_depth levels deep
        for root, dirs, files in os.walk(search_dir):
            root_resolved = os.path.realpath(root)
            
            # Skip excluded directories (prowser cache and Photos Library paths)
            if _is_excluded_path(root_resolved, excluded_paths):
                dirs[:] = []  # Don't recurse into excluded directory
                continue
            
            # Filter hidden directories if not processing them
            if not process_hidden:
                dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            # Calculate depth relative to search_dir
            rel_path = os.path.relpath(root, search_dir)
            if rel_path == '.':
                depth = 0
            else:
                depth = len([p for p in rel_path.split(os.sep) if p])
            
            if depth > max_depth:
                # Skip directories deeper than max_depth levels
                dirs[:] = []  # Don't recurse into subdirectories
                continue
            
            # Collect image files
            for file in files:
                file_path = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()
                if ext in image_extensions and os.path.isfile(file_path):
                    # Normalize path
                    abs_path = os.path.abspath(os.path.expanduser(file_path))
                    
                    # Check if matches filter pattern
                    matches_filter = True
                    if match_pattern and match_pattern != '*':
                        filename = os.path.basename(file_path)
                        matches_filter = fnmatch.fnmatch(filename.lower(), match_pattern.lower())
                    
                    # Add if not already in set
                    if abs_path not in displayed_images_set:
                        displayed_images_set.add(abs_path)
                        displayed_images.append(abs_path)
                        if not matches_filter:
                            non_matching_images.append(abs_path)
    else:
        # Non-recursive: use current displayed images or selected directory
        if search_directory and os.path.isdir(search_directory):
            # Collect images from selected directory non-recursively (top-level only)
            from thumbnail_constants import get_image_extensions
            
            displayed_images = []
            displayed_images_set = set()
            
            # Track source images (reference images) to ensure they're included
            # Normalize reference paths consistently (use realpath to match how paths are normalized in candidates)
            source_images_set = set()
            if isinstance(ref_image_path, list):
                for p in ref_image_path:
                    if p and os.path.exists(p):
                        try:
                            normalized = os.path.realpath(os.path.abspath(os.path.expanduser(p)))
                            source_images_set.add(normalized)
                        except (OSError, ValueError):
                            normalized = os.path.abspath(os.path.expanduser(p))
                            source_images_set.add(normalized)
            else:
                if ref_image_path and os.path.exists(ref_image_path):
                    try:
                        normalized = os.path.realpath(os.path.abspath(os.path.expanduser(ref_image_path)))
                        source_images_set.add(normalized)
                    except (OSError, ValueError):
                        normalized = os.path.abspath(os.path.expanduser(ref_image_path))
                        source_images_set.add(normalized)
            
            # Add reference images to the set and list
            for source_img in source_images_set:
                if source_img not in displayed_images_set:
                    displayed_images_set.add(source_img)
                    displayed_images.append(source_img)
            
            # Get excluded paths
            excluded_paths = _get_excluded_paths(mw.config)
            search_dir_resolved = os.path.realpath(search_directory)
            
            # Skip if search directory is excluded
            if not _is_excluded_path(search_dir_resolved, excluded_paths):
                image_extensions = get_image_extensions()
                
                # Track images that don't match filter pattern
                filter_pattern = mw.filter_pattern if hasattr(mw, 'filter_pattern') else None
                match_pattern = None
                if filter_pattern:
                    from config import ImageBrowserConfig
                    match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)
                non_matching_images = []
                
                # Collect only top-level images (non-recursive)
                try:
                    for file in os.listdir(search_directory):
                        file_path = os.path.join(search_directory, file)
                        if os.path.isfile(file_path):
                            ext = os.path.splitext(file)[1].lower()
                            if ext in image_extensions:
                                # Normalize path (use realpath to resolve symlinks for consistent matching)
                                try:
                                    abs_path = os.path.realpath(os.path.abspath(os.path.expanduser(file_path)))
                                except (OSError, ValueError):
                                    # If realpath fails (e.g., broken symlink), fall back to abspath
                                    abs_path = os.path.abspath(os.path.expanduser(file_path))
                                
                                # Check if matches filter pattern
                                matches_filter = True
                                if match_pattern and match_pattern != '*':
                                    filename = os.path.basename(file_path)
                                    matches_filter = fnmatch.fnmatch(filename.lower(), match_pattern.lower())
                                
                                # Add if not already in set
                                if abs_path not in displayed_images_set:
                                    displayed_images_set.add(abs_path)
                                    displayed_images.append(abs_path)
                                    if not matches_filter:
                                        non_matching_images.append(abs_path)
                except (OSError, PermissionError) as e:
                    print(f"Error reading directory {search_directory}: {e}")
        else:
            # Use current displayed images
            displayed_images = current_displayed
            non_matching_images = []
    
    if not displayed_images:
        show_styled_warning(mw, "No Images Found", "No images found to search.")
        return
    
    # Check if any non-matching images were found and ask user about filter
    displayed_images = handle_filter_pattern_mismatch(mw, displayed_images, non_matching_images, recursive)
    
    # Suspend all background thumbnail loading immediately
    # Stop background loader
    if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
        mw.cache_manager.background_loader.stop()
    
    # Cancel thumbnail loading worker (non-blocking)
    if getattr(mw, 'thumbnail_worker', None):
        try:
            if mw.thumbnail_worker.isRunning():
                mw.thumbnail_worker.cancel()
                # Use non-blocking cleanup
                mw.cleanup_worker_thread('thumbnail_worker', delete_after=False)
            else:
                if hasattr(mw, 'thumbnail_worker'):
                    delattr(mw, 'thumbnail_worker')
        except Exception:
            try:
                mw.cleanup_worker_thread('thumbnail_worker', delete_after=False)
            except Exception:
                if hasattr(mw, 'thumbnail_worker'):
                    delattr(mw, 'thumbnail_worker')
    
    # Lazy initialize CNN sorter on first use
    mw._ensure_cnn_sorter_initialized()
    
    # Track if this is a multi-selection sort
    was_multi_selection = isinstance(ref_image_path, list) and len(ref_image_path) > 1
    
    # Get similarity metric from settings (never CLIP for this method)
    similarity_metric = mw.config.load_settings().get('similarity_metric', 'cosine')
    # Ensure we're not using CLIP - if somehow it's set, default to cosine
    if similarity_metric == 'clip':
        similarity_metric = 'cosine'
    
    # Ensure source images are in displayed_images (they should be, but double-check)
    # Normalize paths consistently using realpath to match how candidates are normalized
    source_images_set = set()
    if isinstance(ref_image_path, list):
        for p in ref_image_path:
            if p and os.path.exists(p):
                try:
                    normalized = os.path.realpath(os.path.abspath(os.path.expanduser(p)))
                    source_images_set.add(normalized)
                except (OSError, ValueError):
                    normalized = os.path.abspath(os.path.expanduser(p))
                    source_images_set.add(normalized)
    else:
        if ref_image_path and os.path.exists(ref_image_path):
            try:
                normalized = os.path.realpath(os.path.abspath(os.path.expanduser(ref_image_path)))
                source_images_set.add(normalized)
            except (OSError, ValueError):
                normalized = os.path.abspath(os.path.expanduser(ref_image_path))
                source_images_set.add(normalized)
    
    # Also normalize displayed_images paths for consistent matching
    normalized_displayed_images = []
    normalized_displayed_images_set = set()
    for img_path in displayed_images:
        if img_path and os.path.exists(img_path):
            try:
                normalized = os.path.realpath(os.path.abspath(os.path.expanduser(img_path)))
                if normalized not in normalized_displayed_images_set:
                    normalized_displayed_images.append(normalized)
                    normalized_displayed_images_set.add(normalized)
            except (OSError, ValueError):
                normalized = os.path.abspath(os.path.expanduser(img_path))
                if normalized not in normalized_displayed_images_set:
                    normalized_displayed_images.append(normalized)
                    normalized_displayed_images_set.add(normalized)
        else:
            # Keep non-existent paths as-is (they'll be filtered out later)
            if img_path not in normalized_displayed_images_set:
                normalized_displayed_images.append(img_path)
                normalized_displayed_images_set.add(img_path)
    
    displayed_images = normalized_displayed_images
    displayed_images_set = normalized_displayed_images_set
    
    # Add source images if not already present
    for source_img in source_images_set:
        if source_img not in displayed_images_set:
            displayed_images.append(source_img)
            displayed_images_set.add(source_img)

    # Lazy initialize UI helper if needed
    mw._ensure_cnn_ui_helper_initialized()
    
    # Create and show progress bar dialog with status line using helper
    is_first_search = mw.cnn_similarity_ui_helper.is_first_similarity_search
    progress_dialog = mw.cnn_similarity_ui_helper.create_similarity_progress_dialog(
        len(displayed_images), is_first_search=is_first_search, recursive=recursive, search_directory=search_directory
    )

    # Create progress callback using helper (only used if progress_dialog is not provided)
    progress_cb = mw.cnn_similarity_ui_helper.create_similarity_progress_callback(
        progress_dialog, is_first_search=is_first_search
    )

    try:
        # Use image-based search with the metric from settings
        # Pass None as callback when we have progress_dialog (tracker will be used instead)
        new_displayed_images = mw.cnn_image_similarity_sorter.reorder_by_similarity(
            displayed_images, ref_image_path, 
            progress_callback=None if progress_dialog else progress_cb, 
            progress_dialog=progress_dialog
        )
        
        # Ensure source images are in results but not duplicated
        source_images_list = list(source_images_set)
        result_set = set(new_displayed_images)
        for source_img in source_images_list:
            if source_img not in result_set:
                new_displayed_images.append(source_img)
                result_set.add(source_img)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_images = []
        for img in new_displayed_images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)
        new_displayed_images = unique_images
        
        # Check if no matches found (only source images in results)
        if recursive and len(new_displayed_images) <= len(source_images_set):
            show_styled_information(
                mw,
                "No Matches Found",
                "No similar images found matching the search criteria.",
            )
            progress_dialog.hide()
            # Restart thumbnails
            if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
                mw.cache_manager.background_loader.start()
            return
        
        # Mark that similarity search has been used
        mw.highlight_image() # DGN try a refresh to fix empty thumbnails
        mw.cnn_similarity_ui_helper.mark_similarity_search_used()
    except KeyboardInterrupt:
        progress_dialog.cancel()
        print(f"KeyboardInterrupt in _reorder_images_by_similarity")
        # Flush cache on cancel to save any features gathered so far
        # Use async flush to avoid blocking main thread
        if getattr(mw, 'cnn_image_similarity_sorter', None) and mw.cnn_image_similarity_sorter.feature_cache:
            mw.cnn_image_similarity_sorter.feature_cache.flush_caches(async_flush=True)
        # Restart thumbnails on cancel
        if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
            mw.cache_manager.background_loader.start()
        return
    finally:
        progress_dialog.setValue(len(displayed_images))
        progress_dialog.hide()

    if recursive:
        # Open results in a new thumbnail level (similar to CLIP recursive search)
        if hasattr(mw, 'directory_stack_history_handler'):
            # Save current state before switching to search results
            mw.directory_stack_history_handler.save_current_state("image_browser_window._reorder_images_by_similarity (recursive)", delay=0.0)
        
        # CRITICAL: Save the current image path BEFORE refresh_from_configuration - this is the source of truth
        # The current_image_path represents the image that should remain current after search
        saved_current_image_path = mw.get_current_image_path()
        
        # CRITICAL: Check if result set is the same as starting set (files and order)
        # Capture current displayed_images before updating
        current_displayed_images = []
        if getattr(mw, 'displayed_images', None):
            current_displayed_images = mw.displayed_images
        
        # Check if files and order are the same
        files_changed = set(current_displayed_images) != set(new_displayed_images)
        order_changed = current_displayed_images != new_displayed_images
        
        # CRITICAL: Set sort mode to CUSTOM BEFORE refresh_from_configuration()
        # This ensures load_specific_files() sees CUSTOM mode and doesn't call apply_display_order()
        # which would repopulate exif_date_sections if mode was still EXIF_DATE
        # Set mode directly to trigger setter cleanup (clears exif_date_sections)
        mw.current_sort_mode = SortMode.CUSTOM
        mw.is_reversed = False  # Best matches at top = ascending order
        
        # CRITICAL: Explicitly clear EXIF sections before refresh to prevent any stale data
        if hasattr(mw, 'exif_date_sections'):
            mw.exif_date_sections = []
        if hasattr(mw, 'exif_section_expanded'):
            mw.exif_section_expanded = {}
        
        # Process search results as if they came from the API
        configuration = {'files': new_displayed_images, 'sort_mode': 'custom'}
        mw.refresh_from_configuration(configuration)
        
        
        # CRITICAL: Ensure displayed_images matches the similarity-ordered list
        # refresh_from_configuration/load_specific_files might have reordered them
        # We must preserve the order from new_displayed_images (similarity search results)
        # Use _set_displayed_images_with_sync to keep file_data_model in sync (browse mode arrow keys use it)
        mw._set_displayed_images_with_sync(new_displayed_images.copy(), sync=True)
        mw.populate_indices_arrays()
        
        # CRITICAL: After refresh, ensure EXIF sections are still cleared and force thumbnail refresh
        # Clear sections again (defensive) and force reorder to remove any sections that were created
        if hasattr(mw, 'exif_date_sections'):
            mw.exif_date_sections = []
        if hasattr(mw, 'exif_section_expanded'):
            mw.exif_section_expanded = {}
        if getattr(mw, 'thumbnail_container', None):
            if hasattr(mw.thumbnail_container, 'canvas'):
                if hasattr(mw.thumbnail_container.canvas, 'section_separators'):
                    mw.thumbnail_container.canvas.section_separators.clear()
                # Only refresh thumbnails if files or order changed
                # If same files and same order, skip thumbnail refresh
                if (files_changed or order_changed) and new_displayed_images:
                    # Force reorder to refresh thumbnails without sections
                    # Use new_displayed_images directly to ensure correct order (similarity search results)
                    mw.thumbnail_container.canvas.reorder_thumbnails(new_displayed_images, force_recalculate_grid=True)
        # Skip apply_current_sort() for CUSTOM mode - order is already correct from similarity search
        # Only apply if mode somehow changed (shouldn't happen, but defensive)
        if mw.current_sort_mode != SortMode.CUSTOM:
            mw._apply_current_sort()
        
        # CRITICAL: Restore current_image_path if it exists in the new results
        # This ensures the same image file is highlighted, not just the same index position
        if saved_current_image_path and saved_current_image_path in new_displayed_images:
            # The original image is in the results - highlight it
            mw.set_current_image_by_path(saved_current_image_path, fallback_index=0)
        elif new_displayed_images:
            # Original image not in results - highlight first result
            mw.set_current_image_by_path(new_displayed_images[0], fallback_index=0)
        
        # Don't save .prsort file for recursive searches (images from multiple directories)
        # mw.sorting_manager.save_custom_sort()
        
        # Update status bar and menu to reflect sort mode
        mw.update_status_bar_sections()
        mw.update_sort_menu_checkmarks()
        mw.save_sorting_settings()

        # Highlight the image and scroll to show it (highlight_image does scroll_to_highlighted)
        mw.highlight_image()
        QTimer.singleShot(100, mw.ensure_highlighted_visible)
    else:
        # Non-recursive: check if we need to handle locked files
        # If locked files exist, rewrite .prsort instead of entering specific files mode
        # CRITICAL: Save the current image path BEFORE any operations
        # This is the source of truth - the image that should remain highlighted
        saved_current_image_path = mw.current_image_path
        
        if getattr(mw, 'current_directory', None):
            if getattr(mw, 'lock_manager', None):
                locked_files = mw.lock_manager.get_locked_files(mw.current_directory)
                
                if locked_files:
                    # Check if all search results are from the same directory
                    directories = set(os.path.dirname(path) for path in new_displayed_images if os.path.exists(path))
                    
                    if len(directories) == 1:
                        dir_path = directories.pop()
                        
                        if dir_path == mw.current_directory:
                            # All results from current directory - rewrite .prsort with locked files at top
                            
                            if hasattr(mw, 'similarity_search_manager'):
                                mw.similarity_search_manager._rewrite_prsort_with_locked_at_top(new_displayed_images, mw.current_directory)
                                
                                # Reload directory then trigger "C" action
                                directory_to_reload = mw.current_directory
                                def reload_then_custom_sort():
                                    if not directory_to_reload:
                                        return
                                    
                                    # Reload directory to get all files from disk (including locked files)
                                    if hasattr(mw, 'directory_loader'):
                                        mw.directory_loader.load_directory(
                                            directory_to_reload,
                                            external_load=False,
                                            refresh_mode=True
                                        )
                                        # Wait for directory load to complete, then trigger set_custom_sort
                                        def trigger_c_and_restore_image():
                                            mw.set_custom_sort()
                                            
                                            # CRITICAL: Restore the current image after reload
                                            if saved_current_image_path:
                                                displayed = mw.get_displayed_images()
                                                if saved_current_image_path in displayed:
                                                    # Image still exists - highlight it
                                                    mw.set_current_image_by_path(saved_current_image_path, fallback_index=0)
                                                    mw.highlight_image()
                                                    QTimer.singleShot(100, mw.ensure_highlighted_visible)
                                                else:
                                                    # Fallback: highlight first image
                                                    if displayed:
                                                        mw.set_current_image_by_path(displayed[0], fallback_index=0)
                                                        mw.highlight_image()
                                                        QTimer.singleShot(100, mw.ensure_highlighted_visible)
                                            
                                        QTimer.singleShot(500, trigger_c_and_restore_image)
                                
                                # Use delay to ensure .prsort file is written to disk before reload
                                QTimer.singleShot(300, reload_then_custom_sort)
                                
                                return
        
        # Non-recursive: update displayed images in place
        # Save current selections before reordering (by file name/path)
        saved_selections = set(mw.selected_files) if mw.selected_files else set()
        
        # CRITICAL: Save the current image path BEFORE reordering - this is the source of truth
        # The current_image_path represents the last selected image (the one that should remain current)
        saved_current_image_path = mw.current_image_path
        
        # CRITICAL: Check if result set is the same as starting set (files and order)
        # Capture current displayed_images before updating
        current_displayed_images = []
        if getattr(mw, 'displayed_images', None):
            current_displayed_images = mw.displayed_images
        
        # Check if files and order are the same
        files_changed = set(current_displayed_images) != set(new_displayed_images)
        order_changed = current_displayed_images != new_displayed_images
        
        # If same files and same order, no thumbnail rebuild is needed
        if not files_changed and not order_changed:
            # Same files, same order - no refresh needed, just restart thumbnails
            if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
                mw.cache_manager.background_loader.start()
            mw.start_background_thumbnail_loading_if_needed()
            # Update UI
            mw.update_status_bar_sections()
            mw.update_sort_menu_checkmarks()
            mw.save_sorting_settings()
            return
        
        # Use _set_displayed_images_with_sync to keep file_data_model in sync (browse mode arrow keys use it)
        mw._set_displayed_images_with_sync(new_displayed_images, sync=True)
        mw.populate_indices_arrays()
        
        # CRITICAL: Set sort mode to CUSTOM BEFORE reorder_thumbnails()
        # This ensures reorder_thumbnails() sees CUSTOM mode and doesn't create EXIF sections
        mw.current_sort_mode = SortMode.CUSTOM
        mw.is_reversed = False  # Best matches at top = ascending order
        
        # Force full thumbnail refresh to ensure display updates
        mw.thumbnail_container.canvas.reorder_thumbnails(mw.displayed_images, force_recalculate_grid=True)
        # After similarity sort: restore selections by file name, ensure random mode
        if was_multi_selection:
            # Restore selections by filtering to only those that still exist in displayed_images
            # All selections are by file name, so they persist automatically
            mw.selected_files = {path for path in saved_selections if path in mw.displayed_images}
            
            # CRITICAL: Set current image by file path (the source of truth)
            # The last selected image (saved_current_image_path) should become current after reordering
            mw.set_current_image_by_path(saved_current_image_path, fallback_index=0)
        else:
            # For single selection (not multiselect), set current image by file path
            mw.selected_files.clear()
            mw.set_current_image_by_path(saved_current_image_path, fallback_index=0)
        
        # Save the custom order (same as cmd-S)
        # But only if search_directory wasn't used or matches current_directory
        
        # Only save .prsort if we're searching in the current directory
        # (not when using a different search_directory)
        if not search_directory:
            # No custom search directory - save .prsort
            mw.sorting_manager.save_custom_sort()
        elif getattr(mw, 'current_directory', None):
            # Normalize paths for comparison
            search_dir_normalized = os.path.abspath(os.path.expanduser(search_directory))
            current_dir_normalized = os.path.abspath(os.path.expanduser(mw.current_directory))
            if search_dir_normalized == current_dir_normalized:
                # Searching in current directory - save .prsort
                mw.sorting_manager.save_custom_sort()
            # Otherwise, don't save .prsort (searching in different directory)
        
        # Update status bar and menu to reflect sort mode
        mw.update_status_bar_sections()
        mw.update_sort_menu_checkmarks()
        mw.save_sorting_settings()
        
        # Update canvas selection to reflect any changes
        mw._emit_selection_changed()
        
        # Highlight the image and scroll to show it
        # PERFORMANCE: Removed duplicate highlight_image() and update_canvas_selection() calls
        mw.highlight_image()
        QTimer.singleShot(100, mw.ensure_highlighted_visible)
        
        mw.thumbnail_container.canvas.update()
    
    # Restart thumbnail generation now that results are displayed
    if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
        mw.cache_manager.background_loader.start()
    # Trigger thumbnail loading for the new results
    mw.start_background_thumbnail_loading_if_needed()
    # mw.highlight_image() # DGN try a refresh to fix empty thumbnails



def reorder_images_by_clip_search(mw):
    """Reorder images using CLIP text-based semantic search.
    Always prompts the user for a text description."""
    # Lazy initialize UI helper if needed
    mw._ensure_cnn_ui_helper_initialized()
    
    # Mark cache activity to reset unload timer
    if getattr(mw, 'cnn_image_similarity_sorter', None) and mw.cnn_image_similarity_sorter.feature_cache:
        mw.cnn_image_similarity_sorter.feature_cache.mark_cache_activity()
    
    # Check if locked files exist in current directory
    has_locked_files = False
    if getattr(mw, 'current_directory', None):
        if getattr(mw, 'lock_manager', None):
            locked_files = mw.lock_manager.get_locked_files(mw.current_directory)
            has_locked_files = len(locked_files) > 0
    
    # Ask user for text prompt FIRST (before loading torch/model)
    settings = mw.config.load_settings()
    saved_prompt = settings.get('clip_prompt', '')
    saved_recursive = settings.get('clip_recursive', False)
    saved_threshold = settings.get('clip_similarity_threshold', 0.20)
    current_dir = mw.get_current_search_directory()
    dialog = mw.cnn_similarity_ui_helper.create_clip_search_dialog(
        "Find Images",
        "Enter text description to search for:",
        text=saved_prompt,
        recursive_default=saved_recursive,
        threshold_default=saved_threshold,
        directory=current_dir,
        hide_threshold=has_locked_files
    )
    
    # If tree had focus when invoked and a directory was provided, check checkbox and set directory field
    tree_had_focus = getattr(mw, '_tree_had_focus_when_invoked', False)
    if tree_had_focus and current_dir and os.path.isdir(current_dir):
        if hasattr(dialog, 'dir_checkbox'):
            dialog.dir_checkbox.setChecked(True)
        if hasattr(dialog, 'dir_input'):
            dialog.dir_input.setText(current_dir)
    
    if not dialog.exec():
        # User canceled dialog - remain in current mode (browse or thumbnail)
        return
    
    # User accepted dialog - exit list view if in list mode (prevents hanging)
    if mw.current_view_mode == 'list':
        mw.toggle_list_view()  # Exit list view
        # Process events to ensure view switch completes
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
    
    # User accepted dialog - switch to thumbnail mode if in browse mode
    if mw.current_view_mode == 'browse':
        mw.close_browse_view()
        # Process events to ensure view switch completes
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
    
    text_prompt = dialog.text_input.text().strip()
    recursive = dialog.recursive_checkbox.isChecked()
    # Force threshold to 0.0 when locked files exist (ignore user setting)
    if has_locked_files:
        threshold = 0.0
    else:
        threshold = dialog.threshold_spinbox.value() if hasattr(dialog, 'threshold_spinbox') else 0.20
    dir_checkbox_checked = dialog.dir_checkbox.isChecked() if hasattr(dialog, 'dir_checkbox') else False
    # Use search_directory if checkbox is checked (regardless of recursive)
    search_directory = dialog.dir_input.text().strip() if dir_checkbox_checked and hasattr(dialog, 'dir_input') else None
    
    if not text_prompt:
        # User entered empty text - don't load anything
        return
    
    # Save the prompt, recursive setting, threshold, and directory settings to config for next time
    # Don't save threshold if it was forced to 0.0 due to locked files
    mw.config.update_setting('clip_prompt', text_prompt)
    mw.config.update_setting('clip_recursive', recursive)
    if not has_locked_files:
        mw.config.update_setting('clip_similarity_threshold', threshold)
    if hasattr(dialog, 'dir_checkbox'):
        mw.config.update_setting('clip_search_dir_enabled', dialog.dir_checkbox.isChecked())
    if hasattr(dialog, 'dir_input'):
        mw.config.update_setting('clip_search_dir', dialog.dir_input.text().strip())
    
    # CLIP search doesn't use reference images - it's text-based
    # The directory selection just changes where to search from
    from thumbnail_constants import get_image_extensions
    
    # Collect images to search
    if recursive:
        # Collect images recursively from selected directory or current directory
        
        # Get depth from search_depth setting (defaults to 4)
        max_depth = settings.get('search_depth', 4)
        
        # Get excluded paths (prowser cache and Photos Library paths)
        excluded_paths = _get_excluded_paths(mw.config)
        
        # Use search_directory if provided and valid, otherwise use current_dir
        current_displayed = mw.get_displayed_images()
        if search_directory and os.path.isdir(search_directory):
            search_dir = search_directory
            # When using custom directory, start with empty list
            displayed_images = []
            displayed_images_set = set()
        else:
            search_dir = current_dir if current_dir else (mw.current_directory if getattr(mw, 'current_directory', None) else os.path.expanduser('~'))
            # When using current directory, start with current directory's displayed images (respects filters)
            displayed_images = [os.path.abspath(os.path.expanduser(p)) for p in current_displayed]
            displayed_images_set = set(displayed_images)
        
        # Check if directory is root or system volume
        if is_root_or_system_volume(search_dir):
            if search_dir == '/':
                show_styled_warning(mw, "Action Not Available", 
                                   "Recursive search is not available on the root directory.")
            else:
                show_styled_warning(mw, "Action Not Available", 
                                   "Recursive search is not available on system volumes.")
            return
        
        search_dir_resolved = os.path.realpath(search_dir)
        image_extensions = get_image_extensions()
        
        # Track images that don't match filter pattern
        filter_pattern = mw.filter_pattern if hasattr(mw, 'filter_pattern') else None
        match_pattern = None
        if filter_pattern:
            from config import ImageBrowserConfig
            match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)
        non_matching_images = []
        
        # Get process hidden directories setting
        process_hidden = settings.get('show_hidden_directories', False)
        
        # Walk directories up to max_depth levels deep
        for root, dirs, files in os.walk(search_dir):
            root_resolved = os.path.realpath(root)
            
            # Skip excluded directories (prowser cache and Photos Library paths)
            if _is_excluded_path(root_resolved, excluded_paths):
                dirs[:] = []  # Don't recurse into excluded directory
                continue
            
            # Filter hidden directories if not processing them
            if not process_hidden:
                dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            # Calculate depth relative to search_dir
            rel_path = os.path.relpath(root, search_dir)
            if rel_path == '.':
                depth = 0
            else:
                depth = len([p for p in rel_path.split(os.sep) if p])
            
            if depth > max_depth:
                # Skip directories deeper than max_depth levels
                dirs[:] = []  # Don't recurse into subdirectories
                continue
            
            # Collect image files
            for file in files:
                file_path = os.path.join(root, file)
                ext = os.path.splitext(file)[1].lower()
                if ext in image_extensions and os.path.isfile(file_path):
                    # Normalize path
                    abs_path = os.path.abspath(os.path.expanduser(file_path))
                    
                    # Check if matches filter pattern
                    matches_filter = True
                    if match_pattern and match_pattern != '*':
                        filename = os.path.basename(file_path)
                        matches_filter = fnmatch.fnmatch(filename.lower(), match_pattern.lower())
                    
                    # Add if not already in set
                    if abs_path not in displayed_images_set:
                        displayed_images_set.add(abs_path)
                        displayed_images.append(abs_path)
                        if not matches_filter:
                            non_matching_images.append(abs_path)
    else:
        # Non-recursive: use current displayed images or selected directory
        current_displayed = mw.get_displayed_images()
        if search_directory and os.path.isdir(search_directory):
            # Collect images from selected directory non-recursively (top-level only)
            displayed_images = []
            displayed_images_set = set()
            
            # Get excluded paths
            excluded_paths = _get_excluded_paths(mw.config)
            search_dir_resolved = os.path.realpath(search_directory)
            
            # Skip if search directory is excluded
            if not _is_excluded_path(search_dir_resolved, excluded_paths):
                image_extensions = get_image_extensions()
                
                # Track images that don't match filter pattern
                filter_pattern = mw.filter_pattern if hasattr(mw, 'filter_pattern') else None
                match_pattern = None
                if filter_pattern:
                    from config import ImageBrowserConfig
                    match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)
                non_matching_images = []
                
                # Collect only top-level images (non-recursive)
                try:
                    for file in os.listdir(search_directory):
                        file_path = os.path.join(search_directory, file)
                        if os.path.isfile(file_path):
                            ext = os.path.splitext(file)[1].lower()
                            if ext in image_extensions:
                                # Normalize path (use realpath to resolve symlinks for consistent matching)
                                try:
                                    abs_path = os.path.realpath(os.path.abspath(os.path.expanduser(file_path)))
                                except (OSError, ValueError):
                                    # If realpath fails (e.g., broken symlink), fall back to abspath
                                    abs_path = os.path.abspath(os.path.expanduser(file_path))
                                
                                # Check if matches filter pattern
                                matches_filter = True
                                if match_pattern and match_pattern != '*':
                                    filename = os.path.basename(file_path)
                                    matches_filter = fnmatch.fnmatch(filename.lower(), match_pattern.lower())
                                
                                # Add if not already in set
                                if abs_path not in displayed_images_set:
                                    displayed_images_set.add(abs_path)
                                    displayed_images.append(abs_path)
                                    if not matches_filter:
                                        non_matching_images.append(abs_path)
                except (OSError, PermissionError) as e:
                    print(f"Error reading directory {search_directory}: {e}")
        else:
            # Use current displayed images
            displayed_images = current_displayed
            non_matching_images = []
    
    if not displayed_images:
        show_styled_warning(mw, "No Images Found", "No images found to search.")
        return
    
    # Check if any non-matching images were found and ask user about filter
    displayed_images = handle_filter_pattern_mismatch(mw, displayed_images, non_matching_images, recursive)
    
    # Suspend all background thumbnail loading immediately
    # Stop background loader
    if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
        mw.cache_manager.background_loader.stop()
    
    # Cancel thumbnail loading worker (non-blocking)
    if getattr(mw, 'thumbnail_worker', None):
        try:
            if mw.thumbnail_worker.isRunning():
                mw.thumbnail_worker.cancel()
                # Use non-blocking cleanup
                mw.cleanup_worker_thread('thumbnail_worker', delete_after=False)
            else:
                if hasattr(mw, 'thumbnail_worker'):
                    delattr(mw, 'thumbnail_worker')
        except Exception:
            try:
                mw.cleanup_worker_thread('thumbnail_worker', delete_after=False)
            except Exception:
                if hasattr(mw, 'thumbnail_worker'):
                    delattr(mw, 'thumbnail_worker')
    
    # NOW lazy initialize CNN sorter (user has confirmed they want to search)
    mw._ensure_cnn_sorter_initialized()
    # Lazy initialize UI helper if needed
    mw._ensure_cnn_ui_helper_initialized()

    # Create and show progress bar dialog with status line using helper
    is_first_search = mw.cnn_similarity_ui_helper.is_first_clip_search
    progress_dialog = mw.cnn_similarity_ui_helper.create_clip_progress_dialog(
        text_prompt, len(displayed_images), is_first_search=is_first_search, recursive=recursive, search_directory=search_directory
    )

    # Create progress callback using helper (only used if progress_dialog is not provided)
    progress_cb = mw.cnn_similarity_ui_helper.create_clip_progress_callback(
        progress_dialog, is_first_search=is_first_search
    )

    # Initialize files_changed to True (default to creating new stack if calculation fails)
    files_changed = True

    try:
        # Use prompt-based search with threshold filtering for both recursive and non-recursive
        threshold_adjusted = False
        original_threshold = threshold
        
        # Use threshold filtering for all CLIP searches (both recursive and non-recursive)
        # Pass None as callback when we have progress_dialog (tracker will be used instead)
        result = mw.cnn_image_similarity_sorter.reorder_by_text_prompt(
            displayed_images, text_prompt, progress_callback=None if progress_dialog else progress_cb,
            similarity_threshold=threshold, filter_below_threshold=True, progress_dialog=progress_dialog
        )
        new_displayed_images, highest_score = result
        
        # If no matches found but there were images below threshold, retry with lower threshold
        if len(new_displayed_images) == 0 and highest_score is not None and highest_score < threshold:
            # Calculate new threshold: max(highest_score - 0.03, 0)
            new_threshold = max(highest_score - 0.03, 0.0)
            threshold_adjusted = True
            threshold = new_threshold
            
            # Update progress dialog
            progress_dialog.setStatusText(f"Retrying with adjusted threshold: {threshold:.2f}...")
            progress_dialog.setValue(0)
            
            # Retry search with adjusted threshold
            result = mw.cnn_image_similarity_sorter.reorder_by_text_prompt(
                displayed_images, text_prompt, progress_callback=None if progress_dialog else progress_cb,
                similarity_threshold=threshold, filter_below_threshold=True, progress_dialog=progress_dialog
            )
            new_displayed_images, highest_score = result
        
        # Debug output
        if mw.debug_mode:
            mode_str = "recursive" if recursive else "non-recursive"
            if threshold_adjusted:
                print(f"CLIP {mode_str} search: Found {len(new_displayed_images)} matching images after threshold adjustment (original: {original_threshold:.2f}, adjusted: {threshold:.2f})")
            else:
                print(f"CLIP {mode_str} search: Found {len(new_displayed_images)} matching images out of {len(displayed_images)} total (threshold: {threshold:.2f})")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_images = []
        for img in new_displayed_images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)
        new_displayed_images = unique_images
        
        # Check if no matches found
        if recursive and len(new_displayed_images) == 0:
            show_styled_information(
                mw,
                "No Matches Found",
                "No images found matching the search criteria.",
            )
            progress_dialog.hide()
            # Restart thumbnails
            if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
                mw.cache_manager.background_loader.start()
            return
        
        # Mark that CLIP search has been used
        mw.cnn_similarity_ui_helper.mark_clip_search_used()
        
        # CRITICAL: Check if files changed before creating new stack
        # Capture current displayed_images BEFORE saving state to history
        current_displayed_images = set()
        if getattr(mw, 'displayed_images', None):
            current_displayed_images = set(mw.displayed_images)
        new_displayed_images_set = set(new_displayed_images)
        files_changed = current_displayed_images != new_displayed_images_set
    except KeyboardInterrupt:
        progress_dialog.cancel()
        # Flush cache on cancel to save any features gathered so far
        # Use async flush to avoid blocking main thread
        if getattr(mw, 'cnn_image_similarity_sorter', None) and mw.cnn_image_similarity_sorter.feature_cache:
            mw.cnn_image_similarity_sorter.feature_cache.flush_caches(async_flush=True)
        # Restart thumbnails on cancel
        if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
            mw.cache_manager.background_loader.start()
        return
    except Exception as e:
        raise
    finally:
        progress_dialog.setValue(len(displayed_images))
        progress_dialog.hide()

    if recursive:
        # Open results in a new thumbnail level (similar to CNN similarity recursive search)
        if hasattr(mw, 'directory_stack_history_handler'):
            # Save current state before switching to search results
            mw.directory_stack_history_handler.save_current_state("image_browser_window._reorder_images_by_clip_search (recursive)", delay=0.0)
        
        # CRITICAL: Save the current image path BEFORE refresh_from_configuration - this is the source of truth
        # The current_image_path represents the image that should remain current after search
        
        # Set sort mode to CUSTOM BEFORE refresh_from_configuration
        # This ensures load_specific_files doesn't re-sort the CLIP search results
        mw.current_sort_mode = SortMode.CUSTOM
        mw.is_reversed = False  # Best matches at top = ascending order
        
        # Process search results as if they came from the API
        configuration = {'files': new_displayed_images, 'sort_mode': 'custom'}
        mw.refresh_from_configuration(configuration)
        
        # CRITICAL: For CLIP searches, always highlight the best match (first non-locked) instead of restoring saved image
        # The saved image may be in results but is not necessarily the best match
        # Use displayed_images after refresh_from_configuration (has locked files at top)
        displayed_images = mw.get_displayed_images()
        if displayed_images:
            # CRITICAL: Check if all files are from the same directory
            # If yes: locked files must be at top (in locked order) and highlight 1st non-locked (or 1st if all locked)
            # If no: just highlight the first image (locked file ordering doesn't apply across directories)
            # This ensures proper highlighting behavior for both single-directory and multi-directory recursive searches
            directories = set(os.path.dirname(path) for path in displayed_images if os.path.exists(path))
            all_same_directory = len(directories) == 1
            
            # For CLIP searches: Always highlight best match (first non-locked), not the saved image
            # Only restore saved image if it IS the best match
            if all_same_directory:
                # All files from same directory: locked files at top, highlight 1st non-locked (or 1st if all locked)
                # _find_best_clip_match handles this correctly for same-directory case
                best_match = mw._find_best_clip_match(displayed_images)
                if best_match:
                    mw.set_current_image_by_path(best_match, fallback_index=0)
                else:
                    # Fallback to first result if no unlocked files found
                    mw.set_current_image_by_path(displayed_images[0], fallback_index=0)
            else:
                # Files from different directories: just highlight the first image (best match)
                mw.set_current_image_by_path(displayed_images[0], fallback_index=0)
        
        # Save state AFTER load_specific_files has set specific_files_active
        # refresh_from_configuration skips state save when files are provided,
        # so we save the correct state here with specific_files set
        if hasattr(mw, 'directory_stack_history_handler'):
            mw.directory_stack_history_handler.save_current_state("image_browser_window._reorder_images_by_clip_search (after load)", delay=0.0)
        
        # Save the custom sort order (same as cmd-S)
        # mw.sorting_manager.save_custom_sort()
        
        # Update status bar and menu to reflect sort mode
        mw.update_status_bar_sections()
        mw.update_sort_menu_checkmarks()
        mw.save_sorting_settings()
        
        # Highlight the image and scroll to show it (highlight_image does scroll_to_highlighted)
        mw.highlight_image()
        QTimer.singleShot(100, mw.ensure_highlighted_visible)

        # Prepare message box content based on results
        if highest_score is not None:
            if len(new_displayed_images) > 0:
                body_msg = (
                    f"Found {len(new_displayed_images)} matching images.\n\n"
                    f"Highest similarity score: {highest_score:.4f}\n"
                )
            else:
                # No matches found, but show highest score that was below threshold
                body_msg = (
                    f"No images matched the search criteria.\n\n"
                    f"Highest similarity score: {highest_score:.4f}\n"
                )
        else:
            body_msg = (
                f"No images matched the search criteria.\n\n"
            )

        threshold_msg = f"Threshold used: {threshold:.2f}"
        if threshold_adjusted:
            threshold_msg += f"\n⚠️ Threshold adjusted from {original_threshold:.2f}"
        full_msg = f"Image Search Results\n\n{body_msg}{threshold_msg}"
        # show_styled_information(mw, "Image Search Results", full_msg)
        QTimer.singleShot(500, lambda: mw.status_notification.show_message(full_msg, duration=6000))
    else:
        # Non-recursive: check if files changed - if same files, rewrite .prsort instead of creating new stack
        if not files_changed:
            # Same files - rewrite .prsort and switch to custom sort mode without creating new stack
            # Check if all search results are from the same directory
            directories = set(os.path.dirname(path) for path in new_displayed_images if os.path.exists(path))
            if len(directories) == 1:
                dir_path = directories.pop()
                if hasattr(mw, 'current_directory') and dir_path == mw.current_directory:
                    # All results from current directory - rewrite .prsort with locked files at top
                    if hasattr(mw, 'similarity_search_manager'):
                        mw.similarity_search_manager._rewrite_prsort_with_locked_at_top(new_displayed_images, mw.current_directory)
                        
                        # CRITICAL: Ensure sort mode is CUSTOM before reloading
                        # This ensures load_directory will read and apply .prsort order
                        mw.current_sort_mode = SortMode.CUSTOM
                        mw.is_reversed = False
                        
                        # CRITICAL: Reload directory first to get all files, then trigger "C" action
                        # set_custom_sort() is what pressing "C" does - it reloads and applies custom sort
                        directory_to_reload = mw.current_directory
                        
                        def do_reload_and_custom():
                            if not directory_to_reload:
                                return
                            
                            # Ensure sort mode is CUSTOM before loading
                            # This ensures load_directory will read and apply .prsort order
                            mw.current_sort_mode = SortMode.CUSTOM
                            mw.is_reversed = False
                            
                            # First reload directory to scan all files from disk
                            if hasattr(mw, 'directory_loader'):
                                mw.directory_loader.load_directory(
                                    directory_to_reload,
                                    external_load=False,
                                    refresh_mode=True
                                )
                            
                            # CRITICAL: Apply custom sort immediately after load to ensure .prsort order is applied
                            # This ensures the displayed order matches the .prsort file we just wrote
                            mw.current_sort_mode = SortMode.CUSTOM
                            mw.is_reversed = False
                            if hasattr(mw, '_apply_current_sort'):
                                mw._apply_current_sort()
                            
                            # Then trigger set_custom_sort (what "C" key does) to ensure UI is updated
                            # NOTE: We do NOT call save_custom_sort() here because we've already written
                            # the .prsort file correctly with the CLIP order in _rewrite_prsort_with_locked_at_top
                            def trigger_c():
                                # Ensure sort mode is CUSTOM
                                mw.current_sort_mode = SortMode.CUSTOM
                                mw.set_custom_sort()
                                
                                # CRITICAL: Highlight best match (first unlocked file if locked files exist)
                                displayed = mw.get_displayed_images()
                                if displayed:
                                    best_match = mw._find_best_clip_match(displayed)
                                    if best_match:
                                        mw.set_current_image_by_path(best_match, fallback_index=0)
                                        mw.highlight_image()
                                        QTimer.singleShot(100, mw.ensure_highlighted_visible)
                                    else:
                                        # Fallback to first image if no unlocked files found
                                        mw.set_current_image_by_path(displayed[0], fallback_index=0)
                                        mw.highlight_image()
                                        QTimer.singleShot(100, mw.ensure_highlighted_visible)
                            QTimer.singleShot(600, trigger_c)
                        
                        # Delay to ensure .prsort file is written to disk
                        QTimer.singleShot(300, do_reload_and_custom)
                        
                        # Restart thumbnails
                        if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
                            mw.cache_manager.background_loader.start()
                        
                        # Prepare message box content based on results
                        if highest_score is not None:
                            if len(new_displayed_images) > 0:
                                body_msg = (
                                    f"Found {len(new_displayed_images)} matching images.\n\n"
                                    f"Highest similarity score: {highest_score:.4f}\n"
                                )
                            else:
                                body_msg = (
                                    f"No images matched the search criteria.\n\n"
                                    f"Highest similarity score: {highest_score:.4f}\n"
                                )
                        else:
                            body_msg = (
                                f"No images matched the search criteria.\n\n"
                            )

                        threshold_msg = f"Threshold used: {threshold:.2f}"
                        if threshold_adjusted:
                            threshold_msg += f"\n⚠️ Threshold adjusted from {original_threshold:.2f}"
                        full_msg = f"Image Search Results\n\n{body_msg}{threshold_msg}"
                        # show_styled_information(mw, "Image Search Results", full_msg)
                        QTimer.singleShot(500, lambda: mw.status_notification.show_message(full_msg, duration=6000))
                        return
        
        # Files changed - open results in a new thumbnail level (all CLIP searches open new stack)
        if hasattr(mw, 'directory_stack_history_handler'):
            # Save current state before switching to search results
            mw.directory_stack_history_handler.save_current_state("image_browser_window._reorder_images_by_clip_search (non-recursive)", delay=0.0)
        
        # Set sort mode to CUSTOM BEFORE refresh_from_configuration
        # This ensures load_specific_files doesn't re-sort the CLIP search results
        mw.current_sort_mode = SortMode.CUSTOM
        mw.is_reversed = False  # Best matches at top = ascending order
        
        # CRITICAL: Write search results to .prsort file BEFORE refresh_from_configuration
        # This ensures apply_display_order can read the correct order from .prsort
        # Check if all search results are from the same directory
        if new_displayed_images:
            directories = set(os.path.dirname(path) for path in new_displayed_images if os.path.exists(path))
            if len(directories) == 1:
                directory = directories.pop()
                # Get locked files if any exist
                locked_files = set()
                if getattr(mw, 'lock_manager', None):
                    locked_files = mw.lock_manager.get_locked_files(directory)
                
                # Separate search results into locked and unlocked
                search_locked = []
                search_unlocked = []
                for path in new_displayed_images:
                    if os.path.exists(path) and os.path.dirname(path) == directory:
                        filename = os.path.basename(path)
                        if filename in locked_files:
                            search_locked.append(path)
                        else:
                            search_unlocked.append(path)
                
                # Get locked files in their saved order (if any)
                all_locked_paths = []
                if locked_files and getattr(mw, 'displayed_images', None):
                    # Get locked files from current display in their current order
                    filename_to_path = {os.path.basename(path): path for path in search_locked}
                    for path in mw.displayed_images:
                        filename = os.path.basename(path)
                        if filename in locked_files and filename in filename_to_path:
                            locked_path = filename_to_path[filename]
                            if locked_path not in all_locked_paths:
                                all_locked_paths.append(locked_path)
                
                # Build final order: locked files first (in saved order), then search results (unlocked only)
                combined_order = all_locked_paths + search_unlocked
                
                # Write to .prsort file to preserve search result order
                if combined_order:
                    mw.sorting_manager.write_prsort_file(
                        directory, combined_order, is_reversed=False, preserve_locks=True
                    )
        
        # Process search results as if they came from the API
        configuration = {'files': new_displayed_images, 'sort_mode': 'custom'}
        mw.refresh_from_configuration(configuration)
        
        # Save state AFTER load_specific_files has set specific_files_active
        # refresh_from_configuration skips state save when files are provided,
        # so we save the correct state here with specific_files set
        if hasattr(mw, 'directory_stack_history_handler'):
            mw.directory_stack_history_handler.save_current_state("image_browser_window._reorder_images_by_clip_search (non-recursive after load)", delay=0.0)
        
        # Highlight best match (first unlocked file if locked files exist, otherwise first result)
        # Use displayed_images after refresh_from_configuration (has locked files at top)
        displayed_images = mw.get_displayed_images()
        if displayed_images:
            best_match = mw._find_best_clip_match(displayed_images)
            if best_match:
                mw.set_current_image_by_path(best_match, fallback_index=0)
            else:
                # Fallback to first result if no unlocked files found
                mw.set_current_image_by_path(displayed_images[0], fallback_index=0)
        
        # Update status bar and menu to reflect sort mode
        mw.update_status_bar_sections()
        mw.update_sort_menu_checkmarks()
        mw.save_sorting_settings()
        
        # Highlight the image and scroll to show it (highlight_image does scroll_to_highlighted)
        mw.highlight_image()
        QTimer.singleShot(100, mw.ensure_highlighted_visible)

    # Restart thumbnail generation now that results are displayed
    if getattr(mw, 'cache_manager', None) and mw.cache_manager.background_loader:
        mw.cache_manager.background_loader.start()
    # Trigger thumbnail loading for the new results
    mw.start_background_thumbnail_loading_if_needed()
    
