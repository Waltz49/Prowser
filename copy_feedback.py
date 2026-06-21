#!/usr/bin/env python3
"""Floating '✓ Copied!' feedback for clipboard text copies."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from shiboken6 import isValid

from theme.theme_service import get_active_theme

COPY_FEEDBACK_DURATION_MS = 1500
COPY_FEEDBACK_MARGIN_X = 12
COPY_FEEDBACK_MARGIN_Y = 10
COPY_FEEDBACK_FONT_SIZE = "11pt"


def _anchor_is_usable(anchor: Optional[QWidget]) -> bool:
    return anchor is not None and isValid(anchor) and anchor.isVisible()


def resolve_copy_feedback_anchor(
    preferred: Optional[QWidget] = None,
    *,
    main_window: Optional[QWidget] = None,
) -> Optional[QWidget]:
    """Choose a widget to anchor copy feedback (upper-right overlay)."""
    if _anchor_is_usable(preferred):
        return preferred

    if main_window is not None and isValid(main_window):
        rs = getattr(main_window, "right_sidebar", None)
        if rs is not None:
            info_edit = getattr(rs, "info_text_edit", None)
            if _anchor_is_usable(info_edit):
                return info_edit

    app = QApplication.instance()
    if app is not None:
        focus = app.focusWidget()
        if _anchor_is_usable(focus):
            return focus
        active = app.activeWindow()
        if _anchor_is_usable(active):
            return active

    if main_window is not None and isValid(main_window):
        return main_window

    return preferred if preferred is not None and isValid(preferred) else None


def show_copy_feedback(
    anchor: Optional[QWidget] = None,
    *,
    duration_ms: int = COPY_FEEDBACK_DURATION_MS,
    font_size: Optional[str] = None,
) -> None:
    """Show a brief floating '✓ Copied!' label at the upper-right of anchor."""
    if not _anchor_is_usable(anchor):
        return
    th = get_active_theme()
    fs = font_size if font_size is not None else COPY_FEEDBACK_FONT_SIZE
    label = QLabel("✓ Copied!", anchor)
    label.setStyleSheet(
        f"""
        QLabel {{
            background-color: {th.information_action_chip_bg_hex};
            color: {th.validation_success_color_hex};
            border: 1px solid {th.validation_success_color_hex};
            border-radius: 4px;
            padding: 4px 10px;
            font-size: {fs};
        }}
        """
    )
    label.adjustSize()
    label.move(
        max(0, anchor.width() - label.width() - COPY_FEEDBACK_MARGIN_X),
        COPY_FEEDBACK_MARGIN_Y,
    )
    label.show()
    label.raise_()
    QTimer.singleShot(duration_ms, label.deleteLater)


def copy_text_to_clipboard(
    text: str,
    *,
    anchor: Optional[QWidget] = None,
    main_window: Optional[QWidget] = None,
    duration_ms: int = COPY_FEEDBACK_DURATION_MS,
    font_size: Optional[str] = None,
) -> None:
    """Copy text to the system clipboard and show floating copy feedback."""
    QApplication.clipboard().setText(text)
    resolved = resolve_copy_feedback_anchor(anchor, main_window=main_window)
    show_copy_feedback(resolved, duration_ms=duration_ms, font_size=font_size)
