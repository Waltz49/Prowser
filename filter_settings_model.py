#!/usr/bin/env python3
"""
Filter Settings Model
Single source of truth for filter_pattern and filtered_tree (tree filter mode).
"""

from typing import Optional

from PySide6.QtCore import QObject, Signal, QMutexLocker, QRecursiveMutex

from config import ImageBrowserConfig, get_config

_VALID_FILTERED_TREE_MODES = frozenset({"all", "images", "use_filter"})


class FilterSettingsModel(QObject):
    """Centralized model for browse filter pattern and tree filter mode."""

    filter_pattern_changed = Signal(str)
    filtered_tree_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._filter_pattern: Optional[str] = "*"
        self._filtered_tree: str = "images"
        self._mutex = QRecursiveMutex()

    def get_filter_pattern(self) -> Optional[str]:
        with QMutexLocker(self._mutex):
            return self._filter_pattern

    def get_filtered_tree(self) -> str:
        with QMutexLocker(self._mutex):
            return self._filtered_tree

    def set_filter_pattern(
        self,
        pattern: Optional[str],
        *,
        persist: bool = True,
        notify: bool = True,
    ) -> None:
        normalized = ImageBrowserConfig.normalize_filter_pattern(pattern)
        with QMutexLocker(self._mutex):
            if normalized == self._filter_pattern:
                return
            self._filter_pattern = normalized
        if persist:
            get_config().update_setting("filter_pattern", normalized)
        if notify:
            self.filter_pattern_changed.emit(normalized)

    def set_filtered_tree(
        self,
        mode: str,
        *,
        persist: bool = True,
        notify: bool = True,
    ) -> None:
        if isinstance(mode, bool):
            mode = "use_filter" if mode else "images"
        if mode not in _VALID_FILTERED_TREE_MODES:
            mode = "images"
        with QMutexLocker(self._mutex):
            if mode == self._filtered_tree:
                return
            self._filtered_tree = mode
        if persist:
            get_config().update_setting("filtered_tree", mode)
        if notify:
            self.filtered_tree_changed.emit(mode)

    def load_from_settings(self, settings: dict, *, notify: bool = False) -> None:
        """Load filter state from a settings dict (startup / batch restore)."""
        saved_filter = settings.get("filter_pattern", "")
        normalized_pattern = ImageBrowserConfig.normalize_filter_pattern(saved_filter)
        filtered_tree = settings.get("filtered_tree", "images")
        if filtered_tree not in _VALID_FILTERED_TREE_MODES:
            filtered_tree = "images"

        pattern_changed = False
        mode_changed = False
        with QMutexLocker(self._mutex):
            if normalized_pattern != self._filter_pattern:
                self._filter_pattern = normalized_pattern
                pattern_changed = True
            if filtered_tree != self._filtered_tree:
                self._filtered_tree = filtered_tree
                mode_changed = True

        if notify:
            if pattern_changed:
                self.filter_pattern_changed.emit(normalized_pattern)
            if mode_changed:
                self.filtered_tree_changed.emit(filtered_tree)
