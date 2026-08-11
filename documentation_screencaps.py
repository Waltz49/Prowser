#!/usr/bin/env python3
"""
Capture settings-dialog tabs for prowser.php documentation images.

Tools > Debug > Documentation screencaps writes 1642x1300 WebPs to
/tmp/screencaps/ using basenames from prowser.php.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from utils import activate_application_window, present_auxiliary_dialog, show_styled_warning

DOC_SCREENCAP_WIDTH = 1642
DOC_SCREENCAP_HEIGHT = 1300
DOC_SCREENCAP_SIZE = QSize(DOC_SCREENCAP_WIDTH, DOC_SCREENCAP_HEIGHT)
DOC_SCREENCAP_OUTPUT_DIR = "/tmp/screencaps"
DOC_SCREENCAP_FORMAT = "WEBP"
DOC_SCREENCAP_WEBP_QUALITY = 95

# tab_id -> output filename (basenames match prowser.php $settings_sim_tabs)
# Order matches settings_dialog.py sidebar tab order.
TAB_CAPTURE_SPECS: List[Tuple[str, str]] = [
    ("app_settings", "settings_general.webp"),
    ("favorites", "settings_favorites.webp"),
    ("directories", "settings_directories.webp"),
    ("extensions", "settings_filetypes.webp"),
    ("move_destinations", "settings_destinations.webp"),
    ("exclude_destinations", "settings_excludes.webp"),
    ("theme_settings", "settings_theme.webp"),
    ("map_settings", "settings_maps_and_editor.webp"),
    ("slideshow_settings", "settings_slideshow.webp"),
    ("similarity_settings", "settings_search_models.webp"),
    ("faces_tab", "settings_face_recognition.webp"),
    ("captioning_settings", "settings_captioning.webp"),
    ("lora_settings", "settings_LoRA.webp"),
    ("cache_management", "settings_caches.webp"),
]

_TAB_SETTLE_MS = 150
_FACES_TAB_SETTLE_MS = 200
_FACES_WAIT_POLL_MS = 50
_FACES_WAIT_MAX_ATTEMPTS = 120  # ~6s


def _macos_window_number(widget) -> Optional[int]:
    """Return macOS window number for screencapture -l, or None."""
    try:
        import objc
        from ctypes import c_void_p

        wid = widget.winId()
        if not wid:
            return None
        view = objc.objc_object(c_void_p=int(wid))
        ns_window = view.window()
        if ns_window is None:
            return None
        return int(ns_window.windowNumber())
    except Exception:
        return None


def capture_window_pixmap(dialog) -> Optional[QPixmap]:
    """Capture the native settings window (title bar included)."""
    from PySide6.QtGui import QGuiApplication

    activate_application_window(dialog, force=True)
    QApplication.processEvents()

    window_num = _macos_window_number(dialog)
    if window_num is not None:
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            result = subprocess.run(
                ["screencapture", "-l", str(window_num), "-o", tmp_path],
                capture_output=True,
                timeout=10,
            )
            if (
                result.returncode == 0
                and os.path.isfile(tmp_path)
                and os.path.getsize(tmp_path) > 0
            ):
                pixmap = QPixmap(tmp_path)
                if not pixmap.isNull():
                    return pixmap
        except Exception:
            pass
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    screen = QGuiApplication.screenAt(dialog.frame().center())
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is not None:
        wid = dialog.winId()
        if wid:
            pixmap = screen.grabWindow(int(wid))
            if not pixmap.isNull():
                return pixmap
    return None


def finalize_screencap(source: QPixmap) -> QPixmap:
    """Place captured window at top-left on a transparent 1642x1300 canvas."""
    canvas = QPixmap(DOC_SCREENCAP_WIDTH, DOC_SCREENCAP_HEIGHT)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return canvas


class DocumentationScreencapRunner(QObject):
    """QTimer-chained capture of each visible settings tab."""

    finished = Signal()

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.dialog = None
        self.specs: List[Tuple[str, str]] = []
        self.index = 0
        self.saved: List[str] = []
        self.failed: List[Tuple[str, str, str]] = []
        self._faces_wait_attempts = 0

    def start(self) -> None:
        from settings_dialog import SettingsDialog

        os.makedirs(DOC_SCREENCAP_OUTPUT_DIR, exist_ok=True)

        self.dialog = SettingsDialog(self.main_window)
        self.dialog.load_current_settings()
        present_auxiliary_dialog(self.dialog)
        activate_application_window(self.dialog, force=True)
        QApplication.processEvents()

        self.specs = [
            (tab_id, filename)
            for tab_id, filename in TAB_CAPTURE_SPECS
            if self.dialog.tab_widget_for_id(tab_id) is not None
        ]
        if not self.specs:
            self._finish()
            return

        self.index = 0
        self.saved = []
        self.failed = []
        self._faces_wait_attempts = 0
        QTimer.singleShot(200, self._switch_to_current_tab)

    def _switch_to_current_tab(self) -> None:
        if self.dialog is None or self.index >= len(self.specs):
            self._finish()
            return

        tab_id, _filename = self.specs[self.index]
        self.dialog.show_tab_by_id(tab_id)
        QApplication.processEvents()
        self._faces_wait_attempts = 0
        self._wait_for_ready()

    def _wait_for_ready(self) -> None:
        if self.dialog is None or self.index >= len(self.specs):
            self._finish()
            return

        tab_id, _filename = self.specs[self.index]
        if tab_id == "faces_tab" and not getattr(self.dialog, "_faces_tab_setup_done", False):
            self._faces_wait_attempts += 1
            if self._faces_wait_attempts >= _FACES_WAIT_MAX_ATTEMPTS:
                QTimer.singleShot(0, self._do_capture)
                return
            QTimer.singleShot(_FACES_WAIT_POLL_MS, self._wait_for_ready)
            return

        delay = _FACES_TAB_SETTLE_MS if tab_id == "faces_tab" else _TAB_SETTLE_MS
        QTimer.singleShot(delay, self._do_capture)

    def _do_capture(self) -> None:
        if self.dialog is None or self.index >= len(self.specs):
            self._finish()
            return

        tab_id, filename = self.specs[self.index]
        pixmap = capture_window_pixmap(self.dialog)
        if pixmap is None:
            self.failed.append((tab_id, filename, "capture failed"))
        else:
            final = finalize_screencap(pixmap)
            out_path = os.path.join(DOC_SCREENCAP_OUTPUT_DIR, filename)
            if final.save(out_path, DOC_SCREENCAP_FORMAT, DOC_SCREENCAP_WEBP_QUALITY):
                self.saved.append(filename)
            else:
                self.failed.append((tab_id, filename, "save failed"))

        self.index += 1
        self._faces_wait_attempts = 0
        if self.index < len(self.specs):
            QTimer.singleShot(50, self._switch_to_current_tab)
        else:
            self._finish()

    def _finish(self) -> None:
        if self.dialog is not None:
            try:
                self.dialog.reject()
            except Exception:
                pass
            self.dialog.deleteLater()
            self.dialog = None

        mw = self.main_window
        if self.failed:
            lines = "\n".join(
                f"  {filename}: {reason}" for _tab_id, filename, reason in self.failed
            )
            show_styled_warning(
                mw,
                "Documentation screencaps",
                f"Saved {len(self.saved)} of {len(self.saved) + len(self.failed)} images "
                f"to {DOC_SCREENCAP_OUTPUT_DIR}.\n\nFailed:\n{lines}",
            )
        elif hasattr(mw, "status_notification") and mw.status_notification:
            mw.status_notification.show_message(
                f"Documentation screencaps saved ({len(self.saved)} images):\n"
                f"{DOC_SCREENCAP_OUTPUT_DIR}",
                duration=6000,
            )

        self.finished.emit()


_active_runner: Optional[DocumentationScreencapRunner] = None


def run_documentation_screencaps(main_window) -> None:
    """Tools > Debug > Documentation screencaps."""
    global _active_runner
    if _active_runner is not None:
        show_styled_warning(
            main_window,
            "Documentation screencaps",
            "A documentation screencap run is already in progress.",
        )
        return

    runner = DocumentationScreencapRunner(main_window)
    _active_runner = runner

    def _clear_runner() -> None:
        global _active_runner
        if _active_runner is runner:
            _active_runner = None

    runner.finished.connect(_clear_runner)
    runner.start()
