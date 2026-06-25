#!/usr/bin/env python3
"""
Shortcuts Sidebar Widget - Displays Favorites and Move list keyboard shortcuts
"""

import os
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from thumbnails.thumbnail_constants import (
    CMD_SYMBOL,
    OPTION_SYMBOL,
    asset_file_url,
)
from theme.theme_service import get_active_theme
from tooltip_popup_utils import ensure_tooltip_label, position_tooltip_near_cursor


def _shortcuts_primary_text_hex():
    th = get_active_theme()
    return getattr(th, "shortcuts_sidebar_primary_text_hex", None) or th.sidebar_text_color_hex


def _shortcuts_heading_text_hex():
    return get_active_theme().sidebar_heading_color_hex()


class _NoContextMenuLabel(QLabel):
    """QLabel that suppresses the default 'Copy Link Location' context menu on links."""

    def contextMenuEvent(self, event: QContextMenuEvent):
        event.accept()


def _full_path_for_tooltip(path):
    """Absolute, expanded path string for tooltips (Organize sidebar)."""
    if not path or not str(path).strip():
        return ""
    try:
        return os.path.realpath(os.path.expanduser(path.strip()))
    except OSError:
        return os.path.abspath(os.path.expanduser(path.strip()))


class ShortcutsSidebar(QWidget):
    """Widget for displaying Favorites and Move list shortcuts in the right_sidebar.
    Header is provided by RightSidebarCombinedWidget."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setup_ui()
        # Subscribe to SETTINGS_CHANGED so favorites and move destinations update immediately
        if hasattr(main_window, 'event_bus') and main_window.event_bus:
            from event_bus import SETTINGS_CHANGED
            main_window.event_bus.subscribe(SETTINGS_CHANGED, self._on_settings_changed)

    def setup_ui(self):
        """Setup the Shortcuts sidebar UI"""
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumWidth(200)
        _th = get_active_theme()
        self.setStyleSheet(_th.shortcuts_sidebar_widget_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Content area with scroll
        self.scroll_area = QScrollArea()
        scroll_area = self.scroll_area
        scroll_area.setFocusPolicy(Qt.NoFocus)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setStyleSheet(_th.shortcuts_sidebar_scroll_stylesheet())

        self.content_widget = QWidget()
        self.content_widget.setFocusPolicy(Qt.NoFocus)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(8)
        self.content_layout.setAlignment(Qt.AlignTop)

        scroll_area.setWidget(self.content_widget)
        if scroll_area.viewport():
            scroll_area.viewport().setFocusPolicy(Qt.NoFocus)
        layout.addWidget(scroll_area)

        self._shortcuts_label = None
        self._favorites_label = None
        self._move_heading_label = None
        self._move_destinations_label = None
        self._move_mode_combo = None
        self._move_mode_row = None
        self._setup_move_mode_combo()
        self.refresh_shortcuts()

    def _setup_move_mode_combo(self):
        """Create the move keys mode combo box with a 'Click Mode' label on the same line."""
        settings = self.main_window.config.load_settings()
        mode = settings.get('move_keys_mode', 'not_links')

        # Create the label for "Click Mode"
        self._move_mode_label = QLabel("Click Mode")
        self._move_mode_label.setStyleSheet(f"""
            QLabel {{
                color: {_shortcuts_primary_text_hex()};
                font-size: 12pt;
                font-weight: bold;
            }}
        """)
        self._move_mode_label.setFocusPolicy(Qt.NoFocus)

        # Create the combo box for move mode
        self._move_mode_combo = QComboBox()
        self._move_mode_combo.setFocusPolicy(Qt.NoFocus)
        self._move_mode_combo.addItems(["No Action", "Move", "Copy"])
        idx = {"not_links": 0, "move": 1, "copy": 2}.get(mode, 0)
        self._move_mode_combo.setCurrentIndex(idx)
        self._move_mode_combo.currentIndexChanged.connect(self._on_move_mode_changed)
        self._move_mode_combo.setStyleSheet(get_active_theme().shortcuts_sidebar_combo_stylesheet())

        # Put label and combo on the same line
        self._move_mode_row = QWidget()
        self._move_mode_row.setFocusPolicy(Qt.NoFocus)
        row_layout = QHBoxLayout(self._move_mode_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(self._move_mode_label)
        row_layout.addWidget(self._move_mode_combo)
        row_layout.addStretch()

        self._move_mode_note_label = QLabel("This does not affect keyboard shortcuts.")
        self._move_mode_note_label.setStyleSheet(get_active_theme().shortcuts_sidebar_note_muted_stylesheet())
        self._move_mode_note_label.setFocusPolicy(Qt.NoFocus)

        if hasattr(self, 'content_layout') and self.content_layout is not None:
            self.content_layout.addWidget(self._move_mode_row)
            self.content_layout.addWidget(self._move_mode_note_label)

    def _on_move_mode_changed(self, index):
        """Persist move keys mode when combo selection changes."""
        mode = ["not_links", "move", "copy"][index]
        self.main_window.config.update_setting('move_keys_mode', mode)
        self.refresh_shortcuts()

    def _on_settings_changed(self, new_settings: dict):
        """Handle SETTINGS_CHANGED - refresh when favorites or move destinations change."""
        if not new_settings:
            return
        relevant_keys = ('favorite_directories', 'move_destinations', 'move_keys_mode', 'destination_menu_action')
        if any(k in new_settings for k in relevant_keys):
            self.refresh_shortcuts()

    def _tooltip_for_organize_url(self, url: str) -> str:
        """Full path for QLabel tooltips when hovering Organize path links."""
        if not url:
            return ""
        if url in ('settings:favorites', 'settings:move'):
            return ""
        settings = self.main_window.config.load_settings()
        favorites = (settings.get('favorite_directories', [None] * 9) + [None] * 9)[:9]
        destinations = (settings.get('move_destinations', [None] * 9) + [None] * 9)[:9]
        last_drop = None
        if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
            ft = getattr(self.main_window.file_tree_handler, 'file_tree', None)
            if ft and hasattr(ft, 'get_last_drop_location'):
                last_drop = ft.get_last_drop_location()
        if url.startswith("favorite:"):
            try:
                idx = int(url.split(":")[1])
                if 0 <= idx < len(favorites) and favorites[idx]:
                    return _full_path_for_tooltip(favorites[idx])
            except (ValueError, IndexError):
                pass
            return ""
        if url == "lastdrop":
            return _full_path_for_tooltip(last_drop) if last_drop else ""
        if url.startswith("move:"):
            try:
                idx = int(url.split(":")[1])
                if idx == 0:
                    return _full_path_for_tooltip(last_drop) if last_drop else ""
                if 1 <= idx <= 9 and destinations[idx - 1]:
                    return _full_path_for_tooltip(destinations[idx - 1])
            except (ValueError, IndexError):
                pass
            return ""
        return ""

    def _organize_path_tooltip_stylesheet(self) -> str:
        t = get_active_theme()
        return (
            f"QLabel {{ background-color: {t.qtooltip_bg_hex}; color: {t.qtooltip_fg_hex}; "
            f"border: 1px solid {t.qtooltip_border_hex}; border-radius: 4px; padding: 4px 8px; font-size: 11pt; }}"
        )

    def _show_organize_path_tooltip(self, anchor_widget, url: str):
        """Show full path near the cursor; avoid QLabel.setToolTip (positions vs whole label on macOS)."""
        if anchor_widget:
            anchor_widget.setToolTip("")
        tip = self._tooltip_for_organize_url(url) if url else ""
        lbl = ensure_tooltip_label(self, "_organize_path_tooltip_label")
        if tip:
            lbl.setStyleSheet(self._organize_path_tooltip_stylesheet())
            lbl.setText(tip)
            lbl.adjustSize()
            position_tooltip_near_cursor(lbl, clamp_widget=self)
            lbl.show()
            lbl.raise_()
        else:
            lbl.hide()

    def refresh_shortcuts(self):
        """Refresh the Favorites and Move shortcuts from config"""
        # Clear existing labels (keep combo) - disconnect only the slots each label actually has
        if self._favorites_label:
            try:
                self._favorites_label.linkActivated.disconnect(self._on_shortcut_link_activated)
                self._favorites_label.linkHovered.disconnect(self._on_link_hovered)
            except Exception:
                pass
            self._favorites_label.deleteLater()
        if self._move_destinations_label:
            try:
                self._move_destinations_label.linkActivated.disconnect(self._on_shortcut_link_activated)
                self._move_destinations_label.linkHovered.disconnect(self._on_move_link_hovered)
            except Exception:
                pass
            self._move_destinations_label.deleteLater()
        if self._shortcuts_label:
            try:
                self._shortcuts_label.linkActivated.disconnect(self._on_shortcut_link_activated)
            except Exception:
                pass
            self._shortcuts_label.deleteLater()
        self._shortcuts_label = None
        self._favorites_label = None
        self._move_destinations_label = None

        # Remove all from layout, we'll re-add in order (keep label+combo row and note)
        keep_widgets = {getattr(self, '_move_mode_row', None), getattr(self, '_move_mode_note_label', None)}
        keep_widgets.discard(None)
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget() and item.widget() not in keep_widgets:
                item.widget().deleteLater()

        settings = self.main_window.config.load_settings()
        favorites = settings.get('favorite_directories', [None] * 9)
        favorites = (favorites + [None] * 9)[:9]
        destinations = settings.get('move_destinations', [None] * 9)
        destinations = (destinations + [None] * 9)[:9]
        move_keys_mode = settings.get('move_keys_mode', 'not_links')
        dest_menu_action = settings.get('destination_menu_action', 'move')
        use_links = move_keys_mode in ('move', 'copy')
        if dest_menu_action == 'copy':
            dest_keys_heading = "Keys for copying files:"
            empty_dest_msg = "No valid copy destinations are defined."
        else:
            dest_keys_heading = "Keys for moving files:"
            empty_dest_msg = "No valid move destinations are defined."

        home_dir = os.path.expanduser("~")

        def path_to_display_segment(path):
            """Return the last directory/file segment of the path, or None if empty/invalid."""
            if not path or not path.strip():
                return None
            p = path.strip()
            if p.startswith(home_dir):
                p = "~" + p[len(home_dir):]
            p = p.rstrip("/")  # Remove any trailing slash for correct basename
            base_segment = os.path.basename(p)
            if base_segment:
                return base_segment
            return p

        def row(html, value_row=False, compress_vertical_padding=False):
            left_pad = "10px" if value_row else "0px"
            vertical_padding = "1px" if compress_vertical_padding else "2px"
            # padding: top right bottom left (left_pad was wrongly in top position)
            return f'<tr><td style="padding: {vertical_padding} 0px {vertical_padding} {left_pad};">{html}</td></tr>'

        _theme = get_active_theme()
        primary = _shortcuts_primary_text_hex()
        heading = _shortcuts_heading_text_hex()
        label_style = f"""
            QLabel {{
                color: {primary};
                font-family: "Helvetica Neue", Helvetica, Arial;
                font-size: 14pt;
                background: transparent;
            }}
        """

        # Gear as inline HTML - button-styled clickable image; hover shows blue gear (matches edit exif dialog)
        gear_img = f'<img src="{asset_file_url("gear.svg")}" width="18" height="18" style="vertical-align: middle;">'
        gear_img_hover = f'<img src="{asset_file_url("gear_hover.svg")}" width="18" height="18" style="vertical-align: middle;">'
        gear_style = _theme.shortcuts_gear_style_normal()
        gear_style_hover = _theme.shortcuts_gear_style_hover()
        fav_gear = f'<a href="settings:favorites" style="{gear_style}">{gear_img}</a>'
        move_gear = f'<a href="settings:move" style="{gear_style}">{gear_img}</a>'
        fav_gear_hover = f'<a href="settings:favorites" style="{gear_style_hover}">{gear_img_hover}</a>'
        move_gear_hover = f'<a href="settings:move" style="{gear_style_hover}">{gear_img_hover}</a>'

        # NOTE: the space with the sizing is necessary to keep the gear aligned regardless of emoji height (heart vs arrow)
        fav_rows = [row(f"<b style=color:{heading}>❤️<span style='font-size:20px;'>&nbsp;</span> Keys for opening Favorites:</b>&nbsp;&nbsp;{fav_gear}")]
        for i, fav in enumerate(favorites):
            display = path_to_display_segment(fav) if fav else None
            if display and os.path.exists(fav):
                link = f'<a href="favorite:{i}" style="color:{primary}; text-decoration:none; cursor:pointer;">{display}</a>'
                fav_rows.append(row(f"^ {i + 1}: &nbsp;&nbsp;{link}", value_row=True))
        _muted = _theme.shortcuts_note_muted_hex
        if not any(fav and os.path.exists(fav) for fav in favorites):
            fav_rows.append(row(f'<span style="color:{_muted};">No valid favorites defined.</span>', value_row=True))
        fav_rows.append(row(""))
        fav_rows.append(row(f"<hr style='border: none; border-top: 1px solid {_theme.shortcuts_hr_hex};'>"))
        fav_rows.append(row(f"<b>↘<span style='font-size:20px;'>&nbsp;</span> <span style=color:{heading}>{dest_keys_heading}</span></b>&nbsp;&nbsp;{move_gear}"))

        self._gear_style = gear_style
        self._gear_style_hover = gear_style_hover
        self._fav_gear = fav_gear
        self._fav_gear_hover = fav_gear_hover
        self._move_gear = move_gear
        self._move_gear_hover = move_gear_hover

        self._favorites_label = _NoContextMenuLabel()
        self._favorites_label.setFocusPolicy(Qt.NoFocus)
        self._favorites_label.setWordWrap(False)
        self._favorites_label.setTextFormat(Qt.TextFormat.RichText)
        self._favorites_label.setOpenExternalLinks(False)
        self._favorites_label.linkActivated.connect(self._on_shortcut_link_activated)
        self._favorites_label.linkHovered.connect(self._on_link_hovered)
        self._favorites_label.setStyleSheet(label_style)
        self._favorites_base_html = f'<table cellpadding="0" cellspacing="0" style="border-collapse: collapse;">{"".join(fav_rows)}</table>'
        self._favorites_label.setText(self._favorites_base_html)
        self.content_layout.addWidget(self._favorites_label)

        # Click Mode label and combo on same line (after destination keys heading)
        self.content_layout.addWidget(self._move_mode_row)
        self.content_layout.addWidget(self._move_mode_note_label)
        # self.content_layout.addSpacing(12)

        # Move destinations section
        dest_rows = []
        for i, dest in enumerate(destinations):
            display = path_to_display_segment(dest) if dest else None
            if display and os.path.exists(dest):
                weight = "500" if use_links else "normal"
                cursor = "pointer" if use_links else "default"
                link = f'<a href="move:{i+1}" style="color:{primary}; text-decoration:none; cursor:{cursor}; font-weight:{weight};">{display}</a>'
                dest_rows.append(row(
                    f"{CMD_SYMBOL} {i + 1} / {OPTION_SYMBOL}{CMD_SYMBOL} {i + 1}: &nbsp;&nbsp;{link}",
                    value_row=True,
                    compress_vertical_padding=True,
                ))
        if not any(dest and os.path.exists(dest) for dest in destinations):
            dest_rows.append(row(f'<span style="color:{_muted};">{empty_dest_msg}</span>', value_row=True, compress_vertical_padding=True))
        last_drop = None
        if hasattr(self.main_window, 'file_tree_handler') and self.main_window.file_tree_handler:
            ft = getattr(self.main_window.file_tree_handler, 'file_tree', None)
            if ft and hasattr(ft, 'get_last_drop_location'):
                last_drop = ft.get_last_drop_location()
        if last_drop and os.path.exists(last_drop):
            display = path_to_display_segment(last_drop)
            if use_links:
                link = f'<a href="move:0" style="color:{primary}; text-decoration:none; cursor:pointer;font-weight:300;">{display}</a>'
                dest_rows.append(row(
                    f"{CMD_SYMBOL} 0 / {OPTION_SYMBOL}{CMD_SYMBOL} 0: &nbsp;&nbsp;{link}",
                    value_row=True,
                    compress_vertical_padding=True,
                ))
            else:
                # Inert link so linkHovered can show full-path tooltip (Qt rich text ignores <a title=...>)
                link = (
                    f'<a href="lastdrop" style="color:{primary}; text-decoration:none; cursor:default; '
                    f'font-weight:300;">{display}</a>'
                )
                dest_rows.append(row(
                    f"{CMD_SYMBOL} 0 / {OPTION_SYMBOL}{CMD_SYMBOL} 0: &nbsp;&nbsp;{link}",
                    value_row=True,
                    compress_vertical_padding=True,
                ))
        else:
            dest_rows.append(row(
                f'{CMD_SYMBOL} 0 / {OPTION_SYMBOL}{CMD_SYMBOL} 0: &nbsp;&nbsp;'
                f'<span style="color:{_muted};">Not yet set</span>',
                value_row=True,
                compress_vertical_padding=True,
            ))

        self._move_destinations_base_html = f'<table cellpadding="0" cellspacing="0" style="border:1px solid transparent; border-collapse: collapse;">{"".join(dest_rows)}</table>'
        self._move_destinations_label = _NoContextMenuLabel()
        self._move_destinations_label.setFocusPolicy(Qt.NoFocus)
        self._move_destinations_label.setWordWrap(False)
        self._move_destinations_label.setTextFormat(Qt.TextFormat.RichText)
        self._move_destinations_label.setOpenExternalLinks(False)
        self._move_destinations_label.linkActivated.connect(self._on_shortcut_link_activated)
        self._move_destinations_label.linkHovered.connect(self._on_move_link_hovered)
        self._move_destinations_label.setStyleSheet(label_style)
        self._move_destinations_label.setText(self._move_destinations_base_html)
        self.content_layout.addWidget(self._move_destinations_label)

        if self.isVisible():
            QTimer.singleShot(10, self._restore_scroll_position)

    def _on_link_hovered(self, url: str):
        """Change link color/underline on hover for favorites; gear button style for settings links."""
        LINK_COLOR = get_active_theme().sidebar_favorite_link_hover_hex
        self._show_organize_path_tooltip(self._favorites_label, url)
        if not hasattr(self, '_favorites_base_html') or not self._favorites_label:
            return
        if url:
            if url in ('settings:favorites', 'settings:move'):
                # Gear button hover: swap to hover style and blue gear SVG
                gear, gear_hover = (self._fav_gear, self._fav_gear_hover) if url == 'settings:favorites' else (self._move_gear, self._move_gear_hover)
                html = self._favorites_base_html.replace(gear, gear_hover)
            else:
                # Favorite link hover: color and underline
                def replace_hover_style(match):
                    tag = match.group(0)
                    tag = re.sub(r'color:#[0-9a-fA-F]+', 'color:' + LINK_COLOR, tag, count=1)
                    tag = re.sub(r'text-decoration:none', 'text-decoration:underline', tag, count=1)
                    return tag
                pattern = r'<a href="' + re.escape(url) + r'"[^>]*>'
                html = re.sub(pattern, replace_hover_style, self._favorites_base_html)
            self._favorites_label.setText(html)
        else:
            self._favorites_label.setText(self._favorites_base_html)

    def _on_move_link_hovered(self, url: str):
        """Full-path tooltip on hover; color/underline when Click Mode is Move or Copy."""
        settings = self.main_window.config.load_settings()
        mode = settings.get('move_keys_mode', 'not_links')
        use_links = mode in ('move', 'copy')
        self._show_organize_path_tooltip(self._move_destinations_label, url)
        LINK_COLOR = "#FF8080" if mode == "move" else "#80FF80"  # maroon for move, thumbnail border blue for copy
        if not hasattr(self, '_move_destinations_base_html') or not self._move_destinations_label:
            return
        if url and use_links:
            def replace_hover_style(match):
                tag = match.group(0)
                tag = re.sub(r'color:#[0-9a-fA-F]+', 'color:' + LINK_COLOR, tag, count=1)
                tag = re.sub(r'text-decoration:none', 'text-decoration:underline', tag, count=1)
                return tag
            pattern = r'<a href="' + re.escape(url) + r'"[^>]*>'
            html = re.sub(pattern, replace_hover_style, self._move_destinations_base_html)
            self._move_destinations_label.setText(html)
        else:
            self._move_destinations_label.setText(self._move_destinations_base_html)

    def _on_shortcut_link_activated(self, url: str):
        """Handle click on favorite, move, or settings link."""
        if url == "settings:favorites":
            if hasattr(self.main_window, 'show_settings'):
                self.main_window.show_settings(tab_index=1)
            return
        if url == "settings:move":
            if hasattr(self.main_window, 'show_settings'):
                self.main_window.show_settings(tab_index=4)
            return
        if url == "lastdrop":
            return
        if url.startswith("favorite:"):
            try:
                idx = int(url.split(":")[1])
                if hasattr(self.main_window, 'open_favorite'):
                    self.main_window.open_favorite(idx)
            except (ValueError, IndexError):
                pass
        elif url.startswith("move:"):
            settings = self.main_window.config.load_settings()
            mode = settings.get("move_keys_mode", "not_links")
            if mode == "not_links":
                return
            copy_only = mode == "copy"
            try:
                idx = int(url.split(":")[1])
                if idx == 0:
                    if hasattr(self.main_window, 'move_to_last_drop_location'):
                        self.main_window.move_to_last_drop_location(copy_only=copy_only)
                else:
                    if hasattr(self.main_window, 'move_to_destination'):
                        self.main_window.move_to_destination(idx, copy_only=copy_only)
            except (ValueError, IndexError):
                pass

    def _save_scroll_position(self):
        """Persist scroll position to config"""
        vbar = self.scroll_area.verticalScrollBar()
        if vbar:
            self.main_window.config.update_setting('shortcuts_sidebar_scroll_position', vbar.value())

    def _restore_scroll_position(self):
        """Restore scroll position from config"""
        settings = self.main_window.config.load_settings()
        pos = settings.get('shortcuts_sidebar_scroll_position', 0)
        vbar = self.scroll_area.verticalScrollBar()
        if vbar and pos > 0:
            vbar.setValue(min(pos, vbar.maximum()))

    def preferred_content_height(self) -> int:
        """Height needed to show all organize shortcuts without vertical scrolling."""
        if not self.content_widget.isVisible():
            return 0
        self.content_widget.adjustSize()
        margins = self.content_layout.contentsMargins()
        return self.content_widget.sizeHint().height() + margins.top() + margins.bottom()

    def refresh_theme_styles(self):
        """Re-apply sidebar chrome and rebuild HTML after theme change."""
        th = get_active_theme()
        self.setStyleSheet(th.shortcuts_sidebar_widget_stylesheet())
        self.scroll_area.setStyleSheet(th.shortcuts_sidebar_scroll_stylesheet())
        if self._move_mode_combo:
            self._move_mode_combo.setStyleSheet(th.shortcuts_sidebar_combo_stylesheet())
        if self._move_mode_note_label:
            self._move_mode_note_label.setStyleSheet(th.shortcuts_sidebar_note_muted_stylesheet())
        if self._move_mode_label:
            self._move_mode_label.setStyleSheet(f"""
                QLabel {{
                    color: {_shortcuts_primary_text_hex()};
                    font-size: 12pt;
                    font-weight: bold;
                }}
            """)
        self.refresh_shortcuts()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(10, self._restore_scroll_position)

    def hideEvent(self, event):
        lbl = getattr(self, "_organize_path_tooltip_label", None)
        if lbl is not None:
            lbl.hide()
        self._save_scroll_position()
        super().hideEvent(event)
