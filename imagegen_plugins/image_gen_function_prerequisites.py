#!/usr/bin/env python3
"""Shared prerequisite checks before opening or switching image-gen functions."""

from __future__ import annotations

from typing import List, Optional

import os

from imagegen_plugins.image_gen_active_model import (
    FUNCTION_EDIT,
    FUNCTION_EXPAND,
    FUNCTION_INFILL_PAINT,
)
from imagegen_plugins.image_gen_edit_dialog import (
    MAX_EDIT_SOURCE_IMAGES,
    active_image_paths_for_edit,
)
from imagegen_plugins.image_gen_expand_dialog import active_image_path_for_expand
from imagegen_plugins.image_gen_infill_paint_dialog import active_image_path_for_infill
from utils import show_styled_warning


def validate_function_prerequisites(
    function: str,
    main_window,
    *,
    parent=None,
    source_image_paths: Optional[List[str]] = None,
) -> bool:
    """Return True when the function may be opened or switched to."""
    warn_parent = parent if parent is not None else main_window
    if function == FUNCTION_INFILL_PAINT:
        if not active_image_path_for_infill(main_window):
            show_styled_warning(
                warn_parent,
                "Infill",
                "Select an image in browse view, or select a single thumbnail, "
                "before using infill by painting.",
            )
            return False
        return True
    if function == FUNCTION_EXPAND:
        if not active_image_path_for_expand(main_window):
            show_styled_warning(
                warn_parent,
                "Expand",
                "Select an image in browse view, or select a single thumbnail, "
                "before using expand.",
            )
            return False
        return True
    if function == FUNCTION_EDIT:
        explicit_paths = normalize_edit_source_paths(source_image_paths)
        if explicit_paths:
            if len(explicit_paths) > MAX_EDIT_SOURCE_IMAGES:
                show_styled_warning(
                    warn_parent,
                    "Edit",
                    f"Select at most {MAX_EDIT_SOURCE_IMAGES} images before using edit.",
                )
                return False
            return True
        if (
            main_window.current_view_mode == "thumbnail"
            and hasattr(main_window, "selection_manager")
            and main_window.selection_manager
            and getattr(main_window, "selected_files", None)
            and len(main_window.selection_manager.get_selected_files())
            > MAX_EDIT_SOURCE_IMAGES
        ):
            show_styled_warning(
                warn_parent,
                "Edit",
                f"Select at most {MAX_EDIT_SOURCE_IMAGES} images before using edit.",
            )
            return False
        if not active_image_paths_for_edit(main_window):
            show_styled_warning(
                warn_parent,
                "Edit",
                "Select an image in browse view, or select up to "
                f"{MAX_EDIT_SOURCE_IMAGES} thumbnails, before using edit.",
            )
            return False
    return True


def normalize_edit_source_paths(
    source_image_paths: Optional[List[str]],
    *,
    max_count: Optional[int] = None,
) -> List[str]:
    if not source_image_paths:
        return []
    paths = [
        os.path.abspath(p)
        for p in source_image_paths
        if p and os.path.isfile(p)
    ]
    if max_count is not None:
        return paths[:max_count]
    return paths
