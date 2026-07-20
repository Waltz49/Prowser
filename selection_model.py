#!/usr/bin/env python3
"""Selection state model for multi-select operations."""

from typing import Optional, Set

from PySide6.QtCore import QObject, Signal, QMutexLocker, QRecursiveMutex


class SelectionModel(QObject):
    """Holds multi-select state; emits selection_changed for bridge/subscribers."""

    selection_changed = Signal(set, object)  # selected_files copy, optional highlight_index

    def __init__(self):
        super().__init__()
        self._mutex = QRecursiveMutex()
        self._selected_files: Set[str] = set()
        self.range_anchor_index: Optional[int] = None
        self.cmd_multi_origin_index: Optional[int] = None
        self.cmd_multi_axis: Optional[str] = None
        self.cmd_multi_sign: int = 0
        self.last_clicked_index: Optional[int] = None
        self.most_recent_selected_index: Optional[int] = None

    @property
    def selected_files(self) -> Set[str]:
        """Mutable set reference for in-place .add/.clear compatibility."""
        return self._selected_files

    @selected_files.setter
    def selected_files(self, value: Set[str]) -> None:
        with QMutexLocker(self._mutex):
            self._selected_files = set(value) if value is not None else set()

    @property
    def multi_select_mode(self) -> bool:
        return len(self._selected_files) > 1

    def emit_selection_changed(self, highlight_index: Optional[int] = None) -> None:
        with QMutexLocker(self._mutex):
            selected = set(self._selected_files)
        self.selection_changed.emit(selected, highlight_index)
