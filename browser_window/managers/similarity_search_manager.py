#!/usr/bin/env python3
"""
Similarity Search Manager
Handles similarity search and CLIP text-based search functionality
"""

import os
from typing import List

from sort_mode import SortMode
from search.similarity_bootstrap import _import_cnn_modules


class SimilaritySearchManager:
    """Manages similarity search and CLIP text-based search operations"""
    
    def __init__(self, main_window):
        """
        Initialize the similarity search manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
        self.cnn_image_similarity_sorter = None
        self.cnn_similarity_ui_helper = None
        self._similarity_metric = None
        
    def _ensure_cnn_sorter_initialized(self):
        """Lazy initialize CNN similarity sorter if not already created"""
        if self.cnn_image_similarity_sorter is None:
            # Lazy import CNN modules
            CNNImageSimilaritySorter, _ = _import_cnn_modules()
            # Get current similarity metric from settings
            settings = self.main_window.config.load_settings()
            similarity_metric = settings.get('similarity_metric', 'cosine')
            if similarity_metric == 'clip':
                similarity_metric = 'cosine'
            self._similarity_metric = similarity_metric
            self.main_window._similarity_metric = similarity_metric
            clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
            resnet_model = settings.get('resnet_model', 'resnet18')
            self.cnn_image_similarity_sorter = CNNImageSimilaritySorter(
                similarity_metric=similarity_metric,
                cache_dir=self.main_window._similarity_cache_dir,
                clip_model_name=clip_model_name,
                resnet_model=resnet_model
            )
            # Store reference to main_window for background process coordination
            self.cnn_image_similarity_sorter.main_window = self.main_window
            self.main_window.cnn_image_similarity_sorter = self.cnn_image_similarity_sorter
    
    def _ensure_cnn_ui_helper_initialized(self):
        """Lazy initialize CNN similarity UI helper if not already created"""
        if self.cnn_similarity_ui_helper is None:
            # Lazy import CNN modules
            _, CNNSimilarityUIHelper = _import_cnn_modules()
            self.cnn_similarity_ui_helper = CNNSimilarityUIHelper(
                parent_widget=self.main_window, 
                config=self.main_window.config
            )
            self.main_window.cnn_similarity_ui_helper = self.cnn_similarity_ui_helper

    def reorder_images_by_similarity(self):
        from search.similarity_reorder import reorder_images_by_similarity
        reorder_images_by_similarity(self.main_window)

    def reorder_images_by_clip_search(self):
        from search.similarity_reorder import reorder_images_by_clip_search
        reorder_images_by_clip_search(self.main_window)
    
    def _rewrite_prsort_with_locked_at_top(self, search_results: List[str], directory: str) -> None:
        """
        Rewrite .prsort file with locked files at top (in their saved order) and search results below.
        This is used when we want to stay in directory mode instead of specific files mode.
        Works with or without locked files.
        
        Args:
            search_results: List of file paths from search (in search order)
            directory: Directory path
        """
        
        # Get locked files from directory (if lock manager exists)
        locked_files = set()
        if hasattr(self.main_window, 'lock_manager') and self.main_window.lock_manager:
            locked_files = self.main_window.lock_manager.get_locked_files(directory)
        
        # CRITICAL: Get ALL files in directory, not just search results
        # This ensures locked files are included even if they weren't in the search results
        if hasattr(self.main_window, 'directory_loader'):
            all_directory_files = self.main_window.directory_loader._get_current_directory_files()
        else:
            all_directory_files = self.main_window._get_current_directory_files()
        
        if not all_directory_files:
            return
        
        # Convert to list and filter to only files from this directory
        all_directory_paths = [path for path in all_directory_files if os.path.dirname(path) == directory]

        # Respect active filter pattern — only include files eligible for display
        if hasattr(self.main_window, 'sorting_manager'):
            all_directory_paths = self.main_window.sorting_manager.filter_images_by_pattern(all_directory_paths)
        if not all_directory_paths:
            return
        
        # Separate locked and unlocked files from ALL directory files
        all_locked_paths = []
        all_unlocked_paths = []
        
        for path in all_directory_paths:
            if os.path.exists(path):
                filename = os.path.basename(path)
                if filename in locked_files:
                    all_locked_paths.append(path)
                else:
                    all_unlocked_paths.append(path)
        
        # Separate search results into locked and unlocked
        search_locked = []
        search_unlocked = []
        
        for path in search_results:
            if os.path.exists(path) and os.path.dirname(path) == directory:
                filename = os.path.basename(path)
                if filename in locked_files:
                    search_locked.append(path)
                else:
                    search_unlocked.append(path)
        
        # Build final order based on whether we have locked files
        if locked_files:
            # CRITICAL: Get locked files in their CURRENT displayed order (before search)
            # This preserves their exact visual position, regardless of .prsort file state
            # Locked files MUST NOT CHANGE position - use current displayed_images order
            current_displayed = getattr(self.main_window, 'displayed_images', [])
            if current_displayed:
                # Get locked files from current display in their current order
                current_locked_order = []
                filename_to_path = {os.path.basename(path): path for path in all_locked_paths}
                
                # Extract locked files in their current displayed order
                for path in current_displayed:
                    filename = os.path.basename(path)
                    if filename in locked_files and filename in filename_to_path:
                        # Use the path from all_locked_paths (ensures it exists)
                        locked_path = filename_to_path[filename]
                        if locked_path not in current_locked_order:
                            current_locked_order.append(locked_path)
                
                # If we found locked files in current display, use that order
                if current_locked_order:
                    # Add any locked files not in current display at the end (shouldn't happen, but be safe)
                    current_locked_set = {os.path.basename(p) for p in current_locked_order}
                    for path in all_locked_paths:
                        if os.path.basename(path) not in current_locked_set:
                            current_locked_order.append(path)
                    all_locked_paths = current_locked_order
                else:
                    # Fallback: Get locked files in their saved order from .prsort
                    prsort_result = self.main_window.sorting_manager._read_prsort_file(directory)
                    if prsort_result:
                        prsort_filenames, _, _ = prsort_result
                        # Build ordered locked paths from .prsort order
                        ordered_locked = []
                        for filename in prsort_filenames:
                            if filename in filename_to_path:
                                ordered_locked.append(filename_to_path[filename])
                        # Add any locked files not in .prsort at the end
                        for path in all_locked_paths:
                            if path not in ordered_locked:
                                ordered_locked.append(path)
                        all_locked_paths = ordered_locked
            else:
                # No current display - use .prsort order as fallback
                prsort_result = self.main_window.sorting_manager._read_prsort_file(directory)
                if prsort_result:
                    prsort_filenames, _, _ = prsort_result
                    # Build ordered locked paths from .prsort order
                    filename_to_path = {os.path.basename(path): path for path in all_locked_paths}
                    ordered_locked = []
                    for filename in prsort_filenames:
                        if filename in filename_to_path:
                            ordered_locked.append(filename_to_path[filename])
                    # Add any locked files not in .prsort at the end
                    for path in all_locked_paths:
                        if path not in ordered_locked:
                            ordered_locked.append(path)
                    all_locked_paths = ordered_locked
            
            # Build final order: ALL locked files first (in saved order), then search results (unlocked only, in CLIP order),
            # then any unlocked files not in search results
            search_unlocked_set = set(search_unlocked)
            unlocked_not_in_search = [path for path in all_unlocked_paths if path not in search_unlocked_set]
            combined_order = all_locked_paths + search_unlocked + unlocked_not_in_search
        else:
            # No locked files: search results (in CLIP order) first, then other files not in search
            search_results_set = set(search_results)
            files_not_in_search = [path for path in all_unlocked_paths if path not in search_results_set]
            combined_order = search_unlocked + files_not_in_search
        
        
        # Write to .prsort file
        # CRITICAL: Always write is_reversed=False to preserve exact order
        # Locked files are already in their correct order from displayed_images
        # CRITICAL: We use preserve_locks=True to preserve locks from existing .prsort,
        # but we've already ensured all locked files from lock_manager are in combined_order
        # The write_prsort_file method will mark files as locked if they're in the existing .prsort
        # If a file is locked in lock_manager but not in existing .prsort, we need to ensure it's marked
        # So we'll write with preserve_locks=True, then update locks from lock_manager if needed
        is_reversed = False
        result = self.main_window.sorting_manager.write_prsort_file(
            directory, combined_order, is_reversed, preserve_locks=True
        )
        
        if not result:
            return
        
        # CRITICAL: Ensure all locked files from lock_manager are marked as locked in .prsort
        # This handles the case where a file is locked in lock_manager but not in existing .prsort
        if locked_files and hasattr(self.main_window, 'lock_manager') and self.main_window.lock_manager:
            # Update .prsort to ensure all locked files from lock_manager are marked
            self.main_window.lock_manager._update_prsort_locks(directory, locked_files)
        
        # CRITICAL: Flush filesystem to ensure .prsort is written to disk
        import sys
        sys.stdout.flush()
        if hasattr(os, 'sync'):
            try:
                os.sync()
            except:
                pass
        
        # Set sort mode to CUSTOM and ensure is_reversed=False
        # This ensures locked files maintain their exact position
        self.main_window.current_sort_mode = SortMode.CUSTOM
        self.main_window.is_reversed = False
        self.main_window.save_sorting_settings()
    
