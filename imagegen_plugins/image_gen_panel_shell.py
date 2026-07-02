#!/usr/bin/env python3
"""Helpers for image-generation panels embedded in ImageGenUnifiedDialog."""

from __future__ import annotations

from typing import Any, Optional, Tuple

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from imagegen_plugins.image_gen_active_model import (
    FUNCTION_CREATE,
    FUNCTION_EDIT,
    FUNCTION_EXPAND,
    FUNCTION_INFILL,
    FUNCTION_INFILL_PAINT,
)

# Outer shell padding for ImageGenUnifiedDialog (left, top, right, bottom).
IMAGE_GEN_UNIFIED_SHELL_MARGINS: Tuple[int, int, int, int] = (4, 2, 4, 4)

_FUNCTION_INTRO_TEXT: dict[str, str] = {
    FUNCTION_EDIT: (
        "Modify the selected image(s) with AI using a text prompt. Drag and drop new images."
    ),
    FUNCTION_CREATE: (
        "Generate a new image from a text (prompt) and optional active image description."
    ),
    FUNCTION_EXPAND: (
        "Extend an image beyond its current edges (outpainting)."
    ),
    FUNCTION_INFILL_PAINT: (
        "Paint a mask to fill or replace part of an image."
    ),
    FUNCTION_INFILL: (
        "" # something having to do with pixelmator
    ),
}


def image_gen_unified_intro_text(function: str) -> str:
    """One-line description for the unified dialog header above each panel."""
    return _FUNCTION_INTRO_TEXT.get(function, "")


def create_image_gen_unified_intro_label(parent=None) -> QLabel:
    from imagegen_plugins.image_gen_form_layout import make_image_gen_field_label

    return make_image_gen_field_label("", parent)


def create_image_gen_unified_intro_rule(parent=None) -> QWidget:
    """1px rule under the intro title; wrapper adds 4px space below."""
    from PySide6.QtGui import QColor
    from theme.theme_service import get_active_theme

    wrap = QWidget(parent)
    layout = QVBoxLayout(wrap)
    layout.setContentsMargins(0, 8, 0, 8)
    layout.setSpacing(0)
    line = QFrame(wrap)
    line.setFixedHeight(1)
    line.setFrameShape(QFrame.Shape.NoFrame)
    border_hex = QColor(get_active_theme().border_default_hex).lighter(150).name()
    line.setStyleSheet(
        f"background-color: {border_hex}; border: none; margin: 0; padding: 0;"
    )
    layout.addWidget(line)
    return wrap


def wrap_image_gen_controls_with_unified_intro(
    controls: QWidget, function: str, *, parent: QWidget | None = None
) -> QWidget:
    """Stack intro copy above the controls column (unified dialog, panel_mode only)."""
    from imagegen_plugins.image_gen_dialog import apply_image_gen_preview_client_background

    host = QWidget(parent)
    apply_image_gen_preview_client_background(host)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    intro_text = (image_gen_unified_intro_text(function) or "").strip()
    if intro_text:
        intro = create_image_gen_unified_intro_label(host)
        intro.setText(intro_text)
        layout.addWidget(intro)
        layout.addWidget(create_image_gen_unified_intro_rule(host))
    layout.addWidget(controls, 1)
    return host


def configure_image_gen_embedded_panel_layout(layout, panel=None) -> None:
    """Zero default Qt layout margins on panels hosted in the unified shell."""
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    if panel is not None:
        from imagegen_plugins.image_gen_dialog import apply_image_gen_preview_client_background

        apply_image_gen_preview_client_background(panel)


def find_image_gen_unified_shell(widget: Any) -> Optional[Any]:
    """Walk parents to the unified shell hosting panel_mode children."""
    host = widget
    while host is not None:
        if callable(getattr(host, "_dismiss_discarding_current", None)):
            return host
        host = host.parent()
    return None


def panel_mode_reject(panel: Any) -> bool:
    """Route reject/Escape from an embedded panel to the unified shell."""
    if not getattr(panel, "_panel_mode", False):
        return False
    shell = find_image_gen_unified_shell(panel)
    if shell is None:
        return False
    shell._dismiss_discarding_current()
    return True
