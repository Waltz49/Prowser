#!/usr/bin/env python3
"""Active theme registry, persistence, and sync into legacy thumbnail_constants globals."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, fields, replace
from typing import Any, Dict, Optional, Tuple, Union

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication

from theme.dark_theme_definitions import DEFAULT_DARK_THEME, DarkTheme
from theme.theme import ThemeStylesMixin, sidebar_header_focus_bg_hex
from theme.theme_defaults import (
    default_dark_theme_colors,
    default_light_theme_colors,
    default_user_theme_colors,
)


@dataclass(frozen=True)
class LightTheme(ThemeStylesMixin):
    theme_id: str = "light"
    general_text_color_hex: str = "black"
    general_bg_color_hex: str = "#c0c0c0"

    current_image_background_color_hex: str = "skyblue"
    current_image_border_color_hex: str = "navy"
    multiselect_background_color_hex: str = "gold"
    multiselect_border_color_hex: str = "#e65100"
    default_image_border_width_index: int = 1
    current_image_border_width_index: int = 2
    multiselect_border_width_index: int = 2
    view_border_width_px: int = 2

    default_background_color_hex: str = general_bg_color_hex
    thumbnail_grid_background_color_hex: str = general_bg_color_hex
    default_border_color_hex: str = "#cfd8dc"
    default_image_background_color_hex: str = general_bg_color_hex
    default_image_color_hex: str = "#222222"
    thumbnail_text_color_hex: str = general_text_color_hex
    text_color_hex: str = general_text_color_hex

    dialog_background_hex: str = "#ececec"
    widget_bg_hover_hex: str = "#dadada"
    widget_bg_pressed_hex: str = "#c8c8c8"
    widget_bg_disabled_hex: str = "#e0e0e0"
    text_disabled_hex: str = "#888888"
    border_default_hex: str = "#b8b8b8"
    border_hover_hex: str = "#989898"
    chrome_border_hex: str = "#282c39"

    tab_button_focus_background_color_hex: str = "#d0d8e8"
    tab_button_focus_border_color_hex: str = "#2b6cb0"
    tab_button_hover_bg_hex: str = "#e4e4e4"

    dialog_text_color_hex: str = general_text_color_hex
    dialog_input_background_hex: str = "#ffffff"

    button_bg_default_hex: str = "#f0f4f8"
    button_text_default_hex: str = "#1a2a3a"
    button_border_default_hex: str = "#7a9ab8"
    button_bg_hover_hex: str = "#dde8f4"
    button_text_hover_hex: str = "#0a1a2a"
    button_border_hover_hex: str = "#4a7aaa"
    button_bg_pressed_hex: str = "#c8d8e8"
    button_focus_text_hex: str = "#0a0a0a"
    button_default_bg_hex: str = "#4a7aaa"
    button_default_border_hex: str = "#2a5a8a"

    sidebar_header_bg_hex: str = "#212833"
    sidebar_background_color_hex: str = general_bg_color_hex
    sidebar_text_color_hex: str = general_text_color_hex
    sidebar_header_border_hex: str = "#424242"
    sidebar_header_text_hex: str = "white"
    sidebar_splitter_handle_hex: str = "#c62828"
    tree_header_focus_bg_hex: str = "#b3d4fc"

    error_color_hex: str = "#cc2222"
    validation_success_color_hex: str = "#228822"
    accent_color_hex: str = "#2b6cb0"

    locked_file_background_hex: str = "#f0e0e8"
    tree_folder_with_images_hex: str = "#8a6f1a"

    tree_view_text_hex: str = general_text_color_hex
    tree_view_border_hex: str = "#c8c8c8"
    tree_view_selection_bg_hex: str = "#cce4f8"
    tree_view_item_hover_hex: str = "#e8f0f8"
    tree_header_section_bg_hex: str = "#e0e8f0"
    groupbox_border_hex: str = "#b0b0b0"
    qslider_handle_hover_border_hex: str = "#4a8ad0"
    qslider_handle_focus_border_hex: str = "#888888"
    qtooltip_bg_hex: str = "#fffff0"
    qtooltip_fg_hex: str = "#1a1a1a"
    qtooltip_border_hex: str = "#a0a0a0"
    spinbox_disabled_text_hex: str = "#999999"
    spinbox_disabled_border_hex: str = "#cccccc"
    checkbox_indicator_border_hex: str = "#606060"
    checkbox_indicator_hover_border_hex: str = "#404040"
    checkbox_indicator_focus_border_hex: str = "#303030"
    radiobutton_indicator_border_hex: str = "#606060"
    radiobutton_indicator_disabled_hex: str = "#c0c0c0"
    qmenu_item_disabled_hex: str = "#888888"

    splitter_handle_hex: str = "#282c39"
    splitter_handle_hover_hex: str = "#b71c1c"
    splitter_handle_pressed_hex: str = "#8e0000"
    main_status_bar_bg_hex: str = general_bg_color_hex
    status_bar_label_text_hex: str = general_text_color_hex
    status_bar_label_disabled_hex: str = "#666666"

    progress_bar_border_hex: str = "#a0a0a0"
    progress_bar_bg_hex: str = "#ececec"
    progress_bar_text_hex: str = general_text_color_hex
    progress_chunk_gradient_start: str = "#5a9ee8"
    progress_chunk_gradient_mid: str = "#3a7ec8"
    progress_chunk_gradient_end: str = "#2a5ea8"

    thumbnail_status_label_text_hex: str = general_text_color_hex

    thumbnail_filename_overlay_rgba: str = "248, 250, 252, 252"
    thumbnail_empty_filter_btn_bg_hex: str = "#f0f2f5"
    thumbnail_empty_filter_btn_bg_hover_hex: str = "#e3f2fd"
    thumbnail_empty_filter_btn_border_hex: str = "#b0bec5"
    thumbnail_empty_filter_btn_border_hover_hex: str = "#2196f3"
    thumbnail_empty_filter_btn_text_hover_hex: str = "#0d47a1"

    right_sidebar_combined_bg_hex: str = "#fafafa"

    browse_view_bg_rgb: str = "245, 245, 245"
    browse_view_fg_hex: str = general_text_color_hex
    browse_filename_bg_rgba: str = "255, 255, 255, 235"
    browse_filename_border_hex: str = "#c9a000"
    browse_filename_text_hex: str = general_text_color_hex
    browse_filename_doc_color_hex: str = "#222222"

    status_menu_border_hex: str = "#a8a8a8"
    status_menu_selected_hex: str = "#181818"
    status_menu_grayed_hex: str = "#888888"

    file_tree_item_highlighted_bg_hex: str = "#e3f2fd"
    file_tree_item_highlighted_selected_bg_hex: str = "#bbdefb"
    file_tree_delegate_drag_bg_hex: str = "#90caf9"
    file_tree_delegate_drag_text_hex: str = general_text_color_hex
    file_tree_nav_container_bg_hex: str = "#f0f0f0"
    file_tree_nav_button_bg_hex: str = "#eeeeee"
    file_tree_nav_button_border_hex: str = "#bdbdbd"
    file_tree_nav_button_hover_hex: str = "#e0e0e0"
    file_tree_nav_button_pressed_hex: str = "#d0d0d0"
    file_tree_nav_button_text_dim_hex: str = "#666666"
    file_tree_nav_button_text_hex: str = general_text_color_hex
    file_tree_dir_label_bg_hex: str = general_bg_color_hex
    file_tree_dir_label_border_hex: str = "#c0c0c0"
    file_tree_filter_btn_bg_hex: str = general_bg_color_hex
    file_tree_filter_btn_border_hex: str = "#a0a0a0"
    file_tree_filter_btn_hover_hex: str = "#f5f5f5"
    file_tree_filter_sep_hex: str = "#c0c0c0"
    file_tree_filter_icon_selected_hex: str = "#333333"
    file_tree_filter_icon_unselected_hex: str = "#888888"

    shortcuts_panel_bg_hex: str = general_bg_color_hex
    shortcuts_scroll_bg_hex: str = "#c8c8c8"
    shortcuts_combo_bg_hex: str = general_bg_color_hex
    shortcuts_combo_border_hex: str = "#c0c0c0"
    shortcuts_combo_hover_border_hex: str = "#909090"
    shortcuts_note_muted_hex: str = "#666666"
    shortcuts_hr_hex: str = "#bdbdbd"
    shortcuts_gear_border_hex: str = "#c0c0c0"
    shortcuts_gear_border_hover_hex: str = "#a0a0a0"
    shortcuts_gear_bg_hex: str = "#f5f5f5"
    shortcuts_gear_bg_hover_hex: str = "#eeeeee"
    shortcuts_sidebar_primary_text_hex: str = "#000000"
    shortcuts_sidebar_heading_text_hex: str = "#000000"
    sidebar_favorite_link_hover_hex: str = "#0b57d0"

    information_panel_bg_hex: str = general_bg_color_hex
    information_textbrowser_bg_hex: str = general_bg_color_hex
    information_link_tooltip_bg_hex: str = "#fffff0"
    information_link_tooltip_fg_hex: str = general_text_color_hex
    information_link_tooltip_border_hex: str = "#a0a0a0"
    information_table_border_hex: str = "#d0d0d0"
    information_action_chip_bg_hex: str = "#e8e8e8"
    information_action_icon_muted_hex: str = "#666666"
    information_icon_cell_border_muted_hex: str = "#cccccc"


DEFAULT_LIGHT_THEME = LightTheme()


ThemeType = Union[DarkTheme, LightTheme]

# Keys persisted under config["user_theme_colors"] — must match DarkTheme field names.
USER_THEME_COLOR_KEYS = (
    "default_background_color_hex",
    "text_color_hex",
    "dialog_background_hex",
    "dialog_text_color_hex",
    "dialog_input_background_hex",
    "thumbnail_grid_background_color_hex",
    "thumbnail_text_color_hex",
    "default_image_color_hex",
    "default_image_background_color_hex",
    "current_image_border_color_hex",
    "current_image_background_color_hex",
    "multiselect_border_color_hex",
    "multiselect_background_color_hex",
    "sidebar_header_bg_hex",
    "sidebar_background_color_hex",
    "sidebar_text_color_hex",
    "status_bar_background_color_hex",
    "status_bar_text_color_hex",
    "default_border_color_hex",
    "button_bg_default_hex",
    "button_border_default_hex",
    "button_bg_hover_hex",
    "button_border_hover_hex",
    "button_text_default_hex",
    "button_text_hover_hex",
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
        "thumbnail_grid_background_color_hex",
        "thumbnail_text_color_hex",
        "default_image_color_hex",
        "default_image_background_color_hex",
        "current_image_border_color_hex",
        "current_image_background_color_hex",
        "multiselect_border_color_hex",
        "multiselect_background_color_hex",
        *THEME_BORDER_WIDTH_KEYS,
    )
)

THEME_DIALOG_KEYS = frozenset(
    (
        "dialog_background_hex",
        "dialog_text_color_hex",
        "dialog_input_background_hex",
    )
)

# Application-wide QWidget / QSS palette (requires QApplication.setStyleSheet).
THEME_APP_WIDE_KEYS = frozenset(
    (
        "default_background_color_hex",
        "text_color_hex",
        "button_bg_default_hex",
        "button_border_default_hex",
        "button_bg_hover_hex",
        "button_border_hover_hex",
        "button_text_default_hex",
        "button_text_hover_hex",
    )
)

# Splitters, sidebars, status bar chrome (per-widget stylesheets; no global QSS).
THEME_CHROME_KEYS = frozenset(
    (
        "sidebar_header_bg_hex",
        "sidebar_background_color_hex",
        "sidebar_text_color_hex",
        "status_bar_background_color_hex",
        "status_bar_text_color_hex",
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
    if not keys.isdisjoint(THEME_DIALOG_KEYS):
        return "full"
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

BUILTIN_THEME_IDS = frozenset({"dark", "light", "user", "system"})
EDITABLE_BUILTIN_THEME_IDS = frozenset({"dark", "light", "user"})

_active_theme: ThemeType = DEFAULT_DARK_THEME

_theme_main_window: Any = None
_system_theme_listener_connected = False


def get_active_theme() -> ThemeType:
    return _active_theme


def apply_view_chrome_splitter_theme(splitter) -> None:
    """Apply View borders color and Splitter & status bar width to a QSplitter handle."""
    t = get_active_theme()
    w = t.view_border_width_px
    splitter.setHandleWidth(w)
    splitter.setStyleSheet(t.chrome_splitter_stylesheet())



def is_builtin_theme_id(theme_id: Optional[str]) -> bool:
    return (theme_id or "").lower() in BUILTIN_THEME_IDS


def is_editable_theme_id(theme_id: Optional[str], custom_themes: Optional[dict] = None) -> bool:
    tid = (theme_id or "").lower()
    if tid in EDITABLE_BUILTIN_THEME_IDS:
        return True
    if custom_themes is None:
        custom_themes = _load_custom_themes_for_normalize()
    return is_custom_theme_id(tid, custom_themes)


def is_custom_theme_id(theme_id: Optional[str], custom_themes: Optional[dict]) -> bool:
    tid = (theme_id or "").lower()
    if not tid or tid in BUILTIN_THEME_IDS:
        return False
    return isinstance(custom_themes, dict) and tid in custom_themes


def slugify_theme_display_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def validate_new_theme_display_name(
    name: str,
    custom_themes: Optional[dict],
) -> Tuple[Optional[str], Optional[str]]:
    """Return (slug, error_message). slug is None when validation fails."""
    display = (name or "").strip()
    if not display:
        return None, "Name cannot be empty."
    slug = slugify_theme_display_name(display)
    if not slug:
        return None, "Name must contain at least one letter or number."
    if slug in BUILTIN_THEME_IDS:
        return None, f"\"{display}\" is a reserved theme name."
    merged = merge_custom_themes(custom_themes)
    base_slug = slug
    n = 2
    while slug in merged:
        slug = f"{base_slug}_{n}"
        n += 1
    return slug, None


def merge_custom_theme_colors(
    stored: Optional[Dict[str, Any]],
    base: str,
) -> Dict[str, Any]:
    if base == "light":
        return merge_light_theme_colors(stored)
    if base == "user":
        return merge_user_theme_colors(stored)
    return merge_dark_theme_colors(stored)


def merge_custom_theme_browse_transparency(raw: Optional[dict]) -> Dict[str, Any]:
    from config import default_browse_transparency_entry

    out = default_browse_transparency_entry()
    if not isinstance(raw, dict):
        return out
    tc = raw.get("transparency_color")
    if isinstance(tc, (list, tuple)) and len(tc) >= 3:
        try:
            out["transparency_color"] = [int(tc[0]), int(tc[1]), int(tc[2])]
        except (TypeError, ValueError):
            pass
    if "use_diamonds" in raw:
        out["use_diamonds"] = bool(raw["use_diamonds"])
    bbc = raw.get("browse_border_color")
    if isinstance(bbc, (list, tuple)) and len(bbc) >= 3:
        try:
            out["browse_border_color"] = [int(bbc[0]), int(bbc[1]), int(bbc[2])]
        except (TypeError, ValueError):
            pass
    return out


def merge_custom_themes(raw: Optional[dict]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for slug, ent in raw.items():
        if not isinstance(slug, str) or not slug or slug in BUILTIN_THEME_IDS:
            continue
        if not isinstance(ent, dict):
            continue
        base = str(ent.get("base") or "dark").lower()
        if base not in EDITABLE_BUILTIN_THEME_IDS:
            base = "dark"
        display_name = str(ent.get("display_name") or slug).strip() or slug
        colors = merge_custom_theme_colors(ent.get("colors"), base)
        browse_transparency = merge_custom_theme_browse_transparency(ent.get("browse_transparency"))
        out[slug] = {
            "display_name": display_name,
            "base": base,
            "colors": colors,
            "browse_transparency": browse_transparency,
        }
    return out


def get_custom_theme_entry(
    custom_themes: Optional[dict],
    theme_id: str,
) -> Optional[Dict[str, Any]]:
    merged = merge_custom_themes(custom_themes)
    return merged.get((theme_id or "").lower())


def theme_base_for_id(theme_id: str, custom_themes: Optional[dict] = None) -> str:
    tid = (theme_id or "dark").lower()
    if tid in EDITABLE_BUILTIN_THEME_IDS:
        return tid
    entry = get_custom_theme_entry(custom_themes, tid)
    if entry:
        return str(entry.get("base") or "dark")
    return "dark"


def build_theme_from_custom_entry(tid: str, entry: Dict[str, Any]) -> ThemeType:
    base = str(entry.get("base") or "dark").lower()
    merged = merge_custom_theme_colors(entry.get("colors"), base)
    if base == "light":
        return replace(build_light_theme_from_colors(merged), theme_id=tid)
    if base == "user":
        return replace(build_user_theme_from_colors(merged), theme_id=tid)
    return replace(build_dark_theme_from_colors(merged), theme_id=tid)


def colors_for_theme_id(theme_id: str, settings: dict) -> Dict[str, Any]:
    tid = (theme_id or "dark").lower()
    if tid == "user":
        return merge_user_theme_colors(settings.get("user_theme_colors"))
    if tid == "dark":
        return merge_dark_theme_colors(settings.get("dark_theme_colors"))
    if tid == "light":
        return merge_light_theme_colors(settings.get("light_theme_colors"))
    entry = get_custom_theme_entry(settings.get("custom_themes"), tid)
    if entry:
        return deepcopy(entry.get("colors") or {})
    return merge_dark_theme_colors(None)


def _load_custom_themes_for_normalize(config: Any = None) -> Dict[str, Dict[str, Any]]:
    try:
        if config is None:
            from config import get_config

            config = get_config()
        return merge_custom_themes(config.load_settings().get("custom_themes"))
    except Exception:
        return {}


def normalize_theme_id(
    theme_id: str,
    *,
    custom_themes: Optional[dict] = None,
    config: Any = None,
) -> str:
    tid = (theme_id or "dark").lower()
    if tid in THEMES or tid in ("user", "system"):
        return tid
    if custom_themes is None:
        custom_themes = _load_custom_themes_for_normalize(config)
    if tid in custom_themes:
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


def resolve_theme_id_for_apply(
    theme_id: str,
    *,
    custom_themes: Optional[dict] = None,
    config: Any = None,
) -> str:
    """Resolve stored ui_theme (including 'system') for palette application."""
    tid = normalize_theme_id(theme_id, custom_themes=custom_themes, config=config)
    if tid == "system":
        return system_appearance_theme_id()
    return tid


def resolved_ui_theme_from_settings(settings: dict) -> str:
    """Browse transparency and other per-theme settings use this (system -> dark/light)."""
    ui = (settings.get("ui_theme") or "dark").lower()
    custom_themes = merge_custom_themes(settings.get("custom_themes"))
    if ui == "system":
        return system_appearance_theme_id()
    return normalize_theme_id(ui, custom_themes=custom_themes)


def set_theme_main_window(main_window: Any) -> None:
    global _theme_main_window
    _theme_main_window = main_window


def sync_view_theme_menu_actions(main_window: Any, ui_theme_id: str) -> None:
    custom_themes = _load_custom_themes_for_normalize(
        getattr(main_window, "config", None),
    )
    tid = normalize_theme_id(ui_theme_id, custom_themes=custom_themes)
    is_custom = is_custom_theme_id(tid, custom_themes)
    if getattr(main_window, "theme_system_action", None) is not None:
        main_window.theme_system_action.setChecked(tid == "system")
    if getattr(main_window, "theme_dark_action", None) is not None:
        main_window.theme_dark_action.setChecked(tid == "dark" and not is_custom)
        main_window.theme_light_action.setChecked(tid == "light" and not is_custom)
    if getattr(main_window, "theme_user_action", None) is not None:
        main_window.theme_user_action.setChecked(tid == "user" and not is_custom)
    for slug, action in (getattr(main_window, "theme_custom_actions", None) or {}).items():
        action.setChecked(tid == slug)


def rebuild_view_custom_theme_menu(
    main_window: Any,
    config: Any,
    *,
    custom_themes: Optional[dict] = None,
) -> None:
    """Rebuild dynamic View > Theme entries for user-defined themes."""
    from PySide6.QtGui import QAction

    theme_menu = getattr(main_window, "theme_menu", None)
    if theme_menu is None:
        return

    old_actions = getattr(main_window, "theme_custom_actions", None) or {}
    theme_group = getattr(main_window, "theme_action_group", None)
    for action in old_actions.values():
        theme_menu.removeAction(action)
        if theme_group is not None:
            theme_group.removeAction(action)

    if custom_themes is None:
        try:
            custom_themes = merge_custom_themes(config.load_settings().get("custom_themes"))
        except Exception:
            custom_themes = {}
    else:
        custom_themes = merge_custom_themes(custom_themes)

    main_window.theme_custom_actions = {}
    system_action = getattr(main_window, "theme_system_action", None)
    menu_separator = getattr(main_window, "theme_menu_separator", None)
    insert_before = menu_separator or system_action
    if menu_separator is not None:
        menu_separator.setVisible(bool(custom_themes))

    def _apply_ui_theme(theme_id: str) -> None:
        apply_theme(
            theme_id,
            app=QApplication.instance(),
            main_window=main_window,
            persist=True,
            config=config,
        )
        sync_view_theme_menu_actions(main_window, theme_id)

    sorted_items = sorted(
        custom_themes.items(),
        key=lambda kv: (str(kv[1].get("display_name") or kv[0]).lower(), kv[0]),
    )
    for slug, entry in sorted_items:
        label = str(entry.get("display_name") or slug)
        action = QAction(label, main_window)
        action.setCheckable(True)
        if theme_group is not None:
            theme_group.addAction(action)
        if insert_before is not None:
            theme_menu.insertAction(insert_before, action)
        else:
            theme_menu.addAction(action)
        action.triggered.connect(lambda _checked=False, tid=slug: _apply_ui_theme(tid))
        main_window.theme_custom_actions[slug] = action

    sync_view_theme_menu_actions(
        main_window,
        (config.load_settings() or {}).get("ui_theme", "dark"),
    )


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
        if normalize_theme_id(
            cfg.load_settings().get("ui_theme", "dark"),
            config=cfg,
        ) != "system":
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
    """Fill default/current/multiselect border width indices."""
    def pick(key: str, fallback: int) -> int:
        if stored and key in stored:
            return _coerce_image_border_width(stored.get(key), fallback)
        return fallback

    out["default_image_border_width_index"] = pick(
        "default_image_border_width_index", int(out["default_image_border_width_index"])
    )
    out["current_image_border_width_index"] = pick(
        "current_image_border_width_index", int(out["current_image_border_width_index"])
    )
    out["multiselect_border_width_index"] = pick(
        "multiselect_border_width_index", int(out["multiselect_border_width_index"])
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
    """
    c = merge_user_theme_colors(colors)
    text = c["text_color_hex"]
    border = c["default_border_color_hex"]
    bg = c["default_background_color_hex"]
    dialog_bg = c["dialog_background_hex"]
    dialog_text = c["dialog_text_color_hex"]
    dialog_input_bg = c["dialog_input_background_hex"]
    thumb_grid_bg = c["thumbnail_grid_background_color_hex"]
    thumb_text = c["thumbnail_text_color_hex"]
    sidebar_bg = c["sidebar_background_color_hex"]
    sidebar_text = c["sidebar_text_color_hex"]
    status_bg = c["status_bar_background_color_hex"]
    status_text = c["status_bar_text_color_hex"]
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
        thumbnail_grid_background_color_hex=thumb_grid_bg,
        thumbnail_text_color_hex=thumb_text,
        text_color_hex=text,
        dialog_background_hex=dialog_bg,
        dialog_text_color_hex=dialog_text,
        dialog_input_background_hex=dialog_input_bg,
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
        sidebar_background_color_hex=sidebar_bg,
        sidebar_text_color_hex=sidebar_text,
        # Thumbnail cell border only — not Qt control borders (those keep t0.border_default_hex / border_hover_hex)
        default_border_color_hex=border,
        # Splitters, status bar top, section header frames (see chrome_border_hex in theme.py)
        chrome_border_hex=border,
        splitter_handle_hex=border,
        splitter_handle_hover_hex=sh,
        splitter_handle_pressed_hex=sp,
        sidebar_splitter_handle_hex=border,
        sidebar_header_border_hex=border,
        main_status_bar_bg_hex=status_bg,
        status_bar_label_text_hex=status_text,
        tree_view_text_hex=sidebar_text,
        browse_view_fg_hex=text,
        thumbnail_status_label_text_hex=status_text,
        shortcuts_sidebar_primary_text_hex=sidebar_text,
        sidebar_header_text_hex=sidebar_text,
        file_tree_nav_button_text_hex=sidebar_text,
        information_link_tooltip_fg_hex=sidebar_text,
        # Information pane and right sidebar shell use customizable sidebar background
        right_sidebar_combined_bg_hex=sidebar_bg,
        information_panel_bg_hex=sidebar_bg,
        information_textbrowser_bg_hex=sidebar_bg,
        information_link_tooltip_bg_hex=sidebar_bg,
        **_shortcuts_sidebar_chrome_from_theme(sidebar_bg, border, sh),
        button_bg_default_hex=c["button_bg_default_hex"],
        button_border_default_hex=c["button_border_default_hex"],
        button_bg_hover_hex=c["button_bg_hover_hex"],
        button_border_hover_hex=c["button_border_hover_hex"],
        button_text_default_hex=c["button_text_default_hex"],
        button_text_hover_hex=c["button_text_hover_hex"],
    )


def build_dark_theme_from_colors(colors: Dict[str, str]) -> DarkTheme:
    """Build dark preset from customizable colors (same propagation as user theme)."""
    c = merge_dark_theme_colors(colors)
    text = c["text_color_hex"]
    border = c["default_border_color_hex"]
    bg = c["default_background_color_hex"]
    dialog_bg = c["dialog_background_hex"]
    dialog_text = c["dialog_text_color_hex"]
    dialog_input_bg = c["dialog_input_background_hex"]
    thumb_grid_bg = c["thumbnail_grid_background_color_hex"]
    thumb_text = c["thumbnail_text_color_hex"]
    sidebar_bg = c["sidebar_background_color_hex"]
    sidebar_text = c["sidebar_text_color_hex"]
    status_bg = c["status_bar_background_color_hex"]
    status_text = c["status_bar_text_color_hex"]
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
        thumbnail_grid_background_color_hex=thumb_grid_bg,
        thumbnail_text_color_hex=thumb_text,
        text_color_hex=text,
        dialog_background_hex=dialog_bg,
        dialog_text_color_hex=dialog_text,
        dialog_input_background_hex=dialog_input_bg,
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
        sidebar_background_color_hex=sidebar_bg,
        sidebar_text_color_hex=sidebar_text,
        default_border_color_hex=border,
        chrome_border_hex=border,
        splitter_handle_hex=border,
        splitter_handle_hover_hex=sh,
        splitter_handle_pressed_hex=sp,
        sidebar_splitter_handle_hex=border,
        sidebar_header_border_hex=border,
        main_status_bar_bg_hex=status_bg,
        status_bar_label_text_hex=status_text,
        tree_view_text_hex=sidebar_text,
        browse_view_fg_hex=text,
        thumbnail_status_label_text_hex=status_text,
        shortcuts_sidebar_primary_text_hex=sidebar_text,
        sidebar_header_text_hex=sidebar_text,
        file_tree_nav_button_text_hex=sidebar_text,
        information_link_tooltip_fg_hex=sidebar_text,
        right_sidebar_combined_bg_hex=sidebar_bg,
        information_panel_bg_hex=sidebar_bg,
        information_textbrowser_bg_hex=sidebar_bg,
        information_link_tooltip_bg_hex=sidebar_bg,
        **_shortcuts_sidebar_chrome_from_theme(sidebar_bg, border, sh),
        button_bg_default_hex=c["button_bg_default_hex"],
        button_border_default_hex=c["button_border_default_hex"],
        button_bg_hover_hex=c["button_bg_hover_hex"],
        button_border_hover_hex=c["button_border_hover_hex"],
        button_text_default_hex=c["button_text_default_hex"],
        button_text_hover_hex=c["button_text_hover_hex"],
    )


def build_light_theme_from_colors(colors: Dict[str, str]) -> LightTheme:
    """Build light preset from customizable colors (mirrors user-theme propagation)."""
    c = merge_light_theme_colors(colors)
    text = c["text_color_hex"]
    border = c["default_border_color_hex"]
    bg = c["default_background_color_hex"]
    dialog_bg = c["dialog_background_hex"]
    dialog_text = c["dialog_text_color_hex"]
    dialog_input_bg = c["dialog_input_background_hex"]
    thumb_grid_bg = c["thumbnail_grid_background_color_hex"]
    thumb_text = c["thumbnail_text_color_hex"]
    sidebar_bg = c["sidebar_background_color_hex"]
    sidebar_text = c["sidebar_text_color_hex"]
    status_bg = c["status_bar_background_color_hex"]
    status_text = c["status_bar_text_color_hex"]
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
        thumbnail_grid_background_color_hex=thumb_grid_bg,
        thumbnail_text_color_hex=thumb_text,
        text_color_hex=text,
        dialog_background_hex=dialog_bg,
        dialog_text_color_hex=dialog_text,
        dialog_input_background_hex=dialog_input_bg,
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
        sidebar_background_color_hex=sidebar_bg,
        sidebar_text_color_hex=sidebar_text,
        default_border_color_hex=border,
        chrome_border_hex=border,
        splitter_handle_hex=border,
        splitter_handle_hover_hex=sh,
        splitter_handle_pressed_hex=sp,
        sidebar_splitter_handle_hex=border,
        sidebar_header_border_hex=border,
        main_status_bar_bg_hex=status_bg,
        status_bar_label_text_hex=status_text,
        tree_view_text_hex=sidebar_text,
        browse_view_fg_hex=text,
        thumbnail_status_label_text_hex=status_text,
        shortcuts_sidebar_primary_text_hex=sidebar_text,
        sidebar_header_text_hex=sidebar_text,
        file_tree_nav_button_text_hex=sidebar_text,
        information_link_tooltip_fg_hex=sidebar_text,
        right_sidebar_combined_bg_hex=sidebar_bg,
        information_panel_bg_hex=sidebar_bg,
        information_textbrowser_bg_hex=sidebar_bg,
        information_link_tooltip_bg_hex=sidebar_bg,
        **_shortcuts_sidebar_chrome_from_theme(sidebar_bg, border, sh),
        button_bg_default_hex=c["button_bg_default_hex"],
        button_border_default_hex=c["button_border_default_hex"],
        button_bg_hover_hex=c["button_bg_hover_hex"],
        button_border_hover_hex=c["button_border_hover_hex"],
        button_text_default_hex=c["button_text_default_hex"],
        button_text_hover_hex=c["button_text_hover_hex"],
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
    import thumbnails.thumbnail_constants as tc

    t = theme
    tc.CURRENT_IMAGE_BACKGROUND_COLOR_HEX = t.current_image_background_color_hex
    tc.CURRENT_IMAGE_BACKGROUND_COLOR = QColor(t.current_image_background_color_hex)
    tc.CURRENT_IMAGE_BORDER_COLOR_HEX = t.current_image_border_color_hex
    tc.CURRENT_IMAGE_BORDER_COLOR = QColor(t.current_image_border_color_hex)
    _mw = int(getattr(tc, "MAX_THEME_BORDER_WIDTH_PX", 10))
    tc.DEFAULT_IMAGE_BORDER_WIDTH_PX = max(0, min(_mw, int(getattr(t, "default_image_border_width_index", 1))))
    tc.CURRENT_IMAGE_BORDER_WIDTH_PX = max(0, min(_mw, int(getattr(t, "current_image_border_width_index", 2))))
    tc.MULTISELECT_BORDER_WIDTH_PX = max(0, min(_mw, int(getattr(t, "multiselect_border_width_index", 2))))

    tc.MULTISELECT_BACKGROUND_COLOR_HEX = t.multiselect_background_color_hex
    _ms = QColor(t.multiselect_background_color_hex)
    if _ms.isValid():
        _ms.setAlpha(130)
    tc.MULTISELECT_BACKGROUND_COLOR = _ms
    tc.MULTISELECT_BORDER_COLOR_HEX = t.multiselect_border_color_hex
    tc.MULTISELECT_BORDER_COLOR = QColor(t.multiselect_border_color_hex)

    tc.DEFAULT_BACKGROUND_COLOR_HEX = t.default_background_color_hex
    tc.DEFAULT_BACKGROUND_COLOR = QColor(t.default_background_color_hex)
    tc.THUMBNAIL_GRID_BACKGROUND_COLOR_HEX = t.thumbnail_grid_background_color_hex
    tc.THUMBNAIL_GRID_BACKGROUND_COLOR = QColor(t.thumbnail_grid_background_color_hex)
    tc.DEFAULT_BORDER_COLOR_HEX = t.default_border_color_hex
    tc.DEFAULT_BORDER_COLOR = QColor(t.default_border_color_hex)
    tc.DEFAULT_IMAGE_BACKGROUND_COLOR_HEX = t.default_image_background_color_hex
    tc.DEFAULT_IMAGE_BACKGROUND_COLOR = QColor(t.default_image_background_color_hex)
    tc.DEFAULT_IMAGE_COLOR_HEX = t.default_image_color_hex
    tc.DEFAULT_IMAGE_COLOR = QColor(t.default_image_color_hex)

    tc.TEXT_COLOR_HEX = t.text_color_hex
    tc.TEXT_COLOR = QColor(t.text_color_hex)
    tc.THUMBNAIL_TEXT_COLOR_HEX = t.thumbnail_text_color_hex
    tc.THUMBNAIL_TEXT_COLOR = QColor(t.thumbnail_text_color_hex)
    tc.QMENU_DEFAULT_STYLE_SHEET = t.qmenu_stylesheet()

    tc.TAB_BUTTON_FOCUS_BACKGROUND_COLOR_HEX = t.tab_button_focus_background_color_hex
    tc.TAB_BUTTON_FOCUS_BORDER_COLOR_HEX = t.tab_button_focus_border_color_hex

    tc.HEADING_COLOR = QColor(t.heading_color_hex())
    tc.HEADING_COLOR_HEX = t.heading_color_hex()

    tc.DIALOG_TEXT_COLOR = QColor(t.dialog_text_color_hex)
    tc.DIALOG_TEXT_COLOR_HEX = t.dialog_text_color_hex

    tc.DIALOG_BACKGROUND_HEX = t.dialog_background_hex
    tc.DIALOG_INPUT_BACKGROUND_HEX = t.dialog_input_background_hex
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
    tc.TREE_HEADER_FOCUS_BG_HEX = sidebar_header_focus_bg_hex(
        t.sidebar_header_bg_hex, theme_id=t.theme_id
    )

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
    custom_themes: Optional[Dict[str, Any]] = None,
    custom_theme_colors: Optional[Dict[str, Any]] = None,
    apply_scope: str = "full",
) -> str:
    """
    Activate a theme by id, sync legacy constants, optionally set QApplication stylesheet,
    persist to settings, and refresh main window chrome.

    For theme_id \"user\", pass user_theme_colors to apply a specific palette without reading
    config, or None to load user_theme_colors from config.

    For \"dark\" / \"light\", pass dark_theme_colors / light_theme_colors to preview overrides,
    or None to load persisted preset colors from config.

    For custom theme slugs, pass custom_themes and/or custom_theme_colors for live preview.

    apply_scope controls how much UI is restyled after syncing constants:
      - \"full\": global QApplication stylesheet + refresh_theme_styles (default)
      - \"chrome\": refresh_theme_styles only (splitters, sidebars, per-widget chrome)
      - \"thumbnail\": thumbnail canvas repaint only

    Returns the stored/normalized theme id (e.g. 'system', 'dark', 'light', 'user', or custom slug).
    """
    if apply_scope not in ("full", "chrome", "thumbnail"):
        apply_scope = "full"
    global _active_theme
    if config is None:
        try:
            from config import get_config

            config = get_config()
        except Exception:
            config = None
    if custom_themes is None and config is not None:
        try:
            custom_themes = merge_custom_themes(config.load_settings().get("custom_themes"))
        except Exception:
            custom_themes = {}
    if custom_themes is None:
        custom_themes = {}

    stored_tid = normalize_theme_id(theme_id, custom_themes=custom_themes, config=config)
    apply_tid = resolve_theme_id_for_apply(
        stored_tid,
        custom_themes=custom_themes,
        config=config,
    )
    if is_custom_theme_id(apply_tid, custom_themes):
        entry = deepcopy(custom_themes.get(apply_tid) or {})
        base = str(entry.get("base") or "dark").lower()
        if custom_theme_colors is not None:
            merged = merge_custom_theme_colors(custom_theme_colors, base)
        else:
            merged = merge_custom_theme_colors(entry.get("colors"), base)
        entry["colors"] = merged
        _active_theme = build_theme_from_custom_entry(apply_tid, entry)
        if persist:
            try:
                if config is None:
                    from config import get_config

                    config = get_config()
                settings = config.load_settings()
                stored_custom = merge_custom_themes(settings.get("custom_themes"))
                stored_entry = stored_custom.get(apply_tid, entry)
                stored_entry["colors"] = deepcopy(merged)
                stored_custom[apply_tid] = stored_entry
                settings["custom_themes"] = stored_custom
                settings["ui_theme"] = apply_tid
                config.save_settings(settings)
            except Exception:
                pass
    elif apply_tid == "user":
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

    if persist and stored_tid not in ("user",) and not is_custom_theme_id(stored_tid, custom_themes):
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
