#!/usr/bin/env python3
"""Default theme color dicts (no Qt) — shared by config and theme_service."""

from typing import Any, Dict


def default_user_theme_colors() -> Dict[str, Any]:
    """Default palette for the customizable user theme: hex strings + per-border widths."""
    return {
        "current_image_background_color_hex": "#19064d",
        "current_image_border_color_hex": "#00fdff",
        "current_image_border_width_index": 1,
        "default_background_color_hex": "#030627",
        "default_border_color_hex": "#151463",
        "default_image_background_color_hex": "#000000",
        "default_image_border_width_index": 1,
        "default_image_color_hex": "#666666",
        "multiselect_background_color_hex": "#000000",
        "multiselect_border_color_hex": "#80db8f",
        "multiselect_border_width_index": 2,
        "sidebar_header_bg_hex": "#020654",
        "text_color_hex": "#e2d2c3",
        "view_border_width_px": 2,
        "button_bg_default_hex": "#16181c",
        "button_border_default_hex": "#38506b",
        "button_bg_hover_hex": "#263447",
        "button_border_hover_hex": "#41a6c6",
        "button_text_default_hex": "#b0bfd6",
        "button_text_hover_hex": "#bbecff",
    }


def default_dark_theme_colors() -> Dict[str, Any]:
    """Default values for the customizable dark preset."""
    return {
        "current_image_background_color_hex": "#0080b2",
        "current_image_border_color_hex": "#87ceeb",
        "current_image_border_width_index": 2,
        "default_background_color_hex": "#000000",
        "default_border_color_hex": "#606060",
        "default_image_background_color_hex": "#000000",
        "default_image_border_width_index": 1,
        "default_image_color_hex": "#606060",
        "multiselect_background_color_hex": "#ffd700",
        "multiselect_border_color_hex": "#705d1f",
        "multiselect_border_width_index": 2,
        "sidebar_header_bg_hex": "#2b2b2b",
        "text_color_hex": "#b6b6b6",
        "view_border_width_px": 2,
        "button_bg_default_hex": "#16181c",
        "button_border_default_hex": "#38506b",
        "button_bg_hover_hex": "#263447",
        "button_border_hover_hex": "#41a6c6",
        "button_text_default_hex": "#b0bfd6",
        "button_text_hover_hex": "#bbecff",
    }


def default_light_theme_colors() -> Dict[str, Any]:
    """Default values for the customizable light preset."""
    return {
        "current_image_background_color_hex": "skyblue",
        "current_image_border_color_hex": "navy",
        "current_image_border_width_index": 2,
        "default_background_color_hex": "#c0c0c0",
        "default_border_color_hex": "#cfd8dc",
        "default_image_background_color_hex": "#c0c0c0",
        "default_image_border_width_index": 1,
        "default_image_color_hex": "#222222",
        "multiselect_background_color_hex": "gold",
        "multiselect_border_color_hex": "#e65100",
        "multiselect_border_width_index": 2,
        "sidebar_header_bg_hex": "#212833",
        "text_color_hex": "black",
        "view_border_width_px": 2,
        "button_bg_default_hex": "#f0f4f8",
        "button_border_default_hex": "#7a9ab8",
        "button_bg_hover_hex": "#dde8f4",
        "button_border_hover_hex": "#4a7aaa",
        "button_text_default_hex": "#1a2a3a",
        "button_text_hover_hex": "#0a1a2a",
    }
