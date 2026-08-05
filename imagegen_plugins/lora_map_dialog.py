#!/usr/bin/env python3
"""Tools > Debug > Map LoRAs — HTML view of LoRAs and models that use them."""

from __future__ import annotations

import html
import os
from datetime import datetime
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from theme.theme_service import get_active_theme
from utils import (
    apply_standard_dialog_layout,
    get_button_style,
    get_dialog_shell_stylesheet,
    show_styled_warning,
)


def _lora_map_rows() -> List[Tuple[str, List[str]]]:
    """Return (lora_label, model_labels) sorted by LoRA display name."""
    from imagegen_plugins.hf_model_ids import lora_model_display_name
    from imagegen_plugins.lora_catalog import get_lora_entry, lora_model_support

    support = lora_model_support()
    rows: List[Tuple[str, List[str]]] = []
    for lora_id, model_keys in support.items():
        entry = get_lora_entry(lora_id)
        label = (entry.display_name.strip() if entry else "") or lora_id
        models = [lora_model_display_name(mk) for mk in model_keys]
        rows.append((label, models))
    rows.sort(key=lambda row: row[0].lower())
    return rows


def build_lora_map_html(rows: Optional[List[Tuple[str, List[str]]]] = None) -> str:
    """Basic compact HTML: LoRA plain-text headers with model UL lists beneath."""
    if rows is None:
        rows = _lora_map_rows()
    th = get_active_theme()
    parts: List[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<style>",
        "body {",
        f"  color: {th.dialog_text_color_hex};",
        f"  background-color: {th.dialog_background_hex};",
        "  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;",
        "  font-size: 12px;",
        "  line-height: 1.25;",
        "  margin: 8px 10px;",
        "}",
        ".lora { margin: 0 0 8px 0; padding: 0; }",
        ".lora-name { font-weight: bold; margin: 0; padding: 0; }",
        "ul { margin: 2px 0 0 1.25em; padding: 0; }",
        "li { margin: 0; padding: 0; }",
        ".empty { margin: 2px 0 0 1.25em; opacity: 0.7; }",
        ".summary { margin: 0 0 12px 0; opacity: 0.85; }",
        "</style></head><body>",
    ]
    mapped = sum(1 for _, models in rows if models)
    parts.append(
        f"<div class='summary'>{len(rows)} LoRA(s); "
        f"{mapped} with at least one model.</div>"
    )
    if not rows:
        parts.append("<div>(No LoRA model-support map yet. Run Check LoRAs first.)</div>")
    for lora_label, models in rows:
        parts.append("<div class='lora'>")
        parts.append(f"<div class='lora-name'>{html.escape(lora_label)}</div>")
        if models:
            parts.append("<ul>")
            for model_label in models:
                parts.append(f"<li>{html.escape(model_label)}</li>")
            parts.append("</ul>")
        else:
            parts.append("<div class='empty'>(none)</div>")
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


class LoraMapDialog(QDialog):
    """Read-only HTML map of LoRAs → models, with Save."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map LoRAs")
        self.setModal(True)
        self.setMinimumSize(520, 400)
        self.resize(720, 640)
        self._html = build_lora_map_html()
        self._setup_ui()

    def _setup_ui(self) -> None:
        th = get_active_theme()
        self.setStyleSheet(get_dialog_shell_stylesheet() + get_button_style())
        layout = QVBoxLayout(self)
        apply_standard_dialog_layout(layout)

        title = QLabel(self.windowTitle())
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        browser = QTextBrowser(self)
        browser.setReadOnly(True)
        browser.setOpenExternalLinks(False)
        browser.setStyleSheet(
            f"""
            QTextBrowser {{
                background-color: {th.dialog_background_hex};
                color: {th.dialog_text_color_hex};
                border: 1px solid {th.border_default_hex};
                border-radius: 4px;
                padding: 8px;
            }}
            """
        )
        browser.setHtml(self._html)
        layout.addWidget(browser, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _default_save_path(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(
            os.path.expanduser("~/Downloads"),
            f"lora_map_{stamp}.html",
        )

    def _on_save(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Save LoRA Map",
            self._default_save_path(),
            "HTML Files (*.html)",
        )
        if not path:
            return
        if not path.lower().endswith((".html", ".htm")):
            path += ".html"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._html)
        except OSError as exc:
            show_styled_warning(self, "Save LoRA Map", f"Could not save:\n{exc}")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        for widget in self.findChildren(QPushButton):
            if widget.text() == "Close":
                widget.setFocus()
                break


def show_lora_map_dialog(parent=None) -> None:
    """Tools > Debug > Map LoRAs."""
    dialog = LoraMapDialog(parent)
    dialog.exec()
