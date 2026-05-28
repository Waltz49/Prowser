#!/usr/bin/env python3
"""
Feature Cache Manager
Handles persistent caching of CNN and CLIP image features for similarity search
Uses directory-based cache splitting for efficient incremental saves
"""

import json
import os
import hashlib
import tempfile
import uuid
import time
import shutil
import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    import torch

from idle_and_cache_constants import FEATURE_CACHE_UNLOAD_TIMEOUT_SECONDS


class FeatureCacheManager:
    """Manages persistent caching of CNN and CLIP image features"""
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        clip_model_name: Optional[str] = None,
        resnet_model_name: Optional[str] = None,
        sorter_reference=None,
        threading_backend: bool = False,
    ):
        """
        Initialize feature cache manager
        
        Args:
            cache_dir: Path to cache directory (default: ~/.prowser/cache/image_recognition/)
            clip_model_name: CLIP model name for model-specific cache (default: from config)
            resnet_model_name: ResNet model name for model-specific CNN cache (default: from config)
            sorter_reference: Optional CNNImageSimilaritySorter for model unload
            threading_backend: If True, use threading.Lock and threading.Timer (non-Qt worker).
        """
        if cache_dir is None:
            from config import get_config
            config = get_config()
            cache_dir = config.image_recognition_cache_dir
        
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Get clip_model_name from config if not provided
        if clip_model_name is None:
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
        
        # Normalize clip_model_name: if it's a filesystem path, extract the model identifier
        # This ensures cache directory names are consistent regardless of where the model is cached
        original_clip_model_name = clip_model_name
        if clip_model_name.startswith('/') or '/Users' in clip_model_name or '/.cache' in clip_model_name:
            # It's a path - extract model identifier from HuggingFace cache path pattern
            import re
            match = re.search(r'models--([^/]+)/snapshots', clip_model_name)
            if match:
                # Convert models--org--model-name back to org/model-name
                clip_model_name = match.group(1).replace('--', '/')
            else:
                # Fallback: get from config
                from config import get_config
                config = get_config()
                settings = config.load_settings()
                clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
        
        self.clip_model_name = clip_model_name

        self._original_clip_model_name = original_clip_model_name  # Keep original for model loading
        
        # Get resnet_model_name from config if not provided
        if resnet_model_name is None:
            from config import get_config
            config = get_config()
            settings = config.load_settings()
            resnet_model_name = settings.get('resnet_model', 'resnet18')
        
        self.resnet_model_name = resnet_model_name
        
        # Sanitize model names for filenames
        resnet_model_safe = resnet_model_name.replace('/', '_').replace('\\', '_')
        clip_model_safe = clip_model_name.replace('/', '_').replace('\\', '_')
        
        # Directory-based cache structure
        self.cnn_cache_dir = self.cache_dir / f"cnn_features_{resnet_model_safe}"
        self.clip_cache_dir = self.cache_dir / f"clip_features_{clip_model_safe}"
        self.cnn_cache_dir.mkdir(parents=True, exist_ok=True)
        self.clip_cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Index files: lightweight metadata {path: {dir_hash, mtime, size}}
        self.cnn_index_file = self.cache_dir / f"cnn_index_{resnet_model_safe}.json"
        self.clip_index_file = self.cache_dir / f"clip_index_{clip_model_safe}.json"
        
        # In-memory caches: {path: (feature_tensor, mtime, size)}
        self.cnn_cache: Dict[str, Tuple[Optional['torch.Tensor'], float, int]] = {}
        self.clip_cache: Dict[str, Tuple[Optional['torch.Tensor'], float, int]] = {}
        
        self._threading_backend = threading_backend
        if threading_backend:
            self.cache_mutex = None
            self._stdlib_lock = threading.Lock()
            self._unload_timer = None
            self._unload_timer_stdlib: Optional[threading.Timer] = None
        else:
            from PySide6.QtCore import QMutex, QTimer
            self._stdlib_lock = None
            self._unload_timer_stdlib = None
            self.cache_mutex = QMutex()
            self._unload_timer = QTimer()
        
        # Track dirty state for deferred disk writes
        self._cnn_dirty = False
        self._clip_dirty = False
        
        # Track which directories are dirty (only save changed directories)
        self._cnn_dirty_dirs: set[str] = set()
        self._clip_dirty_dirs: set[str] = set()
        
        # Track loaded directory caches to avoid reloading
        self._cnn_loaded_dirs: set[str] = set()
        self._clip_loaded_dirs: set[str] = set()
        
        # Track if caches have been loaded (lazy loading)
        self._cnn_cache_loaded = False
        self._clip_cache_loaded = False
        
        # Reference to CNNImageSimilaritySorter for model unloading
        self._sorter_reference = sorter_reference
        
        # Timer for unloading caches after inactivity (Qt) or threading.Timer in worker mode
        if not threading_backend:
            self._unload_timer.setSingleShot(True)
            self._unload_timer.timeout.connect(self._unload_in_memory_caches)
        
        # Track if extraction is in progress (prevents unloading during active extraction)
        self._extraction_in_progress = False
        # Counter to debounce mark_cache_activity calls during extraction
        self._feature_set_count = 0
        # Track recent feature sets to detect active extraction
        import time
        self._last_feature_set_time = 0
        self._time = time
        
        # Rebuild index from .npz files if index is missing or seems incomplete
        # This ensures we don't lose cache entries if index file gets corrupted
        self._rebuild_index_if_needed('clip')
        self._rebuild_index_if_needed('cnn')

    @contextmanager
    def _cache_lock(self):
        if self._threading_backend:
            self._stdlib_lock.acquire()
            try:
                yield
            finally:
                self._stdlib_lock.release()
        else:
            from PySide6.QtCore import QMutexLocker
            with QMutexLocker(self.cache_mutex):
                yield

    def _cancel_unload_timer(self) -> None:
        if self._threading_backend:
            if self._unload_timer_stdlib is not None:
                self._unload_timer_stdlib.cancel()
                self._unload_timer_stdlib = None
        else:
            if self._unload_timer.isActive():
                self._unload_timer.stop()

    def _start_unload_timer(self) -> None:
        if self._threading_backend:
            self._cancel_unload_timer()
            t = threading.Timer(
                FEATURE_CACHE_UNLOAD_TIMEOUT_SECONDS,
                self._unload_in_memory_caches,
            )
            t.daemon = True
            t.start()
            self._unload_timer_stdlib = t
        else:
            self._unload_timer.start(FEATURE_CACHE_UNLOAD_TIMEOUT_SECONDS * 1000)
    
    def _rebuild_index_if_needed(self, cache_type: str):
        """
        Rebuild index file from .npz cache files if index is missing or incomplete.
        This prevents loss of cache entries if the index file gets corrupted.
        
        Args:
            cache_type: 'clip' or 'cnn'
        """
        if cache_type == 'cnn':
            index_file = self.cnn_index_file
            cache_dir = self.cnn_cache_dir
        else:
            index_file = self.clip_index_file
            cache_dir = self.clip_cache_dir
        
        # Count .npz files
        npz_files = list(cache_dir.glob("*.npz")) if cache_dir.exists() else []
        num_npz_files = len(npz_files)
        
        if num_npz_files == 0:
            # No cache files, nothing to rebuild
            return
        
        # Check if index exists and is valid
        index_exists = index_file.exists()
        index_entry_count = 0
        
        if index_exists:
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    index_data = json.load(f)
                    index_entry_count = len(index_data)
            except Exception:
                # Index file is corrupted, need to rebuild
                index_exists = False
                index_entry_count = 0
        
        # Estimate expected entries: each .npz file typically contains multiple entries
        # If index has significantly fewer entries than expected, rebuild it
        # Use a conservative threshold: if index has less than 50% of expected minimum entries
        # (assuming at least 1 entry per .npz file), rebuild it
        min_expected_entries = num_npz_files
        
        if not index_exists or (index_entry_count < min_expected_entries * 0.5 and num_npz_files > 10):
            # Rebuild index from .npz files
            print(f"Rebuilding {cache_type} index from {num_npz_files} cache files...")
            self._rebuild_index_from_npz_files(cache_type)
    
    def _rebuild_index_from_npz_files(self, cache_type: str):
        """
        Rebuild index file by scanning all .npz cache files.
        
        Args:
            cache_type: 'clip' or 'cnn'
        """
        if cache_type == 'cnn':
            index_file = self.cnn_index_file
            cache_dir = self.cnn_cache_dir
        else:
            index_file = self.clip_index_file
            cache_dir = self.clip_cache_dir
        
        if not cache_dir.exists():
            return
        
        index = {}
        npz_files = list(cache_dir.glob("*.npz"))
        
        for npz_file in npz_files:
            try:
                # Load .npz file to extract paths and metadata
                # Note: numpy only loads arrays that are accessed, so features array won't be loaded
                data = np.load(npz_file, allow_pickle=True)
                paths = data['paths']
                mtimes = data['mtimes']
                sizes = data['sizes']
                
                # Extract directory hash from filename
                dir_hash = npz_file.stem
                
                # Add all entries from this file to index
                for i, path in enumerate(paths):
                    if i < len(mtimes) and i < len(sizes):
                        index[str(path)] = {
                            'dir_hash': dir_hash,
                            'mtime': float(mtimes[i]),
                            'size': int(sizes[i])
                        }
            except Exception as e:
                print(f"Error reading cache file {npz_file} during index rebuild: {e}")
                continue
        
        # Save rebuilt index
        if index:
            try:
                self._save_index_file_with_lock(index_file, index)
                print(f"Rebuilt {cache_type} index with {len(index)} entries from {len(npz_files)} cache files")
            except Exception as e:
                print(f"Error saving rebuilt {cache_type} index: {e}")
                import traceback
                traceback.print_exc()
    
    def _get_directory_hash(self, file_path: str) -> str:
        """Get hash for directory to use as cache file name"""
        dir_path = str(Path(file_path).parent.resolve())
        return hashlib.sha256(dir_path.encode('utf-8')).hexdigest()[:16]
    
    def _get_cache_key(self, path: str) -> str:
        """Generate a cache key from file path"""
        # Use absolute path as key
        return str(Path(path).resolve())
    
    def _load_directory_cache(self, cache_type: str, dir_hash: str):
        """Load a directory's cache file"""
        import torch
        
        if cache_type == 'cnn':
            cache_dir = self.cnn_cache_dir
            cache_dict = self.cnn_cache
            loaded_set = self._cnn_loaded_dirs
        else:
            cache_dir = self.clip_cache_dir
            cache_dict = self.clip_cache
            loaded_set = self._clip_loaded_dirs
        
        cache_file = cache_dir / f"{dir_hash}.npz"
        
        if not cache_file.exists():
            loaded_set.add(dir_hash)
            return
        
        try:
            # Load compressed NumPy archive
            data = np.load(cache_file, allow_pickle=True)
            
            # Extract arrays
            paths = data['paths']
            mtimes = data['mtimes']
            sizes = data['sizes']
            valid_mask = data['valid_mask']
            
            # Load features array only if there are any valid features
            has_valid_features = np.any(valid_mask)
            if has_valid_features:
                features_array = data['features']
            else:
                features_array = None
            
            with self._cache_lock():
                valid_idx = 0
                for i, path in enumerate(paths):
                    cache_key = self._get_cache_key(path)
                    if valid_mask[i] and has_valid_features and features_array is not None:
                        # Convert numpy array to PyTorch tensor
                        feature = torch.from_numpy(features_array[valid_idx]).clone()
                        valid_idx += 1
                    else:
                        feature = None
                    cache_dict[cache_key] = (feature, float(mtimes[i]), int(sizes[i]))
                
                loaded_set.add(dir_hash)
        except Exception as e:
            print(f"Error loading {cache_type} directory cache {dir_hash}: {e}")
            import traceback
            traceback.print_exc()
    
    def flush_caches(self, async_flush: bool = False):
        """
        Force flush all dirty caches to disk.
        
        Args:
            async_flush: If True, schedule the flush asynchronously to avoid blocking the main thread.
                        Use this when called from UI operations to prevent beachball.
        """
        if async_flush:
            if self._threading_backend:
                self._flush_caches_sync()
            else:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self._flush_caches_sync)
        else:
            self._flush_caches_sync()
    
    def _flush_caches_sync(self):
        """Synchronous cache flush (internal use)"""
        if self._cnn_dirty:
            self._save_cnn_cache()
        if self._clip_dirty:
            self._save_clip_cache()
    
    def _save_cnn_cache(self):
        """Save CNN feature cache to disk - directory-based"""
        if not self._cnn_dirty_dirs:
            self._cnn_dirty = False
            return
        
        # Load index if exists
        index = {}
        if self.cnn_index_file.exists():
            try:
                with open(self.cnn_index_file, 'r', encoding='utf-8') as f:
                    index = json.load(f)
            except Exception:
                index = {}
        
        saved_dirs = 0
        total_items = 0
        
        # Group all cache items by directory hash first (single pass through cache)
        # This is much faster than scanning the entire cache for each dirty directory
        dir_groups = {}
        with self._cache_lock():
            for path, (feature, mtime, size) in self.cnn_cache.items():
                dir_hash = self._get_directory_hash(path)
                if dir_hash in self._cnn_dirty_dirs:  # Only group dirty directories
                    if dir_hash not in dir_groups:
                        dir_groups[dir_hash] = {}
                    dir_groups[dir_hash][path] = (feature, mtime, size)
        
        # Save each dirty directory
        for dir_hash in list(self._cnn_dirty_dirs):
            # Get features for this directory (already grouped)
            dir_features = dir_groups.get(dir_hash, {})
            
            if not dir_features:
                continue
            
            # Build arrays for NumPy storage
            paths = []
            mtimes = []
            sizes = []
            valid_features = []
            valid_mask = []
            
            for path, (feature, mtime, size) in dir_features.items():
                paths.append(path)
                mtimes.append(mtime)
                sizes.append(size)
                if feature is not None:
                    valid_features.append(feature.cpu().numpy())
                    valid_mask.append(True)
                else:
                    valid_mask.append(False)
            
            # Stack valid features into 2D array
            if valid_features:
                features_array = np.stack(valid_features)
            else:
                # Empty 2D array - shape (0, 1) to match expected 2D structure
                # Won't be accessed since valid_mask will be all False
                features_array = np.empty((0, 1), dtype=np.float32)
            
            # Convert to NumPy arrays
            paths_array = np.array(paths, dtype=object)
            mtimes_array = np.array(mtimes, dtype=np.float64)
            sizes_array = np.array(sizes, dtype=np.int64)
            valid_mask_array = np.array(valid_mask, dtype=bool)
            
            # Save directory cache file
            cache_file = self.cnn_cache_dir / f"{dir_hash}.npz"
            
            try:
                # Atomic write using temp file
                temp_dir = tempfile.mkdtemp(prefix=f"cnn_cache_{dir_hash}_")
                temp_file = Path(temp_dir) / f"{dir_hash}.npz"
                
                try:
                    np.savez_compressed(temp_file,
                        features=features_array,
                        paths=paths_array,
                        mtimes=mtimes_array,
                        sizes=sizes_array,
                        valid_mask=valid_mask_array
                    )
                    
                    temp_file.replace(cache_file)
                    
                    # Update index
                    for path in dir_features:
                        index[path] = {
                            'dir_hash': dir_hash,
                            'mtime': dir_features[path][1],
                            'size': dir_features[path][2]
                        }
                    
                    saved_dirs += 1
                    total_items += len(dir_features)
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
        
        # Save index file (small, quick) with file locking
        if saved_dirs > 0:
            self._save_index_file_with_lock(self.cnn_index_file, index)
        
        with self._cache_lock():
            self._cnn_dirty_dirs.clear()
            self._cnn_dirty = False
    
    def _save_clip_cache(self):
        """Save CLIP feature cache to disk - directory-based"""
        if not self._clip_dirty_dirs:
            self._clip_dirty = False
            return
        
        # Load index if exists
        index = {}
        if self.clip_index_file.exists():
            try:
                with open(self.clip_index_file, 'r', encoding='utf-8') as f:
                    index = json.load(f)
            except Exception:
                index = {}
        
        saved_dirs = 0
        total_items = 0
        
        # Group all cache items by directory hash first (single pass through cache)
        # This is much faster than scanning the entire cache for each dirty directory
        dir_groups = {}
        with self._cache_lock():
            for path, (feature, mtime, size) in self.clip_cache.items():
                dir_hash = self._get_directory_hash(path)
                if dir_hash in self._clip_dirty_dirs:  # Only group dirty directories
                    if dir_hash not in dir_groups:
                        dir_groups[dir_hash] = {}
                    dir_groups[dir_hash][path] = (feature, mtime, size)
        
        # Save each dirty directory
        for dir_hash in list(self._clip_dirty_dirs):
            # Get features for this directory (already grouped)
            dir_features = dir_groups.get(dir_hash, {})
            
            if not dir_features:
                continue
            
            # Build arrays for NumPy storage
            paths = []
            mtimes = []
            sizes = []
            valid_features = []
            valid_mask = []
            
            for path, (feature, mtime, size) in dir_features.items():
                paths.append(path)
                mtimes.append(mtime)
                sizes.append(size)
                if feature is not None:
                    valid_features.append(feature.cpu().numpy())
                    valid_mask.append(True)
                else:
                    valid_mask.append(False)
            
            # Stack valid features into 2D array
            if valid_features:
                features_array = np.stack(valid_features)
            else:
                # Empty 2D array - shape (0, 1) to match expected 2D structure
                # Won't be accessed since valid_mask will be all False
                features_array = np.empty((0, 1), dtype=np.float32)
            
            # Convert to NumPy arrays
            paths_array = np.array(paths, dtype=object)
            mtimes_array = np.array(mtimes, dtype=np.float64)
            sizes_array = np.array(sizes, dtype=np.int64)
            valid_mask_array = np.array(valid_mask, dtype=bool)
            
            # Save directory cache file
            cache_file = self.clip_cache_dir / f"{dir_hash}.npz"
            
            try:
                # Atomic write using temp file
                temp_dir = tempfile.mkdtemp(prefix=f"clip_cache_{dir_hash}_")
                temp_file = Path(temp_dir) / f"{dir_hash}.npz"
                
                try:
                    np.savez_compressed(temp_file,
                        features=features_array,
                        paths=paths_array,
                        mtimes=mtimes_array,
                        sizes=sizes_array,
                        valid_mask=valid_mask_array
                    )
                    
                    temp_file.replace(cache_file)
                    
                    # Update index
                    for path in dir_features:
                        index[path] = {
                            'dir_hash': dir_hash,
                            'mtime': dir_features[path][1],
                            'size': dir_features[path][2]
                        }
                    
                    saved_dirs += 1
                    total_items += len(dir_features)
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
        
        # Save index file (small, quick) with file locking
        if saved_dirs > 0:
            self._save_index_file_with_lock(self.clip_index_file, index)
        
        with self._cache_lock():
            self._clip_dirty_dirs.clear()
            self._clip_dirty = False
    
    def _save_index_file_with_lock(self, index_file: Path, index_data: dict):
        """
        Save index file with file locking to prevent conflicts with background process.
        
        Args:
            index_file: Path to index file
            index_data: Dictionary to save
        """
        lock_file = index_file.with_suffix('.lock')
        
        try:
            # Create lock file if it doesn't exist
            lock_file.touch(exist_ok=True)
            
            with open(lock_file, 'r+') as lock_fd:
                # Acquire exclusive lock
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                
                try:
                    # Read existing index to merge if needed
                    existing_index = {}
                    if index_file.exists():
                        try:
                            with open(index_file, 'r', encoding='utf-8') as f:
                                existing_index = json.load(f)
                        except Exception:
                            existing_index = {}
                    
                    # Merge with existing (new entries override old)
                    merged_index = {**existing_index, **index_data}
                    
                    # Write merged index atomically
                    temp_dir = tempfile.mkdtemp(prefix=f"{index_file.stem}_index_")
                    temp_file = Path(temp_dir) / "index.json"
                    
                    try:
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            json.dump(merged_index, f, indent=2)
                        
                        temp_file.replace(index_file)
                    finally:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                
                finally:
                    # Release lock
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        
        except Exception as e:
            print(f"Error saving index file with lock {index_file}: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to non-locked write if locking fails
            try:
                temp_dir = tempfile.mkdtemp(prefix=f"{index_file.stem}_index_")
                temp_file = Path(temp_dir) / "index.json"
                try:
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(index_data, f, indent=2)
                    temp_file.replace(index_file)
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
    
    def _replace_index_file_with_lock(self, index_file: Path, index_data: dict):
        """
        Replace index file with new data using file locking to prevent conflicts.
        Unlike _save_index_file_with_lock, this REPLACES the entire index rather than merging.
        
        Args:
            index_file: Path to index file
            index_data: Dictionary to save (replaces entire index)
        """
        lock_file = index_file.with_suffix('.lock')
        
        try:
            # Create lock file if it doesn't exist
            lock_file.touch(exist_ok=True)
            
            with open(lock_file, 'r+') as lock_fd:
                # Acquire exclusive lock
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
                
                try:
                    # Write new index atomically (replacing old one)
                    temp_dir = tempfile.mkdtemp(prefix=f"{index_file.stem}_index_replace_")
                    temp_file = Path(temp_dir) / "index.json"
                    
                    try:
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            json.dump(index_data, f, indent=2)
                        
                        temp_file.replace(index_file)
                    finally:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                
                finally:
                    # Release lock
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        
        except Exception as e:
            print(f"Error replacing index file with lock {index_file}: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to non-locked write if locking fails
            try:
                temp_dir = tempfile.mkdtemp(prefix=f"{index_file.stem}_index_replace_")
                temp_file = Path(temp_dir) / "index.json"
                try:
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(index_data, f, indent=2)
                    temp_file.replace(index_file)
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
    
    def get_cnn_feature(self, path: str, mtime: float, size: int, device: str = 'cpu') -> Optional['torch.Tensor']:
        """Get CNN feature from cache if available and valid"""
        import torch
        cache_key = self._get_cache_key(path)
        dir_hash = self._get_directory_hash(path)
        
        # Check if in memory
        with self._cache_lock():
            cache_size = len(self.cnn_cache)
            if cache_key in self.cnn_cache:
                cached_feature, cached_mtime, cached_size = self.cnn_cache[cache_key]
                if cached_mtime == mtime and cached_size == size and cached_feature is not None:
                    # Skip .to() when already on requested device (cache stores CPU; avoids 40k no-op transfers)
                    if cached_feature.device.type == device:
                        return cached_feature
                    return cached_feature.to(device)
        
        # Lazy load directory cache file if not already loaded
        if dir_hash not in self._cnn_loaded_dirs:
            self._load_directory_cache('cnn', dir_hash)
            
            # Mark cache activity after loading
            self.mark_cache_activity()
            # Check again after loading
            with self._cache_lock():
                if cache_key in self.cnn_cache:
                    cached_feature, cached_mtime, cached_size = self.cnn_cache[cache_key]
                    if cached_mtime == mtime and cached_size == size and cached_feature is not None:
                        if cached_feature.device.type == device:
                            return cached_feature
                        return cached_feature.to(device)
        
        return None
    
    def set_cnn_feature(self, path: str, feature: Optional['torch.Tensor'], mtime: float, size: int):
        """Store CNN feature in cache (in-memory only, disk write deferred)"""
        import torch
        cache_key = self._get_cache_key(path)
        dir_hash = self._get_directory_hash(path)
        
        with self._cache_lock():
            # Store CPU copy to save memory
            if feature is not None:
                feature_cpu = feature.cpu().clone()
            else:
                feature_cpu = None
            self.cnn_cache[cache_key] = (feature_cpu, mtime, size)
            self._cnn_dirty_dirs.add(dir_hash)
            self._cnn_dirty = True
            # Don't save to disk here - will be flushed at end of operation
        
        # Mark cache activity periodically during extraction to prevent unloading
        # (every 10 features to avoid excessive timer resets)
        self._feature_set_count += 1
        current_time = self._time.time()
        self._last_feature_set_time = current_time
        
        # If features are being set, extraction is active
        self._extraction_in_progress = True
        if self._feature_set_count % 10 == 0:
            self.mark_cache_activity()
    
    def get_clip_feature(self, path: str, mtime: float, size: int, device: str = 'cpu') -> Optional['torch.Tensor']:
        """Get CLIP feature from cache if available and valid"""
        import torch
        cache_key = self._get_cache_key(path)
        dir_hash = self._get_directory_hash(path)
        
        # Check if in memory
        with self._cache_lock():
            cache_size = len(self.clip_cache)
            if cache_key in self.clip_cache:
                cached_feature, cached_mtime, cached_size = self.clip_cache[cache_key]
                if cached_mtime == mtime and cached_size == size and cached_feature is not None:
                    # Skip .to() when already on requested device (cache stores CPU; avoids 40k no-op transfers)
                    if cached_feature.device.type == device:
                        return cached_feature
                    return cached_feature.to(device)
        
        # Lazy load directory cache file if not already loaded
        if dir_hash not in self._clip_loaded_dirs:
            self._load_directory_cache('clip', dir_hash)
            
            # Mark cache activity after loading
            self.mark_cache_activity()
            # Check again after loading
            with self._cache_lock():
                if cache_key in self.clip_cache:
                    cached_feature, cached_mtime, cached_size = self.clip_cache[cache_key]
                    if cached_mtime == mtime and cached_size == size and cached_feature is not None:
                        if cached_feature.device.type == device:
                            return cached_feature
                        return cached_feature.to(device)
        
        return None
    
    def set_clip_feature(self, path: str, feature: Optional['torch.Tensor'], mtime: float, size: int):
        """Store CLIP feature in cache (in-memory only, disk write deferred)"""
        import torch
        cache_key = self._get_cache_key(path)
        dir_hash = self._get_directory_hash(path)
        
        with self._cache_lock():
            # Store CPU copy to save memory
            if feature is not None:
                feature_cpu = feature.cpu().clone()
            else:
                feature_cpu = None
            self.clip_cache[cache_key] = (feature_cpu, mtime, size)
            self._clip_dirty_dirs.add(dir_hash)
            self._clip_dirty = True
            # Don't save to disk here - will be flushed at end of operation
        
        # Mark cache activity periodically during extraction to prevent unloading
        # (every 10 features to avoid excessive timer resets)
        self._feature_set_count += 1
        current_time = self._time.time()
        self._last_feature_set_time = current_time
        
        # If features are being set, extraction is active
        self._extraction_in_progress = True
        if self._feature_set_count % 10 == 0:
            self.mark_cache_activity()
    
    def mark_cache_activity(self):
        """Mark that cache activity occurred (search or mass rename). Resets the unload timer."""
        if self._threading_backend:
            self._do_mark_cache_activity_timer_ops()
            return
        from PySide6.QtCore import QCoreApplication, QThread, QTimer
        app = QCoreApplication.instance()
        if app is None:
            return
        current_thread = QThread.currentThread()
        main_thread = app.thread()
        if current_thread != main_thread:
            QTimer.singleShot(0, self._do_mark_cache_activity_timer_ops)
            return
        self._do_mark_cache_activity_timer_ops()
    
    def _do_mark_cache_activity_timer_ops(self):
        """Internal method to perform timer operations (must be called on main thread)."""
        self._cancel_unload_timer()
        
        # Reset feature set counter when activity is explicitly marked (not during extraction)
        self._feature_set_count = 0
        
        # Only start timer if caches are actually loaded
        with self._cache_lock():
            has_loaded_cache = (len(self.cnn_cache) > 0 or len(self.clip_cache) > 0 or 
                               len(self._cnn_loaded_dirs) > 0 or len(self._clip_loaded_dirs) > 0)
            cnn_count = len(self.cnn_cache)
            clip_count = len(self.clip_cache)
            loaded_dirs_cnn = len(self._cnn_loaded_dirs)
            loaded_dirs_clip = len(self._clip_loaded_dirs)
        
        if has_loaded_cache:
            self._start_unload_timer()
        else:
            self._start_unload_timer()
    
    def _unload_in_memory_caches(self):
        """Unload in-memory caches after inactivity period to free memory"""
        
        # Check if extraction is still active (features set recently)
        current_time = self._time.time()
        if current_time - self._last_feature_set_time < 10.0:
            # Features were set recently, extraction likely still active
            self._extraction_in_progress = True
            self._start_unload_timer()
            return
        else:
            # No recent feature sets, extraction likely complete
            self._extraction_in_progress = False
        
        # Flush any dirty caches to disk first
        self.flush_caches(async_flush=False)
        
        # Calculate approximate memory being freed
        cnn_count = 0
        clip_count = 0
        estimated_memory_mb = 0.0
        
        with self._cache_lock():
            cnn_count = len(self.cnn_cache)
            clip_count = len(self.clip_cache)
            
            # Estimate memory: each feature tensor is typically ~512 floats (2048 bytes) for CNN
            # and ~512 floats for CLIP, plus overhead
            # Rough estimate: 3KB per feature entry
            estimated_memory_mb = (cnn_count + clip_count) * 3.0 / 1024.0
            
            # Clear in-memory caches
            self.cnn_cache.clear()
            self.clip_cache.clear()
            
            # Reset loaded directories tracking so caches can be reloaded if needed
            self._cnn_loaded_dirs.clear()
            self._clip_loaded_dirs.clear()
            
            # Reset loaded flags
            self._cnn_cache_loaded = False
            self._clip_cache_loaded = False
        
        # Also unload models if sorter reference is available
        if self._sorter_reference is not None:
            try:
                self._sorter_reference.unload_models()
            except Exception as e:
                print(f"Error unloading models: {e}")
        
        from config import get_config
        if get_config().load_settings().get('debug_mode', False):
            if cnn_count > 0 or clip_count > 0:
                print(f"Unloading feature caches after {FEATURE_CACHE_UNLOAD_TIMEOUT_SECONDS}s inactivity: "
                      f"CNN entries={cnn_count}, CLIP entries={clip_count}, "
                      f"estimated memory freed={estimated_memory_mb:.1f} MB")
            else:
                print(f"Timer fired but no feature caches to unload (CNN={cnn_count}, CLIP={clip_count})")


    def clear_all(self):
        """Clear all feature caches"""
        with self._cache_lock():
            self.cnn_cache.clear()
            self.clip_cache.clear()
            self._cnn_dirty = False
            self._clip_dirty = False
            self._cnn_dirty_dirs.clear()
            self._clip_dirty_dirs.clear()
            self._cnn_loaded_dirs.clear()
            self._clip_loaded_dirs.clear()
            self._cnn_cache_loaded = False
            self._clip_cache_loaded = False
        
        # Delete all cache files and directories
        try:
            # Delete index files
            if self.cnn_index_file.exists():
                self.cnn_index_file.unlink()
            if self.clip_index_file.exists():
                self.clip_index_file.unlink()
            
            # Delete background worker's index so it gets fresh state on next run
            clip_index_background = self.cache_dir / "clip_index_background.json"
            if clip_index_background.exists():
                clip_index_background.unlink()
            
            # Delete directory cache files
            for cache_dir in [self.cnn_cache_dir, self.clip_cache_dir]:
                if cache_dir.exists():
                    shutil.rmtree(cache_dir, ignore_errors=True)
                    cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Error clearing feature cache files: {e}")
            import traceback
            traceback.print_exc()
    
    def clear_cache_for_directory(self, directory_path: str):
        """Clear feature cache for a specific directory"""
        dir_path = str(Path(directory_path).resolve())
        dir_hash = hashlib.sha256(dir_path.encode('utf-8')).hexdigest()[:16]
        
        with self._cache_lock():
            # Remove from memory caches
            paths_to_remove = []
            for path in list(self.cnn_cache.keys()):
                if self._get_directory_hash(path) == dir_hash:
                    paths_to_remove.append(path)
            for path in paths_to_remove:
                del self.cnn_cache[path]
            
            paths_to_remove = []
            for path in list(self.clip_cache.keys()):
                if self._get_directory_hash(path) == dir_hash:
                    paths_to_remove.append(path)
            for path in paths_to_remove:
                del self.clip_cache[path]
            
            # Remove from dirty sets
            self._cnn_dirty_dirs.discard(dir_hash)
            self._clip_dirty_dirs.discard(dir_hash)
            self._cnn_loaded_dirs.discard(dir_hash)
            self._clip_loaded_dirs.discard(dir_hash)
        
        # Delete cache files for this directory
        try:
            cnn_cache_file = self.cnn_cache_dir / f"{dir_hash}.npz"
            if cnn_cache_file.exists():
                cnn_cache_file.unlink()
            
            clip_cache_file = self.clip_cache_dir / f"{dir_hash}.npz"
            if clip_cache_file.exists():
                clip_cache_file.unlink()
            
            # Update index files (including background worker's clip index)
            clip_index_background = self.cache_dir / "clip_index_background.json"
            for index_file, cache_type in [(self.cnn_index_file, 'cnn'), (self.clip_index_file, 'clip'), (clip_index_background, 'clip_bg')]:
                if index_file.exists():
                    try:
                        with open(index_file, 'r', encoding='utf-8') as f:
                            index = json.load(f)
                        
                        # Remove entries for this directory
                        paths_to_remove = [p for p in index.keys() if self._get_directory_hash(p) == dir_hash]
                        for path in paths_to_remove:
                            del index[path]
                        
                        # Save updated index
                        temp_dir = tempfile.mkdtemp(prefix=f"{cache_type}_index_")
                        temp_file = Path(temp_dir) / "index.json"
                        try:
                            with open(temp_file, 'w', encoding='utf-8') as f:
                                json.dump(index, f)
                            temp_file.replace(index_file)
                        finally:
                            shutil.rmtree(temp_dir, ignore_errors=True)
                    except Exception as e:
                        print(f"Error updating {cache_type} index: {e}")
        except Exception as e:
            print(f"Error clearing cache for directory {directory_path}: {e}")
            import traceback
            traceback.print_exc()
