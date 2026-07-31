#!/usr/bin/env python3
"""Themed icons for sidebar pane titlebars (tools menu, flyout/flyin)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

import thumbnails.thumbnail_constants as tc
from theme.theme_base import asset_path

TITLEBAR_ICON_SIZE_PX = 14
_COLOR_PLACEHOLDER = "%COLOR%"
_HIDE_ICON_ASSETS = {
    "minus": "titlebar_minus.svg",
    "plus": "titlebar_plus.svg",
    "close": "titlebar_close.svg",
}
_LIGHT_ON_DARK_FG = "#f2f2f2"
_DARK_ON_LIGHT_FG = "#1a1a1a"
_MIN_ACCENT_CONTRAST = 3.0


def titlebar_chip_colors() -> tuple[str, str, str, str, str]:
    """Chip button colors derived from the sidebar header background.

    Returns (bg, hover_bg, pressed_bg, border, border_hover).
    """
    titlebar = QColor(tc.SIDEBAR_HEADER_BG_HEX)
    if not titlebar.isValid():
        titlebar = QColor("#2b2b2b")
    return (
        titlebar.lighter(200).name(),
        titlebar.lighter(300).name(),
        titlebar.lighter(160).name(),
        titlebar.lighter(160).name(),
        titlebar.lighter(180).name(),
    )


def _relative_luminance(color: QColor) -> float:
    def channel(value: int) -> float:
        c = value / 255.0
        if c <= 0.03928:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * channel(color.red())
        + 0.7152 * channel(color.green())
        + 0.0722 * channel(color.blue())
    )


def _contrast_ratio(fg: QColor, bg: QColor) -> float:
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def contrasting_foreground_hex(
    bg_hex: str,
    *,
    light_hex: str = _LIGHT_ON_DARK_FG,
    dark_hex: str = _DARK_ON_LIGHT_FG,
) -> str:
    """Pick light or dark foreground for readable contrast on *bg_hex*."""
    bg = QColor(bg_hex)
    if not bg.isValid():
        return light_hex
    light = QColor(light_hex)
    dark = QColor(dark_hex)
    if _contrast_ratio(light, bg) >= _contrast_ratio(dark, bg):
        return light_hex
    return dark_hex


def _hover_foreground_hex(hover_bg_hex: str, normal_fg_hex: str) -> str:
    accent = (tc.ACCENT_COLOR_HEX or "").strip()
    if accent:
        accent_c = QColor(accent)
        hover_bg = QColor(hover_bg_hex)
        if accent_c.isValid() and hover_bg.isValid():
            if _contrast_ratio(accent_c, hover_bg) >= _MIN_ACCENT_CONTRAST:
                return accent
    normal = QColor(normal_fg_hex)
    hover_bg = QColor(hover_bg_hex)
    if not normal.isValid() or not hover_bg.isValid():
        return contrasting_foreground_hex(hover_bg_hex)
    if _relative_luminance(hover_bg) < 0.5:
        return normal.lighter(125).name()
    return normal.darker(125).name()


def titlebar_icon_colors() -> tuple[str, str]:
    """Normal/hover icon colors contrasting with chip button backgrounds."""
    chip_bg, chip_hover_bg, _, _, _ = titlebar_chip_colors()
    normal = contrasting_foreground_hex(chip_bg)
    hover = _hover_foreground_hex(chip_hover_bg, normal)
    return normal, hover


def titlebar_chip_stylesheet() -> str:
    """Stylesheet for titlebar chip buttons (hide/tools/flyout)."""
    hb_bg, hb_hover, hb_pressed, hb_border, hb_border_hover = titlebar_chip_colors()
    fg = contrasting_foreground_hex(hb_bg)
    return f"""
            QPushButton {{
                background-color: {hb_bg};
                border: 1px solid {hb_border};
                border-radius: 3px;
                color: {fg};
                font-weight: bold;
                min-width: 20px;
                padding: 0px;
            }}
            QPushButton:hover {{
                background-color: {hb_hover};
                border-color: {hb_border_hover};
            }}
            QPushButton:pressed {{
                background-color: {hb_pressed};
                border-color: {hb_border};
            }}
            QPushButton:disabled {{
                color: #888888;
            }}
        """


def _themed_svg_pixmap(asset_name: str, color: str, size_px: int) -> QPixmap:
    path = asset_path(asset_name)
    with open(path, encoding="utf-8") as f:
        svg_data = f.read().replace(_COLOR_PLACEHOLDER, color)
    renderer = QSvgRenderer(svg_data.encode("utf-8"))
    pixmap = QPixmap(size_px, size_px)
    pixmap.fill(Qt.GlobalColor.transparent)
    if renderer.isValid():
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
    return pixmap


def themed_svg_icon(
    asset_name: str, color: str, size_px: int = TITLEBAR_ICON_SIZE_PX
) -> QIcon:
    return QIcon(_themed_svg_pixmap(asset_name, color, size_px))


def titlebar_tools_icon_pair(
    size_px: int = TITLEBAR_ICON_SIZE_PX,
) -> tuple[QIcon, QIcon]:
    normal, hover = titlebar_icon_colors()
    asset = "job_pane_tools_icon.svg"
    return (
        themed_svg_icon(asset, normal, size_px),
        themed_svg_icon(asset, hover, size_px),
    )


def titlebar_flyout_icon_pair(
    pane_mode: bool, size_px: int = TITLEBAR_ICON_SIZE_PX
) -> tuple[QIcon, QIcon]:
    asset = "titlebar_flyout.svg" if pane_mode else "titlebar_flyin.svg"
    normal, hover = titlebar_icon_colors()
    return (
        themed_svg_icon(asset, normal, size_px),
        themed_svg_icon(asset, hover, size_px),
    )


def titlebar_hide_icon_pair(
    mode: str = "minus", size_px: int = TITLEBAR_ICON_SIZE_PX
) -> tuple[QIcon, QIcon]:
    asset = _HIDE_ICON_ASSETS.get(mode, _HIDE_ICON_ASSETS["minus"])
    normal, hover = titlebar_icon_colors()
    return (
        themed_svg_icon(asset, normal, size_px),
        themed_svg_icon(asset, hover, size_px),
    )


def apply_titlebar_button_icons(
    button,
    normal_icon: QIcon,
    hover_icon: QIcon,
    *,
    size_px: int = TITLEBAR_ICON_SIZE_PX,
) -> None:
    button.setIconSize(QSize(size_px, size_px))
    swap = getattr(button, "_titlebar_icon_swap", None)
    if swap is None:
        from widgets.icon_hover_swap import attach_icon_hover_swap

        button._titlebar_icon_swap = attach_icon_hover_swap(
            button, normal_icon, hover_icon
        )
    else:
        swap.set_icons(normal_icon, hover_icon)


def refresh_header_titlebar_icons(header) -> None:
    """Refresh hide, tools, and flyout button icons on a HeaderWidget."""
    hide = getattr(header, "hide_button", None)
    if hide is not None:
        mode = getattr(header, "_hide_button_mode", "minus")
        apply_titlebar_button_icons(hide, *titlebar_hide_icon_pair(mode))
    tools = getattr(header, "tools_button", None)
    if tools is not None:
        apply_titlebar_button_icons(tools, *titlebar_tools_icon_pair())
    fly = getattr(header, "flyout_button", None)
    if fly is not None:
        pane_mode = fly.property("_titlebar_flyout_pane_mode")
        if pane_mode is None:
            pane_mode = True
        apply_titlebar_button_icons(fly, *titlebar_flyout_icon_pair(bool(pane_mode)))
