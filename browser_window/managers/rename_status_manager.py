#!/usr/bin/env python3
"""
Rename Status Manager for Image Browser
Handles scanning directories to check if files match rename pattern and are sequential
"""

import os
import json
import re
import fnmatch
from pathlib import Path
from typing import Dict, Optional, Set, List
from config import get_config, ImageBrowserConfig
from thumbnails.thumbnail_constants import get_image_extensions


class RenameStatusManager:
    """Manages rename status checking and storage"""
    
    def __init__(self):
        self.config = get_config()
        self.status_file = self.config.data_dir / "rename_status.json"
        self._status_cache: Dict[str, bool] = {}
        self._enabled = False
        
    def is_enabled(self) -> bool:
        """Check if rename status checking is enabled"""
        return self._enabled
    
    def set_enabled(self, enabled: bool):
        """Enable or disable rename status checking"""
        self._enabled = enabled
        if not enabled:
            self._status_cache.clear()
            self._clear_status_file()
    
    def _clear_status_file(self):
        """Clear the status file"""
        try:
            if self.status_file.exists():
                self.status_file.unlink()
        except Exception:
            pass
    
    def _load_status_file(self) -> Dict[str, bool]:
        """Load status from file"""
        if not self.status_file.exists():
            return {}
        try:
            with open(self.status_file, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    
    def _save_status_file(self, status: Dict[str, bool]):
        """Save status to file"""
        try:
            with open(self.status_file, 'w') as f:
                json.dump(status, f)
        except Exception:
            pass
    
    def get_directory_status(self, directory: str) -> Optional[bool]:
        """Get rename status for a directory. Returns True if valid, False if invalid, None if not checked"""
        if not self._enabled:
            return None
        
        # Normalize directory path
        directory = os.path.normpath(directory)
        
        # Check cache first (cache only contains directories that have been explicitly checked)
        if directory in self._status_cache:
            status = self._status_cache[directory]
            # Only return True if explicitly True (valid), return None if False (invalid but checked)
            # Actually, we should return the status as-is: True=valid, False=invalid, None=not checked
            return status
        
        # Don't load from file automatically - only use cache
        # File is used for persistence across sessions, but we only load it when explicitly enabled
        # This ensures we don't show checkmarks for directories that haven't been checked in this session
        return None
    
    def _extract_number_from_filename(self, filename: str, prefix: str, 
                                      increment_length: int) -> Optional[int]:
        """Extract the number from filename based on rename pattern.
        Supports both formats: prefix-number.ext and prefixnumber.ext"""
        # Filename format: "{prefix}-{number:0{width}d}{ext}" or "{prefix}{number:0{width}d}{ext}"
        # Example: "image-001.jpg" or "image001.jpg" where prefix="image", increment_length=3
        
        name_without_ext, ext = os.path.splitext(filename)
        
        # Try pattern with dash first: prefix-number
        pattern_regex = rf'^{re.escape(prefix)}-(\d+)$'
        match = re.match(pattern_regex, name_without_ext)
        if match:
            try:
                number_str = match.group(1)
                # Check if number has exactly the correct number of digits (must match increment_length)
                if len(number_str) == increment_length:
                    number = int(number_str)
                    return number
            except (IndexError, ValueError):
                pass
        
        # Try pattern without dash: prefixnumber
        pattern_regex = rf'^{re.escape(prefix)}(\d+)$'
        match = re.match(pattern_regex, name_without_ext)
        if match:
            try:
                number_str = match.group(1)
                # Check if number has exactly the correct number of digits (must match increment_length)
                if len(number_str) == increment_length:
                    number = int(number_str)
                    return number
            except (IndexError, ValueError):
                pass
        
        return None
    
    def _check_directory_status(self, directory: str, rename_prefix_template: str,
                                increment_length: int, filter_pattern: str, 
                                extensions: List[str]) -> bool:
        """
        #############################################################################################
        # "Show rename status" Check - What This Function Does:
        #
        # This function checks if files in a directory meet ALL of the following criteria:
        #
        # 1. FILTER PATTERN MATCH: If a filter pattern is set (e.g., 'image*'), only files matching
        #    that pattern are considered. The matching is case-sensitive.
        #
        # 2. RENAME PATTERN MATCH: Files must match the rename pattern format:
        #    - Format: "{prefix}-{number:0{width}d}{ext}" or "{prefix}{number:0{width}d}{ext}"
        #    - Example: "image-Downloads-0001.webp" where prefix="image-Downloads", increment_length=4
        #    - The prefix comes from rename_prefix_template with %d/%D replaced by directory name
        #
        # 3. NUMBER LENGTH: The number portion must have exactly 'increment_length' digits.
        #    - Example: If increment_length=4, numbers must be 0001, 0002, etc. (not 1, 2, or 001, 002)
        #
        # 4. SEQUENTIAL NUMBERS: All numbers must be sequential with no gaps, starting from the lowest.
        #    - Example: If files have numbers [1, 2, 3, 5], this fails (missing 4).
        #    - Example: If files have numbers [1, 2, 3, 4], this passes.
        #
        # The checkmark appears ONLY when ALL files matching the filter pattern also match the rename
        # pattern, have correct-length numbers, and are sequential. Files that don't match the filter
        # pattern are ignored entirely.
        #
        # IMPORTANT: When a filter pattern is set, files matching the filter MUST still match the
        # rename pattern. The filter pattern doesn't bypass the rename pattern requirement.
        #############################################################################################
        """
        if not os.path.isdir(directory):
            return False
        
        # Get directory name for prefix substitution
        dirname = os.path.basename(directory.rstrip(os.sep))
        if not dirname:
            dirname = "directory"
        
        # Replace %d and %D with directory name to get actual prefix (rename_custom_prefix format)
        # e.g. "imagegen-%d" + dirname "cell" -> "imagegen-cell" (expects imagegen-cell-0001.jpg)
        # e.g. "imagegen" (no %d) -> "imagegen" (expects imagegen-0001.jpg)
        if '%d' in rename_prefix_template or '%D' in rename_prefix_template:
            prefix = rename_prefix_template.replace('%d', dirname).replace('%D', dirname)
        elif '{number:' in rename_prefix_template:
            # Legacy rename_prefix_template format: "image-{number:04d}" -> "image-<dirname>-"
            base = rename_prefix_template.split('{number:')[0].rstrip('-')
            prefix = base + '-' + dirname + '-'
        else:
            # Simple prefix without placeholders: "imagegen" -> "imagegen" (files: imagegen-0001.jpg)
            prefix = rename_prefix_template.rstrip('-') if rename_prefix_template else 'image'
        
        # Get all files in directory
        try:
            files = [f for f in os.listdir(directory) 
                    if os.path.isfile(os.path.join(directory, f))]
        except Exception:
            return False
        
        # Normalize extensions to have leading dot for comparison (handles config with "jpg" vs ".jpg")
        ext_set = set()
        for ext in extensions:
            e = (ext or "").strip().lower()
            if e and not e.startswith('.'):
                e = '.' + e
            if e:
                ext_set.add(e)
        if not ext_set:
            ext_set = {'.jpg', '.jpeg', '.png', '.webp'}  # fallback
        
        # Only consider supported image files - ignore .txt, .pdf, .json, etc.
        image_files = [f for f in files 
                      if os.path.splitext(f)[1].lower() in ext_set]
        
        if not image_files:
            return False
        
        # Filter by filter pattern if provided (case-sensitive)
        # Only check files that match the filter pattern
        if filter_pattern and filter_pattern != '*':
            # Use ImageBrowserConfig to properly normalize the pattern for matching
            match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)
            if match_pattern:
                image_files = [f for f in image_files 
                              if fnmatch.fnmatch(f, match_pattern)]
        
        if not image_files:
            return False
        
        # Check if all files matching the filter pattern ALSO match the rename pattern
        # and have numbers of the correct length
        numbers = []
        for filename in image_files:
            # Always check rename pattern - filter pattern doesn't bypass this requirement
            number = self._extract_number_from_filename(filename, prefix, increment_length)
            
            if number is None:
                # File matches filter pattern but doesn't match rename pattern
                # This is a failure - all filtered files must match rename pattern
                return False
            
            numbers.append(number)
        
        if not numbers:
            # No files with valid numbers found
            return False
        
        # Check if numbers are sequential with no gaps starting from lowest
        numbers.sort()
        min_number = numbers[0]
        expected_numbers = set(range(min_number, min_number + len(numbers)))
        actual_numbers = set(numbers)
        
        return expected_numbers == actual_numbers
    
    def scan_directory_tree(self, root_directory: str, max_depth: int, 
                           rename_prefix_template: str, increment_length: int,
                           filter_pattern: str, extensions: List[str],
                           visible_directories: Optional[List[str]] = None) -> Dict[str, bool]:
        """Scan directory tree and check rename status for each directory.
        
        If visible_directories is provided, only scan those directories (and their immediate children up to max_depth).
        Otherwise, scan recursively from root_directory.
        """
        status_map: Dict[str, bool] = {}
        
        if visible_directories:
            # Only scan visible directories and their immediate children (up to max_depth)
            for directory in visible_directories:
                if not os.path.isdir(directory):
                    continue
                
                # Check this directory
                is_valid = self._check_directory_status(
                    directory, rename_prefix_template, increment_length, 
                    filter_pattern, extensions
                )
                status_map[directory] = is_valid
                
                # Scan immediate children (depth 1 only for visible directories)
                try:
                    for entry in os.listdir(directory):
                        subdir = os.path.join(directory, entry)
                        if os.path.isdir(subdir):
                            # Only check immediate children, not deeper
                            child_is_valid = self._check_directory_status(
                                subdir, rename_prefix_template, increment_length,
                                filter_pattern, extensions
                            )
                            status_map[subdir] = child_is_valid
                except Exception:
                    pass
        else:
            # Original recursive scanning behavior
            def scan_recursive(directory: str, current_depth: int):
                if current_depth > max_depth:
                    return
                
                if not os.path.isdir(directory):
                    return
                
                # Check this directory
                is_valid = self._check_directory_status(
                    directory, rename_prefix_template, increment_length, 
                    filter_pattern, extensions
                )
                status_map[directory] = is_valid
                
                # Recursively scan subdirectories
                try:
                    for entry in os.listdir(directory):
                        subdir = os.path.join(directory, entry)
                        if os.path.isdir(subdir):
                            scan_recursive(subdir, current_depth + 1)
                except Exception:
                    pass
            
            scan_recursive(root_directory, 0)
        
        return status_map
    
    def update_status_for_directory_tree(self, root_directory: str, max_depth: int,
                                        rename_prefix_template: str, increment_length: int,
                                        filter_pattern: str, extensions: List[str],
                                        visible_directories: Optional[List[str]] = None):
        """Update status for directory tree and save to file"""
        if not self._enabled:
            return
        
        # Scan directory tree (only visible directories if provided)
        status_map = self.scan_directory_tree(
            root_directory, max_depth, rename_prefix_template, increment_length,
            filter_pattern, extensions, visible_directories
        )
        
        # Update cache - only store True values (valid directories)
        # False values mean checked but invalid, so we don't need to remember them
        for directory, status in status_map.items():
            if status is True:
                self._status_cache[directory] = True
            elif directory in self._status_cache:
                # Remove from cache if it was previously valid but is now invalid
                del self._status_cache[directory]
        
        # Load existing status and merge - only keep True values
        existing_status = self._load_status_file()
        # Only keep True values from existing status
        existing_status = {dir_path: status for dir_path, status in existing_status.items() if status is True}
        # Add new True values from scan
        existing_status.update({dir_path: status for dir_path, status in status_map.items() if status is True})
        
        # Save to file - only save True values (valid directories)
        self._save_status_file(existing_status)
    
    def load_all_status(self):
        """Load all status from file into cache"""
        if not self._enabled:
            return
        # Load from file - this restores status from previous session
        # But we only show checkmarks for directories that are explicitly True
        file_status = self._load_status_file()
        # Only load True values (valid directories) - don't load False values
        # This ensures we only show checkmarks for directories that were valid when last checked
        self._status_cache = {dir_path: status for dir_path, status in file_status.items() if status is True}
    
    def clear_all_status(self):
        """Clear all status (called at startup/shutdown)"""
        self._status_cache.clear()
        self._clear_status_file()

