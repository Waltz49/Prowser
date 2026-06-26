#!/usr/bin/env python3
"""Dark theme palette values; stylesheets live in theme.ThemeStylesMixin."""

from __future__ import annotations

from dataclasses import dataclass

from theme.theme import ThemeStylesMixin


@dataclass(frozen=True)
class DarkTheme(ThemeStylesMixin):
    theme_id: str = "dark"
    general_text_color_hex: str = "#b6b6b6"
    general_bg_color_hex: str = "#000000"

    # Thumbnail / selection
    current_image_background_color_hex: str = "#0080b2"
    current_image_border_color_hex: str = "#87ceeb"
    multiselect_background_color_hex: str = "#ffd700"
    multiselect_border_color_hex: str = "#705d1f"
    # Thumbnail frame widths (0–10 px); separate per border type
    default_image_border_width_index: int = 1
    current_image_border_width_index: int = 2
    multiselect_border_width_index: int = 2
    # Splitter handles (main / sidebars) and QStatusBar top border (px)
    view_border_width_px: int = 2

    default_background_color_hex: str = general_bg_color_hex
    thumbnail_grid_background_color_hex: str = general_bg_color_hex
    default_border_color_hex: str = "#606060"
    # Non-current thumbnail cell colors (preserve current dark behavior)
    default_image_background_color_hex: str = "#000000"
    default_image_color_hex: str = "#606060"
    thumbnail_text_color_hex: str = general_text_color_hex
    text_color_hex: str = general_text_color_hex

    dialog_background_hex: str = "#2a2a2a"
    widget_bg_hover_hex: str = "#4a4a4a"
    widget_bg_pressed_hex: str = "#5a5a5a"
    widget_bg_disabled_hex: str = "#323232"
    text_disabled_hex: str = "#777777"
    border_default_hex: str = "#4a4a4a"
    border_hover_hex: str = "#5a5a5a"
    # Splitters, status bar top edge, section header frames (not buttons / inputs)
    chrome_border_hex: str = "#444444"

    tab_button_focus_background_color_hex: str = "#223344"
    tab_button_focus_border_color_hex: str = "#5ba0f2"
    tab_button_hover_bg_hex: str = "#3a3a3a"

    dialog_text_color_hex: str = "#b6b6b6"

    button_bg_default_hex: str = "#16181c"
    button_text_default_hex: str = "#b0bfd6"
    button_border_default_hex: str = "#38506b"
    button_bg_hover_hex: str = "#263447"
    button_text_hover_hex: str = "#bbecff"
    button_border_hover_hex: str = "#41a6c6"
    button_bg_pressed_hex: str = "#14202a"
    button_focus_text_hex: str = "#ffffff"
    button_default_bg_hex: str = "#49678b"
    button_default_border_hex: str = "#7f9cb9"

    sidebar_header_bg_hex: str = "#2b2b2b"
    sidebar_background_color_hex: str = general_bg_color_hex
    sidebar_text_color_hex: str = general_text_color_hex
    sidebar_header_border_hex: str = "#404040"
    sidebar_header_text_hex: str = "#b6b6b6"  # same as dialog_text_color_hex (previous header label color)
    sidebar_splitter_handle_hex: str = "#444444"
    tree_header_focus_bg_hex: str = "#0047a5"

    error_color_hex: str = "#ff6666"
    validation_success_color_hex: str = "#66cc66"
    accent_color_hex: str = "#4a90e2"

    locked_file_background_hex: str = "#301020"
    tree_folder_with_images_hex: str = "#ecd660"

    # Global stylesheet extras (tree, tooltip, spinbox disabled, etc.)
    tree_view_text_hex: str = "#deeefa"
    tree_view_border_hex: str = "#333333"
    tree_view_selection_bg_hex: str = "#333333"
    tree_view_item_hover_hex: str = "#1a1a1a"
    tree_header_section_bg_hex: str = "#1a1a1a"
    groupbox_border_hex: str = "#5a5a5a"
    qslider_handle_hover_border_hex: str = "#6bb0ff"
    qslider_handle_focus_border_hex: str = "#6a6a6a"
    qtooltip_bg_hex: str = "#000000"
    qtooltip_fg_hex: str = "#ddeeff"
    qtooltip_border_hex: str = "#b2b2b8"
    spinbox_disabled_text_hex: str = "#666666"
    spinbox_disabled_border_hex: str = "#333333"
    checkbox_indicator_border_hex: str = "#a0a0a0"
    checkbox_indicator_hover_border_hex: str = "#888888"
    checkbox_indicator_focus_border_hex: str = "#aaaaaa"
    radiobutton_indicator_border_hex: str = "#A0A090"
    radiobutton_indicator_disabled_hex: str = "#444444"
    qmenu_item_disabled_hex: str = "#aaaaaa"

    # Main window chrome (splitter / status strip)
    splitter_handle_hex: str = "#444444"
    splitter_handle_hover_hex: str = "#999999"
    splitter_handle_pressed_hex: str = "#cccccc"
    main_status_bar_bg_hex: str = general_bg_color_hex
    status_bar_label_text_hex: str = general_text_color_hex
    status_bar_label_disabled_hex: str = "#888888"

    progress_bar_border_hex: str = "#808080"
    progress_bar_bg_hex: str = "#2a2a2a"
    progress_bar_text_hex: str = "#ffffff"
    progress_chunk_gradient_start: str = "#4A90E2"
    progress_chunk_gradient_mid: str = "#2E5BBA"
    progress_chunk_gradient_end: str = "#1E3A8A"

    thumbnail_status_label_text_hex: str = "#ffffff"

    # Thumbnail grid: filename overlay pill + empty-state “suggested filter” buttons (painted in thumbnail_canvas)
    thumbnail_filename_overlay_rgba: str = "0, 0, 0, 240"
    thumbnail_empty_filter_btn_bg_hex: str = "#161618"
    thumbnail_empty_filter_btn_bg_hover_hex: str = "#263447"
    thumbnail_empty_filter_btn_border_hex: str = "#38506b"
    thumbnail_empty_filter_btn_border_hover_hex: str = "#41a6c6"
    thumbnail_empty_filter_btn_text_hover_hex: str = "#bbecff"

    # Right sidebar shell (Organize + Information splitter)
    right_sidebar_combined_bg_hex: str = "#2a2a2a"

    # Browse view
    browse_view_bg_rgb: str = "0, 0, 0"
    browse_view_fg_hex: str = "#ffffff"
    browse_filename_bg_rgba: str = "0, 0, 0, 220"
    browse_filename_border_hex: str = "#FFD700"
    browse_filename_text_hex: str = "#FFFFFF"
    browse_filename_doc_color_hex: str = "#eeeeee"

    # Status bar context menus (#2a2a2a matches dialog_background_hex)
    status_menu_border_hex: str = "#555555"
    status_menu_selected_hex: str = "#444444"
    status_menu_grayed_hex: str = "#888888"

    # Left file tree panel (overrides global QTreeView for embedded tree)
    file_tree_item_highlighted_bg_hex: str = "#444444"
    file_tree_item_highlighted_selected_bg_hex: str = "#555555"
    file_tree_delegate_drag_bg_hex: str = "#444444"
    file_tree_delegate_drag_text_hex: str = "#FFFFFF"
    file_tree_nav_container_bg_hex: str = "#111111"
    file_tree_nav_button_bg_hex: str = "#1a1a1a"
    file_tree_nav_button_border_hex: str = "#333333"
    file_tree_nav_button_hover_hex: str = "#333333"
    file_tree_nav_button_pressed_hex: str = "#444444"
    file_tree_nav_button_text_dim_hex: str = "#808080"
    file_tree_nav_button_text_hex: str = "#ffffff"
    file_tree_dir_label_bg_hex: str = "#333333"
    file_tree_dir_label_border_hex: str = "#6a6a6a"
    file_tree_filter_btn_bg_hex: str = "#000000"
    file_tree_filter_btn_border_hex: str = "#808080"
    file_tree_filter_btn_hover_hex: str = "#1a1a1a"
    file_tree_filter_sep_hex: str = "#808080"
    file_tree_filter_icon_selected_hex: str = "#eeeeee"
    file_tree_filter_icon_unselected_hex: str = "#808080"

    # Shortcuts / Organize (right sidebar)
    shortcuts_panel_bg_hex: str = "#000000"
    shortcuts_scroll_bg_hex: str = "#000000"
    shortcuts_combo_bg_hex: str = "#2a2a2a"
    shortcuts_combo_border_hex: str = "#4a4a4a"
    shortcuts_combo_hover_border_hex: str = "#6a6a6a"
    shortcuts_note_muted_hex: str = "#888888"
    shortcuts_hr_hex: str = "#6b6b6b"
    shortcuts_gear_border_hex: str = "#4a4a4a"
    shortcuts_gear_border_hover_hex: str = "#6a6a6a"
    shortcuts_gear_bg_hex: str = "#1a1a1a"
    shortcuts_gear_bg_hover_hex: str = "#333333"
    shortcuts_sidebar_primary_text_hex: str = dialog_text_color_hex
    shortcuts_sidebar_heading_text_hex: str = dialog_text_color_hex
    sidebar_favorite_link_hover_hex: str = "#2dc4ff"

    # Information sidebar
    information_panel_bg_hex: str = "#2a2a2a"
    information_textbrowser_bg_hex: str = "#000000"
    information_link_tooltip_bg_hex: str = "#2a2a2a"
    information_link_tooltip_fg_hex: str = "#ddeeff"
    information_link_tooltip_border_hex: str = "#b2b2b8"
    information_table_border_hex: str = "#444444"
    information_action_chip_bg_hex: str = "#23272d"
    information_action_icon_muted_hex: str = "#808890"
    information_icon_cell_border_muted_hex: str = "#555555"


DEFAULT_DARK_THEME = DarkTheme()
