#!/usr/bin/env python3
"""
Cache Prepopulator Module
Populates the cache for all images in the current directory and its children up to a configured depth.
"""

import os
import time
from typing import List, Set, Optional
from PySide6.QtCore import Qt, QTimer
from cnn_image_similarity_sorter import _TimingTracker
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QProgressDialog, QApplication
from thumbnail_constants import get_image_extensions, MIN_THUMBNAIL_SIZE
from image_cache import get_cache_manager
from utils import is_inside_photos_library_resources_or_scopes, wrap_progress_dialog_label_elision
from file_tree_handler import _get_excluded_paths, _is_excluded_path

def _is_in_app_cache_directory(path: str) -> bool:
    """
    Check if a path is within the application's cache directory.
    
    Args:
        path: Path to check
        
    Returns:
        True if the path is within the app's cache directory, False otherwise
    """
    try:
        from config import get_config
        config = get_config()
        app_cache_dir = str(config.cache_dir)
        abs_path = os.path.abspath(path)
        abs_cache_dir = os.path.abspath(app_cache_dir)
        # Check if the path starts with the cache directory
        return abs_path.startswith(abs_cache_dir + os.sep) or abs_path == abs_cache_dir
    except Exception:
        return False

def get_search_depth_from_config() -> int:
    """
    Helper to fetch search_depth setting from the config. Defaults to 4 if not set.
    """
    try:
        from config import get_config
        config = get_config()
        settings = config.load_settings()
        return int(settings.get('search_depth', 4))
    except Exception:
        return 4  # fallback

def scan_directory_for_images_with_progress_recursively(
    root_dir: str,
    progress_dialog: QProgressDialog,
    max_depth: int
) -> List[str]:
    """
    Recursively scan root_dir up to max_depth for image files, updating progress_dialog.

    Args:
        root_dir: Directory to start scan
        progress_dialog: Progress dialog to update
        max_depth: Maximum recursion depth

    Returns:
        List of image file paths
    """
    # Get process hidden directories setting
    try:
        from config import get_config
        config = get_config()
        process_hidden = config.load_settings().get('show_hidden_directories', False)
    except Exception:
        process_hidden = False
        config = None
    
    # Get excluded paths (cache, Photos Library, and ignore directories)
    excluded_paths = []
    try:
        if config is None:
            from config import get_config
            config = get_config()
        excluded_paths = _get_excluded_paths(config)
    except Exception:
        pass
    
    image_extensions = get_image_extensions()
    image_files = []

    # We'll use our own stack to avoid stack overflows and for easier progress calculation.
    stack = [(root_dir, 0)]
    total_scanned_dirs = 0
    scanned_dirs_paths = []

    # First, walk all directories up to depth to count directories (for progress)
    while stack:
        dir_path, depth = stack.pop()
        # Skip excluded directories (cache, Photos Library, and ignore directories)
        dir_path_resolved = os.path.realpath(dir_path)
        if _is_excluded_path(dir_path_resolved, excluded_paths):
            continue
        scanned_dirs_paths.append((dir_path, depth))
        if depth < max_depth:
            try:
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            # Skip hidden directories if not processing them
                            if not process_hidden and entry.name.startswith('.'):
                                continue
                            # Skip excluded directories (cache, Photos Library, and ignore directories)
                            entry_path_resolved = os.path.realpath(entry.path)
                            if _is_excluded_path(entry_path_resolved, excluded_paths):
                                continue
                            stack.append((entry.path, depth + 1))
            except (PermissionError, FileNotFoundError, OSError):
                pass

    total_dirs = len(scanned_dirs_paths)
    del stack  # no longer needed, release

    for dir_idx, (directory, depth) in enumerate(scanned_dirs_paths):
        if progress_dialog.wasCanceled():
            break
        # Update progress
        progress_dialog.setValue(dir_idx)
        dir_name = os.path.basename(directory) or directory
        
        # Count images before scanning this directory
        images_before = len(image_files)
        
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_file():
                        # Skip files in excluded directories (cache, Photos Library, and ignore directories)
                        entry_path_resolved = os.path.realpath(entry.path)
                        if _is_excluded_path(entry_path_resolved, excluded_paths):
                            continue
                        _, ext = os.path.splitext(entry.name)
                        if ext.lower() in image_extensions:
                            image_files.append(entry.path)
        except (PermissionError, OSError, FileNotFoundError):
            # Skip directories we can't access
            pass
        
        # Update label with directory progress and total images found
        total_images_found = len(image_files)
        progress_dialog.setLabelText(
            f"Scanning {dir_name} (depth {depth})... ({dir_idx + 1}/{total_dirs})\n"
            f"Total images found: {total_images_found}"
        )
        QApplication.processEvents()

    return image_files

def _label_with_remaining_line(description: str, done: int, total: int, timing: _TimingTracker) -> str:
    """Append 'N images remaining (Est: …)' using same timing rules as CNN/CLIP progress dialogs."""
    rem = max(0, total - done)
    lines = [description]
    if rem > 0:
        est = timing.get_time_estimate(done, total) if done else ""
        rline = f"{rem} image{'s' if rem != 1 else ''} remaining"
        if est:
            rline += f" ({est})"
        lines.append(rline)
    return "\n".join(lines)


def check_images_need_caching_with_progress(image_paths: List[str], cache_manager, thumbnail_size: int,
                                           progress_dialog: QProgressDialog, scan_progress: int) -> List[str]:
    """
    Check which images need caching (not already cached) with progress updates.

    Args:
        image_paths: List of image file paths to check
        cache_manager: ImageCacheManager instance
        thumbnail_size: Thumbnail size to check for
        progress_dialog: Progress dialog to update
        scan_progress: Progress value at end of scan phase

    Returns:
        List of image paths that need caching
    """
    images_to_cache = []
    total_images = len(image_paths)
    timing = _TimingTracker()
    last_ui_mono = 0.0

    # Update progress dialog for cache checking phase
    for idx, image_path in enumerate(image_paths):
        if progress_dialog.wasCanceled():
            break

        try:
            cached_thumbnail = cache_manager.get_thumbnail_sync(image_path, thumbnail_size)
            if not cached_thumbnail:
                images_to_cache.append(image_path)
        except Exception:
            images_to_cache.append(image_path)

        done = idx + 1
        now = time.monotonic()
        milestone = done == 1 or done % 100 == 0 or done == total_images
        if milestone or (now - last_ui_mono >= 1.0):
            last_ui_mono = now
            progress_value = scan_progress + done
            progress_dialog.setValue(progress_value)
            desc = f"Checking cache status... ({done}/{total_images} images)"
            progress_dialog.setLabelText(_label_with_remaining_line(desc, done, total_images, timing))
            QApplication.processEvents()

    return images_to_cache

def _load_and_cache_thumbnail(cache_manager, image_path: str, size: int) -> bool:
    """
    Load and cache a thumbnail synchronously.

    Args:
        cache_manager: ImageCacheManager instance
        image_path: Path to image file
        size: Thumbnail size

    Returns:
        True if successfully cached, False otherwise
    """
    try:
        cached = cache_manager.get_thumbnail_sync(image_path, size)
        if cached:
            return True

        try:
            from exif_image_loader import load_thumbnail_with_exif_correction
            ignore_exif = cache_manager.get_ignore_exif_setting()
            pixmap = load_thumbnail_with_exif_correction(image_path, size, ignore_exif=ignore_exif)
            if pixmap and not pixmap.isNull():
                cache_manager.cache_thumbnail_sync(image_path, pixmap, size)
                return True
        except ImportError:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(
                    size, size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                cache_manager.cache_thumbnail_sync(image_path, scaled_pixmap, size)
                return True
            else:
                # If image can't be loaded, use noimage thumbnail
                from exif_image_loader import load_noimage_thumbnail
                noimage_pixmap = load_noimage_thumbnail(size)
                cache_manager.cache_thumbnail_sync(image_path, noimage_pixmap, size)
                return True
    except Exception:
        # On exception, still cache the noimage thumbnail so we don't keep retrying
        try:
            from exif_image_loader import load_noimage_thumbnail
            noimage_pixmap = load_noimage_thumbnail(size)
            cache_manager.cache_thumbnail_sync(image_path, noimage_pixmap, size)
            return True
        except Exception:
            pass

    return False

def prepopulate_cache(main_window, thumbnail_size: Optional[int] = None, suppress_success_messages: bool = False,
                      image_paths: Optional[List[str]] = None):
    """
    Prepopulate cache for all images in current directory and its children up to depth specified by search_depth setting (default 4).

    Args:
        main_window: Main window instance
        thumbnail_size: Thumbnail size to cache (if None, uses MIN_THUMBNAIL_SIZE - the size used when there are more than a page full of thumbs)
        suppress_success_messages: If True, suppress success messages (cancel messages still shown)
        image_paths: If set, skip directory scan and only check/cache these paths (used e.g. from tree "show all images" with current filter). Shift+Cmd+C leaves this None.

    Returns:
        True if operation was canceled, False if completed successfully
    """
    # Use MIN_THUMBNAIL_SIZE by default (the size used when there are more than a page full of thumbs)
    # This ensures cache checks and recreation use the minimum icon size
    if thumbnail_size is None:
        thumbnail_size = MIN_THUMBNAIL_SIZE

    # Get current directory
    current_directory = None
    if hasattr(main_window, 'current_directory') and main_window.current_directory:
        current_directory = main_window.current_directory
    else:
        # Try to get from current image path
        if hasattr(main_window, 'get_current_image_path'):
            current_image_path = main_window.get_current_image_path()
            if current_image_path:
                current_directory = os.path.dirname(current_image_path)

    if not current_directory or not os.path.exists(current_directory):
        from utils import show_styled_warning
        show_styled_warning(main_window, "No Directory", "No current directory available for cache prepopulation.")
        return False

    # Interrupt any ongoing thumbnail loading before cache scan (avoids hangs during heavy scan)
    if hasattr(main_window, '_interrupt_thumbnail_loading'):
        main_window._interrupt_thumbnail_loading()

    # Get cache manager
    cache_manager = get_cache_manager()

    # Fetch max scan depth from config — used when scanning disk; messages only when image_paths is None
    max_depth = get_search_depth_from_config()

    scan_label = (
        "Prepopulating cache (filtered file list)..."
        if image_paths is not None
        else f"Prepopulating cache (scanning up to {max_depth} levels)..."
    )
    # Roughly estimate total directory count (“maximum possible”) for progress dialog init - we'll refine after directory collection if needed
    progress_dialog = QProgressDialog(
        scan_label,
        "Cancel",
        0,
        100,  # Temporary value
        main_window
    )
    progress_dialog.setWindowTitle("Prepopulate Cache")
    progress_dialog.setWindowModality(Qt.WindowModal)
    progress_dialog.setMinimumDuration(0)  # Show immediately
    progress_dialog.setValue(0)
    progress_dialog.show()
    from PySide6.QtWidgets import QLabel
    QApplication.processEvents()
    label = progress_dialog.findChild(QLabel)
    if label:
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setMinimumHeight(label.fontMetrics().height() * 2 + 4)
    wrap_progress_dialog_label_elision(progress_dialog)

    # Phase 1: Recursively scan for images, or use caller-supplied paths (tree "show all images" + filter)
    if image_paths is not None:
        image_files = list(image_paths)
    else:
        image_files = scan_directory_for_images_with_progress_recursively(current_directory, progress_dialog, max_depth)

    # Check for cancel after scanning
    if progress_dialog.wasCanceled():
        progress_dialog.close()
        return True

    if not image_files:
        progress_dialog.close()
        from utils import show_styled_warning
        if image_paths is not None:
            show_styled_warning(
                main_window, "No Images",
                "No image files in the filtered list to prepopulate."
            )
        else:
            show_styled_warning(
                main_window, "No Images",
                f"No image files found in {current_directory} or its subdirectories (search depth: {max_depth})."
            )
        return False

    # Phase 2: Check which images need caching (with progress updates)
    scan_progress = progress_dialog.maximum() if progress_dialog.maximum() > 0 else 0
    scan_progress = len(image_files) // 100  # Set start of progress to reflect scan was performed
    progress_dialog.setMaximum(scan_progress + len(image_files))
    progress_dialog.setValue(scan_progress)

    images_to_cache = check_images_need_caching_with_progress(
        image_files, cache_manager, thumbnail_size, progress_dialog, scan_progress
    )

    if progress_dialog.wasCanceled():
        progress_dialog.close()
        return True

    if not images_to_cache:
        progress_dialog.close()
        if not suppress_success_messages:
            from utils import show_styled_information
            if image_paths is not None:
                show_styled_information(
                    main_window, "Cache Complete",
                    f"All {len(image_files)} images in the filtered list are already cached."
                )
            else:
                show_styled_information(
                    main_window, "Cache Complete",
                    f"All {len(image_files)} images in the current directory and its subdirectories (search depth: {max_depth}) are already cached."
                )
        return False

    # Phase 3: Cache images (with progress)
    check_progress = scan_progress + len(image_files)
    progress_dialog.setMaximum(check_progress + len(images_to_cache))
    progress_dialog.setValue(check_progress)

    cached_count = 0
    total_to_cache = len(images_to_cache)
    timing = _TimingTracker()
    last_ui_mono = 0.0
    for idx, image_path in enumerate(images_to_cache):
        if progress_dialog.wasCanceled():
            break

        try:
            if _load_and_cache_thumbnail(cache_manager, image_path, thumbnail_size):
                cached_count += 1
        except Exception:
            # Skip images that fail to cache
            pass

        done = idx + 1
        now = time.monotonic()
        milestone = done == 1 or done % 10 == 0 or done == total_to_cache
        if milestone or (now - last_ui_mono >= 1.0):
            last_ui_mono = now
            progress_dialog.setValue(check_progress + done)
            desc = f"Caching {os.path.basename(image_path)}...\n({done}/{total_to_cache})"
            progress_dialog.setLabelText(_label_with_remaining_line(desc, done, total_to_cache, timing))
            QApplication.processEvents()

    was_canceled = progress_dialog.wasCanceled()

    if not was_canceled:
        progress_dialog.setValue(check_progress + len(images_to_cache))
        progress_dialog.setLabelText(f"Completed: {cached_count} images cached")
        QTimer.singleShot(1000, progress_dialog.close)

        if not suppress_success_messages:
            from utils import show_styled_information
            if image_paths is not None:
                show_styled_information(
                    main_window, "Cache Prepopulation Complete",
                    f"Successfully cached {cached_count} images from the filtered list under {current_directory}."
                )
            else:
                show_styled_information(
                    main_window, "Cache Prepopulation Complete",
                    f"Successfully cached {cached_count} images from {current_directory} and its subdirectories (search depth: {max_depth})."
                )
        return False
    else:
        progress_dialog.close()

        from utils import show_styled_information
        show_styled_information(
            main_window, "Cache Prepopulation",
            f"Cached {cached_count} of {len(images_to_cache)} images before cancellation."
        )
        return True
