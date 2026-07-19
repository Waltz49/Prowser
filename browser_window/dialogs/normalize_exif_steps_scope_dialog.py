#!/usr/bin/env python3
"""
Normalize EXIF Steps scope dialog — choose selected files or directory scan.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)
from utils import apply_standard_dialog_layout, file_string, get_standard_dialog_stylesheet, normalize_path_for_display


class NormalizeExifStepsScopeDialog(QDialog):
    """Ask whether to normalize selected files or scan the current directory."""

    SCOPE_SELECTED = "selected"
    SCOPE_DIRECTORY = "directory"

    def __init__(
        self,
        selected_exif_count: int,
        directory_path: str,
        search_depth: int,
        parent=None,
    ):
        super().__init__(parent)
        self._scope: Optional[str] = None

        self.setWindowTitle("Normalize EXIF Steps")
        self.setMinimumWidth(520)
        self.setStyleSheet(get_standard_dialog_stylesheet())

        layout = QVBoxLayout(self)
        apply_standard_dialog_layout(layout)

        intro = QLabel(
            "Scan for legacy [N] step suffixes in Image Model EXIF. Choose scope:"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._button_group = QButtonGroup(self)

        if selected_exif_count == 1:
            selected_text = "Selected file (1)"
        else:
            selected_text = (
                f"Selected {file_string(selected_exif_count)} ({selected_exif_count})"
            )
        self.selected_radio = QRadioButton(selected_text)
        self.selected_radio.setEnabled(selected_exif_count > 0)
        self._button_group.addButton(self.selected_radio)
        layout.addWidget(self.selected_radio)

        display_dir = normalize_path_for_display(directory_path) if directory_path else ""
        if display_dir and len(display_dir) > 72:
            display_dir = "..." + display_dir[-69:]
        dir_detail = (
            f"\n{display_dir}" if display_dir else ""
        )
        self.directory_radio = QRadioButton(
            f"Current directory and subdirectories "
            f"(search depth {search_depth}){dir_detail}"
        )
        self.directory_radio.setEnabled(bool(directory_path))
        self._button_group.addButton(self.directory_radio)
        layout.addWidget(self.directory_radio)

        if selected_exif_count > 0:
            self.selected_radio.setChecked(True)
        elif directory_path:
            self.directory_radio.setChecked(True)
        else:
            self.selected_radio.setEnabled(False)
            self.directory_radio.setEnabled(False)

        button_box = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        button_box.button(QDialogButtonBox.Ok).setText("Continue")
        button_box.button(QDialogButtonBox.Cancel).setText("Cancel")
        button_box.button(QDialogButtonBox.Cancel).setDefault(True)
        button_box.button(QDialogButtonBox.Cancel).setFocus()
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_accept(self) -> None:
        if self.selected_radio.isChecked():
            self._scope = self.SCOPE_SELECTED
        elif self.directory_radio.isChecked():
            self._scope = self.SCOPE_DIRECTORY
        else:
            return
        self.accept()

    @property
    def scope(self) -> Optional[str]:
        return self._scope

    @staticmethod
    def ask(
        selected_exif_count: int,
        directory_path: str,
        search_depth: int,
        parent=None,
    ) -> Optional[str]:
        if selected_exif_count <= 0 and not directory_path:
            return None
        dialog = NormalizeExifStepsScopeDialog(
            selected_exif_count, directory_path, search_depth, parent
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.scope
