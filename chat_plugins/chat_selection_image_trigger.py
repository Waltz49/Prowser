#!/usr/bin/env python3
"""Insert browser selection into chat via ``{}`` in the user message."""

from __future__ import annotations

import os
import re

from chat_plugins.chat_image_store import MAX_CHAT_IMAGES

SELECTION_IMAGE_TRIGGER = "{}"


def user_message_has_selection_image_trigger(text: str) -> bool:
    return SELECTION_IMAGE_TRIGGER in (text or "")


def strip_selection_image_trigger(text: str) -> str:
    """Remove ``{}`` tokens from *text*."""
    if not user_message_has_selection_image_trigger(text):
        return text or ""
    stripped = (text or "").replace(SELECTION_IMAGE_TRIGGER, "")
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    return stripped.strip()


def selected_images_for_chat(main_window) -> list[str]:
    """Up to MAX_CHAT_IMAGES paths from the current browse/thumbnail selection."""
    if main_window is None:
        return []
    try:
        from imagegen_plugins.image_gen_edit_dialog import active_image_paths_for_edit
    except ImportError:
        return []
    try:
        raw_paths = active_image_paths_for_edit(main_window)
    except Exception:
        return []
    paths: list[str] = []
    for path in raw_paths:
        if not path or not os.path.isfile(path):
            continue
        abs_path = os.path.abspath(path)
        if abs_path not in paths:
            paths.append(abs_path)
        if len(paths) >= MAX_CHAT_IMAGES:
            break
    return paths


def apply_selection_image_trigger(
    text: str,
    image_paths: list[str],
    main_window,
) -> tuple[str, list[str]]:
    """Strip ``{}`` and replace message images with the current selection when present."""
    if not user_message_has_selection_image_trigger(text):
        return text, image_paths
    stripped = strip_selection_image_trigger(text)
    selected = selected_images_for_chat(main_window)
    if selected:
        return stripped, selected
    return stripped, image_paths
