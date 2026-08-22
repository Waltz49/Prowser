#!/usr/bin/env python3
"""Shared prompt library dialog pieces for system and user favorites."""

from __future__ import annotations

from typing import Callable, TypeVar

from PySide6.QtWidgets import QPlainTextEdit, QWidget

from chat_plugins.chat_ui_common import (
    chat_prompt_edit_stylesheet,
    prompt_library_preview_height_px,
)

T = TypeVar("T")


def reorder_entries_mru(
    entries: list[T],
    active_id: str | None,
    id_getter: Callable[[T], str],
) -> list[T]:
    """Move the active entry to the front (MRU) while preserving relative order."""
    if not active_id:
        return entries
    active: T | None = None
    rest: list[T] = []
    for entry in entries:
        if id_getter(entry) == active_id:
            active = entry
        else:
            rest.append(entry)
    if active is None:
        return entries
    return [active, *rest]


def create_prompt_library_preview_editor(
    parent: QWidget | None = None,
    *,
    min_lines: int = 6,
) -> QPlainTextEdit:
    preview = QPlainTextEdit(parent)
    preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    preview.setStyleSheet(chat_prompt_edit_stylesheet())
    preview.setMinimumHeight(
        max(120, prompt_library_preview_height_px(preview.font(), min_lines))
    )
    return preview


def prompt_radio_tooltip(text: str, *, max_chars: int = 200) -> str:
    plain = text or ""
    if len(plain) <= max_chars:
        return plain
    return plain[:max_chars] + "…"
