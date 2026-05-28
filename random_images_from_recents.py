#!/usr/bin/env python3
"""
Random Images from Recents - Load 200 random images from recent directories.

Uses the first 5 unique (highest-level) directories from the File > Recent list.
Respects settings: image extensions, ignore directories, excluded paths.
Excludes .app, .pages, .framework, .bundle, etc. per SKIPPED_PATTERNS.
Isolated module for easy removal.
"""

import fnmatch
import os
import random
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog

from config import get_config
from file_tree_handler import _get_excluded_paths, _is_excluded_path
from thumbnail_constants import get_image_extensions, SKIPPED_PATTERNS

DEFAULT_TARGET_COUNT = 200
MAX_UNIQUE_DIRS = 5


def _is_subpath(child: str, parent: str) -> bool:
    """True if child is equal to or under parent."""
    parent_norm = os.path.normpath(parent).rstrip(os.sep) + os.sep
    child_norm = os.path.normpath(child)
    return child_norm == parent_norm.rstrip(os.sep) or child_norm.startswith(parent_norm)


def _get_unique_highest_level_dirs(recent_dirs: list[str], max_count: int) -> list[str]:
    """
    From recent_dirs (most recent first), return up to max_count unique highest-level dirs.
    If abc and abc/foo are in the list, keep abc (parent) and drop abc/foo.
    """
    selected: list[str] = []
    for candidate in recent_dirs:
        if len(selected) >= max_count:
            break
        candidate = os.path.normpath(candidate)
        if not os.path.isdir(candidate):
            continue
        # Skip if candidate is under any already-selected dir
        if any(_is_subpath(candidate, s) for s in selected):
            continue
        # If candidate is a parent of any selected, replace those with candidate
        selected = [s for s in selected if not _is_subpath(s, candidate)]
        selected.append(candidate)
    return selected[:max_count]


def _should_skip_subdir(dirpath: str, d: str, excluded_paths: list) -> bool:
    """True if subdir d should be skipped (matches SKIPPED_PATTERNS or is under excluded path)."""
    if any(fnmatch.fnmatch(d, p) for p in SKIPPED_PATTERNS):
        return True
    try:
        subpath = os.path.join(dirpath, d)
        return _is_excluded_path(os.path.realpath(subpath), excluded_paths)
    except Exception:
        return True


def _collect_image_files(search_dirs: list[str], config, progress_dialog: Optional[QProgressDialog] = None) -> list[str]:
    """Recursively collect image files from search directories up to search_depth.
    Respects settings: image extensions, ignore directories, excluded paths.
    Skips .app, .pages, .framework, .bundle, etc. per SKIPPED_PATTERNS.
    """
    image_extensions = get_image_extensions()
    excluded_paths = _get_excluded_paths(config)
    max_depth = int(config.load_settings().get('search_depth', 4))
    files = []
    dir_count = 0
    for root_dir in search_dirs:
        if not os.path.isdir(root_dir):
            continue
        stack = [(root_dir, 0)]
        while stack:
            if progress_dialog and progress_dialog.wasCanceled():
                return []
            dirpath, depth = stack.pop()
            try:
                dirpath_resolved = os.path.realpath(dirpath)
            except Exception:
                dirpath_resolved = dirpath
            if _is_excluded_path(dirpath_resolved, excluded_paths):
                continue
            try:
                with os.scandir(dirpath) as entries:
                    for entry in entries:
                        if entry.is_file():
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in image_extensions:
                                files.append(entry.path)
                        elif entry.is_dir(follow_symlinks=False) and depth < max_depth:
                            if not _should_skip_subdir(dirpath, entry.name, excluded_paths):
                                stack.append((entry.path, depth + 1))
            except (PermissionError, OSError, FileNotFoundError):
                pass
            dir_count += 1
            if progress_dialog and dir_count % 50 == 0:
                progress_dialog.setLabelText(f"Scanning... {len(files)} images found")
                QApplication.processEvents()
    return files


def run_random_images_from_recents(main_window, target_count: int = DEFAULT_TARGET_COUNT) -> bool:
    """
    Load target_count random images from the first 5 unique recent directories.
    Returns True if images were loaded, False otherwise.
    """
    mw = main_window
    handler = getattr(mw, 'directory_history_handler_for_menu', None)
    if not handler:
        return False
    recent_raw = getattr(handler, 'directory_history', [])
    tmp_trashes = getattr(mw, 'TMP_TRASHES_DIR', None)
    filtered = [
        d for d in reversed(recent_raw)
        if os.path.exists(d) and (tmp_trashes is None or d != tmp_trashes)
    ]
    search_dirs = _get_unique_highest_level_dirs(filtered, MAX_UNIQUE_DIRS)
    if not search_dirs:
        return False
    config = getattr(mw, 'config', None) or get_config()

    progress_dialog = QProgressDialog("Collecting images from recent directories...", None, 0, 0, mw)
    progress_dialog.setWindowTitle("Random Images")
    progress_dialog.setWindowModality(Qt.WindowModal)
    progress_dialog.setCancelButton(None)
    progress_dialog.setMinimumDuration(0)
    progress_dialog.setAutoClose(True)
    progress_dialog.setRange(0, 0)  # Indeterminate / busy indicator
    progress_dialog.show()
    QApplication.processEvents()

    try:
        files = _collect_image_files(search_dirs, config, progress_dialog)
        if not files:
            return False
        progress_dialog.setLabelText("Selecting random images...")
        QApplication.processEvents()
        selected = random.sample(files, min(target_count, len(files)))
        random.shuffle(selected)
        if hasattr(mw, 'load_specific_files'):
            mw.load_specific_files(selected, external_load=True)
            return True
        return False
    finally:
        progress_dialog.close()
