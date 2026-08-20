#!/usr/bin/env python3
"""Dialog for configuring external exit scripts."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from config import get_config
from exit_scripts import (
    SETTING_IMAGE_AI_EXIT,
    SETTING_SAY_EXIT,
    SETTING_TEXT_AI_EXIT,
    format_exit_script_command,
    parse_exit_script_command,
    validate_exit_script_command,
)
from thumbnails.thumbnail_constants import (
    BUTTON_BG_DEFAULT_HEX,
    BUTTON_BG_HOVER_HEX,
    BUTTON_BORDER_DEFAULT_HEX,
    BUTTON_BORDER_HOVER_HEX,
    BUTTON_TEXT_DEFAULT_HEX,
    BUTTON_TEXT_HOVER_HEX,
    ERROR_COLOR_HEX,
    TEXT_DISABLED_HEX,
    BORDER_DEFAULT_HEX,
    TAB_BUTTON_HOVER_BG_HEX,
    VALIDATION_SUCCESS_COLOR_HEX,
)
from utils import get_button_style, get_dialog_shell_stylesheet


def _small_ellipsis_button_style() -> str:
    return f"""
        QPushButton {{
            border: 1px solid {BUTTON_BORDER_DEFAULT_HEX};
            color: {BUTTON_TEXT_DEFAULT_HEX};
            background: {BUTTON_BG_DEFAULT_HEX};
            border-radius: 4px;
            font-size: 12pt;
            padding: 0px 8px;
            min-width: 0px;
        }}
        QPushButton:hover {{
            background-color: {BUTTON_BG_HOVER_HEX};
            color: {BUTTON_TEXT_HOVER_HEX};
            border: 1px solid {BUTTON_BORDER_HOVER_HEX};
        }}
        QPushButton:focus {{
            background-color: {BUTTON_BG_HOVER_HEX};
            color: {BUTTON_TEXT_HOVER_HEX};
            border: 1px solid {BUTTON_BORDER_HOVER_HEX};
            outline: none;
        }}
        QPushButton:disabled {{
            color: {TEXT_DISABLED_HEX};
            border-color: {BORDER_DEFAULT_HEX};
            background: {TAB_BUTTON_HOVER_BG_HEX};
        }}
    """


def _path_to_display(path: str) -> str:
    home = os.path.expanduser("~")
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def _display_to_path(path: str) -> str:
    return os.path.expanduser((path or "").strip())


class _ExitScriptRow:
    def __init__(
        self,
        *,
        label: str,
        placeholder: str,
        tooltip: str,
        parent: QWidget,
        dialog: "ExitScriptsDialog",
    ) -> None:
        self.dialog = dialog
        self.prefix = ""

        container = QWidget(parent)
        container.setMinimumHeight(28)
        container.setMaximumHeight(28)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(placeholder)
        self.input_field.setToolTip(tooltip)
        self.input_field.setMinimumHeight(28)
        self.input_field.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.input_field)

        self.validation_label = QLabel("")
        self.validation_label.setFixedWidth(20)
        self.validation_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.validation_label)

        browse_button = QPushButton("...")
        browse_button.setToolTip(f"Browse for script file ({label})")
        browse_button.setFixedWidth(30)
        browse_button.setFixedHeight(28)
        browse_button.setStyleSheet(_small_ellipsis_button_style())
        browse_button.clicked.connect(self.browse)
        layout.addWidget(browse_button)

        self.label = label
        self.form_label = QLabel(label + ":")
        self.container = container

    def _on_text_changed(self, text: str) -> None:
        parsed = parse_exit_script_command(text)
        self.prefix = parsed.prefix
        valid, tooltip = validate_exit_script_command(text)
        if not (text or "").strip():
            self.validation_label.setText("")
            self.validation_label.setToolTip("")
            return
        if valid:
            self.validation_label.setText("✓")
            self.validation_label.setStyleSheet(
                f"color: {VALIDATION_SUCCESS_COLOR_HEX}; font-size: 14px; font-weight: bold;"
            )
            self.validation_label.setToolTip(tooltip)
        else:
            self.validation_label.setText("✗")
            self.validation_label.setStyleSheet(
                f"color: {ERROR_COLOR_HEX}; font-size: 14px; font-weight: bold;"
            )
            self.validation_label.setToolTip(tooltip)

    def set_value(self, raw: str) -> None:
        parsed = parse_exit_script_command(raw)
        self.prefix = parsed.prefix
        self.input_field.blockSignals(True)
        self.input_field.setText(raw)
        self.input_field.blockSignals(False)
        self._on_text_changed(raw)

    def value(self) -> str:
        return self.input_field.text().strip()

    def browse(self) -> None:
        current = self.input_field.text().strip()
        parsed = parse_exit_script_command(current)
        self.prefix = parsed.prefix
        current_path = _display_to_path(parsed.path) if parsed.path else ""
        if current_path and os.path.isfile(current_path):
            start_directory = os.path.dirname(current_path)
        elif current_path and os.path.isdir(os.path.dirname(current_path)):
            start_directory = os.path.dirname(current_path)
        else:
            start_directory = os.path.expanduser("~")

        selected_path, _ = QFileDialog.getOpenFileName(
            self.dialog,
            f"Select Script File for {self.label}",
            start_directory,
            "Scripts (*.py *.sh);;All Files (*)",
        )
        if not selected_path:
            return
        display_path = _path_to_display(selected_path)
        self.input_field.setText(format_exit_script_command(self.prefix, display_path))


class ExitScriptsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exit Scripts")
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Configure external scripts that transform prompts or speak text.\n"
            "Enter a file path, or prefix with python / python3 / pypy."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form_layout = QFormLayout()
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.setVerticalSpacing(8)

        settings = get_config().load_settings()
        self._text_row = _ExitScriptRow(
            label="Text AI exit",
            placeholder="Script for LM Studio / caption prompts",
            tooltip=(
                "Runs before text-model calls when prompt filter exits are enabled.\n"
                "An implicit -p paramerter is used to pass the input string and\n"
                "output is sent to stdout. Add user parameters as needed.\n\n"
                "Example: python ~/scripts/text_exit.py"
            ),
            parent=self,
            dialog=self,
        )
        self._image_row = _ExitScriptRow(
            label="Image AI exit",
            placeholder="Script for image generation prompts",
            tooltip=(
                "Runs before image-model calls when prompt filter exits are enabled.\n"
                "An implicit -p paramerter is used to pass the input string and\n"
                "output is sent to stdout. Add user parameters as needed.\n\n"
                "Example: /path/to/image_exit.py"
            ),
            parent=self,
            dialog=self,
        )
        self._say_row = _ExitScriptRow(
            label="Say exit",
            placeholder="Script for speak buttons",
            tooltip=(
                "Runs when speak is triggered instead of macOS say.\n"
                "An implicit -p paramerter is used to pass the input string and\n"
                "output is sent to stdout. Add user parameters as needed.\n\n"
                "Example: python ~/scripts/say_exit.py --voice Joe --rate 1.2"
            ),
            parent=self,
            dialog=self,
        )

        self._text_row.set_value(str(settings.get(SETTING_TEXT_AI_EXIT, "") or ""))
        self._image_row.set_value(str(settings.get(SETTING_IMAGE_AI_EXIT, "") or ""))
        self._say_row.set_value(str(settings.get(SETTING_SAY_EXIT, "") or ""))

        form_layout.addRow(self._text_row.form_label, self._text_row.container)
        form_layout.addRow(self._image_row.form_label, self._image_row.container)
        form_layout.addRow(self._say_row.form_label, self._say_row.container)
        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())

    def accept(self) -> None:
        text_exit = self._text_row.value()
        image_exit = self._image_row.value()
        updates = {
            SETTING_TEXT_AI_EXIT: text_exit,
            SETTING_IMAGE_AI_EXIT: image_exit,
            SETTING_SAY_EXIT: self._say_row.value(),
        }
        if text_exit or image_exit:
            updates["use_prompt_filter_exits"] = True
        get_config().update_settings(updates)
        parent = self.parent()
        if parent is not None and (text_exit or image_exit):
            setattr(parent, "use_prompt_filter_exits", True)
            if hasattr(parent, "use_prompt_filter_exits_checkbox"):
                parent.use_prompt_filter_exits_checkbox.setChecked(True)
        super().accept()


def run_exit_scripts_dialog(parent: QWidget | None = None) -> bool:
    """Show exit-scripts dialog. Returns True when saved."""
    dlg = ExitScriptsDialog(parent)
    return dlg.exec() == QDialog.DialogCode.Accepted
