#!/usr/bin/env python3
"""
Image Cache System
Provides multiple layers of caching for thumbnails, metadata, and full images
"""

# Standard library imports
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
import traceback
from typing import Dict, List, NamedTuple, Optional, Set, Tuple
import time # Added for time.time()
import inspect

# Third-party imports
from PySide6.QtCore import QMutex, QMutexLocker, QObject, Qt, QThread, Signal, QTimer, QMetaObject, QWaitCondition
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

# Local imports
from config import get_config
from thumbnail_constants import RED, RESET, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, THUMBNAIL_GENERATION_THREADS
from thumbnail_cache_key import compute_thumbnail_cache_key, is_path_in_app_cache_directory
from utils import _usleep_ms


class ImageMetadata(NamedTuple):
    """Image metadata structure"""
    filename: str
    file_size: int
    modified_time: float
    source_directory: str  # Add source directory tracking
    width: int = 0  # Image width after EXIF correction
    height: int = 0  # Image height after EXIF correction
    exif_taken_time: Optional[float] = None  # EXIF DateTimeOriginal/DateTimeDigitized timestamp, or None if not available
    
class CachedThumbnail(NamedTuple):
    """Cached thumbnail structure"""
    pixmap: QPixmap
    size: int  # thumbnail size it was generated for
    created_time: float

@dataclass
class CacheStats:
    """Cache statistics"""
    thumbnail_hits: int = 0
    thumbnail_misses: int = 0
    metadata_hits: int = 0
    metadata_misses: int = 0
    fullimage_hits: int = 0
    fullimage_misses: int = 0
    
    def hit_rate(self, cache_type: str) -> float:
        """Calculate hit rate for a cache type"""
        if cache_type == 'thumbnail':
            total = self.thumbnail_hits + self.thumbnail_misses
            return self.thumbnail_hits / total if total > 0 else 0.0
        elif cache_type == 'metadata':
            total = self.metadata_hits + self.metadata_misses
            return self.metadata_hits / total if total > 0 else 0.0
        elif cache_type == 'fullimage':
            total = self.fullimage_hits + self.fullimage_misses
            return self.fullimage_hits / total if total > 0 else 0.0
        return 0.0

class ThumbnailWorkerThread(QThread):
    """Individual worker thread for processing thumbnail requests"""
    
    thumbnail_loaded = Signal(str, QPixmap, int)  # path, pixmap, size
    metadata_loaded = Signal(str, object)  # path, ImageMetadata
    fullimage_loaded = Signal(str, QPixmap)  # path, pixmap
    error_occurred = Signal(str, str)  # path, error_message
    
    def __init__(self, cache_manager, background_loader, queue_mutex, queue_wait_condition, should_stop_flag, thread_id=0, parent=None):
        super().__init__(parent)
        self.cache_manager = cache_manager
        self.background_loader = background_loader  # Store reference to parent to access queue
        self.queue_mutex = queue_mutex
        self.queue_wait_condition = queue_wait_condition
        self.should_stop_flag = should_stop_flag
        self.thread_id = thread_id  # Store thread ID for staggered sleep times
    
    @property
    def load_queue(self):
        """Access queue through parent to ensure we always get the current queue"""
        return self.background_loader.load_queue
    
    def run(self):
        """Main worker thread loop"""
        from thumbnail_constants import THUMBNAIL_WORKER_BATCH_SIZE, THUMBNAIL_WORKER_BATCH_PAUSE_MS
        import time

        process_count = 0
        batch_size = THUMBNAIL_WORKER_BATCH_SIZE
        batch_pause_seconds = THUMBNAIL_WORKER_BATCH_PAUSE_MS / 1000.0  # Convert ms to seconds
        
        # Calculate staggered sleep time to prevent thundering herd GIL contention
        # Spread threads over ~100ms to avoid simultaneous wake-up
        base_sleep = 0.1  # 100ms base sleep
        stagger_offset = (self.thread_id * 0.008)  # ~8ms per thread (spreads 12 threads over ~96ms)
        staggered_sleep = base_sleep + stagger_offset
        idle_backoff_level = 0
        max_idle_backoff_level = 3  # Cap idle delay to keep request pickup responsive
        max_idle_sleep = 0.25  # 250ms max idle delay to avoid noticeable UI lag
        
        while not self.should_stop_flag[0]:
            request = None
            # Get next request from queue
            with QMutexLocker(self.queue_mutex):
                if self.load_queue and not self.should_stop_flag[0]:
                    request = self.load_queue.pop(0)
            
            if not request:
                # No requests available - use time.sleep() instead of msleep() or QWaitCondition.wait()
                # QWaitCondition.wait() requires GIL acquisition when returning (PyEval_RestoreThread),
                # which causes deadlock when main thread holds GIL doing blocking operations.
                # QThread.msleep() ALSO requires GIL restoration (PyEval_RestoreThread) when returning,
                # which causes deadlock. 
                # CRITICAL: nanosleep via ctypes ALSO causes deadlock because ctypes.callproc requires
                # GIL acquisition when returning from the C function, even though nanosleep itself doesn't
                # need the GIL. This creates a deadlock when main thread is dropping GIL during signal
                # connections (e.g., QTimer.singleShot).
                # time.sleep() properly releases the GIL during sleep and handles GIL acquisition correctly
                # when returning, preventing deadlock.
                # CRITICAL FIX: Use staggered sleep times to prevent thundering herd GIL contention.
                # When multiple threads wake up simultaneously, they all try to acquire the GIL at once,
                # causing deadlock when main thread is dropping GIL during Qt signal connections.
                if self.should_stop_flag[0]:
                    return
                # Sleep with thread-specific offset to stagger wake-up times and reduce GIL contention.
                # Add adaptive backoff so idle workers wake less frequently but remain responsive.
                idle_backoff_level = min(idle_backoff_level + 1, max_idle_backoff_level)
                idle_sleep = min(staggered_sleep * (2 ** idle_backoff_level), max_idle_sleep)
                _usleep_ms(idle_sleep * 1000)  # Convert seconds to milliseconds
                continue
            
            # Reset idle backoff after successful dequeue
            idle_backoff_level = 0
            process_count += 1
            
            # Check should_stop before processing
            if self.should_stop_flag[0]:
                break
            
            try:
                request_type = request[0]
                image_path = request[1]
                size_or_none = request[2]
                priority = request[3]
                
                if request_type == 'thumbnail':
                    size = size_or_none
                    if self.should_stop_flag[0]:
                        break
                    pixmap = self._load_thumbnail_sync(image_path, size)
                    if self.should_stop_flag[0]:
                        break
                    if pixmap and not pixmap.isNull():
                        self.thumbnail_loaded.emit(image_path, pixmap, size)
                        
                elif request_type == 'metadata':
                    if self.should_stop_flag[0]:
                        break
                    metadata = self._load_metadata_sync(image_path)
                    if self.should_stop_flag[0]:
                        break
                    if metadata:
                        self.metadata_loaded.emit(image_path, metadata)
                        
                elif request_type == 'fullimage':
                    if self.should_stop_flag[0]:
                        break
                    pixmap = self.load_fullimage_sync(image_path)
                    if self.should_stop_flag[0]:
                        break
                    if pixmap and not pixmap.isNull():
                        self.fullimage_loaded.emit(image_path, pixmap)
                        
            except Exception as e:
                if not self.should_stop_flag[0]:
                    self.error_occurred.emit(image_path, str(e))
            
            # Pause between batches to reduce CPU contention and allow main thread to process events
            if process_count % batch_size == 0:
                if batch_pause_seconds > 0:
                    # Use QThread.msleep() instead of time.sleep() to avoid GIL acquisition deadlock
                    # time.sleep() requires GIL acquisition which can deadlock when main thread is
                    # dropping GIL during signal connections (e.g., QTimer.singleShot)
                    # QThread.msleep() is GIL-free and safe to use in worker threads
                    _usleep_ms(batch_pause_seconds * 1000)  # Convert seconds to milliseconds
                # Reset counter periodically to avoid overflow
                if process_count > 32000:
                    process_count = 0
    
    def _load_thumbnail_sync(self, image_path: str, size: int) -> Optional[QPixmap]:
        """Load thumbnail synchronously with EXIF correction"""
        try:
            if self.should_stop_flag[0]:
                return None
                
            # Check cache first
            cached = self.cache_manager.get_thumbnail_sync(image_path, size)
            if cached:
                # print(f"Thumbnail cache hit for {image_path} at size {size}")
                return cached
            
            # print(f"Thumbnail cache miss for {image_path} at size {size}")
            if self.should_stop_flag[0]:
                return None
            
            # Load and create thumbnail with EXIF correction
            try:
                from exif_image_loader import load_thumbnail_with_exif_correction
                # Use cached ignore_exif_rotation setting instead of loading config every time
                ignore_exif = self.cache_manager.get_ignore_exif_setting()
                pixmap = load_thumbnail_with_exif_correction(image_path, size, ignore_exif=ignore_exif)
                if self.should_stop_flag[0]:
                    return None
                if pixmap and not pixmap.isNull():
                    # Cache it (will skip if in app cache directory)
                    # print(f"Caching thumbnail for {image_path} at size {size}")
                    self.cache_manager.cache_thumbnail_sync(image_path, pixmap, size)
                    return pixmap
                # If pixmap is None or null, load_noimage_thumbnail should have been called in load_thumbnail_with_exif_correction
                # But just in case, return noimage thumbnail here too
                from exif_image_loader import load_noimage_thumbnail
                return load_noimage_thumbnail(size)
            except ImportError:
                if self.should_stop_flag[0]:
                    return None
                pixmap = QPixmap(image_path)
                if self.should_stop_flag[0]:
                    return None
                if not pixmap.isNull():
                    scaled_pixmap = pixmap.scaled(
                        size, size,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    if self.should_stop_flag[0]:
                        return None
                    # Cache it (will skip if in app cache directory)
                    self.cache_manager.cache_thumbnail_sync(image_path, scaled_pixmap, size)
                    return scaled_pixmap
                # If pixmap is null, return noimage thumbnail
                from exif_image_loader import load_noimage_thumbnail
                return load_noimage_thumbnail(size)
                
        except Exception as e:
            pass # print(f"Error loading thumbnail for {image_path}: {e}")
        # Return noimage thumbnail instead of None
        from exif_image_loader import load_noimage_thumbnail
        return load_noimage_thumbnail(size)
    
    def _load_metadata_sync(self, image_path: str) -> Optional[ImageMetadata]:
        """Load metadata synchronously with EXIF correction"""
        try:
            # Check cache first
            cached = self.cache_manager.get_metadata_sync(image_path)
            if cached:
                # Ensure cached metadata has source directory
                if hasattr(cached, 'source_directory') and cached.source_directory and cached.source_directory != "Unknown":
                    return cached
                # If cached metadata exists but has no valid source directory, reload it
            
            # Load metadata
            if not os.path.exists(image_path):
                # Don't cache metadata for non-existent files
                return None
                
            stat = os.stat(image_path)
            
            # Always capture the absolute source directory - this is critical for cache consistency
            source_dir = os.path.dirname(os.path.abspath(image_path))
            
            # Get dimensions and EXIF date/time quickly using fast metadata method
            dimensions = None
            exif_taken_time = None
            try:
                from exif_image_loader import get_image_dimensions_and_exif_date
                result = get_image_dimensions_and_exif_date(image_path)
                if result:
                    dimensions, exif_taken_time = result
            except ImportError:
                # Fallback to dimensions-only if new function not available
                try:
                    from exif_image_loader import get_image_dimensions_fast_metadata
                    dimensions = get_image_dimensions_fast_metadata(image_path)
                except ImportError:
                    pass
            
            # Create metadata with all required fields including dimensions and EXIF date/time
            metadata = ImageMetadata(
                filename=os.path.basename(image_path),
                file_size=stat.st_size,
                modified_time=stat.st_mtime,
                source_directory=source_dir,  # Always set the actual source directory
                width=dimensions[0] if dimensions else 0,
                height=dimensions[1] if dimensions else 0,
                exif_taken_time=exif_taken_time  # EXIF date/time timestamp, or None if not available
            )
            
            # Cache it immediately (will skip if in app cache directory)
            self.cache_manager.cache_metadata_sync(image_path, metadata)
            return metadata
                
        except Exception as e:
            pass # print(f"Error loading metadata for {image_path}: {e}")
        return None
    
    def load_fullimage_sync(self, image_path: str) -> Optional[QPixmap]:
        """Load full image synchronously with EXIF correction"""
        try:
            # Check cache first
            cached = self.cache_manager.get_fullimage_sync(image_path)
            if cached:
                return cached
            
            # Load full image with EXIF correction
            try:
                from exif_image_loader import load_image_with_exif_correction
                # Use cached ignore_exif_rotation setting instead of loading config every time
                ignore_exif = self.cache_manager.get_ignore_exif_setting()
                pixmap = load_image_with_exif_correction(image_path, ignore_exif=ignore_exif)
                if pixmap and not pixmap.isNull():
                    pass # print(f"Full image sync EXIF-corrected load for {os.path.basename(image_path)}: size={pixmap.size()}")
                    # Cache it if not too large (limit to reasonable memory usage)
                    # Will skip if in app cache directory
                    if pixmap.width() * pixmap.height() < 8000000:  # ~8MP limit
                        self.cache_manager.cache_fullimage_sync(image_path, pixmap)
                    return pixmap
            except ImportError:
                # Fallback to direct QPixmap loading if exif_image_loader not available
                pixmap = QPixmap(image_path)
                if not pixmap.isNull():
                    pass # print(f"Full image sync direct load for {os.path.basename(image_path)}: size={pixmap.size()}")
                    # Cache it if not too large (limit to reasonable memory usage)
                    # Will skip if in app cache directory
                    if pixmap.width() * pixmap.height() < 8000000:  # ~8MP limit
                        self.cache_manager.cache_fullimage_sync(image_path, pixmap)
                    return pixmap
                
        except Exception as e:
            pass # print(f"Error loading full image {image_path}: {e}")
        return None


class BackgroundImageLoader(QObject):
    """Manages multiple background threads for loading images without blocking UI"""
    
    # Signals (forwarded from worker threads)
    thumbnail_loaded = Signal(str, QPixmap, int)  # path, pixmap, size
    metadata_loaded = Signal(str, object)  # path, ImageMetadata
    fullimage_loaded = Signal(str, QPixmap)  # path, pixmap
    error_occurred = Signal(str, str)  # path, error_message
    
    def __init__(self, cache_manager):
        super().__init__()
        self.cache_manager = cache_manager
        self.load_queue = []
        self.queue_mutex = QMutex()
        self.queue_wait_condition = QWaitCondition()  # Wake workers when work arrives
        self.should_stop = [False]  # Use list to allow sharing between threads
        self.request_sequence = 0
        self.worker_threads = []
        self.num_threads = THUMBNAIL_GENERATION_THREADS
        
    def add_thumbnail_request(self, image_path: str, size: int, priority: int = 0):
        """Add thumbnail loading request"""
        with QMutexLocker(self.queue_mutex):
            # Remove any existing requests for same path/size to avoid duplicates (modify list in place)
            # Use list comprehension but assign back to maintain reference
            self.load_queue[:] = [req for req in self.load_queue
                                 if not (len(req) >= 5 and req[0] == 'thumbnail' and req[1] == image_path and req[2] == size)]

            # Limit queue size to prevent memory issues with large image sets
            # If queue is getting too large, remove lowest priority items first
            # if len(self.load_queue) >= 10000:
            #     # Remove lowest priority items to make room (sort by priority desc, sequence asc)
            #     self.load_queue.sort(key=lambda x: (-x[3], x[4]))
            #     self.load_queue[:] = self.load_queue[:8000]  # Keep top 8000 items

            # Add new request - 5-element tuple: (type, path, size, priority, sequence)
            self.request_sequence += 1
            self.load_queue.append(('thumbnail', image_path, size, priority, self.request_sequence))
            # Sort by priority (higher priority first), then by sequence (lower sequence first)
            self.load_queue.sort(key=lambda x: (-x[3], x[4]))
            # Wake one waiting worker thread
            self.queue_wait_condition.wakeOne()
    
    def remove_requests_for_file(self, image_path: str):
        """Remove all requests for a specific file from the queue"""
        with QMutexLocker(self.queue_mutex):
            # Modify list in place to maintain reference for worker threads
            self.load_queue[:] = [req for req in self.load_queue
                                 if not (len(req) >= 2 and req[1] == image_path)]
    
    def start(self):
        """Start all worker threads"""
        if self.worker_threads:
            return  # Already started
        
        # Create and start worker threads
        for i in range(self.num_threads):
            worker = ThumbnailWorkerThread(
                self.cache_manager,
                self,  # Pass self so worker can access queue through us
                self.queue_mutex,
                self.queue_wait_condition,
                self.should_stop,
                thread_id=i,  # Pass thread index for staggered sleep times
                parent=self
            )
            # Connect worker signals to our signals with QueuedConnection for thread safety
            worker.thumbnail_loaded.connect(self.thumbnail_loaded, Qt.QueuedConnection)
            worker.metadata_loaded.connect(self.metadata_loaded, Qt.QueuedConnection)
            worker.fullimage_loaded.connect(self.fullimage_loaded, Qt.QueuedConnection)
            worker.error_occurred.connect(self.error_occurred, Qt.QueuedConnection)
            
            worker.start()
            self.worker_threads.append(worker)
    
    def isRunning(self):
        """Check if any worker threads are running"""
        return any(worker.isRunning() for worker in self.worker_threads)
    
    def stop(self):
        """Stop all background threads"""
        # Set stop flag first so threads can check it and exit gracefully
        self.should_stop[0] = True
        
        # Wake all waiting threads so they can check should_stop and exit
        self.queue_wait_condition.wakeAll()
        
        # Clear the queue with mutex protection to prevent threads from getting new work
        # This allows threads to finish current work and exit naturally
        try:
            with QMutexLocker(self.queue_mutex):
                self.load_queue.clear()
        except Exception:
            # If mutex is locked by a thread, that's OK - threads will check should_stop flag
            pass
        
        # Wait for threads to exit gracefully (with timeout)
        import time
        start_time = time.time()
        timeout = 1.0  # 1 second timeout
        
        # Store reference to threads
        old_threads = list(self.worker_threads)
        self.worker_threads.clear()
        
        # Wait for threads to exit
        while time.time() - start_time < timeout:
            all_stopped = True
            for worker in old_threads:
                try:
                    if worker.isRunning():
                        all_stopped = False
                        break
                except Exception:
                    pass
            
            if all_stopped:
                break
            
            # Small sleep to avoid busy-waiting
            time.sleep(0.01)
        
        # If threads are still running after timeout, terminate them
        # This is necessary for clean shutdown
        for worker in old_threads:
            try:
                if worker.isRunning():
                    # Request interruption first
                    worker.requestInterruption()
                    # Give it a brief moment
                    time.sleep(0.05)
                    if worker.isRunning():
                        # Force terminate if still running
                        worker.terminate()
                        worker.wait(100)  # Wait up to 100ms for termination
            except Exception:
                pass

        # Cleanup thread objects - only deleteLater if thread has stopped (avoids Qt abort)
        for worker in old_threads:
            try:
                if not worker.isRunning():
                    worker.deleteLater()
            except Exception:
                pass
        
        # Reset stop flag for potential restart
        self.should_stop[0] = False

class ImageCacheManager(QObject):
    """
    Comprehensive image cache manager with multiple cache layers:
    1. In-memory LRU caches for thumbnails, metadata, and full images
    2. Persistent disk cache for thumbnails
    3. Background loading with prioritization
    """
    
    # Signals
    thumbnail_ready = Signal(str, QPixmap, int)  # path, pixmap, size
    metadata_ready = Signal(str, object)  # path, ImageMetadata
    fullimage_ready = Signal(str, QPixmap)  # path, pixmap

    def __init__(self, cache_dir: Optional[str] = None, 
                 max_thumbnail_cache: int = 12000,
                 max_metadata_cache: int = 12000,
                 max_fullimage_cache: int = 15,
                 start_background_loader: bool = True):
        super().__init__()
        
        # Cache directory setup
        if cache_dir is None:
            config = get_config()
            self.cache_dir = str(config.image_cache_dir)
            self.thumbnail_cache_dir = str(config.thumbnail_cache_dir)
            self.metadata_cache_file = os.path.join(str(config.metadata_cache_dir), "metadata_cache.json")
        else:
            self.cache_dir = cache_dir
            self.thumbnail_cache_dir = os.path.join(cache_dir, "thumbnails")
            self.metadata_cache_file = os.path.join(cache_dir, "metadata_cache.json")
        
        # Ensure cache directories exist
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.thumbnail_cache_dir, exist_ok=True)
        
        # Cache limits
        self.max_thumbnail_cache = max_thumbnail_cache
        self.max_metadata_cache = max_metadata_cache
        self.max_fullimage_cache = max_fullimage_cache
        
        # In-memory caches
        self.thumbnail_cache = {}  # cache_key -> CachedThumbnail
        self._thumbnail_key_index: Dict[str, Set[str]] = {}  # cache_key_base -> set of full keys (avoids O(N) scan on clear)
        self.metadata_cache = {}   # cache_key -> ImageMetadata
        self.fullimage_cache = {}  # cache_key -> QPixmap
        
        # Source directory tracking
        self.source_directories = set()
        
        # Thread safety
        self.cache_mutex = QMutex()
        
        # Store ignore_exif_rotation setting to avoid reading from file every time
        # This prevents timing issues when settings are being saved
        self._ignore_exif_rotation = None  # None means not initialized, will read from config
        self._update_ignore_exif_setting()
        
        # Cache for stat results to avoid repeated os.stat() calls (especially important for network volumes)
        # Maps image_path -> (mtime, cache_time) where cache_time is when we cached it
        self._stat_cache = {}
        self._stat_cache_max_age = 60.0  # Cache stat results for 60 seconds (longer for rename operations)
        self._stat_cache_mutex = QMutex()
        
        # Statistics
        self.stats = CacheStats()
        
        # LRU counter for efficient cache management (replaces expensive timestamps)
        self._lru_counter = 0
        
        # Initialize cache structures (needed before _refresh_thumbnail_dir_cache)
        self._thumbnail_dir_cache = set()
        self._thumbnail_dir_cache_time = 0
        self._thumbnail_dir_cache_valid = False
        
        # Background loader (skip for headless/worker processes to avoid QThread shutdown crash)
        if start_background_loader:
            self.background_loader = BackgroundImageLoader(self)
            # Connect with QueuedConnection for thread safety - forward directly to external listeners
            self.background_loader.thumbnail_loaded.connect(self.thumbnail_ready, Qt.QueuedConnection)
            self.background_loader.metadata_loaded.connect(self.metadata_ready, Qt.QueuedConnection)
            self.background_loader.fullimage_loaded.connect(self.fullimage_ready, Qt.QueuedConnection)
            self.background_loader.error_occurred.connect(self._on_error_occurred, Qt.QueuedConnection)
            self.background_loader.start()
            # Defer blocking cache operations to avoid beachball on startup (especially for network volumes)
            QTimer.singleShot(0, self._load_metadata_cache)
            QTimer.singleShot(0, self._refresh_thumbnail_dir_cache)
        else:
            self.background_loader = None
            self._refresh_thumbnail_dir_cache()
        
        # Periodic cache saving
        self._last_save_time = time.time()
        self._save_interval = 30.0  # Save every 30 seconds
        self._save_timer = QTimer()
        self._save_timer.timeout.connect(self._periodic_save)
        self._save_timer.start(10000)  # Check every 10 seconds
        
        # Store app cache directory path for exclusion check
        config = get_config()
        self._app_cache_dir = str(config.cache_dir)
    
    def is_in_app_cache_directory(self, image_path: str) -> bool:
        """Check if an image path is within the application's cache directory
        
        Args:
            image_path: Path to check
            
        Returns:
            True if the path is within the app's cache directory, False otherwise
        """
        return is_path_in_app_cache_directory(image_path, self._app_cache_dir)
    
    def _refresh_thumbnail_dir_cache(self):
        """Refresh the cached thumbnail directory listing"""
        try:
            if os.path.exists(self.thumbnail_cache_dir):
                self._thumbnail_dir_cache = set(os.listdir(self.thumbnail_cache_dir))
                self._thumbnail_dir_cache_time = time.time()
                self._thumbnail_dir_cache_valid = True
            else:
                self._thumbnail_dir_cache = set()
                self._thumbnail_dir_cache_valid = False
        except Exception:
            self._thumbnail_dir_cache = set()
            self._thumbnail_dir_cache_valid = False
    
    def get_thumbnail_dir_listing(self, force_refresh=False):
        """Get cached thumbnail directory listing, refreshing if needed
        
        CRITICAL: Never refresh from worker threads - this causes GIL deadlock.
        Worker threads should only use cached values. Only main thread refreshes.
        """
        # Check if we're in a worker thread by comparing with main application thread
        try:
            app = QApplication.instance()
            if app:
                current_thread = QThread.currentThread()
                main_thread = app.thread()
                is_main_thread = (current_thread == main_thread)
            else:
                # No app instance - assume main thread
                is_main_thread = True
        except Exception:
            # If we can't determine, assume main thread to be safe
            is_main_thread = True
        
        # If we're not on main thread, NEVER refresh - only use cached value
        # This prevents GIL deadlock when worker threads try to call os.listdir()
        if not is_main_thread:
            # Worker thread - only return cached value, never refresh
            if self._thumbnail_dir_cache_valid:
                return self._thumbnail_dir_cache
            else:
                # No valid cache - return empty set to skip disk cache check
                return set()
        
        # Main thread - can refresh safely
        current_time = time.time()
        
        # Refresh cache if it's invalid, too old, or forced
        if (not self._thumbnail_dir_cache_valid or 
            force_refresh or 
            current_time - self._thumbnail_dir_cache_time > 5.0):  # 5 second cache
            self._refresh_thumbnail_dir_cache()
        
        return self._thumbnail_dir_cache
    
    def invalidate_thumbnail_dir_cache(self):
        """Invalidate the thumbnail directory cache (call when files are added/removed)"""
        self._thumbnail_dir_cache_valid = False
    
    def cleanup(self):
        """Cleanup resources"""
        if self.background_loader:
            self.background_loader.stop()
        
        # Stop the save timer
        if hasattr(self, '_save_timer'):
            self._save_timer.stop()
        
        # Final save of metadata cache
        self.save_metadata_cache(force=True)
    
    def _update_ignore_exif_setting(self):
        """Update the cached ignore_exif_rotation setting from config"""
        try:
            config = get_config()
            settings = config.load_settings()
            self._ignore_exif_rotation = settings.get('ignore_exif_rotation', False)
        except Exception:
            # If we can't get the setting, default to False (EXIF correction enabled)
            self._ignore_exif_rotation = False
    
    def get_ignore_exif_setting(self) -> bool:
        """Get the ignore_exif_rotation setting, using cache if available"""
        if self._ignore_exif_rotation is None:
            self._update_ignore_exif_setting()
        return self._ignore_exif_rotation
    
    def update_exif_setting(self, ignore_exif: bool):
        """Update the ignore_exif_rotation setting (called when setting changes)"""
        old_setting = self._ignore_exif_rotation
        self._ignore_exif_rotation = ignore_exif
        # If setting changed, clear caches
        if old_setting is not None and old_setting != ignore_exif:
            with QMutexLocker(self.cache_mutex):
                self.thumbnail_cache.clear()
                self.fullimage_cache.clear()
    
    def get_cache_key(self, image_path: str, extra: str = "") -> str:
        """Generate cache key for an image"""
        ignore_exif = self.get_ignore_exif_setting()
        with QMutexLocker(self._stat_cache_mutex):
            return compute_thumbnail_cache_key(
                image_path,
                app_cache_dir=self._app_cache_dir,
                ignore_exif_rotation=ignore_exif,
                stat_cache=self._stat_cache,
                stat_cache_max_age=self._stat_cache_max_age,
                extra=extra,
            )
    
    def get_thumbnail_async(self, image_path: str, size: int, priority: int = 0) -> Optional[QPixmap]:
        """
        Get thumbnail asynchronously. Returns cached version immediately if available,
        otherwise queues for background loading and emits thumbnail_ready when done.
        
        This method is smart about using cached thumbnails:
        1. First checks for exact size match
        2. If no exact match, looks for larger cached thumbnails that can be scaled down
        3. Only queues new request if no suitable cached thumbnail is available
        """
        cache_key_base = self.get_cache_key(image_path)
        exact_cache_key = f"{cache_key_base}_{size}"
        
        # Check for exact size match first
        with QMutexLocker(self.cache_mutex):
            if exact_cache_key in self.thumbnail_cache:
                cached = self.thumbnail_cache[exact_cache_key]
                if cached.size == size:
                    self.stats.thumbnail_hits += 1
                    # Update access time using efficient counter (LRU) - much faster than timestamps
                    self._lru_counter += 1
                    self.thumbnail_cache[exact_cache_key] = cached._replace(created_time=self._lru_counter)
                    # Emit signal for immediate cache hits
                    self.thumbnail_ready.emit(image_path, cached.pixmap, size)
                    return cached.pixmap
        
        # Check for larger cached thumbnails that can be scaled down
        # Optimize: only check a limited number of cache entries to avoid expensive scans
        # when cache is large (e.g., after cmd-K recursive with thousands of images)
        best_cached = None
        best_size_diff = float('inf')
        
        # Use index - only check keys for this path (typically 3-5), not whole cache
        with QMutexLocker(self.cache_mutex):
            base = cache_key_base.split('_')[0] if '_' in cache_key_base else cache_key_base
            for key in self._thumbnail_key_index.get(base, set()):
                cached = self.thumbnail_cache.get(key)
                if cached and cached.size >= size:
                    size_diff = cached.size - size
                    if size_diff < best_size_diff:
                        best_cached = cached
                        best_size_diff = size_diff
        
        if best_cached:
            # Scale down the larger thumbnail to the requested size
            scaled_pixmap = best_cached.pixmap.scaled(
                size, size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            # Cache the scaled version for future use (outside of mutex to avoid deadlock)
            self._cache_thumbnail_memory(exact_cache_key, scaled_pixmap, size)
            self.stats.thumbnail_hits += 1
            # Emit signal for scaled cache hits
            self.thumbnail_ready.emit(image_path, scaled_pixmap, size)
            return scaled_pixmap
        
        # Check disk cache for exact size match
        disk_path = os.path.join(self.thumbnail_cache_dir, f"{exact_cache_key}.jpg")
        if os.path.exists(disk_path):
            try:
                pixmap = QPixmap(disk_path)
                if not pixmap.isNull():
                    # Cache in memory (outside of mutex to avoid deadlock)
                    self._cache_thumbnail_memory(exact_cache_key, pixmap, size)
                    self.stats.thumbnail_hits += 1
                    # Emit signal for disk cache hits
                    self.thumbnail_ready.emit(image_path, pixmap, size)
                    return pixmap
            except Exception:
                pass
        
        # Check disk cache for larger thumbnails that can be scaled down
        try:
            thumbnail_files = self.get_thumbnail_dir_listing()
            prefix = (cache_key_base.split('_')[0] if '_' in cache_key_base else cache_key_base) + "_"
            scanned = 0
            max_disk_scan = 200
            for filename in thumbnail_files:
                scanned += 1
                if scanned > max_disk_scan:
                    break
                if filename.startswith(prefix) and filename.endswith('.jpg'):
                    # Extract size from filename
                    try:
                        cached_size = int(filename.split('_')[-1].replace('.jpg', ''))
                        if cached_size >= size:
                            disk_path = os.path.join(self.thumbnail_cache_dir, filename)
                            pixmap = QPixmap(disk_path)
                            if not pixmap.isNull():
                                # Scale down the larger thumbnail
                                scaled_pixmap = pixmap.scaled(
                                    size, size,
                                    Qt.KeepAspectRatio,
                                    Qt.SmoothTransformation
                                )
                                # Cache the scaled version for future use (outside of mutex to avoid deadlock)
                                self._cache_thumbnail_memory(exact_cache_key, scaled_pixmap, size)
                                self.stats.thumbnail_hits += 1
                                # Emit signal for scaled disk cache hits
                                self.thumbnail_ready.emit(image_path, scaled_pixmap, size)
                                return scaled_pixmap
                    except (ValueError, IndexError):
                        continue
        except Exception:
            pass
        
        # Not in cache, queue for background loading
        self.stats.thumbnail_misses += 1
        self.background_loader.add_thumbnail_request(image_path, size, priority)
        return None
    
    def get_thumbnail_sync(self, image_path: str, size: int, thumbnail_dir_listing: Optional[set] = None) -> Optional[QPixmap]:
        """Get thumbnail synchronously (for background thread use)
        
        Args:
            image_path: Path to the image file
            size: Desired thumbnail size
            thumbnail_dir_listing: Optional pre-fetched directory listing to avoid repeated os.listdir() calls
        """
        cache_key_base = self.get_cache_key(image_path)
        exact_cache_key = f"{cache_key_base}_{size}"
        
        # Check in-memory cache - combine both checks into single lock to minimize hold time
        best_cached = None
        best_size = 0
        
        with QMutexLocker(self.cache_mutex):
            # Check for exact size match first
            if exact_cache_key in self.thumbnail_cache:
                cached = self.thumbnail_cache[exact_cache_key]
                if cached.size == size:
                    return cached.pixmap
            
            # OPTIMIZATION: Use index - only check keys for this path (typically 3-5), not whole cache
            base = cache_key_base.split('_')[0] if '_' in cache_key_base else cache_key_base
            for key in self._thumbnail_key_index.get(base, set()):
                cached = self.thumbnail_cache.get(key)
                if cached and cached.size > size:
                    if cached.size > best_size:
                        best_cached = cached
                        best_size = cached.size
        
        if best_cached:
            # Scale down the larger thumbnail to the requested size
            scaled_pixmap = best_cached.pixmap.scaled(
                size, size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            # Cache the scaled version for future use (outside of mutex to avoid deadlock)
            self._cache_thumbnail_memory(exact_cache_key, scaled_pixmap, size)
            return scaled_pixmap
        
        # Check disk cache for exact size match
        disk_path = os.path.join(self.thumbnail_cache_dir, f"{exact_cache_key}.jpg")
        if os.path.exists(disk_path):
            try:
                pixmap = QPixmap(disk_path)
                self._cache_thumbnail_memory(exact_cache_key, pixmap, size)
                return pixmap
            except Exception:
                pass
        
        # Check disk cache for larger thumbnails that can be scaled down
        # OPTIMIZATION: Use provided directory listing if available, otherwise fetch once
        best_disk_size = 0
        best_disk_path = None
        
        try:
            if thumbnail_dir_listing is None:
                thumbnail_files = self.get_thumbnail_dir_listing()
            else:
                thumbnail_files = thumbnail_dir_listing
            
            # OPTIMIZATION: Limit scan to prevent slowdowns with many files
            scanned = 0
            max_disk_scan = 200
            for filename in thumbnail_files:
                scanned += 1
                if scanned > max_disk_scan:
                    break
                if filename.startswith(cache_key_base + "_") and filename.endswith('.jpg'):
                    # Extract size from filename
                    try:
                        cached_size = int(filename.split('_')[-1].replace('.jpg', ''))
                        if cached_size >= size and cached_size > best_disk_size:
                            best_disk_size = cached_size
                            best_disk_path = os.path.join(self.thumbnail_cache_dir, filename)
                    except (ValueError, IndexError):
                        continue
                        
            if best_disk_path:
                pixmap = QPixmap(best_disk_path)
                if not pixmap.isNull():
                    # Scale down the larger thumbnail
                    scaled_pixmap = pixmap.scaled(
                        size, size,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    # Cache the scaled version for future use (outside of mutex to avoid deadlock)
                    self._cache_thumbnail_memory(exact_cache_key, scaled_pixmap, size)
                    return scaled_pixmap
        except Exception:
            pass
        
        return None
    
    def cache_thumbnail_sync(self, image_path: str, pixmap: QPixmap, size: int):
        """Cache thumbnail synchronously (for background thread use)"""
        # Don't cache files that are in the app's cache directory (to avoid duplicates)
        if self.is_in_app_cache_directory(image_path):
            return
        
        cache_key = f"{self.get_cache_key(image_path)}_{size}"
        
        # Cache in memory
        self._cache_thumbnail_memory(cache_key, pixmap, size)
        
        # Cache on disk
        try:
            disk_path = os.path.join(self.thumbnail_cache_dir, f"{cache_key}.jpg")
            pixmap.save(disk_path, "JPEG", quality=85)
            # Invalidate directory cache since we added a file
            self.invalidate_thumbnail_dir_cache()
        except Exception:
            pass
        
        # Ensure metadata exists for this image
        self._ensure_metadata_exists(image_path)
    
    def _cache_thumbnail_memory(self, cache_key: str, pixmap: QPixmap, size: int):
        """Cache thumbnail in memory with LRU management"""
        with QMutexLocker(self.cache_mutex):
            # Remove oldest entries if cache is full
            if len(self.thumbnail_cache) >= self.max_thumbnail_cache:
                # Remove oldest 20% of entries
                remove_count = self.max_thumbnail_cache // 5
                sorted_items = sorted(self.thumbnail_cache.items(), key=lambda x: x[1].created_time)
                for old_key, _ in sorted_items[:remove_count]:
                    del self.thumbnail_cache[old_key]
                    base = old_key.split('_')[0]
                    if base in self._thumbnail_key_index:
                        self._thumbnail_key_index[base].discard(old_key)
                        if not self._thumbnail_key_index[base]:
                            del self._thumbnail_key_index[base]
            
            # Add new entry with efficient counter
            self._lru_counter += 1
            self.thumbnail_cache[cache_key] = CachedThumbnail(
                pixmap=pixmap,
                size=size,
                created_time=self._lru_counter
            )
            base = cache_key.split('_')[0]
            if base not in self._thumbnail_key_index:
                self._thumbnail_key_index[base] = set()
            self._thumbnail_key_index[base].add(cache_key)
    
    
    def get_metadata_sync(self, image_path: str) -> Optional[ImageMetadata]:
        """Get metadata synchronously (for background thread use)"""
        cache_key = self.get_cache_key(image_path)
        
        if cache_key in self.metadata_cache:
            metadata = self.metadata_cache[cache_key]
            # Optimized validation: only check file existence first (fast), then validate if needed
            # Skip expensive os.stat() for files that likely haven't changed
            try:
                if not os.path.exists(image_path):
                    # File doesn't exist, remove from cache
                    if cache_key in self.metadata_cache:
                        del self.metadata_cache[cache_key]
                    return None
                
                # Validate mtime: _stat_cache can serve stale mtime if file was modified outside app.
                # Invalidate _stat_cache and re-check key to detect file changes.
                with QMutexLocker(self._stat_cache_mutex):
                    self._stat_cache.pop(image_path, None)
                fresh_key = self.get_cache_key(image_path)
                if fresh_key != cache_key:
                    with QMutexLocker(self.cache_mutex):
                        self.metadata_cache.pop(cache_key, None)
                    return None
                # Validate source directory
                current_source_dir = os.path.dirname(os.path.abspath(image_path))
                if hasattr(metadata, 'source_directory') and metadata.source_directory:
                    if metadata.source_directory == current_source_dir:
                        return metadata
                    else:
                        with QMutexLocker(self.cache_mutex):
                            self.metadata_cache.pop(cache_key, None)
                        return None
                else:
                    with QMutexLocker(self.cache_mutex):
                        self.metadata_cache.pop(cache_key, None)
                    return None
            except Exception:
                pass
        
        return None
    
    def cache_metadata_sync(self, image_path: str, metadata: ImageMetadata):
        """Cache metadata synchronously"""
        # Don't cache files that are in the app's cache directory (to avoid duplicates)
        if self.is_in_app_cache_directory(image_path):
            return
        
        cache_key = self.get_cache_key(image_path)
        
        with QMutexLocker(self.cache_mutex):
            # Remove oldest entries if cache is full
            if len(self.metadata_cache) >= self.max_metadata_cache:
                remove_count = self.max_metadata_cache // 5
                # For metadata, we can just remove any random entries since they're lightweight
                keys_to_remove = list(self.metadata_cache.keys())[:remove_count]
                for key in keys_to_remove:
                    del self.metadata_cache[key]
            
            # Ensure metadata has the correct source directory
            if not hasattr(metadata, 'source_directory') or not metadata.source_directory or metadata.source_directory == "Unknown":
                # Fix the source directory if it's missing or incorrect
                correct_source_dir = os.path.dirname(os.path.abspath(image_path))
                metadata = metadata._replace(source_directory=correct_source_dir)
            
            self.metadata_cache[cache_key] = metadata
            
            # Track source directory
            if hasattr(metadata, 'source_directory') and metadata.source_directory and metadata.source_directory != "Unknown":
                self.source_directories.add(metadata.source_directory)
        
        # Use periodic save instead of immediate save to avoid mutex contention
        # Immediate saves cause crashes when clicking fast on tree view
        self._periodic_save()
    
    def cache_metadata_batch_sync(self, metadata_updates: List[Tuple[str, ImageMetadata]], defer_save: bool = False):
        """
        Cache metadata for multiple files in batch (more efficient than individual calls).
        
        Args:
            metadata_updates: List of (image_path, metadata) tuples
            defer_save: If True, don't trigger periodic save (caller will save at end)
        """
        if not metadata_updates:
            return
        
        with QMutexLocker(self.cache_mutex):
            # Remove oldest entries if cache is full (do this once for the batch)
            if len(self.metadata_cache) >= self.max_metadata_cache:
                remove_count = self.max_metadata_cache // 5
                keys_to_remove = list(self.metadata_cache.keys())[:remove_count]
                for key in keys_to_remove:
                    del self.metadata_cache[key]
            
            # Process all updates in batch
            for image_path, metadata in metadata_updates:
                # Don't cache files that are in the app's cache directory
                if self.is_in_app_cache_directory(image_path):
                    continue
                
                cache_key = self.get_cache_key(image_path)
                
                # Ensure metadata has the correct source directory
                if not hasattr(metadata, 'source_directory') or not metadata.source_directory or metadata.source_directory == "Unknown":
                    correct_source_dir = os.path.dirname(os.path.abspath(image_path))
                    metadata = metadata._replace(source_directory=correct_source_dir)
                
                self.metadata_cache[cache_key] = metadata
                
                # Track source directory
                if hasattr(metadata, 'source_directory') and metadata.source_directory and metadata.source_directory != "Unknown":
                    self.source_directories.add(metadata.source_directory)
        
        # Only trigger periodic save if not deferred (caller will save at end of batch)
        if not defer_save:
            self._periodic_save()
    
    def get_fullimage_sync(self, image_path: str) -> Optional[QPixmap]:
        """Get full image synchronously"""
        cache_key = self.get_cache_key(image_path)
        return self.fullimage_cache.get(cache_key)
    
    def cache_fullimage_sync(self, image_path: str, pixmap: QPixmap):
        """Cache full image synchronously"""
        # Don't cache files that are in the app's cache directory (to avoid duplicates)
        if self.is_in_app_cache_directory(image_path):
            return
        
        cache_key = self.get_cache_key(image_path)
        
        with QMutexLocker(self.cache_mutex):
            # Remove oldest entries if cache is full
            if len(self.fullimage_cache) >= self.max_fullimage_cache:
                # Remove oldest half of entries (full images are memory-intensive)
                remove_count = self.max_fullimage_cache // 2
                keys_to_remove = list(self.fullimage_cache.keys())[:remove_count]
                for key in keys_to_remove:
                    del self.fullimage_cache[key]
            
            self.fullimage_cache[cache_key] = pixmap
    
    def _on_error_occurred(self, path: str, error_message: str):
        """Handle error occurred from background thread"""
        # This signal is not directly connected to a UI signal in the original code,
        # so it doesn't need to be handled here unless it's intended for logging.
        # For now, we'll just print it.
        pass # print(f"Error loading {path}: {error_message}")
    
    def _load_metadata_cache(self):
        """Load persistent metadata cache from disk"""
        if os.path.exists(self.metadata_cache_file):
            try:
                with open(self.metadata_cache_file, 'r') as f:
                    data = json.load(f)
                    for cache_key, metadata_dict in data.items():
                        try:
                            metadata = ImageMetadata(**metadata_dict)
                        except Exception:
                            # Skip invalid metadata entries
                            continue
                        
                        # Only cache metadata with valid source directories
                        if (hasattr(metadata, 'source_directory') and 
                            metadata.source_directory and 
                            metadata.source_directory != "Unknown"):
                            self.metadata_cache[cache_key] = metadata
                            # Track source directory
                            self.source_directories.add(metadata.source_directory)
                        else:
                            # Skip metadata with unknown source directories
                            continue
            except Exception as e:
                pass # print(f"Error loading metadata cache: {e}")
                # If there's an error loading the cache, clear it to force rebuild
                try:
                    os.unlink(self.metadata_cache_file)
                except Exception:
                    pass
    
    def _json_safe(self, val):
        """Convert value to JSON-serializable form (handles numpy, Path, etc.)"""
        if isinstance(val, (str, int, float, bool, type(None))):
            return val
        if isinstance(val, (list, tuple)):
            return [self._json_safe(v) for v in val]
        if isinstance(val, dict):
            return {str(k): self._json_safe(v) for k, v in val.items()}
        return str(val)

    def save_metadata_cache(self, force: bool = False):
        """Save metadata cache to disk"""
        # Copy data while holding mutex, then write outside mutex to avoid blocking
        with QMutexLocker(self.cache_mutex):
            # Compute hash of current valid metadata (sorted, as string)
            current_metadata_for_hash = {
                cache_key: metadata._asdict()
                for cache_key, metadata in self.metadata_cache.items()
                if (hasattr(metadata, 'source_directory') and
                    metadata.source_directory and
                    metadata.source_directory != "Unknown")
            }
            # Serialize deterministically with JSON-safe conversion (numpy, Path, etc.)
            from hashlib import md5
            safe_metadata = self._json_safe(current_metadata_for_hash)
            metadata_json_str = json.dumps(safe_metadata, sort_keys=True, separators=(',', ':'))
            current_hash = md5(metadata_json_str.encode('utf-8')).hexdigest()
            # If hash matches, nothing has changed, return early
            if getattr(self, 'metadata_hash', None) == current_hash and not force:
                return
            # Update stored hash
            self.metadata_hash = current_hash
            # Use safe_metadata for file write (JSON-serializable)
            valid_metadata = safe_metadata

            # Save only the most recent 10000 valid entries
            # if len(valid_metadata) > 10000:
            #     # Sort by access time if available, otherwise keep most recent
            #     sorted_items = sorted(valid_metadata.items(), key=lambda x: x[1].get('modified_time', 0), reverse=True)
            #     valid_metadata = dict(sorted_items[:10000])
        
        # Write to disk outside mutex to avoid blocking other threads
        try:
            with open(self.metadata_cache_file, 'w') as f:
                json.dump(valid_metadata, f, indent=2)
        except Exception as e:
            # If there's an error saving, try to remove the corrupted file
            try:
                os.unlink(self.metadata_cache_file)
            except Exception:
                pass
    
    def _periodic_save(self):
        """Periodically save metadata cache to disk"""
        current_time = time.time()
        if current_time - self._last_save_time >= self._save_interval:
            self.save_metadata_cache()
            self._last_save_time = current_time
    
    def clear_cache_for_file(self, image_path: str):
        """Clear cache for a specific file (but preserve thumbnails)"""
        # Invalidate _stat_cache so get_cache_key/get_sort_key get fresh mtime from disk
        # (critical when mtime was changed by drag/drop or other in-app operations)
        with QMutexLocker(self._stat_cache_mutex):
            self._stat_cache.pop(image_path, None)
        
        cache_key = self.get_cache_key(image_path)
        
        # Remove any pending requests for this file from the background loader
        if self.background_loader:
            self.background_loader.remove_requests_for_file(image_path)
        
        with QMutexLocker(self.cache_mutex):
            # DO NOT remove from thumbnail cache - preserve thumbnails
            # This prevents constant rebuilding when opening directories
            
            # Remove from metadata cache (by current key and by path - handles mtime change)
            if cache_key in self.metadata_cache:
                metadata = self.metadata_cache[cache_key]
                source_dir = getattr(metadata, 'source_directory', None)
                del self.metadata_cache[cache_key]
                if source_dir and source_dir != "Unknown":
                    other_files_in_dir = any(
                        getattr(m, 'source_directory', None) == source_dir
                        for m in self.metadata_cache.values()
                    )
                    if not other_files_in_dir:
                        self.source_directories.discard(source_dir)
            # Also remove metadata under old cache keys (e.g. after mtime change via drag/drop)
            norm_path = os.path.normpath(image_path)
            for key in list(self.metadata_cache.keys()):
                m = self.metadata_cache[key]
                src = getattr(m, 'source_directory', None)
                fn = getattr(m, 'filename', None)
                if src and fn and os.path.normpath(os.path.join(src, fn)) == norm_path:
                    del self.metadata_cache[key]
                    if src != "Unknown":
                        other = any(getattr(x, 'source_directory', None) == src for x in self.metadata_cache.values())
                        if not other:
                            self.source_directories.discard(src)
                    break
            
            # Remove from full image cache
            if cache_key in self.fullimage_cache:
                del self.fullimage_cache[cache_key]
            
            # DO NOT remove from disk cache - preserve thumbnail files
            # This allows thumbnails to persist across directory changes
            self.clear_cache_for_file_logic(image_path)

    def clear_thumbnails_for_file(self, image_path: str):
        """Clear thumbnails for a specific file (for transformation updates)"""
        
        with QMutexLocker(self.cache_mutex):
           self.clear_cache_for_file_logic(image_path)
    
    def clear_cache_for_file_logic(self, image_path: str, thumbnail_files: Optional[set] = None, skip_disk_deletion: bool = False, defer_invalidate: bool = False):
        """This must be called with the cache mutex held
        
        Args:
            image_path: Path to the image file
            thumbnail_files: Optional pre-fetched directory listing to avoid repeated os.listdir() calls.
                           If None, will fetch the listing (may refresh cache).
            skip_disk_deletion: If True, skip deleting disk cache files (just invalidate cache).
                               Useful for batch operations to reduce blocking time.
            defer_invalidate: If True, do not call invalidate_thumbnail_dir_cache at end.
                             Caller must invalidate once after batch. Reduces N listdirs to 1.
        """

        cache_key = self.get_cache_key(image_path)
        # Remove all thumbnail sizes for this file from memory cache
        # Use index for O(k) instead of O(N) where k=keys per path, N=total cache size
        cache_key_base = cache_key.split('_')[0] if '_' in cache_key else cache_key
        keys_to_remove = list(self._thumbnail_key_index.get(cache_key_base, set()))
        prefix = cache_key_base + "_"  # For disk loop when not skip_disk_deletion
        
        for key in keys_to_remove:
            if key in self.thumbnail_cache:
                del self.thumbnail_cache[key]
        if cache_key_base in self._thumbnail_key_index:
            del self._thumbnail_key_index[cache_key_base]
        
        # Remove from disk cache as well (unless skipping for performance)
        if not skip_disk_deletion:
            try:
                # Use provided listing if available, otherwise fetch (may refresh)
                if thumbnail_files is None:
                    thumbnail_files = self.get_thumbnail_dir_listing()
                
                # CRITICAL: Match by base cache key to find all mtime variants
                # prefix already computed above
                for filename in thumbnail_files:
                    if filename.startswith(prefix) and filename.endswith('.jpg'):
                        disk_path = os.path.join(self.thumbnail_cache_dir, filename)
                        try:
                            os.unlink(disk_path)
                        except Exception:
                            pass  # Ignore deletion errors
                
            except Exception as e:
                print(f"{RED}I dunno.. there is a comment here that says might cause a loop ?? {image_path}: {e}")
                print(f"This is information only and may not indicate an error.")
                pass  # Ignore disk cache clearing errors
        
        # Invalidate cache after clearing (unless caller will do batch invalidate)
        if not defer_invalidate:
            self.invalidate_thumbnail_dir_cache()
    
    def clear_cache_for_files_batch(self, image_paths: List[str]):
        """Clear cache for multiple files. Use instead of N separate clear_cache_for_file calls.
        Fetches thumbnail dir listing at most once, skips disk deletion during batch (orphaned
        thumbnails cleaned up lazily), invalidates once at end. Much faster for mass rename."""
        if not image_paths:
            return
        for image_path in image_paths:
            if self.background_loader:
                self.background_loader.remove_requests_for_file(image_path)
        with QMutexLocker(self.cache_mutex):
            for image_path in image_paths:
                cache_key = self.get_cache_key(image_path)
                if cache_key in self.metadata_cache:
                    metadata = self.metadata_cache[cache_key]
                    source_dir = getattr(metadata, 'source_directory', None)
                    del self.metadata_cache[cache_key]
                    if source_dir and source_dir != "Unknown":
                        other_files_in_dir = any(
                            getattr(m, 'source_directory', None) == source_dir
                            for m in self.metadata_cache.values()
                        )
                        if not other_files_in_dir:
                            self.source_directories.discard(source_dir)
                if cache_key in self.fullimage_cache:
                    del self.fullimage_cache[cache_key]
                self.clear_cache_for_file_logic(image_path, skip_disk_deletion=True, defer_invalidate=True)
            self.invalidate_thumbnail_dir_cache()
    
    def clear_cache(self, cache_type: str = "all"):
        """Clear cache"""
        # Clear background loader queue before clearing cache to prevent processing stale requests
        if self.background_loader and self.background_loader.isRunning():
            # Clear the queue to stop processing pending requests
            # Don't set should_stop=True as the loader is persistent and should keep running
            with QMutexLocker(self.background_loader.queue_mutex):
                self.background_loader.load_queue.clear()
        
        with QMutexLocker(self.cache_mutex):
            if cache_type in ["all", "thumbnails"]:
                self.thumbnail_cache.clear()
                self._thumbnail_key_index.clear()
                # Clear disk cache
                try:
                    thumbnail_files = self.get_thumbnail_dir_listing()
                    for filename in thumbnail_files:
                        if filename.endswith('.jpg'):
                            os.unlink(os.path.join(self.thumbnail_cache_dir, filename))
                    # Invalidate cache after clearing
                    self.invalidate_thumbnail_dir_cache()
                except Exception:
                    pass
            
            if cache_type in ["all", "metadata"]:
                self.metadata_cache.clear()
                # Clear persistent metadata cache file
                try:
                    os.unlink(self.metadata_cache_file)
                except Exception:
                    pass
            
            if cache_type in ["all", "fullimages"]:
                self.fullimage_cache.clear()
    
    def get_cache_info(self) -> dict:
        """Get cache information and statistics"""
        with QMutexLocker(self.cache_mutex):
            result = {
                "thumbnail_count": len(self.thumbnail_cache),
                "metadata_count": len(self.metadata_cache),
                "fullimage_count": len(self.fullimage_cache),
                "cache_dir": self.cache_dir,
                "stats": {
                    "thumbnail_hit_rate": f"{self.stats.hit_rate('thumbnail'):.2%}",
                    "metadata_hit_rate": f"{self.stats.hit_rate('metadata'):.2%}",
                    "fullimage_hit_rate": f"{self.stats.hit_rate('fullimage'):.2%}",
                    "thumbnail_hits": self.stats.thumbnail_hits,
                    "thumbnail_misses": self.stats.thumbnail_misses,
                    "metadata_hits": self.stats.metadata_hits,
                    "metadata_misses": self.stats.metadata_misses,
                    "fullimage_hits": self.stats.fullimage_hits,
                    "fullimage_misses": self.stats.fullimage_misses,
                }
            }
        return result
    
    def get_cache_directories(self) -> list:
        """Get list of directories from which cached files reference"""
        directories = []
        try:
            # Import MIN_THUMBNAIL_SIZE to only count thumbnails of the default size
            from thumbnail_constants import MIN_THUMBNAIL_SIZE
            
            # Load ALL metadata entries from disk (including those with "Unknown" source_directory)
            # This is needed to properly match thumbnails that might have been skipped during normal load
            all_metadata_cache = {}
            if os.path.exists(self.metadata_cache_file):
                try:
                    with open(self.metadata_cache_file, 'r') as f:
                        data = json.load(f)
                        for cache_key, metadata_dict in data.items():
                            try:
                                metadata = ImageMetadata(**metadata_dict)
                                all_metadata_cache[cache_key] = metadata
                            except Exception:
                                # Skip invalid metadata entries
                                continue
                except Exception:
                    pass
            
            # Merge in-memory cache (which may have newer entries) with disk cache
            # In-memory entries take precedence
            all_metadata_cache.update(self.metadata_cache)
            
            # Read thumbnail cache files to get actual cached files
            source_dirs = {}  # directory -> set of unique files
            
            if os.path.exists(self.thumbnail_cache_dir):
                thumbnail_files = [f for f in self.get_thumbnail_dir_listing() if f.endswith('.jpg')]
                
                for filename in thumbnail_files:
                    if filename.endswith('.jpg'):
                        # Extract base cache key from filename (remove size suffix)
                        # Format: {base_cache_key}_{size}.jpg
                        parts = filename.replace('.jpg', '').split('_')
                        if len(parts) >= 2:
                            try:
                                # Check if this is the MIN_THUMBNAIL_SIZE thumbnail
                                thumbnail_size = int(parts[-1])
                                if thumbnail_size != MIN_THUMBNAIL_SIZE:
                                    # Skip thumbnails that aren't the default size
                                    continue
                                
                                # Reconstruct base cache key (everything except the last part which is size)
                                base_cache_key = '_'.join(parts[:-1])
                                
                                # Look up metadata for this cache key (check both in-memory and disk cache)
                                metadata = all_metadata_cache.get(base_cache_key)
                                if metadata:
                                    if (hasattr(metadata, 'source_directory') and 
                                        metadata.source_directory and 
                                        metadata.source_directory != "Unknown"):
                                        source_dir = metadata.source_directory
                                        if source_dir not in source_dirs:
                                            source_dirs[source_dir] = set()
                                        source_dirs[source_dir].add(base_cache_key)
                                    else:
                                        # Metadata exists but has no valid source directory
                                        # Try to fix it if we can determine the source from the metadata filename
                                        if hasattr(metadata, 'filename') and metadata.filename:
                                            # We can't reconstruct the full path from just the filename,
                                            # but we can at least group these separately
                                            pass
                                else:
                                    # No metadata found for cache key
                                    pass
                            except (ValueError, IndexError):
                                # Can't parse size from filename, skip
                                continue
            
            # Get all thumbnail cache keys that don't have metadata (only MIN_THUMBNAIL_SIZE)
            thumbnail_keys_without_metadata = set()
            if os.path.exists(self.thumbnail_cache_dir):
                thumbnail_files = self.get_thumbnail_dir_listing()
                for filename in thumbnail_files:
                    if filename.endswith('.jpg'):
                        parts = filename.replace('.jpg', '').split('_')
                        if len(parts) >= 2:
                            try:
                                # Only count MIN_THUMBNAIL_SIZE thumbnails
                                thumbnail_size = int(parts[-1])
                                if thumbnail_size != MIN_THUMBNAIL_SIZE:
                                    continue
                                
                                base_cache_key = '_'.join(parts[:-1])
                                
                                # Check if already counted from metadata
                                already_counted = False
                                for source_dir in source_dirs.values():
                                    if base_cache_key in source_dir:
                                        already_counted = True
                                        break
                                
                                if not already_counted:
                                    thumbnail_keys_without_metadata.add(base_cache_key)
                            except (ValueError, IndexError):
                                # Can't parse size from filename, skip
                                continue
            
            # Only show "Unknown source" if there are actually thumbnails without any metadata
            # (not just thumbnails with metadata that has "Unknown" source_directory)
            if thumbnail_keys_without_metadata:
                unknown_dir = "Unknown source"
                if unknown_dir not in source_dirs:
                    source_dirs[unknown_dir] = set()
                source_dirs[unknown_dir].update(thumbnail_keys_without_metadata)
            
            # Convert to list and sort
            for source_dir in sorted(source_dirs.keys()):
                try:
                    home_dir = os.path.expanduser("~")
                    if source_dir.startswith(home_dir):
                        display_dir = source_dir.replace(home_dir, "~", 1)
                    else:
                        display_dir = source_dir
                    
                    # Count unique files (not thumbnails) from this directory
                    file_count = len(source_dirs[source_dir])
                    directories.append(f"{display_dir} ({file_count:,} files)")
                except Exception:
                    continue
                    
        except Exception as e:
            directories = ["Error loading directories"]
        return directories
    
    def _ensure_metadata_exists(self, image_path: str):
        """Ensure metadata exists for an image, creating it if necessary"""
        try:
            # Check if metadata already exists
            existing_metadata = self.get_metadata_sync(image_path)
            if existing_metadata and hasattr(existing_metadata, 'source_directory') and existing_metadata.source_directory and existing_metadata.source_directory != "Unknown":
                return  # Metadata already exists and is valid
            
            # Create metadata if it doesn't exist or is invalid
            
            # Create metadata directly since we're in the main cache manager
            if not os.path.exists(image_path):
                return
            
            stat = os.stat(image_path)
            
            # Always capture the absolute source directory
            source_dir = os.path.dirname(os.path.abspath(image_path))
            
            # Get dimensions and EXIF date/time quickly using fast metadata method
            dimensions = None
            exif_taken_time = None
            try:
                from exif_image_loader import get_image_dimensions_and_exif_date
                result = get_image_dimensions_and_exif_date(image_path)
                if result:
                    dimensions, exif_taken_time = result
            except ImportError:
                # Fallback to dimensions-only if new function not available
                try:
                    from exif_image_loader import get_image_dimensions_fast_metadata
                    dimensions = get_image_dimensions_fast_metadata(image_path)
                except ImportError:
                    pass
            
            # Create metadata with all required fields including dimensions and EXIF date/time
            metadata = ImageMetadata(
                filename=os.path.basename(image_path),
                file_size=stat.st_size,
                modified_time=stat.st_mtime,
                source_directory=source_dir,
                width=dimensions[0] if dimensions else 0,
                height=dimensions[1] if dimensions else 0,
                exif_taken_time=exif_taken_time  # EXIF date/time timestamp, or None if not available
            )
            
            # Cache it immediately (will skip if in app cache directory)
            self.cache_metadata_sync(image_path, metadata)
            
        except Exception as e:
            pass # print(f"Error ensuring metadata exists for {image_path}: {e}")
    
    def clear_cache_for_directory(self, directory_path: str, skip_disk_deletion: bool = True):
        """Clear cache for all image files in a directory (non-recursive)
        
        Args:
            directory_path: Path to directory to clear cache for
            skip_disk_deletion: If True (default), skip deleting disk cache files to reduce blocking.
                               Disk files will be regenerated on next access.
        """
        if not os.path.isdir(directory_path):
            return
        
        # Normalize directory path to absolute path for consistent matching
        abs_dir_path = os.path.abspath(directory_path)
        
        # Get image extensions
        try:
            from thumbnail_constants import get_image_extensions
            image_extensions = get_image_extensions()
        except ImportError:
            # Fallback to common extensions if import fails
            image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
        
        # Collect image files in directory (non-recursive) and create a set of filenames for matching
        image_files = []
        image_filenames = set()
        try:
            for entry in os.listdir(abs_dir_path):
                entry_path = f"{abs_dir_path.rstrip('/')}/{entry}"
                if os.path.isfile(entry_path):
                    _, ext = os.path.splitext(entry)
                    if ext.lower() in image_extensions:
                        image_files.append(entry_path)
                        image_filenames.add(entry)
        except (OSError, PermissionError):
            # Can't read directory, return early
            return
        
        with QMutexLocker(self.cache_mutex):
            # Strategy: Find cache entries by matching source_directory and filename
            # This handles cases where mtime has changed and cache keys don't match
            keys_to_remove = set()
            
            # First pass: Find all cache entries for files in this directory
            # by matching source_directory and filename (doesn't depend on mtime)
            for cache_key, metadata in list(self.metadata_cache.items()):
                if hasattr(metadata, 'source_directory') and metadata.source_directory:
                    metadata_dir = os.path.abspath(metadata.source_directory)
                    if metadata_dir == abs_dir_path:
                        # Check if this metadata entry matches a file in the directory
                        if hasattr(metadata, 'filename') and metadata.filename in image_filenames:
                            keys_to_remove.add(cache_key)
            
            # Second pass: Also try current cache keys for files (handles unchanged files)
            # This catches files that haven't changed since caching
            for image_path in image_files:
                try:
                    cache_key = self.get_cache_key(image_path)
                    keys_to_remove.add(cache_key)
                except Exception:
                    # If we can't get cache key (e.g., file doesn't exist), skip it
                    pass
            
            # Remove all matching cache entries
            for cache_key in keys_to_remove:
                # Remove from metadata cache
                if cache_key in self.metadata_cache:
                    del self.metadata_cache[cache_key]
                
                # Remove from thumbnail cache (all sizes) - use index for O(k) not O(N)
                cache_key_base = cache_key.split('_')[0] if '_' in cache_key else cache_key
                thumbnail_keys_to_remove = list(self._thumbnail_key_index.get(cache_key_base, set()))
                for key in thumbnail_keys_to_remove:
                    if key in self.thumbnail_cache:
                        del self.thumbnail_cache[key]
                if cache_key_base in self._thumbnail_key_index:
                    del self._thumbnail_key_index[cache_key_base]
                
                # Remove from fullimage cache
                if cache_key in self.fullimage_cache:
                    del self.fullimage_cache[cache_key]
            
            # Clean up source directory tracking
            other_files_in_dir = any(
                getattr(m, 'source_directory', None) == abs_dir_path 
                for m in self.metadata_cache.values()
            )
            if not other_files_in_dir:
                self.source_directories.discard(abs_dir_path)
        
        # Remove any pending requests for these files from the background loader
        if self.background_loader:
            for image_path in image_files:
                self.background_loader.remove_requests_for_file(image_path)
        
        # Clear disk cache files (if not skipping)
        if not skip_disk_deletion:
            try:
                thumbnail_files = self.get_thumbnail_dir_listing(force_refresh=True)
                for image_path in image_files:
                    cache_key = self.get_cache_key(image_path)
                    cache_key_base = cache_key.split('_')[0] if '_' in cache_key else cache_key
                    prefix = cache_key_base + "_"
                    for filename in thumbnail_files:
                        if filename.startswith(prefix) and filename.endswith('.jpg'):
                            disk_path = os.path.join(self.thumbnail_cache_dir, filename)
                            try:
                                os.unlink(disk_path)
                            except Exception:
                                pass  # Ignore deletion errors
                self.invalidate_thumbnail_dir_cache()
            except Exception:
                pass  # Ignore disk cache clearing errors
    
    def get_cache_statistics(self) -> dict:
        """Get detailed cache statistics"""
        try:
            total_items = len(self.thumbnail_cache) + len(self.metadata_cache) + len(self.fullimage_cache)
            return {
                "total_cached_items": total_items,
                "thumbnail_cache_items": len(self.thumbnail_cache),
                "metadata_cache_items": len(self.metadata_cache),
                "fullimage_cache_items": len(self.fullimage_cache),
                "disk_usage_bytes": 0,
                "disk_usage_mb": 0.0,
                "cache_directories": self.get_cache_directories(),
                "hit_rates": {
                    "thumbnail": f"{self.stats.hit_rate('thumbnail'):.1%}",
                    "metadata": f"{self.stats.hit_rate('metadata'):.1%}",
                    "fullimage": f"{self.stats.hit_rate('fullimage'):.1%}",
                },
                "total_requests": {
                    "thumbnail": self.stats.thumbnail_hits + self.stats.thumbnail_misses,
                    "metadata": self.stats.metadata_hits + self.stats.metadata_misses,
                    "fullimage": self.stats.fullimage_hits + self.stats.fullimage_misses,
                }
            }
        except Exception as e:
            return {
                "total_cached_items": 0,
                "thumbnail_cache_items": 0,
                "metadata_cache_items": 0,
                "fullimage_cache_items": 0,
                "disk_usage_bytes": 0,
                "disk_usage_mb": 0.0,
                "cache_directories": ["Error loading directories"],
                "hit_rates": {
                    "thumbnail": "0.0%",
                    "metadata": "0.0%",
                    "fullimage": "0.0%",
                },
                "total_requests": {
                    "thumbnail": 0,
                    "metadata": 0,
                    "fullimage": 0,
                }
            }
    
   
# Global cache instance
_cache_manager: Optional[ImageCacheManager] = None

def get_cache_manager() -> ImageCacheManager:
    """Get global cache manager instance"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = ImageCacheManager()
    return _cache_manager

def cleanup_cache():
    """Cleanup global cache manager"""
    global _cache_manager
    if _cache_manager:
        _cache_manager.cleanup()
        _cache_manager = None 