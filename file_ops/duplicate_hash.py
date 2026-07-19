"""
MD5 hashing for exact-duplicate detection (off main thread for large file sets).
"""

from __future__ import annotations

import hashlib
import os
import threading
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEventLoop, QThread, Signal
from PySide6.QtWidgets import QApplication, QWidget

from utils import create_titled_progress_dialog, elide_progress_filename

DUPLICATE_HASH_WORKER_MIN_PATHS = 80


def compute_file_md5(file_path: str, *, chunk_size: int = 4096) -> Optional[str]:
    """Return MD5 hex digest for a file, or None if unreadable."""
    try:
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                md5_hash.update(chunk)
        return md5_hash.hexdigest()
    except (IOError, OSError):
        return None


def build_hash_groups(
    file_paths: List[str],
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[Dict[str, List[str]], Dict[str, str], bool]:
    """
    Hash each path and group by digest.

    Returns (hash_to_files, file_to_hash, cancelled).
    """
    hash_to_files: Dict[str, List[str]] = {}
    file_to_hash: Dict[str, str] = {}
    total = len(file_paths)
    cancelled = False

    for idx, file_path in enumerate(file_paths):
        if cancel_check and cancel_check():
            cancelled = True
            break
        if progress_cb:
            progress_cb(
                idx,
                total,
                f"Hashing {elide_progress_filename(os.path.basename(file_path))}... "
                f"({idx + 1}/{total})",
            )
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            continue
        file_hash = compute_file_md5(file_path)
        if not file_hash:
            continue
        file_to_hash[file_path] = file_hash
        hash_to_files.setdefault(file_hash, []).append(file_path)

    if not cancelled and progress_cb and total:
        progress_cb(total, total, "")

    return hash_to_files, file_to_hash, cancelled


class DuplicateHashWorker(QThread):
    """Background MD5 hashing for duplicate-finder UI."""

    progress = Signal(int, int, str)
    finished_hashes = Signal(object, object, bool)

    def __init__(self, file_paths: List[str]):
        super().__init__()
        self._paths = list(file_paths)
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        def progress_cb(value: int, maximum: int, text: str) -> None:
            self.progress.emit(value, maximum, text)

        hash_to_files, file_to_hash, cancelled = build_hash_groups(
            self._paths,
            cancel_check=self._cancel.is_set,
            progress_cb=progress_cb,
        )
        self.finished_hashes.emit(hash_to_files, file_to_hash, cancelled)


def run_duplicate_hash_ui(
    parent: QWidget,
    file_paths: List[str],
    *,
    window_title: str = "Find Duplicate Image Files",
) -> Tuple[Dict[str, List[str]], Dict[str, str], bool]:
    """Hash files with a progress dialog; use a worker thread for large sets."""
    n = len(file_paths)
    progress_dialog = create_titled_progress_dialog(parent, window_title, max(1, n))

    if n >= DUPLICATE_HASH_WORKER_MIN_PATHS:
        loop = QEventLoop(parent)
        result: List[Tuple[Dict[str, List[str]], Dict[str, str], bool]] = [
            ({}, {}, False)
        ]
        worker = DuplicateHashWorker(file_paths)

        def on_progress(value: int, maximum: int, text: str) -> None:
            progress_dialog.setMaximum(maximum)
            progress_dialog.setValue(min(value, maximum))
            if text:
                progress_dialog.setLabelText(text)
            QApplication.processEvents()
            if progress_dialog.wasCanceled():
                worker.request_cancel()

        def on_finished(hash_to_files: object, file_to_hash: object, cancelled: bool) -> None:
            htf = hash_to_files if isinstance(hash_to_files, dict) else {}
            fth = file_to_hash if isinstance(file_to_hash, dict) else {}
            result[0] = (htf, fth, cancelled)
            loop.quit()

        worker.progress.connect(on_progress)
        worker.finished_hashes.connect(on_finished)
        progress_dialog.canceled.connect(worker.request_cancel)
        worker.start()
        loop.exec()
        worker.wait()
        try:
            progress_dialog.canceled.disconnect(worker.request_cancel)
        except (TypeError, RuntimeError):
            pass
        progress_dialog.close()
        return result[0]

    hash_to_files, file_to_hash, cancelled = build_hash_groups(
        file_paths,
        cancel_check=progress_dialog.wasCanceled,
        progress_cb=lambda value, maximum, text: (
            progress_dialog.setValue(value),
            progress_dialog.setMaximum(maximum),
            progress_dialog.setLabelText(text) if text else None,
            QApplication.processEvents(),
        ),
    )
    progress_dialog.close()
    return hash_to_files, file_to_hash, cancelled
