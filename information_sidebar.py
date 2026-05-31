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
from PySide6.QtCore import QEvent, QObject, Qt, QPoint, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from combined_sidebar_widget import HeaderWidget
from theme_service import get_active_theme
from utils import format_file_size, get_file_extension, styled_message_box
from speech_utils import speak_or_stop
from reference_graph import (
    collect_reference_chain_paths,
    get_reference_entries_for_path,
    parse_reference_entries_from_text,
    resolve_exif_reference_paths,
    resolve_reference_entries_map,
    resolve_reference_path,
)

# Path to trash icon for delete action (inline image in information HTML)
_TRASH_ICON_PATH = os.path.join(os.path.dirname(__file__), "assets", "trash_icon.png")
if os.path.exists(_TRASH_ICON_PATH):
    _trash_url = "file://" + os.path.abspath(_TRASH_ICON_PATH).replace(" ", "%20")
    _DELETE_ICON_HTML = f'<img src="{_trash_url}" width="16" height="16" style="margin:0;padding:0;vertical-align:bottom;">'
else:
    _DELETE_ICON_HTML = "⊘"


class _DeleteUserCommentYesNoTabFilter(QObject):
    """Tab/arrow between Yes/No on the delete-user-comment confirm dialog only."""

    def __init__(self, buttons: List[QPushButton], dialog: QWidget):
        super().__init__(dialog)
        self._buttons = buttons
        self._dialog = dialog

    def eventFilter(self, obj, event):
        if obj is not self._dialog and obj not in self._buttons:
            return False
        if event.type() != QEvent.Type.KeyPress:
            return False
        key = event.key()
        if key == Qt.Key.Key_Tab:
            direction = -1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        elif key == Qt.Key.Key_Backtab:
            direction = -1
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            direction = -1 if key == Qt.Key.Key_Left else 1
        else:
            return False
        focused = QApplication.focusWidget()
        if focused in self._buttons:
            idx = self._buttons.index(focused)
        else:
            idx = -1 if direction > 0 else 0
        self._buttons[(idx + direction) % len(self._buttons)].setFocus(Qt.FocusReason.TabFocusReason)
        return True


def _confirm_delete_user_comment(main_window):
    """Show delete-user-comment confirm; Tab works when opened from the info-panel link."""
    from PySide6.QtWidgets import QMessageBox

    dialog = styled_message_box(
        main_window,
        QMessageBox.Question,
        "Delete User Comment",
        "Delete the EXIF user comment from this image?",
        buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        default_button=QMessageBox.StandardButton.No,
    )
    buttons = sorted(dialog.findChildren(QPushButton), key=lambda b: b.x())
    if len(buttons) >= 2:
        tab_filter = _DeleteUserCommentYesNoTabFilter(buttons, dialog)
        dialog._delete_user_comment_tab_filter = tab_filter
        dialog.installEventFilter(tab_filter)
        for btn in buttons:
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            btn.installEventFilter(tab_filter)

    dialog.activateWindow()
    dialog.raise_()
    for btn in buttons:
        if btn.isDefault():
            btn.setFocus(Qt.FocusReason.TabFocusReason)
            break

    dialog.exec()
    return dialog.result_data.get("button")


class InformationSidebar(QWidget):
    """Widget for displaying image information (EXIF data) in a right sidebar"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.info_text_edit = None
        self.information_header = None
        self._speakable_description = None
        self._reference_level_paths: Optional[List[str]] = None
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

        # Create scrollable text browser for EXIF info (QTextBrowser for link handling)
        self.info_text_edit = QTextBrowser(self)
        self.info_text_edit.setReadOnly(True)
        self.info_text_edit.setOpenExternalLinks(False)
        self.info_text_edit.setOpenLinks(False)
        self.info_text_edit.anchorClicked.connect(self._on_anchor_clicked)
        self.info_text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.info_text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.info_text_edit.setFocusPolicy(Qt.NoFocus)
        vp = self.info_text_edit.viewport()
        vp.setMouseTracking(True)
        vp.installEventFilter(self)
        self._information_viewport = vp
        self.info_text_edit.setStyleSheet(get_active_theme().information_sidebar_textbrowser_stylesheet())
        self.info_text_edit.hide()
        right_sidebar_layout.addWidget(self.info_text_edit)

    def toggle_display(self):
        """Toggle the Information sidebar visibility"""
        if hasattr(self.main_window, 'toggle_information_display'):
            self.main_window.toggle_information_display()

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
        if getattr(self, "_last_overlay_data", None):
            self._refresh_overlay_for_hover(getattr(self, "_hovered_anchor", None))

    # Tooltips for information action links (Qt does not render HTML title attributes)
    CMD_SYMBOL = "⌘"
    ALT_SYMBOL = "⌥"

    _ANCHOR_TOOLTIPS = {
        "speak://": "Read aloud (click again to stop)",
        "copy://": f"Copy to clipboard.\n{ALT_SYMBOL}+click to escape newlines.",
        "edit://": "Edit user comment",
        "create://": "Create an image from text...",
        "editai://": "Edit with AI",
        "delete://": "Delete user comment",
        "reflevel://": (
            "click: Show the reference graph for complete history.\n"
            f"{ALT_SYMBOL}+click: Show only this image and its direct references "
        ),
    }

    _LEGACY_REF_MD5_LINE = re.compile(r"^[0-9a-fA-F]{32}$")
    _REF_FILEDATE_LINE = re.compile(r"^\d+(?:\.\d+)?$")
    _REF_SECTION_STOP = re.compile(
        r"^(?:prompt|image model|title|description):$", re.IGNORECASE
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

    @staticmethod
    def _resolve_reference_path(
        image_dir: str, fname: str, expected_mtime: Optional[float] = None
    ) -> Optional[str]:
        candidates: List[str] = []
        if fname.startswith("~") or os.path.isabs(fname) or "/" in fname:
            try:
                candidates.append(os.path.normpath(os.path.abspath(os.path.expanduser(fname))))
            except (OSError, ValueError):
                pass
        rel = fname[2:] if fname.startswith("./") else fname
        candidates.append(os.path.normpath(os.path.join(image_dir, rel)))
        for cand in candidates:
            if not os.path.isfile(cand):
                continue
            if expected_mtime is not None:
                try:
                    if abs(os.path.getmtime(cand) - expected_mtime) > InformationSidebar._REF_FILEDATE_TOLERANCE_S:
                        continue
                except OSError:
                    continue
            return cand
        return None

    def _resolve_reference_entries_map(
        self,
        image_dir: str,
        current_path: str,
        entries: List[Tuple[str, Optional[float]]],
    ) -> Dict[str, str]:
        """Map reference label (lower) -> resolved file path (filedate match when stored)."""
        resolved: Dict[str, str] = {}
        if not current_path or not os.path.isfile(current_path):
            return resolved
        for fname, expected_mtime in entries:
            key = fname.strip().lower()
            if key in resolved:
                continue
            path = self._resolve_reference_path(image_dir, fname, expected_mtime)
            if path:
                resolved[key] = path
        return resolved

    def _collect_reference_chain_paths(
        self, image_dir: str, root_path: str, entries: List[Tuple[str, Optional[float]]]
    ) -> List[str]:
        """Preorder traversal of EXIF References; skip paths and labels already seen."""
        return collect_reference_chain_paths(image_dir, root_path, entries)

    def _resolve_exif_reference_paths(
        self, image_dir: str, current_path: str, entries: List[Tuple[str, Optional[float]]]
    ) -> Tuple[List[str], Dict[str, str]]:
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
        level_paths, _resolved_map = self._resolve_exif_reference_paths(
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
                    if self._resolve_reference_path(image_dir, fname_raw, None) and len(level_paths) > 1:
                        label = segments[j].strip()
                        new_segments.append(
                            f'<a href="reflevel://" style="color:{accent};text-decoration:underline;">{label}</a>'
                        )
                    else:
                        new_segments.append(segments[j])
                    j += 2
                    continue
            fname_raw = unescape(fn_seg)
            if self._resolve_reference_path(image_dir, fname_raw, None) and len(level_paths) > 1:
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
        return get_active_theme().text_color_hex

    def _info_heading_hex(self) -> str:
        return get_active_theme().heading_color_hex()

    def _imagegen_action_cells(self, hovered_anchor, icon_box, spacer_box) -> str:
        """Optional Create / Edit-with-AI icon cells when imagegen plugins are available."""
        try:
            from imagegen_plugins.image_gen_menu import (
                imagegen_edit_plugins_available,
                imagegen_plugins_available,
            )
        except ImportError:
            return ""
        cells = ""
        if imagegen_plugins_available():
            cells += spacer_box() + icon_box(
                "create://", "◇", "Create an image from text..."
            )
        if imagegen_edit_plugins_available():
            cells += spacer_box() + icon_box("editai://", "✦", "Edit with AI")
        return cells

    def eventFilter(self, obj, event):
        """Show tooltip and red highlight when hovering over information action links."""
        if obj is self._information_viewport:
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint() if hasattr(event, 'position') else event.pos()
                anchor = self.info_text_edit.anchorAt(pos)
                tooltip = self._ANCHOR_TOOLTIPS.get(anchor, "")
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
        if not hasattr(self, '_link_tooltip_label'):
            self._link_tooltip_label = QLabel(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
            self._link_tooltip_label.setStyleSheet(get_active_theme().information_link_tooltip_stylesheet())
        lbl = self._link_tooltip_label
        if text:
            lbl.setText(text)
            lbl.adjustSize()
            pos = QCursor.pos() + QPoint(-12, 12)
            lbl.move(pos)
            lbl.show()
            lbl.raise_()
        else:
            lbl.hide()

    def _on_anchor_clicked(self, url):
        """Handle click on speak/copy/delete links in the information description area."""
        from exif_utils import truncate_usercomment_before_prompt
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
            if option_held:
                paths, _resolved = self._resolve_exif_reference_paths(
                    image_dir, current, entries
                )
                if not paths:
                    return
                config = {"files": paths, "sort_mode": "custom"}
            else:
                paths = self._collect_reference_chain_paths(
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
            text = truncate_usercomment_before_prompt(self._speakable_description or "")
            speak_or_stop(text)
        elif url.toString() == "copy://":
            from PySide6.QtWidgets import QApplication
            raw = self._speakable_description or ""
            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
                prompt_part = truncate_usercomment_before_prompt(raw)
                if prompt_part != raw:
                    text = prompt_part.replace("\n", "\\n").replace(";", ".")
                else:
                    text = raw.replace("\n", "\\n").replace(";", ".")
            else:
                text = raw
            QApplication.clipboard().setText(text)
            self._show_copy_feedback()
        elif url.toString() == "edit://":
            if hasattr(self.main_window, 'edit_exif_usercomment'):
                self.main_window.edit_exif_usercomment()
        elif url.toString() == "create://":
            self._on_create_image_prompt()
        elif url.toString() == "editai://":
            self._on_edit_with_ai()
        elif url.toString() == "delete://":
            self._on_delete_user_comment()

    def _on_create_image_prompt(self):
        """Open Create > Create an image from text..., primed from the user comment."""
        try:
            from imagegen_plugins.image_gen_menu import open_imagegen_create_from_text_dialog
        except ImportError:
            return
        data = getattr(self, "_last_overlay_data", None) or {}
        open_imagegen_create_from_text_dialog(
            self.main_window,
            user_comment=data.get("speakable_plain_text"),
        )

    def _on_edit_with_ai(self):
        """Open AI image edit dialog, primed from the current user comment."""
        try:
            from imagegen_plugins.image_gen_menu import open_imagegen_edit_dialog
        except ImportError:
            return
        data = getattr(self, "_last_overlay_data", None) or {}
        open_imagegen_edit_dialog(
            self.main_window,
            user_comment=data.get("speakable_plain_text"),
        )

    def _show_copy_feedback(self):
        """Show a brief floating '✓ Copied!' label over the information text area."""
        if not self.info_text_edit:
            return
        th = get_active_theme()
        label = QLabel("✓ Copied!", self.info_text_edit)
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {th.information_action_chip_bg_hex};
                color: {th.validation_success_color_hex};
                border: 1px solid {th.validation_success_color_hex};
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11pt;
            }}
        """)
        label.adjustSize()
        label.move(self.info_text_edit.width() - label.width() - 12, 10)
        label.show()
        label.raise_()
        QTimer.singleShot(1500, label.deleteLater)

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

        reply = _confirm_delete_user_comment(self.main_window)
        if reply != QMessageBox.StandardButton.Yes:
            return

        from exif_utils import delete_usercomment_from_file
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

            from exif_utils import get_exif_dict_named_from_image_path

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
                                from exif_utils import decode_usercomment
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

    def _refresh_overlay_for_hover(self, hovered_anchor=None):
        """Rebuild overlay HTML with hovered link highlighted (text and border #50c8ff)."""
        if not hasattr(self, '_last_overlay_data') or not self._last_overlay_data:
            return
        if not self.info_text_edit:
            return
        data = self._last_overlay_data
        info_text = self._build_info_overlay_html(
            data['filename'], data['field_value_pairs'],
            data.get('description'), data.get('speakable_plain_text'),
            hovered_anchor=hovered_anchor
        )
        if info_text:
            self.info_text_edit.blockSignals(True)
            self.info_text_edit.clear()
            doc = self.info_text_edit.document()
            doc.setHtml(info_text.rstrip('\x00'))
            th = get_active_theme()
            doc.setDefaultStyleSheet(
                f"body {{ color: {self._info_text_hex()}; background-color: {th.information_textbrowser_bg_hex}; font-size: 12pt; }}"
            )
            self.info_text_edit.blockSignals(False)
            self.info_text_edit.update()

    def _build_info_overlay_html(self, filename: str, field_value_pairs: list, description: str = None,
                                 speakable_plain_text: str = None, hovered_anchor: str = None) -> str:
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
        heading_hex = self._info_heading_hex()
        html_parts = [f'<div style="color: {text_hex}; font-size: 12pt; font-family: \'Courier New\', Monaco, Menlo; line-height: 1.4;">']
        html_parts.append(f'<div style="font-weight: bold; font-size: 14pt; margin-bottom: 12px; color: {heading_hex};">{filename}</div>')

        # Build 2-column table (Field | Value)
        if field_value_pairs:
            html_parts.append(f'<table style="border: 1px solid {bdr}; border-collapse: collapse; width: 100%;">')

            # One row per field-value pair
            for field, value in field_value_pairs:
                html_parts.append('<tr>')
                html_parts.append(f'<td style="border: 1px solid {bdr}; padding: 4px 4px 4px 2px; text-align: right; color: {text_hex}; white-space: nowrap; width: 1%;">{field}:</td>')
                html_parts.append(f'<td style="border: 1px solid {bdr}; padding: 4px 8px; color: {text_hex};">{value}</td>')
                html_parts.append('</tr>')

            html_parts.append('</table>')

        # Constants for font size and color
        ACTION_ICON_FONT_SIZE = "16px"
        ACTION_ICON_COLOR = _th.information_action_icon_muted_hex
        ACTION_ICON_HOVER_COLOR = getattr(_th, "button_border_hover_hex", _th.accent_color_hex)
        SPEAK_ICON = "꡴"
        COPY_ICON = "⧉"
        EDIT_ICON = "✚"
        DELETE_ICON = _DELETE_ICON_HTML

        # Edit button (always shown); speak/copy/delete only when description is long enough
        # Render each button as a boxed icon using a table with borders on <td>
        def icon_button_anchor(href, icon, title):
            color = ACTION_ICON_HOVER_COLOR if href == hovered_anchor else ACTION_ICON_COLOR
            return (
                f'<a href="{href}" '
                f'style="display:block; color:{color}; text-decoration:none; cursor:pointer; '
                f'font-size:{ACTION_ICON_FONT_SIZE}; line-height:22px;" '
                f'title="{title}">{icon}</a>'
            )

        def icon_box(href, icon, title):
            is_hovered = href == hovered_anchor
            border_color = ACTION_ICON_HOVER_COLOR if is_hovered else _th.information_icon_cell_border_muted_hex
            return (
                f'<td style="border:1px solid {border_color}; border-radius:6px; padding:0 6px; text-align:center;'
                f' background:{_th.information_action_chip_bg_hex}; min-width:26px;">'
                f'{icon_button_anchor(href, icon, title)}'
                f'</td>'
            )

        def spacer_box(width=27):
            # Use 1x1 black GIF (PNG base64 caused libpng IHDR CRC errors in Qt WebEngine)
            return (
                f'<td style="width:{width}px; border:none;">'
                f'&nbsp;&nbsp;'
                f'</td>'
            )

        create_cells = self._imagegen_action_cells(hovered_anchor, icon_box, spacer_box)

        # Table for [SPEAK] [space] [COPY] [space] [EDIT] [space] [CREATE?] [space] [DELETE]
        # If no description, show only EDIT (+ CREATE when imagegen available), else all actions
        if speakable_plain_text and len(speakable_plain_text) > 0:
            action_icons = (
                '<table cellpadding="0" cellspacing="0" style="margin-bottom:3px;"><tr>'
                + icon_box("speak://", SPEAK_ICON, "Read aloud (click again to stop)")
                + spacer_box()
                + icon_box("copy://", COPY_ICON, "Copy to clipboard")
                + spacer_box()
                + icon_box("edit://", EDIT_ICON, "Edit user comment")
                + create_cells
                + spacer_box()
                + icon_box("delete://", DELETE_ICON, "Delete user comment")
                + '</tr></table><br><br>'
            )
        else:
            action_icons = (
                '<table cellpadding="0" cellspacing="0" style="margin-bottom:3px;"><tr>'
                + icon_box("edit://", EDIT_ICON, "Edit user comment")
                + create_cells
                + '</tr></table><br><br>'
            )

        # Add Description if present (as full-width row below table)
        if description:
            description = description.replace('\x00', '')
            if description.strip() and not (description.strip().startswith("b'") or description.strip().startswith('b"')):
                html_parts.append(f'<div style="padding-top: 10px; padding-bottom: 6px; margin-top: 10px; border-top: 1px solid {bdr}; color: {text_hex}; font-size: 12pt;">{action_icons}{description}</div>')
            else:
                html_parts.append(f'<div style="padding-top: 10px; padding-bottom: 6px; margin-top: 10px; border-top: 1px solid {bdr}; color: {text_hex}; font-size: 12pt;">{action_icons}</div>')
        else:
            # No user comment: show edit button so user can add one
            html_parts.append(f'<div style="padding-top: 10px; padding-bottom: 6px; margin-top: 10px; border-top: 1px solid {bdr}; color: {text_hex}; font-size: 12pt;">{action_icons} Add user comment</div>')

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

        # Helper function to get directory name (elided if > 40 characters)
        def get_directory_name():
            directory_name = None
            try:
                directory_path = os.path.dirname(current_image_path)
                if directory_path:
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

            # Build HTML using shared method
            self._speakable_description = speakable_plain_text if (speakable_plain_text and len(speakable_plain_text) > 30) else None
            self._last_overlay_data = {
                'filename': filename,
                'field_value_pairs': field_value_pairs,
                'description': description,
                'speakable_plain_text': speakable_plain_text,
            }
            info_text = self._build_info_overlay_html(filename, field_value_pairs, description, speakable_plain_text)

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
            # Clear any existing content
            self.info_text_edit.clear()
            # Set HTML content directly on the document
            info_text = info_text.rstrip('\x00')
            doc = self.info_text_edit.document()
            doc.setHtml(info_text)
            # Ensure default text color is set
            th = get_active_theme()
            doc.setDefaultStyleSheet(
                f"body {{ color: {self._info_text_hex()}; background-color: {th.information_textbrowser_bg_hex}; font-size: 12pt; }}"
            )
            # Set read-only
            self.info_text_edit.setReadOnly(True)
            # The text edit will fill the sidebar width and scroll internally
            # Set text width based on sidebar width (accounting for padding)
            # Use a QTimer to ensure sidebar width is accurate after layout
            def update_text_width():
                if self.isVisible():
                    sidebar_width = self.width()
                    if sidebar_width > 0:
                        doc.setTextWidth(sidebar_width - 36)  # Account for padding (18px each side)
                elif hasattr(self.main_window, 'right_sidebar_width'):
                    doc.setTextWidth(self.main_window.right_sidebar_width - 36)
                self.info_text_edit.update()
            QTimer.singleShot(0, update_text_width)
            # Also update immediately in case sidebar is already sized
            if self.isVisible():
                sidebar_width = self.width()
                if sidebar_width > 0:
                    doc.setTextWidth(sidebar_width - 36)
            elif hasattr(self.main_window, 'right_sidebar_width'):
                doc.setTextWidth(self.main_window.right_sidebar_width - 36)
            # Update the widget
            self.info_text_edit.update()

    def hide_image_info_overlay(self):
        """Hide image info overlay"""
        if self.info_text_edit:
            self.info_text_edit.hide()
