#!/usr/bin/env python3
"""Background QThread workers used by the main image browser window."""

import os
import threading
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import QMutexLocker, Qt, QThread, Signal
from PySide6.QtGui import QPixmap

from utils import _usleep_ms


def person_search_build_displayed_paths(
    recursive: bool,
    search_directory: Optional[str],
    current_dir: str,
    current_displayed: List[str],
    filter_pattern: Optional[str],
    max_depth: int,
) -> List[str]:
    """Collect image paths for person search (same rules as filter_by_person). Intended for a worker thread."""
    from faces.face_scan_runner import get_image_list
    from faces.face_cache import normalize_path_for_face_cache

    resolved_sd = None
    if search_directory and search_directory.strip():
        resolved_sd = os.path.expanduser(search_directory.strip())

    displayed: List[str] = []
    if recursive:
        if resolved_sd and os.path.isdir(resolved_sd):
            search_dir = resolved_sd
        else:
            search_dir = current_dir
        if resolved_sd and os.path.isdir(resolved_sd):
            displayed = get_image_list(search_dir, max_depth, filter_pattern=filter_pattern)
        else:
            displayed_set = {normalize_path_for_face_cache(p) for p in current_displayed}
            displayed = list(displayed_set)
            for p in get_image_list(search_dir, max_depth, filter_pattern=filter_pattern):
                if p not in displayed_set:
                    displayed_set.add(p)
                    displayed.append(p)
    else:
        if resolved_sd and os.path.isdir(resolved_sd):
            displayed = get_image_list(resolved_sd, 0, filter_pattern=filter_pattern)
        else:
            displayed = [normalize_path_for_face_cache(p) for p in current_displayed]
    return displayed


class ThumbnailLoadingWorker(QThread):
    """Background worker for loading thumbnails without blocking the UI"""
    thumbnail_loaded = Signal(str, QPixmap, int)  # path, pixmap, size
    progress_updated = Signal(int, int, str)  # completed, total, current_file
    finished = Signal()
    error = Signal(str, str)  # path, error_message

    def __init__(self, cache_manager, image_paths, thumbnail_size, parent=None):
        super().__init__(parent)
        self.cache_manager = cache_manager
        self.image_paths = image_paths
        self.thumbnail_size = thumbnail_size
        self.cancelled = False

    def run(self):
        """Run the thumbnail loading in background thread"""

        # OPTIMIZATION: Pre-fetch thumbnail directory listing once and reuse
        # This avoids calling os.listdir() repeatedly for each cache miss
        thumbnail_dir_listing = None
        try:
            thumbnail_dir_listing = self.cache_manager.get_thumbnail_dir_listing()
        except Exception:
            pass  # Will fall back to individual checks if needed

        # OPTIMIZATION: Pre-compute cache keys in batches to reuse stat cache
        # Process in batches to avoid holding GIL too long
        batch_size = 50
        cache_keys = {}

        # First pass: count cache misses to determine total work
        # OPTIMIZATION: Check in-memory cache first (fastest), then disk cache
        cache_misses = []

        # Get snapshot of in-memory cache once (outside the loop)
        with QMutexLocker(self.cache_manager.cache_mutex):
            # Create a lookup dict keyed by cache_key_base for faster lookups
            cache_snapshot = {}
            for key, cached in self.cache_manager.thumbnail_cache.items():
                # Extract base key (everything before the last underscore)
                if '_' in key:
                    base_key = '_'.join(key.split('_')[:-1])
                    if base_key not in cache_snapshot:
                        cache_snapshot[base_key] = []
                    cache_snapshot[base_key].append((key, cached))

        # Process images in batches to avoid blocking
        for batch_start in range(0, len(self.image_paths), batch_size):
            if self.cancelled:
                return

            batch_end = min(batch_start + batch_size, len(self.image_paths))
            batch_paths = self.image_paths[batch_start:batch_end]

            # Pre-compute cache keys for this batch
            for image_path in batch_paths:
                if self.cancelled:
                    return
                try:
                    cache_key_base = self.cache_manager.get_cache_key(image_path)
                    cache_keys[image_path] = cache_key_base
                except Exception:
                    cache_keys[image_path] = None

            # Check cache for this batch
            for i, image_path in enumerate(batch_paths):
                if self.cancelled:
                    return

                try:
                    cache_key_base = cache_keys.get(image_path)
                    if cache_key_base is None:
                        # Fallback to full check if cache key failed
                        pixmap = self.cache_manager.get_thumbnail_sync(image_path, self.thumbnail_size, thumbnail_dir_listing)
                        if pixmap and not pixmap.isNull():
                            if not self.cancelled:
                                self.thumbnail_loaded.emit(image_path, pixmap, self.thumbnail_size)
                        else:
                            cache_misses.append(image_path)
                        continue

                    exact_cache_key = f"{cache_key_base}_{self.thumbnail_size}"

                    # Check in-memory cache snapshot first (fastest)
                    found_in_memory = False
                    if cache_key_base in cache_snapshot:
                        best_cached = None
                        best_size = 0
                        for key, cached in cache_snapshot[cache_key_base]:
                            if key == exact_cache_key and cached.size == self.thumbnail_size:
                                # Exact match found
                                if not self.cancelled:
                                    self.thumbnail_loaded.emit(image_path, cached.pixmap, self.thumbnail_size)
                                found_in_memory = True
                                break
                            elif cached.size > self.thumbnail_size and cached.size > best_size:
                                best_cached = cached
                                best_size = cached.size

                        if not found_in_memory and best_cached:
                            # Scale down larger thumbnail
                            scaled_pixmap = best_cached.pixmap.scaled(
                                self.thumbnail_size, self.thumbnail_size,
                                Qt.KeepAspectRatio,
                                Qt.SmoothTransformation
                            )
                            if not self.cancelled:
                                self.thumbnail_loaded.emit(image_path, scaled_pixmap, self.thumbnail_size)
                            found_in_memory = True

                    if found_in_memory:
                        continue

                    # Check disk cache (reuse pre-fetched directory listing)
                    found_on_disk = False
                    if thumbnail_dir_listing is not None:
                        # Check exact match first
                        disk_filename = f"{exact_cache_key}.jpg"
                        if disk_filename in thumbnail_dir_listing:
                            disk_path = os.path.join(self.cache_manager.thumbnail_cache_dir, disk_filename)
                            if os.path.exists(disk_path):
                                try:
                                    pixmap = QPixmap(disk_path)
                                    if not pixmap.isNull():
                                        if not self.cancelled:
                                            self.thumbnail_loaded.emit(image_path, pixmap, self.thumbnail_size)
                                        found_on_disk = True
                                except Exception:
                                    pass

                        # Check for larger thumbnails if exact match not found
                        if not found_on_disk:
                            best_disk_size = 0
                            best_disk_path = None
                            scanned = 0
                            max_disk_scan = 200  # Limit scan to prevent slowdowns
                            for filename in thumbnail_dir_listing:
                                scanned += 1
                                if scanned > max_disk_scan:
                                    break
                                if filename.startswith(cache_key_base + "_") and filename.endswith('.jpg'):
                                    try:
                                        cached_size = int(filename.split('_')[-1].replace('.jpg', ''))
                                        if cached_size >= self.thumbnail_size and cached_size > best_disk_size:
                                            best_disk_size = cached_size
                                            best_disk_path = os.path.join(self.cache_manager.thumbnail_cache_dir, filename)
                                    except (ValueError, IndexError):
                                        continue

                            if best_disk_path:
                                try:
                                    pixmap = QPixmap(best_disk_path)
                                    if not pixmap.isNull():
                                        scaled_pixmap = pixmap.scaled(
                                            self.thumbnail_size, self.thumbnail_size,
                                            Qt.KeepAspectRatio,
                                            Qt.SmoothTransformation
                                        )
                                        if not self.cancelled:
                                            self.thumbnail_loaded.emit(image_path, scaled_pixmap, self.thumbnail_size)
                                        found_on_disk = True
                                except Exception:
                                    pass

                    if not found_in_memory and not found_on_disk:
                        # Fallback to full check (slower but comprehensive)
                        pixmap = self.cache_manager.get_thumbnail_sync(image_path, self.thumbnail_size, thumbnail_dir_listing)
                        if pixmap and not pixmap.isNull():
                            if not self.cancelled:
                                self.thumbnail_loaded.emit(image_path, pixmap, self.thumbnail_size)
                        else:
                            cache_misses.append(image_path)

                except Exception as e:
                    if not self.cancelled:
                        self.error.emit(image_path, str(e))

            # Yield between batches to prevent blocking
            if batch_end < len(self.image_paths):
                _usleep_ms(1)  # 1ms sleep - uses ctypes usleep() which is GIL-free

        # Second pass: process cache misses with progress tracking
        if cache_misses and not self.cancelled:
            # Emit initial progress to show progress bar
            if not self.cancelled:
                self.progress_updated.emit(0, len(cache_misses), "Starting thumbnail generation...")

            for i, image_path in enumerate(cache_misses):
                # Check cancelled BEFORE each operation
                if self.cancelled:
                    break

                # Emit progress for cache miss processing
                if not self.cancelled:
                    self.progress_updated.emit(i + 1, len(cache_misses), os.path.basename(image_path))

                try:
                    # Queue for background loading
                    if not self.cancelled:
                        self.cache_manager.get_thumbnail_async(image_path, self.thumbnail_size, priority=1)
                except Exception as e:
                    if not self.cancelled:
                        self.error.emit(image_path, str(e))

                # Check cancelled every 5 items for faster response
                if i % 5 == 0 and i > 0:
                    if self.cancelled:
                        break

                # Small delay to prevent overwhelming the system, but check cancelled first
                if self.cancelled:
                    break
                # Use _usleep_ms() instead of time.sleep() to avoid GIL acquisition deadlock
                _usleep_ms(5)  # 5ms sleep - GIL-free
        else:
            # No cache misses, emit final progress immediately
            if not self.cancelled:
                self.progress_updated.emit(0, 0, "")

        if not self.cancelled:
            self.finished.emit()

    def cancel(self):
        """Cancel the loading operation"""
        self.cancelled = True
        # Emit final progress to hide progress bar
        self.progress_updated.emit(0, 0, "")


class PersonSearchPrepWorker(QThread):
    """Runs directory walk / path list build for person search off the GUI thread."""

    finished_paths = Signal(object)

    def __init__(
        self,
        recursive: bool,
        search_directory: Optional[str],
        current_dir: str,
        current_displayed: List[str],
        filter_pattern: Optional[str],
        max_depth: int,
        parent=None,
    ):
        super().__init__(parent)
        self._recursive = recursive
        self._search_directory = search_directory
        self._current_dir = current_dir
        self._current_displayed = current_displayed
        self._filter_pattern = filter_pattern
        self._max_depth = max_depth

    def run(self):
        try:
            time.sleep(0)
            paths = person_search_build_displayed_paths(
                self._recursive,
                self._search_directory,
                self._current_dir,
                self._current_displayed,
                self._filter_pattern,
                self._max_depth,
            )
            self.finished_paths.emit(paths)
        except Exception:
            self.finished_paths.emit([])


class PersonFaceMatchWorker(QThread):
    """Background match of face cache encodings against known subject embeddings (person search)."""

    finished_ok = Signal(object)  # List[Tuple[str, float]] paths with best mean distance to all samples per image
    finished_canceled = Signal()

    def __init__(self, displayed: List[str], known_encodings: List, cancel_event: threading.Event, parent=None):
        super().__init__(parent)
        self.displayed = displayed
        self.known_encodings = known_encodings
        self._cancel_event = cancel_event

    def run(self):
        from faces.face_cache import get_encodings
        from faces.face_engine import compare_faces, face_mean_distance

        matching_with_dist: List[Tuple[str, float]] = []
        try:
            # Let the main thread paint the progress dialog before heavy Python work (GIL).
            time.sleep(0)
            for i, path in enumerate(self.displayed):
                if self._cancel_event.is_set():
                    self.finished_canceled.emit()
                    return
                # Periodically release the GIL so the Qt GUI thread can process events (avoids beachball).
                if i > 0 and i % 8 == 0:
                    time.sleep(0)
                try:
                    encodings = get_encodings(path)
                except Exception:
                    continue
                if not encodings:
                    continue
                best_mean = None
                for enc in encodings:
                    if compare_faces(self.known_encodings, enc):
                        d = face_mean_distance(self.known_encodings, enc)
                        if d is not None and (best_mean is None or d < best_mean):
                            best_mean = d
                if best_mean is not None:
                    matching_with_dist.append((path, best_mean))
            self.finished_ok.emit(matching_with_dist)
        except Exception:
            try:
                self.finished_ok.emit([])
            except Exception:
                pass
