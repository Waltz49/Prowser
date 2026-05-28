#!/usr/bin/env python3
"""
Face scan runner: scan directories for images, detect faces, and store encodings in face cache.
Designed to run in a background thread; progress and cancel are reported via callbacks.
"""

import os
import time
from pathlib import Path
import fnmatch
from typing import Dict, List, Callable, Optional, Set

from thumbnail_constants import get_image_extensions
from file_tree_handler import _get_excluded_paths, _is_excluded_path
from face_cache import normalize_path_for_face_cache

# --- Directory scan cache (DISABLED: caused cmd-= to skip while cmd-P rescanned) ---
# When enabled, skipped dirs without checking has_cached_faces, so after face cache clear
# cmd-= would skip (dir marked) but cmd-P would rescan (paths_to_scan bypasses dir cache).
# Both must use has_cached_faces as the single source of truth.
USE_DIRECTORY_CACHE = False
_scanned_dir_cache: Dict[str, float] = {}  # dir_path (resolved) -> mtime when scanned


def clear_scanned_dir_cache() -> None:
    """Clear the in-memory directory cache. Call if cache causes problems."""
    _scanned_dir_cache.clear()


def _dir_can_skip(dir_path: str) -> bool:
    """Return True if dir was scanned and mtime unchanged (can skip)."""
    try:
        resolved = os.path.realpath(dir_path)
        current_mtime = os.stat(resolved).st_mtime
        cached = _scanned_dir_cache.get(resolved)
        return cached is not None and cached == current_mtime
    except OSError:
        return False


def _mark_dir_scanned(dir_path: str) -> None:
    """Record dir as scanned at current mtime."""
    try:
        resolved = os.path.realpath(dir_path)
        _scanned_dir_cache[resolved] = os.stat(resolved).st_mtime
    except OSError:
        pass
# --- End directory scan cache ---


def get_image_list(root_dir: str, max_depth: int, filter_pattern: Optional[str] = None) -> List[str]:
    """Collect image paths under root_dir up to max_depth, respecting exclusions and hidden-dir setting.
    If filter_pattern is provided (e.g. from ImageBrowserConfig.get_filter_pattern_for_matching),
    only include files matching the pattern. Returns paths normalized via Path.resolve for cache consistency."""
    try:
        from config import get_config
        config = get_config()
        process_hidden = config.load_settings().get('show_hidden_directories', False)
        excluded_paths = _get_excluded_paths(config)
    except Exception:
        process_hidden = False
        excluded_paths = []

    match_pattern = None
    if filter_pattern and filter_pattern != '*':
        try:
            from config import ImageBrowserConfig
            match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)
        except Exception:
            pass

    image_extensions = get_image_extensions()
    image_files: List[str] = []
    stack = [(root_dir, 0)]
    scanned_dirs: List[tuple] = []
    stack_iters = 0

    while stack:
        if stack_iters > 0 and stack_iters % 256 == 0:
            time.sleep(0)
        stack_iters += 1
        dir_path, depth = stack.pop()
        dir_path_resolved = os.path.realpath(dir_path)
        if _is_excluded_path(dir_path_resolved, excluded_paths):
            continue
        scanned_dirs.append((dir_path, depth))
        if depth < max_depth:
            try:
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            if not process_hidden and entry.name.startswith('.'):
                                continue
                            entry_path_resolved = os.path.realpath(entry.path)
                            if _is_excluded_path(entry_path_resolved, excluded_paths):
                                continue
                            stack.append((entry.path, depth + 1))
            except (PermissionError, FileNotFoundError, OSError):
                pass

    scan_entry_count = 0
    for directory, _ in scanned_dirs:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if scan_entry_count > 0 and scan_entry_count % 512 == 0:
                        time.sleep(0)
                    scan_entry_count += 1
                    if entry.is_file():
                        entry_path_resolved = os.path.realpath(entry.path)
                        if _is_excluded_path(entry_path_resolved, excluded_paths):
                            continue
                        _, ext = os.path.splitext(entry.name)
                        if ext.lower() in image_extensions:
                            if match_pattern and not fnmatch.fnmatch(entry.name.lower(), match_pattern.lower()):
                                continue
                            try:
                                image_files.append(str(Path(entry.path).resolve()))
                            except (OSError, ValueError):
                                image_files.append(entry.path)
        except (PermissionError, OSError, FileNotFoundError):
            pass

    return image_files


def run_scan(
    root_dir: str,
    max_depth: int,
    progress_callback: Callable[[int, int, str, bool], None],
    cancel_check: Callable[[], bool],
    image_paths_override: Optional[List[str]] = None,
) -> int:
    """
    Scan images under root_dir (up to max_depth), detect faces, and write encodings to face cache.
    If image_paths_override is provided, use that list instead of get_image_list (for non-recursive
    scans that should target specific displayed paths).
    Runs in the thread that calls this (typically a worker thread).
    progress_callback(current_index, total_count, current_path, was_processed) is called after each image.
    was_processed is True when the image was actually processed (not skipped from cache).
    cancel_check() should return True to stop early.
    Returns number of images that had at least one face cached.
    """
    from face_engine import encode_faces_from_path, is_available
    from face_cache import set_encodings, has_cached_faces, flush_face_cache_index

    if not is_available():
        return 0

    image_paths = image_paths_override if image_paths_override is not None else get_image_list(root_dir, max_depth)
    total = len(image_paths)
    cached_count = 0
    skip_dirs_this_run: Set[str] = set()  # dirs we skip this run (cache hit)

    # When given explicit paths (e.g. from person search), bypass directory cache:
    # we must process those paths even if the dir was "scanned" in a previous full run.
    use_dir_cache = USE_DIRECTORY_CACHE and image_paths_override is None

    try:
        for i, path in enumerate(image_paths):
            if cancel_check():
                break
            path = normalize_path_for_face_cache(path)
            dir_path = os.path.dirname(path)
            if use_dir_cache:
                if dir_path in skip_dirs_this_run:
                    progress_callback(i + 1, total, path, False)
                    continue
                if _dir_can_skip(dir_path):
                    skip_dirs_this_run.add(dir_path)
                    progress_callback(i + 1, total, path, False)
                    continue
            try:
                # Skip if we already cached (including negative results).
                if has_cached_faces(path):
                    progress_callback(i + 1, total, path, False)
                    if use_dir_cache:
                        _mark_dir_scanned(dir_path)
                    continue
                encodings = encode_faces_from_path(path)
                # Persist both positive and negative results so cancel/resume
                # doesn't re-scan images we've already processed.
                set_encodings(path, encodings)
                if encodings:
                    cached_count += 1
            except Exception:
                pass
            progress_callback(i + 1, total, path, True)
            if use_dir_cache:
                _mark_dir_scanned(dir_path)
        return cached_count
    finally:
        try:
            flush_face_cache_index()
        except Exception:
            pass
