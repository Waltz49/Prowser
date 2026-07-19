#!/usr/bin/env python3
"""
Information Sidebar Widget - Displays image EXIF data and file information
"""

import os
import re
from datetime import datetime
from html import escape, unescape
from typing import Any, Dict, List, Optional, Tuple

from PIL.ExifTags import GPSTAGS
from PySide6.QtCore import QEvent, Qt, QTimer, QSize, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from thumbnails.combined_sidebar_widget import HeaderWidget
from thumbnails.information_tools_menu import (
    _audio_output_ui_enabled,
    _imagegen_create_available,
    _imagegen_edit_ai_available,
    show_information_context_menu,
    show_information_tools_menu,
)
from thumbnails.sidebar_pane_layout import MIN_INFORMATION_CONTENT_HEIGHT
from thumbnails.information_action_nav import (
    INFO_NAV_ACTION_ORDER,
    InformationActionNavBar,
)
from thumbnails.thumbnail_constants import ALT_SYMBOL
from theme.theme_base import job_pane_tools_icon_path
from theme.theme_service import get_active_theme
from utils import (
    format_file_size,
    get_file_extension,
    normalize_path_for_display,
    show_styled_question,
)
from speech_utils import is_speaking, register_speech_state_listener, speak_or_stop, unregister_speech_state_listener
from tooltip_popup_utils import ensure_tooltip_label, position_tooltip_near_cursor
from search.reference_graph import (
    collect_reference_chain_paths,
    get_reference_entries_for_path,
    notify_reference_extension_swap,
    parse_reference_entries_from_text,
    resolve_exif_reference_paths,
    resolve_reference_entries_map,
    resolve_reference_path,
)

# Content inset via viewport margins so the vertical scrollbar stays flush right.
_INFO_VIEWPORT_MARGIN_LEFT = 18
_INFO_VIEWPORT_MARGIN_TOP = 15
_INFO_VIEWPORT_MARGIN_RIGHT = 18
_INFO_VIEWPORT_MARGIN_BOTTOM = 15
_INFO_CONTENT_WIDTH_INSET = _INFO_VIEWPORT_MARGIN_LEFT + _INFO_VIEWPORT_MARGIN_RIGHT

# Persisted collapse keys for information pane headers (generic keys, not per-file values).
_DEFAULT_INFO_SECTION_EXPANDED = {
    'filename': True,
    'references': True,
    'image_model': True,
    'prompt': True,
    'title': True,
    'description': True,
    'negative_prompt': True,
    'input_to_active_job': True,
}
_INFO_H4_SECTION_KEY_BY_TITLE = {
    'references': 'references',
    'image model': 'image_model',
    'prompt': 'prompt',
    'title': 'title',
    'description': 'description',
    'negative prompt': 'negative_prompt',
}
_INFO_H4_TAG_RE = re.compile(r'<h4>([^<]+)</h4>', re.IGNORECASE)
_INFO_IMAGE_MODEL_H4 = '<h4>Image model</h4>'
_INFO_ELAPSED_IN_MODEL_RE = re.compile(
    r'(?i)Elapsed:\s*(\d+:\d{2}:\d{2})(?:\s*\((\d+:\d{2}:\d{2})/iter\))?'
)
# Table rows derived from file/dimensions only (not camera EXIF); user comment is separate below.
_BASIC_INFO_TABLE_FIELDS = frozenset({'Directory', 'Image Size', 'File Size', 'File Date', 'Scale'})


class InformationSidebar(QWidget):
    """Widget for displaying image information (EXIF data) in a right sidebar"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.info_text_edit = None
        self.information_header = None
        self._speakable_description = None
        self._reference_level_paths: Optional[List[str]] = None
        self._gen_timing_path: Optional[str] = None
        self._overlay_has_image_model = False
        self._input_heading_signal_connected = False
        self._info_section_expanded_cache: Optional[Dict[str, bool]] = None
        self._action_nav_bar: InformationActionNavBar | None = None
        self._show_menu_bar = bool(
            main_window.config.load_settings().get("information_show_menu_bar", False)
        )
        self.setup_ui()

    def setup_ui(self):
        """Setup the Information sidebar UI"""
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumWidth(250)
        self.setMaximumWidth(800)
        self.setStyleSheet(get_active_theme().information_sidebar_outer_stylesheet())

        # Create layout for right sidebar
        right_sidebar_layout = QVBoxLayout(self)
        right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        right_sidebar_layout.setSpacing(0)

        # Create header
        header = HeaderWidget("File Information", omit_left_border=True)
        self.information_header = header
        self.information_header.hide_button.clicked.connect(self.toggle_display)
        right_sidebar_layout.addWidget(self.information_header)

        self._setup_action_nav_bar(right_sidebar_layout)

        # Create scrollable text browser for EXIF info (QTextBrowser for link handling)
        self.info_text_edit = QTextBrowser(self)
        self.info_text_edit.setReadOnly(True)
        self.info_text_edit.setMinimumHeight(0)
        self.info_text_edit.setOpenExternalLinks(False)
        self.info_text_edit.setOpenLinks(False)
        self.info_text_edit.anchorClicked.connect(self._on_anchor_clicked)
        self.info_text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.info_text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.info_text_edit.setFocusPolicy(Qt.NoFocus)
        vp = self.info_text_edit.viewport()
        vp.setMouseTracking(True)
        vp.installEventFilter(self)
        self._information_viewport = vp
        register_speech_state_listener(self._on_speech_state_changed)
        self.info_text_edit.setViewportMargins(
            _INFO_VIEWPORT_MARGIN_LEFT,
            _INFO_VIEWPORT_MARGIN_TOP,
            _INFO_VIEWPORT_MARGIN_RIGHT,
            _INFO_VIEWPORT_MARGIN_BOTTOM,
        )
        self.info_text_edit.setStyleSheet(get_active_theme().information_sidebar_textbrowser_stylesheet())
        self.info_text_edit.hide()
        right_sidebar_layout.addWidget(self.info_text_edit)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: show_information_context_menu(self, self.mapToGlobal(pos))
        )
        self.info_text_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_text_edit.customContextMenuRequested.connect(
            lambda pos: show_information_context_menu(
                self, self.info_text_edit.viewport().mapToGlobal(pos)
            )
        )

        self.attach_titlebar_tools()
        self._update_action_nav_state()

    def toggle_display(self):
        """Toggle the Information sidebar visibility"""
        if hasattr(self.main_window, 'toggle_information_display'):
            self.main_window.toggle_information_display()

    def attach_titlebar_tools(self) -> None:
        header = self.information_header
        if header is None:
            return
        btn = QPushButton()
        btn.setIcon(QIcon(job_pane_tools_icon_path()))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip("File information tools")
        btn.clicked.connect(lambda: show_information_tools_menu(self, btn))
        if hasattr(header, "set_tools_button"):
            header.set_tools_button(btn)

    def is_action_menu_bar_visible(self) -> bool:
        return bool(self._show_menu_bar)

    def set_action_menu_bar_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if self._show_menu_bar == visible:
            return
        self._show_menu_bar = visible
        self.main_window.config.update_setting("information_show_menu_bar", visible)
        self._update_action_nav_state()

    def info_action_specs(self) -> List[Dict[str, Any]]:
        data = getattr(self, "_last_overlay_data", None) or {}
        speakable = str(data.get("speakable_plain_text") or "")
        has_comment = bool(speakable.strip())
        return [
            {
                "action_id": "edit",
                "label": "Edit User Comment",
                "visible": True,
                "enabled": True,
            },
            {
                "action_id": "copy",
                "label": "Copy to Clipboard",
                "visible": True,
                "enabled": has_comment,
            },
            {
                "action_id": "speak",
                "label": "Read User Comment Aloud",
                "visible": _audio_output_ui_enabled(),
                "enabled": has_comment,
            },
            {
                "action_id": "delete",
                "label": "Delete User Comment",
                "visible": True,
                "enabled": has_comment,
            },
            {
                "action_id": "create",
                "label": "Create Image from this prompt",
                "visible": _imagegen_create_available(),
                "enabled": True,
            },
            {
                "action_id": "editai",
                "label": "Edit this image with AI",
                "visible": _imagegen_edit_ai_available(),
                "enabled": True,
            },
        ]

    def trigger_info_action(self, action_id: str) -> None:
        scheme = {
            "speak": "speak://",
            "copy": "copy://",
            "edit": "edit://",
            "create": "create://",
            "editai": "editai://",
            "delete": "delete://",
        }.get(action_id)
        if scheme:
            self._on_anchor_clicked(QUrl(scheme))

    def _setup_action_nav_bar(self, parent_layout: QVBoxLayout) -> None:
        nav_bar = InformationActionNavBar(
            self,
            action_order=INFO_NAV_ACTION_ORDER,
            contents_margins=(8, 4, 8, 4),
        )
        nav_bar.setAutoFillBackground(True)
        nav_bar.action_triggered.connect(self.trigger_info_action)
        nav_bar.hide()
        self._action_nav_bar = nav_bar
        parent_layout.addWidget(nav_bar)

    def _update_action_nav_state(self) -> None:
        if self._action_nav_bar is None:
            return
        specs = {spec["action_id"]: spec for spec in self.info_action_specs()}
        bar_specs = {}
        for action_id in INFO_NAV_ACTION_ORDER:
            spec = specs.get(action_id, {})
            bar_specs[action_id] = {
                "visible": bool(spec.get("visible")) and self._show_menu_bar,
                "enabled": bool(spec.get("enabled", True)),
            }
        any_visible = self._action_nav_bar.apply_specs(bar_specs)
        self._action_nav_bar.setVisible(any_visible)
        self._action_nav_bar.set_speak_highlighted(is_speaking())


    def show_info(self):
        """Show the info text edit widget"""
        if self.info_text_edit:
            self.info_text_edit.show()

    def hide_info(self):
        """Hide the info text edit widget"""
        if self.info_text_edit:
            self.info_text_edit.hide()

    def clear_info(self):
        """Clear the info text edit content"""
        if self.info_text_edit:
            self.info_text_edit.clear()

    def minimumSizeHint(self) -> QSize:
        header_h = 30
        if self.information_header is not None:
            header_h = self.information_header.height()
        return QSize(0, header_h + MIN_INFORMATION_CONTENT_HEIGHT)

    def refresh_theme_styles(self):
        """Reapply theme stylesheets and rebuild overlay HTML so borders/text match the active theme."""
        th = get_active_theme()
        if self.information_header:
            self.information_header.refresh_theme_styles()
        self.setStyleSheet(th.information_sidebar_outer_stylesheet())
        if self.info_text_edit:
            self.info_text_edit.setStyleSheet(th.information_sidebar_textbrowser_stylesheet())
            # Keep QTextBrowser document default stylesheet in sync (body background must match theme)
            self.info_text_edit.document().setDefaultStyleSheet(
                f"body {{ color: {self._info_text_hex()}; background-color: {th.information_textbrowser_bg_hex}; font-size: 12pt; }}"
            )
        if hasattr(self, "_link_tooltip_label"):
            self._link_tooltip_label.setStyleSheet(th.information_link_tooltip_stylesheet())
        if self._action_nav_bar is not None:
            self._action_nav_bar.refresh_theme_styles()
            self._action_nav_bar.set_speak_highlighted(is_speaking())
        if getattr(self, "_last_overlay_data", None):
            self._refresh_overlay_for_hover(getattr(self, "_hovered_anchor", None))

    # Tooltips for information action links (Qt does not render HTML title attributes).
    # MAINTAINER: Option+click behaviors here should also be listed in help_hidden_gems.py.
    _ANCHOR_TOOLTIPS = {
        "speak://": "Read aloud (click again to stop)",
        "copy://": (
            f"Copy prompt to clipboard.\n"
            f"{ALT_SYMBOL}+click to copy full user comment."
        ),
        "edit://": "Edit user comment",
        "create://": "Create image from this prompt",
        "editai://": "Edit this image with AI",
        "delete://": "Delete user comment",
        "cancelgen://": "Cancel generation",
        "skipcooldown://": "Skip cooldown",
        "reflevel://": (
            "click: Show the reference graph for complete history.\n"
            f"{ALT_SYMBOL}+click: Show only this image and its direct references "
        ),
    }
    _INFO_COLLAPSE_TOOLTIP = "Click to expand or collapse this section"

    _LEGACY_REF_MD5_LINE = re.compile(r"^[0-9a-fA-F]{32}$")
    _REF_FILEDATE_LINE = re.compile(r"^\d+(?:\.\d+)?$")
    _REF_SECTION_STOP = re.compile(
        r"^(?:prompt|image model|title|description|negative prompt):$", re.IGNORECASE
    )
    _REF_FILEDATE_TOLERANCE_S = 1.0

    @staticmethod
    def _parse_reference_entries_from_lines(lines: List[str], start: int) -> List[Tuple[str, Optional[float]]]:
        """Parse (label, optional_mtime) from References body lines; skip legacy MD5 lines."""
        entries: List[Tuple[str, Optional[float]]] = []
        i = start
        while i < len(lines):
            label = lines[i].strip()
            if not label:
                i += 1
                continue
            if InformationSidebar._REF_SECTION_STOP.match(label):
                break
            if InformationSidebar._LEGACY_REF_MD5_LINE.fullmatch(label):
                i += 1
                continue
            expected_mtime: Optional[float] = None
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if InformationSidebar._LEGACY_REF_MD5_LINE.fullmatch(nxt):
                    entries.append((label, None))
                    i += 2
                    continue
                if InformationSidebar._REF_FILEDATE_LINE.fullmatch(nxt):
                    try:
                        expected_mtime = float(nxt)
                    except ValueError:
                        expected_mtime = None
                    entries.append((label, expected_mtime))
                    i += 2
                    continue
            entries.append((label, None))
            i += 1
        return entries

    @staticmethod
    def _parse_reference_entries_from_text(text: str) -> List[Tuple[str, Optional[float]]]:
        """Parse References block in EXIF user comment."""
        if not text:
            return []
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.strip().lower() == "references:":
                return InformationSidebar._parse_reference_entries_from_lines(lines, i + 1)
        return []

    def _get_reference_entries_for_path(self, image_path: str) -> List[Tuple[str, Optional[float]]]:
        """Read reference entries from EXIF description on *image_path*."""
        return get_reference_entries_for_path(image_path)

    def _resolve_reference_entries_map(
        self,
        image_dir: str,
        current_path: str,
        entries: List[Tuple[str, Optional[float]]],
    ) -> Tuple[Dict[str, str], bool]:
        """Map reference label (lower) -> resolved file path (filedate match when stored)."""
        return resolve_reference_entries_map(image_dir, current_path, entries)

    def _collect_reference_chain_paths(
        self, image_dir: str, root_path: str, entries: List[Tuple[str, Optional[float]]]
    ) -> Tuple[List[str], bool]:
        """Preorder traversal of EXIF References; skip paths and labels already seen."""
        return collect_reference_chain_paths(image_dir, root_path, entries)

    def _resolve_exif_reference_paths(
        self, image_dir: str, current_path: str, entries: List[Tuple[str, Optional[float]]]
    ) -> Tuple[List[str], Dict[str, str], bool]:
        """Resolve direct reference filenames (basename, or ~ / absolute path)."""
        return resolve_exif_reference_paths(image_dir, current_path, entries)

    def _apply_references_markup(
        self, disp: str, image_dir: str, current_path: str
    ) -> Tuple[str, Optional[List[str]]]:
        """Insert reflevel:// links in the References section; set self._reference_level_paths for clicks."""
        self._reference_level_paths = None
        key = "<h4>References</h4>"
        pos = disp.find(key)
        if pos < 0:
            return disp, None
        body_start = pos + len(key)
        next_h4 = disp.find("<h4>", body_start)
        end = len(disp) if next_h4 < 0 else next_h4
        middle = disp[body_start:end]
        segments = middle.split("<br>")
        entries: List[Tuple[str, Optional[float]]] = []
        i = 0
        while i < len(segments):
            fn_seg = segments[i].strip()
            if not fn_seg:
                i += 1
                continue
            if self._LEGACY_REF_MD5_LINE.fullmatch(fn_seg):
                i += 1
                continue
            fname_raw = unescape(fn_seg)
            if i + 1 < len(segments):
                nxt = segments[i + 1].strip()
                if self._LEGACY_REF_MD5_LINE.fullmatch(nxt):
                    entries.append((fname_raw, None))
                    i += 2
                    continue
                if self._REF_FILEDATE_LINE.fullmatch(nxt):
                    try:
                        expected_mtime = float(nxt)
                    except ValueError:
                        expected_mtime = None
                    entries.append((fname_raw, expected_mtime))
                    i += 2
                    continue
            entries.append((fname_raw, None))
            i += 1
        if not entries:
            return disp, None
        level_paths, _resolved_map, _extension_swapped = self._resolve_exif_reference_paths(
            image_dir, current_path, entries
        )
        self._reference_level_paths = level_paths if len(level_paths) > 1 else None
        accent = get_active_theme().accent_color_hex
        new_segments: List[str] = []
        j = 0
        while j < len(segments):
            fn_seg = segments[j].strip()
            if not fn_seg:
                new_segments.append(segments[j])
                j += 1
                continue
            if self._LEGACY_REF_MD5_LINE.fullmatch(fn_seg):
                j += 1
                continue
            if j + 1 < len(segments):
                nxt = segments[j + 1].strip()
                if self._LEGACY_REF_MD5_LINE.fullmatch(nxt) or self._REF_FILEDATE_LINE.fullmatch(nxt):
                    fname_raw = unescape(fn_seg)
                    if resolve_reference_path(image_dir, fname_raw, None) and len(level_paths) > 1:
                        label = segments[j].strip()
                        new_segments.append(
                            f'<a href="reflevel://" style="color:{accent};text-decoration:underline;">{label}</a>'
                        )
                    else:
                        new_segments.append(segments[j])
                    j += 2
                    continue
            fname_raw = unescape(fn_seg)
            if resolve_reference_path(image_dir, fname_raw, None) and len(level_paths) > 1:
                label = segments[j].strip()
                new_segments.append(
                    f'<a href="reflevel://" style="color:{accent};text-decoration:underline;">{label}</a>'
                )
            else:
                new_segments.append(segments[j])
            j += 1
        new_middle = "<br>".join(new_segments)
        new_disp = disp[:body_start] + new_middle + disp[end:]
        return new_disp, self._reference_level_paths

    def _info_text_hex(self) -> str:
        return get_active_theme().sidebar_text_color_hex

    def _info_heading_hex(self) -> str:
        return get_active_theme().sidebar_heading_color_hex()

    def _load_info_section_expanded(self) -> Dict[str, bool]:
        state = dict(_DEFAULT_INFO_SECTION_EXPANDED)
        try:
            saved = self.main_window.config.load_settings().get('information_section_expanded')
            if isinstance(saved, dict):
                for key, value in saved.items():
                    if key in state and isinstance(value, bool):
                        state[key] = value
        except Exception:
            pass
        return state

    def _info_section_expanded(self, key: str) -> bool:
        if self._info_section_expanded_cache is None:
            self._info_section_expanded_cache = self._load_info_section_expanded()
        if key in self._info_section_expanded_cache:
            return self._info_section_expanded_cache[key]
        return _DEFAULT_INFO_SECTION_EXPANDED.get(key, True)

    def _set_info_section_expanded(self, key: str, expanded: bool) -> None:
        if key not in _DEFAULT_INFO_SECTION_EXPANDED:
            return
        if self._info_section_expanded_cache is None:
            self._info_section_expanded_cache = self._load_info_section_expanded()
        if self._info_section_expanded_cache.get(key) is expanded:
            return
        self._info_section_expanded_cache[key] = expanded
        try:
            if hasattr(self.main_window, 'config'):
                self.main_window.config.update_setting(
                    'information_section_expanded',
                    dict(self._info_section_expanded_cache),
                )
        except Exception:
            pass

    @staticmethod
    def _info_section_key_from_h4_title(title: str) -> Optional[str]:
        return _INFO_H4_SECTION_KEY_BY_TITLE.get(unescape(title).strip().lower())

    def _collapsible_header_html(
        self,
        section_key: str,
        title: str,
        expanded: bool,
        *,
        font_size: str = '12pt',
        margin_bottom: str | None = None,
        link_color: str | None = None,
    ) -> str:
        indicator = '▼' if expanded else '▶'
        color = link_color or self._info_heading_hex()
        if margin_bottom is None:
            margin_bottom = '12px' if expanded else '4px'
        return (
            f'<div style="font-weight: bold; font-size: {font_size}; '
            f'margin-bottom: {margin_bottom};">'
            f'<a href="infocollapse://{section_key}" '
            f'style="color: {color}; text-decoration: none; cursor: pointer;">'
            f'{indicator} {title}</a></div>'
        )

    def _wrap_description_with_collapsible_sections(self, description_html: str) -> str:
        """Replace program-added h4 headers with persisted collapsible sections."""
        if not description_html:
            return description_html
        parts = _INFO_H4_TAG_RE.split(description_html)
        if len(parts) <= 1:
            return description_html
        out = [parts[0]]
        idx = 1
        while idx + 1 < len(parts):
            title = parts[idx]
            body = parts[idx + 1]
            section_key = self._info_section_key_from_h4_title(title)
            if section_key:
                expanded = self._info_section_expanded(section_key)
                out.append(
                    self._collapsible_header_html(
                        section_key,
                        title,
                        expanded,
                        margin_bottom='6px' if expanded else '2px',
                    )
                )
                if expanded:
                    out.append(body)
            else:
                out.append(f'<h4>{title}</h4>{body}')
            idx += 2
        return ''.join(out)

    def _on_speech_state_changed(self, _speaking: bool) -> None:
        QTimer.singleShot(0, self._refresh_speak_action_highlight)

    def _refresh_speak_action_highlight(self) -> None:
        if self._action_nav_bar is not None:
            self._action_nav_bar.refresh_theme_styles()
            self._action_nav_bar.set_speak_highlighted(is_speaking())

    def eventFilter(self, obj, event):
        """Show tooltip and red highlight when hovering over information action links."""
        if obj is self._information_viewport:
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                anchor = self.info_text_edit.anchorAt(pos)
                tooltip = self._ANCHOR_TOOLTIPS.get(anchor, "")
                if not tooltip and anchor.startswith("infocollapse://"):
                    tooltip = self._INFO_COLLAPSE_TOOLTIP
                self._show_link_tooltip(tooltip)
                if anchor != getattr(self, '_hovered_anchor', None):
                    self._hovered_anchor = anchor
                    self._refresh_overlay_for_hover(anchor)
            elif event.type() == QEvent.Type.Leave:
                self._show_link_tooltip("")
                if getattr(self, '_hovered_anchor', None) is not None:
                    self._hovered_anchor = None
                    self._refresh_overlay_for_hover(None)
        return super().eventFilter(obj, event)

    def _show_link_tooltip(self, text):
        """Show or hide floating tooltip for information links. Uses custom QLabel since QToolTip is unreliable on macOS."""
        lbl = ensure_tooltip_label(self, "_link_tooltip_label")
        if text:
            lbl.setStyleSheet(get_active_theme().information_link_tooltip_stylesheet())
            lbl.setText(text)
            lbl.adjustSize()
            position_tooltip_near_cursor(lbl, clamp_widget=self)
            lbl.show()
            lbl.raise_()
        else:
            lbl.hide()

    def _speakable_text_for_speech(self) -> str:
        if self._speakable_description:
            return self._speakable_description
        data = getattr(self, "_last_overlay_data", None) or {}
        return str(data.get("speakable_plain_text") or "")

    def _on_anchor_clicked(self, url):
        """Handle click on speak/copy/delete links in the information description area."""
        from exif.exif_utils import truncate_usercomment_before_prompt
        if url.scheme() == 'infocollapse':
            section_key = url.host() or ''
            if section_key:
                self._set_info_section_expanded(
                    section_key,
                    not self._info_section_expanded(section_key),
                )
                self._rebuild_overlay_from_cache(
                    hovered_anchor=getattr(self, '_hovered_anchor', None)
                )
            return
        if url.toString() == "reflevel://":
            from PySide6.QtWidgets import QApplication

            mw = self.main_window
            current = getattr(mw, "current_image_path", None)
            if not current or not os.path.isfile(current):
                return
            image_dir = os.path.dirname(current) or ""
            entries = self._get_reference_entries_for_path(current)
            option_held = bool(
                QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier
            )
            extension_swapped = False
            if option_held:
                paths, _resolved, extension_swapped = self._resolve_exif_reference_paths(
                    image_dir, current, entries
                )
                if not paths:
                    return
                config = {"files": paths, "sort_mode": "custom"}
            else:
                paths, extension_swapped = self._collect_reference_chain_paths(
                    image_dir, current, entries
                )
                if len(paths) < 2:
                    return
                config = {
                    "files": paths,
                    "sort_mode": "custom",
                    "presentation": "reference_graph",
                    "focus_path": current,
                }
            if extension_swapped:
                notify_reference_extension_swap(mw)
            if hasattr(mw, "directory_stack_history_handler"):
                h = mw.directory_stack_history_handler
                st = h.capture_current_state()
                if st and not h.is_duplicate_state(st):
                    h.backward_stack.append(st)
                    h.forward_stack.clear()
            mw.refresh_from_configuration(config)
            if hasattr(mw, "update_sort_menu_checkmarks"):
                mw.update_sort_menu_checkmarks()
            if hasattr(mw, "save_sorting_settings"):
                mw.save_sorting_settings()
            return
        if url.toString() == "speak://":
            text = truncate_usercomment_before_prompt(self._speakable_text_for_speech())
            speak_or_stop(text)
            QTimer.singleShot(0, self._refresh_speak_action_highlight)
        elif url.toString() == "copy://":
            from PySide6.QtWidgets import QApplication
            from exif.exif_utils import usercomment_text_for_clipboard

            raw = self._speakable_description or ""
            option_held = bool(
                QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier
            )
            text = usercomment_text_for_clipboard(raw, copy_full=option_held)
            from copy_feedback import copy_text_to_clipboard

            copy_text_to_clipboard(text, anchor=self.info_text_edit)
        elif url.toString() == "edit://":
            if hasattr(self.main_window, 'edit_exif_usercomment'):
                self.main_window.edit_exif_usercomment()
        elif url.toString() == "create://":
            self._on_create_image_prompt()
        elif url.toString() == "editai://":
            self._on_edit_with_ai()
        elif url.toString() == "delete://":
            self._on_delete_user_comment()
        elif url.toString() == "cancelgen://":
            self._on_cancel_generation()
        elif url.toString() == "skipcooldown://":
            try:
                from imagegen_plugins.image_gen_controller import get_imagegen_controller

                get_imagegen_controller(self.main_window).skip_copy_cooldown()
            except ImportError:
                pass

    def _on_cancel_generation(self) -> None:
        """Cancel the active generation job after confirmation (same as job pane)."""
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller

            get_imagegen_controller(self.main_window).confirm_cancel_generation(
                self.main_window
            )
        except ImportError:
            pass

    def _on_create_image_prompt(self):
        """Open Create > Create an image from text..., primed from the user comment."""
        try:
            from imagegen_plugins.image_gen_menu import open_imagegen_create_from_text_dialog
        except ImportError:
            return
        data = getattr(self, "_last_overlay_data", None) or {}
        user_comment = data.get("speakable_plain_text") or ""
        open_imagegen_create_from_text_dialog(
            self.main_window,
            user_comment=user_comment,
        )

    def _on_edit_with_ai(self):
        """Open AI image edit dialog with Import Available applied automatically."""
        try:
            from imagegen_plugins.image_gen_menu import open_imagegen_edit_dialog
        except ImportError:
            return
        data = getattr(self, "_last_overlay_data", None) or {}
        user_comment = data.get("speakable_plain_text") or ""
        open_imagegen_edit_dialog(
            self.main_window,
            user_comment=user_comment,
        )

    def _on_delete_user_comment(self):
        """Delete the EXIF user comment from the current image after confirmation."""
        image_path = getattr(self.main_window, 'current_image_path', None)
        if not image_path or not os.path.exists(image_path):
            if getattr(self.main_window, 'status_notification', None):
                self.main_window.status_notification.show_message("No image selected")
            return

        ext = get_file_extension(image_path)
        if ext not in {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp'}:
            if getattr(self.main_window, 'status_notification', None):
                self.main_window.status_notification.show_message("This image format does not support EXIF user comments")
            return

        from PySide6.QtWidgets import QMessageBox

        reply = show_styled_question(
            self.main_window,
            "Delete User Comment",
            "Delete the EXIF user comment from this image?",
            default_no=True,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from exif.exif_utils import delete_usercomment_from_file
        success = delete_usercomment_from_file(image_path)
        if success:
            if getattr(self.main_window, 'status_notification', None):
                self.main_window.status_notification.show_message("EXIF user comment deleted")
            self.show_image_info_overlay()
        else:
            if getattr(self.main_window, 'status_notification', None):
                self.main_window.status_notification.show_message("Failed to delete EXIF user comment")

    def extract_exif_data(self, image_path: str) -> Dict[str, Any]:
        """Extract comprehensive EXIF data from image file, supporting HEIC and other modern formats"""
        exif_data = {}
        try:
            if not os.path.exists(image_path):
                return exif_data

            from exif.exif_utils import get_exif_dict_named_from_image_path

            exif_dict = get_exif_dict_named_from_image_path(image_path)

            # If still no EXIF data found, return empty dict
            if not exif_dict:
                return exif_data

            # Extract GPS info if available
            gps_info = None
            if 'GPSInfo' in exif_dict:
                gps_info_value = exif_dict['GPSInfo']
                # GPSInfo might be a dict (from _getexif) or an int/tag reference (from getexif)
                if isinstance(gps_info_value, dict):
                    gps_info = {}
                    for tag_id, value in gps_info_value.items():
                        tag_name = GPSTAGS.get(tag_id, tag_id)
                        gps_info[tag_name] = value
                else:
                    # GPSInfo is not a dict (might be an int tag reference or other type)
                    # Skip GPS processing for non-dict GPSInfo values
                    pass

            # Priority fields (size, date & time, camera, lens, location author)
            # Note: Image Size will be added from actual image dimensions in show_image_info_overlay
            # We don't add it here to avoid duplication

            # EXIF Date & Time (stored as 'EXIF Date' to distinguish from file system date)
            date_time_fields = ['DateTime', 'DateTimeOriginal', 'DateTimeDigitized']
            for field in date_time_fields:
                if field in exif_dict:
                    try:
                        dt_str = exif_dict[field]
                        if isinstance(dt_str, str):
                            # Format: "YYYY:MM:DD HH:MM:SS"
                            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
                            exif_data['EXIF Date'] = dt.strftime("%Y-%m-%d %H:%M:%S")
                            break
                    except Exception:
                        pass

            # Camera
            make = exif_dict.get('Make', '').strip()
            model = exif_dict.get('Model', '').strip()
            if make or model:
                camera = f"{make} {model}".strip()
                if camera:
                    exif_data['Camera'] = camera

            # Orientation
            if 'Orientation' in exif_dict:
                orientation_value = exif_dict['Orientation']
                if orientation_value is not None:
                    orientation_map = {1: 'Normal', 2: 'Mirrored', 3: 'Rotated 180°',
                                      4: 'Rotated 180°, Mirrored', 5: 'Rotated 90° CCW, Mirrored',
                                      6: 'Rotated 90° CW', 7: 'Rotated 90° CW, Mirrored',
                                      8: 'Rotated 90° CCW'}
                    exif_data['Orientation'] = orientation_map.get(orientation_value, str(orientation_value))

            # Lens
            lens_fields = ['LensModel', 'LensMake', 'LensType', 'LensID']
            lens_parts = []
            for field in lens_fields:
                if field in exif_dict:
                    lens_val = str(exif_dict[field]).strip()
                    if lens_val and lens_val not in lens_parts:
                        lens_parts.append(lens_val)
            if lens_parts:
                exif_data['Lens'] = ' '.join(lens_parts)

            # Location Author (GPS)
            if gps_info:
                lat = gps_info.get('GPSLatitude')
                lon = gps_info.get('GPSLongitude')
                lat_ref = gps_info.get('GPSLatitudeRef', 'N')
                lon_ref = gps_info.get('GPSLongitudeRef', 'E')
                if lat and lon:
                    def dms_to_decimal(dms, ref):
                        if isinstance(dms, tuple) and len(dms) == 3:
                            degrees, minutes, seconds = dms
                            decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
                            if ref in ['S', 'W']:
                                decimal = -decimal
                            return decimal
                        return None
                    latitude = dms_to_decimal(lat, lat_ref)
                    longitude = dms_to_decimal(lon, lon_ref)
                    if latitude is not None and longitude is not None:
                        # Format GPS coordinates: use 3 decimals for floats, integers for whole numbers
                        def format_gps_coord(coord):
                            if coord == int(coord):
                                return str(int(coord))
                            return f"{coord:.3f}"
                        exif_data['Location'] = f"{format_gps_coord(latitude)}, {format_gps_coord(longitude)}"

            # User data (description, etc.)
            user_fields = ['ImageDescription', 'UserComment', 'XPComment', 'XPSubject']
            for field in user_fields:
                if field in exif_dict:
                    desc_value = exif_dict[field]
                    # Handle bytes objects - decode if possible, skip if invalid
                    if isinstance(desc_value, bytes):
                        try:
                            if field == 'UserComment':
                                # Use charset-aware decoder that handles ASCII/UNICODE prefix
                                from exif.exif_utils import decode_usercomment
                                desc = decode_usercomment(desc_value).strip()
                            else:
                                # Try to decode as UTF-8, filtering out null bytes
                                desc = desc_value.decode('utf-8', errors='ignore').strip()
                            # Remove any remaining null bytes
                            desc = desc.replace('\x00', '')
                        except Exception:
                            desc = None
                    else:
                        desc = str(desc_value).strip()
                        # Remove null bytes from string
                        desc = desc.replace('\x00', '')
                        # Skip if it looks like a bytes representation (starts with b' or b")
                        if desc.startswith("b'") or desc.startswith('b"'):
                            desc = None
                    # Only add if description is meaningful (not empty and not just null bytes)
                    if desc and desc.strip():
                        exif_data['Description'] = desc
                        break

            # Remaining known EXIF fields (excluding already added ones)
            priority_fields = {'Image Size', 'EXIF Date', 'Camera', 'Orientation', 'Lens', 'Location', 'Description'}
            known_fields = {
                'Make': 'Make',
                'Model': 'Model',
                'Software': 'Software',
                'Artist': 'Artist',
                'Copyright': 'Copyright',
                'ExposureTime': 'Exposure',
                'FNumber': 'Aperture',
                'ISOSpeedRatings': 'ISO',
                'FocalLength': 'Focal Length',
                'Flash': 'Flash',
                'WhiteBalance': 'White Balance',
                'MeteringMode': 'Metering Mode',
                'ExposureMode': 'Exposure Mode',
                'ExposureProgram': 'Exposure Program',
                'ShutterSpeedValue': 'Shutter Speed',
                'ApertureValue': 'Aperture Value',
                'BrightnessValue': 'Brightness',
                'SubjectDistance': 'Subject Distance',
                'FocalLengthIn35mmFilm': 'Focal Len (35mm)',
                'SceneType': 'Scene Type',
                'ColorSpace': 'Color Space',
                'Orientation': 'Orientation',
            }

            # Helper function to format float values to 3 decimal places
            def format_float(value):
                """Format float to 3 decimal places, or return as integer string if decimals are zero"""
                # If it's already an integer, return as string
                if isinstance(value, int):
                    return str(value)
                # Try to convert to float
                try:
                    float_val = float(value)
                    # If it's actually an integer (no decimal part), return as integer string
                    if float_val == int(float_val):
                        return str(int(float_val))
                    # Format to 3 decimal places
                    formatted = f"{float_val:.3f}"
                    # If all decimals are zero, return as integer string
                    if formatted.endswith(".000"):
                        return str(int(float_val))
                    return formatted
                except (ValueError, TypeError):
                    return value

            for exif_key, display_name in known_fields.items():
                if exif_key in exif_dict and display_name not in priority_fields:
                    value = exif_dict[exif_key]
                    if value is not None:
                        # Format specific fields
                        if exif_key == 'ExposureTime':
                            if isinstance(value, tuple) and len(value) == 2:
                                value = f"{value[0]}/{value[1]}"
                            else:
                                value = f"1/{int(1/value)}" if value < 1 else str(value)
                        elif exif_key == 'FNumber':
                            # Format aperture value to 3 decimal places
                            formatted_value = format_float(value)
                            value = f"f/{formatted_value}"
                        elif exif_key == 'FocalLength':
                            if isinstance(value, tuple) and len(value) == 2:
                                value = f"{value[0]}/{value[1]}"
                            else:
                                # Format focal length to 3 decimal places if it's a float
                                if isinstance(value, float):
                                    value = f"{format_float(value)}mm"
                                elif isinstance(value, int):
                                    value = f"{value}mm"
                                else:
                                    value = f"{value}mm"
                        elif exif_key == 'ShutterSpeedValue':
                            # Format shutter speed value to 3 decimal places
                            value = format_float(value)
                        elif exif_key == 'ApertureValue':
                            # Format aperture value to 3 decimal places
                            value = format_float(value)
                        elif exif_key == 'BrightnessValue':
                            # Format brightness value to 3 decimal places
                            value = format_float(value)
                        elif exif_key == 'SubjectDistance':
                            # Format subject distance to 3 decimal places if it's a float
                            if isinstance(value, float):
                                value = format_float(value)
                            elif isinstance(value, int):
                                value = str(value)
                            else:
                                value = str(value)
                        elif exif_key == 'FocalLengthIn35mmFilm':
                            # Format focal length to 3 decimal places if it's a float
                            if isinstance(value, float):
                                value = f"{format_float(value)}mm"
                            elif isinstance(value, int):
                                value = f"{value}mm"
                            else:
                                value = str(value)
                        elif exif_key == 'Flash':
                            flash_map = {0: 'No Flash', 1: 'Fired', 5: 'Fired, Return not detected',
                                        7: 'Fired, Return detected', 9: 'Fired, Compulsory',
                                        13: 'Fired, Compulsory, Return not detected',
                                        15: 'Fired, Compulsory, Return detected'}
                            value = flash_map.get(value, str(value))
                        elif exif_key == 'WhiteBalance':
                            value = 'Auto' if value == 0 else 'Manual'
                        elif exif_key == 'Orientation':
                            orientation_map = {1: 'Normal', 2: 'Mirrored', 3: 'Rotated 180°',
                                              4: 'Rotated 180°, Mirrored', 5: 'Rotated 90° CCW, Mirrored',
                                              6: 'Rotated 90° CW', 7: 'Rotated 90° CW, Mirrored',
                                              8: 'Rotated 90° CCW'}
                            value = orientation_map.get(value, str(value))
                        else:
                            # For other numeric fields, format floats to 3 decimal places
                            if isinstance(value, float):
                                value = format_float(value)
                            elif isinstance(value, int):
                                value = str(value)

                        exif_data[display_name] = str(value)

        except Exception as e:
            # Silently fail - return empty dict if EXIF extraction fails
            pass

        return exif_data

    @staticmethod
    def _comment_has_image_model_section(text: Optional[str]) -> bool:
        if not text:
            return False
        return bool(re.search(r"(?im)^image model:", text))

    @staticmethod
    def _highlight_image_model_elapsed_html(disp: str) -> str:
        """Bold elapsed duration values in the Image model section (like section headings)."""
        pos = disp.find(_INFO_IMAGE_MODEL_H4)
        if pos < 0:
            return disp
        body_start = pos + len(_INFO_IMAGE_MODEL_H4)
        next_h4 = disp.find('<h4>', body_start)
        end = len(disp) if next_h4 < 0 else next_h4
        middle = disp[body_start:end]

        def repl(match: re.Match[str]) -> str:
            main = match.group(1)
            per_iter = match.group(2)
            out = f'Elapsed: <b>{main}</b>'
            if per_iter:
                out += f' ({per_iter}/iter)'
            return out

        middle = _INFO_ELAPSED_IN_MODEL_RE.sub(repl, middle)
        return disp[:body_start] + middle + disp[end:]

    def _update_overlay_image_model_flag(
        self, image_path: str, speakable_plain_text: Optional[str]
    ) -> None:
        """Sticky per-path Image Model section flag (not re-checked on timing polls)."""
        norm = os.path.normpath(image_path) if image_path else ""
        if norm != (self._gen_timing_path or ""):
            self._gen_timing_path = norm or None
            self._overlay_has_image_model = self._comment_has_image_model_section(
                speakable_plain_text
            )
        elif speakable_plain_text and self._comment_has_image_model_section(
            speakable_plain_text
        ):
            self._overlay_has_image_model = True

    def _info_container_width_px(self) -> int:
        """Full information sidebar widget width (not document text width)."""
        if self.isVisible() and self.width() > 0:
            return self.width()
        if hasattr(self.main_window, "right_sidebar_width"):
            w = int(self.main_window.right_sidebar_width or 0)
            if w > 0:
                return w
        if self.info_text_edit is not None:
            vp_w = int(self.info_text_edit.viewport().width())
            if vp_w > 0:
                return vp_w + _INFO_CONTENT_WIDTH_INSET
        return 250

    def _info_content_width_px(self) -> int:
        """Match QTextDocument.setTextWidth (sidebar width minus browser padding)."""
        if self.info_text_edit is not None:
            doc_w = int(self.info_text_edit.document().textWidth())
            if doc_w > 0:
                return doc_w
            vp_w = int(self.info_text_edit.viewport().width())
            if vp_w > 0:
                return vp_w
        return max(160, self._info_container_width_px() - _INFO_CONTENT_WIDTH_INSET)

    def preferred_content_height(self) -> int:
        """Height needed to show all information content without vertical scrolling."""
        if not self.info_text_edit or not self.info_text_edit.isVisible():
            return 0
        tb = self.info_text_edit
        doc = tb.document()
        content_w = self._info_content_width_px()
        if content_w > 0:
            doc.setTextWidth(content_w)
        layout = doc.documentLayout()
        doc_h = layout.documentSize().height() if layout is not None else doc.size().height()
        # Viewport top/bottom margins (15px each); include slack.
        pad_v = _INFO_VIEWPORT_MARGIN_TOP + _INFO_VIEWPORT_MARGIN_BOTTOM
        extra = (
            pad_v
            + doc.documentMargin() * 2
            + tb.contentsMargins().top()
            + tb.contentsMargins().bottom()
            + tb.frameWidth() * 2
            + 6
        )
        return int(doc_h) + extra

    def _should_show_input_to_active_job_heading(self) -> bool:
        try:
            from bundle_capabilities import imagegen_ui_enabled

            if not imagegen_ui_enabled():
                return False
        except ImportError:
            pass
        path = getattr(self.main_window, "current_image_path", None)
        if not path:
            return False
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller

            return get_imagegen_controller(
                self.main_window
            ).viewing_path_matches_active_generation(path)
        except ImportError:
            return False

    def _restore_info_scroll_position(self, scroll_pos: int) -> None:
        """Restore vertical scroll after HTML relayout."""
        if not self.info_text_edit:
            return
        sb = self.info_text_edit.verticalScrollBar()
        sb.setValue(min(scroll_pos, sb.maximum()))

    def _apply_info_html_to_browser(
        self, info_text: str, *, preserve_scroll: bool = False, scroll_pos: int = 0
    ) -> None:
        if not self.info_text_edit or not info_text:
            return
        info_text = info_text.rstrip("\x00")
        doc = self.info_text_edit.document()
        doc.setHtml(info_text)
        th = get_active_theme()
        doc.setDefaultStyleSheet(
            f"body {{ color: {self._info_text_hex()}; background-color: {th.information_textbrowser_bg_hex}; font-size: 12pt; }}"
        )
        self.info_text_edit.setReadOnly(True)

        def update_text_width():
            if self.isVisible():
                sidebar_width = self.width()
                if sidebar_width > 0:
                    doc.setTextWidth(sidebar_width - _INFO_CONTENT_WIDTH_INSET)
            elif hasattr(self.main_window, "right_sidebar_width"):
                doc.setTextWidth(self.main_window.right_sidebar_width - _INFO_CONTENT_WIDTH_INSET)
            self.info_text_edit.update()
            if preserve_scroll:
                self._restore_info_scroll_position(scroll_pos)

        QTimer.singleShot(0, update_text_width)
        if self.isVisible():
            sidebar_width = self.width()
            if sidebar_width > 0:
                doc.setTextWidth(sidebar_width - _INFO_CONTENT_WIDTH_INSET)
        elif hasattr(self.main_window, "right_sidebar_width"):
            doc.setTextWidth(self.main_window.right_sidebar_width - _INFO_CONTENT_WIDTH_INSET)
        self.info_text_edit.update()
        if preserve_scroll:
            self._restore_info_scroll_position(scroll_pos)

    def _rebuild_overlay_from_cache(self, *, hovered_anchor: str | None = None) -> None:
        if not getattr(self, "_last_overlay_data", None) or not self.info_text_edit:
            return
        scroll_pos = self.info_text_edit.verticalScrollBar().value()
        data = self._last_overlay_data
        info_text = self._build_info_overlay_html(
            data["filename"],
            data["field_value_pairs"],
            data.get("description"),
            data.get("speakable_plain_text"),
            hovered_anchor=hovered_anchor,
            show_input_to_active_job_heading=self._should_show_input_to_active_job_heading(),
        )
        if info_text:
            self.info_text_edit.blockSignals(True)
            self.info_text_edit.clear()
            self._apply_info_html_to_browser(
                info_text, preserve_scroll=True, scroll_pos=scroll_pos
            )
            self.info_text_edit.blockSignals(False)
        self._update_action_nav_state()

    def _ensure_input_heading_signal_connected(self) -> None:
        if self._input_heading_signal_connected:
            return
        try:
            from imagegen_plugins.image_gen_controller import get_imagegen_controller

            controller = get_imagegen_controller(self.main_window)
        except ImportError:
            return
        controller.generation_started.connect(self._refresh_input_to_active_job_heading)
        controller.generation_finished.connect(self._refresh_input_to_active_job_heading)
        self._input_heading_signal_connected = True

    def _refresh_input_to_active_job_heading(self) -> None:
        self._ensure_input_heading_signal_connected()
        if getattr(self, "_last_overlay_data", None) and self.info_text_edit:
            self._rebuild_overlay_from_cache(
                hovered_anchor=getattr(self, "_hovered_anchor", None)
            )

    def _refresh_overlay_for_hover(self, hovered_anchor=None):
        """Rebuild overlay HTML with hovered link highlighted (text and border #50c8ff)."""
        if not hasattr(self, '_last_overlay_data') or not self._last_overlay_data:
            return
        if not self.info_text_edit:
            return
        self._rebuild_overlay_from_cache(hovered_anchor=hovered_anchor)

    def _build_info_overlay_html(
        self,
        filename: str,
        field_value_pairs: list,
        description: str = None,
        speakable_plain_text: str = None,
        hovered_anchor: str = None,
        *,
        show_input_to_active_job_heading: bool = False,
    ) -> str:
        """Build HTML overlay from field-value pairs using table format.

        Args:
            filename: The filename to display as header
            field_value_pairs: List of (field, value) tuples
            description: Optional description fragment (escaped text plus allowed <br>/<h4> markup)
            speakable_plain_text: Optional plain text for TTS; if len > 30, adds ear icon

        Returns:
            HTML string for the overlay
        """
        # Helper function to elide long values
        def elide_value(value_str, max_len=40):
            if len(value_str) > max_len:
                return value_str[:max_len-3] + '...'
            return value_str

        _th = get_active_theme()
        bdr = _th.text_disabled_hex
        # Start building HTML - use proper table with 2 columns
        # Use "Courier New" instead of "monospace" to avoid font warning
        text_hex = self._info_text_hex()
        html_parts = [f'<div style="color: {text_hex}; font-size: 12pt; font-family: \'Courier New\', Monaco, Menlo; line-height: 1.4;">']
        filename_expanded = self._info_section_expanded('filename')
        html_parts.append(
            self._collapsible_header_html(
                'filename',
                filename,
                filename_expanded,
                font_size='14pt',
            )
        )

        # Build 2-column table (Field | Value)
        if filename_expanded and field_value_pairs:
            has_exif_fields = any(
                field not in _BASIC_INFO_TABLE_FIELDS for field, _ in field_value_pairs
            )
            if has_exif_fields:
                table_style = f'border: 1px solid {bdr}; border-collapse: collapse; width: 100%;'
                label_cell_style = (
                    f'border: 1px solid {bdr}; padding: 4px 4px 4px 2px; text-align: right; '
                    f'color: {text_hex}; white-space: nowrap; width: 1%;'
                )
                value_cell_style = (
                    f'border: 1px solid {bdr}; padding: 4px 8px; color: {text_hex};'
                )
            else:
                table_style = (
                    'border: none; border-collapse: collapse; width: 100%; '
                    'line-height: 1.0;'
                )
                label_cell_style = (
                    f'border: none; text-align: left; '
                    f'color: {text_hex}; white-space: nowrap; width: 1%; vertical-align: top;'
                    'padding: 0px;'
                )
                value_cell_style = (
                    f'border: none;  color: {text_hex}; '
                    f'vertical-align: top;'
                    'padding: 0px 0px 0px 4px;'
                )

            html_parts.append(f'<table style="{table_style}">')

            # One row per field-value pair
            for field, value in field_value_pairs:
                html_parts.append('<tr>')
                html_parts.append(f'<td style="{label_cell_style}">{field}:</td>')
                html_parts.append(f'<td style="{value_cell_style}">{value}</td>')
                html_parts.append('</tr>')

            html_parts.append('</table>')

        description_visible = True
        if show_input_to_active_job_heading:
            active_bdr = _th.current_image_border_color_hex
            active_bdr_w = max(1, int(getattr(_th, "current_image_border_width_index", 2)))
            input_expanded = self._info_section_expanded('input_to_active_job')
            description_visible = input_expanded
            html_parts.append(
                f'<div style="margin-top: 12px; padding-top: 10px; padding-bottom: 4px; '
                f'border-top: {active_bdr_w}px solid {active_bdr};">'
            )
            html_parts.append(
                self._collapsible_header_html(
                    'input_to_active_job',
                    'Input to Active Job',
                    input_expanded,
                    font_size='12pt',
                    margin_bottom='6px' if input_expanded else '2px',
                    link_color=active_bdr,
                )
            )
            html_parts.append("</div>")

        if not description_visible:
            html_parts.append('</div>')
            return ''.join(html_parts)

        # Add Description if present (action buttons live in the menu bar / context menu only)
        if description:
            description = description.replace('\x00', '')
            if description.strip() and not (description.strip().startswith("b'") or description.strip().startswith('b"')):
                description = self._wrap_description_with_collapsible_sections(description)
                html_parts.append(f'<div style="padding-top: 10px; padding-bottom: 6px; margin-top: 10px; border-top: 1px solid {bdr}; color: {text_hex}; font-size: 12pt;">{description}</div>')
            else:
                html_parts.append(f'<div style="padding-top: 10px; padding-bottom: 6px; margin-top: 10px; border-top: 1px solid {bdr}; color: {text_hex}; font-size: 12pt;"></div>')
        else:
            html_parts.append(f'<div style="padding-top: 10px; padding-bottom: 6px; margin-top: 10px; border-top: 1px solid {bdr}; color: {text_hex}; font-size: 12pt;">Add user comment</div>')

        html_parts.append('</div>')
        return ''.join(html_parts)

    def show_image_info_overlay(self):
        """Show image info overlay with EXIF data"""
        if not hasattr(self.main_window, 'current_image_path') or not self.main_window.current_image_path:
            return

        self._reference_level_paths = None

        current_image_path = self.main_window.current_image_path

        # Get file metadata and dimensions
        filename_only = os.path.basename(current_image_path)
        filename, width, height = self.main_window.get_image_info(current_image_path)

        # Helper function to elide long values
        def elide_value(value_str, max_len=40):
            if len(value_str) > max_len:
                return value_str[:max_len-3] + '...'
            return value_str

        # Helper function to check if value is zero
        def is_zero(value):
            try:
                # Try numeric conversion
                num_val = float(value)
                return abs(num_val) < 0.0001  # Small epsilon for floating point
            except (ValueError, TypeError):
                # Not numeric, check string representations
                value_str = str(value).strip().lower()
                return value_str in ('0', '0.0', '0.00', 'none', 'n/a', '')

        # Helper function to get file size in bytes
        def get_file_size_bytes():
            file_size_bytes = None
            try:
                # Try to get from cache first
                if hasattr(self.main_window, 'cache_manager') and self.main_window.cache_manager:
                    metadata = self.main_window.cache_manager.get_metadata_sync(current_image_path)
                    if metadata and hasattr(metadata, 'file_size') and metadata.file_size:
                        file_size_bytes = metadata.file_size
                # Fallback to filesystem if not in cache
                if file_size_bytes is None:
                    if os.path.exists(current_image_path):
                        file_size_bytes = os.path.getsize(current_image_path)
            except Exception:
                pass  # If we can't get file size, just skip it
            return file_size_bytes

        # Helper function to get directory name (~ for home; elided if > 40 characters)
        def get_directory_name():
            directory_name = None
            try:
                directory_path = os.path.dirname(current_image_path)
                if directory_path:
                    directory_path = normalize_path_for_display(directory_path)
                    if len(directory_path) > 40:
                        # Show last part of path
                        directory_name = "..." + directory_path[-37:]
                    else:
                        directory_name = directory_path
            except Exception:
                pass  # If we can't get directory, just skip it
            return directory_name

        # Helper function to get file system date/time
        def get_file_date():
            file_date = None
            try:
                if os.path.exists(current_image_path):
                    # Get file modification time
                    mtime = os.path.getmtime(current_image_path)
                    dt = datetime.fromtimestamp(mtime)
                    file_date = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                pass  # If we can't get file date, just skip it
            return file_date

        try:
            # Extract EXIF data
            exif_data = self.extract_exif_data(current_image_path)

            # Get file size, directory, and file date
            file_size_bytes = get_file_size_bytes()
            directory_name = get_directory_name()
            file_date = get_file_date()

            # Collect all field-value pairs, filtering out zeros
            field_value_pairs = []

            # Always add Directory, Image Size, File Size, File Date as the first four lines
            # 1. Directory
            if directory_name:
                directory_escaped = directory_name.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                directory_escaped = elide_value(directory_escaped)
                field_value_pairs.append(('Directory', directory_escaped))

            # 2. Image Size (from actual image dimensions)
            if width > 0 and height > 0:
                field_value_pairs.append(('Image Size', f"{width} × {height}\n{width*height/1000000:.2f}MP"))

            # 3. File Size
            if file_size_bytes is not None and file_size_bytes > 0:
                file_size_str = format_file_size(file_size_bytes)
                field_value_pairs.append(('File Size', file_size_str))

            # 4. File Date (from file system)
            if file_date:
                field_value_pairs.append(('File Date', file_date))

            # 5. EXIF Date (from EXIF data, if available, immediately after File Date)
            if 'EXIF Date' in exif_data:
                exif_date = exif_data['EXIF Date']
                if exif_date:
                    # Escape HTML in values
                    exif_date_str = str(exif_date).replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                    field_value_pairs.append(('EXIF Date', exif_date_str))
                del exif_data['EXIF Date']  # Remove from dict so we don't add it again

            # Build HTML table with EXIF data
            # Priority order: Camera, Orientation, Lens, Location, then Description (if user data), then rest
            # Note: Image Size and EXIF Date are already added above, so we exclude them from priority_order
            priority_order = ['Camera', 'Orientation', 'Lens', 'Location']

            # Add priority fields after File Date/EXIF Date
            for field in priority_order:
                if field in exif_data:
                    value = exif_data[field]
                    if not is_zero(value):
                        # Escape HTML in values
                        value_str = str(value).replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                        value_str = elide_value(value_str)
                        field_value_pairs.append((field, value_str))
                    del exif_data[field]  # Remove from dict so we don't add it again

            # Add remaining EXIF fields (excluding Description)
            description = None
            speakable_plain_text = None
            if 'Description' in exif_data:
                desc = exif_data['Description']
                # Remove null bytes and filter out bytes-like representations
                if isinstance(desc, bytes):
                    try:
                        desc = desc.decode('utf-8', errors='ignore')
                    except Exception:
                        desc = None
                else:
                    desc = str(desc)
                # Remove null bytes
                desc = desc.replace('\x00', '')
                # Skip if it looks like a bytes representation or is empty
                if desc and not (desc.startswith("b'") or desc.startswith('b"')):
                    desc = desc.strip()
                    if desc:
                            try:
                                from imagegen_plugins.image_gen_naming import (
                                    format_user_comment_text_for_display,
                                )

                                desc = format_user_comment_text_for_display(desc)
                            except Exception:
                                pass
                            speakable_plain_text = desc
                            # Escape user/EXIF text so embedded HTML is not interpreted by QTextBrowser;
                            # then newlines and known section prefixes become markup.
                            disp = escape(desc)
                            disp = disp.replace('\n', '<br>')
                            disp = disp.replace('Image Model:<br>', '<h4>Image model</h4>')
                            disp = disp.replace('Prompt:<br>', '<h4>Prompt</h4>')
                            disp = disp.replace('Title:<br>', '<h4>Title</h4>')
                            disp = disp.replace('Description:<br>', '<h4>Description</h4>')
                            disp = re.sub(
                                r'(?i)(^|<br>)References:\s*<br>',
                                r'\1<h4>References</h4>',
                                disp,
                                count=1,
                            )
                            disp = re.sub(
                                r'(?i)(^|<br>)Negative [Pp]rompt:\s*<br>',
                                r'\1<h4>Negative prompt</h4>',
                                disp,
                                count=1,
                            )
                            disp = self._highlight_image_model_elapsed_html(disp)

                            description, _ = self._apply_references_markup(
                                disp, os.path.dirname(current_image_path), current_image_path
                            )
                del exif_data['Description']

            # Add remaining fields, filtering zeros
            for field, value in sorted(exif_data.items()):
                if not is_zero(value):
                    # Escape HTML in values
                    value_str = str(value).replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                    value_str = elide_value(value_str)
                    field_value_pairs.append((field, value_str))

            self._update_overlay_image_model_flag(
                current_image_path, speakable_plain_text
            )

            # Build HTML using shared method
            self._speakable_description = speakable_plain_text
            self._last_overlay_data = {
                'filename': filename,
                'field_value_pairs': field_value_pairs,
                'description': description,
                'speakable_plain_text': speakable_plain_text,
            }
            info_text = self._build_info_overlay_html(
                filename,
                field_value_pairs,
                description,
                speakable_plain_text,
                hovered_anchor=getattr(self, "_hovered_anchor", None),
                show_input_to_active_job_heading=self._should_show_input_to_active_job_heading(),
            )

        except Exception as e:
            # Fallback basic info with error logging
            import traceback
            print(f"Error in show_image_info_overlay: {e}")
            traceback.print_exc()

            # Get file size, directory, and file date
            file_size_bytes = get_file_size_bytes()
            directory_name = get_directory_name()
            file_date = get_file_date()

            # Build field-value pairs for non-EXIF case
            field_value_pairs = []

            # Always add Directory, Image Size, File Size, File Date as the first four lines
            # 1. Directory
            if directory_name:
                directory_escaped = directory_name.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
                directory_escaped = elide_value(directory_escaped)
                field_value_pairs.append(('Directory', directory_escaped))

            # 2. Image Size if available
            if width > 0 and height > 0:
                field_value_pairs.append(('Image Size', f"{width} × {height}"))

            # 3. File Size
            if file_size_bytes is not None and file_size_bytes > 0:
                file_size_str = format_file_size(file_size_bytes)
                field_value_pairs.append(('File Size', file_size_str))

            # 4. File Date (from file system)
            if file_date:
                field_value_pairs.append(('File Date', file_date))

            # Add Scale factor
            if hasattr(self.main_window, 'scale_factor'):
                field_value_pairs.append(('Scale', f"{self.main_window.scale_factor:.2f}x"))

            self._update_overlay_image_model_flag(current_image_path, None)

            # Build HTML using shared method
            self._speakable_description = None
            self._last_overlay_data = {
                'filename': filename,
                'field_value_pairs': field_value_pairs,
                'description': None,
                'speakable_plain_text': None,
            }
            info_text = self._build_info_overlay_html(filename, field_value_pairs)

        # Ensure we have some content
        if not info_text or info_text.strip() == '':
            info_text = f'<div style="color: {self._info_heading_hex()}; font-size: 10px;">{filename}</div>'

        # Display in right sidebar instead of overlay
        if self.info_text_edit:
            self._hovered_anchor = None
            self.info_text_edit.clear()
            self._apply_info_html_to_browser(info_text)
            self._refresh_input_to_active_job_heading()
            self._update_action_nav_state()

    def hide_image_info_overlay(self):
        """Hide image info overlay"""
        if self.info_text_edit:
            self.info_text_edit.hide()
