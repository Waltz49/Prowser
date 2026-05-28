#!/usr/bin/env python3
"""Light theme palette values; stylesheets live in theme.ThemeStylesMixin."""

from __future__ import annotations

from dataclasses import dataclass

from theme import ThemeStylesMixin


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
    default_border_color_hex: str = "#cfd8dc"
    # Non-current thumbnail cell colors (grid/list thumbnail surfaces)
    default_image_background_color_hex: str = general_bg_color_hex
    default_image_color_hex: str = "#222222"
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

    dialog_text_color_hex: str = "#1a1a1a"
    dialog_text_color_hex: str = general_text_color_hex

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
    # Section headers (File Tree / Preview / Organize / File Information) + hide-button chrome
    sidebar_header_border_hex: str = "#424242"
    sidebar_header_text_hex: str = "white"
    # Inner splitter in left sidebar (tree vs preview)
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

    # Main splitter (left | canvas | right) and right sidebar inner splitter (Organize | Information)
    splitter_handle_hex: str = "#282c39"
    splitter_handle_hover_hex: str = "#b71c1c"
    splitter_handle_pressed_hex: str = "#8e0000"
    main_status_bar_bg_hex: str = "#ececec"
    status_bar_label_text_hex: str = "black"
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

    # Right sidebar shell (Organize + Information splitter)
    right_sidebar_combined_bg_hex: str = "#fafafa"
    # QMenu surfaces (menu bar dropdowns, global QMenu rules, status bar menus)
    context_menu_bg_hex: str = dialog_background_hex

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
    # Organize sidebar (Favorites + Move lists): body and heading text on light panels
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
