#!/usr/bin/env python3
"""
Directory Watch Manager
Watches the current directory for filesystem changes via QFileSystemWatcher (FSEvents on macOS).
Debounces notifications and emits FILES_CHANGED_ON_DISK for RefreshManager to handle.
"""

import os
from typing import Optional

from PySide6.QtCore import QFileSystemWatcher, QTimer

from event_bus import FILES_CHANGED_ON_DISK

_DEBOUNCE_MS = 300


class DirectoryWatchManager:
    """Debounced QFileSystemWatcher for single-directory auto-refresh."""

    def __init__(self, main_window):
        self.main_window = main_window
        self._watcher = QFileSystemWatcher(main_window)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._watched_path: Optional[str] = None
        self._debounce_timer = QTimer(main_window)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._emit_files_changed)

    def sync_watcher_state(self) -> None:
        """Start, stop, or re-arm the watcher based on current app mode."""
        watch_path = self._resolve_watch_path()
        if watch_path:
            self._set_watched_path(watch_path)
        else:
            self._clear_watch()

    def _resolve_watch_path(self) -> Optional[str]:
        if not self._should_watch():
            return None
        directory = getattr(self.main_window, "current_directory", None)
        if not directory or not os.path.isdir(directory):
            return None
        return os.path.abspath(directory)

    def _should_watch(self) -> bool:
        mw = self.main_window
        if getattr(mw, "specific_files_active", False):
            return False
        if getattr(mw, "reference_graph_active", False):
            return False
        directory = getattr(mw, "current_directory", None)
        if not directory or not os.path.isdir(directory):
            return False
        displayed = mw.get_displayed_images() if hasattr(mw, "get_displayed_images") else []
        if displayed:
            current_dir = os.path.abspath(directory)
            for path in displayed:
                try:
                    if os.path.dirname(os.path.abspath(path)) != current_dir:
                        return False
                except (OSError, ValueError):
                    return False
        return True

    def _set_watched_path(self, path: str) -> None:
        if self._watched_path == path:
            return
        self._clear_watch()
        if self._watcher.addPath(path):
            self._watched_path = path

    def _clear_watch(self) -> None:
        if self._watched_path:
            try:
                self._watcher.removePath(self._watched_path)
            except Exception:
                pass
            self._watched_path = None

    def _on_directory_changed(self, path: str) -> None:
        if not self._should_watch():
            return
        current = getattr(self.main_window, "current_directory", None)
        if not current:
            return
        try:
            if os.path.abspath(path) != os.path.abspath(current):
                return
        except (OSError, ValueError):
            return
        self._debounce_timer.stop()
        self._debounce_timer.start(_DEBOUNCE_MS)

    def _emit_files_changed(self) -> None:
        if getattr(self.main_window, "_refresh_in_progress", False):
            return
        if not self._should_watch():
            return
        directory = getattr(self.main_window, "current_directory", None)
        if not directory:
            return
        event_bus = getattr(self.main_window, "event_bus", None)
        if event_bus:
            event_bus.emit(FILES_CHANGED_ON_DISK, directory)
