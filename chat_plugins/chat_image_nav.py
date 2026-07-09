#!/usr/bin/env python3
"""Open chat-attached images in browse or specific-files thumbnail view."""

from __future__ import annotations

import os


def open_chat_image_paths(main_window, paths: list[str]) -> None:
    """One image → browse; multiple → new thumbnail level."""
    try:
        from imagegen_plugins.job_queue_common import open_reference_thumbnail_paths

        open_reference_thumbnail_paths(main_window, paths)
        return
    except ImportError:
        pass
    _open_chat_image_paths_fallback(main_window, paths)


def _open_chat_image_paths_fallback(main_window, paths: list[str]) -> None:
    valid = [os.path.abspath(p) for p in paths if p and os.path.isfile(p)]
    if not valid:
        return
    if len(valid) == 1:
        loader = getattr(main_window, "load_file_with_directory_thumbnails", None)
        if callable(loader):
            loader(valid[0])
            return
        if hasattr(main_window, "load_specific_files"):
            main_window.load_specific_files(valid, external_load=True)
        return
    handler = getattr(main_window, "directory_stack_history_handler", None)
    if handler is not None and hasattr(handler, "save_current_state"):
        handler.save_current_state("open_chat_image_paths", delay=0.0)
    refresh = getattr(main_window, "refresh_from_configuration", None)
    if callable(refresh):
        refresh({"files": valid, "sort_mode": "custom"})
