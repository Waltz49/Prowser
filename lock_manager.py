#!/usr/bin/env python3
"""
Lock Manager
Handles file locking operations for organizing images within directories
"""

import os
from typing import List, Set, Optional, Dict, Tuple


class LockManager:
    """Manages file locking operations"""
    
    LOCK_PREFIX = '*'  # Prefix marker for locked files in .prsort
    
    _max_cache_size = 500  # Limit cache size for directories from recursive searches
    
    def __init__(self, main_window):
        """
        Initialize the lock manager
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
        """
        self.main_window = main_window
        # Cache for get_locked_files - in specific-files mode with many directories,
        # we paint many thumbnails and call is_file_locked for each, causing repeated
        # .prsort reads. Cache: directory -> (locked_files, prsort_mtime)
        self._locked_files_cache: Dict[str, Tuple[Set[str], float]] = {}
    
    def _invalidate_locked_cache(self, directory: str) -> None:
        """Invalidate cache for directory (call when .prsort is modified)"""
        if directory in self._locked_files_cache:
            del self._locked_files_cache[directory]
    
    def get_locked_files(self, directory: str) -> Set[str]:
        """
        Get set of locked filenames for a directory
        
        Args:
            directory: Directory path
            
        Returns:
            Set of locked filenames (basenames only)
        """
        prsort_path = os.path.join(directory, '.prsort')
        try:
            prsort_mtime = os.path.getmtime(prsort_path)
        except OSError:
            return set()
        
        # Check cache
        if directory in self._locked_files_cache:
            cached_files, cached_mtime = self._locked_files_cache[directory]
            if cached_mtime == prsort_mtime:
                return cached_files
            del self._locked_files_cache[directory]
        
        try:
            locked_files = set()
            with open(prsort_path, 'r', encoding='utf-8') as f:
                lines = [stripped for line in f if (stripped := line.strip())]
                if not lines:
                    return set()
                
                # Skip the warning comment if present
                if lines[0].startswith('# THIS FILE IS ONLY FOR') or lines[0].startswith('# THIS FILE MUST NOT BE USED'):
                    lines = lines[1:]
                    # Skip second line if it's also a warning comment
                    if lines and lines[0].startswith('# DO NOT USE'):
                        lines = lines[1:]
                
                # Skip header line if present
                start_idx = 1 if lines[0].startswith('#reversed:') else 0
                
                for line in lines[start_idx:]:
                    if line.startswith(self.LOCK_PREFIX):
                        # Remove prefix to get filename
                        filename = line[1:]  # Remove '*' prefix
                        locked_files.add(filename)
            
            # Cache result
            if len(self._locked_files_cache) >= self._max_cache_size:
                # Evict oldest (first) entry
                key_to_remove = next(iter(self._locked_files_cache))
                del self._locked_files_cache[key_to_remove]
            self._locked_files_cache[directory] = (locked_files, prsort_mtime)
            
            return locked_files
        except Exception as e:
            print(f"Error reading locked files from .prsort: {e}")
            return set()
    
    def is_file_locked(self, file_path: str) -> bool:
        """
        Check if a file is locked
        
        Args:
            file_path: Full path to the file
            
        Returns:
            True if file is locked, False otherwise
        """
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        locked_files = self.get_locked_files(directory)
        return filename in locked_files
    
    def lock_files(self, file_paths: List[str]) -> bool:
        """
        Lock selected files
        
        Args:
            file_paths: List of full file paths to lock
            
        Returns:
            True if successful, False otherwise
        """
        if not file_paths:
            return False
        
        # Check all files are in the same directory
        directories = set(os.path.dirname(path) for path in file_paths)
        if len(directories) > 1:
            if self.main_window.status_notification:
                self.main_window.status_notification.show_message("Cannot lock files from multiple directories")
            return False
        
        directory = directories.pop()
        
        # Get current lock status
        locked_files = self.get_locked_files(directory)
        
        # Add new files to locked set
        for file_path in file_paths:
            if os.path.exists(file_path):
                filename = os.path.basename(file_path)
                locked_files.add(filename)
        
        # CRITICAL: Save current displayed_images order to .prsort BEFORE updating locks
        # This ensures locked files are saved in their current order, not in some previous order
        displayed_images = self.main_window.get_displayed_images()
        if displayed_images:
            # Filter to only files from this directory
            directory_files = [path for path in displayed_images if os.path.dirname(path) == directory]
            if directory_files:
                # Get current is_reversed flag
                is_reversed = getattr(self.main_window, 'is_reversed', False)
                # Save current order to .prsort with lock markers
                # This preserves the current order of ALL files (locked and unlocked)
                return self._save_current_order_with_locks(directory, directory_files, locked_files, is_reversed)
        
        # Fallback: update .prsort file with new lock status (preserves existing order)
        return self._update_prsort_locks(directory, locked_files)
    
    def unlock_files(self, file_paths: List[str]) -> bool:
        """
        Unlock selected files
        
        Args:
            file_paths: List of full file paths to unlock
            
        Returns:
            True if successful, False otherwise
        """
        if not file_paths:
            return False
        
        # Check all files are in the same directory
        directories = set(os.path.dirname(path) for path in file_paths)
        if len(directories) > 1:
            if self.main_window.status_notification:
                self.main_window.status_notification.show_message("Cannot unlock files from multiple directories")
            return False
        
        directory = directories.pop()
        
        # Get current lock status
        locked_files = self.get_locked_files(directory)
        
        # Remove files from locked set
        for file_path in file_paths:
            if os.path.exists(file_path):
                filename = os.path.basename(file_path)
                locked_files.discard(filename)
        
        # Update .prsort file with new lock status
        return self._update_prsort_locks(directory, locked_files)
    
    def _save_current_order_with_locks(self, directory: str, file_paths: List[str], locked_files: Set[str], is_reversed: bool) -> bool:
        """
        Save current file order to .prsort with lock markers.
        This ensures locked files are saved in their current displayed order.
        
        Args:
            directory: Directory path
            file_paths: List of full file paths in their current order
            locked_files: Set of locked filenames
            is_reversed: Whether sort is reversed
            
        Returns:
            True if successful, False otherwise
        """
        prsort_path = os.path.join(directory, '.prsort')
        
        try:
            # Extract filenames from paths, preserving order
            filenames = [os.path.basename(path) for path in file_paths]
            
            # Write to .prsort file with lock markers
            with open(prsort_path, 'w', encoding='utf-8') as f:
                # CRITICAL WARNING: This file is ONLY for custom sort ordering and file locking
                # DO NOT use .prsort to order unlocked files - they preserve their visual order or use active sort mode
                f.write('# THIS FILE IS ONLY FOR CUSTOM SORT ORDERING AND FILE LOCKING\n')
                f.write('# DO NOT USE .prsort TO ORDER UNLOCKED FILES\n')
                # Write header
                f.write(f'#reversed:{str(is_reversed).lower()}\n')
                
                # Write filenames with lock prefix if locked, preserving current order
                for filename in filenames:
                    if filename in locked_files:
                        f.write(f'{self.LOCK_PREFIX}{filename}\n')
                    else:
                        f.write(f'{filename}\n')
                # CRITICAL: Flush to ensure file is written to disk before any subsequent reads
                f.flush()
                os.fsync(f.fileno())
            
            self._invalidate_locked_cache(directory)  # Cache now stale
            return True
        except Exception as e:
            print(f"Error saving current order with locks to .prsort file: {e}")
            return False
    
    def _update_prsort_locks(self, directory: str, locked_files: Set[str]) -> bool:
        """
        Update .prsort file with new lock status
        
        Args:
            directory: Directory path
            locked_files: Set of locked filenames
            
        Returns:
            True if successful, False otherwise
        """
        prsort_path = os.path.join(directory, '.prsort')
        
        # Read current .prsort file
        is_reversed = False
        all_filenames = []
        
        if os.path.exists(prsort_path):
            try:
                with open(prsort_path, 'r', encoding='utf-8') as f:
                    lines = [stripped for line in f if (stripped := line.strip())]
                    if lines:
                        # Skip the warning comment if present
                        if lines[0].startswith('# THIS FILE MUST NOT BE USED'):
                            lines = lines[1:]
                        
                        # Check first line for reversed flag
                        first_line = lines[0]
                        if first_line.startswith('#reversed:'):
                            is_reversed_str = first_line.split(':', 1)[1].lower()
                            is_reversed = is_reversed_str == 'true'
                            all_filenames = lines[1:]  # Skip header
                        else:
                            all_filenames = lines
                        
                        # Remove lock prefixes from existing entries
                        all_filenames = [line.lstrip(self.LOCK_PREFIX) for line in all_filenames]
            except Exception as e:
                print(f"Error reading .prsort file: {e}")
                return False
        
        # If no existing .prsort, get filenames from directory
        if not all_filenames:
            try:
                displayed = self.main_window.get_displayed_images()
                if displayed:
                    all_filenames = [os.path.basename(path) for path in displayed]
            except Exception:
                pass
        
        # Write updated .prsort file with lock markers
        try:
            with open(prsort_path, 'w', encoding='utf-8') as f:
                # CRITICAL WARNING: This file is ONLY for custom sort ordering and file locking
                # DO NOT use .prsort to order unlocked files - they preserve their visual order or use active sort mode
                f.write('# THIS FILE IS ONLY FOR CUSTOM SORT ORDERING AND FILE LOCKING\n')
                f.write('# DO NOT USE .prsort TO ORDER UNLOCKED FILES\n')
                # Write header
                f.write(f'#reversed:{str(is_reversed).lower()}\n')
                
                # Write filenames with lock prefix if locked
                for filename in all_filenames:
                    if filename in locked_files:
                        f.write(f'{self.LOCK_PREFIX}{filename}\n')
                    else:
                        f.write(f'{filename}\n')
            
            self._invalidate_locked_cache(directory)  # Cache now stale
            return True
        except Exception as e:
            print(f"Error writing .prsort file: {e}")
            return False
    
    def cleanup_orphaned_locks(self, directory: str) -> bool:
        """
        Remove orphaned lock entries for files that no longer exist
        
        Args:
            directory: Directory path
            
        Returns:
            True if cleanup was performed, False otherwise
        """
        prsort_path = os.path.join(directory, '.prsort')
        if not os.path.exists(prsort_path):
            return False
        
        try:
            is_reversed = False
            filenames = []
            
            with open(prsort_path, 'r', encoding='utf-8') as f:
                lines = [stripped for line in f if (stripped := line.strip())]
                if not lines:
                    return False
                
                # Check first line for reversed flag
                first_line = lines[0]
                if first_line.startswith('#reversed:'):
                    is_reversed_str = first_line.split(':', 1)[1].lower()
                    is_reversed = is_reversed_str == 'true'
                    filenames = lines[1:]  # Skip header
                else:
                    filenames = lines
            
            # Check which files still exist
            existing_files = set()
            if os.path.isdir(directory):
                for item in os.listdir(directory):
                    item_path = os.path.join(directory, item)
                    if os.path.isfile(item_path):
                        existing_files.add(item)
            
            # Filter out orphaned entries
            cleaned_filenames = []
            for line in filenames:
                filename = line.lstrip(self.LOCK_PREFIX)
                if filename in existing_files:
                    cleaned_filenames.append(line)
            
            # Only rewrite if we removed entries
            if len(cleaned_filenames) < len(filenames):
                with open(prsort_path, 'w', encoding='utf-8') as f:
                    f.write(f'#reversed:{str(is_reversed).lower()}\n')
                    for line in cleaned_filenames:
                        f.write(f'{line}\n')
                self._invalidate_locked_cache(directory)  # Cache now stale
                return True
            
            return False
        except Exception as e:
            print(f"Error cleaning up orphaned locks: {e}")
            return False
