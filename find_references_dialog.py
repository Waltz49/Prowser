#!/usr/bin/env python3
"""Dialog listing images whose EXIF User Comment references the current image."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QEvent, Qt, QSize
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import ImageBrowserConfig, get_config
from reference_graph import open_reference_graph_for_path, path_is_referenced_in_exif
from theme_service import get_active_theme
from utils import (
    _dialog_thumbnail_border_color,
    create_titled_progress_dialog,
    ensure_dialog_fits_screen,
    load_dialog_thumbnail,
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_information,
    show_styled_warning,
)

_THUMB_SIZE = 128
_GRID_GAP = 14
_GRID_V_GAP = 18
_FILENAME_EXTRA_H = 22
_GEOMETRY_KEY = "find_references_dialog_geometry"


def _set_label_text_color(label: QLabel, color) -> None:
    """Theme text color without stylesheet (avoids Qt parse warnings next to pixmap labels)."""
    c = color if isinstance(color, QColor) else QColor(str(color))
    if not c.isValid():
        return
    pal = label.palette()
    pal.setColor(QPalette.ColorRole.WindowText, c)
    label.setPalette(pal)


def _thumbnail_widget(file_path: str, size: int) -> QFrame:
    """Thumbnail in a framed QFrame — no stylesheet on the pixmap QLabel."""
    border = QColor(_dialog_thumbnail_border_color())
    if not border.isValid():
        border = QColor("#808080")
    frame = QFrame()
    frame.setFixedSize(size, size)
    frame.setStyleSheet(f"QFrame {{ border: 1px solid {border.name()}; }}")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(2, 2, 2, 2)
    img = QLabel()
    img.setAlignment(Qt.AlignmentFlag.AlignCenter)
    px = load_dialog_thumbnail(file_path, size)
    if px and not px.isNull():
        img.setPixmap(px)
    lay.addWidget(img)
    return frame


@dataclass
class _ReferencingSplit:
    matching_filter: List[str]
    not_matching_filter: List[str]


def _filter_active(main_window) -> bool:
    pattern = getattr(main_window, "filter_pattern", None)
    if not pattern:
        return False
    mp = ImageBrowserConfig.get_filter_pattern_for_matching(pattern)
    return bool(mp and mp != "*")


def _split_by_filter(main_window, paths: List[str]) -> _ReferencingSplit:
    if not _filter_active(main_window):
        return _ReferencingSplit(list(paths), [])
    sm = getattr(main_window, "sorting_manager", None)
    if not sm:
        return _ReferencingSplit(list(paths), [])
    matched = set(sm.filter_images_by_pattern(paths))
    matching = [p for p in paths if p in matched]
    not_matching = [p for p in paths if p not in matched]
    return _ReferencingSplit(matching, not_matching)


def _collect_search_candidate_paths(main_window) -> List[str]:
    """All folder images (no filter) plus thumbnail / specific-files list."""
    seen: set[str] = set()
    out: List[str] = []

    def add(path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        key = os.path.normpath(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            out.append(path)

    loader = getattr(main_window, "directory_loader", None)
    current_dir = getattr(main_window, "current_directory", None)
    if loader and current_dir and os.path.isdir(current_dir):
        raw = loader._get_current_directory_files()
        if raw:
            files = list(raw)
            if hasattr(main_window, "sorting_manager"):
                files = main_window.sorting_manager.apply_display_order(
                    files, current_dir
                )
            for path in files:
                add(path)

    for path in getattr(main_window, "displayed_images", None) or []:
        add(path)

    return out


class _ReferenceThumbCell(QWidget):
    def __init__(
        self, main_window, file_path: str, dialog: "FindReferencesDialog", parent=None
    ):
        super().__init__(parent)
        self._main_window = main_window
        self._file_path = file_path
        self._dialog = dialog
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(
            _thumbnail_widget(file_path, _THUMB_SIZE),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        cap = QLabel(os.path.basename(file_path))
        cap.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        cap.setWordWrap(True)
        cap.setMaximumWidth(_THUMB_SIZE + 12)
        f = QFont(cap.font())
        f.setPointSize(10)
        cap.setFont(f)
        _set_label_text_color(cap, get_active_theme().dialog_text_color_hex)
        lay.addWidget(cap, 0, Qt.AlignmentFlag.AlignHCenter)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dialog.accept()
            open_reference_graph_for_path(self._main_window, self._file_path)
            event.accept()
            return
        super().mousePressEvent(event)


class _FlowThumbnailGrid(QWidget):
    def __init__(
        self, main_window, paths: List[str], dialog: "FindReferencesDialog", parent=None
    ):
        super().__init__(parent)
        self._dialog = dialog
        self._cells = [
            _ReferenceThumbCell(main_window, p, dialog, self) for p in paths
        ]
        self._last_cols: Optional[int] = None
        self._reflow_guard = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(_GRID_GAP)
        self._grid.setVerticalSpacing(_GRID_V_GAP)

    def _cols_for_width(self, width: int) -> int:
        w = max(width, 320) if width > 0 else 320
        stride = _THUMB_SIZE + _GRID_GAP
        return max(1, (w + _GRID_GAP) // stride)

    def _content_height(self, cols: int) -> int:
        n = len(self._cells)
        if not n:
            return 0
        rows = (n + cols - 1) // cols
        return rows * (_THUMB_SIZE + _FILENAME_EXTRA_H + _GRID_V_GAP) - _GRID_V_GAP

    def reflow_to_width(self, width: int) -> None:
        if self._reflow_guard or not self._cells or width <= 0:
            return
        cols = self._cols_for_width(width)
        if cols == self._last_cols and self._grid.count() == len(self._cells):
            return
        self._reflow_guard = True
        try:
            for cell in self._cells:
                self._grid.removeWidget(cell)
            self._last_cols = cols
            for i, cell in enumerate(self._cells):
                r, c = divmod(i, cols)
                self._grid.addWidget(
                    cell,
                    r,
                    c,
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
                )
        finally:
            self._reflow_guard = False
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        w = max(self.width(), 320)
        return QSize(w, self._content_height(self._cols_for_width(w)))

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self._content_height(self._cols_for_width(max(self.width(), 1))))


class FindReferencesDialog(QDialog):
    def __init__(
        self,
        main_window,
        target_path: str,
        split: _ReferencingSplit,
        parent=None,
    ):
        super().__init__(parent or main_window)
        self._main_window = main_window
        self._target_path = target_path
        self._config = (
            main_window.config if hasattr(main_window, "config") else get_config()
        )
        self.setWindowTitle(f"References to {os.path.basename(target_path)}")
        self.setModal(True)
        self._setup_ui(split)
        self.finished.connect(self._save_geometry)

    def _reflow_grids(self) -> None:
        if not hasattr(self, "_scroll"):
            return
        w = self._scroll.viewport().width()
        for grid in self.findChildren(_FlowThumbnailGrid):
            grid.reflow_to_width(w)

    def eventFilter(self, obj, event) -> bool:
        if (
            hasattr(self, "_scroll")
            and obj is self._scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._reflow_grids()
        return super().eventFilter(obj, event)

    def _add_section(
        self,
        body: QWidget,
        body_layout: QVBoxLayout,
        title: str,
        paths: List[str],
        heading_hex: str,
    ) -> None:
        if not paths:
            return
        h = QLabel(title)
        hf = QFont(h.font())
        hf.setBold(True)
        hf.setPointSize(13)
        h.setFont(hf)
        _set_label_text_color(h, heading_hex)
        body_layout.addWidget(h)
        body_layout.addWidget(_FlowThumbnailGrid(self._main_window, paths, self, body))

    def _setup_ui(self, split: _ReferencingSplit) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        t = get_active_theme()

        header = QHBoxLayout()
        header.setSpacing(14)
        header.addWidget(_thumbnail_widget(self._target_path, _THUMB_SIZE))
        intro = QLabel(
            f"EXIF user comments referencing {os.path.basename(self._target_path)}. "
            "Click an image to open its reference graph."
        )
        intro.setWordWrap(True)
        f = QFont(intro.font())
        f.setPointSize(12)
        intro.setFont(f)
        _set_label_text_color(intro, t.dialog_text_color_hex)
        header.addWidget(intro, 1)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(12)

        if _filter_active(self._main_window):
            self._add_section(
                body,
                body_lay,
                "Matching current filter",
                split.matching_filter,
                t.heading_color_hex(),
            )
            self._add_section(
                body,
                body_lay,
                "Not matching current filter",
                split.not_matching_filter,
                t.heading_color_hex(),
            )
        else:
            body_lay.addWidget(
                _FlowThumbnailGrid(self._main_window, split.matching_filter, self, body)
            )

        body_lay.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self._scroll = scroll
        scroll.viewport().installEventFilter(self)

        btns = QHBoxLayout()
        btns.addStretch()
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        btns.addStretch()
        root.addLayout(btns)
        self.setMinimumSize(400, 280)
        self.resize(520, 400)

    def showEvent(self, event) -> None:
        try:
            geom = self._config.load_settings().get(_GEOMETRY_KEY)
            if geom:
                restore_dialog_geometry_hex(self, geom, self.parent())
        except Exception:
            pass
        super().showEvent(event)
        self._reflow_grids()

    def _save_geometry(self, *_args) -> None:
        try:
            self._config.update_setting(_GEOMETRY_KEY, save_dialog_geometry_hex(self))
        except Exception:
            pass


def find_and_show_references_dialog(main_window, target_path: str) -> None:
    if not target_path or not os.path.isfile(target_path):
        show_styled_warning(main_window, "Find References", "No image selected.")
        return

    candidates = _collect_search_candidate_paths(main_window)
    if not candidates:
        show_styled_information(
            main_window, "Find References", "No images are available to search."
        )
        return

    progress = None
    if len(candidates) > 40:
        progress = create_titled_progress_dialog(
            main_window,
            "Find References",
            len(candidates),
            label="Searching EXIF user comments for references…",
        )

    referencing: List[str] = []
    for i, cand in enumerate(candidates):
        if progress and progress.wasCanceled():
            break
        if path_is_referenced_in_exif(cand, target_path):
            referencing.append(cand)
        if progress:
            progress.setValue(i + 1)
            QApplication.processEvents()
    if progress:
        progress.close()

    if not referencing:
        show_styled_information(
            main_window,
            "No References Found",
            f'No other images reference "{os.path.basename(target_path)}" '
            "in their EXIF user comment.",
        )
        return

    FindReferencesDialog(
        main_window, target_path, _split_by_filter(main_window, referencing)
    ).exec()
