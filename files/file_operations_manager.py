#!/usr/bin/env python3
"""
File Operations Manager for Image Browser
Handles file deletion, directory operations, and file management

CRITICAL: .prsort FILE USAGE RULES
===================================
The .prsort file is ONLY used for:
1. Custom sort ordering (when SortMode.CUSTOM is active)
2. File locking (determining which files are locked and their saved order)

.prsort is NEVER used to order unlocked files during normal operations.
Unlocked files preserve their current visual order or are sorted by the active sort mode.

DO NOT use .prsort to determine file order except:
- When applying a custom sort (SortMode.CUSTOM)
- When determining which files are locked and their saved order

This rule applies throughout this entire codebase and all related code.

DO NOT REMOVE THIS COMMENT.  DO NOT IGNORE THIS COMMENT.
"""

# Standard library imports
import hashlib
import logging
import os
import random
import shutil
import subprocess
import string
import threading
import time
import traceback
import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Third-party imports
import numpy as np
from PIL import Image
from PySide6.QtCore import QEventLoop, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressDialog,
    QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget
)
import torch

# Local imports
from config import get_config
from macos_process import run_osascript
from exif.exif_image_loader import get_image_dimensions_fast_metadata
from files.file_move_handler import FileMoveHandler
from pil_image_io import open_pil_with_exif_correction
from thumbnails.thumbnail_constants import GREEN, RED, RESET, get_image_extensions
from utils import (
    styled_message_box,
    show_styled_critical,
    show_styled_information,
    show_styled_question,
    show_styled_warning,
    create_file_operation_progress_dialog,
    create_titled_progress_dialog,
    elide_progress_filename,
    wrap_progress_dialog_label_elision,
    file_string,
    folder_basename_for_display,
    get_button_style,
    get_dialog_shell_stylesheet,
    get_file_extension,
    is_inside_photos_library,
)

# AppKit imports for file operations - will be imported lazily when needed
_NSWorkspace = _NSUndoManager = _NSObject = _NSWorkspaceRecycleOperation = None

logger = logging.getLogger(__name__)


class AppleScriptUndoManager:
    """AppleScript-based undo manager for file operations"""
    
    def __init__(self):
        self.is_available = True
        if not self.is_available:
            logger.warning("AppleScript undo manager only available on macOS")
    
    def _generate_unique_filename(self, original_path):
        """Generate a unique filename to avoid overwriting existing files"""
        directory = os.path.dirname(original_path)
        filename = os.path.basename(original_path)
        name, ext = os.path.splitext(filename)
        
        # Check if original filename is available
        if not os.path.exists(original_path):
            return original_path
        
        # Try with "-restored" suffix
        restored_name = f"{name}-restored{ext}"
        restored_path = os.path.join(directory, restored_name)
        
        if not os.path.exists(restored_path):
            return restored_path
        
        # Try with sequential numbers
        counter = 1
        while True:
            numbered_name = f"{name}-restored-{counter}{ext}"
            numbered_path = os.path.join(directory, numbered_name)
            if not os.path.exists(numbered_path):
                return numbered_path
            counter += 1
    
    def restore_file_from_trash(self, original_path: str, original_position: Optional[int] = None) -> bool:
        """
        Restore a file from trash using AppleScript
        
        Args:
            original_path: The original file path before deletion
            original_position: Optional position in the image list
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_available:
            logger.error("AppleScript not available")
            return False
        
        logger.debug(f"AppleScript undo: Starting restoration of {original_path}")
        logger.debug(f"AppleScript undo: Original position: {original_position}")
        
        try:
            # Generate unique filename to avoid overwriting existing files
            unique_path = self._generate_unique_filename(original_path)
            filename = os.path.basename(unique_path)
            directory = os.path.dirname(unique_path)
            
            logger.debug(f"AppleScript undo: Original path: {original_path}")
            logger.debug(f"AppleScript undo: Unique path: {unique_path}")
            logger.debug(f"AppleScript undo: Filename: {filename}")
            logger.debug(f"AppleScript undo: Directory: {directory}")
            
            # Check if original directory exists
            if not os.path.exists(directory):
                logger.error(f"AppleScript undo: Original directory does not exist: {directory}")
                return False
            
            # Check directory permissions
            try:
                dir_readable = os.access(directory, os.R_OK)
                dir_writable = os.access(directory, os.W_OK)
                logger.debug(f"AppleScript undo: Directory readable: {dir_readable}, writable: {dir_writable}")
            except Exception as e:
                logger.error(f"AppleScript undo: Error checking directory permissions: {e}")
            
            # Try AppleScript first
            success = self._try_applescript_restore(original_path, unique_path, filename, directory)
            if success:
                return True
            
            # If AppleScript fails, try system trash command as fallback
            logger.debug("AppleScript failed, trying system trash command fallback...")
            return self._try_system_trash_restore(filename, directory, original_path, unique_path)
            
        except Exception as e:
            logger.error(f"AppleScript undo: Exception while restoring {filename}: {e}")
            return False
    
    def _try_applescript_restore(self, original_path: str, unique_path: str, filename: str, directory: str) -> bool:
        """Try to restore file using AppleScript"""
        try:
            # Create simple AppleScript that just finds the file
            original_filename = os.path.basename(original_path)
            script = f'''
            tell application "Finder"
                try
                    -- Find the file in trash by name
                    set trashItems to items of trash
                    repeat with trashItem in trashItems
                        if name of trashItem is "{original_filename}" then
                            return "FOUND:" & name of trashItem
                        end if
                    end repeat
                    return "NOT_FOUND"
                on error
                    return "ERROR:Script failed"
                end try
            end tell
            '''
            
            logger.debug("AppleScript undo: Executing AppleScript...")
            logger.debug(f"AppleScript undo: Script content:\n{script}")
            
            # Execute the AppleScript with shorter timeout to prevent beachball
            result = run_osascript(script, timeout=10)
            
            logger.debug(f"AppleScript undo: Subprocess return code: {result.returncode}")
            logger.debug(f"AppleScript undo: Subprocess stdout: {result.stdout.strip()}")
            if result.stderr:
                logger.debug(f"AppleScript undo: Subprocess stderr: {result.stderr.strip()}")
            
            if result.returncode == 0:
                output = result.stdout.strip()
                logger.debug(f"AppleScript undo: Raw output: '{output}'")
                
                if output.startswith("FOUND:"):
                    # AppleScript found the file, now use system commands to restore it
                    found_filename = output[6:]  # Remove "FOUND:" prefix
                    logger.info(f"AppleScript undo: Found file in trash: {found_filename}")
                    
                    # Construct the trash path
                    trash_path = os.path.expanduser("~/.Trash")
                    trash_item_path = os.path.join(trash_path, found_filename)
                    logger.info(f"AppleScript undo: Constructed trash path: {trash_item_path}")
                    
                    # Try to restore using system commands
                    return self._restore_with_system_commands(trash_item_path, unique_path)
                        
                        
                elif output == "NOT_FOUND":
                    logger.debug(f"AppleScript undo: File {filename} not found in trash")
                    return False
                elif output.startswith("ERROR:"):
                    error_msg = output[6:]  # Remove "ERROR:" prefix
                    logger.error(f"AppleScript undo: Error restoring {filename}: {error_msg}")
                    return False
                else:
                    logger.debug(f"AppleScript undo: Unexpected output: '{output}'")
                    return False
            else:
                error_msg = result.stderr.strip()
                logger.error(f"AppleScript undo: Subprocess execution failed: {error_msg}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"AppleScript undo: Timeout while restoring {filename}, trying system fallback")
            # Try system restore as fallback when AppleScript times out
            return self._try_system_trash_restore(filename, directory, original_path, unique_path)
        except Exception as e:
            logger.error(f"AppleScript undo: Exception while restoring {filename}: {e}")
            return False
    
    def _restore_with_system_commands(self, trash_item_path: str, target_path: str) -> bool:
        """Restore file using system commands with the actual trash path"""
        try:
            logger.info(f"System restore: Attempting to restore from {trash_item_path} to {target_path}")
            
            # Try using mv command with the actual trash path
            result = subprocess.run(
                ['mv', trash_item_path, target_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                logger.info(f"System restore: Successfully restored file using mv")
                return True
            else:
                logger.error(f"System restore: mv command failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"System restore: mv command timed out")
            return False
        except Exception as e:
            logger.error(f"System restore: Exception: {e}")
            return False
    
    def _try_system_trash_restore(self, filename: str, directory: str, original_path: str, unique_path: str) -> bool:
        """Try to restore file using system trash command as fallback"""
        try:
            logger.debug(f"System trash fallback: Attempting to restore {filename}")
            logger.debug(f"System trash fallback: Original path: {original_path}")
            logger.debug(f"System trash fallback: Unique path: {unique_path}")
            
            # Try using mv command directly - this often works even with permission restrictions
            logger.debug("System trash fallback: Trying mv command...")
            
            # Construct the trash path using the original filename
            trash_path = os.path.expanduser("~/.Trash")
            original_filename = os.path.basename(original_path)
            trash_file_path = os.path.join(trash_path, original_filename)
            
            # Check if file exists in trash
            if os.path.exists(trash_file_path):
                logger.debug(f"System trash fallback: Found file in trash: {trash_file_path}")
                
                # Try to restore using mv command (mv preserves dates by default)
                try:
                    logger.debug(f"System trash fallback: Moving from {trash_file_path} to {unique_path}")
                    result = subprocess.run(
                        ['mv', trash_file_path, unique_path],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"System trash fallback: Successfully restored {filename} using mv to {unique_path}")
                        return True
                    else:
                        logger.error(f"System trash fallback: mv command failed: {result.stderr}")
                        return False
                        
                except subprocess.TimeoutExpired:
                    logger.error(f"System trash fallback: mv command timed out")
                    return False
                except Exception as e:
                    logger.error(f"System trash fallback: mv command exception: {e}")
                    return False
            else:
                logger.debug(f"System trash fallback: File not found in trash: {trash_file_path}")
                logger.debug(f"System trash fallback: No matching file found for {filename}")
                return False
            
        except Exception as e:
            logger.error(f"System trash fallback: Exception: {e}")
            return False
    
    def test_connection(self) -> bool:
        """Test if AppleScript can communicate with Finder"""
        if not self.is_available:
            logger.warning("AppleScript not available")
            return False
        
        logger.debug("AppleScript undo: Testing connection to Finder...")
        
        try:
            script = '''
            tell application "Finder"
                log "AppleScript: Testing connection to Finder"
                return "OK"
            end tell
            '''
            
            result = run_osascript(script, timeout=10)
            
            success = result.returncode == 0 and result.stdout.strip() == "OK"
            logger.debug(f"AppleScript undo: Connection test result: {success}")
            
            if not success:
                logger.debug(f"AppleScript undo: Connection test failed - return code: {result.returncode}")
                if result.stderr:
                    logger.debug(f"AppleScript undo: Connection test stderr: {result.stderr.strip()}")
            
            return success
        except Exception as e:
            logger.error(f"AppleScript undo: Exception during connection test: {e}")
            return False

def test_applescript_undo():
    """Test the AppleScript undo functionality"""
    logger.info("Testing AppleScript undo functionality...")
    
    manager = AppleScriptUndoManager()
    
    if not manager.is_available:
        logger.error("AppleScript not available on this platform")
        return
    
    # Test connection
    if manager.test_connection():
        logger.info("✓ AppleScript connection to Finder: SUCCESS")
    else:
        logger.error("✗ AppleScript connection to Finder: FAILED")
        return
    
    # Test with a dummy file (won't actually restore anything)
    logger.info("Testing with dummy file path...")
    test_path = "/tmp/test_image.jpg"
    result = manager.restore_file_from_trash(test_path)
    
    if result:
        logger.info("✓ AppleScript undo test: SUCCESS")
    else:
        logger.info("✗ AppleScript undo test: FAILED (expected for non-existent file)")

def _import_appkit_modules():
    """Lazily import AppKit modules when needed"""
    global _NSWorkspace, _NSUndoManager, _NSObject, _NSWorkspaceRecycleOperation
    if _NSWorkspace is None:
        try:
            from AppKit import NSWorkspace, NSUndoManager, NSObject, NSWorkspaceRecycleOperation
            _NSWorkspace, _NSUndoManager, _NSObject, _NSWorkspaceRecycleOperation = (
                NSWorkspace, NSUndoManager, NSObject, NSWorkspaceRecycleOperation
            )
        except ImportError:
            pass

# Constant to control whether quick mass rename uses user's saved settings
# When True: Uses user's last saved settings (sort_mode, date_change_mode, order_direction)
# When False: Uses hardcoded presets (order, none, top) and saves them
QUICK_MASS_RENAME_USE_USER_SETTINGS = True


def _per_directory_duplicate_auto_select_paths(hash_path_pairs: List[Tuple[str, str]]) -> Set[str]:
    """Within each byte-identical hash group, paths to multi-select: all but the first per parent dir.

    The kept file in each directory is the lexicographically smallest full path among duplicates there.
    """
    if not hash_path_pairs:
        return set()
    out: Set[str] = set()
    i = 0
    n = len(hash_path_pairs)
    while i < n:
        file_hash = hash_path_pairs[i][0]
        group_paths: List[str] = []
        while i < n and hash_path_pairs[i][0] == file_hash:
            group_paths.append(hash_path_pairs[i][1])
            i += 1
        dir_to_paths: Dict[str, List[str]] = {}
        for p in group_paths:
            dir_to_paths.setdefault(os.path.dirname(p), []).append(p)
        for paths in dir_to_paths.values():
            paths_sorted = sorted(paths)
            if len(paths_sorted) > 1:
                out.update(paths_sorted[1:])
    return out


# Similar-image duplicate search: EXIF-oriented decode, resize to this width (aspect preserved), RGB MSE clustering.
SIMILAR_COMPARE_WIDTH = 128
# Mean squared error on pixels in 0..1 (cross-codec re-exports of the same bitmap).
SIMILAR_IMAGE_MSE_THRESHOLD = 0.0026
# BILINEAR is much faster than LANCZOS at scale; sufficient for cross-codec matching.
SIMILAR_RESAMPLE = Image.Resampling.BILINEAR
# Run heavy similarity work off the UI thread when this many paths are analyzed.
SIMILAR_WORKER_THREAD_MIN_PATHS = 2000
# Above this many decoded images in one dimension bucket, use mean-color spatial binning
# (same + neighbor RGB cells) to avoid O(n²) all-pairs on huge same-resolution sets.
SIMILAR_BINNED_CLUSTER_MIN = 350
# Cap candidate neighbors per index after binning (pathological single-color bins).
SIMILAR_MAX_CANDIDATES_PER_INDEX = 650
# Decode/compare thumbnails in parallel above this bucket size (I/O + Pillow often release GIL).
SIMILAR_DECODE_PARALLEL_MIN = 40
SIMILAR_DECODE_MAX_WORKERS = 8


def _present_duplicate_groups_browse_view(
    mw,
    group_path_pairs: List[Tuple[str, str]],
    current_image_path: Optional[str],
    status_notification_message: str,
    *,
    auto_select: bool = True,
    convert_conflict_context: Optional[dict] = None,
) -> None:
    """Shared finish path for exact-duplicate (MD5) and similar-image duplicate modes (same UX)."""
    if not group_path_pairs:
        return

    if convert_conflict_context is not None:
        mw.convert_conflict_context = convert_conflict_context
    else:
        mw.convert_conflict_context = None

    if hasattr(mw, "directory_stack_history_handler"):
        current_state = mw.directory_stack_history_handler.capture_current_state()
        if current_state and not mw.directory_stack_history_handler.is_duplicate_state(current_state):
            mw.directory_stack_history_handler.backward_stack.append(current_state)
            mw.directory_stack_history_handler.forward_stack.clear()

    duplicate_displayed = [path for _, path in group_path_pairs]

    duplicate_sections: List[Tuple[int, str]] = []
    current_group_key: Optional[str] = None
    for idx, (group_key, file_path) in enumerate(group_path_pairs):
        if group_key != current_group_key:
            duplicate_sections.append((idx, group_key))
            current_group_key = group_key

    mw.duplicate_sections = duplicate_sections

    from sort_mode import SortMode

    mw.current_sort_mode = SortMode.DUPLICATES
    mw.is_reversed = False

    configuration = {
        "files": duplicate_displayed,
        "prevent_browse_view": True,
        "force_specific_files_grid": len(duplicate_displayed) == 1,
        "skip_filter_pattern": True,
    }
    if hasattr(mw, "refresh_from_configuration"):
        mw.refresh_from_configuration(configuration)

    # refresh + load_specific_files use set_thumbnails for the grid; ensure duplicate mode and
    # section list are still the source of truth for the canvas (defensive if anything cleared them).
    mw.duplicate_sections = duplicate_sections
    mw.current_sort_mode = SortMode.DUPLICATES

    mw.displayed_images = duplicate_displayed

    if current_image_path and current_image_path in mw.displayed_images:
        mw.set_current_image_by_path(current_image_path, fallback_index=0)
    else:
        if mw.displayed_images:
            mw.set_current_image_by_path(mw.displayed_images[0], fallback_index=0)
        else:
            mw.highlight_index = 0
            mw.current_index = 0

    if not hasattr(mw, "image_indices") or not mw.image_indices:
        mw.image_indices = list(range(len(mw.displayed_images)))

    if hasattr(mw, "generate_thumbnails"):
        mw.generate_thumbnails(force_refresh=True)

    if hasattr(mw, "thumbnail_container") and mw.thumbnail_container:
        if hasattr(mw.thumbnail_container, "canvas"):
            if hasattr(mw.thumbnail_container.canvas, "reorder_thumbnails"):
                mw.thumbnail_container.canvas.reorder_thumbnails(
                    duplicate_displayed, force_recalculate_grid=True
                )
                if hasattr(mw, "debug_mode") and mw.debug_mode:
                    print(
                        "Explicitly called reorder_thumbnails (duplicate groups) with "
                        f"{len(duplicate_displayed)} files, duplicate_sections={getattr(mw, 'duplicate_sections', None)}"
                    )

    if auto_select:
        auto_sel = _per_directory_duplicate_auto_select_paths(group_path_pairs)
        if auto_sel:
            mw.selected_files = set(auto_sel)
            keeper = next(
                (p for p in duplicate_displayed if p not in auto_sel),
                duplicate_displayed[0] if duplicate_displayed else None,
            )
            if keeper:
                mw.set_current_image_by_path(keeper, fallback_index=0)
            mw._emit_selection_changed(getattr(mw, "highlight_index", None))
        else:
            mw.selected_files.clear()
    else:
        mw.selected_files.clear()
        if hasattr(mw, "_emit_selection_changed"):
            mw._emit_selection_changed(getattr(mw, "highlight_index", None))

    if hasattr(mw, "highlight_image"):
        mw.highlight_image()

    mw.status_notification.show_message(status_notification_message)

    if hasattr(mw, "update_status_bar_sections"):
        mw.update_status_bar_sections()

    if hasattr(mw, "update_sort_menu_checkmarks"):
        mw.update_sort_menu_checkmarks()

    if hasattr(mw, "save_sorting_settings"):
        mw.save_sorting_settings()

    # Grouped duplicate/conflict views always land in thumbnail mode.
    if getattr(mw, "current_view_mode", None) != "thumbnail":
        if hasattr(mw, "view_manager") and mw.view_manager:
            mw.view_manager.close_browse_view()

    if hasattr(mw, "update_convert_conflict_auto_rename_button"):
        mw.update_convert_conflict_auto_rename_button()


def _pil_rgb_to_compare_array(pil_img: Image.Image) -> np.ndarray:
    """RGB PIL image -> float32 (H, W, 3) in 0..1, resized to width SIMILAR_COMPARE_WIDTH."""
    pil_img = pil_img.convert("RGB")
    w, h = pil_img.size
    if w <= 0 or h <= 0:
        raise ValueError("invalid image size")
    new_w = SIMILAR_COMPARE_WIDTH
    new_h = max(1, int(round(h * (new_w / float(w)))))
    pil_img = pil_img.resize((new_w, new_h), SIMILAR_RESAMPLE)
    arr = np.asarray(pil_img, dtype=np.float32)
    arr /= 255.0
    return arr


def _similar_compare_array_from_path(image_path: str) -> Optional[np.ndarray]:
    pil_img = open_pil_with_exif_correction(image_path, ignore_exif=False)
    if pil_img is None:
        return None
    try:
        return _pil_rgb_to_compare_array(pil_img)
    except Exception:
        return None


def _oriented_dimensions_for_similarity(image_path: str) -> Optional[Tuple[int, int]]:
    dims = get_image_dimensions_fast_metadata(image_path)
    if dims:
        return dims
    pil_img = open_pil_with_exif_correction(image_path, ignore_exif=False)
    if pil_img is None:
        return None
    try:
        return pil_img.size
    except Exception:
        return None


def _mean_color_cell(arr: np.ndarray) -> Tuple[int, int, int]:
    """8×8×8 coarse RGB cell for spatial binning (values 0..7 per channel)."""
    m = np.clip(arr.mean(axis=(0, 1)), 0.0, 1.0)
    return (int(m[0] * 7.999), int(m[1] * 7.999), int(m[2] * 7.999))


def _similar_compare_digest(arr: np.ndarray) -> bytes:
    """Stable digest of compare tensor for exact-match grouping (avoids pairwise MSE)."""
    a = np.ascontiguousarray(arr, dtype=np.float32)
    h = hashlib.blake2b(digest_size=16, usedforsecurity=False)
    h.update(memoryview(a))
    return h.digest()


def _mse_mean_sq_diff(ai: np.ndarray, bj: np.ndarray, scratch: np.ndarray) -> float:
    """Mean squared difference; reuses scratch (same shape as ai, bj)."""
    np.subtract(ai, bj, out=scratch)
    np.square(scratch, out=scratch)
    return float(scratch.mean())


def _load_compare_arrays_for_paths(
    paths: List[str],
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_tick: Optional[Callable[[], None]] = None,
) -> Optional[List[Tuple[str, np.ndarray]]]:
    """Decode paths to compare arrays; parallel decode for large buckets. Returns None if cancelled."""
    n = len(paths)
    if n < SIMILAR_DECODE_PARALLEL_MIN:
        loaded: List[Tuple[str, np.ndarray]] = []
        for bi, p in enumerate(paths):
            if bi % 24 == 0:
                if cancel_check and cancel_check():
                    return None
                if progress_tick:
                    progress_tick()
            arr = _similar_compare_array_from_path(p)
            if arr is not None:
                loaded.append((p, arr))
        return loaded

    max_workers = min(SIMILAR_DECODE_MAX_WORKERS, max(1, os.cpu_count() or 4))
    chunk = max(2, n // (max_workers * 8))
    arrays: List[Optional[np.ndarray]] = []
    cancelled_early = False
    try:
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            for bi, arr in enumerate(
                executor.map(_similar_compare_array_from_path, paths, chunksize=chunk)
            ):
                if bi % 24 == 0:
                    if cancel_check and cancel_check():
                        cancelled_early = True
                        break
                    if progress_tick:
                        progress_tick()
                arrays.append(arr)
        finally:
            executor.shutdown(wait=False, cancel_futures=cancelled_early)
    except Exception:
        arrays = [_similar_compare_array_from_path(p) for p in paths]
        cancelled_early = False

    if cancelled_early:
        return None

    loaded = []
    for bi, arr in enumerate(arrays):
        if arr is not None:
            loaded.append((paths[bi], arr))
    return loaded


def _cluster_paths_by_similarity_mse(
    paths: List[str],
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_tick: Optional[Callable[[], None]] = None,
) -> Optional[List[List[str]]]:
    """Within one (width, height) bucket, cluster paths whose compare thumbnails are within MSE threshold.

    Returns None if cancel_check requested stop (distinct from [] = no similar groups in bucket).
    """
    if len(paths) < 2:
        return []

    loaded = _load_compare_arrays_for_paths(paths, cancel_check=cancel_check, progress_tick=progress_tick)
    if loaded is None:
        return None

    n = len(loaded)
    if n < 2:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    digest_to_indices: Dict[bytes, List[int]] = defaultdict(list)
    use_bins = n >= SIMILAR_BINNED_CLUSTER_MIN
    mean_keys: List[Tuple[int, int, int]] = []
    bin_to_indices: Dict[Tuple[int, int, int], List[int]] = defaultdict(list)

    for idx in range(n):
        if idx % 64 == 0:
            if cancel_check and cancel_check():
                return None
            if progress_tick:
                progress_tick()
        arr = loaded[idx][1]
        digest_to_indices[_similar_compare_digest(arr)].append(idx)
        if use_bins:
            mk = _mean_color_cell(arr)
            mean_keys.append(mk)
            bin_to_indices[mk].append(idx)

    for ids in digest_to_indices.values():
        if len(ids) < 2:
            continue
        head = ids[0]
        for other in ids[1:]:
            union(head, other)

    scratch = np.empty_like(loaded[0][1], dtype=np.float32)

    thr = SIMILAR_IMAGE_MSE_THRESHOLD
    ops = 0

    if use_bins:
        for i in range(n):
            if i % 12 == 0:
                if cancel_check and cancel_check():
                    return None
                if progress_tick:
                    progress_tick()
            ki = mean_keys[i]
            cand: Set[int] = set()
            for dr in (-1, 0, 1):
                for dg in (-1, 0, 1):
                    for db in (-1, 0, 1):
                        nk = (
                            max(0, min(7, ki[0] + dr)),
                            max(0, min(7, ki[1] + dg)),
                            max(0, min(7, ki[2] + db)),
                        )
                        for j in bin_to_indices.get(nk, ()):
                            if j > i:
                                cand.add(j)
            if len(cand) > SIMILAR_MAX_CANDIDATES_PER_INDEX:
                cand = set(sorted(cand)[:SIMILAR_MAX_CANDIDATES_PER_INDEX])
            ai = loaded[i][1]
            for j in cand:
                if find(i) == find(j):
                    continue
                bj = loaded[j][1]
                if ai.shape != bj.shape:
                    continue
                ops += 1
                if ops % 400 == 0 and progress_tick:
                    progress_tick()
                if cancel_check and cancel_check():
                    return None
                if _mse_mean_sq_diff(ai, bj, scratch) <= thr:
                    union(i, j)
    else:
        for i in range(n):
            if i % 8 == 0:
                if cancel_check and cancel_check():
                    return None
                if progress_tick:
                    progress_tick()
            ai = loaded[i][1]
            for j in range(i + 1, n):
                if find(i) == find(j):
                    continue
                bj = loaded[j][1]
                if ai.shape != bj.shape:
                    continue
                ops += 1
                if ops % 300 == 0 and progress_tick:
                    progress_tick()
                if cancel_check and cancel_check():
                    return None
                if _mse_mean_sq_diff(ai, bj, scratch) <= thr:
                    union(i, j)

    root_to_paths: Dict[int, List[str]] = {}
    for idx in range(n):
        r = find(idx)
        root_to_paths.setdefault(r, []).append(loaded[idx][0])

    return [g for g in root_to_paths.values() if len(g) > 1]


def _build_similar_image_group_pairs_impl(
    image_paths: List[str],
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    progress_tick: Optional[Callable[[], None]] = None,
) -> Tuple[List[Tuple[str, str]], bool]:
    """
    Build sorted (group_key, path) pairs for images that have at least one other similar file.
    cancel_check: if set, return ([], True) when it returns True.
    progress_cb: optional (value, maximum, label).
    progress_tick: optional lightweight heartbeat (e.g. Qt signal from worker thread).
    """
    dim_bucket: Dict[Tuple[int, int], List[str]] = {}
    n = len(image_paths)

    def tick() -> None:
        if progress_tick:
            progress_tick()

    cancelled = False
    for idx, file_path in enumerate(image_paths):
        if idx % 64 == 0:
            tick()
        if cancel_check and cancel_check():
            cancelled = True
            break
        if progress_cb:
            progress_cb(
                idx, max(1, n),
                f"Sizing {elide_progress_filename(os.path.basename(file_path))}... ({idx + 1}/{n})",
            )

        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            continue

        dims = _oriented_dimensions_for_similarity(file_path)
        if dims is None:
            continue
        dim_bucket.setdefault(dims, []).append(file_path)

    if cancelled:
        return [], True

    if progress_cb:
        progress_cb(n, max(1, n), "Grouping by size...")

    bucket_list = [(d, pl) for d, pl in sorted(dim_bucket.items(), key=lambda kv: kv[0]) if len(pl) >= 2]
    total_buckets = len(bucket_list)
    raw_pairs: List[Tuple[str, str]] = []

    for bidx, (_dim, plist) in enumerate(bucket_list):
        tick()
        if cancel_check and cancel_check():
            return [], True
        if progress_cb:
            progress_cb(
                bidx,
                max(1, total_buckets),
                f"Comparing similar images ({_dim[0]}×{_dim[1]}, {len(plist)} files)... "
                f"bucket {bidx + 1}/{total_buckets}",
            )
        groups = _cluster_paths_by_similarity_mse(plist, cancel_check=cancel_check, progress_tick=progress_tick)
        if groups is None:
            return [], True
        for group in groups:
            group_key = min(group)
            for p in sorted(group):
                raw_pairs.append((group_key, p))

    raw_pairs.sort(key=lambda x: (x[0], x[1]))
    return raw_pairs, False


def _build_similar_image_group_pairs(
    image_paths: List[str], progress_dialog: QProgressDialog
) -> Tuple[List[Tuple[str, str]], bool]:
    """Main-thread: drive progress dialog while computing similar pairs."""

    def cancel_check() -> bool:
        return bool(progress_dialog.wasCanceled())

    def progress_cb(value: int, maximum: int, text: str) -> None:
        progress_dialog.setMaximum(maximum)
        progress_dialog.setValue(min(value, maximum))
        progress_dialog.setLabelText(text)
        QApplication.processEvents()

    return _build_similar_image_group_pairs_impl(
        image_paths,
        cancel_check=cancel_check,
        progress_cb=progress_cb,
        progress_tick=None,
    )


class _SimilarImagePairsWorkerThread(QThread):
    """Background computation for similar-image grouping (keeps UI responsive)."""

    progress = Signal(int, int, str)
    finished_pairs = Signal(object, bool)

    def __init__(self, image_paths: List[str]):
        super().__init__()
        self._paths = list(image_paths)
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        def tick() -> None:
            self.progress.emit(-1, -1, "")

        def cancel_check() -> bool:
            return self._cancel.is_set()

        def progress_cb(value: int, maximum: int, text: str) -> None:
            self.progress.emit(value, maximum, text)

        pairs, cancelled = _build_similar_image_group_pairs_impl(
            self._paths,
            cancel_check=cancel_check,
            progress_cb=progress_cb,
            progress_tick=tick,
        )
        self.finished_pairs.emit(pairs, cancelled)


def _run_similar_image_group_pairs_ui(
    parent: QWidget,
    image_paths: List[str],
    window_title: str,
) -> Tuple[List[Tuple[str, str]], bool]:
    """Show progress while computing similar-image groups; use a worker thread for large path sets."""
    n = len(image_paths)
    progress_dialog = create_titled_progress_dialog(
        parent, window_title, max(1, n), label="Analyzing images..."
    )

    if n >= SIMILAR_WORKER_THREAD_MIN_PATHS:
        loop = QEventLoop(parent)
        result: List[Tuple[List[Tuple[str, str]], bool]] = [([], False)]
        worker = _SimilarImagePairsWorkerThread(image_paths)

        def on_progress(value: int, maximum: int, text: str) -> None:
            if value == -1 and maximum == -1:
                QApplication.processEvents()
                if progress_dialog.wasCanceled():
                    worker.request_cancel()
                return
            progress_dialog.setMaximum(maximum)
            progress_dialog.setValue(min(value, maximum))
            if text:
                progress_dialog.setLabelText(text)

        def on_finished_pairs(pairs: object, cancelled: bool) -> None:
            pl = pairs if isinstance(pairs, list) else []
            result[0] = (pl, cancelled)
            loop.quit()

        worker.progress.connect(on_progress)
        worker.finished_pairs.connect(on_finished_pairs)
        progress_dialog.canceled.connect(worker.request_cancel)
        worker.start()
        loop.exec()
        worker.wait()
        try:
            progress_dialog.canceled.disconnect(worker.request_cancel)
        except (TypeError, RuntimeError):
            pass
        pairs, cancelled = result[0]
        progress_dialog.close()
        return pairs, cancelled

    pairs, cancelled = _build_similar_image_group_pairs(image_paths, progress_dialog)
    progress_dialog.close()
    return pairs, cancelled


class FileOperationsManager:
    """Manages file operations including deletion, directory selection, and file management"""

    def __init__(self, main_window):
        self.main_window = main_window

    @staticmethod
    def _get_all_readable_trash_directories() -> List[str]:
        """
        Find all readable trash directories on macOS.
        Returns list of trash directory paths that are readable.
        
        Includes:
        - User's home trash: ~/.Trash
        - Volume-specific trash: /Volumes/<volume>/.Trashes/<uid>/
        
        Note: Only returns directories that can be read (listdir succeeds).
        Does not check if directories contain files - that's done separately.
        """
        trash_dirs = []
        uid = os.getuid()
        
        # Check user's home trash directory
        user_trash = os.path.expanduser("~/.Trash")
        try:
            if os.path.isdir(user_trash) and os.access(user_trash, os.R_OK | os.X_OK):
                # Try to list to ensure it's actually readable
                os.listdir(user_trash)
                trash_dirs.append(user_trash)
        except Exception:
            show_styled_information(None, "Error", "User trash not readable")
            pass  # User trash not readable, skip
        
        # Check volume-specific trash directories
        volumes_dir = "/Volumes"
        try:
            if os.path.isdir(volumes_dir) and os.access(volumes_dir, os.R_OK | os.X_OK):
                for volume_name in os.listdir(volumes_dir):
                    # Skip hidden files and special directories
                    if volume_name.startswith('.'):
                        continue
                    
                    volume_path = os.path.join(volumes_dir, volume_name)
                    # Skip if not a directory or is a symlink to a non-existent path
                    if not os.path.isdir(volume_path):
                        continue
                    
                    # Check for .Trashes directory
                    trashes_dir = os.path.join(volume_path, ".Trashes")
                    if not os.path.isdir(trashes_dir):
                        continue
                    
                    # Check for user-specific trash directory
                    user_trash_path = os.path.join(trashes_dir, str(uid))
                    try:
                        if os.path.isdir(user_trash_path) and os.access(user_trash_path, os.R_OK | os.X_OK):
                            # Try to list to ensure it's actually readable
                            os.listdir(user_trash_path)
                            trash_dirs.append(user_trash_path)
                    except Exception:
                        pass  # This volume's trash not readable, skip
        except Exception:
            pass  # Can't access /Volumes, skip volume trash
        
        return trash_dirs

    @staticmethod
    def _has_readable_trash_with_images() -> bool:
        """
        Check if any readable trash directory contains image files.
        Returns True if at least one trash location has readable image files.
        """
        trash_dirs = FileOperationsManager._get_all_readable_trash_directories()
        if not trash_dirs:
            return False
        
        image_exts = get_image_extensions()
        
        for trash_dir in trash_dirs:
            try:
                files = os.listdir(trash_dir)
                for f in files:
                    if get_file_extension(f) in image_exts:
                        file_path = f"{trash_dir.rstrip('/')}/{f}"
                        if os.path.isfile(file_path):
                            return True
            except Exception:
                continue
        
        return False

    @staticmethod
    def _is_in_trash_directory(file_path: str, main_window=None) -> bool:
        """Check if a file path is within any trash directory
        
        Args:
            file_path: Path to check
            main_window: Optional main window instance to check TMP_TRASHES_DIR
            
        Returns:
            True if the path is within a trash directory, False otherwise
        """
        try:
            abs_path = os.path.abspath(file_path)
            # Get all trash directories
            trash_dirs = FileOperationsManager._get_all_readable_trash_directories()
            for trash_dir in trash_dirs:
                abs_trash_dir = os.path.abspath(trash_dir)
                # Check if the path starts with the trash directory
                if abs_path.startswith(abs_trash_dir + os.sep) or abs_path == abs_trash_dir:
                    return True
            # Also check for TMP_TRASHES_DIR (temporary trash browsing directory)
            if main_window and hasattr(main_window, 'TMP_TRASHES_DIR'):
                tmp_trash_dir = os.path.abspath(main_window.TMP_TRASHES_DIR)
                if abs_path.startswith(tmp_trash_dir + os.sep) or abs_path == tmp_trash_dir:
                    return True
            return False
        except Exception:
            return False
    
    @staticmethod
    def _is_browsing_trash(main_window) -> bool:
        """Check if currently browsing a trash directory
        
        Args:
            main_window: Main window instance
            
        Returns:
            True if currently browsing a trash directory, False otherwise
        """
        try:
            current_dir = getattr(main_window, 'current_directory', None)
            if not current_dir:
                # Check current image path
                current_image = getattr(main_window, 'get_current_image_path', lambda: None)()
                if current_image:
                    current_dir = os.path.dirname(current_image)
                else:
                    return False
            
            if not current_dir:
                return False
            
            # Check if current directory is a trash directory
            abs_current_dir = os.path.abspath(current_dir)
            trash_dirs = FileOperationsManager._get_all_readable_trash_directories()
            for trash_dir in trash_dirs:
                abs_trash_dir = os.path.abspath(trash_dir)
                if abs_current_dir.startswith(abs_trash_dir + os.sep) or abs_current_dir == abs_trash_dir:
                    return True
            
            # Also check for TMP_TRASHES_DIR
            if hasattr(main_window, 'TMP_TRASHES_DIR'):
                tmp_trash_dir = os.path.abspath(main_window.TMP_TRASHES_DIR)
                if abs_current_dir.startswith(tmp_trash_dir + os.sep) or abs_current_dir == tmp_trash_dir:
                    return True
            
            return False
        except Exception:
            return False
    
    @staticmethod
    def _get_trash_directories_for_path(original_path: str) -> List[str]:
        """
        Determine which trash directories to search for a file based on its original path.
        
        Returns list of trash directory paths to search:
        - Always includes user's home trash: ~/.Trash
        - If file was on a mounted volume, also includes that volume's trash: /Volumes/<volume>/.Trashes/<uid>/
        
        Args:
            original_path: The original path of the deleted file
            
        Returns:
            List of trash directory paths to search (in order of preference)
        """
        trash_dirs = []
        uid = os.getuid()
        
        # Always include user's home trash (don't use os.listdir — TCC may block it,
        # but direct file access by name still works)
        user_trash = os.path.expanduser("~/.Trash")
        try:
            if os.path.isdir(user_trash):
                trash_dirs.append(user_trash)
        except Exception:
            pass
        
        # Check if file was on a mounted volume
        try:
            resolved_path = os.path.realpath(original_path)
            if resolved_path.startswith("/Volumes/"):
                parts = resolved_path.split(os.sep)
                if len(parts) >= 3 and parts[1] == "Volumes":
                    volume_name = parts[2]
                    volume_path = os.path.join("/Volumes", volume_name)
                    user_trash_path = os.path.join(volume_path, ".Trashes", str(uid))
                    try:
                        if os.path.isdir(user_trash_path):
                            trash_dirs.append(user_trash_path)
                    except Exception:
                        pass
        except Exception:
            pass
        
        return trash_dirs

    def _determine_start_directory(self) -> str:
        """Determine the initial directory for file/directory dialogs.
        
        Uses the directory of the currently highlighted image (same as shown in status bar).
        If no directory is known or derivable, uses the user's home directory (~).
        """
        # Get the currently highlighted image path (same logic as status bar)
        current_image_path = self.main_window.get_current_image_path()
        if current_image_path:
            directory_path = os.path.dirname(current_image_path)
            if directory_path and os.path.exists(directory_path):
                return directory_path
        
        # Fallback: use home directory if no directory is known or derivable
        return os.path.expanduser('~')

    def open_directory_dialog(self) -> Optional[str]:
        """Open directory selection dialog and return selected directory path"""
        start_directory = self._determine_start_directory()
        directory = QFileDialog.getExistingDirectory(
            self.main_window, "Select Image Directory", start_directory)
        return directory or None

    def open_file_dialog(self) -> Optional[List[str]]:
        """Open file selection dialog and return selected image file paths"""
        start_directory = self._determine_start_directory()
        image_exts = get_image_extensions()
        image_filter = "Image Files (" + " ".join(f"*{ext}" for ext in sorted(image_exts)) + ")"
        dialog = QFileDialog(self.main_window, "Select Image File", start_directory)
        dialog.setFileMode(QFileDialog.ExistingFiles)
        dialog.setNameFilter(image_filter)
        dialog.setViewMode(QFileDialog.Detail)
        dialog.setOption(QFileDialog.DontUseNativeDialog, False)
        if dialog.exec():
            selected = dialog.selectedFiles()
            valid = [p for p in selected if os.path.isfile(p) and get_file_extension(p) in image_exts]
            return valid or None
        else:
            return None

    def delete_selected_files(self, force_confirmation: bool = False) -> None:
        """Delete all selected files with proper undo support"""
        mw = self.main_window
        mw.file_deletion_in_progress = True
        selected_files = mw.selection_manager.get_selected_files()
        if not selected_files:
            mw.file_deletion_in_progress = False
            return

        # Prevent deletion in slideshow modes
        if getattr(mw, 'current_view_mode', '') in ['slideshow', 'slideshow2', 'slideshow3']:
            mw.file_deletion_in_progress = False
            return

        # Prevent deletion when browsing trash directories
        if FileOperationsManager._is_browsing_trash(mw):
            show_styled_warning(mw, "Delete restricted", "Cannot delete files from Trash\nUse Finder to delete files from Trash")
            mw.file_deletion_in_progress = False
            return

        # Check if any selected file is in trash
        for file_path in selected_files:
            if FileOperationsManager._is_in_trash_directory(file_path, mw):
                show_styled_warning(mw, "Delete restricted", "Cannot delete files from Trash\nUse Finder to delete files from Trash")
                mw.file_deletion_in_progress = False
                return
        
        # Check for locked files - prevent deletion
        locked_files = []
        if hasattr(mw, 'lock_manager') and mw.lock_manager:
            for file_path in selected_files:
                if mw.lock_manager.is_file_locked(file_path):
                    locked_files.append(os.path.basename(file_path))
        
        if locked_files:
            show_styled_warning(
                mw,
                "Cannot Delete Locked Files",
                f"The following files are locked and cannot be deleted:\n\n" +
                "\n".join(locked_files[:10]) +  # Show first 10
                (f"\n... and {len(locked_files) - 10} more" if len(locked_files) > 10 else "") +
                "\n\nPlease unlock the files (Shift-Cmd-L) before deleting them."
            )
            mw.file_deletion_in_progress = False
            return

        # Capture the active file BEFORE deletion (this is the file that should determine next selection)
        active_file_path = mw.get_current_image_path()

        if len(selected_files) == 1:
            success = self._delete_single_file(selected_files[0], force_confirmation, active_file_path)
        else:
            success = self._delete_multiple_files(selected_files, force_confirmation, active_file_path)
        if success:
            mw.clear_selection()
            mw.highlight_image()
            mw.image_display_manager.update_window_title_for_active_image()
            mw.update_status_bar_sections()
            # Update menu state to activate cmd-Z key without showing menu
            if hasattr(mw, 'update_edit_menu_states'):
                mw.update_edit_menu_states()
            if hasattr(mw, 'event_bus') and mw.event_bus:
                from event_bus import FILE_OPERATION_COMPLETE
                mw.event_bus.emit(FILE_OPERATION_COMPLETE, ('delete', list(selected_files), True))
        mw.file_deletion_in_progress = False
        if getattr(mw, "current_view_mode", "") == 'browse':
            mw.view_manager.open_browse_view(mw.highlight_index)
    def _delete_single_file(self, file_path: str, force_confirmation: bool, active_file_path: str = None) -> bool:
        """Delete a single file with confirmation and undo support
        
        Args:
            file_path: Path of file to delete
            force_confirmation: Whether to force confirmation dialog
            active_file_path: Optional active file path (current_image_path) for next selection
        """
        mw = self.main_window
        
        # Prevent deletion of files in Photos Libraries
        if is_inside_photos_library(file_path):
            show_styled_warning(
                mw,
                "Operation Not Allowed",
                "Deleting files from macOS Photos Library is not allowed.\n\n"
                "Photos Library files cannot be deleted or modified."
            )
            return False
        
        # Prevent deletion of locked files
        if hasattr(mw, 'lock_manager') and mw.lock_manager:
            if mw.lock_manager.is_file_locked(file_path):
                show_styled_warning(
                    mw,
                    "Cannot Delete Locked File",
                    f"The file '{os.path.basename(file_path)}' is locked and cannot be deleted.\n\n"
                    "Please unlock the file (Shift-Cmd-L) before deleting it."
                )
                return False
        
        # Prevent deletion of files in trash directories
        if FileOperationsManager._is_in_trash_directory(file_path, mw):
            show_styled_warning(mw, "Delete restricted", "Cannot delete files from Trash\nUse Finder to delete files from Trash")
            return False
        
        if not os.path.exists(file_path):
            show_styled_warning(mw, "File not found", f"The file '{os.path.basename(file_path)}' does not exist.")
            return False
        if not os.access(file_path, os.W_OK):
            show_styled_warning(mw, "Permission denied", f"No permission to delete file '{os.path.basename(file_path)}'")
            return False
        if force_confirmation or getattr(mw, 'confirm_delete', True):
            reply = self._show_delete_multiple_files_confirmation_dialog([file_path])
            if reply != QMessageBox.StandardButton.Yes:
                return False
        try:
            _import_appkit_modules()
            if _NSWorkspace and _NSWorkspaceRecycleOperation:
                workspace = _NSWorkspace.sharedWorkspace()
                workspace.performFileOperation_source_destination_files_tag_(
                    _NSWorkspaceRecycleOperation,
                    os.path.dirname(file_path), "", [os.path.basename(file_path)], None
                )
                # Check if the file still exists after attempted deletion
                if os.path.exists(file_path):
                    show_styled_warning(mw, "Delete failed", f"Unable to delete file: {file_path}")
                    return False
            self._register_undo_for_deleted_files([file_path], 1)
            mw.remove_thumbnails_for_files([file_path], active_file_path)
            mw.status_notification.show_message(f"Moved '{os.path.basename(file_path)}' to Trash")
            return True
        except Exception as e:
            print(f"Error deleting file {file_path}: {e}")
            show_styled_warning(mw, "Delete failed", f"Error deleting file: {str(e)}")
            return False

    def _delete_multiple_files(self, selected_files: List[str], force_confirmation: bool, active_file_path: str = None) -> bool:
        """Delete multiple files with confirmation and undo support
        
        Args:
            selected_files: List of file paths to delete
            force_confirmation: Whether to force confirmation dialog
            active_file_path: Optional active file path (current_image_path) for next selection
        """
        mw = self.main_window
        
        # Check for Photos Library files before showing confirmation
        photos_library_files = [f for f in selected_files if is_inside_photos_library(f)]
        if photos_library_files:
            show_styled_warning(
                mw,
                "Operation Not Allowed",
                "Deleting files from macOS Photos Library is not allowed.\n\n"
                "Photos Library files cannot be deleted or modified."
            )
            # Remove Photos Library files from the list
            selected_files = [f for f in selected_files if not is_inside_photos_library(f)]
            if not selected_files:
                return False
        
        if force_confirmation or getattr(mw, 'confirm_delete', True):
            reply = self._show_delete_multiple_files_confirmation_dialog(selected_files)
            if reply != QMessageBox.StandardButton.Yes:
                return False
        
        # Show progress dialog for > 10 files
        progress_dialog = None
        if len(selected_files) > 10:
            progress_dialog = create_file_operation_progress_dialog(
                mw, "Deleting Files", len(selected_files)
            )
        
        deleted_count = 0
        files_to_remove = []
        for idx, file_path in enumerate(selected_files):
            # Update progress if dialog is shown
            if progress_dialog:
                progress_dialog.setValue(idx)
                progress_dialog.setLabelText(f"Deleting file {idx + 1} of {len(selected_files)}")
                QApplication.processEvents()
            try:
                # Skip files in Photos Libraries (double-check)
                if is_inside_photos_library(file_path):
                    continue
                # Skip files in trash directories
                if FileOperationsManager._is_in_trash_directory(file_path, mw):
                    continue
                
                if os.path.exists(file_path) and os.access(file_path, os.W_OK):
                    _import_appkit_modules()
                    if _NSWorkspace and _NSWorkspaceRecycleOperation:
                        workspace = _NSWorkspace.sharedWorkspace()
                        workspace.performFileOperation_source_destination_files_tag_(
                            _NSWorkspaceRecycleOperation,
                            os.path.dirname(file_path), "", [os.path.basename(file_path)], None
                        )
                    if not os.path.exists(file_path):
                        deleted_count += 1
                        mw.cache_manager.clear_cache_for_file(file_path)
                        displayed = mw.get_displayed_images()
                        if file_path in displayed:
                            files_to_remove.append(file_path)
            except Exception:
                continue
        
        # Close progress dialog if it was shown
        if progress_dialog:
            progress_dialog.setValue(len(selected_files))
            progress_dialog.close()
        
        if deleted_count > 0 and getattr(mw, 'file_undo_manager', None):
            self._register_undo_for_deleted_files(files_to_remove, deleted_count)
            if files_to_remove:
                mw.remove_thumbnails_for_files(files_to_remove, active_file_path)
                mw.clear_selection()
                mw.status_notification.show_message(f"Deleted {deleted_count} files")
            else:
                mw.status_notification.show_message("No files deleted.")
                return False
        else:
            if not getattr(mw, 'file_undo_manager', None):
                reason = " (undo manager unavailable)"
            else:
                reason = " (no files selected or no files deleted)"
            mw.status_notification.show_message(f"Delete operation cancelled{reason}.")
            return False
        return True

    def _show_delete_multiple_files_confirmation_dialog(self, selected_files: List[str]) -> QMessageBox.StandardButton:
        """Show confirmation dialog for deleting multiple files with styled buttons"""
        file_count = len(selected_files)
        if file_count == 1:
            message = f"Are you sure you want to delete this file?\n\n{os.path.basename(selected_files[0])}"
        else:
            message = f"Are you sure you want to delete these {file_count} files?"
        reply = show_styled_question(self.main_window, "Delete Files", message, default_no=True)
        return reply if reply is not None else QMessageBox.StandardButton.No

    def _register_undo_for_deleted_files(self, files_to_remove_from_images: List[str], deleted_count: int) -> None:
        """Register undo operation for deleted files"""
        mw = self.main_window
        deleted_files_batch = []
        displayed = mw.get_displayed_images()
        for file_path in files_to_remove_from_images:
            original_position = displayed.index(file_path) if file_path in displayed else None
            try:
                stat_info = os.stat(file_path)
                file_size = stat_info.st_size
                file_mtime = stat_info.st_mtime
            except OSError:
                file_size = file_mtime = None
            deleted_files_batch.append({
                'path': file_path,
                'filename': os.path.basename(file_path),
                'directory': os.path.dirname(file_path),
                'original_position': original_position,
                'file_size': file_size,
                'file_mtime': file_mtime
            })
        try:
            undo_mgr = getattr(mw, "file_undo_manager", None)
            if undo_mgr:
                undo_mgr.registerUndoWithTarget_selector_object_(
                    mw, mw.restore_multiple_files_from_trash_, deleted_files_batch
                )
                undo_mgr.setActionName_(f"Delete {deleted_count} Files")
        except ValueError:
            pass
        except Exception as e:
            print(f"Exception registering undo: {e}")
            traceback.print_exc()
        if hasattr(mw, 'deletion_operations'):
            mw.deletion_operations.append(deleted_files_batch)

    def _register_undo_for_moved_files(self, moved_files_info: List[dict], moved_count: int) -> None:
        """Register undo operation for moved files"""
        mw = self.main_window
        try:
            undo_mgr = getattr(mw, "file_undo_manager", None)
            if undo_mgr:
                undo_mgr.registerUndoWithTarget_selector_object_(
                    mw, mw.undo_move_operation_, moved_files_info
                )
                undo_mgr.setActionName_(f"Move {moved_count} File{'s' if moved_count != 1 else ''}")
        except ValueError:
            pass
        except Exception as e:
            print(f"Exception registering move undo: {e}")
            traceback.print_exc()
        if hasattr(mw, 'move_operations'):
            mw.move_operations.append(moved_files_info)

    def _validate_unix_filename(self, prefix: str) -> Tuple[bool, str]:
        """
        Validate that a prefix is valid for Unix filenames.
        Returns (is_valid, error_message)
        """
        if not prefix:
            return False, "Prefix cannot be empty"

        # Check for invalid characters in Unix filenames
        invalid_chars = ['/', '\x00']
        for char in invalid_chars:
            if char in prefix:
                return False, f"Prefix cannot contain '{char}'"

        # Check if prefix starts with a dot (hidden files - allow but warn)
        if prefix.startswith('.'):
            return False, "Prefix cannot start with a dot (hidden files)"

        # Check length (max filename length is typically 255, but we need room for -nnnnn.ext)
        if len(prefix) > 240:
            return False, "Prefix is too long (max 240 characters)"

        return True, ""

    def _find_available_temp_prefix(self, target_directory: str) -> str:
        """
        Find an available temp prefix that doesn't conflict with existing files.
        Tries patterns like tempxyz-*, tempzzz-*, etc.
        Returns the prefix (without the dash).
        """
        # Generate random suffix for temp prefix
        chars = string.ascii_lowercase
        max_attempts = 100

        for attempt in range(max_attempts):
            # Generate a random 4-character suffix
            suffix = ''.join(random.choice(chars) for _ in range(4))
            temp_prefix = f"temp{suffix}"

            # Check if any files exist with this prefix pattern
            try:
                files_in_dir = os.listdir(target_directory)
                conflict_found = False

                for filename in files_in_dir:
                    # Check if filename starts with temp_prefix followed by dash or is exactly temp_prefix
                    if filename.startswith(temp_prefix + '-') or filename == temp_prefix:
                        conflict_found = True
                        break

                if not conflict_found:
                    return temp_prefix
            except Exception:
                # If we can't list directory, try next prefix
                continue

        # Fallback: use timestamp-based prefix if all random attempts fail
        return f"temp{int(time.time() * 1000000)}"

    def _highlight_first_non_locked_after_rename(self, mw, target_directory: str, rename_map: dict = None, preferred_path: str = None) -> None:
        """Highlight the active image after rename (if it was renamed and is not locked),
        otherwise highlight the 1st non-locked item. If there are no locked files and the active
        image was renamed, preserve it as the active image.
        
        Args:
            mw: Main window
            target_directory: Directory path
            rename_map: Optional dict mapping old_path -> new_path. If provided, uses new paths.
            preferred_path: Optional preferred path to highlight (e.g., renamed active image).
        """
        try:
            # Get locked files first
            locked_files = set()
            if hasattr(mw, 'lock_manager') and mw.lock_manager:
                locked_files = mw.lock_manager.get_locked_files(target_directory)
            
            # Get displayed images
            displayed_images = mw.get_displayed_images()
            
            # CRITICAL: Only convert paths if rename_map is provided AND displayed_images has old paths
            # If displayed_images already has new paths (e.g., after deferred_refresh updated them),
            # we should NOT convert them again
            if rename_map and displayed_images:
                # Check if displayed_images has old paths (by checking if any path is in rename_map keys)
                has_old_paths = any(path in rename_map for path in displayed_images)
                if has_old_paths:
                    # Convert displayed_images to new paths
                    new_displayed_images = []
                    for old_path in displayed_images:
                        new_path = rename_map.get(old_path, old_path)
                        if os.path.exists(new_path):
                            new_displayed_images.append(new_path)
                        else:
                            new_displayed_images.append(old_path)  # Fallback to old path if new doesn't exist
                    displayed_images = new_displayed_images
            
            if not displayed_images:
                return
            
            # CRITICAL: Check if preferred_path or current_image_path exists in displayed_images and is not locked
            # This preserves the active image after rename
            target_path = None
            # First check preferred_path (renamed active image)
            if preferred_path and preferred_path in displayed_images:
                filename = os.path.basename(preferred_path)
                # If preferred image is not locked, use it
                if filename not in locked_files:
                    target_path = preferred_path
            # Fallback to current_image_path if preferred_path not available
            if not target_path:
                current_path = getattr(mw, 'current_image_path', None)
                if current_path and current_path in displayed_images:
                    filename = os.path.basename(current_path)
                    # If current image is not locked, use it
                    if filename not in locked_files:
                        target_path = current_path
            
            # If current image is locked or not found, find first non-locked file
            if not target_path:
                for image_path in displayed_images:
                    filename = os.path.basename(image_path)
                    if filename not in locked_files:
                        target_path = image_path
                        break
            
            # If all locked, use first item
            if not target_path and displayed_images:
                target_path = displayed_images[0]
            
            # Set it directly
            if target_path:
                # Set the new one (don't clear first - current_image_path may already be correct)
                if hasattr(mw, 'set_current_image_by_path'):
                    mw.set_current_image_by_path(target_path, fallback_index=0)
                else:
                    mw.current_image_path = target_path
                if hasattr(mw, '_sync_highlight_index_from_current_image_path'):
                    mw._sync_highlight_index_from_current_image_path()
                if hasattr(mw, 'highlight_image'):
                    mw.highlight_image()
                
                # Force update
                if hasattr(mw, '_emit_selection_changed'):
                    mw._emit_selection_changed()
                if hasattr(mw, 'canvas') and mw.canvas:
                    if hasattr(mw.canvas, 'update'):
                        mw.canvas.update()
        except Exception:
            pass
    

    def _build_efficient_rename_plan(self, target_mappings: List[Tuple[str, str]],
                                      target_directory: str, temp_prefix: str, progress_callback=None) -> Optional[Dict]:
        """
        Build an efficient rename plan that PRESERVES ORDER from target_mappings.
        Uses a three-phase approach:
        - Phase 0: Move existing files that conflict with target names to temporary names
        - Phase 1: Rename all sources to temporary names (preserving order)
        - Phase 2: Rename all temps to final names (preserving order)

        This is fast, simple, and guarantees order preservation while handling conflicts.

        Returns a dict with 'phase0', 'phase1', and 'phase2' lists of (source, target) tuples.
        """
        phase0_renames = []  # (existing_conflicting_path, temp_path) - move conflicting existing files
        phase1_renames = []  # (source_path, temp_path) - first phase renames
        phase2_renames = []  # (temp_path, final_path) - second phase renames

        # Track which temp names we've used
        next_temp_id = 0

        # Build set of existing files (case-insensitive) and their actual paths
        existing_files_map = {}  # filename_upper -> actual filepath
        source_paths = set()  # Set of source paths being renamed
        try:
            if progress_callback:
                progress_callback(0, len(target_mappings), "Scanning directory...")
            filenames = os.listdir(target_directory)
            for filename in filenames:
                filepath = os.path.join(target_directory, filename)
                if os.path.isfile(filepath):
                    existing_files_map[filename.upper()] = filepath
            if progress_callback:
                progress_callback(len(target_mappings), len(target_mappings), "Scanning directory...")
        except Exception:
            pass

        # Build set of source paths being renamed
        for source_path, _ in target_mappings:
            source_paths.add(os.path.normpath(os.path.realpath(source_path)))

        # Build set of target filenames (case-insensitive) that we'll be using
        target_filenames = set()
        for _, target_path in target_mappings:
            target_filename = os.path.basename(target_path).upper()
            target_filenames.add(target_filename)

        # Phase 0: Handle conflicts with existing files that aren't being renamed
        # Find existing files that conflict with target names
        conflicting_files = []
        for target_filename_upper, target_path in [(os.path.basename(t).upper(), t) for _, t in target_mappings]:
            if target_filename_upper in existing_files_map:
                existing_file_path = existing_files_map[target_filename_upper]
                existing_file_normalized = os.path.normpath(os.path.realpath(existing_file_path))
                # Only move it if it's not one of the source files being renamed
                if existing_file_normalized not in source_paths:
                    conflicting_files.append(existing_file_path)

        # Remove duplicates while preserving order
        seen_conflicts = set()
        for conflicting_file in conflicting_files:
            normalized = os.path.normpath(os.path.realpath(conflicting_file))
            if normalized not in seen_conflicts:
                seen_conflicts.add(normalized)
                ext = get_file_extension(conflicting_file)
                temp_filename = f"{temp_prefix}-{next_temp_id:05d}{ext}"
                temp_path = os.path.join(target_directory, temp_filename)
                next_temp_id += 1
                phase0_renames.append((conflicting_file, temp_path))

        # Process each mapping IN ORDER
        total_mappings = len(target_mappings)
        for idx, (source_path, target_path) in enumerate(target_mappings):
            if progress_callback and idx % 50 == 0:
                progress_callback(idx, total_mappings, f"Building rename plan... ({idx}/{total_mappings})")

            # Skip if already correct
            if source_path == target_path:
                continue

            source_filename = os.path.basename(source_path).upper()
            target_filename = os.path.basename(target_path).upper()

            # Skip if filename already matches (case-insensitive)
            if source_filename == target_filename:
                continue

            # Generate temp name for this source
            ext = get_file_extension(source_path)
            temp_filename = f"{temp_prefix}-{next_temp_id:05d}{ext}"
            temp_path = os.path.join(target_directory, temp_filename)
            next_temp_id += 1

            # Phase 1: source -> temp
            phase1_renames.append((source_path, temp_path))

            # Phase 2: temp -> final target
            phase2_renames.append((temp_path, target_path))

        if progress_callback and total_mappings > 0:
            progress_callback(total_mappings, total_mappings, f"Building rename plan... ({total_mappings}/{total_mappings})")

        return {'phase0': phase0_renames, 'phase1': phase1_renames, 'phase2': phase2_renames}

    def _get_lowest_sequence_in_directory(
        self, prefix: str, target_directory: str, increment_length: int
    ) -> Optional[int]:
        """Return the lowest sequence number found in files matching the rename pattern in directory.
        Returns None if no matching files exist. Used for subset+order rename to set effective start."""
        _dash_pat = re.compile(rf'^{re.escape(prefix)}-(\d+)$', re.IGNORECASE)
        _nodash_pat = re.compile(rf'^{re.escape(prefix)}(\d+)$', re.IGNORECASE)

        def extract_number(fn: str) -> Optional[int]:
            name, _ = os.path.splitext(fn)
            m = _dash_pat.match(name)
            if m and len(m.group(1)) == increment_length:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
            m = _nodash_pat.match(name)
            if m and len(m.group(1)) == increment_length:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
            return None

        lowest = None
        try:
            for filename in os.listdir(target_directory):
                filepath = os.path.join(target_directory, filename)
                if not os.path.isfile(filepath):
                    continue
                num = extract_number(filename)
                if num is not None:
                    if lowest is None or num < lowest:
                        lowest = num
        except Exception:
            pass
        return lowest

    def _calculate_target_names(
        self,
        images_to_rename: List[str],
        prefix: str,
        target_directory: str,
        increment_length: int,
        starting_number: int,
        progress_callback=None,
        effective_start_override: Optional[int] = None,
        prefer_source_number: bool = False
    ) -> List[Tuple[str, str]]:
        """
        Optimized calculation of new filenames for a sequential rename operation.
        See original docstring for details.
        """
        # 1. List and index all files in target dir (case insensitive)
        existing_files_map = {}  # UPPER(filename) -> path
        try:
            if progress_callback:
                progress_callback(0, 100, "Scanning directory...")
            filenames = os.listdir(target_directory)
            total_files = len(filenames)
            for idx, filename in enumerate(filenames):
                if progress_callback and idx % 100 == 0:
                    progress_callback(idx, total_files, f"Scanning directory... ({idx}/{total_files})")
                filepath = os.path.join(target_directory, filename)
                if os.path.isfile(filepath):
                    existing_files_map[filename.upper()] = filepath
            if progress_callback and total_files > 0:
                progress_callback(total_files, total_files, f"Scanning directory... ({total_files}/{total_files})")
        except Exception:
            existing_files_map = {}

        # 2. Build sets for source files (case insens/faster checks)
        source_paths_normalized = set(
            os.path.normpath(os.path.realpath(p)) for p in images_to_rename
        )

        # Helper: parse number, returns int or None
        _dash_pat = re.compile(rf'^{re.escape(prefix)}-(\d+)$', re.IGNORECASE)
        _nodash_pat = re.compile(rf'^{re.escape(prefix)}(\d+)$', re.IGNORECASE)
        def extract_number(fn: str) -> Optional[int]:
            name, _ = os.path.splitext(fn)
            m = _dash_pat.match(name)
            if m and len(m.group(1)) == increment_length:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
            m = _nodash_pat.match(name)
            if m and len(m.group(1)) == increment_length:
                try:
                    return int(m.group(1))
                except Exception:
                    return None
            return None

        # 3. Find "used" (occupied) and "vacated" numbers
        occupied_numbers = set()
        vacated_numbers = set()
        normalized_to_is_source = {}
        for p in images_to_rename:
            normalized_to_is_source[os.path.normpath(os.path.realpath(p))] = True
        for filename_upper, filepath in existing_files_map.items():
            number = extract_number(filename_upper)
            if number is None:
                continue
            filepath_normalized = os.path.normpath(os.path.realpath(filepath))
            if filepath_normalized in source_paths_normalized:
                vacated_numbers.add(number)
            else:
                occupied_numbers.add(number)

        MAX_SEQ = 10 ** increment_length - 1
        total_images = len(images_to_rename)
        assigned_targets = set()  # UPPER(target filename)
        assigned_numbers = set()
        target_mappings = []
        effective_start = effective_start_override if effective_start_override is not None else starting_number

        # 4. For each file, find lowest available sequence number
        for idx, old_path in enumerate(images_to_rename):
            if progress_callback and idx % 10 == 0:
                progress_callback(idx, total_images, f"Calculating names... ({idx}/{total_images})")
            ext = get_file_extension(old_path)
            next_seq = None

            # Subset+order: prefer source file's number when available (percolate to top, stay together)
            if prefer_source_number:
                src_num = extract_number(os.path.basename(old_path))
                if src_num is not None and src_num >= effective_start:
                    if src_num not in assigned_numbers and src_num not in occupied_numbers:
                        new_basename = f"{prefix}-{'{:0{w}d}'.format(src_num, w=increment_length)}{ext}"
                        new_basename_upper = new_basename.upper()
                        if new_basename_upper not in assigned_targets:
                            if new_basename_upper in existing_files_map:
                                existing_norm = os.path.normpath(
                                    os.path.realpath(existing_files_map[new_basename_upper]))
                                if existing_norm in source_paths_normalized:
                                    next_seq = src_num
                            else:
                                next_seq = src_num
                        if next_seq is not None:
                            cand_pat_dash = f"{prefix}-{'{:0{w}d}'.format(src_num,w=increment_length)}".upper()
                            cand_pat_nodash = f"{prefix}{'{:0{w}d}'.format(src_num,w=increment_length)}".upper()
                            for existing_fn_upper in existing_files_map.keys():
                                name_wo_ext, _ = os.path.splitext(existing_fn_upper)
                                if name_wo_ext == cand_pat_dash or name_wo_ext == cand_pat_nodash:
                                    norm_path = os.path.normpath(os.path.realpath(existing_files_map[existing_fn_upper]))
                                    if norm_path not in source_paths_normalized:
                                        next_seq = None
                                        break

            # Micro-optimize: Don't check all files for each candidate, check using pre-built sets.
            if next_seq is None:
                candidate = effective_start
                # Occupied numbers may grow, use set for O(1) checks.
                while candidate <= MAX_SEQ:
                    if candidate in assigned_numbers:
                        candidate += 1
                        continue
                    if candidate in occupied_numbers:
                        candidate += 1
                        continue

                    new_basename = f"{prefix}-{'{:0{w}d}'.format(candidate, w=increment_length)}{ext}"
                    new_basename_upper = new_basename.upper()

                    # Already assigned in this batch?
                    if new_basename_upper in assigned_targets:
                        candidate += 1
                        continue

                    # Lookup for this exact name in dir (regardless of ext)
                    if new_basename_upper in existing_files_map:
                        existing_norm = os.path.normpath(
                            os.path.realpath(existing_files_map[new_basename_upper])
                        )
                        if existing_norm not in source_paths_normalized:
                            occupied_numbers.add(candidate)
                            candidate += 1
                            continue

                    # Safety: Check all files in dir for any sequence number match (slow only if many files)
                    # This is pattern match, not full filename/ext.
                    cand_pat_dash = f"{prefix}-{'{:0{w}d}'.format(candidate,w=increment_length)}".upper()
                    cand_pat_nodash = f"{prefix}{'{:0{w}d}'.format(candidate,w=increment_length)}".upper()
                    did_conflict = False
                    for existing_fn_upper in existing_files_map.keys():
                        name_wo_ext, _ = os.path.splitext(existing_fn_upper)
                        if name_wo_ext == cand_pat_dash or name_wo_ext == cand_pat_nodash:
                            norm_path = os.path.normpath(os.path.realpath(existing_files_map[existing_fn_upper]))
                            if norm_path not in source_paths_normalized:
                                occupied_numbers.add(candidate)
                                did_conflict = True
                                break
                    if did_conflict:
                        candidate += 1
                        continue

                    next_seq = candidate
                    break

            if next_seq is None:
                raise ValueError(
                    f"Cannot rename files: no available sequence numbers starting from {starting_number}.\n\n"
                    f"All numbers from {starting_number} to {MAX_SEQ} are occupied or already assigned.\n"
                    f"Please use a different prefix, increase the number of digits, or reduce the number of files."
                )

            new_filename = f"{prefix}-{'{:0{w}d}'.format(next_seq, w=increment_length)}{ext}"
            new_filename_upper = new_filename.upper()
            new_path = os.path.join(target_directory, new_filename)
            target_mappings.append((old_path, new_path))
            assigned_targets.add(new_filename_upper)
            assigned_numbers.add(next_seq)

        if progress_callback and total_images > 0:
            progress_callback(total_images, total_images, f"Calculating names... ({total_images}/{total_images})")

        return target_mappings

    def _minimize_date_changes(
        self, file_paths_with_indices: List[Tuple[str, int]], 
        date_change_mode: str, now: int, total_files: int
    ) -> List[Tuple[str, int]]:
        """
        Minimize the number of date changes while ensuring sort order.
        
        Args:
            file_paths_with_indices: List of (file_path, sequence_index) tuples
            date_change_mode: 'oldest' (oldest-to-newest) or 'newest' (newest-to-oldest)
            now: Current timestamp
            total_files: Total number of files
            
        Returns:
            List of (file_path, new_mtime) tuples for files that need date changes
        """
        if not file_paths_with_indices:
            return []
        
        # Sort by sequence index to get target order
        sorted_files = sorted(file_paths_with_indices, key=lambda x: x[1])
        
        # Get current mtimes for all files
        file_data = []
        for file_path, seq_idx in sorted_files:
            if os.path.exists(file_path):
                try:
                    current_mtime = int(os.path.getmtime(file_path))
                    file_data.append((file_path, seq_idx, current_mtime))
                except Exception:
                    # If we can't read mtime, we'll need to set it
                    file_data.append((file_path, seq_idx, None))
            else:
                file_data.append((file_path, seq_idx, None))
        
        if not file_data:
            return []
        
        # Calculate target dates based on sort order
        target_dates = []
        for idx, (file_path, seq_idx, current_mtime) in enumerate(file_data):
            if date_change_mode == 'oldest':
                # First file (idx=0) gets oldest timestamp: now - (total_files - 1)
                # Last file gets newest timestamp: now
                target_date = now - (total_files - 1 - idx)
            else:  # date_change_mode == 'newest'
                # First file (idx=0) gets newest timestamp: now
                # Last file gets oldest timestamp: now - (total_files - 1)
                target_date = now - idx
            target_dates.append((file_path, seq_idx, current_mtime, target_date))
        
        # Check if current dates already satisfy the sort order
        # For oldest-to-newest: dates should be non-decreasing and <= target_date
        # For newest-to-oldest: dates should be non-increasing and >= target_date
        changes_needed = []
        
        if date_change_mode == 'oldest':
            # Check if dates are already in non-decreasing order
            prev_date = None
            for idx, (file_path, seq_idx, current_mtime, target_date) in enumerate(target_dates):
                if current_mtime is None:
                    # Must set date if we can't read it
                    changes_needed.append((file_path, target_date))
                    prev_date = target_date
                elif current_mtime > now:
                    # Future dates must be clamped to now or earlier
                    changes_needed.append((file_path, target_date))
                    prev_date = target_date
                else:
                    # Check if we can keep this date
                    # Must satisfy: >= prev_date (if exists) and <= target_date
                    if prev_date is not None:
                        if current_mtime < prev_date or current_mtime > target_date:
                            # Violates order or exceeds target - must change
                            changes_needed.append((file_path, target_date))
                            prev_date = target_date
                        else:
                            # Can keep this date
                            prev_date = current_mtime
                    else:
                        # First file - can keep if <= target_date
                        if current_mtime <= target_date:
                            prev_date = current_mtime
                        else:
                            changes_needed.append((file_path, target_date))
                            prev_date = target_date
        else:  # date_change_mode == 'newest'
            # Check if dates are already in non-increasing order
            prev_date = None
            for idx, (file_path, seq_idx, current_mtime, target_date) in enumerate(target_dates):
                if current_mtime is None:
                    # Must set date if we can't read it
                    changes_needed.append((file_path, target_date))
                    prev_date = target_date
                elif current_mtime > now:
                    # Future dates must be clamped to now or earlier
                    changes_needed.append((file_path, target_date))
                    prev_date = target_date
                else:
                    # Check if we can keep this date
                    # Must satisfy: <= prev_date (if exists) and >= target_date
                    if prev_date is not None:
                        if current_mtime > prev_date or current_mtime < target_date:
                            # Violates order or below target - must change
                            changes_needed.append((file_path, target_date))
                            prev_date = target_date
                        else:
                            # Can keep this date
                            prev_date = current_mtime
                    else:
                        # First file - can keep if >= target_date
                        if current_mtime >= target_date:
                            prev_date = current_mtime
                        else:
                            changes_needed.append((file_path, target_date))
                            prev_date = target_date
        
        return changes_needed

    def _show_rename_prefix_dialog(
        self, saved_prefix: str, saved_increment_length: int,
        saved_starting_number: int, saved_sort_mode: str = 'date', saved_date_change_mode: str = 'none',
        saved_order_direction: str = 'top'
    ):
        """Show a custom dialog for rename prefix, sequence, and sort mode selection."""
        from thumbnails.thumbnail_constants import (
            BUTTON_BG_DEFAULT_HEX, BUTTON_TEXT_DEFAULT_HEX, BUTTON_BORDER_DEFAULT_HEX,
            BUTTON_BG_HOVER_HEX, BUTTON_TEXT_HOVER_HEX, BUTTON_BORDER_HOVER_HEX,
            BUTTON_BG_PRESSED_HEX, CURRENT_IMAGE_BORDER_COLOR_HEX, TEXT_DISABLED_HEX,
            ERROR_COLOR_HEX, DEFAULT_BORDER_COLOR_HEX, DIALOG_BACKGROUND_HEX,
            DIALOG_TEXT_COLOR_HEX,
        )

        mw = self.main_window
        dialog = QDialog(mw)
        dialog.setWindowTitle("Rename with Custom Prefix")
        dialog.setModal(True)
        dialog.resize(520, 225)

        # Layout
        layout = QVBoxLayout(dialog)
        form_layout = QFormLayout()

        # Prefix field with reset button and note
        prefix_input = QLineEdit(dialog)
        prefix_input.setText(saved_prefix)
        
        # Reset button for prefix input
        prefix_reset_button = QPushButton("X", dialog)
        prefix_reset_button.setToolTip("Reset to 'image-%d'")
        prefix_reset_button.setStyleSheet("""
            QPushButton {
                background-color: """ + BUTTON_BG_DEFAULT_HEX + """;
                color: """ + ERROR_COLOR_HEX + """;
                border: 1px solid """ + BUTTON_BORDER_DEFAULT_HEX + """;
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 16px;
                min-width: 14px;
                max-width: 14px;
            }
            QPushButton:focus {
                border: 1px solid """ + CURRENT_IMAGE_BORDER_COLOR_HEX + """;
                color: """ + ERROR_COLOR_HEX + """;
                outline: none;
            }
            QPushButton:hover {
                background-color: """ + BUTTON_BG_HOVER_HEX + """;
                border: 1px solid """ + BUTTON_BORDER_HOVER_HEX + """;
                color: """ + BUTTON_TEXT_HOVER_HEX + """;
            }
            QPushButton:pressed {
                background-color: """ + BUTTON_BG_PRESSED_HEX + """;
            }
        """)
        prefix_reset_button.clicked.connect(lambda: prefix_input.setText("image-%d"))
        
        # Horizontal layout for prefix input and reset button
        prefix_input_layout = QHBoxLayout()
        prefix_input_layout.setContentsMargins(0, 0, 0, 0)
        prefix_input_layout.addWidget(prefix_input)
        prefix_input_layout.addWidget(prefix_reset_button)
        prefix_input_layout.setSpacing(4)
        prefix_input_widget = QWidget()
        prefix_input_widget.setLayout(prefix_input_layout)
        
        prefix_note = QLabel("Add %d for directory name. Example: 'image-%d'")
        prefix_note.setAlignment(Qt.AlignRight)
        prefix_note.setStyleSheet(
            f"color: {TEXT_DISABLED_HEX}; font-size: 11px; background-color: {DIALOG_BACKGROUND_HEX}; padding: 4px;"
        )
        prefix_vbox = QVBoxLayout()
        prefix_vbox.setContentsMargins(0, 0, 0, 0)
        prefix_vbox.setSpacing(4)
        prefix_vbox.addWidget(prefix_input_widget)
        prefix_vbox.addWidget(prefix_note)
        prefix_widget = QWidget()
        prefix_widget.setLayout(prefix_vbox)
        form_layout.addRow("Prefix:", prefix_widget)

        # Increment length (3-6 digits)
        increment_length_spin = QSpinBox(dialog)
        increment_length_spin.setMinimum(3)
        increment_length_spin.setMaximum(6)
        increment_length_spin.setValue(saved_increment_length)
        increment_length_spin.setFixedWidth(80)
        increment_length_spin.setAlignment(Qt.AlignRight)
        form_layout.addRow("Sequence digits (3-6):", increment_length_spin)

        # Starting number field
        starting_number_spin = QSpinBox(dialog)
        starting_number_spin.setMinimum(1)
        max_starting = 10 ** saved_increment_length - 1
        starting_number_spin.setMaximum(max_starting)
        actual_starting = max(0, min(saved_starting_number, max_starting))
        starting_number_spin.setValue(actual_starting)
        starting_number_spin.setMinimum(0)
        starting_number_spin.setMaximum(max_starting)
        starting_number_spin.setFixedWidth(80)
        starting_number_spin.setAlignment(Qt.AlignRight)
        form_layout.addRow("Starting number:", starting_number_spin)

        # Update starting_number max when increment_length changes
        def update_starting_max():
            new_max = 10 ** increment_length_spin.value() - 1
            current_value = starting_number_spin.value()
            starting_number_spin.setMaximum(new_max)
            if current_value > new_max:
                starting_number_spin.setValue(new_max)
        increment_length_spin.valueChanged.connect(update_starting_max)

        # ---- Renaming order radio buttons and reset dates checkbox in separate boxes side-by-side ----

        # -- Flat: Radio Buttons (no group box, just labeled) --
        # --- Renaming Order --- (standalone UI block, NOT in the form)
        label_sortby = QLabel("Renaming order:")
        radio_date = QRadioButton("Sort by Date\n(oldest becomes 1)")
        radio_order = QRadioButton("Sort by Current Order")

        # Try to make widgets as transparent as possible
        # transparent_style = "background-color: transparent;"
        group_box_style = """
            QGroupBox {
                background-color: """ + DIALOG_BACKGROUND_HEX + """;
                border: 1.5px solid """ + DEFAULT_BORDER_COLOR_HEX + """;
                border-radius: 6px;
                color: """ + DIALOG_TEXT_COLOR_HEX + """;
            }
        """

        # for widget in (label_sortby, radio_date, radio_order):
        #     widget.setStyleSheet(transparent_style)

        radio_vbox = QVBoxLayout()
        radio_vbox.setSpacing(12)
        radio_vbox.setContentsMargins(10, 2, 10, 10)  # Remove extra space above first label
        radio_vbox.addWidget(label_sortby)
        radio_vbox.addWidget(radio_date)
        radio_vbox.addWidget(radio_order)
        radio_vbox.addStretch(1)

        radio_order_widget = QGroupBox()
        radio_order_widget.setLayout(radio_vbox)
        radio_order_widget.setContentsMargins(0, 8, 0, 8)
        radio_order_widget.setStyleSheet(group_box_style)

        label_reset_dates = QLabel("Date changing:")
        radio_no_change = QRadioButton("No change")
        radio_oldest = QRadioButton("Top becomes oldest")
        radio_newest = QRadioButton("Top becomes newest")

        # Set saved value (default to 'none' if invalid)
        if saved_date_change_mode == 'oldest':
            radio_oldest.setChecked(True)
        elif saved_date_change_mode == 'newest':
            radio_newest.setChecked(True)
        else:
            radio_no_change.setChecked(True)

        # label_reset_dates.setStyleSheet(transparent_style)
        # radio_no_change.setStyleSheet(transparent_style)
        # radio_oldest.setStyleSheet(transparent_style)
        # radio_newest.setStyleSheet(transparent_style)

        reset_vbox = QVBoxLayout()
        reset_vbox.setSpacing(13)
        reset_vbox.setContentsMargins(10, 2, 10, 10)  # Remove extra space above first label
        reset_vbox.addWidget(label_reset_dates)
        reset_vbox.addWidget(radio_no_change)
        reset_vbox.addWidget(radio_oldest)
        reset_vbox.addWidget(radio_newest)
        reset_vbox.addStretch(1)

        reset_dates_widget = QGroupBox()
        reset_dates_widget.setLayout(reset_vbox)
        reset_dates_widget.setContentsMargins(0, 8, 0, 8)
        reset_dates_widget.setStyleSheet(group_box_style)

        # --- Order Direction (only enabled when sorting by current order) ---
        label_order_direction = QLabel("Sequence direction:")
        radio_top_becomes_1 = QRadioButton("Top becomes 1")
        radio_bottom_becomes_1 = QRadioButton("Bottom becomes 1")

        # Set saved value (default to 'top' if invalid)
        if saved_order_direction == 'bottom':
            radio_bottom_becomes_1.setChecked(True)
        else:
            radio_top_becomes_1.setChecked(True)

        order_direction_vbox = QVBoxLayout()
        order_direction_vbox.setSpacing(13)
        order_direction_vbox.setContentsMargins(10, 2, 10, 10)
        order_direction_vbox.addWidget(label_order_direction)
        order_direction_vbox.addWidget(radio_top_becomes_1)
        order_direction_vbox.addWidget(radio_bottom_becomes_1)
        order_direction_vbox.addStretch(1)

        order_direction_widget = QGroupBox()
        order_direction_widget.setLayout(order_direction_vbox)
        order_direction_widget.setContentsMargins(0, 8, 0, 8)
        order_direction_widget.setStyleSheet(group_box_style)

        horz_box = QHBoxLayout()
        horz_box.setSpacing(18)
        horz_box.addWidget(radio_order_widget)
        horz_box.addWidget(reset_dates_widget)
        horz_box.addWidget(order_direction_widget)
        horz_box.addStretch(1)

        # Add the layouts as *separate*, not inside the form layout:
        layout.addLayout(form_layout)
        layout.addLayout(horz_box)

        # Determine saved value
        if saved_sort_mode == "order":
            radio_order.setChecked(True)
        else:
            radio_date.setChecked(True)

        # Connect radio buttons to disable/enable date changing controls and order direction
        def update_controls_enabled():
            # When "Sort by Date" is checked, disable the date changing group box and order direction
            # When "Sort by Current Order" is checked, enable date changing and order direction
            is_date_mode = radio_date.isChecked()
            reset_dates_widget.setEnabled(not is_date_mode)
            radio_no_change.setEnabled(not is_date_mode)
            radio_oldest.setEnabled(not is_date_mode)
            radio_newest.setEnabled(not is_date_mode)
            label_reset_dates.setEnabled(not is_date_mode)
            order_direction_widget.setEnabled(not is_date_mode)
            radio_top_becomes_1.setEnabled(not is_date_mode)
            radio_bottom_becomes_1.setEnabled(not is_date_mode)
            label_order_direction.setEnabled(not is_date_mode)

        radio_date.toggled.connect(lambda checked: update_controls_enabled())
        radio_order.toggled.connect(lambda checked: update_controls_enabled())
        # Set initial state
        update_controls_enabled()

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Cancel and OK buttons
        cancel_button = QPushButton("Cancel", dialog)
        ok_button = QPushButton("OK", dialog)
        cancel_button.setDefault(True)
        cancel_button.setFocus()
        
        def validate_and_accept():
            prefix_text = prefix_input.text().strip()
            if not prefix_text:
                show_styled_warning(mw, "Invalid Prefix", "Prefix cannot be blank. Please enter a prefix.")
                return
            dialog.accept()
        
        ok_button.clicked.connect(validate_and_accept)
        cancel_button.clicked.connect(dialog.reject)
        
        # Defaults button (at lower right)
        defaults_button = QPushButton("Defaults", dialog)
        defaults_button.setMaximumWidth(80)

        def reset_to_defaults():
            prefix_input.setText("image-%d")
            radio_date.setChecked(True)
            radio_oldest.setChecked(True)  # top becomes oldest
            radio_top_becomes_1.setChecked(True)  # top becomes 1
        
        defaults_button.clicked.connect(reset_to_defaults)
        
        button_layout.addWidget(defaults_button)
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)
        
        layout.addLayout(button_layout)

        # Dialog styling using centralized button style
        button_style = get_button_style()

        dialog_style = """
        QLabel:disabled {
            color: """ + TEXT_DISABLED_HEX + """;
        }
        QLineEdit {
            background-color: """ + BUTTON_BG_DEFAULT_HEX + """;
            color: """ + BUTTON_TEXT_DEFAULT_HEX + """;
            border: 1px solid """ + BUTTON_BORDER_DEFAULT_HEX + """;
            border-radius: 4px;
            padding: 5px;
        }
        QLineEdit:focus {
            border-color: """ + CURRENT_IMAGE_BORDER_COLOR_HEX + """;
        }
        QRadioButton:disabled {
            color: """ + TEXT_DISABLED_HEX + """;
        }
        QGroupBox:disabled {
            border-color: """ + TEXT_DISABLED_HEX + """;
        }
        """
        combined_style = get_dialog_shell_stylesheet() + button_style + "\n" + dialog_style
        dialog.setStyleSheet(combined_style)

        # Set tab order: top to bottom
        # Skip the reset button (it's not focusable for tab navigation)
        prefix_reset_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        QWidget.setTabOrder(prefix_input, increment_length_spin)
        QWidget.setTabOrder(increment_length_spin, starting_number_spin)
        QWidget.setTabOrder(starting_number_spin, radio_date)
        QWidget.setTabOrder(radio_date, radio_order)
        QWidget.setTabOrder(radio_order, radio_no_change)
        QWidget.setTabOrder(radio_no_change, radio_oldest)
        QWidget.setTabOrder(radio_oldest, radio_newest)
        QWidget.setTabOrder(radio_newest, radio_top_becomes_1)
        QWidget.setTabOrder(radio_top_becomes_1, radio_bottom_becomes_1)
        QWidget.setTabOrder(radio_bottom_becomes_1, defaults_button)
        QWidget.setTabOrder(defaults_button, cancel_button)
        QWidget.setTabOrder(cancel_button, ok_button)

        if dialog.exec() == QDialog.Accepted:
            sort_mode = "order" if radio_order.isChecked() else "date"
            # Determine date change mode
            # If sort_mode is "date", ignore date change mode (set to "none")
            if sort_mode == "date":
                date_change_mode = "none"
            elif radio_oldest.isChecked():
                date_change_mode = "oldest"
            elif radio_newest.isChecked():
                date_change_mode = "newest"
            else:
                date_change_mode = "none"
            # Determine order direction (only relevant when sort_mode is "order")
            if sort_mode == "order":
                order_direction = "bottom" if radio_bottom_becomes_1.isChecked() else "top"
            else:
                order_direction = "top"  # Default, not used when sorting by date
            return (
                prefix_input.text().strip(),
                increment_length_spin.value(),
                starting_number_spin.value(),
                sort_mode,
                date_change_mode,
                order_direction,
                True
            )
        else:
            return ("", 0, 0, "date", "none", "top", False)

    def _compute_file_md5(self, file_path: str) -> Optional[str]:

        """
        Compute MD5 hash of a file.
        Args:
            file_path: Path to file
        Returns:
            MD5 hash as hexadecimal string, or None on error
        """
        try:
            md5_hash = hashlib.md5()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except (IOError, OSError) as e:
            print(f"Error computing MD5 for {file_path}: {e}")
            return None

    def _get_cnn_feature_if_cached(self, path: str, skip_mtime_check: bool = False) -> Optional['torch.Tensor']:
        """
        Get CNN feature from cache if available, without extracting.
        Returns None if not cached.
        """
        mw = self.main_window
        if not hasattr(mw, 'cnn_image_similarity_sorter') or not mw.cnn_image_similarity_sorter:
            return None
        cnn_sorter = mw.cnn_image_similarity_sorter
        # Check in-memory cache first
        if hasattr(cnn_sorter, '_feature_cache') and path in cnn_sorter._feature_cache:
            feat, cached_mtime, cached_size = cnn_sorter._feature_cache[path]
            try:
                stat = os.stat(path)
                if skip_mtime_check or (cached_mtime == stat.st_mtime and cached_size == stat.st_size):
                    return feat
            except (OSError, IOError):
                return None
        # Check disk cache via FeatureCacheManager
        if cnn_sorter.feature_cache:
            try:
                stat = os.stat(path)
                cached_feat = cnn_sorter.feature_cache.get_cnn_feature(
                    path, stat.st_mtime, stat.st_size, device='cpu'
                )
                return cached_feat
            except (OSError, IOError):
                return None
        return None
    def _get_clip_feature_if_cached(self, path: str, skip_mtime_check: bool = False) -> Optional['torch.Tensor']:
        """
        Get CLIP feature from cache if available, without extracting.
        Returns None if not cached.
        """
        mw = self.main_window
        if not hasattr(mw, 'cnn_image_similarity_sorter') or not mw.cnn_image_similarity_sorter:
            return None
        cnn_sorter = mw.cnn_image_similarity_sorter
        # Check in-memory cache first
        if hasattr(cnn_sorter, '_clip_feature_cache') and path in cnn_sorter._clip_feature_cache:
            feat, cached_mtime, cached_size = cnn_sorter._clip_feature_cache[path]
            try:
                stat = os.stat(path)
                if skip_mtime_check or (cached_mtime == stat.st_mtime and cached_size == stat.st_size):
                    return feat
            except (OSError, IOError):
                return None
        # Check disk cache via FeatureCacheManager
        if cnn_sorter.feature_cache:
            try:
                stat = os.stat(path)
                cached_feat = cnn_sorter.feature_cache.get_clip_feature(
                    path, stat.st_mtime, stat.st_size, device='cpu'
                )
                return cached_feat
            except (OSError, IOError):
                return None
        return None
    
    def _get_cnn_feature_with_metadata(self, path: str, skip_mtime_check: bool = False):
        """Get CNN feature with cached mtime/size metadata"""
        from PySide6.QtCore import QMutexLocker
        mw = self.main_window
        if not hasattr(mw, 'cnn_image_similarity_sorter') or not mw.cnn_image_similarity_sorter:
            return (None, None, None)
        cnn_sorter = mw.cnn_image_similarity_sorter
        # Check in-memory cache first
        if hasattr(cnn_sorter, '_feature_cache') and path in cnn_sorter._feature_cache:
            feat, cached_mtime, cached_size = cnn_sorter._feature_cache[path]
            try:
                stat = os.stat(path)
                if skip_mtime_check or (cached_mtime == stat.st_mtime and cached_size == stat.st_size):
                    return (feat, cached_mtime, cached_size)
            except (OSError, IOError):
                return (None, None, None)
        # Check disk cache
        if cnn_sorter.feature_cache:
            try:
                stat = os.stat(path)
                cached_feat = cnn_sorter.feature_cache.get_cnn_feature(
                    path, stat.st_mtime, stat.st_size, device='cpu'
                )
                if cached_feat is not None:
                    # Get cached mtime/size from disk cache
                    cache_key = cnn_sorter.feature_cache._get_cache_key(path)
                    with QMutexLocker(cnn_sorter.feature_cache.cache_mutex):
                        if cache_key in cnn_sorter.feature_cache.cnn_cache:
                            _, cached_mtime, cached_size = cnn_sorter.feature_cache.cnn_cache[cache_key]
                            return (cached_feat, cached_mtime, cached_size)
                    # Fallback to current file mtime/size
                    return (cached_feat, stat.st_mtime, stat.st_size)
            except (OSError, IOError):
                return (None, None, None)
        return (None, None, None)
    

    def _collect_pre_rename_features(self, images_to_rename: List[str], progress_callback=None) -> Dict[str, Tuple[Any, ...]]:
        """
        Collect MD5 hashes, cached CNN/CLIP features, and face encodings (if any) for files to be renamed.

        Returns:
            Dictionary mapping file paths to
            (md5_hash, cnn_feature, clip_feature, cnn_mtime, cnn_size, clip_mtime, clip_size, face_encodings_or_none).
            face_encodings_or_none is a list of 128-D embeddings or None when not cached.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from faces.face_cache import get_encodings

        pre_rename_data = {}
        total = len(images_to_rename)
        completed = 0

        def collect_for_path(path):
            """Collect MD5, CNN/CLIP features, and face encodings for a single path"""
            try:
                md5_hash = self._compute_file_md5(path)

                cnn_feat, cnn_mtime, cnn_size = self._get_cnn_feature_with_metadata(path, skip_mtime_check=True)
                clip_feat, clip_mtime, clip_size = self._get_clip_feature_with_metadata(path, skip_mtime_check=True)

                face_enc = None
                try:
                    face_enc = get_encodings(path, None, None)
                except Exception:
                    face_enc = None

                return path, (
                    md5_hash,
                    cnn_feat,
                    clip_feat,
                    cnn_mtime,
                    cnn_size,
                    clip_mtime,
                    clip_size,
                    face_enc,
                )
            except Exception as e:
                print(f"Error collecting features for {path}: {e}")
                return path, (None, None, None, None, None, None, None, None)

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_path = {executor.submit(collect_for_path, path): path for path in images_to_rename}
            for future in as_completed(future_to_path):
                try:
                    path, data = future.result()
                    pre_rename_data[path] = data
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total, f"Collecting features... ({completed}/{total})")
                except Exception as e:
                    path = future_to_path[future]
                    print(f"Error collecting features for {path}: {e}")
                    pre_rename_data[path] = (None, None, None, None, None, None, None, None)

        return pre_rename_data

    def _get_clip_feature_with_metadata(self, path: str, skip_mtime_check: bool = False):
        """Get CLIP feature with cached mtime/size metadata"""
        from PySide6.QtCore import QMutexLocker
        mw = self.main_window
        if not hasattr(mw, 'cnn_image_similarity_sorter') or not mw.cnn_image_similarity_sorter:
            return (None, None, None)
        cnn_sorter = mw.cnn_image_similarity_sorter
        # Check in-memory cache first
        if hasattr(cnn_sorter, '_clip_feature_cache') and path in cnn_sorter._clip_feature_cache:
            feat, cached_mtime, cached_size = cnn_sorter._clip_feature_cache[path]
            try:
                stat = os.stat(path)
                if skip_mtime_check or (cached_mtime == stat.st_mtime and cached_size == stat.st_size):
                    return (feat, cached_mtime, cached_size)
            except (OSError, IOError):
                return (None, None, None)
        # Check disk cache
        if cnn_sorter.feature_cache:
            try:
                stat = os.stat(path)
                cached_feat = cnn_sorter.feature_cache.get_clip_feature(
                    path, stat.st_mtime, stat.st_size, device='cpu'
                )
                if cached_feat is not None:
                    # Get cached mtime/size from disk cache
                    cache_key = cnn_sorter.feature_cache._get_cache_key(path)
                    with QMutexLocker(cnn_sorter.feature_cache.cache_mutex):
                        if cache_key in cnn_sorter.feature_cache.clip_cache:
                            _, cached_mtime, cached_size = cnn_sorter.feature_cache.clip_cache[cache_key]
                            return (cached_feat, cached_mtime, cached_size)
                    # Fallback to current file mtime/size
                    return (cached_feat, stat.st_mtime, stat.st_size)
            except (OSError, IOError):
                return (None, None, None)
        return (None, None, None)
    
    def _invalidate_features_for_rename(self, images_to_rename: List[str]):
        """
        Invalidate feature cache entries for files to be renamed.
        This must happen BEFORE rename to prevent stale cache entries.
        """
        mw = self.main_window
        if not hasattr(mw, 'cnn_image_similarity_sorter') or not mw.cnn_image_similarity_sorter:
            return
        cnn_sorter = mw.cnn_image_similarity_sorter
        # Invalidate in-memory cache
        if hasattr(cnn_sorter, '_feature_cache'):
            for path in images_to_rename:
                cnn_sorter._feature_cache.pop(path, None)
        if hasattr(cnn_sorter, '_clip_feature_cache'):
            for path in images_to_rename:
                cnn_sorter._clip_feature_cache.pop(path, None)
        # Invalidate FeatureCacheManager's cache entries for old paths
        if cnn_sorter.feature_cache:
            from PySide6.QtCore import QMutexLocker
            feature_cache = cnn_sorter.feature_cache
            with QMutexLocker(feature_cache.cache_mutex):
                for path in images_to_rename:
                    cache_key = feature_cache._get_cache_key(path)
                    feature_cache.cnn_cache.pop(cache_key, None)
                    feature_cache.clip_cache.pop(cache_key, None)
                    # Mark directory as dirty so old entries are removed when saved
                    dir_hash = feature_cache._get_directory_hash(path)
                    feature_cache._cnn_dirty_dirs.add(dir_hash)
                    feature_cache._clip_dirty_dirs.add(dir_hash)
                    feature_cache._cnn_dirty = True
                    feature_cache._clip_dirty = True
    def _collect_post_rename_hashes(self, rename_map: Dict[str, str], progress_callback=None) -> Dict[str, str]:
        """
        Compute MD5 hashes for successfully renamed files.
        Args:
            rename_map: Dictionary mapping old_path to new_path
            progress_callback: Optional callback(current, total, message) for progress updates
        Returns:
            Dictionary mapping new_path to md5_hash
        """
        post_rename_data = {}
        total = len(rename_map)
        completed = 0
        # Use parallel MD5 computation
        def compute_md5(new_path):
            if os.path.exists(new_path):
                return new_path, self._compute_file_md5(new_path)
            return new_path, None
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_path = {executor.submit(compute_md5, new_path): new_path for new_path in rename_map.values()}
            for future in as_completed(future_to_path):
                try:
                    new_path, md5_hash = future.result()
                    if md5_hash:
                        post_rename_data[new_path] = md5_hash
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total, f"Computing MD5 hashes... ({completed}/{total})")
                except Exception as e:
                    new_path = future_to_path[future]
                    print(f"Error computing MD5 for {new_path}: {e}")
        return post_rename_data
    def _restore_features_via_md5(
        self,
        pre_rename_data: Dict[str, Tuple[Optional[str], Optional['torch.Tensor'], Optional['torch.Tensor']]],
        post_rename_data: Dict[str, str],
        rename_map: Dict[str, str],
        flush_progress_callback=None
    ) -> int:
        """
        Match MD5 hashes and restore features to cache under new paths.
        Args:
            pre_rename_data: {old_path: (md5, cnn_feat, clip_feat)}
            post_rename_data: {new_path: md5_hash}
            rename_map: {old_path: new_path}
            flush_progress_callback: Optional callback(message) to call before flushing caches
        Returns:
            Number of features restored
        """
        mw = self.main_window
        if not hasattr(mw, 'cnn_image_similarity_sorter') or not mw.cnn_image_similarity_sorter:
            return 0
        cnn_sorter = mw.cnn_image_similarity_sorter
        if not cnn_sorter.feature_cache:
            return 0
        # Build MD5 to features mapping (with metadata)
        md5_to_features = {}
        for old_path, data in pre_rename_data.items():
            if len(data) >= 7:  # New format with metadata
                md5, cnn_feat, clip_feat, cnn_mtime, cnn_size, clip_mtime, clip_size = data[:7]
            else:  # Old format without metadata
                md5, cnn_feat, clip_feat = data[:3]
                cnn_mtime = cnn_size = clip_mtime = clip_size = None
            if md5 and md5 not in md5_to_features:
                md5_to_features[md5] = (cnn_feat, clip_feat, cnn_mtime, cnn_size, clip_mtime, clip_size)
        
        # Remove old cache entries from FeatureCacheManager before restoring
        from PySide6.QtCore import QMutexLocker
        feature_cache = cnn_sorter.feature_cache
        with QMutexLocker(feature_cache.cache_mutex):
            for old_path in rename_map.keys():
                old_cache_key = feature_cache._get_cache_key(old_path)
                feature_cache.cnn_cache.pop(old_cache_key, None)
                feature_cache.clip_cache.pop(old_cache_key, None)
                # Mark directory as dirty
                dir_hash = feature_cache._get_directory_hash(old_path)
                feature_cache._cnn_dirty_dirs.add(dir_hash)
                feature_cache._clip_dirty_dirs.add(dir_hash)
        
        # Restore features for matching MD5 hashes
        restored_count = 0
        for idx, (new_path, new_md5) in enumerate(post_rename_data.items()):
            if new_md5 in md5_to_features:
                if len(md5_to_features[new_md5]) >= 6:  # New format with metadata
                    cnn_feat, clip_feat, cnn_mtime, cnn_size, clip_mtime, clip_size = md5_to_features[new_md5]
                else:  # Old format
                    cnn_feat, clip_feat = md5_to_features[new_md5][:2]
                    cnn_mtime = cnn_size = clip_mtime = clip_size = None
                try:
                    # CRITICAL: Re-read file mtime/size RIGHT BEFORE restoring to ensure we have the final state
                    # after ALL date changes have been applied. This prevents cache mismatches.
                    # Brief delay every 100 files to allow FS sync (avoids 24s+ for 2400 files)
                    if idx > 0 and idx % 100 == 0:
                        time.sleep(0.01)
                    stat2 = os.stat(new_path)
                    # Use the second read to ensure we have the committed state
                    cnn_mtime_to_use = stat2.st_mtime
                    cnn_size_to_use = stat2.st_size
                    clip_mtime_to_use = stat2.st_mtime
                    clip_size_to_use = stat2.st_size
                    
                    # Restore CNN feature
                    if cnn_feat is not None:
                        cache_key = feature_cache._get_cache_key(new_path)
                        
                        # CRITICAL: Remove OLD cache entries with same path but different mtime/size
                        # This prevents mismatches when features are accessed after rename
                        with QMutexLocker(feature_cache.cache_mutex):
                            # Remove from FeatureCacheManager cache if exists with different mtime/size
                            if cache_key in feature_cache.cnn_cache:
                                old_feat, old_mtime, old_size = feature_cache.cnn_cache[cache_key]
                                if old_mtime != cnn_mtime_to_use or old_size != cnn_size_to_use:
                                    del feature_cache.cnn_cache[cache_key]
                            # Remove from sorter's in-memory cache if exists with different mtime/size
                            if hasattr(cnn_sorter, '_feature_cache') and new_path in cnn_sorter._feature_cache:
                                old_feat, old_mtime, old_size = cnn_sorter._feature_cache[new_path]
                                if old_mtime != cnn_mtime_to_use or old_size != cnn_size_to_use:
                                    del cnn_sorter._feature_cache[new_path]
                        
                        cnn_sorter.feature_cache.set_cnn_feature(new_path, cnn_feat, cnn_mtime_to_use, cnn_size_to_use)
                        # Also update in-memory cache
                        if hasattr(cnn_sorter, '_feature_cache'):
                            cnn_sorter._feature_cache[new_path] = (cnn_feat, cnn_mtime_to_use, cnn_size_to_use)
                        restored_count += 1
                    # Restore CLIP feature
                    if clip_feat is not None:
                        cache_key = feature_cache._get_cache_key(new_path)
                        
                        # CRITICAL: Remove OLD cache entries with same path but different mtime/size
                        with QMutexLocker(feature_cache.cache_mutex):
                            # Remove from FeatureCacheManager cache if exists with different mtime/size
                            if cache_key in feature_cache.clip_cache:
                                old_feat, old_mtime, old_size = feature_cache.clip_cache[cache_key]
                                if old_mtime != clip_mtime_to_use or old_size != clip_size_to_use:
                                    del feature_cache.clip_cache[cache_key]
                            # Remove from sorter's in-memory cache if exists with different mtime/size
                            if hasattr(cnn_sorter, '_clip_feature_cache') and new_path in cnn_sorter._clip_feature_cache:
                                old_feat, old_mtime, old_size = cnn_sorter._clip_feature_cache[new_path]
                                if old_mtime != clip_mtime_to_use or old_size != clip_size_to_use:
                                    del cnn_sorter._clip_feature_cache[new_path]
                        
                        cnn_sorter.feature_cache.set_clip_feature(new_path, clip_feat, clip_mtime_to_use, clip_size_to_use)
                        # Also update in-memory cache
                        if hasattr(cnn_sorter, '_clip_feature_cache'):
                            cnn_sorter._clip_feature_cache[new_path] = (clip_feat, clip_mtime_to_use, clip_size_to_use)
                        if cnn_feat is None:
                            restored_count += 1
                except (OSError, IOError) as e:
                    print(f"Error restoring features for {new_path}: {e}")
        # Flush caches to disk SYNCHRONOUSLY to ensure restored features are saved before refresh_directory
        # This is critical: if async, refresh_directory might reload cache from disk before flush completes
        # Update progress dialog if callback provided
        if flush_progress_callback:
            flush_progress_callback("Writing metadata to disk")
            QApplication.processEvents()
        cnn_sorter.feature_cache.flush_caches(async_flush=False)
        
        # CRITICAL: Keep directory cache marked as loaded so restored features stay in memory
        # The restored features are already in memory cache and have been flushed to disk.
        # If we force a reload, it might load old entries from disk before the flush completes,
        # or there might be a race condition. Instead, keep the restored entries in memory.
        # The directory cache file has been updated by flush, so future reloads will get correct entries.
        
        # Resume background CLIP process after mass rename completes
        mw = self.main_window
        if hasattr(mw, 'background_clip_controller') and mw.background_clip_controller:
            mw.background_clip_controller.resume_after_mass_rename()
        
        return restored_count

    def _migrate_face_metadata_after_rename(
        self,
        pre_rename_data: Dict[str, Tuple[Any, ...]],
        post_rename_data: Dict[str, str],
        rename_map: Dict[str, str],
        progress_message_callback=None,
    ) -> None:
        """
        Re-bind face embeddings, sample thumbnails, and known_faces sample paths after mass rename.
        Uses the same MD5 handoff as CNN/CLIP (pre_rename MD5 must match post_rename_data for new_path).
        """
        from faces.face_cache import (
            set_encodings,
            scrub_stale_entries,
            flush_face_cache_index,
            normalize_path_for_face_cache,
            persist_face_cache_index_always,
        )
        from faces.face_sample_cache import migrate_path_in_index
        from faces.known_faces_manager import update_sample_paths_for_rename

        if progress_message_callback:
            progress_message_callback("Migrating face recognition cache...")
        # Canvas / UI paths may differ from Path.resolve() keys used by get_image_list and face scan.
        pre_by_norm: Dict[str, Tuple[Any, ...]] = {}
        for pk, row in pre_rename_data.items():
            try:
                pre_by_norm[normalize_path_for_face_cache(pk)] = row
            except Exception:
                pre_by_norm[pk] = row
        post_by_norm: Dict[str, str] = {}
        for npth, md5v in post_rename_data.items():
            if md5v is None:
                continue
            try:
                post_by_norm[normalize_path_for_face_cache(npth)] = md5v
            except Exception:
                post_by_norm[npth] = md5v

        for old_path, new_path in rename_map.items():
            if old_path == new_path:
                continue
            try:
                old_norm = normalize_path_for_face_cache(old_path)
                new_norm = normalize_path_for_face_cache(new_path)
            except Exception:
                old_norm, new_norm = old_path, new_path
            data = pre_rename_data.get(old_path) or pre_by_norm.get(old_norm)
            if not data or len(data) < 8:
                continue
            md5_pre = data[0]
            face_enc = data[7]
            if not md5_pre:
                continue
            if face_enc is None:
                continue
            new_md5 = post_rename_data.get(new_path) or post_by_norm.get(new_norm)
            if new_md5 is None:
                continue
            if new_md5 != md5_pre:
                continue
            if not os.path.exists(new_path):
                continue
            try:
                st = os.stat(new_path)
                set_encodings(new_path, face_enc, st.st_mtime, st.st_size)
            except Exception as e:
                print(f"Warning: face cache migrate failed for {new_path}: {e}")

        # Drop stale index rows (old paths no longer on disk). Do not use remove_face_cache_entries
        # on old_path strings: after rename, resolve(old_path) can match resolve(new_path) on some
        # systems, which would pop the new entry we just wrote.
        try:
            scrub_stale_entries()
        except Exception as e:
            print(f"Warning: face cache scrub_stale_entries failed: {e}")

        for old_path, new_path in rename_map.items():
            if old_path == new_path:
                continue
            try:
                migrate_path_in_index(old_path, new_path)
            except Exception as e:
                print(f"Warning: sample thumb migrate failed {old_path} -> {new_path}: {e}")

        try:
            update_sample_paths_for_rename(rename_map)
        except Exception as e:
            print(f"Warning: known_faces path update failed: {e}")

        try:
            flush_face_cache_index()
        except Exception:
            pass
        try:
            persist_face_cache_index_always()
        except Exception:
            pass

    def rename_with_custom_prefix(self, bypass_dialog=False, prefix_template=None, 
                                   increment_length=None, starting_number=None,
                                   sort_mode=None, date_change_mode=None, order_direction=None):
        """Rename displayed images with a custom prefix (prompted from user, choose sort order).
        The `date_change_mode` setting is saved in the config and must be used to prime the corresponding radio buttons.
        Args:
            bypass_dialog: If True, skip the dialog and use provided parameters
            prefix_template: Prefix template to use when bypass_dialog is True
            increment_length: Sequence digit length when bypass_dialog is True
            starting_number: Starting number when bypass_dialog is True
            sort_mode: Sort mode ('order' or 'date') when bypass_dialog is True
            date_change_mode: Date change mode ('none', 'oldest', 'newest') when bypass_dialog is True
            order_direction: Order direction ('top' or 'bottom') when bypass_dialog is True
        """
        mw = self.main_window
        # Use saved config for date_change_mode if present
        if date_change_mode is None:
            date_change_mode = "none"
            if hasattr(mw, 'config') and isinstance(mw.config, dict):
                date_change_mode = mw.config.get('rename_date_change_mode', "none")

        # Only available in thumbnail view
        if mw.current_view_mode != 'thumbnail':
            mw.status_notification.show_message("Rename with custom prefix is only available in thumbnail view")
            return

        # Suspend all background thumbnail loading immediately
        # Stop background loader
        background_loader_was_running = False
        if hasattr(mw, 'cache_manager') and mw.cache_manager and mw.cache_manager.background_loader:
            background_loader_was_running = mw.cache_manager.background_loader.isRunning()
            if background_loader_was_running:
                mw.cache_manager.background_loader.stop()

        # Cancel thumbnail loading worker
        if hasattr(mw, 'thumbnail_worker') and mw.thumbnail_worker:
            try:
                if mw.thumbnail_worker.isRunning():
                    mw.thumbnail_worker.cancel()
                    # Use non-blocking cleanup
                    if hasattr(mw, 'cleanup_worker_thread'):
                        mw.cleanup_worker_thread('thumbnail_worker', delete_after=False)
                    else:
                        # Fallback: use QTimer for non-blocking cleanup
                        def cleanup():
                            try:
                                if hasattr(mw, 'thumbnail_worker') and mw.thumbnail_worker:
                                    if mw.thumbnail_worker.isRunning():
                                        mw.thumbnail_worker.terminate()
                                    if hasattr(mw, 'thumbnail_worker'):
                                        delattr(mw, 'thumbnail_worker')
                            except Exception:
                                pass
                        QTimer.singleShot(100, cleanup)
                else:
                    if hasattr(mw, 'thumbnail_worker'):
                        delattr(mw, 'thumbnail_worker')
            except Exception:
                try:
                    if hasattr(mw, 'cleanup_worker_thread'):
                        mw.cleanup_worker_thread('thumbnail_worker', delete_after=False)
                    else:
                        # Fallback: use QTimer for non-blocking cleanup
                        def cleanup():
                            try:
                                if hasattr(mw, 'thumbnail_worker') and mw.thumbnail_worker:
                                    if mw.thumbnail_worker.isRunning():
                                        mw.thumbnail_worker.terminate()
                                    if hasattr(mw, 'thumbnail_worker'):
                                        delattr(mw, 'thumbnail_worker')
                            except Exception:
                                pass
                        QTimer.singleShot(100, cleanup)
                except Exception:
                    if hasattr(mw, 'thumbnail_worker'):
                        delattr(mw, 'thumbnail_worker')

        # Helper function to restart background loading
        def restart_background_loading():
            if background_loader_was_running:
                if hasattr(mw, 'cache_manager') and mw.cache_manager and mw.cache_manager.background_loader:
                    mw.cache_manager.background_loader.start()
            if hasattr(mw, 'start_background_thumbnail_loading_if_needed'):
                mw.start_background_thumbnail_loading_if_needed()

        try:
            # Get selected files instead of all displayed images
            selected_files = mw.selection_manager.get_selected_files()
            if not selected_files:
                mw.status_notification.show_message("No files selected. Please select files to rename.")
                restart_background_loading()
                return

            # Check for Photos Library files before proceeding
            from utils import is_inside_photos_library, show_styled_warning
            photos_library_files = [f for f in selected_files if is_inside_photos_library(f)]
            if photos_library_files:
                show_styled_warning(
                    mw,
                    "Operation Not Allowed",
                    "Renaming files within macOS Photos Library is not allowed.\n\n"
                    "Photos Library files cannot be renamed or modified."
                )
                restart_background_loading()
                return

            # Get displayed images for later use (limit checking and highlight path)
            displayed_images = mw.get_displayed_images()
            
            # Check for locked files first
            has_locked_files = False
            if hasattr(mw, 'lock_manager') and mw.lock_manager:
                # Get directory from first selected file
                if selected_files:
                    target_dir = os.path.dirname(list(selected_files)[0])
                    locked_files = mw.lock_manager.get_locked_files(target_dir)
                    has_locked_files = len(locked_files) > 0
            
            # Check that all displayed files (matching filter, no limit) are selected
            # ONLY if there are locked files
            if has_locked_files:
                displayed_set = set(displayed_images)
                selected_set = set(selected_files)
                if displayed_set != selected_set:
                    missing_files = displayed_set - selected_set
                    show_styled_warning(
                        mw,
                        "Not All Files Selected",
                        f"Because there are locked files, all files in the displayed list must be selected before renaming.\n\n"
                        f"{len(missing_files)} {file_string(len(missing_files))} are not selected.\n\n"
                        f"Please select all files (Cmd-A) before renaming."
                    )
                    restart_background_loading()
                    return

            # Check if only one file is selected - recommend multi-select (skip if bypassing dialog)
            if not bypass_dialog and len(selected_files) == 1:
                msg_box = styled_message_box(
                    mw,
                    QMessageBox.Warning,
                    "Single File Selected",
                    "Only one image is selected. Rename with custom prefix is intended for multiple selections.\n\n"
                    "Do you want to rename only one file?",
                    buttons=QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                    default_button=QMessageBox.StandardButton.Yes
                )
                # Find the Yes button and change its text to "Continue", ensure it's the default
                continue_button = None
                for button in msg_box.findChildren(QPushButton):
                    if button.text() == "Yes":
                        button.setText("Continue")
                        continue_button = button
                    elif button.text() == "Cancel":
                        button.setDefault(False)
                # Ensure Continue button is default and has focus
                if continue_button:
                    continue_button.setDefault(True)
                    continue_button.setFocus()
                msg_box.exec()
                if msg_box.result_data['button'] != QMessageBox.StandardButton.Yes:
                    # User cancelled - exit
                    restart_background_loading()
                    return

            # Filter pattern check (only warn if no filter pattern, skip if bypassing dialog)
            if not bypass_dialog and not mw.filter_pattern:
                msg_box = styled_message_box(
                    mw,
                    QMessageBox.Warning,
                    "All Files will be Renamed",
                    "Rename all files with a custom prefix\n\nThe filter pattern is empty. This may lead to unwanted files being renamed.\n\n",
                    buttons=QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                    default_button=QMessageBox.StandardButton.Cancel
                )
                msg_box.exec()
                if msg_box.result_data['button'] != QMessageBox.StandardButton.Ok:
                    restart_background_loading()
                    return

            # Use selected files for renaming - ALWAYS use displayed order as source of truth
            # CRITICAL: selected_files is a set (unordered), so we MUST use displayed_images or canvas order
            # to preserve the visual order that the user sees
            selected_set = set(selected_files)
            
            # Try to get order from canvas first (preserves drag-and-drop reordering)
            canvas_order = None
            images_to_rename = []
            
            if hasattr(mw, 'thumbnail_container') and mw.thumbnail_container:
                try:
                    canvas = mw.thumbnail_container.canvas
                    if canvas and hasattr(canvas, 'thumbnails') and canvas.thumbnails:
                        # Get order from canvas thumbnails (this is the actual displayed order)
                        # This preserves drag-and-drop reordering
                        canvas_order = [thumb.image_path for thumb in canvas.thumbnails if hasattr(thumb, 'image_path')]
                        if canvas_order:
                            # Filter to only selected files, preserving canvas order
                            images_to_rename = [path for path in canvas_order if path in selected_set]
                except Exception:
                    pass
            
            # Fallback: if we don't have canvas order, use displayed_images order
            if not images_to_rename:
                # Use displayed_images as source of truth for order
                images_to_rename = [path for path in displayed_images if path in selected_set]
            
            # Add any selected files not in either order (shouldn't happen, but be safe)
            for path in selected_files:
                if path not in images_to_rename:
                    images_to_rename.append(path)
            
            hilighted_path = None
            if hasattr(mw, "highlight_index") and 0 <= mw.highlight_index < len(displayed_images):
                hilighted_path = displayed_images[mw.highlight_index]
            if images_to_rename and hasattr(mw, 'cache_manager') and mw.cache_manager:
                if hasattr(mw.cache_manager, 'background_loader') and mw.cache_manager.background_loader:
                    for image_path in images_to_rename:
                        mw.cache_manager.background_loader.remove_requests_for_file(image_path)
            if not images_to_rename:
                mw.status_notification.show_message("No images to rename")
                restart_background_loading()
                return

            # Only single-directory accepted
            directories = set()
            for image_path in images_to_rename:
                if os.path.exists(image_path):
                    directories.add(os.path.dirname(image_path))
            if len(directories) != 1:
                show_styled_warning(
                    mw,
                    "Multiple Directories",
                    "All selected images must be in the same directory. "
                    "Multiple directories are not supported."
                )
                restart_background_loading()
                return

            target_directory = directories.pop()
            
            # Check if directory is writable
            if not os.access(target_directory, os.W_OK):
                show_styled_warning(
                    mw,
                    "Directory Not Writable",
                    f"The directory is not writable:\n\n{target_directory}\n\n"
                    "You do not have permission to rename files in this directory."
                )
                restart_background_loading()
                return
            
            config = get_config()
            settings = config.load_settings()
            
            if bypass_dialog:
                # Use provided parameters or defaults
                if prefix_template is None:
                    prefix_template = settings.get('rename_custom_prefix', 'image-%d')
                if increment_length is None:
                    increment_length = settings.get('rename_increment_length', 5)
                if starting_number is None:
                    starting_number = settings.get('rename_starting_number', 1)
                if sort_mode is None:
                    sort_mode = 'order'  # Default for quick mass rename
                if date_change_mode is None:
                    date_change_mode = 'none'  # Default for quick mass rename
                if order_direction is None:
                    order_direction = 'top'  # Default for quick mass rename
                # Blank/whitespace prefix: show rename dialog so user can set it
                if not str(prefix_template or '').strip():
                    bypass_dialog = False

            if bypass_dialog:
                ok = True
            else:
                saved_prefix = settings.get('rename_custom_prefix', '')
                saved_increment_length = settings.get('rename_increment_length', 5)
                saved_starting_number = settings.get('rename_starting_number', 1)
                saved_sort_mode = settings.get('rename_sort_mode', 'date')
                saved_date_change_mode = settings.get('rename_date_change_mode', 'none')
                saved_order_direction = settings.get('rename_order_direction', 'top')
                # Handle legacy boolean value for backward compatibility
                if isinstance(saved_date_change_mode, bool):
                    saved_date_change_mode = 'oldest' if saved_date_change_mode else 'none'

                # Pass date_change_mode and order_direction to dialog and get its value back
                prefix_template, increment_length, starting_number, sort_mode, date_change_mode, order_direction, ok = self._show_rename_prefix_dialog(
                    saved_prefix, saved_increment_length, saved_starting_number, saved_sort_mode, saved_date_change_mode, saved_order_direction
                )
                if not ok:
                    restart_background_loading()
                    return
            
            # Preload CLIP/CNN caches if not already loaded, so they are updated by existing code during rename
            # Ensure the sorter is initialized (creates it if it doesn't exist)
            if hasattr(mw, '_ensure_cnn_sorter_initialized'):
                try:
                    mw._ensure_cnn_sorter_initialized()
                    if mw.cnn_image_similarity_sorter:
                        mw.cnn_image_similarity_sorter._ensure_feature_cache_loaded()
                        # Mark cache activity to reset unload timer
                        if mw.cnn_image_similarity_sorter.feature_cache:
                            mw.cnn_image_similarity_sorter.feature_cache.mark_cache_activity()
                except Exception as e:
                    # Non-fatal: cache preload failed, but rename can still proceed
                    print(f"Warning: Could not preload feature cache before rename: {e}")
            else:
                print(f"Warning: No _ensure_cnn_sorter_initialized")
            # Save the original display sort mode to restore it after rename
            original_display_sort_mode = None
            if hasattr(mw, 'current_sort_mode'):
                original_display_sort_mode = mw.current_sort_mode
            dirname = os.path.basename(target_directory.rstrip(os.sep))
            if not dirname:
                dirname = "directory"
            prefix = prefix_template.replace('%d', dirname).replace('%D', dirname)
            is_valid, error_msg = self._validate_unix_filename(prefix)
            if not is_valid:
                detail = (
                    f"Invalid prefix: {error_msg}\n\n"
                    "Please enter a valid Unix filename prefix."
                )
                if not str(prefix or '').strip():
                    detail += (
                        "\n\nSet a prefix via Edit → Rename with Custom Prefix (Ctrl+N). "
                        "Quick Mass Rename uses the last prefix saved there."
                    )
                show_styled_warning(mw, "Invalid Prefix", detail)
                restart_background_loading()
                return
            max_sequence = 10 ** increment_length - 1
            if starting_number > max_sequence:
                show_styled_warning(
                    mw,
                    "Invalid Starting Number",
                    f"Starting number {starting_number} exceeds maximum {max_sequence} for {increment_length} digits.\n\n"
                    f"Please use a starting number between 1 and {max_sequence}."
                )
                restart_background_loading()
                return
            # Save dialog settings to config (save before confirmation dialog so settings persist even if user cancels)
            config.update_setting('rename_custom_prefix', prefix_template)
            config.update_setting('rename_increment_length', increment_length)
            config.update_setting('rename_starting_number', starting_number)
            # Only save sort_mode, date_change_mode, order_direction if:
            # - Not bypassing dialog (normal rename dialog), OR
            # - Bypassing dialog but QUICK_MASS_RENAME_USE_USER_SETTINGS is False (save presets)
            if not bypass_dialog or not QUICK_MASS_RENAME_USE_USER_SETTINGS:
                config.update_setting('rename_sort_mode', sort_mode)
                config.update_setting('rename_date_change_mode', date_change_mode)
                config.update_setting('rename_order_direction', order_direction)
            
            # Filter images_to_rename to only include files that exist and are in target_directory
            images_to_rename = [img for img in images_to_rename
                                if os.path.exists(img) and os.path.dirname(img) == target_directory]
            if not images_to_rename:
                mw.status_notification.show_message("No images to rename")
                restart_background_loading()
                return
            
            # CRITICAL: When sort_mode is "order", consolidate locked files to top AFTER filtering
            # This ensures the final list that will be renamed has locked files first
            if sort_mode == "order" and hasattr(mw, 'lock_manager') and mw.lock_manager:
                locked_files = mw.lock_manager.get_locked_files(target_directory)
                if locked_files:
                    # Get locked files in their saved order from .prsort
                    prsort_result = mw.sorting_manager._read_prsort_file(target_directory)
                    locked_paths_ordered = []
                    locked_paths_set = set()
                    
                    if prsort_result:
                        prsort_filenames, _, _ = prsort_result
                        # Build mapping of filename -> full path
                        filename_to_path = {os.path.basename(path): path for path in images_to_rename}
                        # Get locked files in their saved order from .prsort
                        for filename in prsort_filenames:
                            if filename in locked_files and filename in filename_to_path:
                                path = filename_to_path[filename]
                                if path not in locked_paths_set:
                                    locked_paths_ordered.append(path)
                                    locked_paths_set.add(path)
                    
                    # Add any locked files not in .prsort
                    for path in images_to_rename:
                        filename = os.path.basename(path)
                        if filename in locked_files and path not in locked_paths_set:
                            locked_paths_ordered.append(path)
                            locked_paths_set.add(path)
                    
                    # Separate locked and unlocked files
                    unlocked_paths = [path for path in images_to_rename if path not in locked_paths_set]
                    
                    # Reorder images_to_rename with locked files first (in their .prsort order)
                    images_to_rename = locked_paths_ordered + unlocked_paths
            
            dirname = os.path.basename(target_directory.rstrip(os.sep))
            if not dirname:
                dirname = "directory"
            if not os.access(target_directory, os.W_OK):
                show_styled_warning(
                    mw,
                    "Permission Error",
                    f"The directory '{dirname}' is not writable.\n\n"
                    "Please check directory permissions and try again."
                )
                restart_background_loading()
                return
            try:
                test_file_path = os.path.join(target_directory, ".prowser_rename_test")
                try:
                    with open(test_file_path, 'w') as f:
                        f.write("test")
                    os.remove(test_file_path)
                except Exception:
                    try:
                        if os.path.exists(test_file_path):
                            os.remove(test_file_path)
                    except:
                        pass
                    raise
            except Exception as e:
                show_styled_warning(
                    mw,
                    "Permission Error",
                    f"Cannot write to directory '{dirname}'.\n\n"
                    f"Error: {str(e)}\n\n"
                    "Please check directory permissions and try again."
                )
                restart_background_loading()
                return
            non_renameable_files = []
            for image_path in images_to_rename:
                try:
                    if not os.path.exists(image_path):
                        non_renameable_files.append((os.path.basename(image_path), "File does not exist"))
                        continue
                    file_dir = os.path.dirname(image_path)
                    if not os.access(file_dir, os.W_OK):
                        non_renameable_files.append((os.path.basename(image_path), "Parent directory not writable"))
                        continue
                    try:
                        test_temp_name = f".prowser_rename_test_{int(time.time() * 1000000)}"
                        test_temp_path = os.path.join(file_dir, test_temp_name)
                        os.rename(image_path, test_temp_path)
                        os.rename(test_temp_path, image_path)
                    except PermissionError:
                        non_renameable_files.append((os.path.basename(image_path), "Permission denied: cannot rename file"))
                    except OSError as e:
                        non_renameable_files.append((os.path.basename(image_path), f"OS error: {str(e)}"))
                    except Exception as e:
                        non_renameable_files.append((os.path.basename(image_path), f"Unexpected error: {str(e)}"))
                except Exception as e:
                    non_renameable_files.append((os.path.basename(image_path), f"Permission check failed: {str(e)}"))
            if non_renameable_files:
                error_list = "\n".join([f"  • {name}: {reason}" for name, reason in non_renameable_files[:10]])
                if len(non_renameable_files) > 10:
                    error_list += f"\n  ... and {len(non_renameable_files) - 10} more {file_string(len(non_renameable_files) - 10)}"
                show_styled_warning(
                    mw,
                    "Permission Error",
                    f"Cannot rename some files in '{dirname}'.\n\n"
                    f"Files with permission issues:\n{error_list}\n\n"
                    "Please check file permissions and try again."
                )
                restart_background_loading()
                return

            # Create progress dialog early to prevent beachball during preparation
            # Set up progress phases: sorting (10%), calculating names (40%), building plan (50%)
            num_images = len(images_to_rename)
            # Preparation phase: 100 steps (sorting: 0-10, calculating: 10-50, building: 50-100)
            PREP_TOTAL = 100
            progress_dialog = QProgressDialog("Preparing rename...", None, 0, PREP_TOTAL, mw)
            progress_dialog.setWindowTitle("Rename Files")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setCancelButton(None)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setAutoClose(False)  # Don't auto-close when reaching 100% - we'll close manually after cache flush
            progress_dialog.setAutoReset(False)  # Don't reset when reaching 100%
            progress_dialog.setValue(0)
            wrap_progress_dialog_label_elision(progress_dialog)
            progress_dialog.show()
            QApplication.processEvents()

            # Progress callback helper
            def update_progress(current, total, message, phase_start, phase_end):
                """Update progress within a phase range"""
                if total > 0:
                    phase_progress = int(phase_start + (phase_end - phase_start) * current / total)
                else:
                    phase_progress = phase_start
                progress_dialog.setValue(phase_progress)
                progress_dialog.setLabelText(message)
                QApplication.processEvents()

            # --------- SORT LOGIC: New code supporting two sort modes ------------------
            # Initialize original_displayed_order for date setting after rename
            original_displayed_order = None
            
            # CRITICAL: Preserve locked files order BEFORE any sorting
            # Locked files must maintain their saved order from .prsort, regardless of sort_mode
            locked_files_order = None
            if hasattr(mw, 'lock_manager') and mw.lock_manager and target_directory:
                locked_files = mw.lock_manager.get_locked_files(target_directory)
                if locked_files:
                    # Get locked files in their saved order from .prsort
                    prsort_result = mw.sorting_manager._read_prsort_file(target_directory)
                    if prsort_result:
                        prsort_filenames, _, _ = prsort_result
                        # Build ordered list of locked file paths
                        filename_to_path = {os.path.basename(path): path for path in images_to_rename}
                        locked_files_order = []
                        for filename in prsort_filenames:
                            if filename in locked_files and filename in filename_to_path:
                                path = filename_to_path[filename]
                                if path not in locked_files_order:
                                    locked_files_order.append(path)
                        # Add any locked files not in .prsort at the end
                        for path in images_to_rename:
                            filename = os.path.basename(path)
                            if filename in locked_files and path not in locked_files_order:
                                locked_files_order.append(path)
            
            try:
                progress_dialog.setLabelText("Sorting images...")
                QApplication.processEvents()
                
                if sort_mode == "order":
                    # Sort using current displayed order (NO reordering!)
                    # CRITICAL: images_to_rename is ALREADY in the correct order from earlier code
                    # (either canvas order or displayed_images order), so we do NOT reorder here.
                    # Just preserve the existing order - do nothing!
                    
                    # Save original displayed order for date setting after rename
                    # This is the order BEFORE reversal for sequence numbering
                    original_displayed_order = list(images_to_rename)
                    
                    # Set dates based on displayed order position if date_change_mode is set
                    # This happens BEFORE reversing for sequence numbering, so dates are based on original displayed order
                    if date_change_mode in ('oldest', 'newest'):
                        progress_dialog.setLabelText("Setting file dates based on displayed order...")
                        QApplication.processEvents()
                        now = int(time.time())
                        total_files = len(images_to_rename)
                        
                        # Prepare file paths with their display indices
                        file_paths_with_indices = [(path, idx) for idx, path in enumerate(images_to_rename)]
                        
                        # Get minimal set of date changes needed
                        changes_needed = self._minimize_date_changes(
                            file_paths_with_indices, date_change_mode, now, total_files
                        )
                        
                        # Apply only the necessary date changes
                        # Batch metadata updates for better performance
                        metadata_updates = []
                        for path, new_mtime in changes_needed:
                            if os.path.exists(path):
                                try:
                                    os.utime(path, (new_mtime, new_mtime))
                                    # Batch cache updates
                                    if hasattr(mw, 'cache_manager') and mw.cache_manager:
                                        try:
                                            from cache.image_cache import ImageMetadata
                                            existing_metadata = mw.cache_manager.get_metadata_sync(path)
                                            if existing_metadata:
                                                updated_metadata = existing_metadata._replace(modified_time=new_mtime)
                                                metadata_updates.append((path, updated_metadata))
                                        except Exception:
                                            pass
                                except Exception:
                                    pass  # Don't fail if date setting has issues
                        # Batch update metadata
                        if metadata_updates and hasattr(mw, 'cache_manager') and mw.cache_manager:
                            try:
                                mw.cache_manager.cache_metadata_batch_sync(metadata_updates, defer_save=True)
                            except Exception:
                                pass
                    
                    # CRITICAL: Handle "bottom becomes 1" reversal
                    # If order_direction is "bottom", reverse the entire list so bottom item gets number 1
                    # Locked files WILL be included in numbering (they get numbers based on their position in reversed list)
                    # NOTE: We reverse images_to_rename for numbering, but preserve original_displayed_order for final display
                    if order_direction == "bottom":
                        # Reverse entire list - this ensures bottom item gets number 1
                        # Locked files are included and will be numbered based on their position
                        images_to_rename.reverse()
                    
                    progress_dialog.setValue(10)
                    QApplication.processEvents()
                else:
                    # "date" - sort by user sort key, default as before (date asc via main_window._get_sort_key or mtime)
                    # If date_change_mode is set, we need to set dates BEFORE sorting so sort uses new dates
                    # But we need to know the final sequence order first, so we calculate target names first
                    # Then set dates based on final sequence order, then sort
                    if date_change_mode in ('oldest', 'newest'):
                        # First, calculate what the final names will be to determine sequence order
                        # We'll do a quick calculation to get the order
                        progress_dialog.setLabelText("Calculating final order for date setting...")
                        QApplication.processEvents()
                        
                        # Calculate target names temporarily to get the order
                        try:
                            temp_target_mappings = self._calculate_target_names(
                                images_to_rename, prefix, target_directory, increment_length, starting_number,
                                progress_callback=None
                            )
                            # Extract sequence numbers from final filenames and sort by them
                            def get_sequence_number(target_path):
                                basename = os.path.basename(target_path)
                                # Extract number from pattern: prefix-NNNN.ext
                                match = re.search(rf'{re.escape(prefix)}-(\d+)(\.[^.]+)?$', basename)
                                if match:
                                    return int(match.group(1))
                                return 999999  # Put unmatched files at end
                            
                            # Sort target_mappings by sequence number
                            temp_target_mappings.sort(key=lambda x: get_sequence_number(x[1]))
                            
                            # Create mapping: old_path -> sequence_index
                            old_path_to_seq_idx = {}
                            for seq_idx, (old_path, new_path) in enumerate(temp_target_mappings):
                                old_path_to_seq_idx[old_path] = seq_idx
                            
                            # Set dates on original files based on their final sequence order
                            progress_dialog.setLabelText("Setting file dates for sorting...")
                            QApplication.processEvents()
                            now = int(time.time())
                            total_files = len(temp_target_mappings)
                            
                            # Prepare file paths with their sequence indices
                            file_paths_with_indices = [
                                (path, old_path_to_seq_idx[path]) 
                                for path in images_to_rename 
                                if os.path.exists(path) and path in old_path_to_seq_idx
                            ]
                            
                            # Get minimal set of date changes needed
                            changes_needed = self._minimize_date_changes(
                                file_paths_with_indices, date_change_mode, now, total_files
                            )
                            
                            # Apply only the necessary date changes
                            # Batch metadata updates for better performance
                            metadata_updates = []
                            for path, new_mtime in changes_needed:
                                try:
                                    os.utime(path, (new_mtime, new_mtime))
                                    # Batch cache updates
                                    if hasattr(mw, 'cache_manager') and mw.cache_manager:
                                        try:
                                            from cache.image_cache import ImageMetadata
                                            existing_metadata = mw.cache_manager.get_metadata_sync(path)
                                            if existing_metadata:
                                                updated_metadata = existing_metadata._replace(modified_time=new_mtime)
                                                metadata_updates.append((path, updated_metadata))
                                        except Exception:
                                            pass
                                except Exception:
                                    pass  # Don't fail if date setting has issues
                            # Batch update metadata
                            if metadata_updates and hasattr(mw, 'cache_manager') and mw.cache_manager:
                                try:
                                    mw.cache_manager.cache_metadata_batch_sync(metadata_updates, defer_save=True)
                                except Exception:
                                    pass
                        except Exception as e:
                            print(f"Error calculating target names for date setting: {e}")
                            traceback.print_exc()
                            # Fall back to setting dates based on current order
                            now = int(time.time())
                            total_files = len(images_to_rename)
                            file_paths_with_indices = [(path, idx) for idx, path in enumerate(images_to_rename)]
                            changes_needed = self._minimize_date_changes(
                                file_paths_with_indices, date_change_mode, now, total_files
                            )
                            for path, new_mtime in changes_needed:
                                if os.path.exists(path):
                                    try:
                                        os.utime(path, (new_mtime, new_mtime))
                                    except Exception:
                                        pass
                    
                    # Now sort by date (which will use the newly set dates)
                    if hasattr(mw, 'get_sort_key'):
                        # Pre-calculate sort keys with progress updates
                        progress_dialog.setLabelText("Calculating sort keys...")
                        QApplication.processEvents()
                        sort_keys = []
                        for idx, path in enumerate(images_to_rename):
                            if idx % 50 == 0:
                                update_progress(idx, num_images, f"Calculating sort keys... ({idx}/{num_images})", 0, 8)
                            sort_keys.append((mw.get_sort_key(path), path))
                        progress_dialog.setLabelText("Sorting images...")
                        QApplication.processEvents()
                        sort_keys.sort(key=lambda x: x[0], reverse=False)
                        images_to_rename[:] = [path for _, path in sort_keys]
                    else:
                        # Pre-calculate mtimes with progress updates
                        progress_dialog.setLabelText("Reading file dates...")
                        QApplication.processEvents()
                        sort_keys = []
                        for idx, path in enumerate(images_to_rename):
                            if idx % 50 == 0:
                                update_progress(idx, num_images, f"Reading file dates... ({idx}/{num_images})", 0, 8)
                            mtime = os.path.getmtime(path) if os.path.exists(path) else 0
                            sort_keys.append((mtime, path))
                        progress_dialog.setLabelText("Sorting images...")
                        QApplication.processEvents()
                        sort_keys.sort(key=lambda x: x[0], reverse=False)
                        images_to_rename[:] = [path for _, path in sort_keys]
                    
                    # CRITICAL: Handle "bottom becomes 1" reversal for date sort mode
                    # If order_direction is "bottom", reverse the entire list so bottom item gets number 1
                    # Locked files WILL be included in numbering (they get numbers based on their position in reversed list)
                    # After rename, locked files will be reordered to top via .prsort file
                    if order_direction == "bottom":
                        # Reverse entire list - this ensures bottom item gets number 1
                        # Locked files are included and will be numbered based on their position
                        images_to_rename.reverse()
                    
                    progress_dialog.setValue(10)
                    QApplication.processEvents()
            except Exception:
                progress_dialog.close()
                show_styled_warning(
                    mw,
                    "Sort Error",
                    "Failed to sort images for renaming. Rename cancelled."
                )
                restart_background_loading()
                return

            try:
                def calc_progress_callback(current, total, message):
                    update_progress(current, total, message, 10, 50)
                # Subset + order mode: start at max(settings, lowest in dir), prefer source number when available
                effective_start_override = None
                prefer_source_number = False
                if sort_mode == "order" and len(images_to_rename) < len(displayed_images):
                    lowest = self._get_lowest_sequence_in_directory(prefix, target_directory, increment_length)
                    effective_start_override = max(starting_number, lowest) if lowest is not None else starting_number
                    prefer_source_number = True
                target_mappings = self._calculate_target_names(
                    images_to_rename, prefix, target_directory, increment_length, starting_number,
                    progress_callback=calc_progress_callback,
                    effective_start_override=effective_start_override,
                    prefer_source_number=prefer_source_number
                )
                progress_dialog.setValue(50)
                progress_dialog.setLabelText("Building rename plan...")
                QApplication.processEvents()
                
            except ValueError as e:
                progress_dialog.close()
                show_styled_warning(
                    mw,
                    "Sequence Number Overflow",
                    str(e)
                )
                restart_background_loading()
                return

            temp_prefix = self._find_available_temp_prefix(target_directory)
            def plan_progress_callback(current, total, message):
                update_progress(current, total, message, 50, 100)
            # Check if there are any actual renames to perform
            actual_renames = [m for m in target_mappings if m[0] != m[1]]
            
            # Even if files don't need renaming, we may still need to set dates
            if not actual_renames:
                # Files are already correctly named, but check if we need to set dates
                if date_change_mode in ('oldest', 'newest'):
                    # Set dates based on final sequence order even if no rename needed
                    progress_dialog.setLabelText("Setting file dates...")
                    QApplication.processEvents()
                    now = int(time.time())
                    
                    if sort_mode == "order" and original_displayed_order is not None:
                        # When sorting by current order, use original displayed order position
                        # Create mapping from old_path to displayed order position
                        old_path_to_displayed_idx = {}
                        for displayed_idx, old_path in enumerate(original_displayed_order):
                            old_path_to_displayed_idx[old_path] = displayed_idx
                        
                        total_files = len(original_displayed_order)
                        
                        # Prepare file paths with their displayed indices
                        file_paths_with_indices = [
                            (new_path, old_path_to_displayed_idx[old_path])
                            for old_path, new_path in target_mappings
                            if os.path.exists(new_path) and old_path in old_path_to_displayed_idx
                        ]
                        
                        # Get minimal set of date changes needed
                        changes_needed = self._minimize_date_changes(
                            file_paths_with_indices, date_change_mode, now, total_files
                        )
                        
                        # Apply only the necessary date changes
                        # Batch metadata updates for better performance
                        metadata_updates = []
                        for new_path, new_mtime in changes_needed:
                            try:
                                os.utime(new_path, (new_mtime, new_mtime))
                                actual_mtime = os.path.getmtime(new_path)
                                
                                # Batch cache updates
                                if hasattr(mw, 'cache_manager') and mw.cache_manager:
                                    try:
                                        from cache.image_cache import ImageMetadata
                                        existing_metadata = mw.cache_manager.get_metadata_sync(new_path)
                                        if existing_metadata:
                                            updated_metadata = existing_metadata._replace(modified_time=actual_mtime)
                                            metadata_updates.append((new_path, updated_metadata))
                                    except Exception:
                                        pass
                            except Exception as e:
                                print(f"  ERROR setting date for {os.path.basename(new_path)}: {e}")
                                traceback.print_exc()
                        # Batch update metadata
                        if metadata_updates and hasattr(mw, 'cache_manager') and mw.cache_manager:
                            try:
                                mw.cache_manager.cache_metadata_batch_sync(metadata_updates, defer_save=True)
                            except Exception:
                                pass
                    else:
                        # When sorting by date, use sequence numbers from filenames
                        total_files = len(target_mappings)
                        
                        # Extract sequence numbers from filenames and sort by them
                        def get_sequence_number(target_path):
                            basename = os.path.basename(target_path)
                            match = re.search(rf'{re.escape(prefix)}-(\d+)(\.[^.]+)?$', basename)
                            if match:
                                return int(match.group(1))
                            return 999999
                        
                        # Sort target_mappings by sequence number
                        sorted_mappings = sorted(target_mappings, key=lambda x: get_sequence_number(x[1]))
                        
                        # Prepare file paths with their sequence indices
                        file_paths_with_indices = [
                            (new_path, idx)
                            for idx, (old_path, new_path) in enumerate(sorted_mappings)
                            if os.path.exists(new_path)
                        ]
                        
                        # Get minimal set of date changes needed
                        changes_needed = self._minimize_date_changes(
                            file_paths_with_indices, date_change_mode, now, total_files
                        )
                        
                        # Apply only the necessary date changes
                        # Batch metadata updates for better performance
                        metadata_updates = []
                        for new_path, new_mtime in changes_needed:
                            try:
                                os.utime(new_path, (new_mtime, new_mtime))
                                actual_mtime = os.path.getmtime(new_path)
                                
                                # Batch cache updates
                                if hasattr(mw, 'cache_manager') and mw.cache_manager:
                                    try:
                                        from cache.image_cache import ImageMetadata
                                        existing_metadata = mw.cache_manager.get_metadata_sync(new_path)
                                        if existing_metadata:
                                            updated_metadata = existing_metadata._replace(modified_time=actual_mtime)
                                            metadata_updates.append((new_path, updated_metadata))
                                    except Exception:
                                        pass
                            except Exception as e:
                                print(f"  ERROR setting date for {os.path.basename(new_path)}: {e}")
                                traceback.print_exc()
                        # Batch update metadata
                        if metadata_updates and hasattr(mw, 'cache_manager') and mw.cache_manager:
                            try:
                                mw.cache_manager.cache_metadata_batch_sync(metadata_updates, defer_save=True)
                            except Exception:
                                pass
                    
                    # CRITICAL: Clear selections even if only dates were updated
                    if hasattr(mw, 'selected_files'):
                        mw.selected_files.clear()
                    if hasattr(mw, '_emit_selection_changed'):
                        mw._emit_selection_changed()
                    progress_dialog.close()
                    mw.status_notification.show_message("File dates updated")
                    restart_background_loading()
                    return
                else:
                    # No rename and no date change needed
                    # CRITICAL: Clear selections even if no rename happened
                    if hasattr(mw, 'selected_files'):
                        mw.selected_files.clear()
                    if hasattr(mw, '_emit_selection_changed'):
                        mw._emit_selection_changed()
                    progress_dialog.close()
                    mw.status_notification.show_message("All files are already correctly named")
                    # CRITICAL: Still highlight 1st non-locked item if there are locked files
                    # Even though no rename happened, user expects highlight to be on 1st non-locked
                    # target_mappings exists at this point (defined before the check)
                    # Since no renames happened, all mappings are old->old, so create identity mapping
                    rename_map_dict = {path: path for path in displayed_images} if displayed_images else {}
                    self._highlight_first_non_locked_after_rename(mw, target_directory, rename_map_dict)
                    restart_background_loading()
                    return
            
            # Prepare background CLIP process for mass rename
            # This flushes background cache, imports it, and pauses the process
            if hasattr(mw, 'background_clip_controller') and mw.background_clip_controller:
                if not mw.background_clip_controller.prepare_for_mass_rename():
                    mw.status_notification.show_message("Warning: Background CLIP process did not flush in time. Proceeding anyway.")
            
            # NEW: Collect pre-rename features and invalidate cache
            if settings.get('preserve_features_on_rename', True):
                def pre_progress_callback(current, total, message):
                    progress_dialog.setValue(int(current * 10 / total))
                    progress_dialog.setLabelText(message)
                    QApplication.processEvents()
                
                # Collect features BEFORE invalidating cache
                pre_rename_data = self._collect_pre_rename_features(images_to_rename, progress_callback=pre_progress_callback)
                # Now invalidate old cache entries
                self._invalidate_features_for_rename(images_to_rename)
            
            # CRITICAL: Check for read-only conflicting files BEFORE building rename plan
            # These are files that would be moved in Phase 0 but aren't being renamed themselves
            progress_dialog.setLabelText("Checking for conflicting files...")
            QApplication.processEvents()
            conflicting_readonly_files = []
            try:
                # Build set of existing files (case-insensitive) - same logic as Phase 0
                existing_files_map = {}  # filename_upper -> actual filepath
                try:
                    filenames = os.listdir(target_directory)
                    for filename in filenames:
                        filepath = os.path.join(target_directory, filename)
                        if os.path.isfile(filepath):
                            existing_files_map[filename.upper()] = filepath
                except Exception:
                    pass
                
                # Build set of source paths being renamed
                source_paths = set()
                for source_path, _ in target_mappings:
                    source_paths.add(os.path.normpath(os.path.realpath(source_path)))
                
                # Find conflicting files (same logic as Phase 0)
                for target_filename_upper, target_path in [(os.path.basename(t).upper(), t) for _, t in target_mappings]:
                    if target_filename_upper in existing_files_map:
                        existing_file_path = existing_files_map[target_filename_upper]
                        existing_file_normalized = os.path.normpath(os.path.realpath(existing_file_path))
                        # Only check it if it's not one of the source files being renamed
                        if existing_file_normalized not in source_paths:
                            # Check if this conflicting file is writable/renameable
                            try:
                                if not os.path.exists(existing_file_path):
                                    continue
                                file_dir = os.path.dirname(existing_file_path)
                                if not os.access(file_dir, os.W_OK):
                                    conflicting_readonly_files.append((os.path.basename(existing_file_path), "Parent directory not writable"))
                                    continue
                                # Test if file can be renamed (same test as earlier permission check)
                                test_temp_name = f".prowser_rename_test_{int(time.time() * 1000000)}"
                                test_temp_path = os.path.join(file_dir, test_temp_name)
                                os.rename(existing_file_path, test_temp_path)
                                os.rename(test_temp_path, existing_file_path)
                            except PermissionError:
                                conflicting_readonly_files.append((os.path.basename(existing_file_path), "Permission denied: cannot rename file"))
                            except OSError as e:
                                conflicting_readonly_files.append((os.path.basename(existing_file_path), f"OS error: {str(e)}"))
                            except Exception as e:
                                conflicting_readonly_files.append((os.path.basename(existing_file_path), f"Unexpected error: {str(e)}"))
            except Exception as e:
                # If check fails, log but don't block - let the rename proceed and fail naturally
                print(f"Warning: Failed to check conflicting files: {e}")
                traceback.print_exc()
            
            if conflicting_readonly_files:
                progress_dialog.close()
                error_list = "\n".join([f"  • {name}: {reason}" for name, reason in conflicting_readonly_files[:10]])
                if len(conflicting_readonly_files) > 10:
                    error_list += f"\n  ... and {len(conflicting_readonly_files) - 10} more {file_string(len(conflicting_readonly_files) - 10)}"
                show_styled_warning(
                    mw,
                    "Permission Error",
                    f"Cannot rename files because some existing files with conflicting names are read-only:\n\n{error_list}\n\n"
                    "These files would need to be moved to make room for the renamed files, but they cannot be renamed.\n\n"
                    "Please check file permissions and try again."
                )
                restart_background_loading()
                return
            
            rename_plan = self._build_efficient_rename_plan(
                target_mappings, target_directory, temp_prefix, progress_callback=plan_progress_callback
            )
            if not rename_plan:
                progress_dialog.close()
                show_styled_warning(
                    mw,
                    "Rename Planning Failed",
                    "Failed to create rename plan. Please try again."
                )
                restart_background_loading()
                return
            
            # Verify we have operations to perform
            phase0_ops = len(rename_plan.get('phase0', []))
            phase1_ops = len(rename_plan['phase1'])
            phase2_ops = len(rename_plan['phase2'])
            if phase0_ops == 0 and phase1_ops == 0 and phase2_ops == 0:
                progress_dialog.close()
                mw.status_notification.show_message("No files need renaming")
                restart_background_loading()
                return
            
            rename_map = {src: tgt for src, tgt in target_mappings}
            # Initialize rename_map_dict for feature restoration (may be empty if no renames)
            rename_map_dict = rename_map
            phase0_ops = len(rename_plan.get('phase0', []))
            phase1_ops = len(rename_plan['phase1'])
            phase2_ops = len(rename_plan['phase2'])
            total_operations = phase0_ops + phase1_ops + phase2_ops
            # Update progress dialog with actual total operations
            progress_dialog.setMaximum(total_operations)
            progress_dialog.setValue(0)
            progress_dialog.setLabelText("Renaming files...")
            QApplication.processEvents()

            # CRITICAL: Collect metadata BEFORE rename (old paths won't exist after rename)
            # This allows us to migrate metadata to new paths after rename completes
            pre_rename_metadata = {}
            if hasattr(mw, 'cache_manager') and mw.cache_manager and rename_map:
                try:
                    for old_path in rename_map.keys():
                        if old_path != rename_map[old_path] and os.path.exists(old_path):
                            # Get metadata for old path (before rename)
                            metadata = mw.cache_manager.get_metadata_sync(old_path)
                            if metadata:
                                pre_rename_metadata[old_path] = metadata
                except Exception:
                    pass  # Don't fail if metadata collection has issues

            completed_renames = []
            rename_errors = []  # Collect all rename errors
            # Collect paths to clear from cache - batch clear after rename completes to reduce mutex contention
            paths_to_clear_cache = []
            try:
                # Phase 0: Move conflicting existing files to temp names
                for idx, (source_path, target_path) in enumerate(rename_plan.get('phase0', [])):
                    progress_dialog.setValue(idx)
                    progress_dialog.setLabelText(
                        f"Moving conflicting file {elide_progress_filename(os.path.basename(source_path))}..."
                    )
                    QApplication.processEvents()
                    if source_path == target_path:
                        continue
                    try:
                        os.rename(source_path, target_path)
                        completed_renames.append((target_path, source_path))
                        # Collect path for cache clearing (batch later)
                        paths_to_clear_cache.append(source_path)
                    except Exception as e:
                        rename_errors.append(f"Failed to move conflicting file {os.path.basename(source_path)}: {str(e)}")
                
                # Phase 1: Rename sources to temp names
                for idx, (source_path, target_path) in enumerate(rename_plan['phase1']):
                    progress_dialog.setValue(phase0_ops + idx)
                    progress_dialog.setLabelText(
                        f"Renaming {elide_progress_filename(os.path.basename(source_path))}..."
                    )
                    QApplication.processEvents()
                    if source_path == target_path:
                        continue
                    try:
                        os.rename(source_path, target_path)
                        completed_renames.append((target_path, source_path))
                        # Collect path for cache clearing (batch later)
                        paths_to_clear_cache.append(source_path)
                    except Exception as e:
                        rename_errors.append(f"Failed to rename {os.path.basename(source_path)}: {str(e)}")
                
                # Phase 2: Rename temps to final names
                for idx, (temp_path, final_path) in enumerate(rename_plan['phase2']):
                    progress_dialog.setValue(phase0_ops + phase1_ops + idx)
                    progress_dialog.setLabelText(
                        f"Finalizing {elide_progress_filename(os.path.basename(final_path))}..."
                    )
                    QApplication.processEvents()
                    if temp_path == final_path:
                        continue
                    try:
                        os.rename(temp_path, final_path)
                        original_path = None
                        for curr_path, orig_path in completed_renames:
                            if curr_path == temp_path:
                                original_path = orig_path
                                break
                        if original_path:
                            completed_renames = [(p, orig) for p, orig in completed_renames if p != temp_path]
                            completed_renames.append((final_path, original_path))
                        # Collect path for cache clearing (batch later instead of clearing immediately)
                        paths_to_clear_cache.append(final_path)
                    except Exception as e:
                        rename_errors.append(f"Failed to rename {os.path.basename(temp_path)} to {os.path.basename(final_path)}: {str(e)}")
            except Exception as e:
                rename_errors.append(f"Unexpected error during rename: {str(e)}")
            finally:
                # Stop at 99% to allow message update before cache flush
                if total_operations > 0:
                    progress_dialog.setValue(total_operations - 1)
                else:
                    progress_dialog.setValue(0)
            # Don\'t close progress dialog yet - keep it open for cache flush
            # Update message and prepare progress bar for cache flush
            if total_operations > 0:
                progress_dialog.setMaximum(total_operations + 1)  # Increase max to accommodate cache flush
                progress_dialog.setValue(total_operations - 1)  # Set to 98% of new max to allow "Writing metadata" message to show at 99%
            QApplication.processEvents()

            # Show error message if any renames failed
            # Show error message if any renames failed
            if rename_errors:
                error_list = "\n".join([f"  • {error}" for error in rename_errors[:10]])
                if len(rename_errors) > 10:
                    error_list += f"\n  ... and {len(rename_errors) - 10} more error(s)"
                
                # Attempt rollback of completed renames
                rollback_errors = []
                for current_path, original_path in reversed(completed_renames):
                    try:
                        if os.path.exists(current_path) and current_path != original_path:
                            os.rename(current_path, original_path)
                    except Exception as e:
                        rollback_errors.append(f"Failed to rollback {os.path.basename(current_path)}: {str(e)}")
                
                rollback_msg = ""
                if rollback_errors:
                    rollback_msg = f"\n\nRollback errors:\n" + "\n".join([f"  • {err}" for err in rollback_errors[:5]])
                    if len(rollback_errors) > 5:
                        rollback_msg += f"\n  ... and {len(rollback_errors) - 5} more"
                
                show_styled_critical(
                    mw,
                    "Rename Failed",
                    f"Some rename operations failed:\n\n{error_list}{rollback_msg}"
                )
                restart_background_loading()
                return
            
            # CRITICAL: Migrate metadata cache from old paths to new paths
            # This ensures clip search and other features can find metadata after rename
            # Cache keys include path, so old cache entries won't be found with new paths
            # We collected pre_rename_metadata before rename, now migrate it to new paths
            if hasattr(mw, 'cache_manager') and mw.cache_manager and rename_map:
                try:
                    from cache.image_cache import ImageMetadata
                    from PySide6.QtCore import QMutexLocker
                    metadata_migrations = []
                    
                    # Progress update
                    progress_dialog.setLabelText("Migrating metadata cache...")
                    QApplication.processEvents()
                    
                    old_paths_to_clear = []
                    for old_path, new_path in rename_map.items():
                        if old_path == new_path:
                            continue  # Skip if no rename happened
                        
                        # Get metadata we collected before rename
                        if old_path in pre_rename_metadata:
                            old_metadata = pre_rename_metadata[old_path]
                            
                            if old_metadata and os.path.exists(new_path):
                                try:
                                    # Get new mtime and size for the renamed file
                                    stat = os.stat(new_path)
                                    new_mtime = stat.st_mtime
                                    new_size = stat.st_size
                                    source_dir = os.path.dirname(os.path.abspath(new_path))
                                    
                                    # Create updated metadata with new path info
                                    updated_metadata = old_metadata._replace(
                                        filename=os.path.basename(new_path),
                                        modified_time=new_mtime,
                                        file_size=new_size,
                                        source_directory=source_dir
                                    )
                                    
                                    # Add to migration batch
                                    metadata_migrations.append((new_path, updated_metadata))
                                    
                                    old_paths_to_clear.append(old_path)
                                    
                                except Exception:
                                    pass  # Skip if we can't get stat
                        else:
                            old_paths_to_clear.append(old_path)
                    
                    # Batch clear old cache entries (avoids N listdirs and N*O(cache_size) work)
                    if old_paths_to_clear:
                        mw.cache_manager.clear_cache_for_files_batch(old_paths_to_clear)
                    
                    # Batch migrate all metadata to new paths
                    if metadata_migrations:
                        mw.cache_manager.cache_metadata_batch_sync(metadata_migrations, defer_save=True)
                    
                except Exception as e:
                    # Don't fail rename if metadata migration has issues
                    print(f"Warning: Failed to migrate metadata cache after rename: {e}")
                    traceback.print_exc()
            
            # Preserve lock status after rename - update .prsort file with new filenames
            if hasattr(mw, 'lock_manager') and mw.lock_manager:
                try:
                    # Build mapping of old filename -> new filename
                    old_to_new = {}
                    for old_path, new_path in target_mappings:
                        old_filename = os.path.basename(old_path)
                        new_filename = os.path.basename(new_path)
                        old_to_new[old_filename] = new_filename
                    
                    # CRITICAL RULE: .prsort is ONLY used to:
                    # 1. Determine which files are locked (via lock markers '*')
                    # 2. Get the ORDER of locked files (from .prsort file order)
                    # .prsort is NEVER used to order unlocked files!
                    # Unlocked files ALWAYS preserve their current visual order
                    
                    # Get current locked files (as set for membership testing)
                    # We ONLY read .prsort to determine which files are locked, NOT to order unlocked files
                    locked_files = mw.lock_manager.get_locked_files(target_directory)
                    
                    # Update locked files list with new filenames - PRESERVE ORDER from .prsort
                    # CRITICAL: This is the ONLY valid use of .prsort for ordering - locked files only!
                    # Use list, not set, to preserve order of locked files from .prsort
                    new_locked_files_list = []
                    new_locked_files_set = set()  # For fast membership testing only
                    
                    # Get locked files in their saved order from .prsort
                    # CRITICAL: We ONLY use .prsort to get the order of LOCKED files, NOT unlocked files
                    prsort_result = mw.sorting_manager._read_prsort_file(target_directory)
                    if prsort_result:
                        prsort_filenames, _, _ = prsort_result
                        # Map old locked filenames to new filenames in .prsort order
                        # This preserves the order of locked files from .prsort (the ONLY valid use)
                        for old_filename in prsort_filenames:
                            if old_filename in locked_files:
                                if old_filename in old_to_new:
                                    new_filename = old_to_new[old_filename]
                                else:
                                    new_filename = old_filename  # File wasn't renamed
                                if new_filename not in new_locked_files_set:
                                    new_locked_files_list.append(new_filename)
                                    new_locked_files_set.add(new_filename)
                    
                    # Add any locked files not in .prsort (shouldn't happen, but be safe)
                    for old_filename in locked_files:
                        if old_filename in old_to_new:
                            new_filename = old_to_new[old_filename]
                        else:
                            new_filename = old_filename
                        if new_filename not in new_locked_files_set:
                            new_locked_files_list.append(new_filename)
                            new_locked_files_set.add(new_filename)
                    
                    # Keep set for membership testing, but use list for order
                    new_locked_files = new_locked_files_set  # For membership testing
                    new_locked_files_ordered = new_locked_files_list  # For preserving order
                    
                    # Update .prsort file with new lock status and order
                    # CRITICAL: Use locked_files_order (preserved BEFORE rename) to get correct locked file order
                    # Map old paths to new paths while preserving locked file order
                    old_to_new_path = {old: new for old, new in target_mappings}
                    
                    # Build locked files list in their saved order (from locked_files_order)
                    # CRITICAL: locked_files_order contains OLD paths in their correct order from .prsort
                    # CRITICAL: Use lists, not sets, to preserve order!
                    locked_new_paths = []
                    locked_new_paths_set = set()  # For fast membership testing only
                    
                    if locked_files_order:
                        for old_locked_path in locked_files_order:
                            # Map old path to new path
                            new_locked_path = old_to_new_path.get(old_locked_path)
                            if new_locked_path and os.path.exists(new_locked_path):
                                if new_locked_path not in locked_new_paths_set:
                                    locked_new_paths.append(new_locked_path)
                                    locked_new_paths_set.add(new_locked_path)
                    
                    # Fallback: if locked_files_order wasn't set or mapping failed, use new_locked_files_ordered
                    if not locked_new_paths and new_locked_files_ordered:
                        # Build filename to path mapping
                        filename_to_new_path = {}
                        for old_path, new_path in target_mappings:
                            new_filename = os.path.basename(new_path)
                            filename_to_new_path[new_filename] = new_path
                        
                        # Use new_locked_files_ordered to preserve order from .prsort
                        for new_filename in new_locked_files_ordered:
                            if new_filename in filename_to_new_path:
                                new_path = filename_to_new_path[new_filename]
                                if new_path not in locked_new_paths_set:
                                    locked_new_paths.append(new_path)
                                    locked_new_paths_set.add(new_path)
                    
                    # Build unlocked files list - preserve order from images_to_rename, excluding locked files
                    unlocked_new_paths = []
                    unlocked_new_paths_set = set()  # For fast membership testing only
                    
                    for old_path in images_to_rename:
                        new_path = old_to_new_path.get(old_path, old_path)
                        new_filename = os.path.basename(new_path)
                        # Only add if it's not locked and not already added
                        if new_filename not in new_locked_files and new_path not in locked_new_paths_set:
                            if os.path.exists(new_path) and new_path not in unlocked_new_paths_set:
                                unlocked_new_paths.append(new_path)
                                unlocked_new_paths_set.add(new_path)
                    
                    # Add any renamed files not in images_to_rename (shouldn't happen, but be safe)
                    for old_path, new_path in target_mappings:
                        new_filename = os.path.basename(new_path)
                        if new_path not in locked_new_paths_set and new_path not in unlocked_new_paths_set:
                            if new_filename in new_locked_files:
                                locked_new_paths.append(new_path)
                                locked_new_paths_set.add(new_path)
                            else:
                                unlocked_new_paths.append(new_path)
                                unlocked_new_paths_set.add(new_path)
                    
                    # CRITICAL: Combine with locked files first (in their saved order), then unlocked files
                    # This ensures locked files are ALWAYS at the top in the .prsort file
                    new_filenames_order = locked_new_paths + unlocked_new_paths
                    
                    # CRITICAL: Always write is_reversed=False to preserve exact order
                    # Locked files are at top in their saved order - don't reverse!
                    is_reversed = False
                    
                    # Write updated .prsort with new filenames and lock status directly
                    # Use _save_current_order_with_locks to write both order and lock markers in one operation
                    # This ensures atomic update and prevents race conditions
                    success = mw.lock_manager._save_current_order_with_locks(
                        target_directory,
                        new_filenames_order,
                        new_locked_files,
                        is_reversed
                    )
                    
                    if not success:
                        print(f"WARNING: Failed to write .prsort file with lock status after rename")
                    
                    # CRITICAL: Force file system sync to ensure .prsort file is written to disk
                    # before deferred_refresh reads it
                    # NOTE: os is already imported at module level, don't import it here
                    prsort_path = os.path.join(target_directory, '.prsort')
                    if os.path.exists(prsort_path):
                        # Force sync to ensure file is written
                        with open(prsort_path, 'r') as f:
                            f.flush()
                            os.fsync(f.fileno())
                    time.sleep(0.05)  # Increased delay to ensure file system has fully flushed
                    
                except Exception as e:
                    print(f"Error preserving lock status after rename: {e}")
                    traceback.print_exc()

            # ---- Reset file dates if requested ----
            # Set mtimes based on date_change_mode:
            # - "oldest": First file (0001) should be oldest, last file (highest number) should be newest
            # - "newest": First file (0001) should be newest, last file (highest number) should be oldest
            # - "none": Don't change dates
            # NOTE: If sort_mode == "date", dates were already set before sorting on original files.
            # But after rename, files have new paths, so we need to set dates again on the new paths.
            # The dates should match the final order (by sequence number in filename).
            # NOTE: If sort_mode == "order", dates were already set based on displayed order position.
            # After rename, files have new paths, so we need to set dates again on the new paths.
            # The dates should match the original displayed order (by position in images_to_rename before reversal).
            if date_change_mode in ('oldest', 'newest') and target_mappings:
                now = int(time.time())
                
                if sort_mode == "order" and original_displayed_order is not None:
                    # When sorting by current order, use original displayed order position
                    # Create mapping from old_path to displayed order position
                    old_path_to_displayed_idx = {}
                    for displayed_idx, old_path in enumerate(original_displayed_order):
                        old_path_to_displayed_idx[old_path] = displayed_idx
                    
                    total_files = len(original_displayed_order)
                    
                    # Set dates based on displayed order position
                    for old_path, new_path in target_mappings:
                        if os.path.exists(new_path) and old_path in old_path_to_displayed_idx:
                            displayed_idx = old_path_to_displayed_idx[old_path]
                            try:
                                # Get current date before changing it
                                old_mtime = os.path.getmtime(new_path)
                                
                                if date_change_mode == 'oldest':
                                    # First image (displayed_idx=0, "top") gets oldest timestamp: now - (total_files - 1)
                                    # Last image gets newest timestamp: now
                                    new_mtime = now - (total_files - 1 - displayed_idx)
                                else:  # date_change_mode == 'newest'
                                    # First image (displayed_idx=0, "top") gets newest timestamp: now
                                    # Last image gets oldest timestamp: now - (total_files - 1)
                                    new_mtime = now - displayed_idx
                                
                                # Only set date if it's different
                                if abs(old_mtime - new_mtime) > 1:
                                    os.utime(new_path, (new_mtime, new_mtime))
                                
                                # Update cache
                                if hasattr(mw, 'cache_manager') and mw.cache_manager:
                                    try:
                                        from cache.image_cache import ImageMetadata
                                        existing_metadata = mw.cache_manager.get_metadata_sync(new_path)
                                        if existing_metadata:
                                            updated_metadata = existing_metadata._replace(modified_time=new_mtime)
                                            mw.cache_manager.cache_metadata_sync(new_path, updated_metadata)
                                    except Exception:
                                        pass
                            except Exception as e:
                                print(f"  ERROR setting date for {os.path.basename(new_path)}: {e}")
                                traceback.print_exc()
                elif sort_mode == "date":
                    # When sorting by date, use sequence numbers from filenames
                    # Extract sequence numbers from final filenames to sort by sequence
                    def get_sequence_number(target_path):
                        basename = os.path.basename(target_path)
                        match = re.search(rf'{re.escape(prefix)}-(\d+)(\.[^.]+)?$', basename)
                        if match:
                            return int(match.group(1))
                        return 999999
                    
                    # CRITICAL: Set dates for ALL files in target_mappings, not just renamed ones
                    # Sort ALL target_mappings by final sequence number
                    all_files_sorted = sorted(target_mappings, key=lambda x: get_sequence_number(x[1]))
                    total_files = len(all_files_sorted)
                    
                    if total_files > 0:
                        # Update progress dialog to show we're updating metadata
                        progress_dialog.setLabelText("Updating file dates and metadata...")
                        QApplication.processEvents()
                        
                        # Batch metadata updates for better performance
                        metadata_updates = []
                        BATCH_SIZE = 50  # Process metadata updates in batches
                        
                        # Iterate over ALL files in sequence order and set dates
                        # Use sequence number position (0-based from sequence number) not enumerate index
                        for idx, mapping in enumerate(all_files_sorted):
                            # Update progress every 10 files
                            if idx % 10 == 0:
                                progress_dialog.setValue(total_operations - 1 + int((idx / total_files) * 0.5))
                                QApplication.processEvents()
                            
                            old_path, new_path = mapping
                            if os.path.exists(new_path):
                                try:
                                    # Get sequence number to determine date position
                                    seq_num = get_sequence_number(new_path)
                                    # Calculate position: sequence number - starting_number (0-based)
                                    seq_position = seq_num - starting_number
                                    # Clamp to valid range
                                    if seq_position < 0:
                                        seq_position = 0
                                    if seq_position >= total_files:
                                        seq_position = total_files - 1
                                    
                                    old_mtime = os.path.getmtime(new_path)
                                    if date_change_mode == 'oldest':
                                        # First file (seq 0001, position 0) gets oldest timestamp: now - (total_files - 1)
                                        # Last file gets newest timestamp: now
                                        # Each file is 1 second newer than the previous
                                        new_mtime = now - (total_files - 1 - seq_position)
                                    else:  # date_change_mode == 'newest'
                                        # First file (seq 0001, position 0) gets newest timestamp: now
                                        # Last file gets oldest timestamp: now - (total_files - 1)
                                        # Each file is 1 second older than the previous
                                        new_mtime = now - seq_position
                                    
                                    # Only set date if it's different
                                    if abs(old_mtime - new_mtime) > 1:
                                        # Set both atime and mtime to the same value
                                        os.utime(new_path, (new_mtime, new_mtime))
                                        
                                        # Verify the date was set correctly
                                        actual_mtime = os.path.getmtime(new_path)
                                        if abs(actual_mtime - new_mtime) > 1:
                                            # Date wasn't set correctly - try again
                                            os.utime(new_path, (new_mtime, new_mtime))
                                            actual_mtime = os.path.getmtime(new_path)
                                    else:
                                        # Date didn't change, use existing mtime
                                        actual_mtime = old_mtime
                                    
                                    # CRITICAL: Update cache metadata with new date BEFORE refresh
                                    # This ensures cache matches disk, preventing mismatch issues
                                    # (See GIL_DEADLOCK_FIX.md - cache must be up to date before refresh)
                                    # Batch metadata updates for better performance
                                    if hasattr(mw, 'cache_manager') and mw.cache_manager:
                                        try:
                                            # Import ImageMetadata
                                            try:
                                                from cache.image_cache import ImageMetadata
                                            except ImportError:
                                                ImageMetadata = None
                                            
                                            if ImageMetadata:
                                                # Get existing metadata or create new
                                                existing_metadata = mw.cache_manager.get_metadata_sync(new_path)
                                                if existing_metadata:
                                                    # Update modified_time in existing metadata
                                                    updated_metadata = existing_metadata._replace(
                                                        modified_time=actual_mtime,
                                                        filename=os.path.basename(new_path)
                                                    )
                                                    metadata_updates.append((new_path, updated_metadata))
                                                else:
                                                    # No existing metadata - create new with correct date
                                                    try:
                                                        stat = os.stat(new_path)
                                                        source_dir = os.path.dirname(os.path.abspath(new_path))
                                                        new_metadata = ImageMetadata(
                                                            filename=os.path.basename(new_path),
                                                            file_size=stat.st_size,
                                                            modified_time=actual_mtime,
                                                            source_directory=source_dir,
                                                            width=0,
                                                            height=0,
                                                            exif_taken_time=None
                                                        )
                                                        metadata_updates.append((new_path, new_metadata))
                                                    except Exception:
                                                        pass  # If we can't create metadata, skip
                                                
                                                # Batch update metadata every BATCH_SIZE items
                                                if len(metadata_updates) >= BATCH_SIZE:
                                                    try:
                                                        mw.cache_manager.cache_metadata_batch_sync(metadata_updates, defer_save=True)
                                                        metadata_updates = []
                                                    except Exception:
                                                        pass  # Don't fail if batch update has issues
                                        except Exception:
                                            pass  # Don't fail if cache update has issues
                                except Exception as e:
                                    # Print error for debugging but don't fail the rename
                                    print(f"Error setting date for {new_path}: {e}")
                                    traceback.print_exc()
                                    pass  # If permission denied or file missing, skip
                        
                        # Process remaining metadata updates
                        if metadata_updates and hasattr(mw, 'cache_manager') and mw.cache_manager:
                            try:
                                mw.cache_manager.cache_metadata_batch_sync(metadata_updates, defer_save=True)
                            except Exception:
                                pass
                        
                        # Final progress update
                        progress_dialog.setValue(total_operations - 1)
                        QApplication.processEvents()

            # ---- Restore features AFTER date changes (so mtime matches final state) ----
            # CRITICAL: Ensure date changes are fully committed to filesystem before restoring features
            # This prevents cache mismatches where restored features have different mtime than file on disk
            time.sleep(0.1)  # Small delay to ensure filesystem has committed date changes
            # Also sync filesystem if possible (on Unix-like systems)
            try:
                import subprocess
                # Try to sync filesystem (may require permissions, so wrap in try/except)
                subprocess.run(['sync'], timeout=1, check=False)
            except Exception:
                pass  # If sync fails, continue anyway - the delay should be sufficient
            
            if settings.get('preserve_features_on_rename', True):
                try:
                    if rename_map:
                        # Progress dialog is still open - use it to show cache flush progress
                        def post_progress_callback(current, total, message):
                            # Process events during hash collection
                            QApplication.processEvents()
                        
                        def flush_progress_callback(message):
                            # Update progress dialog during cache flush
                            progress_dialog.setLabelText(message)
                            progress_dialog.setMaximum(total_operations + 1)  # Increase max to prevent auto-close
                            progress_dialog.setValue(total_operations + 1)  # Set to 100% when flushing
                            progress_dialog.show()  # Ensure dialog stays visible
                            QApplication.processEvents()
                        
                        post_rename_data = self._collect_post_rename_hashes(rename_map, progress_callback=post_progress_callback)
                        # Update progress bar message before starting cache flush
                        progress_dialog.setLabelText("Writing metadata to disk")
                        progress_dialog.setMaximum(total_operations + 1)  # Ensure max is increased
                        progress_dialog.setValue(total_operations)  # Set to 99% of new max
                        QApplication.processEvents()
                        restored_count = self._restore_features_via_md5(pre_rename_data, post_rename_data, rename_map, flush_progress_callback=flush_progress_callback)
                        if restored_count > 0:
                            mw.status_notification.show_message(f"Preserved features for {restored_count} files")

                        def face_progress_message(msg):
                            progress_dialog.setLabelText(msg)
                            QApplication.processEvents()

                        self._migrate_face_metadata_after_rename(
                            pre_rename_data,
                            post_rename_data,
                            rename_map,
                            progress_message_callback=face_progress_message,
                        )
                except (NameError, UnboundLocalError) as e:
                    # rename_map not defined, skip feature restoration
                    pass
                except Exception as e:
                    traceback.print_exc()
            
            # Close progress dialog after cache flush completes
            # Save all deferred metadata updates once at the end of rename operation
            if hasattr(mw, 'cache_manager') and mw.cache_manager:
                try:
                    mw.cache_manager.save_metadata_cache(force=True)
                except Exception:
                    pass  # Don't fail if save has issues
            
            progress_dialog.close()
            QApplication.processEvents()

            # Schedule naming-consistency check after all renames in this batch complete
            if hasattr(mw, 'schedule_rename_status_check_after_rename'):
                mw.schedule_rename_status_check_after_rename(target_directory)

            # ---- CRITICAL: Update active image to its new name after rename ----
            # Do this BEFORE deferred_refresh so it happens immediately, regardless of code path
            rename_map_dict = {old: new for old, new in target_mappings if old != new}
            
            # CRITICAL: Determine the new name of the active image
            # This will be passed to highlight functions to preserve the active image after rename
            new_active_path = None
            if hilighted_path and hilighted_path in rename_map_dict:
                new_active_path = rename_map_dict[hilighted_path]
                if os.path.exists(new_active_path):
                    # Update current_image_path to the new name (source of truth)
                    if hasattr(mw, 'set_current_image_by_path'):
                        mw.set_current_image_by_path(new_active_path, fallback_index=0)
                    else:
                        mw.current_image_path = new_active_path
            
            # ---- CRITICAL: Highlight appropriate item after rename ----
            # Pass rename_map and preferred_path so we can preserve the renamed active image
            # This will prioritize the renamed active image if it exists and is not locked
            self._highlight_first_non_locked_after_rename(mw, target_directory, rename_map_dict, preferred_path=new_active_path)

            # Defer refresh to avoid blocking during rename
            # Note: Cache invalidation is not necessary - the cache key mechanism (which includes mtime)
            # automatically handles changes. When mtime or path changes, cache keys change, causing
            # cache misses which trigger automatic thumbnail regeneration.
            def deferred_refresh():
                try:
                    # Build mapping of old -> new paths for order preservation
                    rename_map_dict = {old: new for old, new in target_mappings if old != new}
                    
                    # Store the order from target_mappings BEFORE refresh
                    # target_mappings is in the order files were renamed (may be reversed if order_direction == "bottom")
                    preserved_order = [new_path for old_path, new_path in target_mappings]
                    
                    # CRITICAL: When sort_mode is "order", preserve the exact visual order
                    # Update displayed_images and canvas directly - don't rely on .prsort or refresh_directory
                    if sort_mode == "order":
                        # CRITICAL: Use original_displayed_order (before reversal) for display, not preserved_order
                        # preserved_order may be reversed if order_direction == "bottom", but display should stay the same
                        # Map original displayed order (old paths) to new paths
                        final_order = []
                        if original_displayed_order:
                            for old_path in original_displayed_order:
                                new_path = rename_map_dict.get(old_path, old_path)
                                if os.path.exists(new_path) and new_path not in final_order:
                                    final_order.append(new_path)
                        
                        # Add any files from preserved_order that weren't in original_displayed_order
                        # (shouldn't happen, but be safe)
                        for new_path in preserved_order:
                            if os.path.exists(new_path) and new_path not in final_order:
                                final_order.append(new_path)
                        
                        # CRITICAL: Ensure final_order contains ALL files in the directory (not just renamed ones)
                        # This is important because locked files might not have been renamed
                        try:
                            all_files_in_dir = []
                            if os.path.isdir(target_directory):
                                for filename in os.listdir(target_directory):
                                    file_path = os.path.join(target_directory, filename)
                                    if os.path.isfile(file_path) and file_path not in final_order:
                                        # Check if it's an image file
                                        if get_file_extension(filename) in get_image_extensions():
                                            all_files_in_dir.append(file_path)
                            # Add any missing files to final_order (preserve their relative order)
                            for file_path in all_files_in_dir:
                                if file_path not in final_order:
                                    final_order.append(file_path)
                        except Exception:
                            pass  # If we can't list directory, continue with what we have
                        
                        # Apply filter pattern
                        if hasattr(self.main_window, 'filter_pattern') and self.main_window.filter_pattern:
                            final_order = self.main_window.sorting_manager.filter_images_by_pattern(final_order)
                        # CRITICAL: When sort_mode == "order", preserve exact visual order
                        # BUT: Always ensure locked files are at top using centralized function
                        # Force a delay to ensure .prsort file has been written and flushed
                        time.sleep(0.15)  # Increased delay to ensure .prsort file is fully written and available
                        
                        # CRITICAL RULE: .prsort is ONLY used to:
                        # 1. Determine which files are locked (via lock markers '*')
                        # 2. Get the ORDER of locked files (from .prsort file order)
                        # .prsort is NEVER used to order unlocked files!
                        # Unlocked files ALWAYS preserve their current visual order
                        
                        # CRITICAL: Re-read lock status from .prsort to ensure we have the latest state
                        # This is important because unlock operations might have happened before rename
                        # We ONLY read .prsort to determine which files are locked, NOT to order unlocked files
                        # Force a fresh read of .prsort file to get current lock status
                        current_locked_files = set()
                        if hasattr(mw, 'lock_manager') and mw.lock_manager:
                            current_locked_files = mw.lock_manager.get_locked_files(target_directory)
                        
                        # CRITICAL: Use centralized _separate_locked_unlocked to ensure locked files are at top
                        # This MUST happen - locked files must be at top after rename
                        # ALWAYS call _separate_locked_unlocked if there are locked files, even if final_order seems correct
                        if final_order:
                            if current_locked_files:
                                # There are locked files - MUST separate them to top
                                locked_paths, unlocked_paths = mw.sorting_manager._separate_locked_unlocked(final_order)
                                final_order = locked_paths + unlocked_paths
                                
                                # VERIFY: Ensure locked files are actually at the top
                                if final_order and len(locked_paths) > 0:
                                    # Check if first file is locked
                                    first_basename = os.path.basename(final_order[0])
                                    if first_basename not in current_locked_files:
                                        # Locked files weren't moved to top - force fix by re-separating
                                        locked_paths, unlocked_paths = mw.sorting_manager._separate_locked_unlocked(final_order)
                                        final_order = locked_paths + unlocked_paths
                                        # Double-check after fix
                                        if final_order:
                                            first_basename_after = os.path.basename(final_order[0])
                                            if first_basename_after not in current_locked_files and len(locked_paths) > 0:
                                                # Still not correct - this indicates a bug in _separate_locked_unlocked
                                                # Force locked files to top manually as last resort
                                                locked_manual = []
                                                unlocked_manual = []
                                                for path in final_order:
                                                    basename = os.path.basename(path)
                                                    if basename in current_locked_files:
                                                        locked_manual.append(path)
                                                    else:
                                                        unlocked_manual.append(path)
                                                # Get locked files in their .prsort order
                                                prsort_result = mw.sorting_manager._read_prsort_file(target_directory)
                                                if prsort_result:
                                                    prsort_filenames, _, _ = prsort_result
                                                    filename_to_path = {os.path.basename(p): p for p in locked_manual}
                                                    locked_ordered = []
                                                    locked_ordered_set = set()
                                                    for filename in prsort_filenames:
                                                        if filename in current_locked_files and filename in filename_to_path:
                                                            path = filename_to_path[filename]
                                                            if path not in locked_ordered_set:
                                                                locked_ordered.append(path)
                                                                locked_ordered_set.add(path)
                                                    # Add any remaining locked files
                                                    for path in locked_manual:
                                                        if path not in locked_ordered_set:
                                                            locked_ordered.append(path)
                                                    final_order = locked_ordered + unlocked_manual
                                                else:
                                                    final_order = locked_manual + unlocked_manual
                        
                        # CRITICAL: Update displayed_images FIRST with locked files at top
                        if hasattr(mw, '_set_displayed_images_with_sync'):
                            mw._set_displayed_images_with_sync(final_order, sync=True)
                        else:
                            mw.displayed_images = final_order
                        
                        # VERIFY: displayed_images must have locked files at top - fix if needed
                        if mw.displayed_images and current_locked_files:
                            num_locked = len(current_locked_files)
                            # Check if locked files are at top
                            locked_at_top = True
                            for i in range(min(num_locked, len(mw.displayed_images))):
                                basename = os.path.basename(mw.displayed_images[i])
                                if basename not in current_locked_files:
                                    locked_at_top = False
                                    break
                            
                            if not locked_at_top:
                                # Fix it immediately - re-separate and update
                                locked_paths, unlocked_paths = mw.sorting_manager._separate_locked_unlocked(mw.displayed_images)
                                final_order = locked_paths + unlocked_paths
                                if hasattr(mw, '_set_displayed_images_with_sync'):
                                    mw._set_displayed_images_with_sync(final_order, sync=True)
                                else:
                                    mw.displayed_images = final_order
                        
                        # Populate indices arrays
                        if hasattr(mw, 'populate_indices_arrays'):
                            mw.populate_indices_arrays()
                        
                        # Update canvas - MUST use final_order (locked files at top)
                        if hasattr(mw, 'thumbnail_container') and mw.thumbnail_container:
                            canvas = mw.thumbnail_container.canvas
                            if canvas:
                                # Update thumbnail paths
                                if hasattr(canvas, 'thumbnails'):
                                    for thumb in canvas.thumbnails:
                                        if hasattr(thumb, 'image_path') and thumb.image_path in rename_map_dict:
                                            thumb.image_path = rename_map_dict[thumb.image_path]
                                
                                # CRITICAL: Reorder using final_order (locked files at top)
                                if hasattr(canvas, 'reorder_thumbnails'):
                                    canvas.reorder_thumbnails(final_order, force_recalculate_grid=True)
                                
                                # Force repaint
                                if hasattr(canvas, 'needs_repaint'):
                                    canvas.needs_repaint = True
                                if hasattr(canvas, 'update'):
                                    canvas.update()
                        
                        # Clear selections
                        if hasattr(mw, 'selected_files'):
                            mw.selected_files.clear()
                        if hasattr(mw, '_emit_selection_changed'):
                            mw._emit_selection_changed()
                        
                        # Highlight 1st non-locked item directly
                        # CRITICAL: displayed_images already has NEW paths (we just set final_order)
                        # So we should NOT pass rename_map - the paths are already correct
                        # Pass None for rename_map since displayed_images already has new paths
                        # But pass preferred_path to preserve the renamed active image
                        self._highlight_first_non_locked_after_rename(mw, target_directory, rename_map=None, preferred_path=new_active_path)
                        
                        # Skip refresh_directory - we've already updated displayed_images and canvas directly
                        restart_background_loading()
                        return
                    
                    # For other sort modes, use refresh_directory as before
                    # CRITICAL: If locked files exist, use refresh_directory instead of load_directory
                    # refresh_directory is safer and won't cause segfaults
                    if hasattr(mw, 'lock_manager') and mw.lock_manager:
                        locked_files = mw.lock_manager.get_locked_files(target_directory)
                        if locked_files:
                            # Use refresh_directory instead of load_directory to avoid segfault
                            # Set sort mode to CUSTOM first to ensure locked files are at top
                            try:
                                from sort_mode import SortMode
                                mw.current_sort_mode = SortMode.CUSTOM
                            except Exception:
                                pass
                            
                            # Use refresh_directory which is safer than load_directory
                            if hasattr(mw, 'refresh_directory'):
                                # CRITICAL: Clear current_image_path BEFORE refresh to prevent preserving old highlighted image
                                if hasattr(mw, 'current_image_path'):
                                    mw.current_image_path = None
                                if hasattr(mw, 'highlight_index'):
                                    mw.highlight_index = 0
                                
                                # Clear selections BEFORE refresh - CRITICAL
                                if hasattr(mw, 'selected_files'):
                                    mw.selected_files.clear()
                                
                                # Set flag to prevent generate_thumbnails from restoring selections
                                mw._skip_selection_restore_during_refresh = True
                                
                                mw.refresh_directory(force=True)
                                
                                # Clear flag
                                mw._skip_selection_restore_during_refresh = False
                                
                                # Clear selections after refresh and highlight appropriate thumbnail
                                if hasattr(mw, 'selected_files'):
                                    mw.selected_files.clear()
                                if hasattr(mw, '_emit_selection_changed'):
                                    mw._emit_selection_changed()
                                
                                # CRITICAL: Highlight the 1st non-locked image AFTER refresh completes
                                # Use QTimer to ensure refresh_directory has fully completed
                                def highlight_after_refresh():
                                    # rename_map_dict and new_active_path are captured from outer scope
                                    self._highlight_first_non_locked_after_rename(mw, target_directory, rename_map_dict, preferred_path=new_active_path)
                                QTimer.singleShot(100, highlight_after_refresh)
                                
                                return  # Exit early - refresh already handled everything
                    
                    if hasattr(mw, 'refresh_directory'):
                        # CRITICAL: Clear current_image_path BEFORE refresh to prevent preserving old highlighted image
                        if hasattr(mw, 'current_image_path'):
                            mw.current_image_path = None
                        if hasattr(mw, 'highlight_index'):
                            mw.highlight_index = 0
                        
                        # Clear selections BEFORE refresh - CRITICAL
                        # File paths are the source of truth - clear selected_files
                        if hasattr(mw, 'selected_files'):
                            mw.selected_files.clear()
                        
                        # Set flag to prevent generate_thumbnails from restoring selections
                        mw._skip_selection_restore_during_refresh = True
                        
                        mw.refresh_directory(force=True)
                        
                        # Clear flag
                        mw._skip_selection_restore_during_refresh = False
                        
                        # CRITICAL: Clear selections IMMEDIATELY after refresh_directory returns
                        # refresh_directory calls generate_thumbnails which calls update_canvas_selection
                        # which reads from selected_files. We MUST clear it immediately after refresh.
                        if hasattr(mw, 'selected_files'):
                            mw.selected_files.clear()
                        if hasattr(mw, '_emit_selection_changed'):
                            mw._emit_selection_changed()
                        
                        # CRITICAL: Highlight the 1st non-locked image AFTER refresh completes
                        # Use QTimer to ensure refresh_directory has fully completed
                        def highlight_after_refresh():
                            # rename_map_dict and new_active_path are captured from outer scope
                            self._highlight_first_non_locked_after_rename(mw, target_directory, rename_map_dict, preferred_path=new_active_path)
                        QTimer.singleShot(100, highlight_after_refresh)
                    
                    # Clear selections and highlight appropriate thumbnail after rename
                    # Use multiple attempts to ensure selections stay cleared
                    def clear_and_select(attempt=1):
                        # Clear selections - be absolutely sure they're cleared
                        if hasattr(mw, 'selected_files'):
                            mw.selected_files.clear()
                        
                        # Clear selected_indices directly in canvas
                        if hasattr(mw, 'thumbnail_container') and mw.thumbnail_container:
                            canvas = mw.thumbnail_container.canvas
                            if canvas and hasattr(canvas, 'selected_indices'):
                                canvas.selected_indices.clear()
                        
                        if hasattr(mw, '_emit_selection_changed'):
                            mw._emit_selection_changed()
                        
                        # Check if selections are still there (something restored them)
                        if hasattr(mw, 'selected_files') and mw.selected_files and attempt < 3:
                            # Something restored them - clear again
                            QTimer.singleShot(200, lambda: clear_and_select(attempt + 1))
                            return
                        
                        # Selections are cleared - highlighting will happen after sort mode restoration
                    QTimer.singleShot(500, lambda: clear_and_select(1))
                    
                    # CRITICAL: Clear current_image_path before sort mode restoration
                    # This prevents apply_current_sort from restoring the old highlighted image
                    if hasattr(mw, 'current_image_path'):
                        mw.current_image_path = None
                    if hasattr(mw, 'highlight_index'):
                        mw.highlight_index = 0
                    
                    # Restore original display sort mode after all updates are complete
                    # If it was CUSTOM, change to DATE (newest first) instead
                    if original_display_sort_mode is not None:
                        try:
                            from sort_mode import SortMode
                            if original_display_sort_mode == SortMode.CUSTOM:
                                # Change from CUSTOM to DATE (newest first)
                                # Use set_date_sort if available, otherwise set manually
                                if hasattr(mw, 'set_date_sort'):
                                    mw.set_date_sort(reverse=False)  # newest first
                                else:
                                    mw.current_sort_mode = SortMode.DATE
                                    mw.is_reversed = False  # newest first
                                    # Apply the date sort
                                    if hasattr(mw, '_apply_current_sort'):
                                        mw._apply_current_sort()
                                    if hasattr(mw, 'save_sorting_settings'):
                                        mw.save_sorting_settings()
                                    if hasattr(mw, 'update_sort_menu_checkmarks'):
                                        mw.update_sort_menu_checkmarks()
                                    if hasattr(mw, 'update_status_bar_sections'):
                                        mw.update_status_bar_sections()
                            else:
                                # Restore the original sort mode
                                mw.current_sort_mode = original_display_sort_mode
                                if hasattr(mw, 'update_sort_menu_checkmarks'):
                                    mw.update_sort_menu_checkmarks()
                                if hasattr(mw, 'update_status_bar_sections'):
                                    mw.update_status_bar_sections()
                        except Exception as e:
                            traceback.print_exc()
                    
                    # CRITICAL: Highlight the 1st non-locked image AFTER sort mode restoration
                    # This must happen after sort mode changes because set_date_sort/apply_current_sort
                    # may restore the old highlighted image. We override it here with the correct one.
                    def highlight_after_sort():
                        # rename_map_dict is captured from outer scope
                        self._highlight_first_non_locked_after_rename(mw, target_directory, rename_map_dict)
                    QTimer.singleShot(600, highlight_after_sort)  # After clear_and_select (500ms) + small delay
                    # Note: Don't call debounce_refresh_directory() here - refresh_directory(force=True) already handles the refresh
                    # Calling debounce would schedule another refresh 260ms later which could interfere with the first refresh
                except Exception:
                    traceback.print_exc()
                    pass  # Don't fail if refresh has issues
                
                # CRITICAL: Final highlight at the end of deferred_refresh - ensure 1st non-locked is highlighted
                # This runs after all refresh operations complete
                # rename_map_dict is already defined in this scope
                self._highlight_first_non_locked_after_rename(mw, target_directory, rename_map_dict)
            
            # Use QTimer to defer refresh - prevents blocking the UI thread
            QTimer.singleShot(50, deferred_refresh)
            renamed_count = len([m for m in target_mappings if m[0] != m[1]])
            mw.status_notification.show_message(
                f"Successfully renamed {renamed_count} {file_string(renamed_count)}"
            )

            # Restart background loading after successful completion
            restart_background_loading()
        except Exception as e:
            # Ensure background loading is restarted even on unexpected errors
            restart_background_loading()
            raise

    # ---- All other previously shown methods retained, unchanged... ----
    def quick_mass_rename(self):
        """Quick mass rename: Select all thumbnails and rename with preset options (no dialog).
        Only available when: thumbnail mode and non-specific files mode.
        Uses presets: Sort by Current Order, No date change, Top becomes 1."""
        mw = self.main_window
        
        # Mark cache activity to reset unload timer
        if hasattr(mw, 'cnn_image_similarity_sorter') and mw.cnn_image_similarity_sorter and mw.cnn_image_similarity_sorter.feature_cache:
            mw.cnn_image_similarity_sorter.feature_cache.mark_cache_activity()
        
        # Check if quick mass rename is enabled in settings
        config = get_config()
        settings = config.load_settings()
        allow_quick_mass_rename = settings.get('allow_quick_mass_rename', False)
        if not allow_quick_mass_rename:
            show_styled_warning(
                mw,
                "Quick Mass Rename",
                "Quick Mass Rename is disabled in settings.\n\n"
                "Please enable it in Settings to use this feature.",
            )
            return
        
        # Validate conditions
        if mw.current_view_mode != 'thumbnail':
            show_styled_warning(mw, "Quick Mass Rename", "Quick Mass Rename is only available in thumbnail view")
            return
        
        # Check if in specific files mode
        if getattr(mw, 'specific_files_active', False):
            show_styled_warning(
                mw,
                "Quick Mass Rename",
                "Quick Mass Rename is not available when viewing specific files.\n\n"
                "Please open a directory instead of specific files to use this feature.",
            )
            return
        
        # Select all thumbnails (same as cmd-A)
        mw.select_all_thumbnails()
        
        # Get saved prefix from config, or use default
        config = get_config()
        settings = config.load_settings()
        prefix_template = settings.get('rename_custom_prefix', 'image-%d')
        increment_length = settings.get('rename_increment_length', 5)
        starting_number = settings.get('rename_starting_number', 1)
        
        # Use user's saved settings or hardcoded presets based on constant
        if QUICK_MASS_RENAME_USE_USER_SETTINGS:
            # Use user's last saved settings
            sort_mode = settings.get('rename_sort_mode', 'order')
            date_change_mode = settings.get('rename_date_change_mode', 'none')
            order_direction = settings.get('rename_order_direction', 'top')
            # Handle legacy boolean value for backward compatibility
            if isinstance(date_change_mode, bool):
                date_change_mode = 'oldest' if date_change_mode else 'none'
        else:
            # Use hardcoded presets (will be saved to config)
            sort_mode = 'order'  # Sort by Current Order
            date_change_mode = 'none'  # No change
            order_direction = 'top'  # Top becomes 1
        
        # Call rename_with_custom_prefix with bypass_dialog=True and presets
        self.rename_with_custom_prefix(
            bypass_dialog=True,
            prefix_template=prefix_template,
            increment_length=increment_length,
            starting_number=starting_number,
            sort_mode=sort_mode,
            date_change_mode=date_change_mode,
            order_direction=order_direction
        )
    
    def find_exact_duplicates(self):
        """Set duplicate mode - shows only duplicate files sorted by hash (like random mode)"""
        mw = self.main_window

        if hasattr(mw, 'slideshow2_manager') and mw.current_view_mode == 'slideshow2':
            mw.slideshow2_manager.stop_slideshow2()
        if hasattr(mw, 'slideshow3_manager') and mw.current_view_mode == 'slideshow3':
            mw.slideshow3_manager.stop_slideshow3()

        displayed = mw.get_displayed_images()
        if not displayed:
            mw.status_notification.show_message("No images displayed", 2000)
            return

        # Re-apply filter if one is active
        if hasattr(mw, 'filter_pattern') and mw.filter_pattern:
            displayed = mw.sorting_manager.filter_images_by_pattern(displayed)
            if not displayed:
                return

        # Save current image path (not index, since images will be reordered)
        current_image_path = None
        if hasattr(mw, 'highlight_index') and 0 <= mw.highlight_index < len(displayed):
            current_image_path = displayed[mw.highlight_index]

        progress_dialog = create_titled_progress_dialog(
            mw, "Find Duplicate Image Files", len(displayed)
        )

        # Compute MD5 hash for each file
        hash_to_files = {}
        file_to_hash = {}  # Store hash for each file for later use

        cancelled = False
        for idx, file_path in enumerate(displayed):
            # Check for cancellation
            if progress_dialog.wasCanceled():
                cancelled = True
                break

            # Update progress
            progress_dialog.setValue(idx)
            progress_dialog.setLabelText(
                f"Hashing {elide_progress_filename(os.path.basename(file_path))}... "
                f"({idx + 1}/{len(displayed)})"
            )
            QApplication.processEvents()  # Keep UI responsive

            if not os.path.exists(file_path) or not os.path.isfile(file_path):
                continue

            try:
                # Compute MD5 hash
                md5_hash = hashlib.md5()
                chunk_count = 0
                with open(file_path, 'rb') as f:
                    # Read file in chunks to handle large files efficiently
                    for chunk in iter(lambda: f.read(4096), b''):
                        # Check for cancellation during file reading (every 100 chunks for performance)
                        chunk_count += 1
                        if chunk_count % 100 == 0:
                            QApplication.processEvents()
                            if progress_dialog.wasCanceled():
                                cancelled = True
                                break
                        md5_hash.update(chunk)

                if cancelled:
                    break

                file_hash = md5_hash.hexdigest()

                # Store hash for this file
                file_to_hash[file_path] = file_hash

                # Group files by hash
                if file_hash not in hash_to_files:
                    hash_to_files[file_hash] = []
                hash_to_files[file_hash].append(file_path)
            except (IOError, OSError, PermissionError):
                # Skip files that can't be read - they can't be duplicates
                continue

        # Set final progress value if not cancelled
        if not cancelled:
            progress_dialog.setValue(len(displayed))
            QApplication.processEvents()

        # Close progress dialog
        progress_dialog.close()

        # If cancelled, return early
        if cancelled:
            mw.status_notification.show_message("Find duplicates cancelled", 2000)
            return

        # Find all files that have duplicates (hash appears more than once)
        duplicate_files = []
        for file_hash, files in hash_to_files.items():
            if len(files) > 1:
                duplicate_files.extend(files)

        if not duplicate_files:
            show_styled_information(mw, "No Duplicates Found", "No exact byte-for-byte duplicates found.")
            return

        hash_path_pairs = [
            (file_to_hash[file_path], file_path)
            for file_path in duplicate_files
            if file_path in file_to_hash
        ]
        hash_path_pairs.sort(key=lambda x: (x[0], x[1]))
        duplicate_count = len(duplicate_files)
        _present_duplicate_groups_browse_view(
            mw,
            hash_path_pairs,
            current_image_path,
            f"Browse mode: Duplicates ({duplicate_count} files)",
        )

    def find_exact_duplicates_recursive(self):
        """Find exact duplicates in current directory and all subdirectories"""
        mw = self.main_window

        if hasattr(mw, 'slideshow2_manager') and mw.current_view_mode == 'slideshow2':
            mw.slideshow2_manager.stop_slideshow2()
        if hasattr(mw, 'slideshow3_manager') and mw.current_view_mode == 'slideshow3':
            mw.slideshow3_manager.stop_slideshow3()

        # Get current directory - prioritize highlighted tree directory when tree has focus
        current_dir = None
        
        # Priority: If tree has focus, get selected directory from tree selection model
        if hasattr(mw, '_tree_has_focus') and mw._tree_has_focus():
            if (hasattr(mw, 'file_tree_handler') and mw.file_tree_handler and
                hasattr(mw.file_tree_handler, 'file_tree') and mw.file_tree_handler.file_tree):
                tree = mw.file_tree_handler.file_tree
                selection = tree.selectionModel().selectedIndexes()
                if selection:
                    index = selection[0]
                    model = tree.model()
                    if model:
                        source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                        selected_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                        
                        # Only use if it's a directory
                        if selected_path and os.path.isdir(selected_path):
                            current_dir = selected_path
        
        # Fallback to current_directory or displayed_images directory
        if not current_dir:
            if hasattr(mw, 'current_directory') and mw.current_directory:
                current_dir = mw.current_directory
            elif hasattr(mw, 'displayed_images') and mw.displayed_images:
                current_dir = os.path.dirname(mw.displayed_images[0])
        
        if not current_dir or not os.path.isdir(current_dir):
            mw.status_notification.show_message("No directory available", 2000)
            return

        # Interrupt any ongoing thumbnail loading before recursive scan (avoids hangs during scan)
        if hasattr(mw, '_interrupt_thumbnail_loading'):
            mw._interrupt_thumbnail_loading()

        # Check if directory is root or system volume
        from utils import is_root_or_system_volume, show_styled_warning
        if is_root_or_system_volume(current_dir):
            if current_dir == '/':
                show_styled_warning(mw, "Action Not Available", 
                                   "This action is not available on the root directory.")
            else:
                show_styled_warning(mw, "Action Not Available", 
                                   "This action is not available on system volumes.")
            return

        # Collect all image files recursively
        image_extensions = get_image_extensions()
        all_image_files = []
        
        progress_dialog = create_titled_progress_dialog(
            mw, "Find Duplicate Image Files", 0, indeterminate=True
        )

        # Get process hidden directories setting
        from config import get_config
        config = get_config()
        process_hidden = config.load_settings().get('show_hidden_directories', False)
        
        # Get excluded paths (prowser cache, Photos Library, and ignore directories)
        from files.file_tree_handler import _get_excluded_paths, _is_excluded_path
        excluded_paths = _get_excluded_paths(config)
        
        # Walk directories recursively
        file_count = 0
        cancelled = False
        try:
            for root, dirs, files in os.walk(current_dir):
                # Check for cancellation
                if progress_dialog.wasCanceled():
                    cancelled = True
                    break
                
                # Skip excluded directories
                root_resolved = os.path.realpath(root)
                if _is_excluded_path(root_resolved, excluded_paths):
                    dirs[:] = []  # Don't recurse into excluded directory
                    continue
                
                # Filter hidden directories if not processing them
                if not process_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                # Collect image files
                for file in files:
                    file_path = os.path.join(root, file)
                    if get_file_extension(file) in image_extensions and os.path.isfile(file_path):
                        all_image_files.append(file_path)
                        file_count += 1
                
                # Update progress with total images found on separate line
                progress_dialog.setLabelText(
                    f"Scanning {os.path.relpath(root, current_dir) or '.'}...\n"
                    f"Total images found: {file_count}"
                )
                QApplication.processEvents()
        except Exception as e:
            progress_dialog.close()
            mw.status_notification.show_message(f"Error scanning directories: {e}", 3000)
            return

        progress_dialog.close()

        if cancelled:
            mw.status_notification.show_message("Find duplicates cancelled", 2000)
            return

        if not all_image_files:
            show_styled_information(mw, "No Images Found", "No image files found in directory and subdirectories.")
            return

        # Save current image path (not index, since images will be reordered)
        current_image_path = None
        if hasattr(mw, 'highlight_index') and hasattr(mw, 'displayed_images') and mw.displayed_images:
            if 0 <= mw.highlight_index < len(mw.displayed_images):
                current_image_path = mw.displayed_images[mw.highlight_index]

        progress_dialog = create_titled_progress_dialog(
            mw, "Find Duplicate Image Files", len(all_image_files)
        )

        # Compute MD5 hash for each file
        hash_to_files = {}
        file_to_hash = {}

        cancelled = False
        for idx, file_path in enumerate(all_image_files):
            # Check for cancellation
            if progress_dialog.wasCanceled():
                cancelled = True
                break

            # Update progress
            progress_dialog.setValue(idx)
            progress_dialog.setLabelText(
                f"Hashing {elide_progress_filename(os.path.basename(file_path))}... "
                f"({idx + 1}/{len(all_image_files)})"
            )
            QApplication.processEvents()

            if not os.path.exists(file_path) or not os.path.isfile(file_path):
                continue

            try:
                # Compute MD5 hash
                md5_hash = hashlib.md5()
                chunk_count = 0
                with open(file_path, 'rb') as f:
                    # Read file in chunks to handle large files efficiently
                    for chunk in iter(lambda: f.read(4096), b''):
                        # Check for cancellation during file reading (every 100 chunks for performance)
                        chunk_count += 1
                        if chunk_count % 100 == 0:
                            QApplication.processEvents()
                            if progress_dialog.wasCanceled():
                                cancelled = True
                                break
                        md5_hash.update(chunk)

                if cancelled:
                    break

                file_hash = md5_hash.hexdigest()

                # Store hash for this file
                file_to_hash[file_path] = file_hash

                # Group files by hash
                if file_hash not in hash_to_files:
                    hash_to_files[file_hash] = []
                hash_to_files[file_hash].append(file_path)
            except (IOError, OSError, PermissionError) as e:
                # Skip files that can't be read - they can't be duplicates
                continue

        # Set final progress value if not cancelled
        if not cancelled:
            progress_dialog.setValue(len(all_image_files))
            QApplication.processEvents()

        # Close progress dialog
        progress_dialog.close()

        # If cancelled, return early
        if cancelled:
            mw.status_notification.show_message("Find duplicates cancelled", 2000)
            return

        # Find all files that have duplicates (hash appears more than once)
        duplicate_files = []
        for file_hash, files in hash_to_files.items():
            if len(files) > 1:
                duplicate_files.extend(files)

        if not duplicate_files:
            show_styled_information(mw, "No Duplicates Found", "No exact byte-for-byte duplicates found in directory and subdirectories.")
            return

        hash_path_pairs = [
            (file_to_hash[file_path], file_path)
            for file_path in duplicate_files
            if file_path in file_to_hash
        ]
        hash_path_pairs.sort(key=lambda x: (x[0], x[1]))
        duplicate_count = len(duplicate_files)
        _present_duplicate_groups_browse_view(
            mw,
            hash_path_pairs,
            current_image_path,
            f"Browse mode: Duplicates ({duplicate_count} files)",
        )

    def find_similar_image_files(self):
        """Find visually similar images in the current displayed list (same UX as exact duplicates)."""
        mw = self.main_window

        if hasattr(mw, 'slideshow2_manager') and mw.current_view_mode == 'slideshow2':
            mw.slideshow2_manager.stop_slideshow2()
        if hasattr(mw, 'slideshow3_manager') and mw.current_view_mode == 'slideshow3':
            mw.slideshow3_manager.stop_slideshow3()

        displayed = mw.get_displayed_images()
        if not displayed:
            mw.status_notification.show_message("No images displayed", 2000)
            return

        if hasattr(mw, 'filter_pattern') and mw.filter_pattern:
            displayed = mw.sorting_manager.filter_images_by_pattern(displayed)
            if not displayed:
                return

        current_image_path = None
        if hasattr(mw, 'highlight_index') and 0 <= mw.highlight_index < len(displayed):
            current_image_path = displayed[mw.highlight_index]

        group_pairs, cancelled = _run_similar_image_group_pairs_ui(
            mw, displayed, "Find Similar Image Files"
        )

        if cancelled:
            mw.status_notification.show_message("Find similar images cancelled", 2000)
            return

        if not group_pairs:
            show_styled_information(
                mw,
                "No Similar Images Found",
                "No groups of visually similar images were found (same oriented dimensions; compared at 128px width).",
            )
            return

        nfiles = len(group_pairs)
        _present_duplicate_groups_browse_view(
            mw,
            group_pairs,
            current_image_path,
            f"Browse mode: Similar images ({nfiles} files)",
        )

    def find_similar_image_files_in_directory(self, directory_path: str) -> None:
        """Find visually similar images under directory_path recursively; used from tree context menu."""
        mw = self.main_window

        if hasattr(mw, 'slideshow2_manager') and mw.current_view_mode == 'slideshow2':
            mw.slideshow2_manager.stop_slideshow2()
        if hasattr(mw, 'slideshow3_manager') and mw.current_view_mode == 'slideshow3':
            mw.slideshow3_manager.stop_slideshow3()

        if hasattr(mw, '_interrupt_thumbnail_loading'):
            mw._interrupt_thumbnail_loading()

        from utils import is_root_or_system_volume, show_styled_warning
        if is_root_or_system_volume(directory_path):
            if directory_path == '/':
                show_styled_warning(mw, "Action Not Available",
                                    "This action is not available on the root directory.")
            else:
                show_styled_warning(mw, "Action Not Available",
                                    "This action is not available on system volumes.")
            return

        if not directory_path or not os.path.isdir(directory_path):
            mw.status_notification.show_message("Invalid folder", 2000)
            return

        if mw.current_view_mode != 'thumbnail':
            if hasattr(mw, 'view_manager'):
                mw.view_manager.close_browse_view()

        mw.current_directory = directory_path

        image_extensions = get_image_extensions()
        all_image_files: List[str] = []

        progress_dialog = create_titled_progress_dialog(
            mw, "Find Similar Image Files", 0, indeterminate=True
        )

        config = get_config()
        process_hidden = config.load_settings().get('show_hidden_directories', False)
        from files.file_tree_handler import _get_excluded_paths, _is_excluded_path
        excluded_paths = _get_excluded_paths(config)

        file_count = 0
        cancelled = False
        try:
            for root, dirs, files in os.walk(directory_path):
                if progress_dialog.wasCanceled():
                    cancelled = True
                    break
                root_resolved = os.path.realpath(root)
                if _is_excluded_path(root_resolved, excluded_paths):
                    dirs[:] = []
                    continue
                if not process_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                for file in files:
                    file_path = os.path.join(root, file)
                    if get_file_extension(file) in image_extensions and os.path.isfile(file_path):
                        all_image_files.append(file_path)
                        file_count += 1
                progress_dialog.setLabelText(
                    f"Scanning {os.path.relpath(root, directory_path) or '.'}...\n"
                    f"Total images found: {file_count}"
                )
                QApplication.processEvents()
        except Exception as e:
            progress_dialog.close()
            mw.status_notification.show_message(f"Error scanning directories: {e}", 3000)
            return

        progress_dialog.close()

        if cancelled:
            mw.status_notification.show_message("Find similar images cancelled", 2000)
            return

        if len(all_image_files) < 2:
            show_styled_information(
                mw,
                "Not Enough Images",
                "Need at least two image files under this folder (including subfolders) to search for similar images.",
            )
            return

        current_image_path = None
        if hasattr(mw, 'highlight_index') and hasattr(mw, 'displayed_images') and mw.displayed_images:
            if 0 <= mw.highlight_index < len(mw.displayed_images):
                current_image_path = mw.displayed_images[mw.highlight_index]

        group_pairs, cancelled = _run_similar_image_group_pairs_ui(
            mw, all_image_files, "Find Similar Image Files"
        )

        if cancelled:
            mw.status_notification.show_message("Find similar images cancelled", 2000)
            return

        if not group_pairs:
            show_styled_information(
                mw,
                "No Similar Images Found",
                "No groups of visually similar images were found under this folder (same oriented dimensions; compared at 128px width).",
            )
            return

        nfiles = len(group_pairs)
        _present_duplicate_groups_browse_view(
            mw,
            group_pairs,
            current_image_path,
            f"Browse mode: Similar images ({nfiles} files)",
        )

    def find_similar_image_files_recursive(self):
        """Find visually similar images under the current directory tree (recursive)."""
        mw = self.main_window

        if hasattr(mw, 'slideshow2_manager') and mw.current_view_mode == 'slideshow2':
            mw.slideshow2_manager.stop_slideshow2()
        if hasattr(mw, 'slideshow3_manager') and mw.current_view_mode == 'slideshow3':
            mw.slideshow3_manager.stop_slideshow3()

        current_dir = None
        if hasattr(mw, '_tree_has_focus') and mw._tree_has_focus():
            if (hasattr(mw, 'file_tree_handler') and mw.file_tree_handler and
                    hasattr(mw.file_tree_handler, 'file_tree') and mw.file_tree_handler.file_tree):
                tree = mw.file_tree_handler.file_tree
                selection = tree.selectionModel().selectedIndexes()
                if selection:
                    index = selection[0]
                    model = tree.model()
                    if model:
                        source_index = model.mapToSource(index) if hasattr(model, 'mapToSource') else index
                        selected_path = model.sourceModel().filePath(source_index) if hasattr(model, 'sourceModel') else ""
                        if selected_path and os.path.isdir(selected_path):
                            current_dir = selected_path

        if not current_dir:
            if hasattr(mw, 'current_directory') and mw.current_directory:
                current_dir = mw.current_directory
            elif hasattr(mw, 'displayed_images') and mw.displayed_images:
                current_dir = os.path.dirname(mw.displayed_images[0])

        if not current_dir or not os.path.isdir(current_dir):
            mw.status_notification.show_message("No directory available", 2000)
            return

        if hasattr(mw, '_interrupt_thumbnail_loading'):
            mw._interrupt_thumbnail_loading()

        from utils import is_root_or_system_volume, show_styled_warning
        if is_root_or_system_volume(current_dir):
            if current_dir == '/':
                show_styled_warning(mw, "Action Not Available",
                                    "This action is not available on the root directory.")
            else:
                show_styled_warning(mw, "Action Not Available",
                                    "This action is not available on system volumes.")
            return

        image_extensions = get_image_extensions()
        all_image_files: List[str] = []

        progress_dialog = create_titled_progress_dialog(
            mw, "Find Similar Image Files", 0, indeterminate=True
        )

        config = get_config()
        process_hidden = config.load_settings().get('show_hidden_directories', False)
        from files.file_tree_handler import _get_excluded_paths, _is_excluded_path
        excluded_paths = _get_excluded_paths(config)

        file_count = 0
        cancelled = False
        try:
            for root, dirs, files in os.walk(current_dir):
                if progress_dialog.wasCanceled():
                    cancelled = True
                    break
                root_resolved = os.path.realpath(root)
                if _is_excluded_path(root_resolved, excluded_paths):
                    dirs[:] = []
                    continue
                if not process_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                for file in files:
                    file_path = os.path.join(root, file)
                    if get_file_extension(file) in image_extensions and os.path.isfile(file_path):
                        all_image_files.append(file_path)
                        file_count += 1
                progress_dialog.setLabelText(
                    f"Scanning {os.path.relpath(root, current_dir) or '.'}...\n"
                    f"Total images found: {file_count}"
                )
                QApplication.processEvents()
        except Exception as e:
            progress_dialog.close()
            mw.status_notification.show_message(f"Error scanning directories: {e}", 3000)
            return

        progress_dialog.close()

        if cancelled:
            mw.status_notification.show_message("Find similar images cancelled", 2000)
            return

        if not all_image_files:
            show_styled_information(
                mw, "No Images Found", "No image files found in directory and subdirectories."
            )
            return

        current_image_path = None
        if hasattr(mw, 'highlight_index') and hasattr(mw, 'displayed_images') and mw.displayed_images:
            if 0 <= mw.highlight_index < len(mw.displayed_images):
                current_image_path = mw.displayed_images[mw.highlight_index]

        group_pairs, cancelled = _run_similar_image_group_pairs_ui(
            mw, all_image_files, "Find Similar Image Files"
        )

        if cancelled:
            mw.status_notification.show_message("Find similar images cancelled", 2000)
            return

        if not group_pairs:
            show_styled_information(
                mw,
                "No Similar Images Found",
                "No groups of visually similar images were found in directory and subdirectories.",
            )
            return

        nfiles = len(group_pairs)
        _present_duplicate_groups_browse_view(
            mw,
            group_pairs,
            current_image_path,
            f"Browse mode: Similar images ({nfiles} files)",
        )

    def move_to_last_drop_location(self, copy_only=None):
        """Move or copy selected files (or active file) to the last drop location.

        copy_only: when True/False, force copy or move (Organize sidebar links).
        When None, use destination_menu_action (keyboard shortcuts and menu).
        """
        mw = self.main_window
        # Get last drop location from file tree
        if not (hasattr(mw, 'file_tree_handler') and
                hasattr(mw.file_tree_handler, 'file_tree') and
                mw.file_tree_handler.file_tree):
            return

        from files.file_tree_handler import CustomTreeView
        if not isinstance(mw.file_tree_handler.file_tree, CustomTreeView):
            return

        target_directory = mw.file_tree_handler.file_tree.get_last_drop_location()
        if not target_directory or not os.path.isdir(target_directory):
            mw.status_notification.show_message("No previous drop location available")
            return

        # Get selected files (or active file if none selected)
        file_paths = mw.selection_manager.get_selected_files()
        if not file_paths:
            mw.status_notification.show_message("No files selected")
            return

        if copy_only is None:
            settings = mw.config.load_settings()
            action = settings.get('destination_menu_action', 'move')
            if action == 'none':
                return
            copy_only = action == 'copy'

        # Use the same move logic as drop handler, but skip files that would overwrite
        self._move_files_to_directory(file_paths, target_directory, copy_only=copy_only)

    def _copy_files_from_photos_library(self, file_paths: List[str], target_directory: str) -> None:
        """Copy files from Photos Library to target directory (never move/delete originals).
        This ensures Photos Library files remain intact."""
        from utils import is_inside_photos_library
        mw = self.main_window
        
        # Initialize file move handler if not already done (for path resolution)
        if not hasattr(mw, 'file_move_handler') or mw.file_move_handler is None:
            mw.file_move_handler = FileMoveHandler(mw)
        
        copied_count = 0
        skipped_count = 0
        errors = []
        failed_filenames = []  # Track filenames that failed to copy
        
        # Track "apply to all" state
        apply_to_all_state = {}
        
        # Check if destination is writable before starting
        if not os.access(target_directory, os.W_OK):
            show_styled_critical(
                mw,
                "Cannot Copy Files",
                f"Cannot copy files to destination:\n\n{target_directory}\n\n"
                f"Reason: Destination is read-only or you don't have write permission.\n\n"
                f"Please check the destination permissions or choose a different location."
            )
            return
        
        # Show progress dialog for > 10 files
        progress_dialog = None
        if len(file_paths) > 10:
            from utils import create_file_operation_progress_dialog
            progress_dialog = create_file_operation_progress_dialog(
                mw, "Copying Files from Photos Library", len(file_paths)
            )
        
        for idx, source_path in enumerate(file_paths):
            # Update progress if dialog is shown
            if progress_dialog:
                progress_dialog.setValue(idx)
                progress_dialog.setLabelText(f"Copying file {idx + 1} of {len(file_paths)}")
                QApplication.processEvents()
            # Skip if source is not in Photos Library (shouldn't happen, but safety check)
            if not is_inside_photos_library(source_path):
                continue
            
            # Use common handler to resolve target path (handles overwrite dialog and rename)
            target_path, should_cancel = mw.file_move_handler.resolve_target_path(
                source_path, target_directory, apply_to_all_state
            )
            
            if should_cancel:
                # User cancelled the entire operation
                break
            
            if target_path is None:
                skipped_count += 1
                continue
            
            # Copy the file (never delete source)
            try:
                shutil.copy2(source_path, target_path)
                copied_count += 1
                
                # Update cache if available (add entry for new file)
                if hasattr(mw, 'cache_manager'):
                    mw.cache_manager.clear_cache_for_file(target_path)
            except Exception as e:
                print(f"Error copying file {source_path} to {target_directory}: {e}")
                failed_filename = os.path.basename(source_path)
                failed_filenames.append(failed_filename)
                error_msg = f"Error copying '{failed_filename}': {str(e)}"
                errors.append(error_msg)
                skipped_count += 1
        
        # Close progress dialog if it was shown
        if progress_dialog:
            progress_dialog.setValue(len(file_paths))
            progress_dialog.close()
        
        # Show error dialog if there were failures
        if failed_filenames:
            if len(failed_filenames) == 1:
                # Single file failed - show filename
                show_styled_critical(
                    mw,
                    "Copy Failed",
                    f"Failed to copy file:\n\n{failed_filenames[0]}\n\n"
                    f"Destination: {target_directory}\n\n"
                    f"Please check file permissions and try again.\n\n"
                    f"Note: Original files remain in Photos Library."
                )
            else:
                # Multiple files failed - show count
                show_styled_critical(
                    mw,
                    "Copy Failed",
                    f"Failed to copy {len(failed_filenames)} {file_string(len(failed_filenames))}.\n\n"
                    f"Destination: {target_directory}\n\n"
                    f"Please check file permissions and try again.\n\n"
                    f"Note: Original files remain in Photos Library."
                )
        
        # Show status message
        if copied_count > 0:
            if skipped_count > 0:
                mw.status_notification.show_message(
                    f"Copied {copied_count} {file_string(copied_count)} from Photos Library, skipped {skipped_count}"
                )
            else:
                show_styled_information(
                    mw,
                    "Copy Completed",
                    f"Successfully copied {copied_count} {file_string(copied_count)} from Photos Library to '{folder_basename_for_display(target_directory)}'.\n\n"
                    f"Original files remain in Photos Library."
                )
        elif copied_count > 0:
            show_styled_information(
                mw,
                "Copy Completed",
                f"Successfully copied {copied_count} {file_string(copied_count)} from Photos Library to '{folder_basename_for_display(target_directory)}'.\n\n"
                f"Original files remain in Photos Library."
            )
        elif skipped_count > 0:
            mw.status_notification.show_message(f"No files copied, {skipped_count} skipped")
        
        # Don't remove files from displayed images for copy operations (files still exist in original location)
        # Refresh directory if needed
        if hasattr(mw, 'debounce_refresh_directory'):
            QTimer.singleShot(100, mw.debounce_refresh_directory)

    def move_to_destination(self, destination_index: int, copy_only=None):
        """Move or copy selected files to the specified destination (1-9).

        copy_only: when True/False, force copy or move (Organize sidebar links).
        When None, use destination_menu_action (keyboard shortcuts and menu).
        """
        mw = self.main_window
        # Get destinations from config
        settings = mw.config.load_settings()
        destinations = settings.get('move_destinations', [None] * 9)

        # Ensure we have exactly 9 items
        while len(destinations) < 9:
            destinations.append(None)
        destinations = destinations[:9]

        # Get destination for this index (1-9 maps to 0-8)
        if destination_index < 1 or destination_index > 9:
            return

        target_directory = destinations[destination_index - 1]

        # Check if destination is set
        if not target_directory:
            # Destination is blank - ignore
            return

        # Validate destination directory
        if not os.path.isdir(target_directory):
            # Invalid directory - show error and do nothing
            show_styled_warning(
                mw,
                "Invalid Destination",
                f"Destination {destination_index} specifies an invalid directory:\n\n{target_directory}"
            )
            return

        # Get selected files (or active file if none selected)
        file_paths = mw.selection_manager.get_selected_files()
        if not file_paths:
            mw.status_notification.show_message("No files selected")
            return

        if copy_only is None:
            settings = mw.config.load_settings()
            action = settings.get('destination_menu_action', 'move')
            if action == 'none':
                return
            copy_only = action == 'copy'

        # Use the same move logic as drop handler
        self._move_files_to_directory(file_paths, target_directory, copy_only=copy_only)

    def _move_files_to_directory(self, file_paths: List[str], target_directory: str, copy_only: bool = False) -> None:
        """Move or copy files to target directory with overwrite checks and rename protection.
        Processes files one at a time (copy then delete for move) to detect read-only source errors early.
        When copy_only=True, copies files without deleting originals."""
        mw = self.main_window

        # Check for Photos Library operations
        from utils import is_inside_photos_library, show_styled_warning
        
        target_in_library = is_inside_photos_library(target_directory)
        photos_library_sources = [path for path in file_paths if is_inside_photos_library(path)]
        any_source_in_library = len(photos_library_sources) > 0
        
        # Check if this is dragging OUT of Photos Library (must copy, not move)
        # or dragging INTO/within Photos Library (not allowed)
        if target_in_library:
            if any_source_in_library:
                # This is a within-library operation - not allowed
                show_styled_warning(
                    mw,
                    "Operation Not Allowed",
                    "File operations within macOS Photos Library are not allowed.\n\n"
                    "Photos Library files cannot be moved, renamed, or modified within the library.\n"
                    "You can drag files OUT of the Photos Library to other locations."
                )
                return
            else:
                # Dragging external files INTO Photos Library - not allowed
                show_styled_warning(
                    mw,
                    "Operation Not Allowed",
                    "Adding files to macOS Photos Library is not allowed.\n\n"
                    "Please use the Photos app to add files to your Photos Library."
                )
                return
        
        # Check for locked files - prevent moving (not copying) locked files to different directory
        locked_files = []
        if not copy_only and hasattr(mw, 'lock_manager') and mw.lock_manager:
            for path in file_paths:
                source_dir = os.path.dirname(path)
                target_dir = os.path.realpath(target_directory)
                source_dir_real = os.path.realpath(source_dir)
                # Only prevent if moving to different directory
                if source_dir_real != target_dir and mw.lock_manager.is_file_locked(path):
                    locked_files.append(os.path.basename(path))
        
        if locked_files:
            show_styled_warning(
                mw,
                "Cannot Move Locked Files",
                f"The following files are locked and cannot be moved:\n\n" +
                "\n".join(locked_files[:10]) +  # Show first 10
                (f"\n... and {len(locked_files) - 10} more" if len(locked_files) > 10 else "") +
                "\n\nPlease unlock the files (Shift-Cmd-L) before moving them."
            )
            return
        
        # If source files are in Photos Library, we must copy (not move) to preserve originals
        if any_source_in_library:
            # Convert move operation to copy operation for Photos Library files
            self._copy_files_from_photos_library(file_paths, target_directory)
            return

        # Initialize file move handler if not already done
        if not hasattr(mw, 'file_move_handler') or mw.file_move_handler is None:
            mw.file_move_handler = FileMoveHandler(mw)

        # Capture the active file BEFORE any moves (this is the file that should determine next selection)
        active_file_path = mw.get_current_image_path()

        moved_count = 0
        skipped_count = 0
        skipped_src_dest_count = 0  # Track files skipped due to src=dest
        user_cancelled = False  # User pressed Esc/Cancel on overwrite dialog - no error to show
        errors = []  # Collect error messages for detailed reporting
        failed_filenames = []  # Track filenames that failed to move/copy
        successfully_moved_files = []  # Track files that were successfully moved
        moved_files_info = []  # Track move info for undo: [(source_path, target_path, original_position), ...]

        # Track "apply to all" state
        apply_to_all_state = {}

        # Check if destination is writable before starting
        op_label = "Copy" if copy_only else "Move"
        op_label_past = "Copied" if copy_only else "Moved"  # Correct past tense (not "copyed")
        if not os.access(target_directory, os.W_OK):
            show_styled_critical(
                mw,
                f"Cannot {op_label} Files",
                f"Cannot {op_label.lower()} files to destination:\n\n{target_directory}\n\n"
                f"Reason: Destination is read-only or you don't have write permission.\n\n"
                f"Please check the destination permissions or choose a different location."
            )
            return

        # Show progress dialog for > 10 files
        progress_dialog = None
        if len(file_paths) > 10:
            from utils import create_file_operation_progress_dialog
            progress_dialog = create_file_operation_progress_dialog(
                mw, f"{op_label}ing Files", len(file_paths)
            )

        for idx, source_path in enumerate(file_paths):
            # Update progress if dialog is shown
            if progress_dialog:
                progress_dialog.setValue(idx)
                progress_dialog.setLabelText(f"{op_label}ing file {idx + 1} of {len(file_paths)}")
                QApplication.processEvents()
            # Check if source and destination directories are the same
            source_dir = os.path.realpath(os.path.dirname(source_path))
            target_dir = os.path.realpath(target_directory)
            if source_dir == target_dir:
                # Source and destination are the same - skip with notification
                skipped_count += 1
                skipped_src_dest_count += 1
                mw.status_notification.show_message(f"file {op_label.lower()} skipped, src=dest")
                continue
            
            # Use common handler to resolve target path (handles overwrite dialog and rename)
            target_path, should_cancel = mw.file_move_handler.resolve_target_path(
                source_path, target_directory, apply_to_all_state
            )

            if should_cancel:
                # User cancelled the entire operation (Esc or Cancel on overwrite dialog)
                user_cancelled = True
                break

            if target_path is None:
                skipped_count += 1
                continue

            # Process move/copy one at a time: copy first, then delete source (for move only)
            try:
                # Copy the file to destination
                try:
                    shutil.copy2(source_path, target_path)
                except (OSError, PermissionError) as copy_error:
                    # Destination is read-only or permission denied
                    failed_filename = os.path.basename(source_path)
                    failed_filenames.append(failed_filename)
                    error_msg = f"Cannot copy '{failed_filename}' to destination."
                    error_detail = f"Error: {str(copy_error)}\n\n"
                    error_detail += f"Destination: {target_directory}\n"
                    if "read-only" in str(copy_error).lower() or "permission denied" in str(copy_error).lower():
                        error_detail += "\nThe destination directory is read-only or you don't have write permission."
                    errors.append(f"{error_msg}\n{error_detail}")
                    skipped_count += 1
                    continue

                if copy_only:
                    moved_count += 1
                    successfully_moved_files.append(source_path)
                    if hasattr(mw, 'cache_manager'):
                        mw.cache_manager.clear_cache_for_file(target_path)
                    continue

                # Try to delete the source file (move only)
                try:
                    os.remove(source_path)
                    moved_count += 1
                    successfully_moved_files.append(source_path)
                    
                    # Track move info for undo
                    displayed = mw.get_displayed_images()
                    original_position = displayed.index(source_path) if source_path in displayed else None
                    moved_files_info.append({
                        'source_path': source_path,
                        'target_path': target_path,
                        'original_position': original_position
                    })

                    # Update cache if available
                    if hasattr(mw, 'cache_manager'):
                        mw.cache_manager.clear_cache_for_file(source_path)

                    # Note: We'll remove files from displayed images after all moves complete
                    # to ensure proper next image selection based on original active file
                except (OSError, PermissionError) as delete_error:
                    # Source file could not be deleted (likely read-only folder)
                    # Remove the copied file since move failed
                    try:
                        os.remove(target_path)
                    except Exception:
                        pass  # Ignore errors removing the copy

                    # Ask user if they want to cancel the move operation
                    error_msg = f"Cannot delete source file '{os.path.basename(source_path)}'.\n\n"
                    error_msg += f"Error: {str(delete_error)}\n\n"
                    error_msg += "The file has been copied but the source could not be deleted.\n"
                    error_msg += "Do you want to cancel the remaining move operations?"

                    # Create custom styled dialog to match settings dialog
                    from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
                    from PySide6.QtCore import Qt
                    from utils import create_image_preview_row
                    error_dialog = QDialog(mw)
                    error_dialog.setWindowTitle("Move Operation Failed")
                    error_dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
                    error_dialog.setMinimumWidth(420)
                    error_dialog.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())

                    layout = QVBoxLayout(error_dialog)
                    layout.setSpacing(15)
                    layout.setContentsMargins(20, 20, 20, 20)

                    # Image preview row: source (couldn't delete) and target (copy)
                    image_paths = [p for p in (source_path, target_path) if p and os.path.isfile(p)]
                    if image_paths:
                        labels = ["Source (couldn't delete)" if p == source_path else "Target (copy)" for p in image_paths]
                        preview_row, _ = create_image_preview_row(image_paths, labels=labels, size=96)
                        layout.addLayout(preview_row)

                    # Add message label
                    msg_label = QLabel(error_msg)
                    msg_label.setWordWrap(True)
                    layout.addWidget(msg_label)

                    # Add button layout
                    button_layout = QHBoxLayout()
                    button_layout.addStretch()

                    yes_button = QPushButton("Yes")
                    no_button = QPushButton("No")
                    yes_button.setDefault(True)
                    yes_button.setFocus()

                    button_layout.addWidget(yes_button)
                    button_layout.addWidget(no_button)
                    layout.addLayout(button_layout)

                    # Styling is applied globally via QApplication.setStyleSheet() in main.py

                    reply_result = [None]
                    yes_button.clicked.connect(lambda: (reply_result.__setitem__(0, QMessageBox.StandardButton.Yes), error_dialog.accept()))
                    no_button.clicked.connect(lambda: (reply_result.__setitem__(0, QMessageBox.StandardButton.No), error_dialog.accept()))

                    # Handle Escape key to cancel (No)
                    def handle_reject():
                        reply_result[0] = QMessageBox.StandardButton.No
                        error_dialog.accept()
                    error_dialog.reject = handle_reject

                    error_dialog.exec()
                    reply = reply_result[0] if reply_result[0] is not None else QMessageBox.StandardButton.Yes

                    if reply == QMessageBox.StandardButton.Yes:
                        # User wants to cancel remaining operations
                        break
                    else:
                        # User wants to continue (skip this file)
                        skipped_count += 1
                        continue

            except Exception as e:
                print(f"Error {op_label.lower()}ing file {source_path} to {target_directory}: {e}")
                failed_filename = os.path.basename(source_path)
                failed_filenames.append(failed_filename)
                error_msg = f"Error {op_label.lower()}ing '{failed_filename}': {str(e)}"
                errors.append(error_msg)
                skipped_count += 1

        # Close progress dialog if it was shown
        if progress_dialog:
            progress_dialog.setValue(len(file_paths))
            progress_dialog.close()

        # Show error dialog if there were failures
        fail_title = f"{op_label} Failed"
        if failed_filenames:
            if len(failed_filenames) == 1:
                show_styled_critical(
                    mw,
                    fail_title,
                    f"Failed to {op_label.lower()} file:\n\n{failed_filenames[0]}\n\n"
                    f"Destination: {target_directory}\n\n"
                    f"Please check file permissions and try again."
                )
            else:
                show_styled_critical(
                    mw,
                    fail_title,
                    f"Failed to {op_label.lower()} {len(failed_filenames)} {file_string(len(failed_filenames))}.\n\n"
                    f"Destination: {target_directory}\n\n"
                    f"Please check file permissions and try again."
                )

        # Show status message or error dialog
        destination_name = folder_basename_for_display(target_directory)
        if moved_count > 0:
            if skipped_count > 0:
                mw.status_notification.show_message(
                    f"{op_label_past} {moved_count} {file_string(moved_count)} to {destination_name}, skipped {skipped_count}"
                )
            else:
                mw.status_notification.show_message(
                    f"{op_label_past} {moved_count} {file_string(moved_count)} to {destination_name}"
                )

        # Show error dialog if no files were moved (but only if not already shown above)
        # Don't show error when user cancelled (Esc) or chose No to skip - those are intentional, not failures
        if moved_count == 0 and skipped_src_dest_count < len(file_paths) and not failed_filenames and not user_cancelled and skipped_count == 0:
            error_title = f"Cannot {op_label} Files"
            error_text = f"Cannot {op_label.lower()} files to destination:\n\n{target_directory}\n\n"
            error_text += f"No files were {op_label_past.lower()}. All files may have been skipped due to overwrite conflicts."
            show_styled_critical(
                mw,
                error_title,
                error_text
            )

        # Register move operations for undo if any files were successfully moved (move only)
        if not copy_only and moved_files_info:
            self._register_undo_for_moved_files(moved_files_info, moved_count)

        # Remove successfully moved files from displayed images and update selection (move only)
        if not copy_only and successfully_moved_files and hasattr(mw, 'remove_thumbnails_for_files'):
            mw.remove_thumbnails_for_files(successfully_moved_files, active_file_path)

        # Remove only successfully moved files from selections (move only)
        if not copy_only and moved_count > 0 and successfully_moved_files:
            if hasattr(mw, 'selected_files'):
                mw.selected_files.difference_update(successfully_moved_files)
                if hasattr(mw, '_emit_selection_changed'):
                    mw._emit_selection_changed()

        # In browse mode, navigate to the next image after successful move (move only)
        if not copy_only and moved_count > 0 and mw.current_view_mode == 'browse':
            def navigate_to_next_image():
                displayed = mw.get_displayed_images()
                if displayed and 0 <= mw.highlight_index < len(displayed):
                    next_image_path = displayed[mw.highlight_index]
                    # Update current_index and current_image_path
                    try:
                        # Find the global index of this image
                        if hasattr(mw, 'image_indices') and mw.image_indices:
                            mw.current_index = mw.image_indices[mw.highlight_index]
                        else:
                            mw.current_index = mw.highlight_index
                        mw.current_image_path = next_image_path
                        # Show the next image
                        mw.show_image(next_image_path, mw.current_index)
                    except (IndexError, ValueError):
                        # If something went wrong, just try to show next image normally
                        mw.show_next_image()

            QTimer.singleShot(150, navigate_to_next_image)

        # Emit FILE_OPERATION_COMPLETE for move - subscribers (RefreshManager, MenuManager) can react
        if not copy_only and moved_count > 0 and successfully_moved_files:
            if hasattr(mw, 'event_bus') and mw.event_bus:
                from event_bus import FILE_OPERATION_COMPLETE
                mw.event_bus.emit(FILE_OPERATION_COMPLETE, ('move', successfully_moved_files, True))
        # Refresh directory if needed (delay longer than navigation to avoid conflicts)
        if hasattr(mw, 'debounce_refresh_directory'):
            QTimer.singleShot(200, mw.debounce_refresh_directory)

    def _generate_unique_filename(self, original_path):
        """Generate a unique filename to avoid overwriting existing files"""
        directory = os.path.dirname(original_path)
        filename = os.path.basename(original_path)
        name, ext = os.path.splitext(filename)

        # Check if original filename is available
        if not os.path.exists(original_path):
            return original_path

        # Try with "-restored" suffix
        restored_name = f"{name}-restored{ext}"
        restored_path = os.path.join(directory, restored_name)

        if not os.path.exists(restored_path):
            return restored_path

        # Try with sequential numbers
        counter = 1
        while True:
            numbered_name = f"{name}-restored-{counter}{ext}"
            numbered_path = os.path.join(directory, numbered_name)
            if not os.path.exists(numbered_path):
                return numbered_path
            counter += 1

    def restore_file_from_trash_(self, original_path, original_position=None, show_status=True):
        """Restore file from trash (undo operation)
        
        Searches both user's home trash and volume-specific trash directories
        based on where the original file was located.
        """
        mw = self.main_window

        try:
            # Generate unique filename once at the beginning
            unique_path = self._generate_unique_filename(original_path)
            # Use original filename for trash search, not the unique_path filename
            original_filename = os.path.basename(original_path)

            # Check original directory permissions
            original_dir = os.path.dirname(original_path)
            try:
                if not os.path.exists(original_dir):
                    return False
            except Exception:
                pass

            # Get metadata from deletion_operations for precise matching
            file_size = None
            file_mtime = None
            if hasattr(mw, 'deletion_operations') and mw.deletion_operations:
                for _, operation in enumerate(reversed(mw.deletion_operations)):
                    for entry in operation:
                        if entry['path'] == original_path:
                            file_size = entry.get('file_size')
                            file_mtime = entry.get('file_mtime')
                            break
                    if file_size is not None:
                        break

            # Build list of candidate trash directories (without os.listdir)
            trash_dirs = self._get_trash_directories_for_path(original_path)

            # --- Fast path: try direct file access by name (works even under TCC) ---
            restored_file = None
            for trash_path in trash_dirs:
                candidate_path = os.path.join(trash_path, original_filename)
                try:
                    if not os.path.isfile(candidate_path):
                        continue
                    if file_size is not None:
                        stat_info = os.stat(candidate_path)
                        if stat_info.st_size == file_size:
                            if file_mtime is None or abs(stat_info.st_mtime - file_mtime) < 5:
                                restored_file = candidate_path
                                break
                    else:
                        restored_file = candidate_path
                        break
                except OSError:
                    continue

            # --- Enumeration fallback: scan trash dirs for metadata matches ---
            if not restored_file:
                candidates_with_metadata = []
                candidates_by_name = []
                for trash_path in trash_dirs:
                    try:
                        trash_files = os.listdir(trash_path)
                    except (PermissionError, OSError):
                        continue
                    except Exception:
                        continue

                    for file in trash_files:
                        candidate_path = os.path.join(trash_path, file)
                        if not os.path.isfile(candidate_path):
                            continue
                        try:
                            stat_info = os.stat(candidate_path)
                            candidate_size = stat_info.st_size
                            candidate_mtime = stat_info.st_mtime
                        except OSError:
                            candidate_size = None
                            candidate_mtime = None

                        if file_size is not None and candidate_size is not None:
                            size_match = (file_size == candidate_size)
                            mtime_match = (file_mtime is None or abs(candidate_mtime - file_mtime) < 5)
                            if size_match and mtime_match:
                                mtime_diff = abs(candidate_mtime - file_mtime) if file_mtime is not None else 0
                                candidates_with_metadata.append((candidate_path, file, mtime_diff, True))
                            elif size_match:
                                mtime_diff = abs(candidate_mtime - file_mtime) if file_mtime is not None else 999999
                                candidates_with_metadata.append((candidate_path, file, mtime_diff, False))
                        if file == original_filename:
                            candidates_by_name.append((candidate_path, file))

                if candidates_with_metadata:
                    candidates_with_metadata.sort(key=lambda x: (not x[3], x[2]))
                    restored_file = candidates_with_metadata[0][0]
                elif candidates_by_name:
                    restored_file = candidates_by_name[0][0]

            # --- AppleScript fallback (for sandboxed app bundles) ---
            if not restored_file:
                try:
                    applescript_manager = AppleScriptUndoManager()
                    if applescript_manager.is_available:
                        success = applescript_manager.restore_file_from_trash(original_path, original_position)
                        if success:
                            QTimer.singleShot(300, mw.sequential_refresh_after_browse)
                            return True
                except Exception:
                    pass
                if show_status:
                    show_styled_warning(mw, "Undo Failed", f"Undo: '{original_filename}' not found in Trash.")
                return False

            if restored_file and os.path.exists(restored_file):

                # Restore the file to its unique location
                try:
                    shutil.move(restored_file, unique_path)

                    # Optimized: Return False immediately if file does not exist after restore
                    if not os.path.exists(unique_path):
                        return False

                except Exception as e:
                    if show_status:
                        show_styled_warning(None, "Restore Error", f"Undo: Error restoring '{original_filename}': {e}")
                    return False

                # Add back to displayed images list if it was removed
                displayed = mw.get_displayed_images()
                if unique_path not in displayed:
                    if original_position is not None and original_position <= len(displayed):
                        mw.displayed_images.insert(original_position, unique_path)
                    else:
                        mw.displayed_images.append(unique_path)
                    mw.populate_indices_arrays()

                    # Always update thumbnail view when a file is restored, regardless of current view mode
                    # This ensures thumbnails are updated even when in browse mode
                    if hasattr(mw, 'cache_manager') and mw.cache_manager:
                        mw.cache_manager.clear_cache_for_file(unique_path)

                    # Refresh thumbnail view - add the restored file at its original position
                    if hasattr(mw, 'thumbnail_display_manager') and mw.thumbnail_display_manager:
                        mw.thumbnail_display_manager.add_thumbnails_for_files([unique_path], [original_position] if original_position is not None else None)
                    return True
                else:
                    # Formatted mode: file was kept as slot, just clear placeholder and repaint
                    if hasattr(mw, 'cache_manager') and mw.cache_manager:
                        mw.cache_manager.clear_cache_for_file(unique_path)
                    placeholders = getattr(mw, 'deleted_file_placeholders', None)
                    if placeholders:
                        placeholders.discard(unique_path)
                        placeholders.discard(original_path)
                    # Synchronous repaint (os.path.exists at paint time handles the X)
                    if hasattr(mw, 'thumbnail_container') and mw.thumbnail_container and hasattr(mw.thumbnail_container, 'canvas'):
                        mw.thumbnail_container.canvas.repaint()
                    if getattr(mw, 'current_view_mode', None) == 'list' and hasattr(mw, 'view_manager') and mw.view_manager:
                        mw.view_manager.update_list_view()

                    if mw.current_view_mode == 'browse':
                        displayed = mw.get_displayed_images()
                        if displayed:
                            mw.show_image(displayed[mw.image_indices[mw.current_index]], mw.current_index)

                    if show_status and mw.status_notification:
                        restored_filename = os.path.basename(unique_path)
                        if unique_path != original_path:
                            mw.status_notification.show_message(f"Restored: {restored_filename} (renamed to avoid overwrite)")
                        else:
                            mw.status_notification.show_message(f"Restored: {restored_filename}")
                    return True
            else:
                if show_status:
                    show_styled_warning(mw, "Undo Failed", f"Undo: '{original_filename}' not found in Trash.")
                return False
        except Exception as e:
            if show_status:
                show_styled_warning(None, "Restore Error", f"Undo: Error restoring '{original_filename}': {e}")
            return False

    def restore_multiple_files_from_trash_(self, deleted_files_batch):
        """Restore multiple files from trash"""
        mw = self.main_window
        is_formatted = getattr(mw, '_is_formatted_list_mode', lambda: False)()
        restored_count = 0
        restored_files = []
        restored_positions = []
        total = len(deleted_files_batch)

        progress = None
        if total > 1:
            progress = QProgressDialog("Restoring files from trash...", None, 0, total, mw)
            progress.setWindowTitle("Restoring Files")
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.setValue(0)
            progress.show()
            QApplication.processEvents()

        for i, file_info in enumerate(deleted_files_batch):
            try:
                original_path = file_info['path']
                original_position = file_info.get('original_position')

                if progress:
                    progress.setLabelText(f"Restoring file {i + 1} of {total}")
                    progress.setValue(i)
                    QApplication.processEvents()

                unique_path = self._generate_unique_filename(original_path)

                if os.path.exists(unique_path):
                    restored_count += 1
                    restored_files.append(unique_path)
                    restored_positions.append(original_position)
                    continue

                if self.restore_file_from_trash_(original_path, original_position, show_status=False):
                    restored_count += 1
                    if not is_formatted:
                        actual_restored_path = self._generate_unique_filename(original_path)
                        restored_files.append(actual_restored_path)
                        restored_positions.append(original_position)
                    else:
                        restored_files.append(original_path)
                        restored_positions.append(original_position)

            except Exception:
                pass

        if progress:
            progress.setValue(total)
            progress.close()

        if restored_count > 0:
            if is_formatted:
                # Formatted mode: displayed_images was never changed, just clear
                # placeholders and repaint. Do NOT call add_thumbnails_for_files.
                placeholders = getattr(mw, 'deleted_file_placeholders', None)
                if placeholders:
                    for fi in deleted_files_batch:
                        placeholders.discard(fi['path'])
                    for p in restored_files:
                        placeholders.discard(p)
                # Synchronous repaint (file is already on disk, os.path.exists handles it)
                if hasattr(mw, 'thumbnail_container') and mw.thumbnail_container and hasattr(mw.thumbnail_container, 'canvas'):
                    mw.thumbnail_container.canvas.repaint()
                if getattr(mw, 'current_view_mode', None) == 'list' and hasattr(mw, 'view_manager') and mw.view_manager:
                    mw.view_manager.update_list_view()
            else:
                # Normal mode: add files back to displayed_images
                if restored_files and hasattr(mw, 'thumbnail_display_manager') and mw.thumbnail_display_manager:
                    mw.thumbnail_display_manager.add_thumbnails_for_files(restored_files, restored_positions)

            if mw.status_notification:
                mw.status_notification.show_message(f"Restored {restored_count} files from trash")
        else:
            show_styled_warning(mw, "Undo Failed", "Failed to restore files from trash")

    def _handle_successful_restore(self, original_path, original_position=None):
        """Handle successful file restoration from AppleScript fallback"""
        mw = self.main_window

        try:
            filename = os.path.basename(original_path)
            is_formatted = getattr(mw, '_is_formatted_list_mode', lambda: False)()

            if is_formatted:
                # Formatted mode: slot was never removed, just clear placeholder and repaint
                placeholders = getattr(mw, 'deleted_file_placeholders', None)
                if placeholders:
                    placeholders.discard(original_path)
                if hasattr(mw, 'cache_manager') and mw.cache_manager:
                    mw.cache_manager.clear_cache_for_file(original_path)
                if hasattr(mw, 'thumbnail_container') and mw.thumbnail_container and hasattr(mw.thumbnail_container, 'canvas'):
                    mw.thumbnail_container.canvas.repaint()
                if getattr(mw, 'current_view_mode', None) == 'list' and hasattr(mw, 'view_manager') and mw.view_manager:
                    mw.view_manager.update_list_view()
                mw.status_notification.show_message(f"Restored: {filename}")
                return

            # Normal mode: add back to displayed images
            displayed = mw.get_displayed_images()
            if original_path not in displayed:
                if original_position is not None and original_position <= len(displayed):
                    mw.displayed_images.insert(original_position, original_path)
                else:
                    mw.displayed_images.append(original_path)
                mw.populate_indices_arrays()

                if hasattr(mw, 'cache_manager') and mw.cache_manager:
                    mw.cache_manager.clear_cache_for_file(original_path)

                if hasattr(mw, 'thumbnail_display_manager') and mw.thumbnail_display_manager:
                    mw.thumbnail_display_manager.add_thumbnails_for_files([original_path], [original_position] if original_position is not None else None)

                if mw.current_view_mode == 'browse':
                    displayed = mw.get_displayed_images()
                    if displayed:
                        mw.show_image(displayed[mw.image_indices[mw.current_index]], mw.current_index)

                mw.status_notification.show_message(f"Restored: {filename}")

        except Exception:
            pass

    def browse_trash_images(self):
        """
        Browse images in macOS Trash from all readable locations.
        
        Collects images from:
        - User's home trash: ~/.Trash
        - Volume-specific trash: /Volumes/<volume>/.Trashes/<uid>/
        
        Opens as a set of specific files (not directory-based).
        """
        mw = self.main_window

        # Supported image extensions for filtering (from config)
        image_exts = get_image_extensions()

        # Get all readable trash directories
        trash_dirs = self._get_all_readable_trash_directories()
        if not trash_dirs:
            show_styled_information(mw, "No Trash Available", "No readable trash directories found.")
            return

        # Collect all image files from all trash directories
        all_image_files = []
        for trash_dir in trash_dirs:
            try:
                files = os.listdir(trash_dir)
                for f in files:
                    src_path = os.path.join(trash_dir, f)
                    try:
                        # Include all image files (no filter pattern restriction for trash)
                        if os.path.isfile(src_path) and get_file_extension(f) in image_exts:
                            all_image_files.append(src_path)
                    except Exception as e:
                        print(f"Failed to check {src_path}: {e}")
            except Exception as e:
                print(f"Failed to list {trash_dir}: {e}")
                continue

        if not all_image_files:
            show_styled_information(mw, "No Images in Trash", "No image files found in any readable trash location.")
            return

        # Open as specific files (not directory-based)
        # Use refresh_from_configuration with files list
        configuration = {
            "files": all_image_files,
            "view_mode": "thumbnail",
        }

        if hasattr(mw, 'refresh_from_configuration'):
            mw.refresh_from_configuration(configuration)
        else:
            show_styled_critical(mw, "Error Opening Trash Images", "Cannot open trash images: refresh_from_configuration not available.")

    def undo_file_operation(self):
        """Undo last file operation (file deletion, move, or wallpaper change)"""
        mw = self.main_window

        # First check if wallpaper undo is available
        if (hasattr(mw, 'wallpaper_manager') and mw.wallpaper_manager and
            mw.wallpaper_manager.can_undo_wallpaper()):
            success = mw.wallpaper_manager.undo_wallpaper()
            if success:
                return  # Wallpaper undo successful, we're done

        # Second check if move undo is available
        # First try undo manager (maintains correct order)
        if mw.file_undo_manager and hasattr(mw.file_undo_manager, 'canUndo') and mw.file_undo_manager.canUndo():
            try:
                # Use undo manager - it will call the appropriate method (undo_move_operation_ or restore_multiple_files_from_trash_)
                if hasattr(mw.file_undo_manager, 'undo') and callable(getattr(mw.file_undo_manager, 'undo')):
                    mw.file_undo_manager.undo()
                    return
            except Exception as e:
                print(f"Undo manager error: {e}")
                # Fall through to fallback lists
        
        # Fallback: check move_operations directly (if undo manager not available or failed)
        if hasattr(mw, 'move_operations') and mw.move_operations:
            last_move_operation = mw.move_operations.pop()
            self.undo_move_operation(last_move_operation)
            return

        # If no wallpaper or move undo, try file deletion undo
        # Check deletion_operations fallback (undo manager already checked above)
        if hasattr(mw, 'deletion_operations') and mw.deletion_operations:
            # Fallback undo using deletion operations stack
            last_operation = mw.deletion_operations.pop()

            if len(last_operation) == 1:
                # Single file operation
                file_info = last_operation[0]

                success = self.restore_file_from_trash_(file_info['path'], file_info.get('original_position'))

                # If standard restore succeeds, update the UI
                if success:
                    # Update the UI to reflect the restored file
                    self._handle_successful_restore(file_info['path'], file_info.get('original_position'))
                # If standard restore fails, try AppleScript fallback
                elif not success:
                    try:
                        applescript_manager = AppleScriptUndoManager()
                        if applescript_manager.is_available:
                            success = applescript_manager.restore_file_from_trash(file_info['path'], file_info.get('original_position'))
                            if success:
                                # Update the UI to reflect the restored file
                                self._handle_successful_restore(file_info['path'], file_info.get('original_position'))
                    except Exception as e:
                        pass
            else:
                # Multiple file operation
                self.restore_multiple_files_from_trash_(last_operation)
                # After restoring, set highlight_index to the last image restored
                if last_operation:
                    last_restored_path = last_operation[-1]['path']
                    if last_restored_path in mw.displayed_images:
                        mw.highlight_index = mw.displayed_images.index(last_restored_path)
                        mw.highlight_image()
            # In formatted mode, skip refresh - it would drop still-deleted placeholder slots
            if not getattr(mw, '_is_formatted_list_mode', lambda: False)():
                if hasattr(mw, 'debounce_refresh_directory'):
                    mw.debounce_refresh_directory()
        else:
            if mw.status_notification:
                mw.status_notification.show_message("No undo operations available")

    def _fallback_undo_from_deletion_operations(self):
        """Fallback undo using deletion operations stack when undo manager fails"""
        mw = self.main_window
        import inspect
        print(f"{RED}DEBUG {RESET}: {RED}_fallback_undo_from_deletion_operations{RESET} called by {GREEN}{inspect.stack()[1].function}{RESET}: Entering")
        if not hasattr(mw, 'deletion_operations') or not mw.deletion_operations:
            if mw.status_notification:
                mw.status_notification.show_message("No undo operations available")
            return

        # Use the existing deletion operations logic
        last_operation = mw.deletion_operations.pop()

        if len(last_operation) == 1:
            # Single file operation
            file_info = last_operation[0]

            # Try standard restore first
            success = self.restore_file_from_trash_(file_info['path'], file_info.get('original_position'))

            # If standard restore succeeds, update the UI
            if success:
                # Update the UI to reflect the restored file
                self._handle_successful_restore(file_info['path'], file_info.get('original_position'))
            # If standard restore fails, try AppleScript fallback
            elif not success:
                try:
                    applescript_manager = AppleScriptUndoManager()
                    if applescript_manager.is_available:
                        success = applescript_manager.restore_file_from_trash(file_info['path'], file_info.get('original_position'))
                        if success:
                            # Update the UI to reflect the restored file
                            self._handle_successful_restore(file_info['path'], file_info.get('original_position'))
                except Exception:
                    pass
        else:
            # Multiple file operation
            self.restore_multiple_files_from_trash_(last_operation)

    def undo_move_operation(self, moved_files_info: List[dict]) -> None:
        """Undo move operation by moving files back to their original locations"""
        mw = self.main_window
        if not moved_files_info:
            if mw.status_notification:
                mw.status_notification.show_message("No move operations to undo")
            return

        restored_count = 0
        errors = []
        restored_files = []  # Track successfully restored files with their positions
        restored_positions = []
        
        for move_info in moved_files_info:
            target_path = move_info['target_path']  # Current location (where file was moved to)
            source_path = move_info['source_path']  # Original location (where file should be moved back to)
            original_position = move_info.get('original_position')
            
            # Check if target file still exists
            if not os.path.exists(target_path):
                errors.append(f"File no longer exists: {os.path.basename(target_path)}")
                continue
            
            # Check if source directory exists
            source_dir = os.path.dirname(source_path)
            if not os.path.exists(source_dir):
                errors.append(f"Original directory no longer exists: {source_dir}")
                continue
            
            # Check if source path already exists (file was moved back already or another file is there)
            if os.path.exists(source_path):
                # Generate unique filename to avoid overwriting
                base, ext = os.path.splitext(source_path)
                counter = 1
                unique_source_path = f"{base}_restored_{counter}{ext}"
                while os.path.exists(unique_source_path):
                    counter += 1
                    unique_source_path = f"{base}_restored_{counter}{ext}"
                source_path = unique_source_path
            
            try:
                # Move file back to original location
                shutil.move(target_path, source_path)
                restored_count += 1
                restored_files.append(source_path)
                restored_positions.append(original_position)
                
                # Update cache
                if hasattr(mw, 'cache_manager'):
                    mw.cache_manager.clear_cache_for_file(target_path)
                    mw.cache_manager.clear_cache_for_file(source_path)
                    
            except Exception as e:
                error_msg = f"Error moving '{os.path.basename(target_path)}' back: {str(e)}"
                errors.append(error_msg)
                print(f"Undo move error: {error_msg}")
        
        # Show status message
        if restored_count > 0:
            if errors:
                mw.status_notification.show_message(
                    f"Undo: Moved {restored_count} {file_string(restored_count)} back, {len(errors)} error(s)"
                )
            else:
                mw.status_notification.show_message(
                    f"Undo: Moved {restored_count} {file_string(restored_count)} back"
                )
            
            # Add restored files back to displayed_images at their original positions
            if restored_files and hasattr(mw, 'displayed_images'):
                displayed = mw.get_displayed_images()
                for restored_file, original_pos in zip(restored_files, restored_positions):
                    if restored_file not in displayed:
                        if original_pos is not None and original_pos <= len(displayed):
                            displayed.insert(original_pos, restored_file)
                        else:
                            displayed.append(restored_file)
                
                # Update indices arrays
                if hasattr(mw, 'populate_indices_arrays'):
                    mw.populate_indices_arrays()
                
                # Add thumbnails for restored files
                if hasattr(mw, 'thumbnail_display_manager') and mw.thumbnail_display_manager:
                    mw.thumbnail_display_manager.add_thumbnails_for_files(restored_files, restored_positions)
                
                # Highlight/select restored files
                if len(restored_files) == 1:
                    # Single file: highlight it
                    restored_file = restored_files[0]
                    if restored_file in displayed:
                        highlight_idx = displayed.index(restored_file)
                        mw.highlight_index = highlight_idx
                        if hasattr(mw, 'current_index'):
                            mw.current_index = highlight_idx
                        if hasattr(mw, 'current_image_path'):
                            mw.current_image_path = restored_file
                        if hasattr(mw, 'highlight_image'):
                            mw.highlight_image()
                else:
                    # Multiple files: select them
                    if hasattr(mw, 'selected_files'):
                        mw.selected_files.clear()
                        for restored_file in restored_files:
                            if restored_file in displayed:
                                mw.selected_files.add(restored_file)
                        # Highlight the last restored file
                        if restored_files:
                            last_file = restored_files[-1]
                            if last_file in displayed:
                                highlight_idx = displayed.index(last_file)
                                mw.highlight_index = highlight_idx
                                if hasattr(mw, 'current_index'):
                                    mw.current_index = highlight_idx
                                if hasattr(mw, 'current_image_path'):
                                    mw.current_image_path = last_file
                                if hasattr(mw, '_emit_selection_changed'):
                                    mw._emit_selection_changed(highlight_index=highlight_idx)
                                if hasattr(mw, 'highlight_image'):
                                    mw.highlight_image()

            # Refresh directory to show restored files
            # CRITICAL: Reuse existing timer - QTimer.singleShot drops GIL during connect(),
            # causing deadlock when thumbnail workers are waiting for GIL (reproducible on undo after delete).
            if mw.current_view_mode == 'thumbnail':
                if hasattr(mw, '_refresh_directory_timer') and mw._refresh_directory_timer:
                    mw._refresh_directory_timer.stop()
                    mw._refresh_directory_timer.start(30)
                elif hasattr(mw, 'debounce_refresh_directory'):
                    mw.debounce_refresh_directory()
            elif hasattr(mw, 'debounce_refresh_directory'):
                mw.debounce_refresh_directory()
        else:
            if errors:
                error_text = "Could not undo move operation:\n\n" + "\n".join(errors[:3])
                if len(errors) > 3:
                    error_text += f"\n... and {len(errors) - 3} more error(s)"
                show_styled_warning(mw, "Undo Failed", error_text)
            else:
                show_styled_warning(mw, "Undo Failed", "No files could be moved back")

    # Similiarly, all other methods shown above are retained exactly as in the original file.
