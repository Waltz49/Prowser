"""
Background image discovery for the file tree filter.

Deep recursive directory walks run off the GUI thread. Results are delivered
back to CustomFileSystemFilter on the main thread via Qt signals.
"""

from __future__ import annotations

import fnmatch
import heapq
import os
import threading
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from config import ImageBrowserConfig, get_config
from path_exclusions import _get_excluded_paths
from thumbnails.thumbnail_constants import SKIPPED_PATTERNS, get_image_extensions
from utils import is_inside_photos_library_resources_or_scopes


def _get_enabled_root_directories() -> Set[str]:
    try:
        config = get_config()
        settings = config.load_settings()
        enabled = settings.get("root_directories", ["/Users", "/Volumes", "/tmp"])
        if not isinstance(enabled, list):
            enabled = ["/Users", "/Volumes", "/tmp"]
        normalized = []
        for dir_path in enabled:
            if dir_path.startswith("/"):
                normalized.append(dir_path)
            else:
                normalized.append(f"/{dir_path}")
        return set(normalized)
    except Exception:
        return {"/Users", "/Volumes", "/tmp"}


def _get_show_hidden_directories() -> bool:
    try:
        config = get_config()
        settings = config.load_settings()
        return settings.get("show_hidden_directories", False)
    except Exception:
        return False


def _get_follow_symlinks() -> bool:
    try:
        config = get_config()
        settings = config.load_settings()
        return settings.get("follow_symlinks", False)
    except Exception:
        return False



def _filter_walk_symlink_dirs(
    root: str,
    dirs: List[str],
    follow_symlinks: bool,
    enabled_root_dirs: Set[str],
) -> None:
    if follow_symlinks:
        return
    dirs[:] = [
        d
        for d in dirs
        if not os.path.islink(os.path.join(root, d))
        or os.path.normpath(os.path.join(root, d)) in enabled_root_dirs
    ]


def _resolve_paths_on_main_thread(paths: Iterable[str]) -> Tuple[str, ...]:
    """Resolve exclusion paths once on the GUI thread (realpath may fault off-thread on network FS)."""
    resolved: List[str] = []
    for path in paths:
        if not path:
            continue
        try:
            resolved.append(os.path.realpath(path))
        except (OSError, ValueError):
            try:
                resolved.append(os.path.abspath(os.path.normpath(path)))
            except (OSError, ValueError):
                resolved.append(os.path.normpath(path))
    return tuple(resolved)


def _worker_safe_path(path: str) -> str:
    """Path key for comparisons in the background worker — no realpath."""
    try:
        return os.path.abspath(os.path.normpath(path))
    except (OSError, ValueError):
        return os.path.normpath(path)


def _is_excluded_in_worker(
    path: str,
    excluded_resolved: Tuple[str, ...],
    cache_dir_resolved: Optional[str],
) -> bool:
    try:
        path_key = _worker_safe_path(path)
        for excl in excluded_resolved:
            if path_key == excl or path_key.startswith(excl + os.sep):
                return True
        if cache_dir_resolved:
            if path_key == cache_dir_resolved or path_key.startswith(cache_dir_resolved + os.sep):
                return True
    except Exception:
        pass
    return False


@dataclass(frozen=True)
class TreeImageCheckContext:
    """Immutable snapshot of filter settings for a background walk."""

    max_depth: int
    mode: str
    filter_pattern_key: str
    match_pattern: Optional[str]
    process_hidden: bool
    follow_symlinks: bool
    enabled_root_dirs: FrozenSet[str]
    excluded_paths_resolved: Tuple[str, ...]
    cache_dir_resolved: Optional[str]
    image_exts: Tuple[str, ...]
    prioritized_exts: Tuple[str, ...]
    other_exts: Tuple[str, ...]

    def cache_key_for(self, dir_path: str) -> str:
        return f"{dir_path}:{self.max_depth}:{self.mode}:{self.filter_pattern_key}"


def build_tree_image_check_context(
    mode: str,
    filter_pattern: Optional[str],
    *,
    max_depth: Optional[int] = None,
    process_hidden: Optional[bool] = None,
    follow_symlinks: Optional[bool] = None,
    enabled_root_dirs: Optional[Set[str]] = None,
) -> TreeImageCheckContext:
    """Build a context snapshot from current settings."""
    try:
        config = get_config()
        settings = config.load_settings()
        if max_depth is None:
            max_depth = int(settings.get("search_depth", 4))
        excluded_paths = _get_excluded_paths(config)
        excluded_paths_resolved = _resolve_paths_on_main_thread(excluded_paths)
        try:
            cache_dir_resolved = os.path.realpath(str(config.cache_dir))
        except Exception:
            try:
                cache_dir_resolved = os.path.abspath(os.path.normpath(str(config.cache_dir)))
            except Exception:
                cache_dir_resolved = None
    except Exception:
        max_depth = max_depth if max_depth is not None else 4
        excluded_paths_resolved = ()
        cache_dir_resolved = None

    if process_hidden is None:
        process_hidden = _get_show_hidden_directories()
    if follow_symlinks is None:
        follow_symlinks = _get_follow_symlinks()
    if enabled_root_dirs is None:
        enabled_root_dirs = _get_enabled_root_directories()

    filter_pattern_key = ""
    match_pattern = None
    if mode == "use_filter" and filter_pattern:
        filter_pattern_key = filter_pattern
        match_pattern = ImageBrowserConfig.get_filter_pattern_for_matching(filter_pattern)

    image_exts = tuple(e.lstrip(".").lower() for e in get_image_extensions() if e)
    prioritized: List[str] = []
    other = list(image_exts)
    if "jpg" in other:
        prioritized.append("jpg")
        other.remove("jpg")
    if "jpeg" in other:
        prioritized.append("jpeg")
        other.remove("jpeg")

    return TreeImageCheckContext(
        max_depth=max_depth,
        mode=mode,
        filter_pattern_key=filter_pattern_key,
        match_pattern=match_pattern,
        process_hidden=process_hidden,
        follow_symlinks=follow_symlinks,
        enabled_root_dirs=frozenset(enabled_root_dirs),
        excluded_paths_resolved=excluded_paths_resolved,
        cache_dir_resolved=cache_dir_resolved,
        image_exts=image_exts,
        prioritized_exts=tuple(prioritized),
        other_exts=tuple(other),
    )


def deep_check_has_images(dir_path: str, context: TreeImageCheckContext) -> bool:
    """Recursive image check (safe to call off the GUI thread)."""
    if context.mode == "all":
        return True
    if not os.path.isdir(dir_path):
        return False
    if not context.image_exts:
        return False

    def matches(fname: str) -> bool:
        basename = os.path.basename(fname)
        ext = os.path.splitext(basename)[1][1:].lower()
        if ext not in context.image_exts:
            return False
        if context.mode == "use_filter" and context.match_pattern and context.match_pattern != "*":
            return fnmatch.fnmatch(basename, context.match_pattern)
        return True

    if dir_path.endswith(os.sep):
        basecount = dir_path.rstrip(os.sep).count(os.sep)
    else:
        basecount = dir_path.count(os.sep)

    try:
        for root, dirs, files in os.walk(dir_path):
            if _is_excluded_in_worker(root, context.excluded_paths_resolved, context.cache_dir_resolved):
                dirs.clear()
                continue

            rel_depth = root.count(os.sep) - basecount
            if rel_depth >= context.max_depth:
                dirs.clear()
                continue

            if not context.process_hidden:
                dirs[:] = [d for d in dirs if not d.startswith(".")]

            _filter_walk_symlink_dirs(
                root,
                dirs,
                context.follow_symlinks,
                set(context.enabled_root_dirs),
            )

            skip_dir = False
            for pattern in SKIPPED_PATTERNS:
                if pattern in root:
                    skip_dir = True
                    break
            if skip_dir:
                dirs.clear()
                continue

            try:
                if is_inside_photos_library_resources_or_scopes(root):
                    dirs.clear()
                    continue
            except Exception:
                pass

            for fname in files:
                ext = os.path.splitext(fname)[1][1:].lower()
                if ext in context.prioritized_exts and matches(fname):
                    return True

            for fname in files:
                ext = os.path.splitext(fname)[1][1:].lower()
                if ext in context.other_exts and matches(fname):
                    return True
    except Exception:
        return False
    return False


class _TreeImageDiscoveryWorker(QObject):
    """Processes queued directory checks on a background thread (priority heap)."""

    result_ready = Signal(str, str, bool)

    def __init__(self) -> None:
        super().__init__()
        # (priority, sequence, dir_path, cache_key, context) — lower priority value = sooner
        self._heap: List[Tuple[int, int, str, str, TreeImageCheckContext]] = []
        self._queued_priorities: Dict[str, int] = {}
        self._sequence: int = 0
        self._lock = threading.Lock()
        self._active = True
        self._processing = False

    def shutdown(self) -> None:
        with self._lock:
            self._active = False
            self._heap.clear()
            self._queued_priorities.clear()

    @Slot(str, str, object, int)
    def enqueue(
        self,
        dir_path: str,
        cache_key: str,
        context: TreeImageCheckContext,
        priority: int = 2,
    ) -> None:
        with self._lock:
            if not self._active:
                return
            existing = self._queued_priorities.get(cache_key)
            if existing is not None and priority >= existing:
                return
            self._queued_priorities[cache_key] = priority
            self._sequence += 1
            heapq.heappush(self._heap, (priority, self._sequence, dir_path, cache_key, context))
            should_start = not self._processing

        if should_start:
            self._process_next()

    def _pop_next_item(self) -> Optional[Tuple[str, str, TreeImageCheckContext]]:
        with self._lock:
            while self._heap:
                priority, _seq, dir_path, cache_key, context = heapq.heappop(self._heap)
                if not self._active:
                    return None
                if self._queued_priorities.get(cache_key) != priority:
                    continue
                del self._queued_priorities[cache_key]
                return dir_path, cache_key, context
            return None

    @Slot()
    def _process_next(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._processing = True

        while True:
            item = self._pop_next_item()
            if item is None:
                with self._lock:
                    self._processing = False
                return

            dir_path, cache_key, context = item
            try:
                found = deep_check_has_images(dir_path, context)
            except Exception:
                found = False

            with self._lock:
                if not self._active:
                    self._processing = False
                    return

            self.result_ready.emit(dir_path, cache_key, found)


class TreeImageDiscoveryService(QObject):
    """Owns the background thread used for deep tree image checks."""

    _enqueue_signal = Signal(str, str, object, int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = _TreeImageDiscoveryWorker()
        self._worker.moveToThread(self._thread)
        self._enqueue_signal.connect(
            self._worker.enqueue,
            Qt.ConnectionType.QueuedConnection,
        )
        self.result_ready = self._worker.result_ready
        self._thread.start()

    def submit(
        self,
        dir_path: str,
        cache_key: str,
        context: TreeImageCheckContext,
        priority: int = 2,
    ) -> None:
        self._enqueue_signal.emit(dir_path, cache_key, context, priority)

    def shutdown(self) -> None:
        self._worker.shutdown()
        if self._thread.isRunning():
            self._thread.quit()
            if not self._thread.wait(3000):
                self._thread.terminate()
                self._thread.wait(1000)
