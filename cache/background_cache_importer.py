#!/usr/bin/env python3
"""
Background Cache Importer
Imports CLIP cache files written by the background process into the main app's cache.
"""

import json
import os
import fcntl
import time
from pathlib import Path
from typing import Optional, Set, Callable
from PySide6.QtCore import QObject, QTimer, Signal, QMutexLocker
from PySide6.QtWidgets import QApplication

from config import get_config


class BackgroundCacheImporter(QObject):
    """Imports cache files written by background CLIP process"""
    
    cache_imported = Signal(int)  # number of files imported
    
    def __init__(self, main_window, parent=None):
        """
        Initialize background cache importer
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
            parent: Parent QObject
        """
        super().__init__(parent)
        self.main_window = main_window
        self.config = get_config()
        self.cache_dir = self.config.image_recognition_cache_dir
        
        # Background index file
        self.background_index_file = self.cache_dir / "clip_index_background.json"
        
        # Track imported files to avoid re-importing
        self.imported_files: Set[Path] = set()
        
        # Periodic import timer
        self.import_timer = QTimer()
        self.import_timer.timeout.connect(self.import_periodic)
        self.import_timer.setInterval(30000)  # 30 seconds
        self.import_timer.start()
    
    def start(self):
        """Start periodic imports"""
        self.import_timer.start()
    
    def stop(self):
        """Stop periodic imports"""
        self.import_timer.stop()
    
    def clear_imported_tracking(self):
        """Clear imported files tracking. Call when cache is cleared so new files will be re-imported."""
        self.imported_files.clear()
    
    def clear_imported_for_dir_hash(self, dir_hash: str):
        """Remove a directory's cache file from imported tracking so it will be re-imported when background worker writes it"""
        if not hasattr(self.main_window, 'cnn_image_similarity_sorter') or not self.main_window.cnn_image_similarity_sorter:
            return
        if not self.main_window.cnn_image_similarity_sorter.feature_cache:
            return
        clip_cache_dir = self.main_window.cnn_image_similarity_sorter.feature_cache.clip_cache_dir
        path_to_remove = clip_cache_dir / f"{dir_hash}.npz"
        self.imported_files.discard(path_to_remove)
    
    def import_all_pending(self, progress_callback: Optional[Callable[[str], None]] = None) -> int:
        """
        Import all pending background cache files immediately.
        Used before mass rename operations.
        
        Args:
            progress_callback: Optional callable(message) for UI updates
        
        Returns:
            Number of files imported
        """
        if not hasattr(self.main_window, 'cnn_image_similarity_sorter') or not self.main_window.cnn_image_similarity_sorter:
            return 0
        
        cnn_sorter = self.main_window.cnn_image_similarity_sorter
        if not cnn_sorter.feature_cache:
            return 0
        
        feature_cache = cnn_sorter.feature_cache
        clip_cache_dir = feature_cache.clip_cache_dir
        
        if not clip_cache_dir.exists():
            return 0
        
        imported_count = 0
        
        # Find all .npz files in clip cache directory
        current_time = time.time()
        npz_files = list(clip_cache_dir.glob("*.npz"))
        total_npz = len(npz_files)
        for file_idx, npz_file in enumerate(npz_files):
            if progress_callback and file_idx % 25 == 0:
                progress_callback(f"Importing background cache... ({file_idx}/{total_npz})")
                app = QApplication.instance()
                if app is not None:
                    app.processEvents()
            # Check if we've already imported this file
            if npz_file in self.imported_files:
                continue
            
            # SAFEGUARD: Skip files modified very recently (within last 1 second)
            # These might still be in the process of being written by background process
            # This prevents reading partially written files even with atomic writes
            try:
                file_mtime = npz_file.stat().st_mtime
                if current_time - file_mtime < 1.0:
                    # File was modified less than 1 second ago, skip it to avoid race condition
                    continue
            except Exception:
                # If we can't get mtime, skip the file to be safe
                continue
            
            # For import_all_pending (used before mass rename), import all files
            # For periodic import, only import files modified recently
            # We'll check mtime in import_periodic, not here
            
            # Extract directory hash from filename
            dir_hash = npz_file.stem
            
            # Clear from loaded_dirs to force reload of updated cache file
            # This ensures new features written by background worker are picked up
            with QMutexLocker(feature_cache.cache_mutex):
                feature_cache._clip_loaded_dirs.discard(dir_hash)
            
            # Import the cache file
            try:
                feature_cache._load_directory_cache('clip', dir_hash)
                self.imported_files.add(npz_file)
                imported_count += 1
            except Exception as e:
                print(f"Error importing cache file {npz_file}: {e}")
                continue
        
        # Merge index files if background index exists
        if self.background_index_file.exists():
            self._merge_index_files(feature_cache)
        
        if imported_count > 0:
            self.cache_imported.emit(imported_count)
        
        return imported_count
    
    def import_periodic(self):
        """Periodic import (called by timer) - only imports recent files"""
        if not hasattr(self.main_window, 'cnn_image_similarity_sorter') or not self.main_window.cnn_image_similarity_sorter:
            return
        
        cnn_sorter = self.main_window.cnn_image_similarity_sorter
        if not cnn_sorter.feature_cache:
            return
        
        feature_cache = cnn_sorter.feature_cache
        clip_cache_dir = feature_cache.clip_cache_dir
        
        if not clip_cache_dir.exists():
            return
        
        imported_count = 0
        
        # Find all .npz files in clip cache directory
        for npz_file in clip_cache_dir.glob("*.npz"):
            # Check if we've already imported this file
            if npz_file in self.imported_files:
                continue
            
            # Only import files modified in last minute (periodic import)
            mtime = npz_file.stat().st_mtime
            if time.time() - mtime > 60:
                continue
            
            # Extract directory hash from filename
            dir_hash = npz_file.stem
            
            # Clear from loaded_dirs to force reload of updated cache file
            # This ensures new features written by background worker are picked up
            with QMutexLocker(feature_cache.cache_mutex):
                feature_cache._clip_loaded_dirs.discard(dir_hash)
            
            # Import the cache file
            try:
                feature_cache._load_directory_cache('clip', dir_hash)
                self.imported_files.add(npz_file)
                imported_count += 1
            except Exception as e:
                print(f"Error importing cache file {npz_file}: {e}")
                continue
        
        # Merge index files if background index exists
        if self.background_index_file.exists():
            self._merge_index_files(feature_cache)
        
        if imported_count > 0:
            self.cache_imported.emit(imported_count)
    
    def _merge_index_files(self, feature_cache):
        """
        Merge background index file into main index file with file locking.
        
        Args:
            feature_cache: FeatureCacheManager instance
        """
        main_index_file = feature_cache.clip_index_file
        
        if not self.background_index_file.exists():
            return
        
        # Acquire lock on main index file
        lock_file = main_index_file.with_suffix('.lock')
        
        try:
            # Create lock file if it doesn't exist
            lock_file.touch(exist_ok=True)
            
            with open(lock_file, 'r+') as lock_fd:
                # Acquire exclusive lock
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                
                try:
                    # Read main index
                    main_index = {}
                    if main_index_file.exists():
                        try:
                            with open(main_index_file, 'r', encoding='utf-8') as f:
                                main_index = json.load(f)
                        except Exception:
                            main_index = {}
                    
                    # Read background index
                    background_index = {}
                    try:
                        with open(self.background_index_file, 'r', encoding='utf-8') as f:
                            background_index = json.load(f)
                    except Exception:
                        background_index = {}
                    
                    # Merge (background entries override main for same paths)
                    merged_index = {**main_index, **background_index}
                    
                    # Identify directories with new entries from background index
                    # These need to be cleared from _clip_loaded_dirs so they reload
                    dirs_to_reload = set()
                    for path, entry in background_index.items():
                        dir_hash = entry.get('dir_hash')
                        if dir_hash:
                            dirs_to_reload.add(dir_hash)
                    
                    # Clear directories with new entries from loaded_dirs
                    # This ensures get_clip_feature() will reload these directories
                    # and pick up the new features written by background worker
                    with QMutexLocker(feature_cache.cache_mutex):
                        for dir_hash in dirs_to_reload:
                            feature_cache._clip_loaded_dirs.discard(dir_hash)
                    
                    # Write merged index atomically
                    import tempfile
                    import shutil
                    temp_dir = tempfile.mkdtemp(prefix="clip_index_merge_")
                    temp_file = Path(temp_dir) / "index.json"
                    
                    try:
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            json.dump(merged_index, f, indent=2)
                        
                        temp_file.replace(main_index_file)
                    finally:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    
                    # Delete background index file after successful merge
                    try:
                        self.background_index_file.unlink()
                    except Exception:
                        pass
                
                finally:
                    # Release lock
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        
        except Exception as e:
            print(f"Error merging index files: {e}")
            import traceback
            traceback.print_exc()
