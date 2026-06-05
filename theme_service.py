#!/usr/bin/env python3
"""Active theme registry, persistence, and sync into legacy thumbnail_constants globals."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, replace
from typing import Any, Dict, Optional, Union

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication

from dark_theme_definitions import DEFAULT_DARK_THEME, DarkTheme
from light_theme_definitions import DEFAULT_LIGHT_THEME, LightTheme
from theme_defaults import (
    default_dark_theme_colors,
    default_light_theme_colors,
    default_user_theme_colors,
)

ThemeType = Union[DarkTheme, LightTheme]

# Keys persisted under config["user_theme_colors"] — must match DarkTheme field names.
USER_THEME_COLOR_KEYS = (
    "default_background_color_hex",
    "text_color_hex",
    "default_image_color_hex",
    "default_image_background_color_hex",
    "current_image_border_color_hex",
    "current_image_background_color_hex",
    "multiselect_border_color_hex",
    "multiselect_background_color_hex",
    "sidebar_header_bg_hex",
    "default_border_color_hex",
)

# Persisted with theme color dicts (int 0–10 px per thumbnail border type)
THEME_BORDER_WIDTH_KEYS = (
    "default_image_border_width_index",
    "current_image_border_width_index",
    "multiselect_border_width_index",
)

# Splitter handles + status bar top (1–8 px), per preset
VIEW_CHROME_THEME_KEYS = ("view_border_width_px",)

# Thumbnail grid paint + borders only (no global QSS / settings-dialog chrome refresh needed).
THEME_THUMBNAIL_ONLY_KEYS = frozenset(
    (
        "default_image_color_hex",
        "default_image_background_color_hex",
        "current_image_border_color_hex",
        "current_image_background_color_hex",
        "multiselect_border_color_hex",
        "multiselect_background_color_hex",
        *THEME_BORDER_WIDTH_KEYS,
    )
)

# Application-wide QWidget / QSS palette (requires QApplication.setStyleSheet).
THEME_APP_WIDE_KEYS = frozenset(
    (
        "default_background_color_hex",
        "text_color_hex",
    )
)

# Splitters, sidebars, status bar chrome (per-widget stylesheets; no global QSS).
THEME_CHROME_KEYS = frozenset(
    (
        "sidebar_header_bg_hex",
        "default_border_color_hex",
        *VIEW_CHROME_THEME_KEYS,
    )
)


def theme_apply_scope_for_keys(changed_keys: Optional[set]) -> str:
    """Return the lightest apply path needed: 'thumbnail', 'chrome', or 'full'."""
    if not changed_keys:
        return "full"
    keys = frozenset(changed_keys)
    if keys.issubset(THEME_THUMBNAIL_ONLY_KEYS):
        return "thumbnail"
    if keys.isdisjoint(THEME_APP_WIDE_KEYS):
        return "chrome"
    return "full"

_VIEW_CHROME_BORDER_MIN_PX = 0
_VIEW_CHROME_BORDER_MAX_PX = 8


def _assert_theme_palette_structural_parity() -> None:
    """LightTheme and DarkTheme must declare identical field names in the same order."""
    lnames = [f.name for f in fields(LightTheme)]
    dnames = [f.name for f in fields(DarkTheme)]
    if lnames != dnames:
        only_l = sorted(set(lnames) - set(dnames))
        only_d = sorted(set(dnames) - set(lnames))
        raise AssertionError(
            "LightTheme and DarkTheme dataclass fields must match exactly. "
            f"only in light: {only_l}; only in dark: {only_d}"
        )


_assert_theme_palette_structural_parity()

THEMES: Dict[str, ThemeType] = {
    "dark": DEFAULT_DARK_THEME,
    "light": DEFAULT_LIGHT_THEME,
}

_active_theme: ThemeType = DEFAULT_DARK_THEME

_theme_main_window: Any = None
_system_theme_listener_connected = False


def get_active_theme() -> ThemeType:
    return _active_theme


def get_theme(theme_id: str) -> Optional[ThemeType]:
    return THEMES.get((theme_id or "dark").lower())


def normalize_theme_id(theme_id: str) -> str:
    tid = (theme_id or "dark").lower()
    if tid in THEMES or tid in ("user", "system"):
        return tid
    return "dark"


def system_appearance_theme_id() -> str:
    """Map macOS/Qt appearance to 'dark' or 'light'."""
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Light:
        return "light"
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    return "dark"


def resolve_theme_id_for_apply(theme_id: str) -> str:
    """Resolve stored ui_theme (including 'system') to dark/light/user for palette application."""
    tid = normalize_theme_id(theme_id)
    if tid == "system":
        return system_appearance_theme_id()
    return tid


def resolved_ui_theme_from_settings(settings: dict) -> str:
    """Browse transparency and other per-theme settings use this (system -> dark/light)."""
    return resolve_theme_id_for_apply((settings.get("ui_theme") or "dark"))


def set_theme_main_window(main_window: Any) -> None:
    global _theme_main_window
    _theme_main_window = main_window


def sync_view_theme_menu_actions(main_window: Any, ui_theme_id: str) -> None:
    tid = normalize_theme_id(ui_theme_id)
    if getattr(main_window, "theme_system_action", None) is not None:
        main_window.theme_system_action.setChecked(tid == "system")
    if getattr(main_window, "theme_dark_action", None) is not None:
        main_window.theme_dark_action.setChecked(tid == "dark")
        main_window.theme_light_action.setChecked(tid == "light")
    if getattr(main_window, "theme_user_action", None) is not None:
        main_window.theme_user_action.setChecked(tid == "user")


def connect_system_theme_listener() -> None:
    """Re-apply theme when OS light/dark changes while ui_theme is 'system'."""
    global _system_theme_listener_connected
    if _system_theme_listener_connected:
        return
    QGuiApplication.styleHints().colorSchemeChanged.connect(_on_system_color_scheme_changed)
    _system_theme_listener_connected = True


def _on_system_color_scheme_changed(_scheme: Qt.ColorScheme) -> None:
    try:
        from config import get_config

        cfg = get_config()
        if normalize_theme_id(cfg.load_settings().get("ui_theme", "dark")) != "system":
            return
    except Exception:
        return
    apply_theme(
        "system",
        app=QApplication.instance(),
        main_window=_theme_main_window,
        persist=False,
        config=cfg,
    )
    if _theme_main_window is not None:
        sync_view_theme_menu_actions(_theme_main_window, "system")


def _coerce_image_border_width(stored: Any, fallback: int) -> int:
    if isinstance(stored, int) and 0 <= stored <= 10:
        return stored
    if isinstance(stored, str) and stored.strip().isdigit():
        i = int(stored.strip())
        if 0 <= i <= 10:
            return i
    return fallback


def _coerce_view_border_width(stored: Any, fallback: int) -> int:
    lo, hi = _VIEW_CHROME_BORDER_MIN_PX, _VIEW_CHROME_BORDER_MAX_PX
    if isinstance(stored, int) and lo <= stored <= hi:
        return stored
    if isinstance(stored, str) and stored.strip().isdigit():
        i = int(stored.strip())
        if lo <= i <= hi:
            return i
    return max(lo, min(hi, fallback))


def _merge_view_border_width(out: Dict[str, Any], stored: Optional[Dict[str, Any]]) -> None:
    fb = _coerce_view_border_width(out.get("view_border_width_px"), 2)
    if stored and "view_border_width_px" in stored:
        out["view_border_width_px"] = _coerce_view_border_width(stored.get("view_border_width_px"), fb)
    else:
        out["view_border_width_px"] = fb


def _splitter_hover_pressed_from_chrome(chrome_hex: str) -> tuple[str, str]:
    """Hover/pressed splitter handle colors derived from chrome border (lighter, like stock dark theme)."""
    c = QColor(chrome_hex)
    if not c.isValid():
        return chrome_hex, chrome_hex
    return QColor(c).lighter(125).name(), QColor(c).lighter(145).name()


def _shortcuts_sidebar_chrome_from_theme(bg: str, border: str, splitter_hover: str) -> Dict[str, str]:
    """Organize sidebar: panel/scroll/combo/gear/HR from application background and chrome border.

    DEFAULT_DARK_THEME left shortcuts_panel_bg_hex / shortcuts_scroll_bg_hex as #000000; customizable
    themes must override them or the Organize pane stays black while the shell uses default_background.
    """
    q = QColor(bg)
    gear_hover = q.lighter(115).name() if q.isValid() else bg
    return {
        "shortcuts_panel_bg_hex": bg,
        "shortcuts_scroll_bg_hex": bg,
        "shortcuts_combo_bg_hex": bg,
        "shortcuts_combo_border_hex": border,
        "shortcuts_combo_hover_border_hex": splitter_hover,
        "shortcuts_gear_border_hex": border,
        "shortcuts_gear_border_hover_hex": splitter_hover,
        "shortcuts_gear_bg_hex": bg,
        "shortcuts_gear_bg_hover_hex": gear_hover,
        "shortcuts_hr_hex": border,
    }


def _merge_border_width_indices(out: Dict[str, Any], stored: Optional[Dict[str, Any]]) -> None:
    """Fill default/current/multiselect border width indices; migrate legacy image_border_width_index."""
    legacy: Optional[int] = None
    if stored and "image_border_width_index" in stored:
        legacy = _coerce_image_border_width(stored.get("image_border_width_index"), 2)

    def pick(key: str, fallback: int, use_legacy: bool) -> int:
        if stored and key in stored:
            return _coerce_image_border_width(stored.get(key), fallback)
        if use_legacy and legacy is not None:
            return legacy
        return fallback

    out["default_image_border_width_index"] = pick(
        "default_image_border_width_index", int(out["default_image_border_width_index"]), False
    )
    out["current_image_border_width_index"] = pick(
        "current_image_border_width_index", int(out["current_image_border_width_index"]), True
    )
    out["multiselect_border_width_index"] = pick(
        "multiselect_border_width_index", int(out["multiselect_border_width_index"]), True
    )


def merge_user_theme_colors(stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge persisted user_theme_colors with defaults; unknown keys dropped."""
    out = default_user_theme_colors()
    if not stored:
        return out
    for k in USER_THEME_COLOR_KEYS:
        v = stored.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    _merge_border_width_indices(out, stored)
    _merge_view_border_width(out, stored)
    return out


def merge_dark_theme_colors(stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge persisted dark_theme_colors with built-in dark defaults."""
    out = default_dark_theme_colors()
    if not stored:
        return out
    for k in USER_THEME_COLOR_KEYS:
        v = stored.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    _merge_border_width_indices(out, stored)
    _merge_view_border_width(out, stored)
    return out


def merge_light_theme_colors(stored: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge persisted light_theme_colors with built-in light defaults."""
    out = default_light_theme_colors()
    if not stored:
        return out
    for k in USER_THEME_COLOR_KEYS:
        v = stored.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    _merge_border_width_indices(out, stored)
    _merge_view_border_width(out, stored)
    return out


def build_user_theme_from_colors(colors: Dict[str, Any]) -> DarkTheme:
    """
    Build the active user theme from customizable colors (dark stylesheet base).
    Propagates text_color_hex into main views and status bar label styling.
    """
    c = merge_user_theme_colors(colors)
    text = c["text_color_hex"]
    border = c["default_border_color_hex"]
    bg = c["default_background_color_hex"]
    t0 = DEFAULT_DARK_THEME
    sh, sp = _splitter_hover_pressed_from_chrome(border)
    dbw = int(c["default_image_border_width_index"])
    cbw = int(c["current_image_border_width_index"])
    mbw = int(c["multiselect_border_width_index"])
    vbw = int(c["view_border_width_px"])
    return replace(
        t0,
        theme_id="user",
        general_text_color_hex=text,
        general_bg_color_hex=bg,
        default_background_color_hex=bg,
        text_color_hex=text,
        dialog_text_color_hex=text,
        default_image_color_hex=c["default_image_color_hex"],
        default_image_background_color_hex=c["default_image_background_color_hex"],
        current_image_border_color_hex=c["current_image_border_color_hex"],
        current_image_background_color_hex=c["current_image_background_color_hex"],
        default_image_border_width_index=dbw,
        current_image_border_width_index=cbw,
        multiselect_border_width_index=mbw,
        view_border_width_px=vbw,
        multiselect_border_color_hex=c["multiselect_border_color_hex"],
        multiselect_background_color_hex=c["multiselect_background_color_hex"],
        sidebar_header_bg_hex=c["sidebar_header_bg_hex"],
        # Thumbnail cell border only — not Qt control borders (those keep t0.border_default_hex / border_hover_hex)
        default_border_color_hex=border,
        # Splitters, status bar top, section header frames (see chrome_border_hex in theme.py)
        chrome_border_hex=border,
        splitter_handle_hex=border,
        splitter_handle_hover_hex=sh,
        splitter_handle_pressed_hex=sp,
        sidebar_splitter_handle_hex=border,
        sidebar_header_border_hex=border,
        status_bar_label_text_hex=text,
        tree_view_text_hex=text,
        browse_view_fg_hex=text,
        thumbnail_status_label_text_hex=text,
        shortcuts_sidebar_primary_text_hex=text,
        shortcuts_sidebar_heading_text_hex=text,
        sidebar_header_text_hex=text,
        file_tree_nav_button_text_hex=text,
        information_link_tooltip_fg_hex=text,
        # Information pane and right sidebar shell use the same customizable default background
        right_sidebar_combined_bg_hex=bg,
        information_panel_bg_hex=bg,
        information_textbrowser_bg_hex=bg,
        information_link_tooltip_bg_hex=bg,
        **_shortcuts_sidebar_chrome_from_theme(bg, border, sh),
    )


def build_dark_theme_from_colors(colors: Dict[str, str]) -> DarkTheme:
    """Build dark preset from customizable colors (same propagation as user theme)."""
    c = merge_dark_theme_colors(colors)
    text = c["text_color_hex"]
    border = c["default_border_color_hex"]
    bg = c["default_background_color_hex"]
    t0 = DEFAULT_DARK_THEME
    sh, sp = _splitter_hover_pressed_from_chrome(border)
    dbw = int(c["default_image_border_width_index"])
    cbw = int(c["current_image_border_width_index"])
    mbw = int(c["multiselect_border_width_index"])
    vbw = int(c["view_border_width_px"])
    return replace(
        t0,
        theme_id="dark",
        general_text_color_hex=text,
        general_bg_color_hex=bg,
        default_background_color_hex=bg,
        text_color_hex=text,
        dialog_text_color_hex=text,
        default_image_color_hex=c["default_image_color_hex"],
        default_image_background_color_hex=c["default_image_background_color_hex"],
        current_image_border_color_hex=c["current_image_border_color_hex"],
        current_image_background_color_hex=c["current_image_background_color_hex"],
        default_image_border_width_index=dbw,
        current_image_border_width_index=cbw,
        multiselect_border_width_index=mbw,
        view_border_width_px=vbw,
        multiselect_border_color_hex=c["multiselect_border_color_hex"],
        multiselect_background_color_hex=c["multiselect_background_color_hex"],
        sidebar_header_bg_hex=c["sidebar_header_bg_hex"],
        default_border_color_hex=border,
        chrome_border_hex=border,
        splitter_handle_hex=border,
        splitter_handle_hover_hex=sh,
        splitter_handle_pressed_hex=sp,
        sidebar_splitter_handle_hex=border,
        sidebar_header_border_hex=border,
        status_bar_label_text_hex=text,
        tree_view_text_hex=text,
        browse_view_fg_hex=text,
        thumbnail_status_label_text_hex=text,
        shortcuts_sidebar_primary_text_hex=text,
        shortcuts_sidebar_heading_text_hex=text,
        sidebar_header_text_hex=text,
        file_tree_nav_button_text_hex=text,
        information_link_tooltip_fg_hex=text,
        right_sidebar_combined_bg_hex=bg,
        information_panel_bg_hex=bg,
        information_textbrowser_bg_hex=bg,
        information_link_tooltip_bg_hex=bg,
        **_shortcuts_sidebar_chrome_from_theme(bg, border, sh),
    )


def build_light_theme_from_colors(colors: Dict[str, str]) -> LightTheme:
    """Build light preset from customizable colors (mirrors user-theme propagation)."""
    c = merge_light_theme_colors(colors)
    text = c["text_color_hex"]
    border = c["default_border_color_hex"]
    bg = c["default_background_color_hex"]
    t0 = DEFAULT_LIGHT_THEME
    sh, sp = _splitter_hover_pressed_from_chrome(border)
    dbw = int(c["default_image_border_width_index"])
    cbw = int(c["current_image_border_width_index"])
    mbw = int(c["multiselect_border_width_index"])
    vbw = int(c["view_border_width_px"])
    return replace(
        t0,
        theme_id="light",
        general_text_color_hex=text,
        general_bg_color_hex=bg,
        default_background_color_hex=bg,
        text_color_hex=text,
        dialog_text_color_hex=text,
        default_image_color_hex=c["default_image_color_hex"],
        default_image_background_color_hex=c["default_image_background_color_hex"],
        current_image_border_color_hex=c["current_image_border_color_hex"],
        current_image_background_color_hex=c["current_image_background_color_hex"],
        default_image_border_width_index=dbw,
        current_image_border_width_index=cbw,
        multiselect_border_width_index=mbw,
        view_border_width_px=vbw,
        multiselect_border_color_hex=c["multiselect_border_color_hex"],
        multiselect_background_color_hex=c["multiselect_background_color_hex"],
        sidebar_header_bg_hex=c["sidebar_header_bg_hex"],
        default_border_color_hex=border,
        chrome_border_hex=border,
        splitter_handle_hex=border,
        splitter_handle_hover_hex=sh,
        splitter_handle_pressed_hex=sp,
        sidebar_splitter_handle_hex=border,
        sidebar_header_border_hex=border,
        status_bar_label_text_hex=text,
        tree_view_text_hex=text,
        browse_view_fg_hex=text,
        thumbnail_status_label_text_hex=text,
        shortcuts_sidebar_primary_text_hex=text,
        shortcuts_sidebar_heading_text_hex=text,
        file_tree_nav_button_text_hex=text,
        information_link_tooltip_fg_hex=text,
        right_sidebar_combined_bg_hex=bg,
        information_panel_bg_hex=bg,
        information_textbrowser_bg_hex=bg,
        information_link_tooltip_bg_hex=bg,
        **_shortcuts_sidebar_chrome_from_theme(bg, border, sh),
    )


def load_user_theme_colors_from_config(config: Any) -> Dict[str, str]:
    try:
        settings = config.load_settings()
    except Exception:
        settings = {}
    return merge_user_theme_colors(settings.get("user_theme_colors"))


def load_dark_theme_colors_from_config(config: Any) -> Dict[str, str]:
    try:
        settings = config.load_settings()
    except Exception:
        settings = {}
    return merge_dark_theme_colors(settings.get("dark_theme_colors"))


def load_light_theme_colors_from_config(config: Any) -> Dict[str, str]:
    try:
        settings = config.load_settings()
    except Exception:
        settings = {}
    return merge_light_theme_colors(settings.get("light_theme_colors"))


def _qcolor_from_rgba_csv(s: str) -> QColor:
    parts = [int(x.strip()) for x in s.split(",")]
    if len(parts) >= 4:
        return QColor(parts[0], parts[1], parts[2], parts[3])
    if len(parts) == 3:
        return QColor(parts[0], parts[1], parts[2])
    return QColor()


def sync_to_thumbnail_constants(theme: ThemeType) -> None:
    """Copy theme palette into thumbnail_constants module globals (legacy single source for painting)."""
    import thumbnail_constants as tc

    t = theme
    tc.CURRENT_IMAGE_BACKGROUND_COLOR_HEX = t.current_image_background_color_hex
    tc.CURRENT_IMAGE_BACKGROUND_COLOR = QColor(t.current_image_background_color_hex)
    tc.CURRENT_IMAGE_BORDER_COLOR_HEX = t.current_image_border_color_hex
    tc.CURRENT_IMAGE_BORDER_COLOR = QColor(t.current_image_border_color_hex)
    _mw = int(getattr(tc, "MAX_THEME_BORDER_WIDTH_PX", 10))
    tc.DEFAULT_IMAGE_BORDER_WIDTH_PX = max(0, min(_mw, int(getattr(t, "default_image_border_width_index", 1))))
    tc.CURRENT_IMAGE_BORDER_WIDTH_PX = max(0, min(_mw, int(getattr(t, "current_image_border_width_index", 2))))
    tc.MULTISELECT_BORDER_WIDTH_PX = max(0, min(_mw, int(getattr(t, "multiselect_border_width_index", 2))))
    # Legacy alias: highlight width (same as current)
    tc.IMAGE_BORDER_WIDTH_PX = tc.CURRENT_IMAGE_BORDER_WIDTH_PX

    tc.MULTISELECT_BACKGROUND_COLOR_HEX = t.multiselect_background_color_hex
    _ms = QColor(t.multiselect_background_color_hex)
    if _ms.isValid():
        _ms.setAlpha(130)
    tc.MULTISELECT_BACKGROUND_COLOR = _ms
    tc.MULTISELECT_BORDER_COLOR_HEX = t.multiselect_border_color_hex
    tc.MULTISELECT_BORDER_COLOR = QColor(t.multiselect_border_color_hex)

    tc.DEFAULT_BACKGROUND_COLOR_HEX = t.default_background_color_hex
    tc.DEFAULT_BACKGROUND_COLOR = QColor(t.default_background_color_hex)
    tc.DEFAULT_BORDER_COLOR_HEX = t.default_border_color_hex
    tc.DEFAULT_BORDER_COLOR = QColor(t.default_border_color_hex)
    tc.DEFAULT_IMAGE_BACKGROUND_COLOR_HEX = t.default_image_background_color_hex
    tc.DEFAULT_IMAGE_BACKGROUND_COLOR = QColor(t.default_image_background_color_hex)
    tc.DEFAULT_IMAGE_COLOR_HEX = t.default_image_color_hex
    tc.DEFAULT_IMAGE_COLOR = QColor(t.default_image_color_hex)

    tc.TEXT_COLOR_HEX = t.text_color_hex
    tc.TEXT_COLOR = QColor(t.text_color_hex)
    tc.QMENU_DEFAULT_STYLE_SHEET = t.qmenu_stylesheet()

    tc.TAB_BUTTON_FOCUS_BACKGROUND_COLOR_HEX = t.tab_button_focus_background_color_hex
    tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX = t.tab_button_focus_border_color_hex

    tc.HEADING_COLOR = QColor(t.heading_color_hex())
    tc.HEADING_COLOR_HEX = t.heading_color_hex()

    tc.DIALOG_TEXT_COLOR = QColor(t.dialog_text_color_hex)
    tc.DIALOG_TEXT_COLOR_HEX = t.dialog_text_color_hex

    tc.DIALOG_BACKGROUND_HEX = t.dialog_background_hex
    tc.WIDGET_BG_HOVER_HEX = t.widget_bg_hover_hex
    tc.WIDGET_BG_PRESSED_HEX = t.widget_bg_pressed_hex
    tc.WIDGET_BG_DISABLED_HEX = t.widget_bg_disabled_hex
    tc.TEXT_DISABLED_HEX = t.text_disabled_hex
    tc.BORDER_DEFAULT_HEX = t.border_default_hex
    tc.BORDER_HOVER_HEX = t.border_hover_hex
    tc.CHROME_BORDER_HEX = t.chrome_border_hex
    _vb_lo = int(getattr(tc, "MIN_VIEW_CHROME_BORDER_WIDTH_PX", 0))
    _vb_hi = int(getattr(tc, "MAX_VIEW_CHROME_BORDER_WIDTH_PX", 8))
    tc.VIEW_BORDER_WIDTH_PX = max(_vb_lo, min(_vb_hi, int(getattr(t, "view_border_width_px", 2))))

    tc.BUTTON_BG_DEFAULT_HEX = t.button_bg_default_hex
    tc.BUTTON_TEXT_DEFAULT_HEX = t.button_text_default_hex
    tc.BUTTON_BORDER_DEFAULT_HEX = t.button_border_default_hex
    tc.BUTTON_BG_HOVER_HEX = t.button_bg_hover_hex
    tc.BUTTON_TEXT_HOVER_HEX = t.button_text_hover_hex
    tc.BUTTON_BORDER_HOVER_HEX = t.button_border_hover_hex
    tc.BUTTON_BG_PRESSED_HEX = t.button_bg_pressed_hex
    tc.BUTTON_FOCUS_TEXT_HEX = t.button_focus_text_hex
    tc.BUTTON_DEFAULT_BG_HEX = t.button_default_bg_hex
    tc.BUTTON_DEFAULT_BORDER_HEX = t.button_default_border_hex

    tc.SIDEBAR_HEADER_BG_HEX = t.sidebar_header_bg_hex
    tc.SIDEBAR_HEADER_BORDER_HEX = t.sidebar_header_border_hex
    tc.SIDEBAR_HEADER_TEXT_HEX = t.sidebar_header_text_hex
    tc.SIDEBAR_SPLITTER_HANDLE_HEX = t.sidebar_splitter_handle_hex
    tc.TREE_HEADER_FOCUS_BG_HEX = t.tree_header_focus_bg_hex

    tc.ERROR_COLOR_HEX = t.error_color_hex
    tc.VALIDATION_SUCCESS_COLOR_HEX = t.validation_success_color_hex
    tc.ACCENT_COLOR_HEX = t.accent_color_hex
    tc.TAB_BUTTON_HOVER_BG_HEX = t.tab_button_hover_bg_hex

    tc.LOCKED_FILE_BACKGROUND_COLOR = QColor(t.locked_file_background_hex)
    tc.TREE_FOLDER_WITH_IMAGES_COLOR = QColor(t.tree_folder_with_images_hex)

    tc.THUMBNAIL_FILENAME_OVERLAY_BOX_COLOR = _qcolor_from_rgba_csv(t.thumbnail_filename_overlay_rgba)
    tc.THUMBNAIL_EMPTY_FILTER_BTN_BG = QColor(t.thumbnail_empty_filter_btn_bg_hex)
    tc.THUMBNAIL_EMPTY_FILTER_BTN_BG_HOVER = QColor(t.thumbnail_empty_filter_btn_bg_hover_hex)
    tc.THUMBNAIL_EMPTY_FILTER_BTN_BORDER = QColor(t.thumbnail_empty_filter_btn_border_hex)
    tc.THUMBNAIL_EMPTY_FILTER_BTN_BORDER_HOVER = QColor(t.thumbnail_empty_filter_btn_border_hover_hex)
    tc.THUMBNAIL_EMPTY_FILTER_BTN_TEXT_HOVER = QColor(t.thumbnail_empty_filter_btn_text_hover_hex)


def apply_theme(
    theme_id: str,
    *,
    app: Optional[QApplication] = None,
    main_window: Any = None,
    persist: bool = False,
    config: Any = None,
    user_theme_colors: Optional[Dict[str, Any]] = None,
    dark_theme_colors: Optional[Dict[str, Any]] = None,
    light_theme_colors: Optional[Dict[str, Any]] = None,
    apply_scope: str = "full",
) -> str:
    """
    Activate a theme by id, sync legacy constants, optionally set QApplication stylesheet,
    persist to settings, and refresh main window chrome.

    For theme_id \"user\", pass user_theme_colors to apply a specific palette without reading
    config, or None to load user_theme_colors from config.

    For \"dark\" / \"light\", pass dark_theme_colors / light_theme_colors to preview overrides,
    or None to load persisted preset colors from config.

    apply_scope controls how much UI is restyled after syncing constants:
      - \"full\": global QApplication stylesheet + refresh_theme_styles (default)
      - \"chrome\": refresh_theme_styles only (splitters, sidebars, per-widget chrome)
      - \"thumbnail\": thumbnail canvas repaint only

    Returns the stored/normalized theme id (e.g. 'system', 'dark', 'light', 'user').
    """
    if apply_scope not in ("full", "chrome", "thumbnail"):
        apply_scope = "full"
    global _active_theme
    stored_tid = normalize_theme_id(theme_id)
    apply_tid = resolve_theme_id_for_apply(stored_tid)
    if apply_tid == "user":
        if user_theme_colors is not None:
            merged = merge_user_theme_colors(user_theme_colors)
        else:
            try:
                if config is None:
                    from config import get_config

                    config = get_config()
                merged = load_user_theme_colors_from_config(config)
            except Exception:
                merged = merge_user_theme_colors(None)
        _active_theme = build_user_theme_from_colors(merged)
        if persist:
            try:
                if config is None:
                    from config import get_config

                    config = get_config()
                settings = config.load_settings()
                settings["user_theme_colors"] = deepcopy(merged)
                settings["ui_theme"] = "user"
                config.save_settings(settings)
            except Exception:
                pass
    elif apply_tid == "dark":
        if dark_theme_colors is not None:
            merged = merge_dark_theme_colors(dark_theme_colors)
        else:
            try:
                if config is None:
                    from config import get_config

                    config = get_config()
                merged = load_dark_theme_colors_from_config(config)
            except Exception:
                merged = merge_dark_theme_colors(None)
        _active_theme = build_dark_theme_from_colors(merged)
    elif apply_tid == "light":
        if light_theme_colors is not None:
            merged = merge_light_theme_colors(light_theme_colors)
        else:
            try:
                if config is None:
                    from config import get_config

                    config = get_config()
                merged = load_light_theme_colors_from_config(config)
            except Exception:
                merged = merge_light_theme_colors(None)
        _active_theme = build_light_theme_from_colors(merged)

    sync_to_thumbnail_constants(_active_theme)

    if apply_scope == "full" and app is not None:
        app.setStyleSheet(_active_theme.global_stylesheet())

    if persist and stored_tid != "user":
        try:
            if config is None:
                from config import get_config

                config = get_config()
            config.update_setting("ui_theme", stored_tid)
        except Exception:
            pass

    if main_window is not None:
        try:
            if apply_scope == "thumbnail":
                if hasattr(main_window, "refresh_thumbnail_theme_styles"):
                    main_window.refresh_thumbnail_theme_styles()
            elif hasattr(main_window, "refresh_theme_styles"):
                main_window.refresh_theme_styles()
        except Exception:
            pass

    return stored_tid


def get_dark_theme_stylesheet() -> str:
    """Backward-compatible name: global stylesheet for the active theme."""
    return get_active_theme().global_stylesheet()
