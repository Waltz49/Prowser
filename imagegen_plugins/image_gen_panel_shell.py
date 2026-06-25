#!/usr/bin/env python3
"""Helpers for image-generation panels embedded in ImageGenUnifiedDialog."""

from __future__ import annotations

from typing import Any, Optional, Tuple

# Outer shell padding for ImageGenUnifiedDialog (left, top, right, bottom).
IMAGE_GEN_UNIFIED_SHELL_MARGINS: Tuple[int, int, int, int] = (4, 2, 4, 4)


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
