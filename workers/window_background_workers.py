#!/usr/bin/env python3
"""Background QThread workers used by the main image browser window."""

import os
import threading
import time
from typing import List, Optional, Tuple

from PySide6.QtCore import QThread, Signal


def person_search_build_displayed_paths(
    recursive: bool,
    search_directory: Optional[str],
    current_dir: str,
    current_displayed: List[str],
    filter_pattern: Optional[str],
    max_depth: int,
) -> List[str]:
    """Collect image paths for person search (same rules as filter_by_person). Intended for a worker thread."""
    from faces.face_scan_runner import get_image_list
    from faces.face_cache import normalize_path_for_face_cache

    resolved_sd = None
    if search_directory and search_directory.strip():
        resolved_sd = os.path.expanduser(search_directory.strip())

    displayed: List[str] = []
    if recursive:
        if resolved_sd and os.path.isdir(resolved_sd):
            search_dir = resolved_sd
        else:
            search_dir = current_dir
        if resolved_sd and os.path.isdir(resolved_sd):
            displayed = get_image_list(search_dir, max_depth, filter_pattern=filter_pattern)
        else:
            displayed_set = {normalize_path_for_face_cache(p) for p in current_displayed}
            displayed = list(displayed_set)
            for p in get_image_list(search_dir, max_depth, filter_pattern=filter_pattern):
                if p not in displayed_set:
                    displayed_set.add(p)
                    displayed.append(p)
    else:
        if resolved_sd and os.path.isdir(resolved_sd):
            displayed = get_image_list(resolved_sd, 0, filter_pattern=filter_pattern)
        else:
            displayed = [normalize_path_for_face_cache(p) for p in current_displayed]
    return displayed


class PersonSearchPrepWorker(QThread):
    """Runs directory walk / path list build for person search off the GUI thread."""

    finished_paths = Signal(object)

    def __init__(
        self,
        recursive: bool,
        search_directory: Optional[str],
        current_dir: str,
        current_displayed: List[str],
        filter_pattern: Optional[str],
        max_depth: int,
        parent=None,
    ):
        super().__init__(parent)
        self._recursive = recursive
        self._search_directory = search_directory
        self._current_dir = current_dir
        self._current_displayed = current_displayed
        self._filter_pattern = filter_pattern
        self._max_depth = max_depth

    def run(self):
        try:
            time.sleep(0)
            paths = person_search_build_displayed_paths(
                self._recursive,
                self._search_directory,
                self._current_dir,
                self._current_displayed,
                self._filter_pattern,
                self._max_depth,
            )
            self.finished_paths.emit(paths)
        except Exception:
            self.finished_paths.emit([])


class PersonFaceMatchWorker(QThread):
    """Background match of face cache encodings against known subject embeddings (person search)."""

    finished_ok = Signal(object)  # List[Tuple[str, float]] paths with best mean distance to all samples per image
    finished_canceled = Signal()

    def __init__(self, displayed: List[str], known_encodings: List, cancel_event: threading.Event, parent=None):
        super().__init__(parent)
        self.displayed = displayed
        self.known_encodings = known_encodings
        self._cancel_event = cancel_event

    def run(self):
        from faces.face_cache import get_encodings
        from faces.face_engine import compare_faces, face_mean_distance

        matching_with_dist: List[Tuple[str, float]] = []
        try:
            # Let the main thread paint the progress dialog before heavy Python work (GIL).
            time.sleep(0)
            for i, path in enumerate(self.displayed):
                if self._cancel_event.is_set():
                    self.finished_canceled.emit()
                    return
                # Periodically release the GIL so the Qt GUI thread can process events (avoids beachball).
                if i > 0 and i % 8 == 0:
                    time.sleep(0)
                try:
                    encodings = get_encodings(path)
                except Exception:
                    continue
                if not encodings:
                    continue
                best_mean = None
                for enc in encodings:
                    if compare_faces(self.known_encodings, enc):
                        d = face_mean_distance(self.known_encodings, enc)
                        if d is not None and (best_mean is None or d < best_mean):
                            best_mean = d
                if best_mean is not None:
                    matching_with_dist.append((path, best_mean))
            self.finished_ok.emit(matching_with_dist)
        except Exception:
            try:
                self.finished_ok.emit([])
            except Exception:
                pass
