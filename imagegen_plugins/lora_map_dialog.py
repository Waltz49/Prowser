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
    raise_dialog_without_space_hop,
    show_styled_warning,
)

_active_dialog: Optional["LoraMapDialog"] = None

# (lora_label, [(model_display_label, is_cross_family), ...])
LoraMapRow = Tuple[str, List[Tuple[str, bool]]]


def _lora_map_rows() -> List[LoraMapRow]:
    """Return LoRA rows sorted by display name.

    Uses the same association rules as the LoRA combos / settings grid:
    curated host models (e.g. Furry → SD1.5) plus Check LoRAs probe passes.
  Cross-family associations are marked for display with an asterisk.
    """
    from config import get_config
    from imagegen_plugins.hf_model_ids import LORA_PROBE_MODEL_ORDER, lora_model_display_name
    from imagegen_plugins.lora_catalog import (
        catalog_entries_sorted,
        lora_model_is_cross_family,
        lora_probe_passed_for_model,
    )
    from imagegen_plugins.lora_catalog_settings import lora_catalog_from_settings

    settings = get_config().load_settings()
    lc = lora_catalog_from_settings(settings)
    raw_ms = lc.get("model_support")
    model_support = raw_ms if isinstance(raw_ms, dict) else {}
    raw_cf = lc.get("cross_family_models")
    cross_family = raw_cf if isinstance(raw_cf, dict) else {}

    rows: List[LoraMapRow] = []
    for entry in catalog_entries_sorted(settings):
        label = (entry.display_name.strip() if entry.display_name else "") or entry.lora_id
        models: List[Tuple[str, bool]] = []
        for mk in LORA_PROBE_MODEL_ORDER:
            if not lora_probe_passed_for_model(
                entry.lora_id,
                mk,
                entry=entry,
                model_support=model_support,
            ):
                continue
            model_label = lora_model_display_name(mk)
            is_cross = lora_model_is_cross_family(
                entry.lora_id,
                mk,
                settings=settings,
                entry=entry,
                cross_family=cross_family,
            )
            if is_cross:
                model_label = f"{model_label} *"
            models.append((model_label, is_cross))
        rows.append((label, models))
    rows.sort(key=lambda row: row[0].lower())
    return rows


def build_lora_map_html(rows: Optional[List[LoraMapRow]] = None) -> str:
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
        ".footnote { margin: 12px 0 0 0; opacity: 0.75; font-size: 11px; }",
        "</style></head><body>",
    ]
    mapped = sum(1 for _, models in rows if models)
    cross_count = sum(1 for _, models in rows for _, is_cross in models if is_cross)
    parts.append(
        f"<div class='summary'>{len(rows)} LoRA(s); "
        f"{mapped} with at least one model."
        + (f" {cross_count} cross-family link(s)." if cross_count else "")
        + "</div>"
    )
    if not rows:
        parts.append("<div>(No LoRA model-support map yet. Run Check LoRAs first.)</div>")
    for lora_label, models in rows:
        parts.append("<div class='lora'>")
        parts.append(f"<div class='lora-name'>{html.escape(lora_label)}</div>")
        if models:
            parts.append("<ul>")
            for model_label, _is_cross in models:
                parts.append(f"<li>{html.escape(model_label)}</li>")
            parts.append("</ul>")
        else:
            parts.append("<div class='empty'>(none)</div>")
        parts.append("</div>")
    parts.append(
        "<div class='footnote'>* cross-family — Check LoRAs found this LoRA "
        "working on a base model outside its catalog host family.</div>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)


class LoraMapDialog(QDialog):
    """Read-only HTML map of LoRAs → models, with Save."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Map LoRAs")
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setMinimumSize(520, 400)
        self.resize(720, 640)
        self._html = build_lora_map_html()
        self._setup_ui()
        self.finished.connect(self._on_finished)

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
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _on_finished(self, *_args) -> None:
        global _active_dialog
        if _active_dialog is self:
            _active_dialog = None

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
    """Tools > Debug > Map LoRAs (non-modal; raise if already open)."""
    global _active_dialog
    if _active_dialog is not None:
        raise_dialog_without_space_hop(_active_dialog)
        return
    dialog = LoraMapDialog(parent)
    _active_dialog = dialog
    dialog.show()
    raise_dialog_without_space_hop(dialog)
