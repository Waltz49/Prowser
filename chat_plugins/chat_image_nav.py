#!/usr/bin/env python3
"""Open chat-attached images in browse or specific-files thumbnail view."""

from __future__ import annotations

import os


def open_chat_image_paths(main_window, paths: list[str]) -> None:
    """One image → browse; multiple → new thumbnail level."""
    valid = [os.path.abspath(p) for p in paths if p and os.path.isfile(p)]
    if not valid:
        return
    handler = getattr(main_window, "directory_stack_history_handler", None)
    if handler is not None and hasattr(handler, "save_current_state"):
        handler.save_current_state("open_chat_image_paths", delay=0.0)
    refresh = getattr(main_window, "refresh_from_configuration", None)
    if callable(refresh):
        # Chat copies use message-id prefixes; ignore unrelated global filters.
        refresh(
            {
                "files": valid,
                "sort_mode": "custom",
                "skip_filter_pattern": True,
            }
        )
        return
    _open_chat_image_paths_fallback(main_window, valid)


def _open_chat_image_paths_fallback(main_window, paths: list[str]) -> None:
    if hasattr(main_window, "load_specific_files"):
        main_window.load_specific_files(
            paths, external_load=True, skip_filter_pattern=True
        )
