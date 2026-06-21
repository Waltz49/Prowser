#!/usr/bin/env python3
"""
Background CLIP Worker Process
Standalone process that extracts CLIP features for directories in Favorites and Recently Used.
Runs at low priority when the system is idle.
"""

import json
import os
import sys
import time
import tempfile
import shutil
import logging
import socket
import select
from pathlib import Path
from typing import List, Optional, Set, TYPE_CHECKING

# Add parent directory to path to import modules
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

# Cached paths (macOS) - computed once at import
_SEP = "/"
_HOME = os.environ.get("HOME") or os.path.expanduser("~")
_PHOTOS_RESOURCES = f"{_HOME}/Pictures/Photos Library.photoslibrary/resources"
_PHOTOS_SCOPES = f"{_HOME}/Pictures/Photos Library.photoslibrary/scopes"

from config import get_config
from files.image_extensions_helpers import get_image_extensions, MIN_THUMBNAIL_SIZE
from cache.feature_cache_manager import FeatureCacheManager
from search.cnn_image_similarity_sorter import CNNImageSimilaritySorter
from cache.thumbnail_cache_key import (
    compute_thumbnail_cache_key,
    is_path_in_app_cache_directory,
)

if TYPE_CHECKING:
    from PIL import Image as PILImage


def _pil_rgba_to_rgb_thumbnail(pil_img: "PILImage.Image") -> "PILImage.Image":
    """Composite transparency onto solid gray (matches default UI transparency color roughly)."""
    from PIL import Image

    if pil_img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", pil_img.size, (98, 98, 98))
        if pil_img.mode == "RGBA":
            bg.paste(pil_img, mask=pil_img.split()[3])
        else:
            la = pil_img.convert("RGBA")
            bg.paste(la, mask=la.split()[3])
        return bg
    if pil_img.mode != "RGB":
        return pil_img.convert("RGB")
    return pil_img


def load_thumbnail_pil_with_exif_correction(
    image_path: str, size: int, ignore_exif: bool = False
) -> Optional["PILImage.Image"]:
    """
    Load a thumbnail as PIL Image with EXIF orientation applied (when ignore_exif is False).
    Returns None if loading fails. No Qt dependencies.
    """
    from PIL import Image

    file_ext = os.path.splitext(image_path)[1].lower()
    if file_ext == ".svg":
        return None

    from pil_image_io import open_pil_with_exif_correction

    pil_img = open_pil_with_exif_correction(
        image_path, ignore_exif=ignore_exif, cr2_half_size=True
    )
    if pil_img is None:
        return None
    pil_img = _pil_rgba_to_rgb_thumbnail(pil_img)
    pil_img.thumbnail((size, size), Image.Resampling.LANCZOS)
    return pil_img


class BackgroundThumbnailCache:
    """Disk-backed thumbnail access without Qt."""

    def __init__(self) -> None:
        config = get_config()
        self._app_cache_dir = str(config.cache_dir)
        self.thumbnail_cache_dir = str(config.thumbnail_cache_dir)
        os.makedirs(self.thumbnail_cache_dir, exist_ok=True)
        self._stat_cache: dict = {}
        self._stat_cache_max_age = 60.0

    def _ignore_exif_rotation(self) -> bool:
        try:
            return bool(get_config().load_settings().get("ignore_exif_rotation", False))
        except Exception:
            return False

    def get_cache_key(self, image_path: str, extra: str = "") -> str:
        return compute_thumbnail_cache_key(
            image_path,
            app_cache_dir=self._app_cache_dir,
            ignore_exif_rotation=self._ignore_exif_rotation(),
            stat_cache=self._stat_cache,
            stat_cache_max_age=self._stat_cache_max_age,
            extra=extra,
        )

    def is_in_app_cache_directory(self, image_path: str) -> bool:
        return is_path_in_app_cache_directory(image_path, self._app_cache_dir)

    def get_thumbnail_sync(
        self,
        image_path: str,
        size: int,
        thumbnail_dir_listing: Optional[Set[str]] = None,
    ) -> Optional["PILImage.Image"]:
        """Return cached thumbnail as PIL Image if present on disk, else None."""
        from PIL import Image

        cache_key_base = self.get_cache_key(image_path)
        exact_cache_key = f"{cache_key_base}_{size}"
        disk_path = os.path.join(self.thumbnail_cache_dir, f"{exact_cache_key}.jpg")
        if os.path.exists(disk_path):
            try:
                im = Image.open(disk_path)
                im.load()
                return im.convert("RGB")
            except Exception:
                pass

        best_disk_size = 0
        best_disk_path = None
        try:
            if thumbnail_dir_listing is None:
                thumbnail_files = (
                    set(os.listdir(self.thumbnail_cache_dir))
                    if os.path.exists(self.thumbnail_cache_dir)
                    else set()
                )
            else:
                thumbnail_files = thumbnail_dir_listing

            prefix = cache_key_base + "_"
            scanned = 0
            max_disk_scan = 200
            for filename in thumbnail_files:
                scanned += 1
                if scanned > max_disk_scan:
                    break
                if filename.startswith(prefix) and filename.endswith(".jpg"):
                    try:
                        cached_size = int(filename.split("_")[-1].replace(".jpg", ""))
                        if cached_size >= size and cached_size > best_disk_size:
                            best_disk_size = cached_size
                            best_disk_path = os.path.join(self.thumbnail_cache_dir, filename)
                    except (ValueError, IndexError):
                        continue

            if best_disk_path and os.path.exists(best_disk_path):
                im = Image.open(best_disk_path)
                im.load()
                im = im.convert("RGB")
                if im.width != size or im.height != size:
                    im.thumbnail((size, size), Image.Resampling.LANCZOS)
                return im
        except Exception:
            pass

        return None

    def cache_thumbnail_sync(self, image_path: str, pil_image: "PILImage.Image", size: int) -> None:
        """Write JPEG to the same path ImageCacheManager uses."""
        if self.is_in_app_cache_directory(image_path):
            return

        cache_key = f"{self.get_cache_key(image_path)}_{size}"
        try:
            disk_path = os.path.join(self.thumbnail_cache_dir, f"{cache_key}.jpg")
            rgb = pil_image.convert("RGB")
            rgb.save(disk_path, "JPEG", quality=85)
        except Exception:
            pass


def _flush_face_cache_index_safe() -> None:
    """Persist batched face cache index writes (see face_cache.INDEX_PERSIST_INTERVAL)."""
    try:
        from faces.face_cache import flush_face_cache_index
        flush_face_cache_index()
    except Exception:
        pass


def setup_logging(config, debug_mode: bool = False):
    """Setup logging for background worker process
    
    Args:
        config: Config instance
        debug_mode: If True, enable logging (both file and console). If False, suspend all logging.
    """
    logs_dir = config.logs_dir
    log_file = logs_dir / "background_clip_worker.log"

    # Get logger and clear any existing handlers to avoid duplicates
    logger = logging.getLogger(__name__)
    logger.handlers.clear()
    
    # If debug_mode is False, suspend all logging by setting level to CRITICAL
    # This effectively disables all logging without removing handlers
    if debug_mode:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.CRITICAL + 1)  # Set to level higher than CRITICAL to disable all logging
        # Prevent propagation to root logger to avoid duplicates
        logger.propagate = False
        return logger

    # Create formatter
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # File handler (only enabled when debug_mode is True)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler (stdout) only if debug_mode is True
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # When debug_mode is False, suppress root logger stdout/stderr handlers
    root_logger = logging.getLogger()
    # Remove any StreamHandlers that write to stdout or stderr
    handlers_to_remove = []
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            if handler.stream in (sys.stdout, sys.stderr):
                handlers_to_remove.append(handler)
    for handler in handlers_to_remove:
        root_logger.removeHandler(handler)

    # Prevent propagation to root logger to avoid duplicates
    logger.propagate = False

    return logger


def update_logging_debug_mode(logger: logging.Logger, debug_mode: bool):
    """Update logging to enable/disable all logging based on debug_mode
    
    Args:
        logger: Logger instance to update
        debug_mode: If True, enable logging (both file and console). If False, suspend all logging.
    """
    if debug_mode:
        # Enable logging by setting level to INFO and ensuring handlers exist
        logger.setLevel(logging.INFO)
        
        # Check if handlers exist
        has_file_handler = False
        has_console_handler = False
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                has_file_handler = True
            elif isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
                has_console_handler = True
        
        # Add file handler if missing
        if not has_file_handler:
            config = get_config()
            logs_dir = config.logs_dir
            log_file = logs_dir / "background_clip_worker.log"
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        # Add console handler if missing
        if not has_console_handler:
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
    else:
        # Suspend all logging by setting level higher than CRITICAL
        logger.setLevel(logging.CRITICAL + 1)
        
        # Remove console handler
        handlers_to_remove = []
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
                handlers_to_remove.append(handler)
        for handler in handlers_to_remove:
            logger.removeHandler(handler)
        
        # Also suppress root logger stdout/stderr handlers
        root_logger = logging.getLogger()
        handlers_to_remove = []
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                if handler.stream in (sys.stdout, sys.stderr):
                    handlers_to_remove.append(handler)
        for handler in handlers_to_remove:
            root_logger.removeHandler(handler)


def main():
    """Main entry point for background CLIP worker process"""
    from print_log_redirect import setup_stdout_print_log

    setup_stdout_print_log()

    # Setup logging first (will be updated based on control file)
    config = get_config()
    
    # Initialize debug mode (will be updated from first command)
    initial_debug_mode = False
    
    logger = setup_logging(config, debug_mode=initial_debug_mode)
    current_debug_mode = initial_debug_mode

    import sys

    logger.info("Background CLIP worker process starting (non-Qt)")
    
    # Set low priority on macOS
    try:
        os.nice(10)  # Lower priority (higher nice value)
        logger.info("Set process priority to low (nice=10)")
    except Exception:
        logger.warning("Could not set process priority (nice() not available)")
    
    # Setup Unix domain socket for event-driven command reception
    data_dir = config.data_dir
    socket_path = data_dir / "background_clip_control.sock"
    command_socket = _setup_command_socket(socket_path, logger)
    
    # Status socket client for sending status updates (will be set from first command)
    status_socket_path = None
    
    # Initialize status (send via socket once we have status socket path)
    current_status = {"status": "stopped", "last_update": time.time()}
    
    # Load settings
    settings = config.load_settings()
    clip_model_name = settings.get('clip_model_name', 'openai/clip-vit-base-patch32')
    resnet_model = settings.get('resnet_model', 'resnet18')
    cache_dir = config.image_recognition_cache_dir
    max_depth = settings.get('search_depth', 4)
    
    logger.info(f"CLIP model: {clip_model_name}, ResNet model: {resnet_model}")
    logger.info(f"Cache directory: {cache_dir}")
    logger.info(f"Maximum depth for directory expansion: {max_depth}")
    
    # Initialize feature cache manager (with separate background index)
    feature_cache = FeatureCacheManager(
        cache_dir=cache_dir,
        clip_model_name=clip_model_name,
        resnet_model_name=resnet_model,
        sorter_reference=None,
        threading_backend=True,
    )
    
    # Use separate index file for background process
    clip_index_background = cache_dir / "clip_index_background.json"
    feature_cache.clip_index_file = clip_index_background

    # Disk thumbnail cache (PIL only; matches ImageCacheManager paths via thumbnail_cache_key)
    image_cache = BackgroundThumbnailCache()

    # Initialize CLIP sorter
    cnn_sorter = None
    
    paused = False
    should_stop = False
    cycle_type = "clip"  # Track current cycle: "clip" or "cnn"
    last_command_timestamp = 0.0  # Track timestamp of last processed command to ignore stale commands
    
    logger.info("Background CLIP worker initialized and ready")
    
    # Try to send initial "ready" status if status socket is available
    # (controller sets up status socket before starting worker)
    initial_status_socket_path = data_dir / "background_clip_status.sock"
    if initial_status_socket_path.exists():
        status_socket_path = initial_status_socket_path
        logger.info(f"Found status socket at startup: {status_socket_path}")
        # Send initial "ready" status
        current_status = {"status": "ready", "last_update": time.time()}
        _send_status_update(status_socket_path, current_status, logger)
        logger.info("Sent initial ready status")
    else:
        logger.info(f"Status socket not found at startup: {initial_status_socket_path}")
    
    while not should_stop:
        try:
            # Wait for command via socket (event-driven) with 5 second timeout
            # Fully event-driven - no file fallback
            control_data = None
            if command_socket:
                control_data = _wait_for_command(command_socket, timeout=5.0, logger=logger)
            
            if not control_data:
                # No command received, continue loop (will wait again on next iteration)
                continue
            
            # Get status socket path from control data (if not already set)
            if status_socket_path is None:
                status_socket_path_str = control_data.get("status_socket_path")
                if status_socket_path_str:
                    status_socket_path = Path(status_socket_path_str)
                    logger.info(f"Status socket path received from command: {status_socket_path}")
                    # Send current status immediately
                    _send_status_update(status_socket_path, current_status, logger)
                    logger.info(f"Sent status update: {current_status.get('status', 'unknown')}")
            
            # Check if this command has an older timestamp than the last processed command
            # This prevents reprocessing stale commands from the control file
            command_timestamp = control_data.get("last_update", 0.0)
            command = control_data.get("command", "")
            if (command_timestamp <= last_command_timestamp and 
                last_command_timestamp > 0.0 and
                command in ("pause", "resume", "start")):
                # This is an old/stale command, skip it
                continue
            
            # Check if debug_mode changed and update logging accordingly
            new_debug_mode = control_data.get('debug_mode', False)
            if new_debug_mode != current_debug_mode:
                current_debug_mode = new_debug_mode
                update_logging_debug_mode(logger, current_debug_mode)
                logger.info(f"Debug mode {'enabled' if current_debug_mode else 'disabled'}")
            
            command = control_data.get("command", "stop")
            foreground_busy = control_data.get("foreground_busy", False)
            
            # Update last processed timestamp for commands that actually do something
            if command in ("pause", "resume", "start", "stop", "flush_and_pause"):
                last_command_timestamp = command_timestamp
            
            if command == "stop":
                logger.info("Received stop command, shutting down")
                should_stop = True
                current_status = {"status": "stopped", "last_update": time.time()}
                _send_status_update(status_socket_path, current_status, logger)
                break
            
            elif command == "flush_and_pause":
                logger.info("Received flush_and_pause command")
                # Finish current extraction if any
                if cnn_sorter and hasattr(cnn_sorter, 'feature_cache'):
                    # Flush all dirty caches to disk
                    cnn_sorter.feature_cache.flush_caches(async_flush=False)
                    logger.info("Flushed CNN sorter feature cache")
                
                # Also flush feature_cache directly
                feature_cache.flush_caches(async_flush=False)
                _flush_face_cache_index_safe()
                logger.info("Flushed feature cache manager")
                
                current_status = {"status": "flushed_and_paused", "last_flush_time": time.time(), "last_update": time.time()}
                _send_status_update(status_socket_path, current_status, logger)
                paused = True
                logger.info("Status: flushed_and_paused")
            
            elif command == "pause":
                if not paused: logger.info("Status: paused")
                paused = True
                current_status = {"status": "paused", "last_update": time.time()}
                _send_status_update(status_socket_path, current_status, logger)
            
            elif command == "resume":
                paused = False
                current_status = {"status": "running", "last_update": time.time()}
                _send_status_update(status_socket_path, current_status, logger)
                logger.info("Status: resumed (running)")
                # Continue to processing logic below (same as "start")
            
            # Process directories for both "start" and "resume" commands
            if command == "start" or (command == "resume" and not foreground_busy):
                # Resume if paused (for "start" command)
                if command == "start" and paused:
                    paused = False
                    current_status = {"status": "running", "last_update": time.time()}
                    _send_status_update(status_socket_path, current_status, logger)
                    logger.info("Resuming from paused state - Status: running")
                
                if not paused and not foreground_busy:
                    # Send "running" status immediately when starting to process
                    current_status = {"status": "running", "last_update": time.time()}
                    if status_socket_path:
                        _send_status_update(status_socket_path, current_status, logger)
                    logger.info("Status: running")
                    
                    # Initialize sorter if needed
                    if cnn_sorter is None:
                        try:
                            cnn_sorter = CNNImageSimilaritySorter(
                                similarity_metric='cosine',
                                cache_dir=cache_dir,
                                clip_model_name=clip_model_name,
                                resnet_model=resnet_model
                            )
                            # Use the same feature cache instance
                            cnn_sorter.feature_cache = feature_cache
                            logger.info("CLIP model loaded successfully")
                        except Exception as e:
                            logger.error(f"Error loading CLIP model: {e}")
                            import traceback
                            logger.error(traceback.format_exc())
                            current_status = {"status": "stopped", "last_update": time.time()}
                            _send_status_update(status_socket_path, current_status, logger)
                            time.sleep(5)
                            continue
                    
                    # Get directories to process
                    directories = control_data.get("directories", []) if control_data else []
                    if not directories:
                        # Get directories from Favorites and Recently Used
                        directories = _get_target_directories(config, logger)
                    else:
                        # Directories came from control file - still need to expand subdirectories
                        logger.info(f"Received {len(directories)} directories from control file")
                        if directories:
                            priority_dir = directories[0] if len(directories) > 0 else None
                            if priority_dir:
                                logger.info(f"Priority directory (will be processed first): {priority_dir}")
                        logger.debug(f"Top-level directories from control: {directories[:5]}{'...' if len(directories) > 5 else ''}")
                        
                        # Get prowser cache directory to exclude
                        prowser_cache_dir = str(config.cache_dir)
                        exclude_paths = [prowser_cache_dir]
                        logger.info(f"Excluding prowser cache directory: {prowser_cache_dir}")
                        
                        # Add Photos Library paths to exclude
                        exclude_paths.extend([_PHOTOS_RESOURCES, _PHOTOS_SCOPES])
                        logger.info(f"Excluding Photos Library paths: {_PHOTOS_RESOURCES}, {_PHOTOS_SCOPES}")
                        
                        # Add ignore directories from settings
                        ignore_dirs = _get_ignore_directories(config)
                        if ignore_dirs:
                            exclude_paths.extend(ignore_dirs)
                            logger.info(f"Excluding ignore directories from settings: {len(ignore_dirs)} directories")
                        
                        # Extract priority directory (first in list) before optimization
                        priority_directory = directories[0] if directories else None
                        
                        # First optimize: remove directories that are subdirectories of others
                        optimized_top_level = _optimize_directory_list(directories)
                        removed_count = len(directories) - len(optimized_top_level)
                        
                        # Handle priority directory
                        priority_parent = None
                        if priority_directory:
                            if priority_directory in optimized_top_level:
                                # Remove it from its current position and put it first
                                optimized_top_level.remove(priority_directory)
                                optimized_top_level.insert(0, priority_directory)
                                logger.info(f"Priority directory preserved as first: {priority_directory}")
                            else:
                                # Priority directory was removed by optimization (it's a subdirectory)
                                # Find its parent directory
                                for parent_dir in optimized_top_level:
                                    try:
                                        priority_normalized = os.path.abspath(os.path.realpath(priority_directory)).rstrip(_SEP)
                                        parent_normalized = os.path.abspath(os.path.realpath(parent_dir)).rstrip(_SEP)
                                        if priority_normalized.startswith(parent_normalized + _SEP):
                                            priority_parent = parent_dir
                                            break
                                    except Exception:
                                        pass
                                
                                if priority_parent:
                                    # Move parent to first position so priority directory gets processed first
                                    optimized_top_level.remove(priority_parent)
                                    optimized_top_level.insert(0, priority_parent)
                                    logger.info(f"Priority directory {priority_directory} is subdirectory of {priority_parent}, prioritizing parent")
                                else:
                                    logger.info(f"Priority directory {priority_directory} was optimized out")
                        
                        if removed_count > 0:
                            logger.info(f"Optimized: removed {removed_count} redundant subdirectories, keeping {len(optimized_top_level)} top-level directories")
                        else:
                            logger.info(f"Optimized: {len(optimized_top_level)} top-level directories (no redundancies)")
                        
                        # Then expand the optimized list to include all subdirectories recursively (excluding prowser cache and Photos Library paths)
                        # Priority directory (or its parent) is first, so it will be expanded first
                        # Reload settings to get current depth setting
                        current_settings = config.load_settings()
                        current_max_depth = current_settings.get('search_depth', 4)
                        directories = _expand_directories_with_subdirs(optimized_top_level, logger, exclude_paths=exclude_paths, max_depth=current_max_depth)
                        
                        # If priority directory was a subdirectory, ensure it appears early in the expanded list
                        if priority_directory and priority_directory not in directories[:100]:
                            # Find where priority directory appears in expanded list
                            try:
                                priority_normalized = os.path.abspath(os.path.realpath(priority_directory)).rstrip(_SEP)
                                for idx, dir_path in enumerate(directories):
                                    try:
                                        dir_normalized = os.path.abspath(os.path.realpath(dir_path)).rstrip(_SEP)
                                        if dir_normalized == priority_normalized:
                                            # Move priority directory to near the front (but after its parent if parent exists)
                                            directories.pop(idx)
                                            # Insert after first directory (which is the parent)
                                            insert_pos = min(1, len(directories))
                                            directories.insert(insert_pos, dir_path)
                                            logger.info(f"Repositioned priority directory {priority_directory} to position {insert_pos}")
                                            break
                                    except Exception:
                                        continue
                            except Exception:
                                pass
                        logger.info(f"Expanded to {len(directories)} total directories (including subdirectories up to depth {current_max_depth}, excluding prowser cache and Photos Library paths)")
                        
                        # Show sample of expanded directories to verify depth
                        if directories:
                            sample_size = min(10, len(directories))
                            logger.info(f"Sample of directories to process (first {sample_size}, max depth: {current_max_depth}):")
                            for i, dir_path in enumerate(directories[:sample_size]):
                                # Calculate depth by counting path separators
                                path_parts = dir_path.rstrip(_SEP).split(_SEP)
                                depth = len([p for p in path_parts if p]) - 1
                                logger.info(f"  [{i+1}] {dir_path} (depth: {depth})")
                            if len(directories) > sample_size:
                                logger.info(f"  ... and {len(directories) - sample_size} more directories")
                    
                    if directories:
                        # Process CLIP cycle first
                        if cycle_type == "clip":
                            logger.info(f"Starting CLIP cycle: Processing {len(directories)} directories")
                            _process_directories(cnn_sorter, directories, feature_cache, image_cache, logger, command_socket, status_socket_path, current_status)
                            
                            # Check if processing was paused/stopped (non-blocking check, socket-only)
                            control_data = None
                            if command_socket:
                                control_data = _wait_for_command(command_socket, timeout=0.0, logger=logger)
                            if control_data:
                                command = control_data.get("command", "")
                                if command in ("stop", "pause", "flush_and_pause"):
                                    logger.info(f"CLIP processing was interrupted by {command} command")
                                    continue  # Skip CNN cycle and wait
                            
                            logger.info("CLIP cycle completed. Starting CNN cycle.")
                            
                            # Immediately process CNN cycle (non-concurrent, alternating)
                            logger.info(f"Starting CNN cycle: Processing {len(directories)} directories")
                            _process_directories_cnn(cnn_sorter, directories, feature_cache, image_cache, logger, command_socket, status_socket_path, current_status)
                            
                            # Check if processing was paused/stopped (non-blocking check, socket-only)
                            control_data = None
                            if command_socket:
                                control_data = _wait_for_command(command_socket, timeout=0.0, logger=logger)
                            should_wait = True
                            if control_data:
                                command = control_data.get("command", "")
                                if command in ("stop", "pause", "flush_and_pause"):
                                    logger.info(f"CNN processing was interrupted by {command} command, skipping wait")
                                    should_wait = False
                            
                            # After both CLIP and CNN cycles complete, wait 2 minutes before restarting
                            # Use event-driven socket waiting with timeout to remain responsive
                            if should_wait:
                                logger.info("Both CLIP and CNN cycles completed. Waiting 2 minutes before restarting...")
                                wait_seconds = 120  # 2 minutes
                                waited = 0
                                
                                # Update status to "waiting" to indicate sleep period
                                current_status = {"status": "waiting", "last_update": time.time()}
                                _send_status_update(status_socket_path, current_status, logger)
                                
                                while waited < wait_seconds:
                                    # Wait for command via socket with timeout (event-driven)
                                    remaining_wait = wait_seconds - waited
                                    check_timeout = min(5.0, remaining_wait)  # Check every 5 seconds or remaining time
                                    
                                    control_data = None
                                    if command_socket:
                                        control_data = _wait_for_command(command_socket, timeout=check_timeout, logger=logger)
                                    
                                    # Socket-only (event-driven) - must process command so status updates (e.g. flushed_and_paused)
                                    if control_data:
                                        command = control_data.get("command", "")
                                        if command in ("stop", "pause", "flush_and_pause"):
                                            logger.info(f"Received {command} command during wait, stopping wait")
                                            if command == "stop":
                                                should_stop = True
                                                current_status = {"status": "stopped", "last_update": time.time()}
                                                _send_status_update(status_socket_path, current_status, logger)
                                            elif command == "flush_and_pause":
                                                if cnn_sorter and hasattr(cnn_sorter, 'feature_cache'):
                                                    cnn_sorter.feature_cache.flush_caches(async_flush=False)
                                                feature_cache.flush_caches(async_flush=False)
                                                _flush_face_cache_index_safe()
                                                current_status = {"status": "flushed_and_paused", "last_flush_time": time.time(), "last_update": time.time()}
                                                _send_status_update(status_socket_path, current_status, logger)
                                                paused = True
                                            elif command == "pause":
                                                paused = True
                                                current_status = {"status": "paused", "last_update": time.time()}
                                                _send_status_update(status_socket_path, current_status, logger)
                                            break
                                    
                                    waited += check_timeout
                                
                                if waited >= wait_seconds:
                                    logger.info("Wait period completed, restarting with CLIP cycle")
                                    # Update status back to "running" when sleep completes
                                    current_status = {"status": "running", "last_update": time.time()}
                                    _send_status_update(status_socket_path, current_status, logger)
                            
                            # Cycle type stays "clip" for next iteration (always start with CLIP)
                    else:
                        logger.debug("No directories to process")
                else:
                    # Paused or foreground busy - update status accordingly
                    current_status = {"status": "paused" if paused else "running", "last_update": time.time()}
                    _send_status_update(status_socket_path, current_status, logger)
            
            # No explicit sleep needed - next iteration will wait on socket with timeout
            
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down")
            should_stop = True
            break
        except Exception as e:
            logger.error(f"Background CLIP worker error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            time.sleep(5)
    
    # Cleanup
    if cnn_sorter:
        try:
            cnn_sorter.unload_models()
            logger.info("Unloaded CLIP models")
        except Exception as e:
            logger.warning(f"Error unloading models: {e}")
    
    # Cleanup socket
    if command_socket:
        try:
            command_socket.close()
            if socket_path.exists():
                socket_path.unlink()
            logger.info("Closed command socket")
        except Exception as e:
            logger.warning(f"Error closing socket: {e}")
    
    # Send final status update
    if status_socket_path:
        final_status = {"status": "stopped", "last_update": time.time()}
        _send_status_update(status_socket_path, final_status, logger)

    try:
        try:
            if hasattr(image_cache, "cleanup"):
                image_cache.cleanup()
        except Exception:
            pass
        logger.info("Image cache cleaned up")
    except Exception as e:
        logger.warning(f"Error cleaning up image cache: {e}")

    logger.info("Background CLIP worker stopped")


def _get_ignore_directories(config) -> List[str]:
    """Get ignore directories from settings (only returns enabled ones)"""
    ignore_dirs = []
    try:
        settings = config.load_settings()
        ignore_dirs_list = settings.get('ignore_directories', [])
        if isinstance(ignore_dirs_list, list):
            for ignore_dir in ignore_dirs_list:
                if isinstance(ignore_dir, dict):
                    path = ignore_dir.get('path')
                    enabled = ignore_dir.get('enabled', False)
                    if enabled and path and isinstance(path, str) and path.strip():
                        expanded_path = os.path.expanduser(path.strip())
                        ignore_dirs.append(expanded_path)
                elif ignore_dir and isinstance(ignore_dir, str) and ignore_dir.strip():
                    # Backward compatibility: if it's just a string, treat as enabled
                    expanded_path = os.path.expanduser(ignore_dir.strip())
                    ignore_dirs.append(expanded_path)
    except Exception:
        pass
    return ignore_dirs


def _expand_directories_with_subdirs(directories: List[str], logger: logging.Logger, exclude_paths: Optional[List[str]] = None, max_depth: int = 4) -> List[str]:
    """
    Expand directory list to include all subdirectories, recursively up to max_depth.
    
    Args:
        directories: List of top-level directories
        logger: Logger instance
        exclude_paths: List of paths to exclude (and their subdirectories)
        max_depth: Maximum depth to recurse (from search_depth setting, defaults to 4)
        
    Returns:
        List of all directories including subdirectories (excluding specified paths, respecting max_depth)
    """
    expanded = []
    
    # Load settings for hidden directories and symlinks
    try:
        config = get_config()
        settings = config.load_settings()
        process_hidden = settings.get('show_hidden_directories', False)
        follow_symlinks = settings.get('follow_symlinks', False)
    except Exception:
        # Fallback to defaults if settings can't be loaded
        process_hidden = False
        follow_symlinks = False
    
    # Normalize exclude paths
    exclude_normalized = []
    if exclude_paths:
        for excl_path in exclude_paths:
            try:
                abs_path = os.path.abspath(os.path.realpath(excl_path))
                abs_path = abs_path.rstrip(_SEP)
                exclude_normalized.append(abs_path)
            except Exception:
                exclude_normalized.append(excl_path.rstrip(_SEP))
    
    def _is_excluded(path: str) -> bool:
        """Check if a path should be excluded"""
        try:
            abs_path = os.path.abspath(os.path.realpath(path))
            abs_path = abs_path.rstrip(_SEP)
            for excl_path in exclude_normalized:
                if abs_path == excl_path or abs_path.startswith(excl_path + _SEP):
                    return True
        except Exception:
            pass
        return False
    
    for directory in directories:
        if not os.path.exists(directory) or not os.path.isdir(directory):
            continue
        
        # Skip if directory itself is excluded
        if _is_excluded(directory):
            logger.info(f"Skipping excluded directory: {directory}")
            continue
        
        # Add the directory itself
        expanded.append(directory)
        logger.debug(f"Added top-level directory: {directory}")
        
        # Recursively add all subdirectories up to max_depth
        subdir_count = 0
        skipped_count = 0
        try:
            # Use followlinks parameter to control symlink following
            for root, dirs, files in os.walk(directory, followlinks=follow_symlinks):
                # Filter out excluded directories before processing
                dirs[:] = [d for d in dirs if not _is_excluded(f"{root.rstrip(_SEP)}/{d}")]
                
                # Filter hidden directories if not processing them
                if not process_hidden:
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                # Filter symlinks if not following them (even if followlinks=False, we still need to filter them from dirs list)
                if not follow_symlinks:
                    dirs[:] = [d for d in dirs if not os.path.islink(f"{root.rstrip(_SEP)}/{d}")]
                
                # Calculate depth relative to top-level directory
                rel_path = os.path.relpath(root, directory)
                if rel_path == '.':
                    depth = 0
                else:
                    depth = len([p for p in rel_path.split(_SEP) if p])
                
                # Stop when depth >= max_depth to match find -maxdepth behavior
                # max_depth=4 means: root (depth 0), subdir (depth 1), subsubdir (depth 2), subsubsubdir (depth 3)
                # This matches find -maxdepth 4 which scans 4 levels total
                if depth >= max_depth:
                    dirs[:] = []  # Don't recurse deeper than max_depth
                    continue
                
                # Add each subdirectory
                for subdir in dirs:
                    subdir_path = f"{root.rstrip(_SEP)}/{subdir}"
                    if os.path.isdir(subdir_path):
                        if _is_excluded(subdir_path):
                            skipped_count += 1
                            continue
                        expanded.append(subdir_path)
                        subdir_count += 1
                        # Log deeper subdirectories (show depth)
                        if depth <= 2:  # Log up to 2 levels deep
                            logger.debug(f"  Added subdirectory (depth {depth + 1}): {subdir_path}")
        except Exception as e:
            logger.warning(f"Error walking directory {directory}: {e}")
            continue
        
        if skipped_count > 0:
            logger.info(f"Expanded {directory}: added {subdir_count} subdirectories, skipped {skipped_count} excluded (total: {subdir_count + 1} directories)")
        else:
            logger.info(f"Expanded {directory}: added {subdir_count} subdirectories (total: {subdir_count + 1} directories)")
    
    return expanded


def _optimize_directory_list(directories: List[str]) -> List[str]:
    """
    Optimize directory list by removing directories that are subdirectories of others.
    
    For example, if ['/abc/', '/abc/def/'] are in the list, remove '/abc/def/'
    since it will be processed as part of '/abc/'.
    
    Args:
        directories: List of directory paths
        
    Returns:
        Optimized list with subdirectories removed
    """
    if not directories:
        return []
    
    # Normalize paths (resolve symlinks, remove trailing slashes)
    normalized = []
    for d in directories:
        try:
            # Resolve symlinks and get absolute path
            abs_path = os.path.abspath(os.path.realpath(d))
            # Remove trailing slash
            abs_path = abs_path.rstrip(_SEP)
            normalized.append(abs_path)
        except Exception:
            # If we can't normalize, keep original
            normalized.append(d.rstrip(_SEP))
    
    # Sort by length (shorter paths first) so we check parents before children
    normalized.sort(key=len)
    
    optimized = []
    for current_dir in normalized:
        # Check if this directory is a subdirectory of any already in optimized list
        is_subdirectory = False
        for existing_dir in optimized:
            # Handle root directory case
            if existing_dir == _SEP:
                # Root directory - all other directories are subdirectories
                if current_dir != _SEP:
                    is_subdirectory = True
                    break
            elif current_dir == existing_dir:
                # Exact duplicate
                is_subdirectory = True
                break
            elif current_dir.startswith(existing_dir + _SEP):
                # Check if current_dir starts with existing_dir + _SEP
                # This ensures we match '/abc/def' as subdirectory of '/abc' but not '/abc-def'
                is_subdirectory = True
                break
        
        if not is_subdirectory:
            optimized.append(current_dir)
    
    return optimized


def _get_target_directories(config, logger: logging.Logger) -> List[str]:
    """Get directories from Favorites and Recently Used, expanded to include subdirectories up to max_depth"""
    directories = []
    
    settings = config.load_settings()
    
    # Get depth from search_depth setting
    max_depth = settings.get('search_depth', 4)
    
    # Get favorites
    favorites = settings.get('favorite_directories', [None] * 9)
    for fav in favorites:
        if fav and os.path.exists(fav) and os.path.isdir(fav):
            directories.append(fav)
    
    # Get recently used
    recent = settings.get('directory_menu_history', [])
    for dir_path in recent:
        if dir_path and os.path.exists(dir_path) and os.path.isdir(dir_path):
            if dir_path not in directories:
                directories.append(dir_path)
    
    if not directories:
        return []
    
    logger.info(f"Found {len(directories)} top-level directories from favorites/recent")
    logger.debug(f"Top-level directories: {directories[:5]}{'...' if len(directories) > 5 else ''}")
    
    # First optimize: remove directories that are subdirectories of others
    # (e.g., if '/abc/' and '/abc/def/' are both in the list, remove '/abc/def/')
    optimized_top_level = _optimize_directory_list(directories)
    removed_count = len(directories) - len(optimized_top_level)
    if removed_count > 0:
        logger.info(f"Optimized: removed {removed_count} redundant subdirectories, keeping {len(optimized_top_level)} top-level directories")
        logger.debug(f"Optimized top-level directories: {optimized_top_level}")
    else:
        logger.info(f"Optimized: {len(optimized_top_level)} top-level directories (no redundancies)")
    
    # Get paths to exclude (prowser cache, Photos Library paths, and ignore directories)
    prowser_cache_dir = str(config.cache_dir)
    exclude_paths = [prowser_cache_dir, _PHOTOS_RESOURCES, _PHOTOS_SCOPES]
    # Add ignore directories from settings
    ignore_dirs = _get_ignore_directories(config)
    if ignore_dirs:
        exclude_paths.extend(ignore_dirs)
    logger.info(f"Excluding paths: prowser cache, Photos Library resources, Photos Library scopes, and {len(ignore_dirs)} ignore directories")
    
    # Then expand the optimized list to include all subdirectories recursively up to max_depth
    expanded = _expand_directories_with_subdirs(optimized_top_level, logger, exclude_paths=exclude_paths, max_depth=max_depth)
    logger.info(f"Expanded to {len(expanded)} total directories (including subdirectories up to depth {max_depth}, excluding prowser cache and Photos Library paths)")
    
    # Show sample of expanded directories to verify depth
    if expanded:
        sample_size = min(10, len(expanded))
        logger.info(f"Sample of directories to process (first {sample_size}, max depth: {max_depth}):")
        for i, dir_path in enumerate(expanded[:sample_size]):
            # Calculate depth relative to first top-level directory
            if optimized_top_level:
                rel_path = dir_path.replace(optimized_top_level[0], '', 1) if dir_path.startswith(optimized_top_level[0]) else dir_path
                depth = rel_path.count(_SEP) if rel_path else 0
                logger.info(f"  [{i+1}] {dir_path} (depth: {depth})")
            else:
                logger.info(f"  [{i+1}] {dir_path}")
        if len(expanded) > sample_size:
            logger.info(f"  ... and {len(expanded) - sample_size} more directories")
    
    return expanded


def _process_directories_cnn(cnn_sorter: CNNImageSimilaritySorter, directories: List[str], feature_cache: FeatureCacheManager, image_cache, logger: logging.Logger, command_socket: Optional[socket.socket] = None, status_socket_path: Optional[Path] = None, current_status: dict = None):
    """Process directories and extract CNN features"""
    image_extensions = get_image_extensions()
    
    # Get paths to exclude (double-check): prowser cache, Photos Library paths, and ignore directories
    try:
        config = get_config()
        prowser_cache_dir = str(config.cache_dir)
        prowser_cache_normalized = os.path.abspath(os.path.realpath(prowser_cache_dir)).rstrip(_SEP)
        photos_resources_normalized = os.path.abspath(os.path.realpath(_PHOTOS_RESOURCES)).rstrip(_SEP)
        photos_scopes_normalized = os.path.abspath(os.path.realpath(_PHOTOS_SCOPES)).rstrip(_SEP)
        # Get ignore directories and normalize them
        ignore_dirs = _get_ignore_directories(config)
        ignore_dirs_normalized = []
        for ignore_dir in ignore_dirs:
            try:
                normalized = os.path.abspath(os.path.realpath(ignore_dir)).rstrip(_SEP)
                ignore_dirs_normalized.append(normalized)
            except Exception:
                ignore_dirs_normalized.append(ignore_dir.rstrip(_SEP))
    except Exception:
        prowser_cache_normalized = None
        photos_resources_normalized = None
        photos_scopes_normalized = None
        ignore_dirs_normalized = []
    
    def _should_pause() -> bool:
        """Check if pause command has been received (non-blocking check, socket-only)"""
        try:
            control_data = None
            if command_socket:
                control_data = _wait_for_command(command_socket, timeout=0.0, logger=logger)
            if control_data:
                command = control_data.get("command", "")
                return command in ("pause", "flush_and_pause", "stop")
        except Exception:
            pass
        return False
    
    def _get_command() -> Optional[str]:
        """Get the current command if any (non-blocking check, socket-only)"""
        try:
            control_data = None
            if command_socket:
                control_data = _wait_for_command(command_socket, timeout=0.0, logger=logger)
            if control_data:
                return control_data.get("command", "")
        except Exception:
            pass
        return None
    
    for dir_idx, directory in enumerate(directories):
        # Check for pause command every directory (responsive pause)
        if _should_pause():
            logger.info(f"Pause command received, stopping CNN directory processing (processed {dir_idx}/{len(directories)} directories)")
            # Update status to paused (socket-based)
            try:
                # Check command via socket
                control_data = None
                if command_socket:
                    control_data = _wait_for_command(command_socket, timeout=0.0, logger=logger)
                if control_data:
                    command = control_data.get("command", "")
                    if command == "flush_and_pause":
                        # Flush before pausing
                        feature_cache.flush_caches(async_flush=False)
                        _flush_face_cache_index_safe()
                        current_status["status"] = "flushed_and_paused"
                        current_status["last_flush_time"] = time.time()
                        current_status["last_update"] = time.time()
                        _send_status_update(status_socket_path, current_status, logger)
                        logger.info("Flushed caches and paused")
                    else:
                        current_status["status"] = "paused"
                        current_status["last_update"] = time.time()
                        _send_status_update(status_socket_path, current_status, logger)
                        logger.info("Paused")
            except Exception as e:
                logger.warning(f"Error updating status on pause: {e}")
            return
        # Skip excluded directories if they somehow got through (prowser cache, Photos Library paths, and ignore directories)
        is_excluded = False
        try:
            dir_normalized = os.path.abspath(os.path.realpath(directory)).rstrip(_SEP)
            if prowser_cache_normalized and (dir_normalized == prowser_cache_normalized or dir_normalized.startswith(prowser_cache_normalized + _SEP)):
                logger.debug(f"Skipping excluded directory: {directory}")
                is_excluded = True
            elif photos_resources_normalized and (dir_normalized == photos_resources_normalized or dir_normalized.startswith(photos_resources_normalized + _SEP)):
                logger.debug(f"Skipping excluded directory: {directory}")
                is_excluded = True
            elif photos_scopes_normalized and (dir_normalized == photos_scopes_normalized or dir_normalized.startswith(photos_scopes_normalized + _SEP)):
                logger.debug(f"Skipping excluded directory: {directory}")
                is_excluded = True
            else:
                # Check ignore directories
                for ignore_normalized in ignore_dirs_normalized:
                    if dir_normalized == ignore_normalized or dir_normalized.startswith(ignore_normalized + _SEP):
                        logger.debug(f"Skipping ignored directory: {directory}")
                        is_excluded = True
                        break
        except Exception:
            pass
        if is_excluded:
            continue
        if not os.path.exists(directory) or not os.path.isdir(directory):
            logger.warning(f"Directory does not exist or is not a directory: {directory}")
            continue
        
        try:
            # Calculate depth by counting path separators (rough estimate)
            path_parts = directory.rstrip(_SEP).split(_SEP)
            depth = len([p for p in path_parts if p]) - 1  # -1 because root doesn't count
            depth_info = f" [depth: {depth}]"
            
            logger.debug(f"Processing directory for CNN{depth_info}: {directory}")
            # Get all image files in directory
            image_files = []
            for filename in os.listdir(directory):
                _, ext = os.path.splitext(filename)
                if ext.lower() in image_extensions:
                    filepath = f"{directory.rstrip(_SEP)}/{filename}"
                    if os.path.isfile(filepath):
                        image_files.append(filepath)
            if len(image_files) > 0:
                logger.debug(f"Found {len(image_files)} image files in {directory}{depth_info}")
            
            processed_count = 0
            cached_count = 0
            error_count = 0
            extractions_since_last_flush = 0  # Track extractions to avoid unnecessary flushes
            face_processed_count = 0
            face_cached_count = 0
            
            # Check if we should gather thumbnails (setting can change between directories)
            gather_thumbnails = config.load_settings().get('background_clip_gather_thumbnails', True)
            extract_faces = config.load_settings().get('background_clip_extract_faces', False)
            
            # Process each image
            for idx, image_path in enumerate(image_files):
                # Check for stop/pause command before each image for immediate interruption
                # This ensures the stop command is processed as soon as possible
                command = _get_command()
                if command:
                    if command == "stop":
                        # Stop immediately - don't wait for flush
                        logger.info(f"Stop command received, stopping CNN image processing in {directory} (processed {idx}/{len(image_files)} images)")
                        # Only flush if we have pending extractions (quick flush before exit)
                        if extractions_since_last_flush > 0:
                            try:
                                feature_cache.flush_caches(async_flush=False)
                            except Exception:
                                pass  # Don't block shutdown if flush fails
                            _flush_face_cache_index_safe()
                        current_status["status"] = "stopped"
                        current_status["last_update"] = time.time()
                        _send_status_update(status_socket_path, current_status, logger)
                        return
                    elif command in ("pause", "flush_and_pause"):
                        logger.info(f"Pause command received, stopping CNN image processing in {directory} (processed {idx}/{len(image_files)} images)")
                        # Update status to paused (socket-based)
                        try:
                            if command == "flush_and_pause":
                                # Flush before pausing (always flush on flush_and_pause command)
                                feature_cache.flush_caches(async_flush=False)
                                _flush_face_cache_index_safe()
                                current_status["status"] = "flushed_and_paused"
                                current_status["last_flush_time"] = time.time()
                                current_status["last_update"] = time.time()
                                _send_status_update(status_socket_path, current_status, logger)
                                logger.info("Flushed caches and paused")
                            else:
                                # Only flush if we have pending extractions
                                if extractions_since_last_flush > 0:
                                    feature_cache.flush_caches(async_flush=False)
                                    _flush_face_cache_index_safe()
                                current_status["status"] = "paused"
                                current_status["last_update"] = time.time()
                                _send_status_update(status_socket_path, current_status, logger)
                                logger.info("Paused")
                        except Exception as e:
                            logger.warning(f"Error updating status on pause: {e}")
                        return
                
                try:
                    # Get filename for logging
                    fname = image_path.rsplit("/", 1)[-1]

                    # Check if thumbnail is already cached - only gather when setting is enabled
                    if gather_thumbnails:
                        existing_thumbnail = image_cache.get_thumbnail_sync(image_path, MIN_THUMBNAIL_SIZE)
                        if existing_thumbnail is None:
                            # Generate and cache thumbnail for this image at MIN_THUMBNAIL_SIZE
                            try:
                                logger.debug(f"Generating thumbnail for {image_path}")
                                # Generate thumbnail directly using EXIF loader
                                pil_thumb = load_thumbnail_pil_with_exif_correction(
                                    image_path, MIN_THUMBNAIL_SIZE, ignore_exif=False
                                )
                                if pil_thumb is not None:
                                    image_cache.cache_thumbnail_sync(image_path, pil_thumb, MIN_THUMBNAIL_SIZE)
                                    logger.info(f"New thumbnail cache entry created for {image_path}")
                                else:
                                    logger.info(f"Thumbnail generation returned no image for {image_path}")
                            except Exception as e:
                                # Don't fail the entire process if thumbnail generation fails
                                logger.info(f"Thumbnail generation failed for {image_path}: {e}")

                    # Extract faces when setting is enabled (skip if already cached)
                    # Skip when foreground face scan is active - foreground has priority, no concurrent face gathering
                    # Use same path normalization and cache semantics as foreground (face_scan_runner.run_scan)
                    if extract_faces:
                        try:
                            from faces.face_gathering_coordinator import is_foreground_face_scan_active
                            if not is_foreground_face_scan_active():
                                from faces.face_cache import normalize_path_for_face_cache
                                from faces.face_engine import is_available as face_engine_available
                                from faces.face_engine import encode_faces_from_path as face_encode
                                from faces.face_cache import has_cached_faces as face_has_cached
                                from faces.face_cache import set_encodings as face_set_encodings
                                path_for_face = normalize_path_for_face_cache(image_path)
                                if face_engine_available() and not face_has_cached(path_for_face):
                                    encodings = face_encode(image_path)
                                    face_set_encodings(path_for_face, encodings)  # store both positive and negative
                                    face_processed_count += 1
                                    if face_processed_count == 1:
                                        logger.info(f"Face extraction started for {directory} ({len(image_files)} images)")
                                    if encodings:
                                        face_cached_count += 1
                                        if face_cached_count <= 5 or face_cached_count % 50 == 0:
                                            logger.info(f"Face extraction: cached {face_cached_count} images with faces in {directory} (latest: {fname})")
                        except Exception as e:
                            logger.debug(f"Face extraction skipped for {image_path}: {e}")

                    # Check if already cached
                    stat = os.stat(image_path)
                    mtime = stat.st_mtime
                    size = stat.st_size

                    # Check if already in cache
                    cached_feat = feature_cache.get_cnn_feature(image_path, mtime, size, device='cpu')
                    if cached_feat is not None:
                        cached_count += 1
                        continue  # Already cached, skip

                    # Extract CNN feature
                    feat = cnn_sorter._get_feature(image_path)
                    if feat is not None:
                        processed_count += 1
                        extractions_since_last_flush += 1
                        # Feature is automatically stored in cache by _get_feature

                        if processed_count % 50 == 0:
                            total_images = len(image_files)
                            logger.info(f"Processed {processed_count}/{total_images} CNN images from {directory}")
                    else:
                        # Extraction failed but no exception was raised
                        logger.warning(f"CNN extraction failed: {fname}")
                    
                    # Flush periodically (every 50 images) to avoid memory buildup
                    # Only flush if we actually extracted features since last flush
                    # Check for stop command before flushing to avoid blocking shutdown
                    if (idx + 1) % 50 == 0:
                        # Check for stop command before flush (already checked above, but double-check)
                        command = _get_command()
                        if command == "stop":
                            # Stop immediately without flushing
                            logger.info(f"Stop command received before CNN flush, stopping immediately (processed {idx}/{len(image_files)} images)")
                            current_status["status"] = "stopped"
                            current_status["last_update"] = time.time()
                            _send_status_update(status_socket_path, current_status, logger)
                            return
                        
                        if extractions_since_last_flush > 0:
                            feature_cache.flush_caches(async_flush=False)
                            _flush_face_cache_index_safe()
                            extractions_since_last_flush = 0  # Reset counter after flush
                
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Error processing {image_path}: {e}")
                    continue
            
            # Final flush for this directory (only if we have pending extractions)
            # Check for stop command before final flush
            command = _get_command()
            if command == "stop":
                logger.info(f"Stop command received before final CNN flush, stopping immediately")
                current_status["status"] = "stopped"
                current_status["last_update"] = time.time()
                _send_status_update(status_socket_path, current_status, logger)
                return
            
            if extractions_since_last_flush > 0:
                feature_cache.flush_caches(async_flush=False)
                _flush_face_cache_index_safe()
            if extract_faces and face_processed_count > 0:
                logger.info(f"Face extraction completed for {directory}: {face_processed_count} processed, {face_cached_count} with faces")
            # logger.info(f"Completed CNN {directory}: processed={processed_count}, cached={cached_count}, errors={error_count}")
        
        except PermissionError:
            # logger.error(f"CNN background: Permission error processing directory {directory}")
            continue
        except Exception as e:
            logger.error(f"Error processing directory {directory}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            continue


def _process_directories(cnn_sorter: CNNImageSimilaritySorter, directories: List[str], feature_cache: FeatureCacheManager, image_cache, logger: logging.Logger, command_socket: Optional[socket.socket] = None, status_socket_path: Optional[Path] = None, current_status: dict = None):
    """Process directories and extract CLIP features"""
    image_extensions = get_image_extensions()
    
    # Get paths to exclude (double-check): prowser cache, Photos Library paths, and ignore directories
    try:
        config = get_config()
        prowser_cache_dir = str(config.cache_dir)
        prowser_cache_normalized = os.path.abspath(os.path.realpath(prowser_cache_dir)).rstrip(_SEP)
        photos_resources_normalized = os.path.abspath(os.path.realpath(_PHOTOS_RESOURCES)).rstrip(_SEP)
        photos_scopes_normalized = os.path.abspath(os.path.realpath(_PHOTOS_SCOPES)).rstrip(_SEP)
        # Get ignore directories and normalize them
        ignore_dirs = _get_ignore_directories(config)
        ignore_dirs_normalized = []
        for ignore_dir in ignore_dirs:
            try:
                normalized = os.path.abspath(os.path.realpath(ignore_dir)).rstrip(_SEP)
                ignore_dirs_normalized.append(normalized)
            except Exception:
                ignore_dirs_normalized.append(ignore_dir.rstrip(_SEP))
    except Exception:
        prowser_cache_normalized = None
        photos_resources_normalized = None
        photos_scopes_normalized = None
        ignore_dirs_normalized = []
    
    def _should_pause() -> bool:
        """Check if pause command has been received (non-blocking check, socket-only)"""
        try:
            control_data = None
            if command_socket:
                control_data = _wait_for_command(command_socket, timeout=0.0, logger=logger)
            if control_data:
                command = control_data.get("command", "")
                return command in ("pause", "flush_and_pause", "stop")
        except Exception:
            pass
        return False
    
    def _get_command() -> Optional[str]:
        """Get the current command if any (non-blocking check, socket-only)"""
        try:
            control_data = None
            if command_socket:
                control_data = _wait_for_command(command_socket, timeout=0.0, logger=logger)
            if control_data:
                return control_data.get("command", "")
        except Exception:
            pass
        return None
    
    for dir_idx, directory in enumerate(directories):
        # Check for pause command every directory (responsive pause)
        if _should_pause():
            logger.info(f"Pause command received, stopping directory processing (processed {dir_idx}/{len(directories)} directories)")
            # Update status to paused (socket-based)
            try:
                # Check command via socket
                control_data = None
                if command_socket:
                    control_data = _wait_for_command(command_socket, timeout=0.0, logger=logger)
                if control_data:
                    command = control_data.get("command", "")
                    if command == "flush_and_pause":
                        # Flush before pausing
                        feature_cache.flush_caches(async_flush=False)
                        _flush_face_cache_index_safe()
                        current_status["status"] = "flushed_and_paused"
                        current_status["last_flush_time"] = time.time()
                        current_status["last_update"] = time.time()
                        _send_status_update(status_socket_path, current_status, logger)
                        logger.info("Flushed caches and paused")
                    else:
                        current_status["status"] = "paused"
                        current_status["last_update"] = time.time()
                        _send_status_update(status_socket_path, current_status, logger)
                        logger.info("Paused")
            except Exception as e:
                logger.warning(f"Error updating status on pause: {e}")
            return
        # Skip excluded directories if they somehow got through (prowser cache, Photos Library paths, and ignore directories)
        is_excluded = False
        try:
            dir_normalized = os.path.abspath(os.path.realpath(directory)).rstrip(_SEP)
            if prowser_cache_normalized and (dir_normalized == prowser_cache_normalized or dir_normalized.startswith(prowser_cache_normalized + _SEP)):
                logger.debug(f"Skipping excluded directory: {directory}")
                is_excluded = True
            elif photos_resources_normalized and (dir_normalized == photos_resources_normalized or dir_normalized.startswith(photos_resources_normalized + _SEP)):
                logger.debug(f"Skipping excluded directory: {directory}")
                is_excluded = True
            elif photos_scopes_normalized and (dir_normalized == photos_scopes_normalized or dir_normalized.startswith(photos_scopes_normalized + _SEP)):
                logger.debug(f"Skipping excluded directory: {directory}")
                is_excluded = True
            else:
                # Check ignore directories
                for ignore_normalized in ignore_dirs_normalized:
                    if dir_normalized == ignore_normalized or dir_normalized.startswith(ignore_normalized + _SEP):
                        logger.debug(f"Skipping ignored directory: {directory}")
                        is_excluded = True
                        break
        except Exception:
            pass
        if is_excluded:
            continue
        if not os.path.exists(directory) or not os.path.isdir(directory):
            logger.warning(f"Directory does not exist or is not a directory: {directory}")
            continue
        
        try:
            # Calculate depth by counting path separators (rough estimate)
            # This helps verify we're processing subdirectories
            path_parts = directory.rstrip(_SEP).split(_SEP)
            depth = len([p for p in path_parts if p]) - 1  # -1 because root doesn't count
            depth_info = f" [depth: {depth}]"
            
            logger.debug(f"Processing directory{depth_info}: {directory}")
            # Get all image files in directory
            image_files = []
            for filename in os.listdir(directory):
                _, ext = os.path.splitext(filename)
                if ext.lower() in image_extensions:
                    filepath = f"{directory.rstrip(_SEP)}/{filename}"
                    if os.path.isfile(filepath):
                        image_files.append(filepath)
            
            if len(image_files) > 0:
                logger.debug(f"Found {len(image_files)} image files in {directory}{depth_info}")
            
            processed_count = 0
            cached_count = 0
            error_count = 0
            extractions_since_last_flush = 0  # Track extractions to avoid unnecessary flushes
            face_processed_count = 0
            face_cached_count = 0
            
            # Check if we should gather thumbnails (setting can change between directories)
            gather_thumbnails = config.load_settings().get('background_clip_gather_thumbnails', True)
            extract_faces = config.load_settings().get('background_clip_extract_faces', False)
            
            # Process each image
            for idx, image_path in enumerate(image_files):
                # Check for stop/pause command before each image for immediate interruption
                # This ensures the stop command is processed as soon as possible
                command = _get_command()
                if command:
                    if command == "stop":
                        # Stop immediately - don't wait for flush
                        logger.info(f"Stop command received, stopping image processing in {directory} (processed {idx}/{len(image_files)} images)")
                        # Only flush if we have pending extractions (quick flush before exit)
                        if extractions_since_last_flush > 0:
                            try:
                                feature_cache.flush_caches(async_flush=False)
                            except Exception:
                                pass  # Don't block shutdown if flush fails
                            _flush_face_cache_index_safe()
                        current_status["status"] = "stopped"
                        current_status["last_update"] = time.time()
                        _send_status_update(status_socket_path, current_status, logger)
                        return
                    elif command in ("pause", "flush_and_pause"):
                        logger.info(f"Pause command received, stopping image processing in {directory} (processed {idx}/{len(image_files)} images)")
                        # Update status to paused (socket-based)
                        try:
                            if command == "flush_and_pause":
                                # Flush before pausing (always flush on flush_and_pause command)
                                feature_cache.flush_caches(async_flush=False)
                                _flush_face_cache_index_safe()
                                current_status["status"] = "flushed_and_paused"
                                current_status["last_flush_time"] = time.time()
                                current_status["last_update"] = time.time()
                                _send_status_update(status_socket_path, current_status, logger)
                                logger.info("Flushed caches and paused")
                            else:
                                # Only flush if we have pending extractions
                                if extractions_since_last_flush > 0:
                                    feature_cache.flush_caches(async_flush=False)
                                    _flush_face_cache_index_safe()
                                current_status["status"] = "paused"
                                current_status["last_update"] = time.time()
                                _send_status_update(status_socket_path, current_status, logger)
                                logger.info("Paused")
                        except Exception as e:
                            logger.warning(f"Error updating status on pause: {e}")
                        return
                
                try:
                    # Get filename for logging
                    fname = image_path.rsplit("/", 1)[-1]

                    # Check if thumbnail is already cached - only gather when setting is enabled
                    if gather_thumbnails:
                        existing_thumbnail = image_cache.get_thumbnail_sync(image_path, MIN_THUMBNAIL_SIZE)
                        if existing_thumbnail is None:
                            # Generate and cache thumbnail for this image at MIN_THUMBNAIL_SIZE
                            try:
                                logger.debug(f"Generating thumbnail for {image_path}")
                                # Generate thumbnail directly using EXIF loader
                                pil_thumb = load_thumbnail_pil_with_exif_correction(
                                    image_path, MIN_THUMBNAIL_SIZE, ignore_exif=False
                                )
                                if pil_thumb is not None:
                                    image_cache.cache_thumbnail_sync(image_path, pil_thumb, MIN_THUMBNAIL_SIZE)
                                    logger.info(f"New thumbnail cache entry created for {image_path}")
                                else:
                                    logger.info(f"Thumbnail generation returned no image for {image_path}")
                            except Exception as e:
                                # Don't fail the entire process if thumbnail generation fails
                                logger.info(f"Thumbnail generation failed for {image_path}: {e}")

                    # Extract faces when setting is enabled (skip if already cached)
                    # Skip when foreground face scan is active - foreground has priority, no concurrent face gathering
                    # Use same path normalization and cache semantics as foreground (face_scan_runner.run_scan)
                    if extract_faces:
                        try:
                            from faces.face_gathering_coordinator import is_foreground_face_scan_active
                            if not is_foreground_face_scan_active():
                                from faces.face_cache import normalize_path_for_face_cache
                                from faces.face_engine import is_available as face_engine_available
                                from faces.face_engine import encode_faces_from_path as face_encode
                                from faces.face_cache import has_cached_faces as face_has_cached
                                from faces.face_cache import set_encodings as face_set_encodings
                                path_for_face = normalize_path_for_face_cache(image_path)
                                if face_engine_available() and not face_has_cached(path_for_face):
                                    encodings = face_encode(image_path)
                                    face_set_encodings(path_for_face, encodings)  # store both positive and negative
                                    face_processed_count += 1
                                    if face_processed_count == 1:
                                        logger.info(f"Face extraction started for {directory} ({len(image_files)} images)")
                                    if encodings:
                                        face_cached_count += 1
                                        if face_cached_count <= 5 or face_cached_count % 50 == 0:
                                            logger.info(f"Face extraction: cached {face_cached_count} images with faces in {directory} (latest: {fname})")
                        except Exception as e:
                            logger.debug(f"Face extraction skipped for {image_path}: {e}")

                    # Check if already cached
                    stat = os.stat(image_path)
                    mtime = stat.st_mtime
                    size = stat.st_size

                    # Check if already in cache
                    cached_feat = feature_cache.get_clip_feature(image_path, mtime, size, device='cpu')
                    if cached_feat is not None:
                        cached_count += 1
                        # logger.info(f"Not Extracted: {fname}")
                        continue  # Already cached, skip

                    # Extract CLIP feature
                    feat = cnn_sorter._get_clip_image_feature(image_path)
                    if feat is not None:
                        processed_count += 1
                        extractions_since_last_flush += 1
                        logger.info(f"Extracted    : {fname}")
                        # Debug print to stdout
                        # if DEBUG_PRINT_EXTRACTIONS:
                        #     print(f"Extracting CLIP data: {fname}")
                        # Feature is automatically stored in cache by _get_clip_image_feature

                        if processed_count % 50 == 0:
                            total_images = len(image_files)
                            logger.info(f"Processed {processed_count}/{total_images} CLIP images from {directory}")
                    else:
                        # Extraction failed but no exception was raised
                        logger.warning(f"Extraction failed: {fname}")
                    
                    # Flush periodically (every 50 images) to avoid memory buildup
                    # Only flush if we actually extracted features since last flush
                    # Check for stop command before flushing to avoid blocking shutdown
                    if (idx + 1) % 50 == 0:
                        # Check for stop command before flush (already checked above, but double-check)
                        command = _get_command()
                        if command == "stop":
                            # Stop immediately without flushing
                            logger.info(f"Stop command received before CLIP flush, stopping immediately (processed {idx}/{len(image_files)} images)")
                            current_status["status"] = "stopped"
                            current_status["last_update"] = time.time()
                            _send_status_update(status_socket_path, current_status, logger)
                            return
                        
                        if extractions_since_last_flush > 0:
                            feature_cache.flush_caches(async_flush=False)
                            _flush_face_cache_index_safe()
                            extractions_since_last_flush = 0  # Reset counter after flush
                
                except Exception as e:
                    error_count += 1
                    logger.warning(f"Error processing {image_path}: {e}")
                    continue
            
            # Final flush for this directory (only if we have pending extractions)
            # Check for stop command before final flush
            command = _get_command()
            if command == "stop":
                logger.info(f"Stop command received before final CLIP flush, stopping immediately")
                current_status["status"] = "stopped"
                current_status["last_update"] = time.time()
                _send_status_update(status_socket_path, current_status, logger)
                return
            
            if extractions_since_last_flush > 0:
                feature_cache.flush_caches(async_flush=False)
                _flush_face_cache_index_safe()
            if extract_faces and face_processed_count > 0:
                logger.info(f"Face extraction completed for {directory}: {face_processed_count} processed, {face_cached_count} with faces")
            if processed_count > 0:
                logger.info(f"Completed {directory}: processed={processed_count}, cached={cached_count}, errors={error_count}")
            else:
                logger.debug(f"Completed {directory}: processed={processed_count}, cached={cached_count}, errors={error_count}")
        
        except PermissionError:
            # logger.error(f"CLIP background: Permission error processing directory {directory}")
            continue
        except Exception as e:
            logger.error(f"Error processing directory {directory}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            continue


def _setup_command_socket(socket_path: Path, logger: logging.Logger) -> Optional[socket.socket]:
    """Setup Unix domain socket server for receiving commands
    
    Args:
        socket_path: Path to socket file
        logger: Logger instance
        
    Returns:
        Socket server object or None if setup failed
    """
    try:
        # Remove existing socket file if it exists
        if socket_path.exists():
            socket_path.unlink()
        
        # Create Unix domain socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(socket_path))
        sock.listen(1)
        sock.setblocking(False)  # Non-blocking for select()
        logger.info(f"Command socket created at {socket_path}")
        return sock
    except Exception as e:
        logger.error(f"Failed to setup command socket: {e}")
        return None


def _wait_for_command(sock: socket.socket, timeout: float, logger: logging.Logger) -> Optional[dict]:
    """Wait for command via socket with timeout
    
    Args:
        sock: Socket server object
        timeout: Timeout in seconds (0.0 for non-blocking check)
        logger: Logger instance
        
    Returns:
        Command data dict if received, None if timeout or error
    """
    try:
        # Use select() to wait for connection with timeout
        ready, _, _ = select.select([sock], [], [], timeout)
        
        if not ready:
            return None  # Timeout
        
        # Accept connection
        try:
            conn, _ = sock.accept()
        except OSError:
            return None  # Connection error
        
        try:
            # Read data from connection
            data_parts = []
            conn.settimeout(1.0)  # Timeout for reading
            
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data_parts.append(chunk)
            
            # Parse JSON command
            if data_parts:
                data = b''.join(data_parts).decode('utf-8')
                command_data = json.loads(data)
                return command_data
            return None
        finally:
            conn.close()
    except socket.timeout:
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse command JSON: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error receiving command: {e}")
        return None


def _send_status_update(status_socket_path: Optional[Path], status_data: dict, logger: logging.Logger):
    """Send status update via socket (event-driven, no file fallback)
    
    Args:
        status_socket_path: Path to status socket (None if not yet available)
        status_data: Status data dict with "status" and optionally "last_flush_time"
        logger: Logger instance
    """
    if status_socket_path is None or not status_socket_path.exists():
        logger.debug(f"Status socket not available: {status_socket_path}")
        return  # Status socket not available yet
    
    try:
        # Prepare status data
        update_data = {
            "status": status_data.get("status", "unknown"),
            "last_update": time.time()
        }
        
        if "last_flush_time" in status_data:
            update_data["last_flush_time"] = status_data["last_flush_time"]
        
        # Send via socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)  # Increased timeout
        sock.connect(str(status_socket_path))
        
        # Send JSON data
        data = json.dumps(update_data).encode('utf-8')
        sock.sendall(data)
        sock.close()
        logger.debug(f"Sent status update: {update_data.get('status', 'unknown')}")
    except Exception as e:
        # Log failures - this helps debug connection issues
        logger.debug(f"Failed to send status update to {status_socket_path}: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Write to stderr so parent process can capture it
        import sys
        import traceback
        sys.stderr.write(f"Worker process exception: {e}\n")
        sys.stderr.write(traceback.format_exc())
        sys.exit(1)
