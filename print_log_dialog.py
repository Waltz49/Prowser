#!/usr/bin/env python3
"""Tools > Debug > View log — live print-log viewer."""

from __future__ import annotations

import os
import shutil
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from config import get_config
from print_log_redirect import _print_log_lock, clear_print_log_file
from utils import (
    ensure_dialog_fits_screen,
    get_button_style,
    get_dialog_shell_stylesheet,
    raise_dialog_without_space_hop,
    restore_dialog_geometry_before_first_show,
    save_dialog_geometry_hex,
)

_GEOMETRY_KEY = "view_print_log_dialog_geometry"
_WRAP_KEY = "view_print_log_wrap"
_POLL_MS = 300

_active_dialog: PrintLogDialog | None = None


class PrintLogDialog(QDialog):
    """Always-on-top, resizable live view of the shared print() log file."""

    def __init__(self, parent, log_path: str):
        super().__init__(parent)
        self._log_path = log_path
        self._file_pos = 0
        self._config = parent.config if (parent and hasattr(parent, "config")) else get_config()
        self._geometry_restore_attempted = False
        self._geometry_was_restored = False

        self.setWindowTitle("View Log")
        self.setMinimumSize(520, 360)
        self.resize(820, 520)
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._log_view.setStyleSheet(
            """
            QPlainTextEdit {
                border-radius: 6px;
                padding: 8px 10px;
                font-family: Menlo, Monaco, "Courier New", monospace;
                font-size: 12px;
            }
            """
        )
        layout.addWidget(self._log_view, stretch=1)

        btn_row = QHBoxLayout()
        self._wrap_cb = QCheckBox("Wrap")
        wrap_enabled = bool(self._config.load_settings().get(_WRAP_KEY, False))
        self._wrap_cb.setChecked(wrap_enabled)
        if wrap_enabled:
            self._log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._wrap_cb.toggled.connect(self._on_wrap_toggled)
        btn_row.addWidget(self._wrap_cb)
        btn_row.addStretch()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self._clear_btn)
        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.setDefault(True)
        self._close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_MS)
        self._poll_timer.timeout.connect(self._poll_log)

        self.finished.connect(self._save_geometry)
        self.finished.connect(self._on_finished)

        self._load_initial_log()
        self._poll_timer.start()

    def _is_at_bottom(self) -> bool:
        bar = self._log_view.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def _append_text(self, text: str, *, stick_to_bottom: bool) -> None:
        if not text:
            return
        cursor = self._log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if stick_to_bottom:
            bar = self._log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _read_from_file(self) -> str:
        try:
            with _print_log_lock:
                with open(self._log_path, "r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(self._file_pos)
                    chunk = fh.read()
                    self._file_pos = fh.tell()
            return chunk
        except OSError:
            return ""

    def _load_initial_log(self) -> None:
        chunk = self._read_from_file()
        self._append_text(chunk, stick_to_bottom=True)

    def _poll_log(self) -> None:
        stick = self._is_at_bottom()
        chunk = self._read_from_file()
        self._append_text(chunk, stick_to_bottom=stick)

    def _on_wrap_toggled(self, checked: bool) -> None:
        self._log_view.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if checked
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        try:
            self._config.update_setting(_WRAP_KEY, bool(checked))
        except Exception:
            pass

    def _on_clear(self) -> None:
        clear_print_log_file()
        self._log_view.clear()
        self._file_pos = 0

    def _default_save_path(self) -> str:
        base = os.path.splitext(os.path.basename(self._log_path))[0] or "prowser_log"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(os.path.expanduser("~/Downloads"), f"{base}_{stamp}.txt")

    def _on_save(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Log",
            self._default_save_path(),
            "Text Files (*.txt)",
        )
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"
        try:
            with _print_log_lock:
                shutil.copyfile(self._log_path, path)
        except OSError as exc:
            from utils import show_styled_warning

            show_styled_warning(self, "Save Log", f"Could not save log:\n{exc}")

    def _save_geometry(self, *_args) -> None:
        try:
            self._config.update_setting(_GEOMETRY_KEY, save_dialog_geometry_hex(self))
        except Exception:
            pass

    def _on_finished(self, *_args) -> None:
        self._poll_timer.stop()
        global _active_dialog
        if _active_dialog is self:
            _active_dialog = None

    def showEvent(self, event) -> None:
        if not self._geometry_restore_attempted:
            geom_hex = self._config.load_settings().get(_GEOMETRY_KEY)
            restore_dialog_geometry_before_first_show(self, geom_hex, self.parent())
        super().showEvent(event)
        ensure_dialog_fits_screen(self, self.parent())


def show_print_log_dialog(parent, log_path: str) -> None:
    """Open or raise the live print-log viewer."""
    global _active_dialog
    if _active_dialog is not None:
        raise_dialog_without_space_hop(_active_dialog)
        return
    dialog = PrintLogDialog(parent, log_path)
    _active_dialog = dialog
    dialog.show()
    raise_dialog_without_space_hop(dialog)
