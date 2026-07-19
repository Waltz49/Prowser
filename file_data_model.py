#!/usr/bin/env python3
"""
File Data Model Manager
Centralizes management of displayed_images and ensures UI consistency.
This provides a single source of truth for file data displayed in thumbnails and tree views.

Navigation contract (read before changing current image / index):
- Source of truth: _current_image_path and _displayed_images; _current_index is derived.
- Prefer set_current_image_path(path) when the path is known (thumbnail widget path, tree
  selection, browse navigation). It syncs index when the path is in displayed_images.
- Use set_current_index(index) only when the index into displayed_images is authoritative
  (e.g. keyboard move in thumbnail grid). It updates current_image_path from displayed_images.
- Never set index from a canvas/visual slot index; that index may not match displayed_images
  (see mvc_controller._on_thumbnail_clicked).
- Multi-select lives on ImageBrowserWindow.selected_files; it does not replace current path.
- Reads: use get_current_image_path() / get_current_index(); avoid parallel caches.
"""

import os
from typing import List, Optional, Callable

from PySide6.QtCore import QObject, Signal, QMutexLocker, QRecursiveMutex

# Skip per-path os.path.exists when the caller already validated paths (large directory loads).
_VALIDATE_EXISTS_MAX = 500


def normalize_file_path(path: str) -> str:
    """Canonical absolute path for file lists (display order, lock matching)."""
    return os.path.abspath(os.path.expanduser(path))


class FileDataModel(QObject):
    """
    Centralized model for managing displayed file data.
    Ensures UI always reflects current data without increasing disk access.
    """
    
    # Signals emitted when data changes
    displayed_images_changed = Signal(list)  # New displayed_images list
    current_image_changed = Signal(str)  # New current_image_path
    directory_changed = Signal(str)  # New current_directory
    current_index_changed = Signal(int)  # Index of focused image in displayed_images
    view_mode_changed = Signal(str)  # 'thumbnail' | 'list' | 'browse' | 'slideshow' | etc.
    
    def __init__(self):
        super().__init__()
        
        # Core data - single source of truth
        self._displayed_images: List[str] = []
        self._current_image_path: Optional[str] = None
        self._current_directory: Optional[str] = None
        self._current_index: int = 0  # Unified highlight_index/current_index
        self._current_view_mode: str = 'thumbnail'
        
        # Thread safety (recursive: slots may call get_* while holding lock)
        self._mutex = QRecursiveMutex()
        
        # Listeners for updates (for tree view synchronization, etc.)
        self._update_listeners: List[Callable] = []

    def add_update_listener(self, callback: Callable) -> None:
        """Register a callback to be notified when model data changes"""
        self._update_listeners.append(callback)
    
    def get_displayed_images(self) -> List[str]:
        """Get current displayed images list (thread-safe)"""
        with QMutexLocker(self._mutex):
            return self._displayed_images.copy()
    
    def set_displayed_images(self, images: List[str], notify: bool = True, *, validate_exists: Optional[bool] = None):
        """
        Set displayed images list.
        
        Args:
            images: List of image file paths
            notify: If True, emit signals and notify listeners
            validate_exists: When False, skip os.path.exists per path (faster for
                large lists from directory scans). Default: True for lists up to
                _VALIDATE_EXISTS_MAX entries.
        """
        with QMutexLocker(self._mutex):
            check_exists = (
                validate_exists
                if validate_exists is not None
                else len(images) <= _VALIDATE_EXISTS_MAX
            )
            normalized_images = []
            for img in images:
                if img and isinstance(img, str):
                    try:
                        abs_path = normalize_file_path(img)
                        if not check_exists or os.path.exists(abs_path):
                            normalized_images.append(abs_path)
                    except Exception:
                        continue
            
            # Only update if changed
            if normalized_images != self._displayed_images:
                old_index = self._current_index
                self._displayed_images = normalized_images
                # Clamp current_index to valid range
                n = len(self._displayed_images)
                if n == 0:
                    self._current_index = 0
                    self._current_image_path = None
                elif self._current_index >= n:
                    self._current_index = n - 1
                    self._current_image_path = self._displayed_images[self._current_index]
                
                if notify:
                    self.displayed_images_changed.emit(self._displayed_images.copy())
                    if self._current_index != old_index:
                        self.current_index_changed.emit(self._current_index)
                    if self._current_image_path:
                        self.current_image_changed.emit(self._current_image_path)
                    self._notify_listeners()
    
    def get_current_image_path(self) -> Optional[str]:
        """Get current image path (thread-safe)"""
        with QMutexLocker(self._mutex):
            return self._current_image_path

    def get_current_directory(self) -> Optional[str]:
        """Get current directory (thread-safe)"""
        with QMutexLocker(self._mutex):
            return self._current_directory
    
    def set_current_image_path(self, path: Optional[str], notify: bool = True):
        """
        Set current image path.
        
        Args:
            path: Path to current image file
            notify: If True, emit signals and notify listeners
        """
        with QMutexLocker(self._mutex):
            if path:
                abs_path = os.path.abspath(os.path.expanduser(path))
                if not os.path.exists(abs_path):
                    # Path doesn't exist - don't set it
                    return
                new_path = abs_path
            else:
                new_path = None
            
            if new_path != self._current_image_path:
                self._current_image_path = new_path
                # Sync current_index from path if path is in displayed_images
                if new_path and new_path in self._displayed_images:
                    idx = self._displayed_images.index(new_path)
                    if idx != self._current_index:
                        self._current_index = idx
                
                if notify:
                    if new_path:
                        self.current_image_changed.emit(new_path)
                    if new_path and new_path in self._displayed_images:
                        self.current_index_changed.emit(self._current_index)
                    self._notify_listeners()
    
    def set_current_directory(self, directory: Optional[str], notify: bool = True):
        """
        Set current directory.
        
        Args:
            directory: Path to current directory
            notify: If True, emit signals and notify listeners
        """
        with QMutexLocker(self._mutex):
            if directory:
                abs_dir = os.path.abspath(os.path.expanduser(directory))
                if not os.path.isdir(abs_dir):
                    # Directory doesn't exist - don't set it
                    return
                new_dir = abs_dir
            else:
                new_dir = None
            
            if new_dir != self._current_directory:
                self._current_directory = new_dir
                
                if notify and new_dir:
                    self.directory_changed.emit(new_dir)
                    self._notify_listeners()
    
    def get_current_index(self) -> int:
        """Get current index (thread-safe). Clamped to valid range."""
        with QMutexLocker(self._mutex):
            n = len(self._displayed_images)
            if n == 0:
                return 0
            return max(0, min(self._current_index, n - 1))
    
    def set_current_index(self, index: int, notify: bool = True):
        """
        Set current index (focused image in displayed_images).
        Clamps to valid range. Updates current_image_path to match.
        
        Args:
            index: Index in displayed_images
            notify: If True, emit signals and notify listeners
        """
        with QMutexLocker(self._mutex):
            n = len(self._displayed_images)
            new_index = max(0, min(index, n - 1)) if n > 0 else 0
            
            if new_index != self._current_index:
                self._current_index = new_index
                # Sync current_image_path from displayed_images
                if n > 0 and 0 <= new_index < n:
                    new_path = self._displayed_images[new_index]
                    if new_path != self._current_image_path:
                        self._current_image_path = new_path
                
                if notify:
                    self.current_index_changed.emit(new_index)
                    if n > 0 and 0 <= new_index < n:
                        self.current_image_changed.emit(self._displayed_images[new_index])
                    self._notify_listeners()
    
    def get_current_view_mode(self) -> str:
        """Get current view mode (thread-safe)"""
        with QMutexLocker(self._mutex):
            return self._current_view_mode
    
    def set_current_view_mode(self, mode: str, notify: bool = True):
        """
        Set current view mode.
        
        Args:
            mode: 'thumbnail' | 'list' | 'browse' | 'slideshow' | 'slideshow2' | 'slideshow3'
            notify: If True, emit signals and notify listeners
        """
        with QMutexLocker(self._mutex):
            if mode != self._current_view_mode:
                self._current_view_mode = mode
                if notify:
                    self.view_mode_changed.emit(mode)
                    self._notify_listeners()
    
    def clear(self, notify: bool = True):
        """Clear all data"""
        with QMutexLocker(self._mutex):
            self._displayed_images = []
            self._current_image_path = None
            self._current_index = 0
            # Don't clear current_directory - it's useful to remember where we were
        
        if notify:
            self.displayed_images_changed.emit([])
            if self._current_image_path:
                self.current_image_changed.emit(None)
            self._notify_listeners()
    
    def _notify_listeners(self):
        """Notify all registered listeners of data changes"""
        for listener in self._update_listeners:
            try:
                listener()
            except Exception:
                # Don't let listener errors break the model
                import traceback
                traceback.print_exc()
    
    
